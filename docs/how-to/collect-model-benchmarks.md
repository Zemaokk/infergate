# Collect model benchmarks

This guide collects new measurements; it does not redraw the historical run.
See the [benchmark specification](../reference/benchmarks.md) for success rules
and [methodology](../explanation/benchmark-methodology.md) for interpretation.

Use an x86_64 Linux host with an NVIDIA GPU and driver. Recorded validation used
an RTX 4090 and driver 550.54.14; other environments require fresh kernel and
native-route checks. Copy the repository into a dedicated checkout and run
from its root. Use one model instance, an idle GPU, and an unused port 8002.
Choose an isolated environment rather than stopping an existing service.

Create separate tool, inference, and gateway environments. Installation requires
network access:

```sh
export INFERGATE_GPU_ROOT=/root/infergate-repro
mkdir -p "$INFERGATE_GPU_ROOT"
python3 -m venv "$INFERGATE_GPU_ROOT/tools"
"$INFERGATE_GPU_ROOT/tools/bin/python" -m pip install uv==0.12.2
export PATH="$INFERGATE_GPU_ROOT/tools/bin:$PATH"
uv venv --python 3.12 "$INFERGATE_GPU_ROOT/vllm-env"
uv pip install --python "$INFERGATE_GPU_ROOT/vllm-env/bin/python" --index-url https://download.pytorch.org/whl/cu118 --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --index-strategy unsafe-first-match -r configs/m4/vllm-responses-requirements.txt
uv pip check --python "$INFERGATE_GPU_ROOT/vllm-env/bin/python"
uv sync --locked --no-editable --python 3.13
uv venv --python 3.12 "$INFERGATE_GPU_ROOT/model-tools"
uv pip install --python "$INFERGATE_GPU_ROOT/model-tools/bin/python" --index-url https://pypi.tuna.tsinghua.edu.cn/simple modelscope==1.40.1
export M4_MODEL_PATH="$INFERGATE_GPU_ROOT/models/Qwen2.5-7B-Instruct"
"$INFERGATE_GPU_ROOT/model-tools/bin/python" scripts/download_m4_model.py
```

Weights are approximately 15.2 GB; allow extra download/cache space. The original
download used `master` without recording its revision. For a pinned new run,
select an existing revision and set `M4_MODEL_REVISION` before downloading.
The missing historical revision prevents a byte-identical weight claim;
configuration hashes cannot replace it. The inference requirements pin key
packages, not all transitive dependencies, so record the actual installed set.

Start the model in a separate foreground terminal and retain its log:

```sh
export INFERGATE_GPU_ROOT=/root/infergate-repro
export M4_MODEL_PATH="$INFERGATE_GPU_ROOT/models/Qwen2.5-7B-Instruct"
M43_WORK_ROOT="$INFERGATE_GPU_ROOT" M43_MODEL_PATH="$M4_MODEL_PATH" bash scripts/start_m43_backend.sh > "$INFERGATE_GPU_ROOT/backend.log" 2>&1
```

In another terminal, verify HTTP 200 from `/health`, the served alias in
`/v1/models`, and both native routes in OpenAPI. Check direct nonempty generation
through both Chat and Responses before benchmarking. A Chat-only server does
not satisfy this profile.

From the gateway checkout root, generate a fresh environment record, then run
the pilot and formal profile:

```sh
export INFERGATE_GPU_ROOT=/root/infergate-repro
export M4_MODEL_PATH="$INFERGATE_GPU_ROOT/models/Qwen2.5-7B-Instruct"
export PATH="$INFERGATE_GPU_ROOT/tools/bin:$PATH"
"$INFERGATE_GPU_ROOT/vllm-env/bin/python" - <<'PY' > "$INFERGATE_GPU_ROOT/environment.json"
import hashlib, json, os, platform, subprocess
from importlib.metadata import version
from pathlib import Path
model = Path(os.environ['M4_MODEL_PATH'])
print(json.dumps({
    'platform': platform.platform(),
    'gpu': subprocess.check_output(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'], text=True).strip(),
    'inference_packages': {n: version(n) for n in ('vllm', 'torch', 'transformers', 'openai')},
    'model_path': str(model),
    'model_revision': os.environ.get('M4_MODEL_REVISION', 'master; exact revision unknown'),
    'config_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in model.glob('*.json')},
    'weights_bytes': {p.name: p.stat().st_size for p in model.glob('*.safetensors')},
    'backend_log': str(Path(os.environ['INFERGATE_GPU_ROOT']) / 'backend.log'),
}, indent=2))
PY
uv run --locked --no-editable python -m scripts.m4_benchmark.real --profile pilot --environment "$INFERGATE_GPU_ROOT/environment.json" --output artifacts/m4-benchmark/new-real-pilot
uv run --locked --no-editable python -m scripts.m4_benchmark.real --profile real --environment "$INFERGATE_GPU_ROOT/environment.json" --output artifacts/m4-benchmark/new-real
```

Inspect the original data if the pilot fails; do not continue the formal run.
The collector starts/stops its temporary gateway but leaves the foreground
model server running. Finish with Ctrl-C in the model terminal and verify that
your service exited and released GPU memory. Back up the environment JSON,
backend log, and all output directories before redrawing reports.

Client, gateway, and model communicate over loopback on the GPU host. SSH
tunnels and public-network latency are outside this experiment.
