# M3 验收状态

**状态：约定范围内的 M3 已完成。** 2026-10-05 M3.1/M3.2 指标与 M3.3 日志/tracing 代码验证
基线为 290 passed，2 条已有依赖弃用警告。自动化测试不代替完整观测栈验收。

M3.4 已运行：[本地观测栈](../../observability/README.md)、固定版本 Compose、
Grafana 数据源/仪表盘与 scripts/verify_m3.py。Docker Desktop Engine 29.8.2、
Compose 5.5.1 启动 Prometheus 3.15.0、Jaeger 2.21.0、Grafana 13.2.3 成功。

实际证据：[带时间戳的 JSON](evidence/acceptance-2026-10-05.json)，
[Grafana 曲线截图](evidence/grafana-2026-10-05.jpg)、
[并发及健康截图](evidence/grafana-status-2026-10-05.jpg)。

- 受控 HTTP 联调 passed：9 个请求、10 次后端尝试；Prometheus 抓取 up=1，
  请求/尝试计数与完成日志一致，最终 active_requests=0。
- 普通成功、流式完成、拒绝、客户端断开、fallback、双后端离线均有对应
  Jaeger trace；每次尝试的 span ID、父子关系及 outcome 与日志一致。
- fallback 请求 completed，A transport_error，B completed，共 3 个 span；
  取消请求虽已发送 HTTP 200，最终请求及尝试均为 cancelled。
- 受控健康探测间隔为 3600 秒；后端停止后既有选路状态仍为 healthy，
  Gauge 合计 2。此结果不代表停止后的后端仍可连接。
- Grafana 11 个面板 provisioning 通过；浏览器实际检查速率、耗时、首字节、
  并发、健康与抓取状态面板。首轮单次抓取时速率图显示 No data；增加跨周期
  请求后显示真实曲线。脚本停止网关后 up 降为 0。
- 所有脚本创建的应用进程已停止；观测容器保留运行。现有 Python 测试基线
  沿用 290 passed，本轮未修改应用代码，未重跑完整测试集。

2026-10-05 作者复述：正确解释流式响应先发送状态码，后续取消不能改变
HTTP 200，而最终 outcome 由实际执行和清理结果决定；正确预测 fallback
请求计数 +1、尝试计数 +2，请求/B completed、A transport_error，并正确
指出 A/B 尝试 span 均以请求 span 为父项。作者最初预期 6 个 span，AI 纠正：
当前仅网关创建请求和尝试 span，共 3 个；context 传播不会自动创建上游或
后端 span，A 连接失败也通常不会产生后端 span。作者随后确认当前插桩范围。

阶段复盘：作者主导观测状态与关键埋点，共同完成生命周期和失败语义，AI
主导工具接入、测试配套与仪表盘。主要理解点是请求结果与尝试结果独立，
HTTP 状态码与流式最终结果独立。计数、取消、fallback 与本地栈已验证；
性能结论与后端内部计算阶段仍无证据。M4 保持 learning mode，先完成
可复现应用打包，再逐项推进真实后端、协议 adapter 和 benchmark。

现有边界继续保留：单进程配额、首字节不等于 TTFT、没有可信 token/s、
没有等待队列、网关 trace 不能证明后端内部计算阶段、trace 导出为 best effort，
本轮无生产性能或多进程验证。
