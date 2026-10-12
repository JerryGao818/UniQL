#!/usr/bin/env python3
"""Validate portable prediction files against the locked 80/20 test split."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


FORBIDDEN_GOLD_FIELDS = {"gold_sql", "ground_truth_sql", "sql", "SQL"}


def read_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
    return rows


def extract_sql(response: str) -> str:
    blocks = re.findall(r"```sql\s*(.*?)\s*```", response or "", flags=re.IGNORECASE | re.DOTALL)
    return blocks[-1].strip() if blocks else ""


def main() -> None:
    experiment_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=experiment_dir / "artifacts/bundle")
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dialects", nargs="+")
    parser.add_argument("--expected-limit", type=int)
    parser.add_argument("--allow-empty-sql", action="store_true")
    args = parser.parse_args()

    config = read_json(experiment_dir / "config/experiment.json")
    split = read_json(args.bundle / "split.json")
    dialects = args.dialects or config["all_dialects"]
    expected_ids = list(map(int, split["test_ids"]))
    if args.expected_limit is not None:
        expected_ids = expected_ids[:args.expected_limit]
    expected_set = set(expected_ids)
    errors = []
    total_empty = 0

    for dialect in dialects:
        inputs = {
            int(row["question_id"]): row
            for row in read_jsonl(args.bundle / f"inference/{dialect}.jsonl")
            if int(row["question_id"]) in expected_set
        }
        path = args.predictions_root / args.run_id / f"{dialect}.jsonl"
        if not path.exists():
            errors.append(f"missing {path}")
            continue
        rows = read_jsonl(path)
        seen = set()
        for index, row in enumerate(rows, 1):
            forbidden = FORBIDDEN_GOLD_FIELDS & set(row)
            if forbidden:
                errors.append(f"{path}:{index}: forbidden fields {sorted(forbidden)}")
            qid = int(row.get("question_id", -1))
            if row.get("run_id") != args.run_id:
                errors.append(f"{path}:{index}: run_id mismatch")
            if row.get("target_dialect") != dialect:
                errors.append(f"{path}:{index}: dialect mismatch")
            if row.get("sample_id") != f"{qid}:{dialect}":
                errors.append(f"{path}:{index}: sample_id mismatch")
            if qid not in expected_set:
                errors.append(f"{path}:{index}: unexpected qid={qid}")
            elif row.get("db_id") != inputs[qid]["db_id"]:
                errors.append(f"{path}:{index}: db_id mismatch")
            if qid in seen:
                errors.append(f"{path}:{index}: duplicate qid={qid}")
            seen.add(qid)
            parsed = extract_sql(row.get("response", ""))
            if parsed != row.get("pred_sql", ""):
                errors.append(f"{path}:{index}: pred_sql extraction mismatch")
            total_empty += int(not parsed)
        if len(rows) != len(expected_ids) or seen != expected_set:
            errors.append(f"{path}: coverage mismatch rows={len(rows)} unique={len(seen)}")

    if total_empty and not args.allow_empty_sql:
        errors.append(f"{total_empty} predictions have no complete fenced SQL")
    if errors:
        raise SystemExit("Prediction validation failed:\n- " + "\n- ".join(errors[:50]))
    print(json.dumps({
        "status": "passed",
        "run_id": args.run_id,
        "dialects": dialects,
        "rows": len(expected_ids) * len(dialects),
        "empty_sql": total_empty,
    }, indent=2))


if __name__ == "__main__":
    main()
