# M3.1 可观测性合同草案

**状态：** 2026-09-26 已完成一轮情景讨论，确认范围见第 5 节；其余接口与
指标设计仍为草案，尚未接入观测代码。

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
