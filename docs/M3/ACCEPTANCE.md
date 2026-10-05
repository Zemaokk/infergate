# M3 验收状态

**状态：未完成。** 2026-10-05 M3.1/M3.2 指标与 M3.3 日志/tracing 代码验证
基线为 290 passed，2 条已有依赖弃用警告。自动化测试不代替完整观测栈验收。

M3.4 已准备：[本地观测栈](../../observability/README.md)、固定版本 Compose、
Grafana 数据源/仪表盘与 scripts/verify_m3.py。YAML/JSON 解析、引用检查、
脚本语法及 CLI 检查通过；当前主机没有容器运行环境，尚未启动这些服务。

待取得的实际证据：

- Compose 配置及镜像启动成功，Prometheus 能抓取实际网关。
- Jaeger 中请求/尝试 span 和完成日志 trace ID 对应，fallback、流式关闭和
  取消的结果与父子关系正确。
- Prometheus 请求/尝试计数与日志一致，名额最终恢复，健康状态按既有语义。
- Grafana 仪表盘加载与渲染、低流量/缺失样本表现合理。
- 受控脚本实际执行并保存带时间戳的 passed 证据，完成作者复述。

现有边界继续保留：单进程配额、首字节不等于 TTFT、没有可信 token/s、
没有等待队列、网关 trace 不能证明后端内部计算阶段、trace 导出为 best effort，
本轮无生产性能或多进程验证。
