# M4 工作计划：应用打包与可复现实验

**状态：已启动，2026-10-05。** M3 约定范围已完成。当前从 M4.1 开始，
保持 learning mode，按可独立验证的小任务推进。
本轮重新运行测试：290 passed，2 条已有依赖弃用警告。

## 1. 顺序与分工

| 步骤 | 类别及分工 | 验收产物 |
| --- | --- | --- |
| M4.1 应用打包与本地启动 | C 类：AI 完成 Dockerfile、Compose 和说明；B 类：共同定义运行配置，作者先写关键路径 | 锁定依赖安装、双 mock + 网关启动、普通/流式/健康恢复验证 |
| M4.2 真实推理后端 | B 类：作者选择可用后端与模型，共同验证配置和兼容性 | 至少一个真实 OpenAI-compatible inference backend 的请求与原始证据 |
| M4.3 最小非流式 Responses adapter | B 类：先定义支持字段和错误行为，作者写转换关键路径，AI review/测试 | `/v1/responses` 子集，复用 shared gateway core，不重复流控机制 |
| M4.4 Benchmark | A 类：作者先设计 workload 与变量；C 类：AI 整理结果与绘图 | 可重复负载、原始结果、环境/模型说明、失败样本与性能图表 |
| M4.5 CI 与交付收尾 | C 类：AI 配置 CI、架构及使用文档；作者复述与复盘 | 自动检查、第三方复现步骤、M4 验收记录 |

M4.1 验证后才进入后续应用任务。CI 可以在运行入口稳定后补充。
不加入 cache、其他路由策略、Kubernetes 或多进程共享配额。
M4.2 的设备、后端和模型选择需由作者提供实际可用条件，不预设有 GPU。

## 2. M4.1 第一小步

已保存根目录 Dockerfile 与 `.dockerignore`：构建阶段使用 uv 0.12.2，按
`uv.lock` 安装非 editable 应用；运行阶段只复制安装环境和日志配置，使用
非 root UID，单 worker 启动。现有 pytest 仍在项目主依赖中，本轮不调整依赖结构。

运行入口继续使用 `infergate.runtime:app`，不使用目前只打印问候的
`infergate` console script。容器启动命令不经过 `uv run`，避免启动时解析或安装依赖。
Python 基础镜像使用 3.13 系列标签，尚未固定 digest；不能据此承诺镜像字节级复现。
构建/运行方法与实际验证状态见 [打包合同](PACKAGING_CONTRACT.md)。

下一小步是运行配置：当前固定 loopback 地址不能连接独立后端容器。
先完成合同 → 作者预测 → 最小第一版 → focused review → 验证 → teach-back，
随后 AI 补双 mock + 网关 Compose 和受控验收。完整应用 Compose 尚未生成。
现有 M3 观测 Compose 继续独立；应用打包完成后再验证容器间抓取和 OTLP 地址。

## 3. 验收和证据边界

- Compose 能从仓库启动三个服务；镜像运行不挂载源代码或宿主机虚拟环境。
- 两个 mock 健康时可验证轮换；普通响应与 SSE 透传正确。
- 停止一个后端后，探测更新可使其退出路由，恢复后重新加入。
- 所有后端不可用时沿用既有 502/503 行为，不改 fallback 条件。
- 单 worker、容量 2、每 key 容量 2/补充速率 1 的默认行为保持一致。
- 镜像构建成功、HTTP 联调成功、真实模型成功、性能实验成功分别记录。
- mock 延迟不是模型性能；读侧 first-byte 不是 TTFT，不编造 token/s。

## 4. 当前记录

2026-10-05：AI 阅读人机协作约定、M3 验收及现有 runtime，启动 M4.1。
工作区初始干净，未修改核心请求路径。Docker CLI 29.8.2 可用，但 Engine
socket 不存在；尝试启动 Docker.app 返回 `kLSNoExecutableErr`（可执行文件缺失）。
当前环境不能构建镜像或运行容器。镜像文件待实测，M4.1 尚未验收。

独立安装检查已通过：只复制构建输入至临时目录，执行
`uv sync --locked --no-dev --no-editable`，安装 61 个包；离开项目目录后
确认 infergate 从临时环境的 site-packages 加载，runtime/mock 两个 FastAPI
入口及 Uvicorn 0.52.4 可用。验证环境为 macOS ARM64、CPython 3.13.14；
这不验证 Linux wheel 或 Dockerfile 的实际构建。首次离线安装因临时缓存
缺依赖失败，随后联网按锁文件安装通过。锁文件检查及 `git diff --check`
通过，未修改 pyproject.toml、uv.lock 或已有核心实现。
