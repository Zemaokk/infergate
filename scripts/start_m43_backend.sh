#!/usr/bin/env bash
set -euo pipefail
work_root="${M43_WORK_ROOT:-/root/infergate-m43}"
model_path="${M43_MODEL_PATH:-/root/shared-nvme/infergate-m4/models/Qwen2.5-7B-Instruct}"
test -f "$model_path/config.json"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1
export VLLM_USE_V1=1 VLLM_ENABLE_RESPONSES_API_STORE=0
exec "$work_root/vllm-env/bin/vllm" serve "$model_path" \
  --served-model-name Qwen2.5-7B-Instruct --host 127.0.0.1 --port 8002 \
  --dtype bfloat16 --max-model-len 4096 --max-num-seqs 2 \
  --gpu-memory-utilization 0.85 --enforce-eager
