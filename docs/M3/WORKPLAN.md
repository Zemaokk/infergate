# M3 工作计划：可观测性

**状态：** M3.1 请求状态、尝试计数、候选结果、发送信号与最终 outcome 已验证；
作者已完成生命周期和首字节计时情景 teach-back。
M3.2 请求计数、总耗时、请求级首字节 Histogram、并发占用与健康 Gauge 已接入；
后端尝试状态与异常生命周期已接入；尝试级指标导出、日志与 trace 待完成。

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

作者已完成独立的 `RequestObservation` 及 focused review 修正；AI 统一
`started_at` 拼写并补充 6 个单元测试用例。完整测试集 128 passed，2 条已有
依赖弃用警告。验证详情见合同第 7 节。

作者已解释 finish 返回 False 不应重复计数，并预测零首字节耗时应保留；AI
纠正了 `0.0 is not None` 的表达。AI 完成 middleware 框架样板，作者完成注册、
endpoint 读取及实际后端调用前的尝试计数。

2026-09-27 新增 18 个集成用例，完整测试集 152 passed，2 条已有依赖警告。
随后作者完成 pending_outcome/pending_reason 和各响应分支标记，AI 扩展测试，
完整测试集 161 passed，2 条已有依赖警告。已验证后端 HTTP 503 与网关拒绝
503 分类不同，候选结果不会提前 finish；详见合同第 9 节。
AI 已补 middleware 的 send 包装，成功发送后记录 status_code 与 response_complete，
新增 6 个发送边界用例并扩展集成断言；完整测试集 167 passed，2 条已有依赖警告。
AI 已补断开、取消、异常与清理失败观测，在完整响应调用退出时 finish。
新增 13 个生命周期用例并更新集成断言，完整测试集 180 passed，2 条已有依赖警告。
作者正确解释 body 发完但清理失败时，response_complete/cleanup_failed/is_finish
均为 True，最终 internal_error、候选 completed。
首字节埋点经 focused review 后，作者移除了 send 中的错误埋点；按作者请求，AI
补下游异步迭代器包装、6 个测试并扩展集成断言。完整测试集 186 passed，
2 条已有依赖警告。下一步解释 yield 前采样与流式惰性读取，随后整理指标接入。
Prometheus 尚未接入，M3.1 未完成。

作者正确预测空块后换行的首字节耗时为 0.5 秒，且客户端发送阻塞不影响读侧采样。
AI 随后完成 M3.2 第一小步：独立 GatewayMetrics registry、请求 Counter、请求
耗时 Histogram 和 GET /metrics。仅 finish 首次成功时回调记录；抓取不计入业务
请求，上报异常不替换业务结果。新增 8 个测试用例并扩展集成断言，完整测试集
194 passed，2 条已有依赖警告。M3 未完成：首字节/尝试/并发/健康指标导出与
日志、tracing、Grafana 仍待接入。下一步先解释 registry、labels 和 histogram 样本。

最小指标代码已逐步讲解。AI 随后接入请求级首字节 Histogram，使用 route/outcome
标签，请求定稿后提交；None 不产生样本，0.0 保留。新增 4 个测试并扩展请求
集成检查，完整测试集 198 passed，2 条已有依赖警告。下一步继续 backend-attempt、
并发与健康指标的定义和接入；尝试级与请求级耗时不能混用。

AI 接入 infergate_active_requests Gauge，抓取时直接读取并发控制器的
limit - available，不复制计数状态。新增 4 个用例并扩展集成断言，完整测试集
202 passed，2 条已有依赖警告。已验证真实 app 的 ASGI 流保持期间抓取为 1，
正常结束、读取失败和取消后恢复 0；不是外部网络或生产负载验证。

AI 接入 infergate_backend_healthy{backend}，抓取时读取路由共用 HealthManager，
按配置 backend ID 去重；无 HealthManager 时不导出，初始化未探测状态沿用 0。
新增 2 个测试并补无健康检查时不导出的断言；完整测试集 204 passed，2 条已有
依赖警告。验证健康探测更新与选路一致，scrape 不额外触发探测。尝试级指标、
日志、trace 与 Grafana 仍待接入。

2026-10-01 继续 M3.2：重新运行完整测试集 204 passed，2 条已有依赖警告；
新增[尝试级指标合同草案](OBSERVABILITY_CONTRACT.md#17-m32-后端尝试级指标合同与作者预测)。
作者完成普通 fallback 的计数/耗时预测，并正确确认流式尝试在下游清理结束后
定稿。下一步作者先写独立 BackendAttemptObservation 的开始/结束状态，
AI 随后 review、测试并补框架接入；尚未接入 attempts Counter 或 Histogram。
工作区既有 `.DS_Store` 修改未触碰。

作者随后要求暂缓尝试级任务，先整理 RequestObservation。AI 按授权移除独立
完成布尔值，以 is_finished 只读属性从 total_time 推导；最终结果决策移入
finish(now)，middleware 只决定调用时机。更新调用及测试，完整测试集
211 passed，2 条已有依赖警告；验证详情见合同第 18 节。尝试级任务继续暂缓。

2026-10-01 作者恢复尝试级任务，完成 BackendAttemptObservation 及关键埋点。
AI 按授权补齐未移交尝试的异常清理与定稿，同步 attempts 接口和测试。
普通调用取消/内部异常、流式移交前构造失败、延迟清理、清理失败及发送端
分类均有验证；完整测试集 225 passed，2 条已有依赖警告。详见合同第 19 节。
下一步接入尝试级 Counter/Histogram；当前仍不导出尝试级指标。
