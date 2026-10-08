# Verification and reproduction

[Documentation index](README.md) · [Usage](USAGE.md) · [Benchmark results](BENCHMARKS.md)

Run commands from the repository root. The gateway uses Python 3.13; real GPU
inference uses an independent Python 3.12 environment. Save new verification
outputs separately from dated evidence. Reproduction makes procedures and
records inspectable; it does not promise identical performance or image bytes.

| Task | Requirements | What it establishes |
| --- | --- | --- |
| Run tests and controlled HTTP checks | Python; Docker for packaging/observation checks | Behavior of the code under test |
| Redraw saved measurements | Python and a separate matplotlib environment; no GPU | Report regeneration from recorded data |
| Collect new local measurements | Free loopback ports and stable local load | A new controlled mock experiment |
| Collect new model measurements | Dedicated Linux NVIDIA GPU environment | A new real-model experiment in that environment |

## 1. Verify the gateway

After installing uv 0.12.2:

```sh
uv sync --locked --no-editable
uv run --locked --no-editable python -m pytest -q
```

`--locked` prevents silent lockfile changes. Non-editable installation matches
the packaging approach. Record the actual Python patch version. Native startup,
request examples, and runtime configuration are in [Usage](USAGE.md).
Container verification requires Docker Engine/Compose:

```sh
docker compose config --quiet
uv run --locked --no-editable python scripts/verify_m4.py --output /tmp/infergate-packaging-new.json
```

The script builds an image, starts its own three containers, checks UID and
installation location, routing, SSE, stop/recovery, and all-backend rejection,
then saves evidence and removes its containers/network. Port 8000 must be free.
It refuses to reuse an existing project; `--project` selects a different name.

For rate limits, concurrency, and fallback over actual loopback HTTP:

```sh
uv run --locked --no-editable python scripts/verify_m2.py --output /tmp/infergate-m2-new.json
```

Ports 8000–8002 must be free. The observation stack is separate from application
Compose; setup and cleanup are in the [stack guide](../observability/README.md).

## 2. Redraw saved data without a GPU

Verify the two portable archives first. Use `shasum` on macOS or `sha256sum`
on Linux:

```sh
shasum -a 256 -c docs/M4/evidence/SHA256SUMS
```

Use a clean checkout without these existing evidence directories. The temporary
plotting environment and report output directories below should also be fresh;
choose new paths when repeating the procedure.

```sh
mkdir -p artifacts/m4-benchmark/remote-20261007
tar -xzf docs/M4/evidence/benchmark-local-2026-10-07.tar.gz -C artifacts/m4-benchmark
tar -xzf docs/M4/evidence/benchmark-real-2026-10-07.tar.gz -C artifacts/m4-benchmark/remote-20261007
uv venv --python 3.13 /tmp/infergate-plot
uv pip install --python /tmp/infergate-plot/bin/python matplotlib==3.11.2
MPLCONFIGDIR=/tmp/infergate-mpl /tmp/infergate-plot/bin/python -m scripts.m4_benchmark.report artifacts/m4-benchmark/20261007-local-retry-01 --output /tmp/infergate-local-report
MPLCONFIGDIR=/tmp/infergate-mpl /tmp/infergate-plot/bin/python -m scripts.m4_benchmark.real_report artifacts/m4-benchmark/remote-20261007/real-01 --output /tmp/infergate-real-report
```

Plotting dependencies stay separate from the gateway environment. Reports
contain Markdown, PNG/SVG, and input hashes. The local archive includes both
original and replacement cases; preserve both directories. The real archive also
includes two pilots, environment records, startup logs, and cleanup evidence.

Absolute paths and source snapshots in historical manifests describe the
original machine. They are not paths to reuse on a new machine. The original
local report's statement that real-model measurements were still pending is a
dated snapshot; the subsequent [real-model report](M4/benchmark-real-20261007/RESULTS.md)
is separate.

## 3. Collect new local measurements

Run a pilot before the formal profile. Output directories must not already exist:

```sh
uv run --locked --no-editable python -m scripts.m4_benchmark.run --profile pilot --output artifacts/m4-benchmark/new-pilot
uv run --locked --no-editable python -m scripts.m4_benchmark.run --profile local --output artifacts/m4-benchmark/new-local
```

The tool starts temporary loopback services and cleans up its processes on
normal or failed exit. Only invalid cases may be repeated, with the same source
as the original run; do not mix changed implementations into old measurements.
See the [tool guide](../scripts/m4_benchmark/README.md) for validity rules,
arrival windows, retries, and reporting.

Successful latency excludes rejected requests, while success rates include
issued failures. Mock measurements do not establish GPU inference performance.

## 4. Collect new real-model measurements

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

## 5. CI and reproduction boundaries

The [CI workflow](../.github/workflows/ci.yml) runs on push, pull requests, or
manual dispatch. It installs locked Python 3.13 dependencies, runs tests and
compilation checks, verifies evidence checksums, and performs isolated Docker
integration checks. It does not rent a GPU, rerun formal benchmarks, or publish
a service. Packaging evidence is printed in job logs; local verification can
save the JSON separately.

Action setup follows [checkout v4](https://github.com/actions/checkout/tree/v4)
and [setup-python v5](https://github.com/actions/setup-python/tree/v5).
Actions and base images use version tags; the toolchain is not guaranteed
immutable or byte-reproducible. The fresh-GPU installation procedure was checked
against the recorded environment and scripts, but final acceptance did not
provision another GPU from scratch.

See [project acceptance](PROJECT_ACCEPTANCE.md) for dated local and hosted
results. A new local check is not evidence that a new hosted CI run passed.
