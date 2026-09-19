# M1 工作计划：Streaming 与后端健康

**状态：** M1.1 streaming contract 已接受，进入 first attempt  
**模式：** Learning mode  
**完成标准：** 流式响应不会在网关中完整缓冲；单个后端失效时，健康后端仍能
服务请求。

## 1. 范围

M1 只包含：

- Chat Completions 的 streaming passthrough；
- 有明确边界的下游请求 timeout；
- backend health check；
- unhealthy backend 暂时退出路由；
- 客户端断开时取消下游请求并释放连接。

以下内容仍不属于 M1：

- retry 和 fallback；
- rate limit、并发上限和排队；
- metrics、tracing 和完整 structured logging；
- Responses API adapter；
- 动态配置和多进程共享健康状态。

## 2. 已确认的框架事实

- HTTPX 的普通请求方法会读取完整响应；流式下游请求需要使用 streaming mode，
  并迭代响应字节。
- 手动使用 HTTPX streaming mode 时，所有退出路径最终都必须关闭下游 response，
  否则连接不能可靠地回到连接池。
- FastAPI/Starlette 的 `StreamingResponse` 可以消费 async iterator，并把每个 chunk
  逐段发送给客户端。
- streaming generator 必须到达可取消的 `await`，取消才能及时传播。
- Starlette 提供客户端断开检测，但是否需要显式轮询，要由实现方式和断开测试
  共同决定，不能只凭 API 存在就加入轮询。

参考：

- [HTTPX async and streaming](https://www.python-httpx.org/async/)
- [FastAPI custom and streaming responses](https://fastapi.tiangolo.com/advanced/custom-response/)
- [Starlette requests and disconnect detection](https://www.starlette.io/requests/)

## 3. Task 顺序与协作边界

### M1.1 Streaming passthrough contract（A 类）

当前产物：[STREAMING_CONTRACT.md](STREAMING_CONTRACT.md)。作者已完成请求路径
预测、最小伪代码和资源生命周期 teach-back；下一步是 first implementation。

作者先完成：

1. 用自然语言预测一条 `stream: true` 请求从客户端到 backend、再返回客户端的
   完整路径。
2. 说明下游 response 由谁持有、何时关闭。
3. 说明 backend 在发送 headers 前失败和发送部分 body 后失败有什么区别。
4. 写最小伪代码，不要求框架语法完全正确。

AI 随后：

- review 一个最关键的 invariant；
- 补充 HTTPX/FastAPI 的框架细节；
- 与作者共同定稿 contract 和测试边界。

### M1.2 Timeout 与 cancellation contract（B 类）

共同明确：

- connect、pool、write、read timeout 是否分别配置；
- streaming read timeout 表示什么；
- 客户端断开如何终止下游读取；
- 取消和 transport failure 是否进入相同错误映射；
- headers 已发送后发生失败时还能做什么、不能做什么。

### M1.3 Backend health state（A 类）

作者先定义：

- 最小状态集合；
- 哪些事件触发状态变化；
- 健康检查频率和超时；
- backend 恢复条件；
- router 如何读取可选 backend 集合；
- 并发访问状态时的同步边界。

在合同接受前，不实现 health-aware router。

### M1.4 集成与验证（B 类）

至少验证：

- 首个 chunk 在完整响应结束前到达客户端；
- chunk 内容与顺序不被修改；
- 下游响应在成功、失败和取消路径都被关闭；
- 客户端断开后下游工作停止；
- unhealthy backend 不被选择；
- backend 恢复后重新进入选择集合；
- 一个 backend 失效时另一个健康 backend 仍能服务请求；
- M0 非流式路径仍全部通过。

## 4. M1.1 作者预测模板

开始实现前，请先补完下面四项：

1. **输入：** `stream: true` 请求进入 endpoint 后，哪些字段由 gateway 校验，哪些
   内容必须原样交给 backend？
2. **状态：** streaming 期间哪些对象仍然存活，分别由谁持有？
3. **输出：** gateway 在什么时候可以把响应 headers 和第一个 chunk 发给客户端？
4. **失败：** 如果 backend 在第一个 chunk 前失败，和已经发出若干 chunk 后失败，
   客户端分别会看到什么？

可以使用下面的数据流骨架，但先不要填框架代码：

```text
receive request
  -> validate streaming request
  -> select eligible backend
  -> open downstream streaming response
  -> ______________________________
  -> ______________________________
  -> close downstream response on every exit path
```

## 5. 暂缓的 M0 技术债

以下问题已记录，但按当前决定不在 M1 kickoff 中修复：

- 同一个 runtime app 不能经历第二次 lifespan startup；
- 安装后的 `infergate` console command 仍是占位行为。

如果它们开始阻塞 M1 测试或运行，再作为独立小任务处理，不与 streaming 或 health
状态机混在同一提交中。
