# M3.1 可观测性合同草案

**状态：** 2026-09-26 已完成一轮情景讨论，确认范围见第 5 节；其余接口与
指标设计仍为草案；当前已接入请求生命周期最终结果，最新状态重构见第 18 节。

## 1. 输入、状态、输出、失败行为

- **输入：** 业务请求的生命周期事件、admission 结果、后端尝试开始/结束、
  响应发送、流读取与清理结果、健康状态变化。
- **状态：** 每个请求的单调时钟时间戳和一次性结束标记、每次尝试的上下文；
  每个 app 独立的指标 registry。并发占用以原控制器为事实来源。
- **输出：** 聚合指标、结构化日志与关联 trace；业务响应内容不因观测变化。
- **失败：** HTTP 状态与最终 outcome 分开；流中失败、取消和清理失败均可记录。
  观测上报失败不改变业务结果，不吞掉业务异常或取消，不无限等待 exporter。

## 2. 建议指标与边界

下表名称均省略 `infergate_` 前缀；时间单位为秒。

| 指标 | 类型 | 建议含义与位置 |
| --- | --- | --- |
| `requests_total` | Counter | 业务请求终止时记一次，含校验/限流拒绝；流式在完整生命周期结束时记 |
| `request_duration_seconds` | Histogram | ASGI 业务请求入口到响应调用退出（含流式清理）；是网关观察时长，不是客户端实际收齐耗时 |
| `backend_attempts_total` | Counter | 实际发起下游调用记一次；选路无候选不算一次尝试 |
| `backend_attempt_duration_seconds` | Histogram | 普通：调用到完整读取/失败；流式：打开到流清理结束/失败，不只到 headers |
| `backend_first_byte_seconds` | Histogram | 仅流式，每次尝试开始到读到首个非空 body chunk；空流/首块前失败不采样 |
| `active_requests` | Gauge | 已获取且未释放的全局并发名额，即 `limit - available`，包含 fallback 与流清理 |
| `queue_depth` | Gauge | 当前快速拒绝策略下恒为 0；未来增加队列须重订合同 |
| `backend_healthy` | Gauge | 每个配置 backend 的当前路由健康状态，0/1；沿用现有初始状态与探测更新 |

普通响应的名额会在发送客户端前释放，因此 `active_requests` 不等于所有仍在
发送响应的 HTTP 请求数。流式名额在清理后释放。两个生命周期不能混为一谈。

建议最终 outcome 为有限枚举：`completed`、`rejected`、`backend_http_error`、
`transport_error`、`stream_error`、`cancelled`、`internal_error`。
`completed` 表示传输正常结束，不宣称模型语义正确或必然含 `[DONE]`。
如同时发生主错误与清理错误，保留主 outcome，另记清理错误事件，避免二次计数。
枚举优先级与具体映射在作者预测后定稿。

HTTP 状态取实际已发出的状态；尚未发出 headers 的取消/异常记 `none`，
不虚构已发送 500。成功发出 200 后发生流错误，保留 status=200，并以 outcome
区分。因此仪表盘不能只用 HTTP 5xx 计算失败率。

指标 labels 仅允许有限集合，例如 route 模板、status、outcome、配置 backend ID。
拒绝原因可用固定 reason 枚举；缺失 backend 用固定 `none`。请求级指标不绑定
某个 backend，后端分布使用尝试级指标，避免 fallback 丢失首次尝试。
不使用调用方 key、任意 model 字符串、URL、异常文本、request/trace ID 作 label。

## 3. 埋点草图与 trace 边界

```text
业务请求入口（覆盖框架校验与提前拒绝）
  -> validation / admission
  -> routing
  -> backend attempt A
  -> 如允许 fallback：routing -> backend attempt B
  -> 普通响应发送 / 流式读取与发送
  -> 资源清理与终止记录
```

- 请求外层观测需要包住实际 ASGI response 生命周期；只包 endpoint 函数会漏掉
  流传输、发送失败与取消。首个响应状态从 ASGI send 观察。
- attempt span 覆盖对应下游生命周期；流式不得在 `open_stream()` 返回时结束。
  请求 span 保持到外层终止，健康探测独立于业务 trace。
- 日志建议每请求一条完成记录，含 request ID、trace ID（存在时）、status、
  outcome、duration、attempt count；失败细节采用有界事件，避免泄露正文或 key。
- 总时长减去后端耗时不是纯网关 CPU 开销：流传输与客户端背压会影响计时。
  首块可能只是 SSE 元数据，不能当作首 token；chunk 数不能当作 token 数。
- 第一版不采样 queue time、TTFT、output tokens/s。仪表盘须标注未测量，不能
  将缺失数据画成 0；将来接入可信 token/usage 数据时补独立合同与测试。

## 4. 作者预测练习

**情景 A：** 一个合法请求已扣一次令牌、获取一个名额。A 连接失败，
允许 fallback；B 成功返回普通 200。请预测：

1. 请求计数与后端尝试计数各增加多少？分别在哪一刻增加？
2. A 失败到 B 开始之间，活跃名额应是多少？什么时候归还？
3. 最终请求 outcome 与 A/B 各自的尝试结果应如何区分？

**情景 B：** 流式 headers=200，已转发两块数据，随后读取失败。
HTTP 状态、最终 outcome、首字节采样与活跃名额分别怎样变化？

**情景 C：** 并发满导致 503，与无健康 backend 导致 503。
两者如何在指标/trace 中区分？各自是否创建 backend attempt？

**情景 D：** 客户端在第一块到来前断开。请求计数、首字节样本、资源释放和
trace 结束如何保证各自的含义？清理又抛异常时如何保留原始退出原因？

作者预测后定稿最小接口与验收测试，再由作者写关键埋点第一版；AI 负责 registry、
导出和配置样板，并共同补全框架生命周期边界。

## 5. 本轮讨论记录

- 作者正确预测一次请求经 A 失败、B 成功：请求数 +1，尝试数 +2；同一名额
  在 fallback 期间持续占用。AI 解释了请求最终结果与各次尝试结果分别记录。
- 作者正确预测 A、B 都连接失败：请求数 +1，尝试数 +2，请求失败数 +1。
  请求失败数是最终 outcome 的聚合，不要求再维护一个独立可漂移的计数器。
- 作者正确预测已发 200 后流读取失败：不能改为 502，最终为 `stream_error`，
  清理后释放名额。AI 补充关闭抛异常时也必须执行释放。
- 作者正确预测并发满与首次选路无健康后端：都不增加尝试，都为 `rejected`；
  前者没有名额可释放，后者需要归还已获取名额。AI 建议用现有错误 code
  `concurrency_limit_exceeded` / `no_backend_available` 作为 reason 区分。
- 作者正确预测首块前客户端断开：最终为 `cancelled`，不产生首字节样本；
  若清理再失败，保留取消作为主要结果，清理失败另记事件。

上述为预测与讨论记录，不等同于埋点代码验收。计数的具体触发时机、完整错误
优先级、ASGI 断开信号的识别以及 registry/trace 接口仍需在实现与测试时核对。

## 6. 下一步：最小请求状态第一版（B 类，作者先写）

建议新建 `src/infergate/observability.py`，先实现独立的 `RequestObservation`，
暂不接 Prometheus 或修改 endpoint。它仅保存一个请求的观测状态，不获取或
释放并发名额，也不负责判定是否重试。

- 构造时显式传入 `started_at`；保存尝试次数、可选首字节耗时、终止状态、
  可选 outcome 与总耗时，避免依赖真实时钟来验证状态转换。
- `start_attempt()`：实际下游调用开始时增加尝试数。
- `record_first_byte(now)`：只在第一次观察到非空 body chunk 时记录
  `now - started_at`。这是请求级首字节耗时，可能包含 fallback；不等于上表
  的尝试级 `backend_first_byte_seconds`，后者稍后用单独尝试起点计算。
- `finish(outcome, now) -> bool`：第一次结束保存 outcome 与耗时并返回 True；
  重复结束返回 False，保留原值。未来调用方只在 True 时提交一次聚合样本。
- 请求结束后不再改变该对象的尝试次数或首字节值。

首轮验收示例：起点 10，尝试两次，12 以 `cancelled` 结束，再于 13 以
`internal_error` 结束；最终应保留两次尝试、`cancelled`、耗时 2、首字节 None，
两次 finish 分别返回 True/False。清理错误由后续事件记录通道承载，不用第二次
finish 覆盖结果。作者提交第一版后进行 focused review，再共同补自动化测试。

## 7. 独立状态对象验证记录

作者完成第一版并修正默认时钟参数、重复结束及结束后更新的问题。AI 统一
`strat_at` 为 `started_at`，保留作者状态控制逻辑，补充
`tests/test_observability.py`：6 个用例覆盖两次尝试只结束一次、取消结果不被
后续清理错误覆盖、结束后忽略更新、首字节只记一次（含 0.0）、拒绝无尝试，
以及不同请求的状态隔离。

完整测试集 128 passed，2 条已有依赖弃用警告。这里通过显式时间和方法调用
验证状态对象的合同，不是实际客户端断开、fallback 或清理路径已完成埋点的证据。
调用方仍须只在非空 chunk 到来时记录首字节、用同一单调时钟提供时间，且在
完整请求生命周期的正确位置调用 finish；这些边界留待集成测试。

待作者 teach-back：为什么只有 finish 返回 True 才能提交一次最终统计？起点
10、首字节时刻也是 10、第二块时刻为 11，首字节耗时应保留什么值？

## 8. Middleware 与尝试计数接入 — 2026-09-27

作者已回答 finish 返回 False 表示结束过、不应重复计数，并正确预测首字节
零耗时；AI 补充 `0.0 is not None` 为 True，所以保护分支会保留该值。

AI 完成 middleware 样板及透传/隔离测试；作者在 create_app 注册 middleware，
通过 `http_request.state.observation` 读取请求级对象，在选路成功后、普通与
流式后端调用之前执行 start_attempt。该位置 review 通过，无需改动实现。

AI 新增 `tests/test_observation_integration.py`，9 种场景分别覆盖普通和流式
请求，共 18 个用例：成功、fallback、两次连接失败、失败后无备用、首次无候选、
请求体验证失败、缺少 key、限流拒绝、并发拒绝。测试通过真实 FastAPI/ASGI
调用路径取出 observation，与 MockTransport 记录的实际后端调用数核对；
同时检查名额归还。完整测试集 152 passed，2 条已有依赖弃用警告。

当前只创建观测对象及统计尝试次数。尚未调用 finish、采集首字节、提交聚合
指标或记录 outcome；不能据此声称取消/流失败已完成观测。下一步需将 endpoint
的候选结果传递到外层生命周期，避免普通返回或流式 headers 发出时提前定稿。

## 9. 候选结果验证 — 2026-09-27

作者完成 make_result、pending_outcome/pending_reason、验证处理器安全读取及
各响应分支标记。后端返回 HTTP 4xx/5xx 为 backend_http_error；本地 admission
拒绝为 rejected；最终无法取得响应的传输失败为 transport_error；收到小于
400 的状态为候选 completed。不从 HTTP 200 推断模型语义正确。

AI 扩展现有 18 个集成用例的候选结果断言，新增后端 400/503、读取超时的
普通与流式路径共 6 例、未观测路由的校验错误 1 例、候选状态单元测试 2 例。
完整测试集 161 passed，2 条已有依赖警告。新增未观测路由测试首次受本机代理
依赖影响，改为显式 MockTransport 后通过；没有修改运行时网络或依赖配置。

已验证候选标记不调用 finish、不产生总时长，结束后不再修改候选状态；fallback
成功最终候选为 completed。实际响应状态采集、流失败/取消识别、清理错误保留与
最终记录仍未实现。下一步的完整生命周期不能只依据 self.app 正常返回判断成功，
也不能将所有异常都归为 stream_error。

## 10. ASGI 发送信号验证 — 2026-09-27

AI 补齐 observed_send 框架包装：原样 await 下层 send 成功后，才从
http.response.start 记录 status_code；最后一个 http.response.body 的
more_body 为 False（或省略）时设置 response_complete。当前响应不使用 trailers；
若以后引入 trailers，需扩展完成边界。该标记只代表 body 的 ASGI 发送完成，
不代表客户端已收齐，也不代表后续清理已完成。

非目标请求保持原样透传。发送异常或取消继续向外传播，不误记成功，不在 send
包装内调用 finish。这里不采集首字节耗时，因为向客户端发送首块与从后端读到
首块是不同的测量位置。

新增 6 个用例覆盖显式/省略 more_body、状态在 send 成功后更新、headers/body
发送失败与取消保留原始异常；现有普通/流式集成用例核对实际 status 与 body 完成。
完整测试集 167 passed，2 条已有依赖弃用警告。最终 outcome 与 finish、客户端
断开信号、清理错误记录仍未接入，下一步共同完成这些生命周期边界。

## 11. 最终请求结果与清理边界 — 2026-09-27

AI 接入 observed_receive，在 body 未完成时观察到 http.disconnect 则记录
cancelled；发送端 OSError 和外部任务取消也记录 cancelled。普通内部异常记录
internal_error，LimitedStreamingResponse 在清理前捕获下游流 TransportError，
记录 stream_error。首个实际执行失败保存在 failure_outcome，优先于候选结果。

清理失败另设 cleanup_failed=True；已有主要失败时不覆盖它。若只发生清理
失败，则结果为 internal_error。原有异常继续向外传播；本轮保护的是观测结果，
没有改变既有 finally 中清理异常可能成为向外抛出异常的行为。

middleware 在 self.app 退出后的 finally 调用 finish：优先使用实际执行失败，
否则要求 body 完成后才能采用 pending_outcome；无候选或响应未完成且没有已知
失败时保守记 internal_error。最终 reason 仅在最终 outcome 与候选一致时沿用
pending_reason，避免取消结果携带过时的拒绝原因。

新增 13 个用例覆盖 ASGI 2.3/2.4 的正常流、读取失败、清理失败及组合，
disconnect/外部取消与清理错误组合，以及 body 已完成但清理仍阻塞时不提前
finish。更新既有发送与集成测试，核对最终结果、原因和耗时。完整测试集
180 passed，2 条已有依赖弃用警告。差异检查通过。

边界：测试为内存 ASGI 与受控流，不等同于真实网络所有断开模式；首字节未埋点，
cleanup_failed 尚未导出为日志或 trace 事件。cleanup deadline、任意重复取消和
多个并发异常组合未在本轮扩展。作者待 teach-back，M3.1 尚未完成。

## 12. 请求级首字节埋点 — 2026-09-27

作者已正确完成生命周期情景预测。首次首字节实现放在 observed_send 中，
review 发现测量边界不符，且 elif 导致非空末块跳过完成标记；作者移除后请求
AI 协助实现包装器。

LimitedStreamingResponse 接收当前请求的 observation，以 observed_chunks
包装下游 aiter_bytes。读到非空 chunk 后、yield 前调用 record_first_byte；
所有块原样 yield，不完整缓冲、不 strip 空白。首字节是请求入口到首次下游
非空块读取的耗时，包含 fallback；不是尝试级耗时、客户端收到首字节时间或 TTFT。
普通缓冲响应与本地拒绝响应不采样。后端流式 HTTP 错误的非空 body 也会采样，
因此后续聚合应按 outcome 区分，不能直接解释为成功生成延迟。

AI 新增 6 个用例，覆盖空块、空格/换行有效字节、只采样一次、惰性读取、
首块前失败不采样，以及读到首块后发送失败仍保留样本。集成用例确认 endpoint
传入 observation，普通/拒绝无样本、流式成功/fallback/后端 HTTP 错误有样本。
完整测试集 186 passed，2 条已有依赖弃用警告。包装器待作者 teach-back；
本轮未实现尝试级首字节指标或 Prometheus 导出。

## 13. Prometheus 请求指标最小闭环

作者完成首字节计时情景预测后，AI 接入 prometheus-client 0.26.0，依赖和锁文件
由 uv 更新。GatewayMetrics 每个 app 实例创建独立 CollectorRegistry，避免默认
全局 registry 导致重复注册或测试间污染。使用官方客户端的
[Counter](https://prometheus.github.io/client_python/instrumenting/counter/) 与
[Histogram](https://prometheus.github.io/client_python/instrumenting/histogram/)。

- infergate_requests_total：labels 为固定 route、实际观察 status（或 none）、
  最终 outcome、最终 reason（或 none）。不使用 key、prompt、任意 model 字符串。
- infergate_request_duration_seconds：labels 为 route、outcome；从请求入口到
  清理后定稿的秒数。包含失败与拒绝；按 outcome 筛选后再解释延迟分布。
- bucket 边界为 0.01、0.05、0.1、0.25、0.5、1、2.5、5、10、30、60、120、300
  秒和 +Inf，属于初始设计选择，不是性能结论。p50/p95/p99 留待查询聚合。
- GET /metrics 以官方 exposition 格式返回本 app registry，无需 key；该请求
  不进入业务观测。没有样本的 label 组合尚不产生时间序列。
- middleware 仅在 finish 返回 True 时同步调用 record_request_metrics。普通上报异常被记录
  为固定 warning，不覆盖业务结果/原异常，不进行网络 exporter 调用或重试。
  指标提交不保证跨 Counter/Histogram 的事务原子性；单进程内存统计不持久化。

新增 8 个测试覆盖已知耗时的 bucket/count/sum、未结束不计数、registry 隔离、
HTTP scrape 可解析且不计业务量、敏感值不进入 labels、200 流失败和无 headers
取消各计一次、上报异常不改变正常结果/原始异常/取消。既有 24 个请求集成场景
补充指标断言。完整测试集 194 passed，2 条已有依赖弃用警告。

范围：本轮只导出请求计数与请求耗时；尚未导出首字节、backend attempts、并发和
健康指标。未启动 Prometheus server 或 Grafana，未接入 tracing 或结构化完成日志。

## 14. 请求级首字节 Histogram 导出

新增 infergate_request_first_byte_seconds，labels 为 route/outcome，桶边界与
请求耗时一致。请求定稿时仅在 first_byte_sec is not None 时 observe；0.0 是
有效样本。读到首字节后失败的请求仍提交样本，但按最终失败 outcome 单独分组。
长流在终止前不会提交该样本，这是使用最终 outcome 分组的明确选择。

此指标起点是请求入口，包含 fallback，不能替代第 2 节仍待实现的尝试级
backend_first_byte_seconds，也不能称为 TTFT。普通响应、拒绝及首块前失败没有
首字节样本；新增 4 例单元测试并扩展请求集成断言，完整测试集 198 passed，
2 条已有依赖弃用警告。其余尝试/并发/健康指标和完整观测栈仍待接入。

## 15. 当前并发占用 Gauge

GatewayMetrics 显式接收当前 app 的 ConcurrencyLimiter，使用
[Gauge.set_function](https://prometheus.github.io/client_python/instrumenting/gauge/)
在抓取时读取 limit - available，导出 infergate_active_requests。不增加每请求
的 inc/dec 逻辑，不计等待队列，不把计数与请求 finish 绑定。

该值是当前占用名额的瞬时值：普通请求按原语义在响应发送前释放；流式请求
保持到关闭下游并释放名额。没有请求时也导出 0；请求 Counter/Histogram
仍只在有对应样本后出现时间序列。仍限单进程，不支持多进程共享配额或汇总。

新增 4 个用例验证名额变化、容量拒绝不增值、app 隔离，以及实际 app ASGI
流保持时通过 GET /metrics 读到 1、正常/读取失败/取消后恢复 0；既有请求集成
场景补充 Gauge 检查。完整测试集 202 passed，2 条已有依赖弃用警告。

## 16. 后端健康 Gauge

create_app 仅在 router 有 HealthManager 时调用 track_backend_health，将路由
配置中的 backend ID 去重后注册 infergate_backend_healthy{backend}。
每条 Gauge 用 partial 固定 backend ID，抓取时读取 HealthManager.is_healthy，
不复制状态、不发起 HTTP 探测。没有 HealthManager 时不导出该指标。

1 表示当前存储状态允许健康筛选通过；0 包括已标记不健康和初始化未探测。
该值沿用现有单进程路由状态，不表示即时存活证明，也不保证下一次调用成功。
backend labels 仅来自 app 构造时的配置；动态路由配置热更新不在本轮范围内。

新增 2 个用例：验证去重/状态变化/app 隔离，以及经现有 HealthChecker 探测后
HTTP scrape 输出与真实 app 选路一致。补无 HealthManager 的 app 不导出断言。
完整测试集 204 passed，2 条已有依赖弃用警告。backend-attempt 等仍待完成。

## 17. M3.2 后端尝试级指标：合同与作者预测

**状态：** 2026-10-01 普通 fallback 与流式终点情景已讨论；下一步为作者
独立尝试状态第一版，尚未接入尝试级指标。
这属于 [人机协作约定](../COLLABORATION_CONTRACT.md)中的 B 类指标定义与
埋点任务：作者先说明关键路径，AI 再补框架生命周期与 Prometheus 样板。

- **一次尝试的输入：** 选路成功后确定的配置 backend ID、该次实际下游调用。
  选路无候选、限流或并发拒绝均不创建尝试。不能用客户端请求数替代尝试数。
- **独立状态：** 每次尝试保存自己的单调时钟起点、终点、backend ID、结束
  原因和可选下游 HTTP 状态。已有 `RequestObservation.attempt` 只保存总次数，
  不足以恢复 A、B 各自的耗时与结果；尝试状态必须相互独立。
- **普通响应终点：** `backend_client.forward()` 完整读取下游响应或抛出
  `BackendTransportError` 时。连接失败的 A 此时结束；fallback 的 B 从其实际
  调用开始重新计时。
- **流式响应终点：** 下游 `open_stream()` 返回 headers 只表示打开成功，
  **不能**结束这次尝试。正常流结束、读取失败、取消或断开时，要等下游关闭
  完成（或关闭失败）后再定稿；若打开阶段就失败，则按打开异常结束。
- **状态与失败：** 尝试自己的 `completed`、`backend_http_error`、
  `transport_error`、`stream_error`、`cancelled`、`internal_error` 是有限分类。
  A 连接失败但 B 成功时，A 仍记失败、B 记成功，客户端请求只记一次成功。
  清理再失败不能覆盖先发生的读取失败或取消；清理失败另作有限事件。
- **指标草案：** `infergate_backend_attempts_total{backend,outcome}` 每次完成
  一个尝试计一次；`infergate_backend_attempt_duration_seconds{backend,outcome}`
  每次结束观察一个耗时。backend label 只取配置 ID，不用 URL、异常文本、
  调用方 key、model 或请求 ID。HTTP status 可在日志/trace 中另记；先不加入
  尝试级 label，避免把错误状态与尝试 outcome 混同。

首个作者预测情景：一个普通请求在 `t=0` 调用 A；A 于 `t=0.2` 连接失败；
`t=0.3` 调用 B，B 于 `t=1.1` 返回完整 HTTP 200。请先回答：请求级和
尝试级各增加几个样本？A、B 的尝试耗时与 outcome 分别是什么？从哪个动作
之后才允许记录 B 的样本？之后再讨论流式 headers 与清理边界。

### 本轮预测记录

作者正确回答请求级 1 个样本、尝试级 2 个样本，A 耗时 0.2 秒失败，B 耗时
0.8 秒成功。作者最初提出收到 headers 时记录 B，AI 解释实际调用开始才是
计时起点，普通响应完整读取后才提交样本；结果名称分别为 transport_error
与 completed。随后作者正确回答流式 B 应在 t=2.1 完成下游清理后结束计时，
而不是 t=0.4 拿到 headers 或 t=2.0 发完 body 时。

### 下一步最小实现（B 类，作者先写）

**暂缓：** 作者要求先整理 RequestObservation；恢复此任务时再核对接口与状态设计。

在 src/infergate/observability.py 增加独立 BackendAttemptObservation。
先只做开始/结束记录：构造参数为 backend_id、started_at；保存 backend_id、
started_at、outcome（初始 None）、total_time（初始 None）、is_finish（初始 False）。
finish(outcome, now) 首次保存结果与 now-started_at 并返回 True；重复调用
返回 False，不覆盖记录。先不修改 RequestObservation.start_attempt 或请求路径。

首轮核对示例：A 起点 0，0.2 以 transport_error 结束；B 起点 0.3，1.1 以
completed 结束。两者保持独立的 backend ID 与耗时，不能把请求级起点复用为
B 的起点。随后若再次结束 A，原结果和 0.2 秒耗时应保持不变。作者完成后进行
focused review 与共同测试，再补下游 HTTP 状态、流式失败与资源交接。

## 18. RequestObservation 定稿职责整理 — 2026-10-01

作者明确暂缓尝试级实现，要求先完成两项重构：

- 移除存储的 is_finish 布尔值，改为只读 is_finished 属性，从 total_time is not
  None 推导。0.0 耗时仍表示已定稿；body 完成状态 response_complete 保留。
- RequestObservation.finish(now) 自行选择最终 outcome：主要执行失败优先；
  否则 body 已完成才采用候选结果；缺少候选或 body 未完成则为 internal_error。
  reason 沿用现有规则。middleware 仅负责完整生命周期结束时调用并提交指标，
  不再读取多个状态字段组装 outcome。旧的 finish(outcome, time) 为历史接口。

调用处、指标读取和测试已同步。重复结束仍返回 False，首次结束后其他观测方法
不更新状态。6 个结果选择场景验证成功、拒绝、失败优先、原因清空、未完成 body
及缺失候选；另验证完成属性只读，并在零耗时情景检查重复定稿被拒绝。
原有流式读取/发送失败、取消、清理失败、延迟清理和指标单次提交测试继续通过。
完整测试集 211 passed，2 条已有依赖弃用警告。

## 19. 后端尝试生命周期与异常处理 — 2026-10-01

作者恢复尝试级实现，完成独立 BackendAttemptObservation、请求持有的
backend_attempts 列表、后端调用前创建、连接失败和普通响应返回后的定稿、
流式对象交接及关闭后的定稿。完成状态由 total_time is not None 推导，
请求尝试次数改为 attempts 属性，取列表长度；第 17 节的独立布尔值草案不再使用。

按作者授权，AI 补齐剩余异常处理：未移交的尝试由 endpoint 在 finally 中，
关闭已打开的下游流之后定稿；调用期间取消记 cancelled，其他执行异常记
internal_error。已有定稿结果不覆盖；流式移交后由 LimitedStreamingResponse
负责。没有实际调用的拒绝不创建尝试。

流式执行失败优先沿用 middleware 对发送端/断开的分类。ASGI 2.3 的断开
可能由 Starlette 内部任务组处理后正常返回，因此清理前仍需检查已记录的
failure_outcome。关闭失败仅在没有先前执行失败时改为 internal_error；
此前的读取失败或取消保留。定稿与并发名额释放使用 finally 保证执行。
与既有行为一致，关闭异常仍可能替代向外传播的执行异常，观测保留主要原因。

验证覆盖普通和流式调用期间真实任务取消/内部异常、移交前构造失败与延迟
关闭（含关闭异常）、ASGI 2.3/2.4 下读取失败、断开、任务取消、header/body
发送失败，以及 fallback 的独立结果。已有请求级指标语义保持不变。
完整测试集 225 passed，2 条已有依赖弃用警告。尝试级 Counter/Histogram
尚未接入；M3.2 未全部完成。

## 20. 尝试次数与耗时指标导出 — 2026-10-01

GatewayMetrics 注册 infergate_backend_attempts_total 和
infergate_backend_attempt_duration_seconds，labels 均为 backend/outcome。
耗时桶沿用请求 Histogram。record_request 在请求定稿后遍历 backend_attempts，
只提交已定稿尝试，每个对象分别 inc/observe；零耗时保留，未结束的对象不提交。
调用方仍通过请求 finish 返回 True 保证一次提交；record_request 本身不提供
重复调用去重。没有实际调用的拒绝不创建尝试时间序列。

计时终点与提交时间不同：尝试的 total_time 在各自结束时固定，但其 Counter
和 Histogram 统一在请求最终结束后导出。fallback 的 A 即使已连接失败，也需
等待 B 的流和清理结束后才可在抓取中看到；这与现有请求提交入口保持一致。
未来如需尝试一结束就立即可见，需另设尝试提交入口和单次提交约束。

验证确定性 fallback 样本 A=0.2 秒 transport_error、B=0.8 秒 completed，
请求一次/尝试两次、重复 finish 不重计、未定稿请求不提交、零耗时和 registry
隔离；普通/流式集成场景检查每个样本次数与其独立耗时，拒绝无尝试样本。
完整测试集 227 passed，2 条已有依赖弃用警告。尝试级首字节指标仍未导出，
M3.3 日志/tracing 和 M3.4 完整观测栈验收仍待实现。

## 21. 尝试级首字节计时与导出 — 2026-10-03

按作者请求，AI 完成 BackendAttemptObservation.record_first_byte(self, now)：
仅第一次且未定稿时保存 now-started_at，保留 0.0；finish 后不更新。
LimitedStreamingResponse 在读到非空 chunk 后、yield 前只读取一次单调时钟，
分别传给请求和当前尝试的 record_first_byte。空白字节有效，不 strip，不预取。
尝试计时从自己的调用起点开始，排除此前 fallback；请求级仍包含此前时间。

新增 infergate_backend_first_byte_seconds{backend,outcome} Histogram，桶与
既有耗时指标一致。请求定稿时，仅对已定稿且 first_byte_sec is not None 的
尝试提交样本，按该次尝试的最终 outcome 分组。首块后失败仍保留样本；
空流、首块前失败以及普通请求不采样。与第 20 节一致，长流请求结束前不提交。
测量是首个非空 body chunk 的读取边界，不是网络字节到达时刻或 TTFT。

验证不同请求/尝试起点、空块及空白块、无预取、零耗时、首次采样和定稿后
不更新、无请求观测对象时尝试仍可采样、发送失败后保留首字节、成功/失败/
取消最终分组，以及普通/流式 fallback 的真实 app 指标。完整测试集
239 passed，2 条已有依赖弃用警告。M3.3/M3.4 仍待实现。

## 22. 请求完成日志构造与提交 — 2026-10-03

作者在 RequestObservation 中增加 uuid4().hex 请求 ID。AI 按授权完成
build_request_log：固定请求字段及按 1 起序号排列的尝试详情，不记录请求头、
正文、后端 URL 或异常文本；None 和 0.0 保留。该函数仅构造数据，不输出。

middleware 在 finish 首次返回 True 后，向模块 logger 以 INFO 提交 JSON
完成记录，再独立提交指标。有无指标回调均可输出日志。日志构造或 handler
普通异常不影响业务及指标；指标异常及其告警 handler 故障也不替换原异常。
不捕获日志系统的 BaseException。此阶段尚未配置 runtime 的 INFO 输出
handler；部署环境需启用模块 INFO 级别才能看到完成日志。trace 关联待接入。

13 个新用例验证日志/指标独立故障组合、正常/异常/取消原结果、单条完成日志
和无指标回调时日志仍输出。完整测试集 252 passed，2 条已有依赖弃用警告。
下一步为运行入口日志配置，再接入 tracing；M3.3 尚未完成。

## 23. 运行入口日志输出配置 — 2026-10-03

新增 configs/logging.json，沿用当前安装的 Uvicorn 默认 server/access 配置，
为 infergate.observability 设置 INFO、仅消息 formatter、stderr handler 和
propagate=false。README 网关启动命令增加 --log-config configs/logging.json。
完成记录保持单行 JSON，服务器/访问日志保持原格式；指标故障告警为普通文本。
不在 create_app/create_runtime_app 中安装 handler，其他启动方式需显式配置。

独立子进程通过 Uvicorn Config 两次加载配置，实际调用 middleware 验证只输出
一条可解析的 JSON 完成记录；即使已有 root handler 也不重复，并验证服务器
日志仍正常输出。完整测试集 253 passed，2 条已有依赖弃用警告。
尚未做完整日志收集栈或 trace 关联；M3.3 tracing 和 M3.4 验收仍待完成。

## 24. 请求 span 与完成日志关联 — 2026-10-03

作者确认请求成功/A 失败/B 成功不矛盾，并确认尝试 span 应为请求 span 的
兄弟子项。当前先接入请求 span：依赖 OpenTelemetry API/SDK 1.45.0，
create_app 使用独立 TracerProvider，也允许注入测试 provider，不安装全局
provider。默认仅生成 span，无 exporter/processor，无网络上报或工作线程。
未来接入 exporter 时必须同时补充 provider shutdown 生命周期。

middleware 仅为业务 POST 创建 SERVER span，名称为固定路由；请求自己的
trace_id/span_id 为有效 context 的十六进制值，进入完成日志但不作为指标 label。
当前从空 context 开始，不接收上游 traceparent，不设置 ambient current span；
尝试子项和向后端传播 context 待下一步实现。未提供 tracer 时日志 ID 为 null。

请求定稿后从既有 outcome/次数/清理标志/耗时/首字节/发送状态填入有限属性，
再结束 span，之后独立提交日志和指标。不自动记录原始异常，避免异常文本泄露。
completed 标记 OK；rejected 保留 UNSET，并由 infergate.outcome/reason
表达拒绝；其他 outcome 标记 ERROR。该映射为本阶段网关定义，不等同于仅按
HTTP 状态判断成功。错误创建、写属性和结束 span 的普通异常均与业务隔离。

8 个新增测试验证成功/拒绝/流错误/取消结果、日志 ID 对应、清理前不结束，
以及 tracing 各阶段故障不替换原异常或阻止指标。完整测试集 261 passed，
2 条已有依赖弃用警告。未接入外部追踪服务，M3.3 尚未完成。

## 25. 后端尝试子 span — 2026-10-03

start_attempt 创建尝试对象后，通过请求 tracer 和显式请求 span context 创建
CLIENT backend_attempt span，属性仅含配置 backend ID、尝试序号和请求 ID。
不设置上一尝试为 current span，因此 fallback 的 A/B 为同一请求的兄弟项。
每次尝试的 span ID 写入完成日志 backend_attempts；不增加指标 label。

BackendAttemptObservation.finish 首次定稿时填入自己的最终 outcome、耗时及
可选首字节，并结束对应 span。completed 为 OK，其余尝试 outcome 为 ERROR。
各既有结束位置复用，普通响应完整读取后结束，流式读取/发送/关闭完成后结束，
清理失败仍保留主要失败。请求的 span 继续按整个请求最终结果独立定稿。
span 生命周期直接跟随尝试 finish，不等待请求指标的统一提交；默认无 exporter。

创建、写属性或结束 span 的普通异常不影响业务或尝试记录，重复 finish 不重复
结束 span。测试扩展真实 app 的 24 个普通/流式集成情景检查父项、trace ID、
结果与请求结束顺序，生命周期测试检查延迟关闭、读取失败、取消和清理错误，
新增 3 个故障隔离情景。完整测试集 264 passed，2 条已有依赖弃用警告。
context 的跨服务传播及外部 exporter/关闭生命周期仍待接入，M3.3 未全部完成。

## 26. 上游 trace context 提取 — 2026-10-05

作者正确确认 B 后端应接在 B 尝试 span 下。当前先完成入口提取：middleware
使用 TraceContextTextMapPropagator，仅从 ASGI headers 提取 traceparent 和
tracestate（名称不区分大小写），以显式空 Context 为默认来源。有效时网关
请求 span 延续上游 trace ID，父项为远端 span；缺失或无效时创建新 trace。
不依赖 ambient current span，不提取 baggage，不写入原始请求头/正文。
request_id 仍由网关独立生成。采样决策沿用 SDK 默认 ParentBased 行为。

5 个新增测试覆盖缺失、非法格式、零 trace ID、零父 span ID 和有效头，检查
有效父项的 remote 标志、tracestate、A/B 兄弟关系和日志 ID；span 属性不包含
业务 key 或 baggage。完整测试集 269 passed，2 条已有依赖弃用警告。
向后端注入当前尝试的 context 尚未实现，外部 exporter/关闭生命周期仍待接入。
