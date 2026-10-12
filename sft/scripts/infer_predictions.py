#!/usr/bin/env python3
"""Generate portable all-dialect predictions with vLLM and optional LoRA."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer
from vllm import LLM, SamplingParams
from vllm.lora.request import LoRARequest


DIALECTS = (
    "sqlite", "clickhouse", "doris", "drill", "druid", "duckdb", "hive",
    "mysql", "oracle", "postgresql", "presto", "spark", "starrocks",
    "mssql", "teradata", "trino",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
    return rows


def extract_sql(response: str) -> str:
    blocks = re.findall(r"```sql\s*(.*?)\s*```", response or "", flags=re.IGNORECASE | re.DOTALL)
    return blocks[-1].strip() if blocks else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report-file", type=Path, required=True)
    parser.add_argument("--dialects", nargs="+", default=list(DIALECTS))
    parser.add_argument("--max-new-tokens", type=int, default=768)
    parser.add_argument("--max-model-len", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.88)
    parser.add_argument("--dtype", choices=("bfloat16", "float16"), default="float16")
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip dialect files that already exist; the caller must run validate_predictions.py afterwards.",
    )
    args = parser.parse_args()

    if not args.model.exists():
        raise FileNotFoundError(args.model)
    if args.adapter is not None and not (args.adapter / "adapter_config.json").exists():
        raise FileNotFoundError(f"Invalid adapter directory: {args.adapter}")
    unknown = sorted(set(args.dialects) - set(DIALECTS))
    if unknown:
        raise ValueError(f"Unknown dialects: {unknown}")

    run_dir = args.output_root / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    existing = [dialect for dialect in args.dialects if (run_dir / f"{dialect}.jsonl").exists()]
    if existing and not (args.resume or args.overwrite):
        raise FileExistsError(
            f"Existing prediction files for {existing}; pass --resume to keep them or --overwrite to replace them"
        )
    dialects_to_generate = [
        dialect for dialect in args.dialects
        if args.overwrite or not (run_dir / f"{dialect}.jsonl").exists()
    ]
    if not dialects_to_generate:
        write_json(args.report_file, {
            "status": "complete",
            "run_id": args.run_id,
            "resumed": True,
            "skipped_existing_dialects": existing,
        })
        print(json.dumps({"status": "nothing_to_generate", "skipped": existing}, indent=2))
        return

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    tokenizer = AutoTokenizer.from_pretrained(
        args.model, local_files_only=True, trust_remote_code=True
    )
    tokenizer.padding_side = "left"

    rows_by_dialect: dict[str, list[dict[str, Any]]] = {}
    prompts_by_dialect: dict[str, list[str]] = {}
    prompt_lengths: dict[str, list[int]] = {}
    for dialect in dialects_to_generate:
        rows = read_jsonl(args.input_dir / f"{dialect}.jsonl")
        if args.max_rows is not None:
            rows = rows[:args.max_rows]
        prompts = [tokenizer.apply_chat_template(
            row["messages"], tokenize=False, add_generation_prompt=True,
            enable_thinking=False,
        ) for row in rows]
        lengths = [len(tokenizer(prompt, add_special_tokens=False).input_ids) for prompt in prompts]
        if max(lengths) + args.max_new_tokens > args.max_model_len:
            raise ValueError(
                f"{dialect}: max prompt {max(lengths)} + generation {args.max_new_tokens} "
                f"exceeds max_model_len {args.max_model_len}; refusing to truncate full schema"
            )
        rows_by_dialect[dialect] = rows
        prompts_by_dialect[dialect] = prompts
        prompt_lengths[dialect] = lengths

    llm_args: dict[str, Any] = {
        "model": str(args.model),
        "tokenizer": str(args.model),
        "trust_remote_code": True,
        "tensor_parallel_size": 1,
        "dtype": args.dtype,
        "max_model_len": args.max_model_len,
        "gpu_memory_utilization": args.gpu_memory_utilization,
        "swap_space": 0,
        "seed": args.seed,
    }
    if args.adapter is not None:
        llm_args.update({"enable_lora": True, "max_lora_rank": 16, "max_loras": 1})
    llm = LLM(**llm_args)
    lora_request = None
    if args.adapter is not None:
        lora_request = LoRARequest(
            lora_name=args.run_id,
            lora_int_id=1,
            lora_path=str(args.adapter),
            base_model_name=str(args.model),
        )
    sampling = SamplingParams(
        n=1, temperature=0.0, max_tokens=args.max_new_tokens, seed=args.seed
    )

    report: dict[str, Any] = {
        "run_id": args.run_id,
        "model": str(args.model.resolve()),
        "adapter": str(args.adapter.resolve()) if args.adapter else None,
        "generation": {
            "temperature": 0.0,
            "max_new_tokens": args.max_new_tokens,
            "max_model_len": args.max_model_len,
            "enable_thinking": False,
            "dtype": args.dtype,
            "seed": args.seed,
        },
        "files": {},
        "resumed": args.resume,
        "skipped_existing_dialects": existing if args.resume else [],
    }
    for dialect in dialects_to_generate:
        destination = run_dir / f"{dialect}.jsonl"
        started = time.time()
        outputs = llm.generate(
            prompts_by_dialect[dialect], sampling,
            lora_request=lora_request, use_tqdm=True,
        )
        if len(outputs) != len(rows_by_dialect[dialect]):
            raise RuntimeError(f"Output count mismatch for {dialect}")
        temporary = destination.with_suffix(".jsonl.incomplete")
        empty_sql = 0
        with temporary.open("w", encoding="utf-8") as handle:
            for row, output in zip(rows_by_dialect[dialect], outputs):
                response = output.outputs[0].text
                pred_sql = extract_sql(response)
                empty_sql += int(not pred_sql)
                handle.write(json.dumps({
                    "run_id": args.run_id,
                    "sample_id": row["sample_id"],
                    "question_id": int(row["question_id"]),
                    "db_id": row["db_id"],
                    "target_dialect": dialect,
                    "response": response,
                    "pred_sql": pred_sql,
                    "model_path": str(args.model),
                    "adapter_path": str(args.adapter) if args.adapter else None,
                }, ensure_ascii=False) + "\n")
        os.replace(temporary, destination)
        report["files"][dialect] = {
            "path": str(destination.resolve()),
            "rows": len(rows_by_dialect[dialect]),
            "empty_sql": empty_sql,
            "prompt_tokens_max": max(prompt_lengths[dialect]),
            "elapsed_seconds": time.time() - started,
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
        }
        write_json(args.report_file, report)
        print(json.dumps({"dialect": dialect, **report["files"][dialect]}, indent=2), flush=True)
    report["status"] = "complete"
    write_json(args.report_file, report)


if __name__ == "__main__":
    main()
