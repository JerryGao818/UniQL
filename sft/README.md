# Qwen3-8B LoRA supervision-transfer experiment

This directory contains the portable training and inference components of the UniQL SFT experiment. It reads the benchmark from `data/queries/` and full dialect-specific schemas from `data/schemas/`.

## Protocol

- Split by `question_id`, stratified by `(db_id, difficulty)`: 1,227 training intents and 307 held-out intents, seed 42. The released IDs are in `splits/seed42.json`.
- Keep all dialect realizations of an intent in the same partition. All 16 dialects use the same test IDs.
- Include the complete schema for the target dialect and database in each prompt.
- Disable Qwen3 thinking in training and inference. Supervise only the assistant's final fenced SQL block; mask user tokens with label `-100`.
- Compare the unchanged base checkpoint with three LoRA adapters under the same direct-SQL inference protocol.

| Training variant | Paper name | Training examples |
|---|---|---:|
| `sqlite_only` | SQLite-only | 1,227 |
| `joint_balanced` | Balanced-16 | 1,227 |
| `joint16_full` | Full-16 | 19,632 |

Balanced-16 assigns one dialect target to each training intent, with dialect counts differing by at most one. Full-16 uses all 16 translations of every training intent. The latter has 16 times more examples, so its gains also reflect training volume.

Frozen training settings: 3 epochs, learning rate `1e-4`, warmup ratio `0.03`, effective batch size 16, sequence length 4,096, and LoRA rank/alpha/dropout `16/32/0.05` on all attention and MLP projection layers. Training uses fp16 with an initial loss scale of 256. The epoch count was selected from a training-loss pilot before examining held-out EX. Inference uses temperature 0 and at most 768 new tokens.

Data preparation uses the reference annotations in the current checkout and records their hashes. Dataset revisions can affect reproduced EX; the intent split and training settings remain fixed.

## Environments

Use a CUDA-capable machine and a local Qwen3-8B checkpoint. Training and vLLM inference use separate dependency sets, matching the experiment environments:

```bash
pip install -r sft/requirements-train.txt
# In the inference environment:
pip install -r sft/requirements-infer.txt
```

The repository's root requirements provide the database drivers for execution evaluation. Set environment variables to the Python executables for the two GPU environments:

```bash
export UNIQL_MODEL_PATH=/path/to/Qwen3-8B
export UNIQL_RUN_ROOT=/path/to/writable/sft_runs
export UNIQL_TRAIN_PYTHON=/path/to/train/env/bin/python
export UNIQL_INFER_PYTHON=/path/to/infer/env/bin/python
```

## Prepare and validate data

Run from the repository root:

```bash
python sft/scripts/prepare_bundle.py
python sft/scripts/validate_bundle.py
```

The generated `sft/artifacts/bundle/` contains the three training JSONL files, 16 inference JSONL files, the fixed split, and a hash manifest. Inference records contain only the user message and omit gold SQL.

## Train three adapters

```bash
bash sft/scripts/run_training.sh sqlite_only 42 4
bash sft/scripts/run_training.sh joint_balanced 42 4
bash sft/scripts/run_training.sh joint16_full 42 4
```

The final argument is the GPU count. The wrapper supports 1, 2, or 4 GPUs and adjusts gradient accumulation to preserve global batch size 16. It saves rolling checkpoints and resumes interrupted training; a completed nonempty adapter directory is protected from overwriting. Outputs live under `$UNIQL_RUN_ROOT`.

## Infer and validate

```bash
bash sft/scripts/run_inference.sh qwen3-8b-base base
bash sft/scripts/run_inference.sh qwen3-8b-sqlite_only-s42
bash sft/scripts/run_inference.sh qwen3-8b-joint_balanced-s42
bash sft/scripts/run_inference.sh qwen3-8b-joint16_full-s42
```

Inference runs the 16 dialects sequentially on one GPU (`UNIQL_GPU_ID`, default 0). Completed dialect files are reused and checked for all 307 held-out IDs. Predictions are written to `sft/returned_predictions/<run_id>/`. Empty or malformed generations remain failures rather than being dropped.

## Export and execute

```bash
python sft/scripts/export_predictions.py --run-id qwen3-8b-sqlite_only-s42
python evaluation/evaluate.py \
  --predicted_sql_path results/qwen3-8b-sqlite_only-s42/hive_pred_sql.json \
  --dialect hive --model qwen3-8b-sqlite_only-s42 \
  --output_dir evaluation_results
```

Repeat export and evaluation for the base and other adapters, across all dialects. The export joins predictions to the current reference files by `question_id` and preserves `annotation_source`. SQLite evaluation additionally requires `--db_root_path /path/to/BIRD/dev_databases`; other dialects require their configured database services.

Report mean EX over the 15 non-SQLite targets for supervision transfer, alongside SQLite EX and the per-dialect scores. Compare against the matched base run produced here, since reasoning-enabled inference uses a different protocol.
