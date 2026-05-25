# UniQL

**UniQL** is a human-verified executable benchmark for cross-dialect text-to-SQL evaluation. UniQL extends the BIRD development split from SQLite to a controlled multi-dialect setting: the same 1,534 natural-language intents are aligned with executable SQL annotations across 16 SQL dialects, yielding 24,544 dialect-specific queries.

The artifact contains the minimum code and data needed to inspect the benchmark, run open-weight model inference, evaluate generated SQL under dialect-specific execution protocols, and reproduce the core construction pipeline components used for database migration and SQL translation.

## What Is UniQL

Most text-to-SQL benchmarks evaluate models on a single SQL dialect, usually SQLite. In practice, SQL engines differ in syntax, built-in functions, type systems, ordering behavior, duplicate semantics, implicit casts, and execution semantics. A query that is correct in SQLite may fail or produce different results in PostgreSQL, Hive, Trino, Druid, Teradata, or other engines.

UniQL is designed to isolate this cross-dialect generalization problem. It keeps the natural-language questions, schemas, and database contents aligned across dialects, so model performance differences reflect dialect transfer rather than unrelated task or schema changes.

Supported dialects:

`SQLite`, `ClickHouse`, `Doris`, `Drill`, `Druid`, `DuckDB`, `Hive`, `MySQL`, `Oracle`, `PostgreSQL`, `Presto`, `Spark`, `StarRocks`, `Teradata`, `Trino`, and `T-SQL`.

## Repository Layout

```text
UniQL-DialectBench/
  data/
    queries/                  # SQLite source queries and constructed target-dialect task files
    schemas/                  # Dialect-specific schema descriptions
  inference/
    infer_open_source.py       # vLLM-based inference for open-weight models
    infer_open_source_compact.py
    infer_dinsql_zero_shot.py  # DIN-SQL-style zero-shot prompting baseline
  evaluation/
    evaluate.py                # Main executable evaluation entry point
    evaluate_server.py         # Server-side evaluation variant
    *_eval.py                  # Dialect-specific evaluators
  migration/
    clickhouse/
    doris/
    drill/
    druid/
    duckdb/
    hive/
    mysql/
    oracle/
    postgresql/
    presto/
    spark/
    starrocks/
    t_sql/
    teradata/
    trino/
    source_bird/               # Source BIRD metadata used by migration scripts
  construction/
    main.py                    # Hybrid SQL translation pipeline
    translator.py
    validator.py
    rule_optimizer.py
    db_manager.py
    prompts/
    rules/
```

## Data Format

Each file under `data/queries/` is a list of examples for one SQL dialect. The important fields are:

| Field | Description |
|---|---|
| `question_id` | Example identifier inherited from the aligned BIRD split. |
| `db_id` | Database identifier. |
| `question` | Natural-language question. |
| `evidence` | Optional evidence/hint text from the source data. |
| `difficulty` | Original BIRD difficulty label: `simple`, `moderate`, or `challenging`. |
| `SQL-*` | Dialect-specific reference SQL field. The exact suffix follows the dialect naming convention used by the construction scripts. |
| `annotation_source` | Construction stage for target-dialect SQL annotations. This field is intentionally absent from `sqlite.json`, which is the source dialect. |

For constructed target dialects, `annotation_source` can take:

| Value | Meaning |
|---|---|
| `glot` | Accepted from the tool-based SQLGlot translation stage. |
| `LLM-0shot` | Produced by direct LLM translation. |
| `LLM-retry` | Produced after bounded self-reflection with execution feedback. |
| `LLM-rule` | Produced after iterative rule evolution/refinement. |
| `human` | Human validated or human rewritten. |

## Installation

Create a Python environment and install the packages required by the inference and evaluation scripts. Exact database drivers depend on which dialects you evaluate.

```bash
conda create -n uniql python=3.10
conda activate uniql
pip install -r requirements.txt
```

For open-weight model inference with vLLM, install a CUDA-compatible vLLM build following the official vLLM instructions for your system.

## Running Open-Weight Model Inference

Example: run a Qwen model on Hive examples.

```bash
python inference/infer_open_source.py \
  --model Qwen3-8B \
  --pretrained_model_name_or_path /path/to/Qwen3-8B \
  --input_file data/queries/hive.json \
  --schema_dir data/schemas \
  --dialect Hive \
  --output_file results/Qwen3-8B \
  --tensor_parallel_size 4 \
  --temperature 0
```

For a quick prompt-building check without loading a model:

```bash
python inference/infer_open_source.py \
  --input_file data/queries/mysql.json \
  --schema_dir data/schemas \
  --dialect mysql \
  --dry_run
```

The inference scripts preserve `annotation_source` in their prediction outputs so that stratified analysis by construction stage remains possible.

## Executable Evaluation

The main evaluator compares predicted SQL against the dialect-specific reference SQL by executing both queries and comparing their outputs under the UniQL protocol. The protocol is stricter than unordered set comparison: it preserves ordering when order is semantically required and treats duplicate multiplicities conservatively.

Example:

```bash
python evaluation/evaluate.py \
  --predicted_sql_path results/Qwen3-8B/hive_pred_sql.json \
  --dialect hive \
  --model Qwen3-8B \
  --output_dir evaluation_results
```

Dialect-specific evaluators live in `evaluation/*_eval.py`. They handle connection details, query execution, and result normalization for each database system.

## Database Migration and Construction

The `migration/` directory contains database-specific scripts and configuration files for loading the source BIRD databases into target systems. It covers ClickHouse, Doris, Drill, Druid, DuckDB, Hive, MySQL, Oracle, PostgreSQL, Presto, Spark, StarRocks, T-SQL, Teradata, and Trino, with Docker/environment files where those services were run locally.

The `construction/` directory contains the hybrid SQL translation pipeline:

1. tool-based translation,
2. LLM-based translation,
3. execution-based validation,
4. self-reflection with feedback,
5. iterative rule evolution,
6. human validation for unresolved or ambiguous cases.

The construction pipeline uses prompt templates in `construction/prompts/` and dialect rules in `construction/rules/`.

## Notes on Reproducibility

UniQL evaluation requires live database backends for executable accuracy. Some dialects need local Docker services, external database servers, or vendor-specific drivers. The repository includes code and configuration used by the project, but users should adapt connection parameters, credentials, ports, and filesystem paths to their own environments before running migration or evaluation.

## Intended Use and Upstream Artifacts

UniQL is intended for research on text-to-SQL, executable semantic parsing, SQL dialect transfer, and benchmark analysis. The benchmark extends the BIRD development split by preserving the original natural-language questions, evidence, database contents, and SQLite references while adding aligned SQL annotations for additional SQL dialects.

Our use of upstream artifacts is limited to benchmark construction and research evaluation. The derived dialect annotations, schemas, migration scripts, and evaluation code are intended to remain compatible with the original research-oriented access conditions of the upstream data. In particular, derivatives of data obtained for research purposes should be used for research, reproducibility, and non-commercial academic evaluation unless the upstream licenses and access terms explicitly allow broader use.

Users should not treat UniQL as a source of production database content, personally actionable information, or commercial training data without independently verifying that such use is permitted by the upstream datasets and any applicable database, driver, or model licenses. If users redistribute modified versions of UniQL, they should preserve this intended-use notice and document any additional upstream artifacts they incorporate.

## License

The benchmark artifact contains both source code and benchmark data, which may be subject to different licensing considerations.

- Code in `inference/`, `evaluation/`, `migration/`, and `construction/` is intended to be released under a permissive open-source license.
- Benchmark examples, schema metadata, and dialect-specific SQL annotations in `data/` are intended for research use and should be redistributed consistently with the license terms of the underlying BIRD dataset and any other upstream resources.
- Users are responsible for checking the licenses of external database systems, drivers, model checkpoints, and upstream datasets before redistribution or commercial use.

Before archival release, we recommend adding an explicit repository-level `LICENSE` file and, if needed, separate notices for code and data.


