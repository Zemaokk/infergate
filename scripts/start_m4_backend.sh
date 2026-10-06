#!/usr/bin/env bash
set -euo pipefail

# Run on the leased Linux machine. Model download is a separate preparation step.
work_root="${M4_WORK_ROOT:-/root/infergate-m4}"
model_path="${M4_MODEL_PATH:?Set M4_MODEL_PATH to the downloaded model directory}"
test -f "$model_path/config.json"
test -x "$work_root/vllm-env/bin/vllm"

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export VLLM_NO_USAGE_STATS=1
export DO_NOT_TRACK=1
# Start with V0/eager for compatibility verification, not performance comparison.
export VLLM_USE_V1=0
exec "$work_root/vllm-env/bin/vllm" serve "$model_path" \
  --served-model-name Qwen2.5-7B-Instruct \
  --host 127.0.0.1 --port 8001 \
  --dtype bfloat16 --max-model-len 4096 --max-num-seqs 2 \
  --gpu-memory-utilization 0.85 --enforce-eager --disable-log-requests
