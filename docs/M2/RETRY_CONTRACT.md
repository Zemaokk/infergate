# M2.3 Retry / Fallback 行为合同

**状态：** 第一版已实现、验证，并完成作者 teach-back
**分类：** A 类核心任务；作者先判断重试条件并写第一版，AI 协助异常映射和测试

## 1. 第一版策略

最多进行 **2 次下游尝试，包括第一次**：首次连接失败后，可以选择另一个支持
同一 model、健康且本请求未尝试过的 backend。两次尝试串行执行，不并行发出，
不重试同一个 backend，不切换模型、不改变 payload。

本阶段将这次重新尝试称为 retry，将改选其他 backend 称为 fallback。它们是
同一个有界流程，不各自拥有一份重试预算。第一版不增加等待队列、退避调度、
hedging 或第三方重试库，也不额外开启 HTTPX transport 内部重试。

## 2. 为什么不能只判断“还没收到响应”？

收到响应前的 read timeout，可能发生在 backend 已收到请求并开始生成之后。
重新发送可能导致重复计算。写入失败也不能仅凭异常判断 backend 收到了多少。
因此，“客户端响应尚未提交”只是必要条件，不能单独作为重试许可。

HTTPX 将 ConnectError/ConnectTimeout、ReadError/ReadTimeout、写入错误和
PoolTimeout 区分开；其 transport 内建连接重试也仅覆盖 ConnectError 和
ConnectTimeout。参见 [异常分类](https://www.python-httpx.org/exceptions/) 与
[连接重试](https://www.python-httpx.org/advanced/transports/#http-transport)。
下面的矩阵是本项目的保守策略选择，并非所有系统必须采用的规则。

| 事件 | 第一版策略 | 理由 |
| --- | --- | --- |
| `ConnectError` / `ConnectTimeout` | 满足预算与候选条件时允许 fallback | 连接建立阶段失败；并非保证下一次能成功 |
| `PoolTimeout` | 不重试 | 本地连接池压力不靠增加一次尝试解决 |
| `ReadError` / `ReadTimeout` | 不重试 | backend 可能已开始或完成执行 |
| `WriteError` / `WriteTimeout`、协议错误等 | 不重试 | 无法保证请求未被处理，默认不扩大白名单 |
| backend 返回 429、500、502、503 等 HTTP 状态 | 原样转发 | 第一版保持现有 HTTP 透传语义 |
| 客户端响应已提交后的任何流错误 | 不重试 | 无法撤回状态和已发送内容 |
| 请求取消或客户端断开 | 不重试 | 终止工作并清理，不能转换成重试机会 |

该分类依赖底层 transport 正确报告失败阶段；不能把任意自定义异常都标成
“连接失败”，也不由此承诺一般意义上的 exactly-once 执行。

## 3. 输入、状态与输出

- 输入：model、原始转发 payload、是否 streaming、错误类别、尝试预算。
- 每请求状态：尝试次数、已尝试 backend ID 集合、最后一次失败及 backend。
  这些状态不跨请求共享；现有 router 游标、健康状态和 admission 控制器仍共享。
- 成功：返回实际服务 backend 的 status/body/Content-Type 和
  `X-InferGate-Backend`，继续遵守原有 streaming 生命周期。
- 第一次选路就没有候选：保留 `503 no_backend_available`，不发下游请求。
- 已发生传输失败，且不能继续尝试：保留 `502 backend_transport_failure`，
  header 标识最后实际尝试的 backend。没有备用 backend 不能把该失败改成首次
  无候选的 503，也不能反复回到刚失败的 backend。
- 第二次返回 HTTP 错误：原样转发，不增加第三次尝试。

仅本次请求排除已经尝试的 backend；不因这一次连接失败直接修改全局健康状态，
后续健康探测仍按 M1 合同控制全局状态。

## 4. 与配额、并发和 timeout 的关系

一个客户端请求只通过一次 token bucket、占用一个并发名额。fallback 不再次
扣令牌，不另取名额，也不在两次尝试之间释放。最终失败由 endpoint 释放；成功
获得流式响应后沿 M2.2 的所有权交接释放。取消仍向上传播。

每次尝试沿用现有 HTTPX 分阶段 timeout。最大尝试次数为 2，不等于整个请求
总时长有固定上限：M1 的 read timeout 是等待下一段数据的超时，仍未设置总生成
时长。不要把“次数有界”写成“端到端时长有界”。

## 5. 已实现的接口

1. `BackendClient` 把传输错误包装为 `BackendTransportError`，通过
   `raise ... from e` 保留原异常；`retryable` 默认为 False，仅连接错误置 True。
2. `RoundRobinRouter.select()` 支持按本次请求的 backend ID 集合排除候选，
   同时保留健康筛选与游标规则。没有传排除集合时保持原行为；不论是否启用健康
   管理都必须执行排除。没有候选时游标不推进。
3. 重试循环位于一次 admission 与资源释放的范围内，不能把整个 endpoint
   重跑一遍。首版不接管已开始执行的 `LimitedStreamingResponse`。

## 6. 验证清单

- A 连接失败、B 成功：两次下游尝试，返回 B 的响应和身份。
- A 和 B 都连接失败：最终 502，标识 B；无第三次尝试。
- 只有 A 或其他 backend 不健康：A 失败后结束，不重新选择 A。
- read/write/pool 失败、HTTP 错误、流式提交后失败和取消：不 fallback。
- 同一次请求只扣一个令牌并持有同一并发名额，最终释放恰好一次。
- 普通与 streaming 的连接失败路径均可 fallback；流式中途失败保持清理行为。
- 第一次无候选与失败后无备用候选的状态码不同，分别验证。
- 并发请求各自持有尝试记录，排除集合不互相污染；已有测试保持通过。

## 7. 作者预测与完成记录

假设 A、B 均健康、支持同一 model，最多 2 次尝试，第一次选中 A：

1. A 抛出 ConnectError，能否尝试 B？总共扣几个令牌、占几个并发名额？
2. A 已收到请求，但等待响应头时发生 ReadTimeout，是否尝试 B？为什么？
3. A 直接返回 HTTP 503，第一版如何处理？
4. A 连接失败，但 B 此时不健康，最终返回什么？是否再次尝试 A？

作者已完成上述预测与实现，并解释了第 4 项应返回 502、保留 A 的失败且不重试 A。
最终集成证据见 [M2 验收记录](ACCEPTANCE.md)，包括并发请求的尝试记录独立性
以及流式 body 已开始后不 fallback 的专项验证。
