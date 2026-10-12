#!/usr/bin/env python3
"""Strict structural and leakage audit for the UniQL 80/20 bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SQL_ONLY = re.compile(r"\A```sql\n(?P<sql>[\s\S]*\S)\n```\Z", re.IGNORECASE)
FORBIDDEN_TEST_FIELDS = {"gold_sql", "ground_truth_sql", "sql", "SQL"}


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fail(message: str) -> None:
    raise ValueError(message)


def audit_record_common(row: dict[str, Any], dialect: str, schemas: dict[str, str]) -> None:
    qid = int(row["question_id"])
    if row["sample_id"] != f"{qid}:{dialect}":
        fail(f"sample_id mismatch for qid={qid}, dialect={dialect}")
    if row["target_dialect"] != dialect:
        fail(f"target_dialect mismatch for qid={qid}: {row['target_dialect']}")
    if row["prompt"] != row["messages"][0]["content"]:
        fail(f"prompt/messages mismatch for {row['sample_id']}")
    db_id = row["db_id"]
    schema = schemas[db_id]
    if schema not in row["prompt"]:
        fail(f"full schema is absent or altered for {row['sample_id']}")
    if row["schema_sha256"] != sha256_text(schema):
        fail(f"schema hash mismatch for {row['sample_id']}")
    if row["schema_chars"] != len(schema):
        fail(f"schema length mismatch for {row['sample_id']}")
    if "analysis" in {message["role"] for message in row["messages"]}:
        fail(f"trajectory-like analysis message found for {row['sample_id']}")


def main() -> None:
    experiment_dir = Path(__file__).resolve().parents[1]
    repo_dir = experiment_dir.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=experiment_dir / "artifacts/bundle")
    parser.add_argument("--config", type=Path, default=experiment_dir / "config/experiment.json")
    parser.add_argument("--schema-dir", type=Path, default=repo_dir / "data/schemas")
    parser.add_argument("--report", type=Path, default=experiment_dir / "artifacts/data_smoke_report.json")
    args = parser.parse_args()

    config = read_json(args.config)
    split = read_json(args.bundle / "split.json")
    dialects = list(config["all_dialects"])
    train_ids = list(map(int, split["train_ids"]))
    test_ids = list(map(int, split["test_ids"]))
    train_set, test_set = set(train_ids), set(test_ids)
    if len(train_ids) != 1227 or len(test_ids) != 307:
        fail(f"unexpected split sizes: {len(train_ids)}/{len(test_ids)}")
    if train_set & test_set or len(train_set | test_set) != 1534:
        fail("intent split is not a disjoint partition of 1534 IDs")

    schema_by_dialect = {
        dialect: read_json(args.schema_dir / f"{dialect}_schema.json")
        for dialect in dialects
    }

    training_specs = {
        "sqlite_only.jsonl": 1227,
        "joint_balanced.jsonl": 1227,
        "joint16_full.jsonl": 1227 * 16,
    }
    training_rows: dict[str, list[dict[str, Any]]] = {}
    for filename, expected_count in training_specs.items():
        path = args.bundle / "train" / filename
        rows = read_jsonl(path)
        training_rows[filename] = rows
        if len(rows) != expected_count:
            fail(f"{filename}: rows={len(rows)} expected={expected_count}")
        for row in rows:
            qid = int(row["question_id"])
            dialect = row["target_dialect"]
            if qid not in train_set:
                fail(f"test intent leaked into {filename}: {qid}")
            if dialect not in dialects:
                fail(f"unknown training dialect: {dialect}")
            if len(row["messages"]) != 2:
                fail(f"training record does not have user+assistant: {row['sample_id']}")
            if [m["role"] for m in row["messages"]] != ["user", "assistant"]:
                fail(f"invalid roles for {row['sample_id']}")
            target = row["messages"][1]["content"]
            match = SQL_ONLY.fullmatch(target)
            if not match or match.group("sql").strip() != row["gold_sql"].strip():
                fail(f"assistant target is not SQL-only for {row['sample_id']}")
            audit_record_common(row, dialect, schema_by_dialect[dialect])

    sqlite_rows = training_rows["sqlite_only.jsonl"]
    if {int(row["question_id"]) for row in sqlite_rows} != train_set:
        fail("sqlite_only does not cover every train intent exactly once")
    if {row["target_dialect"] for row in sqlite_rows} != {"sqlite"}:
        fail("sqlite_only contains a non-SQLite target")

    balanced_rows = training_rows["joint_balanced.jsonl"]
    if {int(row["question_id"]) for row in balanced_rows} != train_set:
        fail("joint_balanced does not cover every train intent exactly once")
    balanced_counts = Counter(row["target_dialect"] for row in balanced_rows)
    if set(balanced_counts) != set(dialects) or max(balanced_counts.values()) - min(balanced_counts.values()) > 1:
        fail(f"joint_balanced is not dialect-balanced: {balanced_counts}")

    full_rows = training_rows["joint16_full.jsonl"]
    full_by_qid: dict[int, set[str]] = defaultdict(set)
    for row in full_rows:
        full_by_qid[int(row["question_id"])].add(row["target_dialect"])
    if set(full_by_qid) != train_set or any(values != set(dialects) for values in full_by_qid.values()):
        fail("joint16_full does not contain all 16 dialects exactly once per train intent")

    inference_schema_examples: dict[int, dict[str, str]] = defaultdict(dict)
    for dialect in dialects:
        path = args.bundle / "inference" / f"{dialect}.jsonl"
        rows = read_jsonl(path)
        if len(rows) != 307 or {int(row["question_id"]) for row in rows} != test_set:
            fail(f"{dialect} inference IDs/count mismatch")
        for row in rows:
            forbidden = FORBIDDEN_TEST_FIELDS & set(row)
            if forbidden:
                fail(f"gold-like fields in inference {row['sample_id']}: {sorted(forbidden)}")
            if len(row["messages"]) != 1 or row["messages"][0]["role"] != "user":
                fail(f"inference row must contain only a user message: {row['sample_id']}")
            audit_record_common(row, dialect, schema_by_dialect[dialect])
            inference_schema_examples[int(row["question_id"])][dialect] = row["schema_sha256"]

    # At least one aligned intent must expose dialect-specific schema differences.
    if not any(len(set(hashes.values())) > 1 for hashes in inference_schema_examples.values()):
        fail("dialect-specific schema injection was not observable")

    summary = {
        "status": "passed",
        "train_intents": len(train_set),
        "test_intents": len(test_set),
        "training_rows": {name: len(rows) for name, rows in training_rows.items()},
        "inference_files": len(dialects),
        "inference_rows_total": len(dialects) * len(test_set),
        "joint_balanced_dialect_counts": dict(sorted(balanced_counts.items())),
        "checks": [
            "intent-level train/test disjointness",
            "all-dialect aligned test coverage",
            "full per-dialect schema embedded verbatim",
            "SQL-only assistant targets",
            "no gold labels in inference exports",
            "SQLite-only and equal-budget joint controls",
        ],
    }
    write_json(args.report, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
