#!/usr/bin/env bash
set -euo pipefail

EXPERIMENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${UNIQL_MODEL_PATH:?Set UNIQL_MODEL_PATH to the local Qwen3-8B checkpoint}"
: "${UNIQL_RUN_ROOT:?Set UNIQL_RUN_ROOT to a writable training directory}"

VARIANT="${1:?Usage: run_ddp_training.sh sqlite_only|joint_balanced|joint16_full [seed] [num_gpus]}"
SEED="${2:-42}"
NUM_GPUS="${3:-4}"
case "${VARIANT}" in
  sqlite_only|joint_balanced|joint16_full) ;;
  *) echo "Unknown variant: ${VARIANT}" >&2; exit 2 ;;
esac
case "${NUM_GPUS}" in
  1) DEFAULT_DEVICES="0"; GRAD_ACCUM=16 ;;
  2) DEFAULT_DEVICES="0,1"; GRAD_ACCUM=8 ;;
  4) DEFAULT_DEVICES="0,1,2,3"; GRAD_ACCUM=4 ;;
  *) echo "num_gpus must be 1, 2, or 4 to preserve effective batch size 16" >&2; exit 2 ;;
esac

TRAIN_PYTHON="${UNIQL_TRAIN_PYTHON:-python}"
EPOCHS="${UNIQL_EPOCHS:-3}"
CHECKPOINT_SAVE_STEPS="${UNIQL_CHECKPOINT_SAVE_STEPS:-250}"
CUDA_DEVICES="${UNIQL_CUDA_DEVICES:-${DEFAULT_DEVICES}}"
RUN_ID="qwen3-8b-${VARIANT}-s${SEED}"
BUNDLE_DIR="${EXPERIMENT_DIR}/artifacts/bundle"

mkdir -p "${UNIQL_RUN_ROOT}/adapters" "${UNIQL_RUN_ROOT}/checkpoints" "${UNIQL_RUN_ROOT}/logs" "${UNIQL_RUN_ROOT}/cache" "${UNIQL_RUN_ROOT}/tmp"
export CUDA_VISIBLE_DEVICES="${CUDA_DEVICES}"
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
export TOKENIZERS_PARALLELISM=false
export HF_HOME="${UNIQL_RUN_ROOT}/cache/huggingface"
export TORCH_HOME="${UNIQL_RUN_ROOT}/cache/torch"
export TMPDIR="${UNIQL_RUN_ROOT}/tmp"

"${TRAIN_PYTHON}" -m torch.distributed.run \
  --standalone \
  --nproc_per_node "${NUM_GPUS}" \
  "${EXPERIMENT_DIR}/scripts/train_lora.py" \
  --input "${BUNDLE_DIR}/train/${VARIANT}.jsonl" \
  --run-id "${RUN_ID}" \
  --model "${UNIQL_MODEL_PATH}" \
  --adapter-dir "${UNIQL_RUN_ROOT}/adapters/${RUN_ID}" \
  --checkpoint-dir "${UNIQL_RUN_ROOT}/checkpoints/${RUN_ID}" \
  --metrics-file "${UNIQL_RUN_ROOT}/logs/${RUN_ID}_train.json" \
  --max-length 4096 \
  --epochs "${EPOCHS}" \
  --learning-rate 1e-4 \
  --warmup-ratio 0.03 \
  --per-device-batch-size 1 \
  --gradient-accumulation-steps "${GRAD_ACCUM}" \
  --precision fp16 \
  --fp16-initial-scale 256 \
  --load-directly-to-gpu \
  --seed "${SEED}" \
  --checkpoint-save-steps "${CHECKPOINT_SAVE_STEPS}" \
  --resume-from-checkpoint \
  --save-checkpoint \
  2>&1 | tee "${UNIQL_RUN_ROOT}/logs/${RUN_ID}_ddp${NUM_GPUS}_train.log"
