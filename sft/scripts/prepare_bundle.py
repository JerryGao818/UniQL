#!/usr/bin/env python3
"""Build the intent-disjoint 80/20 UniQL SFT and inference bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DIALECTS = (
    "sqlite", "clickhouse", "doris", "drill", "druid", "duckdb", "hive",
    "mysql", "oracle", "postgresql", "presto", "spark", "starrocks",
    "mssql", "teradata", "trino",
)

DISPLAY_NAMES = {
    "sqlite": "SQLite",
    "clickhouse": "ClickHouse",
    "doris": "Doris",
    "drill": "Apache Drill",
    "druid": "Apache Druid",
    "duckdb": "DuckDB",
    "hive": "Apache Hive",
    "mysql": "MySQL",
    "oracle": "Oracle",
    "postgresql": "PostgreSQL",
    "presto": "Presto",
    "spark": "Spark SQL",
    "starrocks": "StarRocks",
    "mssql": "T-SQL",
    "teradata": "Teradata",
    "trino": "Trino",
}


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def sha256_bytes(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_case_insensitive(row: dict[str, Any], wanted_key: str) -> str:
    wanted = wanted_key.lower()
    for key, value in row.items():
        if key.lower() == wanted:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Empty or invalid value in {wanted_key}")
            return value.strip()
    raise KeyError(f"Missing {wanted_key!r}; available fields={list(row)}")


def load_dialect_rows(data_dir: Path, dialect: str) -> list[dict[str, Any]]:
    # SQLite has its own source file in the public data layout.
    source_name = dialect
    rows = read_json(data_dir / f"{source_name}.json")
    if not isinstance(rows, list) or len(rows) != 1534:
        raise ValueError(f"Expected 1534 rows for {dialect}, found {len(rows)}")
    return rows


def allocate_stratified_train_ids(
    rows: list[dict[str, Any]], train_size: int, seed: int
) -> list[int]:
    """Largest-remainder allocation within (db_id, difficulty) strata."""
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in rows:
        groups[(row["db_id"], row["difficulty"])].append(int(row["question_id"]))

    exact = {key: len(ids) * train_size / len(rows) for key, ids in groups.items()}
    allocation = {key: int(value) for key, value in exact.items()}
    remaining = train_size - sum(allocation.values())
    ranked = sorted(groups, key=lambda key: (-(exact[key] - allocation[key]), key))
    for key in ranked[:remaining]:
        allocation[key] += 1

    selected: list[int] = []
    for key in sorted(groups):
        ids = sorted(groups[key])
        key_seed = seed + int(hashlib.sha256(repr(key).encode()).hexdigest()[:8], 16)
        random.Random(key_seed).shuffle(ids)
        selected.extend(ids[:allocation[key]])
    if len(selected) != train_size or len(set(selected)) != train_size:
        raise AssertionError("Stratified allocation failed")
    return sorted(selected)


def balanced_dialect_assignment(
    train_ids: list[int], dialects: list[str], seed: int
) -> dict[int, str]:
    shuffled = list(train_ids)
    random.Random(seed + 80020).shuffle(shuffled)
    assignment = {qid: dialects[index % len(dialects)] for index, qid in enumerate(shuffled)}
    counts = Counter(assignment.values())
    if max(counts.values()) - min(counts.values()) > 1:
        raise AssertionError(f"Unbalanced dialect assignment: {counts}")
    return assignment


def render_prompt(template: str, schema_text: str, row: dict[str, Any], dialect: str) -> str:
    # Preserve the complete schema string from schema/<dialect>_schema.json verbatim.
    return template.format(
        dialect=DISPLAY_NAMES[dialect],
        db_details=schema_text,
        question=row["question"],
        evidence=row.get("evidence", "") or "None provided.",
    )


def make_record(
    row: dict[str, Any],
    dialect: str,
    schema_text: str,
    schema_source: Path,
    template: str,
    include_gold: bool,
) -> dict[str, Any]:
    qid = int(row["question_id"])
    prompt = render_prompt(template, schema_text, row, dialect)
    record: dict[str, Any] = {
        "sample_id": f"{qid}:{dialect}",
        "question_id": qid,
        "db_id": row["db_id"],
        "target_dialect": dialect,
        "difficulty": row["difficulty"],
        "annotation_source": row.get("annotation_source", "unknown"),
        "schema_source": str(schema_source),
        "schema_sha256": sha256_bytes(schema_text),
        "schema_chars": len(schema_text),
        "prompt": prompt,
        "messages": [{"role": "user", "content": prompt}],
    }
    if include_gold:
        gold_sql = value_case_insensitive(row, f"SQL-{dialect}")
        record["gold_sql"] = gold_sql
        # There is no trajectory supervision: the only supervised content is SQL.
        record["messages"].append(
            {"role": "assistant", "content": f"```sql\n{gold_sql}\n```"}
        )
    return record


def main() -> None:
    experiment_dir = Path(__file__).resolve().parents[1]
    repo_dir = experiment_dir.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=experiment_dir / "config/experiment.json")
    parser.add_argument("--data-dir", type=Path, default=repo_dir / "data/queries")
    parser.add_argument("--schema-dir", type=Path, default=repo_dir / "data/schemas")
    parser.add_argument("--template", type=Path, default=experiment_dir / "config/prompt_template.txt")
    parser.add_argument("--locked-split", type=Path, default=experiment_dir / "splits/seed42.json")
    parser.add_argument("--output-dir", type=Path, default=experiment_dir / "artifacts/bundle")
    args = parser.parse_args()

    config = read_json(args.config)
    dialects = list(config["all_dialects"])
    if tuple(dialects) != DIALECTS:
        raise ValueError(f"Dialect list/order must be exactly {DIALECTS}")
    if config["train_size"] + config["test_size"] != 1534:
        raise ValueError("train_size + test_size must equal 1534")
    template = args.template.read_text(encoding="utf-8")

    dialect_rows = {d: load_dialect_rows(args.data_dir, d) for d in dialects}
    reference = dialect_rows["sqlite"]
    reference_keys = [
        (int(r["question_id"]), r["db_id"], r["question"], r["difficulty"])
        for r in reference
    ]
    for dialect, rows in dialect_rows.items():
        keys = [
            (int(r["question_id"]), r["db_id"], r["question"], r["difficulty"])
            for r in rows
        ]
        if keys != reference_keys:
            raise ValueError(f"Intent alignment/order mismatch for {dialect}")

    schemas: dict[str, dict[str, str]] = {}
    schema_sources: dict[str, Path] = {}
    for dialect in dialects:
        source = args.schema_dir / f"{dialect}_schema.json"
        schema = read_json(source)
        if set(schema) != {r["db_id"] for r in reference}:
            raise ValueError(f"Schema database coverage mismatch for {dialect}")
        if any(not isinstance(value, str) or not value.strip() for value in schema.values()):
            raise ValueError(f"Invalid full schema entry for {dialect}")
        schemas[dialect] = schema
        schema_sources[dialect] = source.resolve()

    train_ids = allocate_stratified_train_ids(
        reference, int(config["train_size"]), int(config["split_seed"])
    )
    train_set = set(train_ids)
    test_ids = sorted(int(r["question_id"]) for r in reference if int(r["question_id"]) not in train_set)
    if len(test_ids) != config["test_size"]:
        raise AssertionError("Unexpected test size")
    locked = read_json(args.locked_split)
    if train_ids != locked["train_ids"] or test_ids != locked["test_ids"]:
        raise ValueError("Generated intent split differs from the released seed-42 split")
    balanced = balanced_dialect_assignment(train_ids, dialects, int(config["split_seed"]))

    row_by_dialect_id = {
        dialect: {int(row["question_id"]): row for row in rows}
        for dialect, rows in dialect_rows.items()
    }

    def record(qid: int, dialect: str, include_gold: bool) -> dict[str, Any]:
        row = row_by_dialect_id[dialect][qid]
        return make_record(
            row,
            dialect,
            schemas[dialect][row["db_id"]],
            schema_sources[dialect],
            template,
            include_gold,
        )

    sqlite_rows = [record(qid, "sqlite", True) for qid in train_ids]
    balanced_rows = [record(qid, balanced[qid], True) for qid in train_ids]
    joint_rows = [record(qid, dialect, True) for qid in train_ids for dialect in dialects]

    counts: dict[str, int] = {}
    counts["train/sqlite_only.jsonl"] = write_jsonl(
        args.output_dir / "train/sqlite_only.jsonl", sqlite_rows
    )
    counts["train/joint_balanced.jsonl"] = write_jsonl(
        args.output_dir / "train/joint_balanced.jsonl", balanced_rows
    )
    counts["train/joint16_full.jsonl"] = write_jsonl(
        args.output_dir / "train/joint16_full.jsonl", joint_rows
    )
    for dialect in dialects:
        rows = [record(qid, dialect, False) for qid in test_ids]
        relative = f"inference/{dialect}.jsonl"
        counts[relative] = write_jsonl(args.output_dir / relative, rows)

    split = {
        "experiment_id": config["experiment_id"],
        "seed": config["split_seed"],
        "strategy": "intent-level stratified by (db_id, difficulty)",
        "train_ids": train_ids,
        "test_ids": test_ids,
        "train_count": len(train_ids),
        "test_count": len(test_ids),
        "balanced_dialect_counts": dict(sorted(Counter(balanced.values()).items())),
    }
    write_json(args.output_dir / "split.json", split)

    manifest: dict[str, Any] = {
        "experiment_id": config["experiment_id"],
        "format_version": 1,
        "config_sha256": sha256_file(args.config),
        "prompt_template_sha256": sha256_file(args.template),
        "split_sha256": sha256_file(args.output_dir / "split.json"),
        "files": {},
        "schema_files": {},
        "query_files": {d: {"sha256": sha256_file(args.data_dir / f"{d}.json"), "rows": len(dialect_rows[d])} for d in dialects},
        "invariants": [
            "Train and test are disjoint at natural-language intent/question_id level.",
            "All 16 test dialects use the same 307 held-out intent IDs.",
            "Each prompt embeds the complete dialect- and db_id-specific schema string.",
            "SFT assistant targets contain only one fenced SQL block and no trajectory.",
            "Inference exports contain no gold SQL or assistant message.",
        ],
    }
    for relative, count in sorted(counts.items()):
        path = args.output_dir / relative
        manifest["files"][relative] = {
            "rows": count,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    for dialect, source in schema_sources.items():
        manifest["schema_files"][dialect] = {
            "path": str(source),
            "sha256": sha256_file(source),
            "databases": len(schemas[dialect]),
        }
    write_json(args.output_dir / "manifest.json", manifest)
    print(json.dumps({
        "status": "prepared",
        "output_dir": str(args.output_dir.resolve()),
        "train": len(train_ids),
        "test": len(test_ids),
        "counts": counts,
    }, indent=2))


if __name__ == "__main__":
    main()
