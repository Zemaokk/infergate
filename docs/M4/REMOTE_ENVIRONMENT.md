# M4.2 远程环境检查

**日期：2026-10-06；SSH 连接和只读检查已完成，尚未安装 vLLM 或下载模型。**

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

系统盘只有 30 GB，下一步先确认模型缓存与依赖安装的数据盘位置、可用空间
和持久性，再下载模型。free 输出显示的是容器可见的宿主机内存，不能用它
断言本实例获得 1 TiB 独占内存。

本记录不保存密码、认证材料或机器硬件序列号，不包含模型运行、推理接口、
吞吐量或网关真实后端验收结论。
