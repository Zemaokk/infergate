# M3 工作计划：可观测性

**状态：** 已启动；M3.1 首轮情景讨论完成，下一步为作者的最小请求状态第一版；
指标合同其余设计仍待细化，尚未接入观测代码。

**模式：** Learning mode；作者主导 40%，AI 主导 60% 为阶段节奏目标。  
**基线：** 2026-09-26 当前工作区 `uv run --offline pytest -q`：122 passed，
2 条已有依赖弃用警告。M2 验收范围与技术债继续见 [M2 验收](../M2/ACCEPTANCE.md)。

## 1. 顺序与分工

| 步骤 | 类别及分工 | 可验收产物 |
| --- | --- | --- |
| M3.1 指标语义与生命周期 | B 类，共同定义；作者先预测情景并完成关键埋点第一版 | [指标合同](OBSERVABILITY_CONTRACT.md)、请求与尝试分别计数、失败及取消测试 |
| M3.2 Prometheus 接入 | C 类，AI 主导样板；B 类共同验证埋点 | `/metrics`、独立 registry、Counter/Gauge/Histogram，测试可隔离重复建 app |
| M3.3 Structured logging 与 tracing | B 类共同定义事件与 span 边界；C 类 AI 接入样板 | 请求完成日志、请求与后端尝试关联、流式错误和取消可定位 |
| M3.4 Grafana 与集成验收 | C 类 AI 主导配置；B 类共同验证 | 仪表盘、最小本地观测运行说明、受控延迟/失败证据、作者 teach-back |

每一步有验证证据再进入下一步。M3.1 先完成 contract → prediction → 作者关键
路径第一版 → focused review → verification → teach-back → record。
观测栈所需最小运行配置可在 M3 完成；完整应用打包与 benchmark 仍在 M4。

## 2. 范围和证据边界

- 保留项目蓝图中的 metrics、structured logging、OpenTelemetry 和 Grafana。
- 当前无等待队列：队列深度定义为 0，排队时间不采样；不将 admission 耗时
  命名为排队时间。
- 先测量网关可见的首个非空下游字节，明确称为 first-byte latency。
  真正 TTFT 与 output tokens/s 需额外定义 token 事件或可信 usage 来源，暂不
  伪造数据；是否扩展 SSE 解析由作者另定范围。
- 诊断目标是区分 admission、选路、各次后端调用、响应传输和清理；仅凭网关
  trace 无法拆分后端内部排队与模型计算，需要后端侧证据。
- 保持 M2 的扣费、容量所有权、重试和透传语义；不借观测接入重写策略。

## 3. 集成验收目标

- 一次客户端请求只记录一次最终 outcome；fallback 的每次后端调用分别记录。
- 校验失败、429、并发 503、无候选 503、传输 502、后端 HTTP 错误均可区分。
- 流式 headers 为 200 后的读取失败不能被归为正常完成；取消独立记录。
- 活跃名额与 M2 控制器一致，正常、异常和取消后恢复；不能在 endpoint 返回时
  提前结束流式观测。
- 用受控时钟/事件验证计时边界；不对真实机器的毫秒耗时写脆弱断言。
- metrics 抓取和健康探测不计入业务请求；日志、指标和 trace 不记录 key、
  prompt、响应正文；trace/request ID 不作为指标 label。
- 仪表盘可复现展示请求结果、延迟分布、并发、健康与后端尝试分布；trace
  展示 fallback 和流式生命周期。测试通过不等于生产性能已验证。

## 4. 当前作者任务

第 4 节情景已完成首轮讨论，具体回答与 AI 补充见合同第 5 节。下一步按
[合同第 6 节](OBSERVABILITY_CONTRACT.md#6-下一步最小请求状态第一版b-类作者先写)
完成独立的 `RequestObservation` 第一版，再进行 focused review 与验证。
当前尚无观测实现或新测试证据，不能标记 M3.1 完成。
