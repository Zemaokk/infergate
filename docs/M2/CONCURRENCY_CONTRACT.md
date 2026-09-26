# M2.2 全局并发上限行为合同草案

**状态：** 第一版实现与自动化验证通过；待作者完成流式清理包装的 teach-back
**分类：** A 类核心任务；作者先写状态更新与生命周期控制，AI 协助集成和测试

## 1. 第一版范围

第一版采用立即拒绝策略，等待队列容量为 0。所有 key、model 和 backend 共用一个
进程内的并发预算，普通请求与 streaming 都计入。健康探测不占名额。
这里限制的是正在处理的推理转发任务，不是 TCP 连接数量。

应用创建时初始化并注入一个共享控制器。边界是单进程、单事件循环；不承诺
多 worker 共用同一计数，也不承诺各 key 的调度公平性。

## 2. 输入、状态、输出

- 输入：配置的正整数上限 `limit`，一次获取名额或释放名额的操作。
- 状态：作者第一版使用剩余名额数 `available`，初始为 `limit`。
  已占用名额数为 `limit - available`，下文情景中的 `active` 指这个派生数量。
- 获取：容量未满时占用一个名额并返回成功；已满时立即返回失败，不等待。
- 释放：只有成功获取过名额的请求可以释放，每次成功获取必须且只能释放一次。
- 不变量：`0 <= available <= limit`；获取成功减 1，释放加 1。
  检查与占用必须作为一次不可交错的更新。

可先使用这个接口表达目标，方法体由作者完成：

```python
class ConcurrencyLimiter:
    def try_acquire(self) -> bool: ...
    def release(self) -> None: ...
```

## 3. 请求路径与错误响应（建议方案）

```text
请求体和 key 校验
  -> per-key token bucket
  -> 获取全局名额，失败则立即拒绝
  -> 选择健康 backend
  -> 转发并在任务结束时释放名额
```

全局容量满时返回 HTTP `503`，`type="gateway_error"`，
`code="concurrency_limit_exceeded"`，`param=null`，不选路、不调用 backend。
它与 per-key 配额不足的 `429 rate_limit_exceeded` 分别表示两种拒绝原因。

按上述顺序，全局容量拒绝发生在 token bucket 扣费之后，令牌不退还；无有效
key 或已被 per-key 限流的请求不获取全局名额。作者在实现前确认这个顺序。

## 4. 名额生命周期

- 无可用 backend、打开下游失败、取消、异常：已获取的名额必须释放。
- 普通请求：下游响应体已完整读取，或转发失败/取消，结束下游转发任务后释放；
  不延长到缓冲响应向客户端发送完成。第一版不限制这段发送的并发数。
- Streaming：不能在 endpoint 返回 `StreamingResponse` 时释放；迭代与下游
  response 清理结束后才释放。正常耗尽、读取失败、断开与取消都要覆盖。
- 名额从 endpoint 转交给流式响应生命周期时，必须明确谁负责释放；包括 body
  iterator 尚未开始、响应发送就失败的路径。具体接入方式由作者先预测，随后
共同用 ASGI 测试验证，不只依赖正常 generator 耗尽测试。
- 下游清理本身抛异常时，名额也不能永久泄漏；取消仍按取消传播。

## 5. 最小验证集合

1. 上限 2 时连续获取三次，第三次拒绝；释放一次后可以再获取一次。
2. 两个不同 key 共享同一并发上限；拒绝不选路、不触达 backend。
3. 用受控下游保持请求未结束，证明名额确实跨越等待阶段。
4. 普通响应成功、backend HTTP 错误、传输失败、无可用 backend 后容量恢复。
5. Streaming 返回响应对象后仍占用名额；结束、错误、取消、客户端断开后恢复。
6. 流式响应在迭代开始前发送失败，以及下游关闭异常，都不会泄漏或重复释放。
7. 原有测试通过，原有 per-key 限流与错误映射保持有效。

## 6. 作者第一项预测

假设 `limit=2`，所有请求均已通过 key 和速率校验：

1. A 是仍在输出的 streaming 请求，B 是等待 backend 的普通请求，`active` 是多少？
2. C 此时到达，返回什么？状态是否改变？
3. B 遇到传输错误后，D 到达，能否进入？
4. A 的 endpoint 早已返回，但流还没结束。为什么不能把 endpoint 返回当作释放点？

先回答预测并确认快速拒绝策略，再实现独立的控制器；通过小测试后再接入请求
生命周期，避免把计数逻辑与 streaming 资源所有权同时调试。

## 7. 实现与验证记录

作者完成剩余名额计数、runtime 注入、快速拒绝和 endpoint 的 `handed_off` 分支。
AI 补充 `LimitedStreamingResponse.__call__` 的框架包装：响应执行结束后关闭下游，
再在嵌套 finally 中释放名额。关闭过程使用 AnyIO cancellation shield，避免外部
取消域反复中断清理；pytest 仍使用原有 pytest-asyncio。

`handed_off=False` 时 endpoint 负责释放，已打开的流在构造响应失败时也由它关闭；
交接后仅响应包装负责关闭和释放，body iterator 不再另行释放。

完整测试集 **79 passed**。`tests/test_concurrency_limiter.py` 验证容量耗尽和恢复；
`tests/test_app.py` 使用受控下游与直接 ASGI 调用验证普通/流式占用、跨 key 拒绝、
错误和取消、断开、headers/body 发送失败、关闭异常及响应构造失败。
释放调用计数用于检查重复释放，避免控制器的 `min()` 上界掩盖这类错误。

这些是进程内 mock/ASGI 测试，不构成真实网络断开、负载性能或跨进程验证。
本轮 runtime 实验上限为 2；M2.2 完成前，作者还需解释为何 generator 未开始时
响应包装仍能负责清理，以及内层 finally 如何保证关闭异常后释放名额。
