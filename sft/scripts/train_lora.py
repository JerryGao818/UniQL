#!/usr/bin/env python3
"""Train one Qwen3-8B LoRA adapter with assistant-only SQL loss."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
import transformers
from peft import LoraConfig, get_peft_model
from torch.utils.data import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, set_seed


TARGET_MODULES = (
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
    if not rows:
        raise ValueError(f"No rows found in {path}")
    return rows


class TokenizedSFTDataset(Dataset):
    def __init__(self, rows: list[dict[str, Any]], tokenizer, max_length: int):
        self.examples: list[dict[str, list[int]]] = []
        self.full_lengths: list[int] = []
        self.target_lengths: list[int] = []
        for index, row in enumerate(rows):
            messages = row.get("messages")
            if not isinstance(messages, list) or len(messages) != 2:
                raise ValueError(f"row {index}: expected user+assistant messages")
            if [message.get("role") for message in messages] != ["user", "assistant"]:
                raise ValueError(f"row {index}: invalid roles")
            assistant = messages[1].get("content", "")
            if not assistant.startswith("```sql\n") or not assistant.endswith("\n```"):
                raise ValueError(f"row {index}: assistant target must be one fenced SQL block")

            full_ids = tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=False,
                enable_thinking=False,
            )
            prefix_ids = tokenizer.apply_chat_template(
                messages[:1], tokenize=True, add_generation_prompt=True,
                enable_thinking=False,
            )
            if full_ids[:len(prefix_ids)] != prefix_ids:
                raise ValueError(f"row {index} {row.get('sample_id')}: chat prefix mismatch")
            if len(full_ids) > max_length:
                raise ValueError(
                    f"row {index} {row.get('sample_id')}: {len(full_ids)} tokens exceeds "
                    f"max_length={max_length}; refusing to truncate the full schema or SQL"
                )
            target_ids = full_ids[len(prefix_ids):]
            if len(target_ids) <= 1:
                raise ValueError(f"row {index}: empty assistant target")
            self.examples.append({
                "input_ids": full_ids,
                "attention_mask": [1] * len(full_ids),
                "labels": [-100] * len(prefix_ids) + target_ids,
            })
            self.full_lengths.append(len(full_ids))
            self.target_lengths.append(len(target_ids))

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> dict[str, list[int]]:
        return self.examples[index]


@dataclass
class DynamicCausalCollator:
    pad_token_id: int
    pad_to_multiple_of: int = 8

    def __call__(self, features: list[dict[str, list[int]]]) -> dict[str, torch.Tensor]:
        longest = max(len(item["input_ids"]) for item in features)
        padded = ((longest + self.pad_to_multiple_of - 1) // self.pad_to_multiple_of) * self.pad_to_multiple_of
        batch = {"input_ids": [], "attention_mask": [], "labels": []}
        for item in features:
            count = padded - len(item["input_ids"])
            batch["input_ids"].append(item["input_ids"] + [self.pad_token_id] * count)
            batch["attention_mask"].append(item["attention_mask"] + [0] * count)
            batch["labels"].append(item["labels"] + [-100] * count)
        return {key: torch.tensor(value, dtype=torch.long) for key, value in batch.items()}


def percentile(values: list[int], fraction: float) -> int:
    values = sorted(values)
    return values[min(int(len(values) * fraction), len(values) - 1)]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--adapter-dir", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--metrics-file", type=Path, required=True)
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--warmup-ratio", type=float, default=0.03)
    parser.add_argument("--per-device-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=16)
    parser.add_argument(
        "--dataloader-num-workers",
        type=int,
        default=0,
        help="Keep at 0 on memory-constrained multi-GPU nodes; tokenization is already done in memory.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--precision", choices=("auto", "bf16", "fp16"), default="fp16")
    parser.add_argument("--fp16-initial-scale", type=float, default=256.0)
    parser.add_argument(
        "--load-directly-to-gpu",
        action="store_true",
        help="Stream checkpoint shards to this rank's GPU to avoid one full CPU model copy per DDP rank.",
    )
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--sample-strategy", choices=("first", "longest_prompt"), default="first")
    parser.add_argument("--max-steps", type=int, default=-1)
    parser.add_argument("--save-checkpoint", action="store_true")
    parser.add_argument(
        "--checkpoint-save-steps",
        type=int,
        default=0,
        help="When positive, save a rolling checkpoint every N optimizer steps instead of once per epoch.",
    )
    parser.add_argument(
        "--resume-from-checkpoint",
        action="store_true",
        help="Resume from the highest complete checkpoint-* directory when present.",
    )
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for Qwen3-8B LoRA training")
    if args.precision == "bf16" and not torch.cuda.is_bf16_supported():
        raise RuntimeError("--precision bf16 was requested, but this GPU does not support bf16")
    use_bf16 = args.precision == "bf16" or (
        args.precision == "auto" and torch.cuda.is_bf16_supported()
    )
    precision = "bf16" if use_bf16 else "fp16"
    model_dtype = torch.bfloat16 if use_bf16 else torch.float16
    for path, label in ((args.model, "model"), (args.input, "input")):
        if not path.exists():
            raise FileNotFoundError(f"Missing {label}: {path}")
    if args.adapter_dir.exists() and any(args.adapter_dir.iterdir()):
        raise FileExistsError(f"Adapter directory is not empty: {args.adapter_dir}")
    args.adapter_dir.mkdir(parents=True, exist_ok=True)
    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    args.metrics_file.parent.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    set_seed(args.seed)
    rows = read_jsonl(args.input)
    if args.max_samples is not None:
        if args.sample_strategy == "longest_prompt":
            rows = sorted(rows, key=lambda row: len(row.get("prompt", "")), reverse=True)
        rows = rows[:args.max_samples]

    tokenizer = AutoTokenizer.from_pretrained(
        args.model, local_files_only=True, trust_remote_code=True
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    dataset = TokenizedSFTDataset(rows, tokenizer, args.max_length)
    audit = {
        "rows": len(dataset),
        "full_tokens": {
            "min": min(dataset.full_lengths),
            "p50": percentile(dataset.full_lengths, 0.50),
            "p95": percentile(dataset.full_lengths, 0.95),
            "max": max(dataset.full_lengths),
        },
        "target_tokens": {
            "min": min(dataset.target_lengths),
            "p50": percentile(dataset.target_lengths, 0.50),
            "p95": percentile(dataset.target_lengths, 0.95),
            "max": max(dataset.target_lengths),
        },
        "assistant_only_loss": True,
        "enable_thinking": False,
    }
    print(json.dumps({"tokenization_audit": audit}, indent=2), flush=True)

    model_load_kwargs: dict[str, Any] = {
        "local_files_only": True,
        "trust_remote_code": True,
        "torch_dtype": model_dtype,
        "attn_implementation": "sdpa",
        "low_cpu_mem_usage": True,
    }
    if args.load_directly_to_gpu:
        local_rank = int(os.environ.get("LOCAL_RANK", "0"))
        torch.cuda.set_device(local_rank)
        model_load_kwargs["device_map"] = {"": local_rank}
    model = AutoModelForCausalLM.from_pretrained(args.model, **model_load_kwargs)
    model.config.use_cache = False
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=list(TARGET_MODULES),
    ))
    trainable, total = model.get_nb_trainable_parameters()
    model.print_trainable_parameters()

    training_args = TrainingArguments(
        output_dir=str(args.checkpoint_dir),
        overwrite_output_dir=False,
        do_train=True,
        eval_strategy="no",
        per_device_train_batch_size=args.per_device_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        lr_scheduler_type="linear",
        warmup_ratio=args.warmup_ratio,
        weight_decay=0.0,
        max_grad_norm=1.0,
        logging_strategy="steps",
        logging_steps=1,
        logging_first_step=True,
        save_strategy=(
            "steps" if args.save_checkpoint and args.checkpoint_save_steps > 0
            else "epoch" if args.save_checkpoint else "no"
        ),
        save_steps=args.checkpoint_save_steps if args.checkpoint_save_steps > 0 else 500,
        save_total_limit=1,
        save_safetensors=True,
        bf16=use_bf16,
        fp16=not use_bf16,
        tf32=False,
        seed=args.seed,
        data_seed=args.seed,
        dataloader_num_workers=args.dataloader_num_workers,
        dataloader_pin_memory=True,
        remove_unused_columns=False,
        report_to="none",
        ddp_find_unused_parameters=False,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="adamw_torch",
        include_num_input_tokens_seen=True,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=DynamicCausalCollator(tokenizer.pad_token_id),
        processing_class=tokenizer,
    )
    if not use_bf16 and trainer.accelerator.scaler is not None:
        # The default 65536 scale overflowed Qwen3-8B LoRA gradients on V100.
        # Set this before GradScaler's first lazy initialization.
        trainer.accelerator.scaler._init_scale = args.fp16_initial_scale
    resume_checkpoint = None
    if args.resume_from_checkpoint:
        candidates = []
        for path in args.checkpoint_dir.glob("checkpoint-*"):
            try:
                step = int(path.name.rsplit("-", 1)[1])
            except (IndexError, ValueError):
                continue
            required = (path / "trainer_state.json", path / "optimizer.pt")
            has_model = (path / "adapter_model.safetensors").is_file() or (path / "pytorch_model.bin").is_file()
            if all(item.is_file() for item in required) and has_model:
                candidates.append((step, path))
        if candidates:
            resume_checkpoint = str(max(candidates)[1])
            print(json.dumps({"resume_from_checkpoint": resume_checkpoint}), flush=True)
    started = time.time()
    result = trainer.train(resume_from_checkpoint=resume_checkpoint)
    elapsed = time.time() - started
    trainer.save_model(str(args.adapter_dir))
    if trainer.is_world_process_zero():
        tokenizer.save_pretrained(args.adapter_dir)
        metadata = {
            "run_id": args.run_id,
            "input": str(args.input.resolve()),
            "model": str(args.model.resolve()),
            "adapter_dir": str(args.adapter_dir.resolve()),
            "seed": args.seed,
            "training": {
                "epochs": args.epochs,
                "learning_rate": args.learning_rate,
                "warmup_ratio": args.warmup_ratio,
                "per_device_batch_size": args.per_device_batch_size,
                "gradient_accumulation_steps": args.gradient_accumulation_steps,
                "dataloader_num_workers": args.dataloader_num_workers,
                "world_size": int(os.environ.get("WORLD_SIZE", "1")),
                "effective_batch_size": args.per_device_batch_size * args.gradient_accumulation_steps * int(os.environ.get("WORLD_SIZE", "1")),
                "max_length": args.max_length,
                "max_steps_override": args.max_steps,
                "checkpoint_save_steps": args.checkpoint_save_steps,
                "precision": precision,
                "fp16_initial_scale": args.fp16_initial_scale if not use_bf16 else None,
                "load_directly_to_gpu": args.load_directly_to_gpu,
                "assistant_only_loss": True,
                "enable_thinking": False,
                "lora": {"rank": 16, "alpha": 32, "dropout": 0.05, "target_modules": list(TARGET_MODULES)},
            },
            "tokenization_audit": audit,
            "parameters": {"trainable": trainable, "total": total, "trainable_fraction": trainable / total},
            "train_metrics": result.metrics,
            "log_history": trainer.state.log_history,
            "elapsed_seconds": elapsed,
            "resumed_from_checkpoint": resume_checkpoint,
            "peak_cuda_memory": {
                "allocated_bytes": torch.cuda.max_memory_allocated(),
                "reserved_bytes": torch.cuda.max_memory_reserved(),
            },
            "environment": {
                "python": sys.version,
                "platform": platform.platform(),
                "torch": torch.__version__,
                "transformers": transformers.__version__,
                "cuda": torch.version.cuda,
                "gpu": torch.cuda.get_device_name(0),
            },
        }
        write_json(args.metrics_file, metadata)
        write_json(args.adapter_dir / "training_metadata.json", metadata)
        print(json.dumps({"status": "complete", "run_id": args.run_id, "train_loss": result.metrics.get("train_loss"), "elapsed_seconds": elapsed}, indent=2), flush=True)


if __name__ == "__main__":
    main()
