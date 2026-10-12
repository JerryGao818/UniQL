#!/usr/bin/env bash
set -euo pipefail

EXPERIMENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${UNIQL_MODEL_PATH:?Set UNIQL_MODEL_PATH to the local Qwen3-8B checkpoint}"
: "${UNIQL_RUN_ROOT:?Set UNIQL_RUN_ROOT to the training run root}"

RUN_ID="${1:?Usage: run_formal_inference.sh RUN_ID [base|ADAPTER_PATH]}"
ADAPTER_SPEC="${2:-${UNIQL_RUN_ROOT}/adapters/${RUN_ID}}"
INFER_PYTHON="${UNIQL_INFER_PYTHON:-python}"
VALIDATE_PYTHON="${UNIQL_VALIDATE_PYTHON:-python}"
GPU_ID="${UNIQL_GPU_ID:-0}"
ADAPTER_ARGS=()
if [[ "${ADAPTER_SPEC}" != "base" ]]; then
  ADAPTER_ARGS=(--adapter "${ADAPTER_SPEC}")
fi

mkdir -p "${UNIQL_RUN_ROOT}/logs" "${EXPERIMENT_DIR}/returned_predictions"
CUDA_VISIBLE_DEVICES="${GPU_ID}" "${INFER_PYTHON}" "${EXPERIMENT_DIR}/scripts/infer_predictions.py" \
  --run-id "${RUN_ID}" \
  --model "${UNIQL_MODEL_PATH}" \
  "${ADAPTER_ARGS[@]}" \
  --input-dir "${EXPERIMENT_DIR}/artifacts/bundle/inference" \
  --output-root "${EXPERIMENT_DIR}/returned_predictions" \
  --report-file "${UNIQL_RUN_ROOT}/logs/${RUN_ID}_inference.json" \
  --max-new-tokens 768 \
  --max-model-len 4096 \
  --dtype float16 \
  --seed 42 \
  --resume \
  2>&1 | tee "${UNIQL_RUN_ROOT}/logs/${RUN_ID}_inference.log"

"${VALIDATE_PYTHON}" "${EXPERIMENT_DIR}/scripts/validate_predictions.py" \
  --predictions-root "${EXPERIMENT_DIR}/returned_predictions" \
  --run-id "${RUN_ID}" \
  --allow-empty-sql
