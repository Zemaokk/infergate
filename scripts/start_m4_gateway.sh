#!/usr/bin/env bash
set -euo pipefail
work_root="${M4_WORK_ROOT:-/root/infergate-m4}"
cd "$work_root/gateway"
export INFERGATE_MODEL_NAME=Qwen2.5-7B-Instruct
export INFERGATE_BACKEND_COUNT=1
export INFERGATE_BACKEND_A_URL=http://127.0.0.1:8001
# Deliberately unused in single-backend mode; it must not be validated or probed.
export INFERGATE_BACKEND_B_URL=""
exec .venv/bin/uvicorn infergate.runtime:app --host 127.0.0.1 --port 8000 \
  --workers 1 --log-config configs/logging.json
