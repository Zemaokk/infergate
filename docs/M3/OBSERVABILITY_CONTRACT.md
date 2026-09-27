# M3.1 可观测性合同草案

**状态：** 2026-09-26 已完成一轮情景讨论，确认范围见第 5 节；其余接口与
指标设计仍为草案；当前已接入请求生命周期最终结果，验证进度见第 8–11 节。

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
