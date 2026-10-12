#!/usr/bin/env python3
"""Convert portable held-out JSONL predictions to the public evaluation/evaluate.py JSON format."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


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


def case_insensitive_value(row: dict[str, Any], wanted: str) -> Any:
    for key, value in row.items():
        if key.lower() == wanted.lower():
            return value
    raise KeyError(f"Missing {wanted!r}; available fields={list(row)}")


def extract_sql(response: str) -> str:
    blocks = re.findall(r"```sql\s*(.*?)\s*```", response or "", re.IGNORECASE | re.DOTALL)
    return blocks[-1].strip() if blocks else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".incomplete")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(temporary, path)


def main() -> None:
    experiment_dir = Path(__file__).resolve().parents[1]
    repo_dir = experiment_dir.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions-root", type=Path, default=experiment_dir / "returned_predictions")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--data-dir", type=Path, default=repo_dir / "data/queries")
    parser.add_argument("--split", type=Path, default=experiment_dir / "artifacts/bundle/split.json")
    parser.add_argument("--dialects", nargs="+")
    args = parser.parse_args()

    config = read_json(experiment_dir / "config/experiment.json")
    dialects = args.dialects or config["all_dialects"]
    test_ids = [int(value) for value in read_json(args.split)["test_ids"]]
    expected = set(test_ids)
    output_dir = args.output_dir or repo_dir / "results" / args.run_id
    manifest: dict[str, Any] = {
        "format": "UniQL evaluation/evaluate.py predicted_sql_path",
        "run_id": args.run_id,
        "test_rows_per_dialect": len(test_ids),
        "files": {},
    }

    for dialect in dialects:
        prediction_path = args.predictions_root / args.run_id / f"{dialect}.jsonl"
        predictions = read_jsonl(prediction_path)
        by_id: dict[int, dict[str, Any]] = {}
        for row in predictions:
            qid = int(row["question_id"])
            if qid in by_id:
                raise ValueError(f"Duplicate question_id={qid} in {prediction_path}")
            if row.get("run_id") != args.run_id or row.get("target_dialect") != dialect:
                raise ValueError(f"Run/dialect mismatch for question_id={qid} in {prediction_path}")
            by_id[qid] = row
        if set(by_id) != expected:
            raise ValueError(
                f"Coverage mismatch for {prediction_path}: expected={len(expected)}, "
                f"found={len(by_id)}, missing={sorted(expected - set(by_id))[:10]}"
            )

        # Read the current dialect reference file from the public benchmark.
        source_name = dialect
        source_rows = {int(row["question_id"]): row for row in read_json(args.data_dir / f"{source_name}.json")}
        converted = []
        empty_sql = 0
        for qid in test_ids:
            prediction = by_id[qid]
            source = source_rows[qid]
            sql = (prediction.get("pred_sql") or extract_sql(prediction.get("response", ""))).strip()
            empty_sql += int(not sql)
            if prediction["db_id"] != source["db_id"]:
                raise ValueError(f"db_id mismatch for {dialect} question_id={qid}")
            # Preserve the public evaluator input fields and construction-stage labels.
            converted.append({
                "question_id": qid,
                "db_id": source["db_id"],
                "pred_sqls": [sql],
                "ground_truth_sql": case_insensitive_value(source, f"SQL-{dialect}"),
                "difficulty": source["difficulty"],
                "annotation_source": source.get("annotation_source", "unknown"),
            })

        destination = output_dir / f"{dialect}_pred_sql.json"
        atomic_json(destination, converted)
        manifest["files"][dialect] = {
            "path": str(destination.resolve()),
            "rows": len(converted),
            "empty_sql": empty_sql,
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
        }
        print(json.dumps({"dialect": dialect, **manifest["files"][dialect]}, ensure_ascii=False))

    manifest_path = output_dir / "legacy_results_manifest.json"
    atomic_json(manifest_path, manifest)
    print(json.dumps({"status": "complete", "manifest": str(manifest_path.resolve())}, indent=2))


if __name__ == "__main__":
    main()
