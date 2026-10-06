# M4.2 远程环境检查

**日期：2026-10-06；独立 vLLM、模型下载、直接接口与单后端网关联调已完成。**
作者配置第一版及 review 已通过；工程验收见
[M4.2 验收记录](REAL_BACKEND_ACCEPTANCE.md)，作者独立复述待完成。

| 项目 | 实际检查结果 |
| --- | --- |
| 系统 | Ubuntu 24.04.1 LTS，x86_64 |
| GPU | 单卡 NVIDIA GeForce RTX4090，24564 MiB 显存 |
| 检查时 GPU 状态 | 约 1 MiB 占用，未列出运行进程 |
| NVIDIA 驱动 | 550.54.14 |
| nvidia-smi 显示 CUDA | 12.4 |
| 系统 Python | 3.12.3 |
| 预装 PyTorch | 2.7.0a0+7c8ec84dab.nv25.03 |
| PyTorch 编译 CUDA | 12.8 |
| torch.cuda.is_available() | True |
| 根文件系统 | fuse-overlayfs，30 GB，检查时约 30 GB 可用 |
| 常用工具 | pip、git、curl、wget 可用；未找到 uv 或 docker 命令 |

预装 PyTorch 是 NVIDIA 25.03 发行构建，并非仅凭界面文字就可视为普通
PyPI torch 2.7.0。nvidia-smi 与 torch.version.cuda 表示不同信息：前者显示
驱动报告的 CUDA 支持，后者显示 PyTorch 的编译版本；当前实际 GPU 可检测，
但这不足以证明新安装的 vLLM 全部 kernel 可运行。

初步环境方案：单实例模型服务使用独立 Python 3.12 环境；InferGate 继续
保持项目 Python >=3.13 要求，不把两个服务的依赖强行放入同一环境。
vLLM 具体版本及 CUDA/PyTorch 组合需按驱动和实际 import/kernel 验证确定。
遵循 [vLLM 独立环境安装建议](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)。

进一步确认 `/root/shared-nvme` 为 50 GB JuiceFS 数据挂载，模型存放在那里。
从 cgroup 确认本容器 memory.max 为 128849018880 字节，即 120 GiB；free
显示的是容器可见的宿主机内存，不能据此断言独占 1 TiB。
数据卷在平台关机/释放后的保留行为尚未验证，不能仅凭目录名称承诺持久性。

## 已安装与启动

- 工具：uv 0.12.2，安装于 `/root/infergate-m4/tools`。
- 独立推理环境：`/root/infergate-m4/vllm-env`，Python 3.12.3、vLLM 0.8.5、
  PyTorch 2.6.0+cu124；未覆盖预装 NVIDIA PyTorch。
- vLLM 导入与 BF16 GPU 矩阵计算通过。安装版本依据官方
  [0.8.5 CUDA 12.4 安装说明](https://docs.vllm.ai/en/v0.8.5/getting_started/installation/gpu.html)
  和实际 PyPI 依赖元数据选择；这是一条当前驱动下已验证的基线路径，
  不是最新版或未来接口支持承诺。
- Qwen 官方 ModelScope 仓库：Qwen/Qwen2.5-7B-Instruct，下载到
  `/root/shared-nvme/infergate-m4/models/Qwen2.5-7B-Instruct`；四片权重
  合计 15231271888 字节。本机到 Hugging Face API 超时，ModelScope 可访问。
- 服务别名：Qwen2.5-7B-Instruct；监听远程 `127.0.0.1:8001`，无公网端口开放。
- 初始参数：BF16、上下文 4096、max_num_seqs=2、GPU memory utilization=0.85，
  V0 engine + eager，未开启 prefix caching；这些是功能验证设置，不用于性能结论。
- 服务本轮保留运行，启动时记录的父进程 PID 为 1965；PID 文件
  `/root/infergate-m4/backend.pid`，日志 `/root/infergate-m4/backend.log`。

复现配套：`configs/m4/vllm-requirements.txt`、`scripts/download_m4_model.py`、
`scripts/start_m4_backend.sh`、`scripts/verify_real_backend.py`。在远程专用目录
复制相应脚本后执行：

```bash
/root/infergate-m4/vllm-env/bin/python /root/infergate-m4/download_m4_model.py
M4_MODEL_PATH=/root/shared-nvme/infergate-m4/models/Qwen2.5-7B-Instruct \
  bash /root/infergate-m4/start_m4_backend.sh
```

启动脚本前台运行；已有服务正在运行时不要重复启动。在另一终端验证：

```bash
/root/infergate-m4/vllm-env/bin/python /root/infergate-m4/verify_real_backend.py \
  --output /root/infergate-m4/real-backend-evidence.json
```

## 证据与边界

健康 200、模型列表、真实非流式生成和 65 个 SSE JSON 事件及 [DONE] 均通过，
见 [真实请求证据](evidence/real-backend-2026-10-06.json)。回答以 max_tokens=64
限制，可能截断，不把内容完整性作为模型能力结论。
完整已安装依赖见 [版本清单](evidence/vllm-environment-2026-10-06.txt)；
模型权重文件大小、配置/index SHA256 和实际 OpenAPI 接口声明见
[模型清单](evidence/model-manifest-2026-10-06.json)。没有计算权重全文 SHA256，
ModelScope revision 使用 master，因此不承诺从该标签重下载时字节级相同。

该 vLLM 的实际 OpenAPI 未声明 /v1/responses，M4.3 需另选兼容版本/后端并
重新验证，不通过协议转换伪造支持。后续已完成网关功能接入；未验证
生产负载或模型性能，客户端 SSE 事件到达时刻不等于网关读侧 first-byte 或 TTFT。
本记录不保存密码、认证材料或机器硬件序列号。

## 单后端网关部署

网关位于 `/root/infergate-m4/gateway`，独立 CPython 3.13.14 环境，非 editable
安装；单 worker 监听 `127.0.0.1:8000`。启动配置：model 为
Qwen2.5-7B-Instruct，count=1，A 为 `http://127.0.0.1:8001`，B 显式空白。
B 不参与创建、校验或探测，指标仅有 backend-a。

初次 `uv sync --locked --no-dev --no-editable --python 3.13` 下载长时间停滞，
停止后改为从原锁文件导出带哈希 requirements，通过清华 PyPI 镜像安装。
哈希校验开启，随后以 `--no-deps` 安装应用；未修改仓库锁文件。实际 61 个
已安装包版本全部与锁文件一致，见
[网关环境与源文件哈希](evidence/gateway-environment-2026-10-06.json)。

复现安装（在复制了 pyproject.toml、uv.lock、README、src 和 logging 配置的目录中）：

```bash
cd /root/infergate-m4/gateway
/root/infergate-m4/tools/bin/uv venv --python 3.13
/root/infergate-m4/tools/bin/uv export --frozen --no-dev --no-emit-project \
  --format requirements-txt --output-file ../gateway-requirements.txt
/root/infergate-m4/tools/bin/uv pip install --python .venv/bin/python \
  --require-hashes --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  -r ../gateway-requirements.txt
/root/infergate-m4/tools/bin/uv pip install --python .venv/bin/python --no-deps .
```

将 `scripts/start_m4_gateway.sh` 和 `scripts/verify_m4_gateway.py` 复制到工作根目录。
启动脚本前台运行；不要在已有服务运行时重复启动。验收脚本只用于本任务
专用网关，读取 backend.pid 并核对 vLLM 命令，短暂停止并重新启动该模型服务：

```bash
bash /root/infergate-m4/start_m4_gateway.sh
# 另一个终端；运行前按 backend.pid / gateway.pid 记录各自的服务进程。
/root/infergate-m4/gateway/.venv/bin/python /root/infergate-m4/verify_m4_gateway.py \
  --output /root/infergate-m4/gateway-evidence.json
```

网关日志 `/root/infergate-m4/gateway.log`，PID 文件 `/root/infergate-m4/gateway.pid`。
两项服务本轮保留运行；模型恢复后的 PID 以 backend.pid 为准，初始 1965 已退出。
