# 安装、复现实验与重新绘图

所有相对路径从仓库根目录执行。运行网关需要 Python 3.13；真实 GPU 推理
使用独立 Python 3.12 环境。验收快照与本次复现的新结果须保存在不同目录。
这里只承诺步骤和证据可检查，不承诺重新测量得到相同吞吐或字节级相同镜像。

## 1. 网关与受控 HTTP 验收

安装 uv 0.12.2 后：

```sh
uv sync --locked --no-editable
uv run --locked --no-editable python -m pytest -q
```

`--locked` 阻止静默改写锁文件；非 editable 安装与镜像路径一致。
Python 3.13 的补丁版本可不同，记录本机实际版本。原生启动、curl、配置地址
及 SSE 示例见 [README](../README.md)。镜像流程需要 Docker Engine/Compose：

```sh
docker compose config --quiet
uv run --locked --no-editable python scripts/verify_m4.py --output /tmp/infergate-packaging-new.json
```

该脚本实际构建镜像，启动自己的三个容器，验证 UID/site-packages、轮换、
SSE、停止/恢复和全后端拒绝，保存日志并清理自己的容器/网络。
8000 必须空闲；已有同名验收项目时拒绝复用，可用 `--project` 指定新名字。
M2 的限流、并发、fallback 真实 HTTP 实验另用：

```sh
uv run --locked --no-editable python scripts/verify_m2.py --output /tmp/infergate-m2-new.json
```

其端口 8000–8002 必须空闲。观测栈独立启动，步骤及清理见
[observability/README.md](../observability/README.md)，不是应用 Compose 的一部分。

## 2. 从随仓库交付的原始数据重绘

先核验两个压缩包。macOS 使用 `shasum`，Linux 可使用 `sha256sum`：

```sh
shasum -a 256 -c docs/M4/evidence/SHA256SUMS
```

在尚无以下证据目录的干净 checkout 中执行；不要覆盖本机已有实验目录：

```sh
mkdir -p artifacts/m4-benchmark/remote-20261007
tar -xzf docs/M4/evidence/benchmark-local-2026-10-07.tar.gz -C artifacts/m4-benchmark
tar -xzf docs/M4/evidence/benchmark-real-2026-10-07.tar.gz -C artifacts/m4-benchmark/remote-20261007
uv venv --python 3.13 /tmp/infergate-plot
uv pip install --python /tmp/infergate-plot/bin/python matplotlib==3.11.2
MPLCONFIGDIR=/tmp/infergate-mpl /tmp/infergate-plot/bin/python -m scripts.m4_benchmark.report artifacts/m4-benchmark/20261007-local-retry-01 --output /tmp/infergate-local-report
MPLCONFIGDIR=/tmp/infergate-mpl /tmp/infergate-plot/bin/python -m scripts.m4_benchmark.real_report artifacts/m4-benchmark/remote-20261007/real-01 --output /tmp/infergate-real-report
```

绘图依赖不安装进网关。每份报告包含 Markdown、PNG/SVG 及输入摘要哈希。
本地压缩包同时包含首次运行与补测，不能只交付补测目录；首次漏发的无效
case 仍在原目录。真实压缩包还包含两次 pilot、环境、启动日志及清理记录。
manifest 内旧机器绝对路径与历史源码快照保持原样，不能把它们当作新机器路径。
2026-10-07 本地报告原文的“尚未获得真实模型性能数据”是当时记录；后续真实
结果单列于 [真实报告](M4/benchmark-real-20261007/RESULTS.md)。

## 3. 重新采集本地实验

先小样本检查，再正式采集；输出目录必须不存在：

```sh
uv run --locked --no-editable python -m scripts.m4_benchmark.run --profile pilot --output artifacts/m4-benchmark/new-pilot
uv run --locked --no-editable python -m scripts.m4_benchmark.run --profile local --output artifacts/m4-benchmark/new-local
```

工具在 loopback 上启动临时服务，正常退出或失败时清理自己创建的进程。
只对无效 case 使用 retry，且源码必须与原运行一致。不要用今天已扩展的工具
补测旧源码的实验。规则、到达率窗口和报告命令见 [工具说明](../scripts/m4_benchmark/README.md)。
mock 实验不能替代 GPU 性能测量；拒绝耗时不计入成功延迟，失败仍进入成功率分母。

## 4. 在新的 GPU Linux 主机采集真实模型

以下在具备 NVIDIA GPU/驱动的 x86_64 Linux 主机上执行。已验证硬件是
RTX4090/驱动 550.54.14；其他硬件需要重新核对实际 kernel 和路由支持。
将本仓库复制到专用 checkout，并进入根目录。使用单个模型实例；启动前确认
GPU 空闲、8002 未占用。已有业务模型不能直接停机，应选择隔离环境。

创建独立工具、推理与网关环境（安装阶段需要联网）：

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

模型约 15.2 GB 权重，另留下载/缓存空间。首次模型使用 master，下载 revision
未记录；若需要固定快照，先选择实际存在的 revision，再设置 `M4_MODEL_REVISION`。
该缺失意味着历史模型权重字节级复现尚无证据，不能以配置哈希替代。
推理依赖文件固定关键包而非完整传递依赖锁，新安装要记录全部实际版本。

在独立终端前台运行模型，保存完整日志：

```sh
export INFERGATE_GPU_ROOT=/root/infergate-repro
export M4_MODEL_PATH="$INFERGATE_GPU_ROOT/models/Qwen2.5-7B-Instruct"
M43_WORK_ROOT="$INFERGATE_GPU_ROOT" M43_MODEL_PATH="$M4_MODEL_PATH" bash scripts/start_m43_backend.sh > "$INFERGATE_GPU_ROOT/backend.log" 2>&1
```

另一终端确认 `/health` 为 200、`/v1/models` 的模型别名正确，并检查 OpenAPI
同时声明 `/v1/chat/completions` 和 `/v1/responses`。先直接验证两个原生协议
有非空生成，再使用采集工具；Chat-only 服务不满足前提。

在网关 checkout 根目录生成本次环境记录（不是复制历史 JSON）：

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

pilot 失败时先检查原始数据，不继续正式采集。采集器启动并停止实验网关，
不会停止你前台运行的模型；结束后在模型终端 Ctrl-C，确认自建服务退出与
GPU 显存释放。把环境 JSON、backend.log 与全部输出目录一起备份，再重绘。
不经 SSH 隧道采集，不把公网延迟纳入此组 loopback 结果。

## 5. CI 与复现限制

[CI workflow](../.github/workflows/ci.yml) 在 push、pull_request 或手动触发时
运行 Python 3.13 锁定安装、测试、编译、证据 SHA 校验，以及独立 Docker
打包验收。托管 CI 不租 GPU、不重新运行正式 benchmark，也不发布服务。
Docker 验收 JSON 会打印到 job 日志；本地执行可按上面命令单独保存文件。
Action 用法依据 [checkout v4](https://github.com/actions/checkout/tree/v4) 与
[setup-python v5](https://github.com/actions/setup-python/tree/v5)。
这些 action 和镜像仍使用版本标签；未承诺不可变工具链或字节级构建。
未推送前不能宣称 GitHub CI 已通过；当前实际检查见 [总验收](PROJECT_ACCEPTANCE.md)。
