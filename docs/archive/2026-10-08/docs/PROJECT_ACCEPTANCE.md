# InferGate 第一版项目总验收

**2026-10-08：M1–M4 在约定的第一版单进程范围内通过全项目验收，M4.5 收尾。**
推送提交 `35c6902d096b8a36440a54b2a3364d5bfe0d8d4d` 的首次托管 CI 两个
job 均成功，Linux AMD64 容器验收通过；本地测试与 M2/M3 实测再次通过。
这是既定范围的项目验收，不是全平台或生产就绪认证。

依据 [项目蓝图](PROJECT_PLAN.md) 与 [协作约定](COLLABORATION_CONTRACT.md)，
按实际缩定的第一版范围验收。各里程碑原记录保留当时环境、测试数量和边界；
不能把历史 Docker/远程结果说成本轮重新运行。

| 阶段 | 实际交付及证据 | 当前判定 |
| --- | --- | --- |
| M0 最小转发 | 双 mock、同协议普通请求、round-robin、错误映射；当前 router/backend/runtime 回归测试，历史 [工作流](M0/FULL_WORKFLOW_GUIDE.md) | 约定范围完成 |
| M1 流式/健康 | SSE 增量透传、取消清理、探测失效/恢复及 timeout；[验收](M1/ACCEPTANCE.md) | 约定范围完成 |
| M2 负载保护 | per-key token bucket、共享并发 2、零队列快速拒绝、连接错误最多两次尝试；[验收](M2/ACCEPTANCE.md) | 单进程范围完成；本轮七组 HTTP 检查再次通过 |
| M3 可观测性 | 请求/尝试指标、完成日志、W3C context、OTLP、Prometheus/Jaeger/Grafana；[验收](M3/ACCEPTANCE.md) | 约定范围完成；2026-10-08 真实联调再次通过 |
| M4.1 打包 | 非 root、非 editable 镜像、三服务 Compose、11 个 HTTP 业务请求；[验收](M4/ACCEPTANCE.md) | 2026-10-06 快照通过；2026-10-07 当前代码 Linux ARM64 重验通过 |
| M4.2 真实后端 | Qwen 7B 普通/SSE、单后端、502/503、停机恢复；[验收](M4/REAL_BACKEND_ACCEPTANCE.md) | 工程与作者复述完成 |
| M4.3 Responses | 最小文本非流式原生转发、共享 admission/观测及 vLLM 原生生成；[验收](M4/RESPONSES_ACCEPTANCE.md) | 工程与作者复述完成 |
| M4.4 实验 | 本地 52 个有效 case / 29,630 次尝试；真实 24 个 case / 1,200 次成功测量；[本地](M4/benchmark-local-20261007/RESULTS.md) / [真实](M4/benchmark-real-20261007/RESULTS.md) | 工程与作者统计口径复述完成 |
| M4.5 交付 | CI、[当前架构](ARCHITECTURE.md)、[复现指南](REPRODUCING.md)、两份便携原始数据、校验和及本记录 | 本地及首次托管 CI 验收完成 |

## 2026-10-08 最终复核

- [首次 CI](https://github.com/Zemaokk/infergate/actions/runs/37645717168)
  于北京时间 2026-10-07 23:40 完成，本轮实时查询并读取 job 日志；提交 SHA
  与当前 HEAD 一致。tests 为 435 passed / 2 warnings；packaging 的 Linux
  AMD64 镜像完成 11 个业务请求，active=0，cleaned_up=true。原始摘要与
  容器记录见 [CI 证据](M4/evidence/ci-2026-10-08.json) 和
  [CI 打包记录](M4/evidence/ci-packaging-2026-10-08.json)。
- 本地全部 435 项测试再次通过；M2 七组真实 HTTP 检查通过，见
  [当日 M2 证据](M2/acceptance-2026-10-08.json)。
- 启动既有观测栈，M3 真实联调再次通过：9 请求 / 10 次尝试的日志、指标与
  trace 对应，Grafana 11 面板 provisioning 通过，最终 active=0。见
  [当日 M3 证据](M3/evidence/acceptance-2026-10-08.json)。本轮没有重新进行
  Grafana 浏览器截图检查，沿用 2026-10-05 的渲染证据。应用进程与本轮启动
  的观测容器均已停止，原有卷保留。
- 两份原始实验压缩包 SHA256 再次通过。真实 benchmark 归档中的 14 个核心
  Python 文件逐一与当前版本匹配；自 M4.3 功能验收后核心源码没有变化，
  因此沿用带日期的真实模型证据，本轮未启动远程 GPU。旧 M4.2 的真实 SSE
  与故障恢复仍是历史验收；当前流式回归由自动测试和真实 mock HTTP 覆盖。

完整复核摘要见 [全项目证据](M4/evidence/project-acceptance-2026-10-08.json)。

## 2026-10-07 交付检查（历史记录）

- 在项目外临时目录，只复制构建输入，按锁文件安装非 editable 应用，61 个包
  安装成功；离开 checkout 后从 site-packages 导入 runtime 为 FastAPI。
- 使用该新环境运行全部测试：**435 passed，2 条已有依赖弃用警告**。
  工具测试需要仓库脚本，因此测试时把仓库根目录加入 PYTHONPATH；核心包
  仍从 site-packages 加载，未把 src 加入路径。
- `verify_m2.py` 七组真实 loopback HTTP 检查全部通过，所有子进程已停止。
  [本轮原始记录](M4/evidence/delivery-m2-2026-10-07.json)。
- 作者启动 Docker 后，当前代码实际构建和三服务 HTTP 验收通过：11 个业务请求、
  UID 10001、CPython 3.13.16、从 site-packages 加载，最终 active=0，验收容器
  与网络全部清理。镜像包含两个 API route。见
  [本轮容器原始记录](M4/evidence/delivery-packaging-2026-10-07.json)。
- 两份便携证据 SHA256 通过。将它们解压到新的临时目录，从解压数据生成
  本地及真实 Markdown/PNG/SVG；输入摘要与原报告 provenance 一致。
  本地首次运行原始 29,627 条 + 补测 210 条 = 29,837 条全部保留；合并有效
  尝试为 29,630。真实正式 1,200 条全部保留，pilot 不混入正式汇总。
- CI YAML 与各 shell step 解析、Python 编译、依赖锁校验、Compose 静态配置
  及差异检查通过。检查摘要见 [交付证据](M4/evidence/delivery-2026-10-07.json)。

## 保留的复现边界

1. 本地 Linux ARM64 与托管 Linux AMD64 的打包都通过；不外推其他平台。
2. 新 GPU 环境安装指南已结合实际环境与脚本核对，但本轮未租新机器从零安装。
   历史模型下载 revision 未记录、推理传递依赖未完整锁定，不承诺相同模型
   权重字节或性能；原始数据重绘无需模型，已经实测通过。

## 计划中第一版以外的范围

无 Kubernetes、自动扩缩容、其他路由策略、网关 cache、多进程共享配额、
可信身份认证、key 状态淘汰或总生成 deadline。没有等待队列，读侧 first-byte
不是 TTFT，没有可靠的生产 token/s、队列内部阶段或生产 SLA。
不同 prompt/output 长度、冷 cache、长期压力与网络黑洞实验未开展。
这些都是明确边界，不从已有通过记录推断生产就绪。

## 作者理解与贡献记录

作者主导路由、健康状态、token bucket、并发责任、fallback、共享执行与薄入口
的关键路径；AI 协助 focused review、声明校验、工程测试、环境、工具、图表与文档。
作者明确授权本次 benchmark 设计由 AI 提供，不能据协作比例目标推断实际百分比。
各阶段复述与纠正来源见对应验收记录。

M4.4 作者先指出拒绝请求不能计入成功延迟，后解释恢复默认 key 配额后吞吐
可能因限流下降；AI 补充失败仍进成功率分母、需排除额度混淆。该闭环完成，
不再要求重复 GPU 实验作为理解验收。
M4.5 未新增核心机制，作者最终交付复盘可围绕两个问题：当前系统保证哪些上限，
哪些仍不保证；第三方如何区分重绘已有数据与重新测量新环境。

M4.5 本地及托管工程验收已完成。M1–M4 按约定范围收尾，后续变更继续由 CI
验证；不为扩大功能或重新测量已有性能数据阻塞本次交付。
