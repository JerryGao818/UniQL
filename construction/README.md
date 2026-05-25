# UniQL Construction Pipeline

This directory contains the SQL construction pipeline used to produce target-dialect annotations from the SQLite source queries. The pipeline combines deterministic translation, model-assisted repair, execution validation, iterative rule refinement, and human validation.

## Pipeline Overview

1. `main.py` orchestrates translation, validation, retry, and result writing.
2. `translator.py` calls the configured LLM backend for direct translation or repair.
3. `validator.py` executes translated SQL against the target database and compares results.
4. `rule_optimizer.py` summarizes recurring failures into dialect-specific refinement rules.
5. `db_manager.py` centralizes target-database connection handling.
6. `prompts/` and `rules/` store prompt templates and dialect rules.

The final benchmark files expose the construction stage through `annotation_source` for target dialects:

| Value | Meaning |
|---|---|
| `glot` | Accepted from SQLGlot-based translation. |
| `LLM-0shot` | Produced by direct LLM translation. |
| `LLM-retry` | Produced after bounded reflection with execution feedback. |
| `LLM-rule` | Produced after iterative rule refinement. |
| `human` | Human validated or human rewritten. |

## Usage

Configure database credentials and model settings in `config.py`, then run the pipeline for a target dialect:

```bash
python main.py --source sqlite --target postgresql --workers 5 --iteration 3
```

Common arguments:

| Argument | Description |
|---|---|
| `--source` | Source dialect, normally `sqlite`. |
| `--target` | Target dialect, such as `mysql`, `postgresql`, `oracle`, or `hive`. |
| `--workers` | Number of parallel validation workers. |
| `--iteration` | Number of rule-refinement iterations. |
| `--limit` | Optional example limit for debugging. |

The construction pipeline requires live target databases and executable source data. Update paths, credentials, ports, and driver settings for your local environment before running it.
