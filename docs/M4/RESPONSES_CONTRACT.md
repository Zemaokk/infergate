# M4.3 最小非流式 Responses adapter：合同准备

**状态：2026-10-06，最小字段与共享路径合同已整理，待作者预测及第一版。** B 类：共同定义合同，作者写关键路径
第一版，AI focused review 与测试；文档和兼容环境准备为 C 类。

## 已确定的架构边界

沿用 [ADR-0001](../decisions/0001-api-surface.md)：增加 POST /v1/responses 的
最小非流式入口；请求发往后端同名接口，响应沿同一种协议返回。不进行
Responses 与 Chat Completions 语义转换。复用已有路由、健康、per-key 配额、
全局并发和 fallback 状态，两个入口不能各自创建一份容量或限流器。

当前真实 vLLM 0.8.5 的 OpenAPI 未声明 /v1/responses，证据见
[模型接口清单](evidence/model-manifest-2026-10-06.json)。后续可先用受控 mock
验证网关行为；真实双协议支持仍需选择并实际验证兼容后端/版本。不能仅凭
网关返回模拟响应或 Chat 接口成功就宣称真实 Responses 接入完成。本次不升级
正在运行的模型服务。

## 当前需要解耦的位置

检查现有代码发现：

- app.py 的模型校验和 endpoint 依赖 ChatCompletionRequest；后端 path 固定为
  /v1/chat/completions，业务控制流也在这个 endpoint 内。
- BackendClient 已接收 path 参数，可继续复用。
- RequestObservationMiddleware 的匹配条件、span 名称和 http.route 固定为 Chat。
- GatewayMetrics.record_request 的 route 标签固定为 Chat。

因此不能只复制 endpoint 并更换 URL：应抽取协议无关的请求执行路径，将
已校验正文、模型路由 key、后端 path 和 stream 选择由薄 adapter 交给它。
观测须保存实际入口 route，同时维持现有定稿时机、清理和尝试计数语义。
这些是待作者设计的边界，并未指定最终函数签名或代写实现。

## 合同定稿与验收顺序

1. 核对目标后端的实际 Responses 接口，定义最小支持字段、类型和未知字段
   策略，以及不支持 streaming、状态管理和工具能力时的明确错误行为。
   本文件尚未承诺具体请求 schema 或完整 OpenAI API 兼容。
2. 作者预测：两个入口如何共用同一个 token bucket 与并发名额；一个入口
   占满容量时另一个入口应如何响应。确定共享执行路径的输入与资源所有权。
3. 作者抽取最小共享路径，保持全部 Chat 测试通过，再接入第二个 adapter。
4. 补同协议正文/path 透传、错误校验、跨入口共享限额、失败释放、健康路由、
   正确 route 日志/指标和尝试次数测试。
5. 真实兼容后端直接请求与网关请求分别验证，更新支持矩阵，再完成 teach-back。

初始准备只定位了字段与共享路径边界；本次补充的具体小步见下文。
尚未进入核心实现，benchmark workload 仍由作者在 M4.4 先设计。

## 最小字段子集（本项目的收窄设计）

2026-10-06 使用 OpenAI Docs 核对
[Create a model response](https://developers.openai.com/api/reference/python/resources/responses/methods/create)。
官方支持字符串或结构化 input；instructions 是指令文本，max_output_tokens
限制生成 token，stream 控制 SSE，store 控制后续检索所需的保存。
以下类型、必填性及限制是 InferGate 第一版设计，不等于完整官方 schema，
也不证明当前 vLLM 支持这些字段。

| 字段 | 本项目第一版规则 |
| --- | --- |
| model | 必填、严格字符串；strip 后不能为空，用原值路由与转发 |
| input | 必填、严格字符串；strip 后不能为空，保留原始文本；暂不接受数组 |
| instructions | 可省略；提供时为严格字符串，允许空字符串，不接受 null |
| max_output_tokens | 可省略；提供时为严格整数且 >=16，不接受 bool 或 null |
| stream | 可省略，缺省 false；提供时须严格 bool 且为 false |
| store | 必填，须严格 bool 且为 false |
| background | 可省略，缺省 false；提供时须严格 bool 且为 false |

官方 store 省略时默认 true。项目先要求显式 store=false，以表达无保存的
请求意图并保持正文透明转发；网关不代填、不悄悄改 true 为 false，也不承诺
后端实际上没有保存数据。实际兼容后端仍需单独验证。

顶层使用 extra=forbid：未列出的字段全部 400，包括 tools、previous_response_id、
conversation、text、reasoning、temperature 等。这是明确的首版支持边界，
不是认为它们在官方接口中非法。所有 schema 错误复用已有 400 格式及
invalid_request_body 观测原因；发生在 key 验证、扣 token、获取并发名额及
后端尝试之前。暂不为不同不支持字段增加独立错误码。

最小请求示例（model 为配置中的实际路由 key）：

```json
{"model":"responses-model","input":"Explain an HTTP gateway.","store":false}
```

省略的 stream/background 不注入转发正文；显式字段经校验后保留。
后端 path 固定为 /v1/responses；响应状态、Content-Type 和正文使用既有
非流式透传方式，不组装 output、不把后端响应换成 Chat 的 choices。
后端 HTTP 错误沿用原样转发且不 fallback，连接阶段失败沿用既有有界策略。
HTTP 200 不等于 Response 内部 status 必然 completed；网关仍按既有 HTTP
完成语义记录，不据此声称生成完整。

## 当前第一小步：只抽取 Chat 的共享执行路径

作者先在 app.py 的 create_app 内抽取一个异步 execute_gateway_request。
函数位于与 endpoint 相同的闭包中，复用既有 router、backend_client、
key_limiter 和 concurrency_limiter；不要在函数内新建这些对象。

建议输入：http_request、x_infergate_key、model、payload、backend_path、stream。
输出仍为 Response（流式分支仍为 LimitedStreamingResponse）。共享函数不接收
ChatCompletionRequest，也不读取 messages/input/choices/output。

Chat endpoint 留下三件事：FastAPI 请求模型校验、准备 model/payload/stream，
调用共享函数并传入 /v1/chat/completions。model_dump(exclude_unset=True)
保持原有字段省略语义。迁移原 endpoint 的 key 校验、限流、并发获取、路由、
尝试记录、转发、响应构造与 finally 清理，保持执行顺序；不要复制两份流程。

资源边界保持：未移交流时共享函数负责关闭和释放；流式响应构造成功后移交给
LimitedStreamingResponse，后者在发送/清理结束后释放。请求观测继续由中间件
定稿，不能在共享函数提前结束。

本小步暂不增加 Responses endpoint、请求模型、mock 或远程后端，不改观测
route。验收为现有 336 项测试全部通过，特别是取消、失败、fallback 和流清理
行为不变。通过后再加入 Responses schema 与实际 route 的观测支持，最后注册
第二个 endpoint 并验证跨入口共享容量。

作者写代码前先预测：

1. 两个 endpoint 共用同一 key 的 token bucket 时，额度会分别计算还是合计计算？
2. Chat 流仍占用最后一个并发名额时，schema/key 合法且 key 额度充足的
   Responses 请求应返回什么，是否访问后端？

当前只完成文档设计和代码边界检查，未实现或验证新的 Responses 行为。

作者预测已完成：同一个 key 的额度应合计计算；Chat 流占满并发名额时，
格式/key 合法且额度充足的 Responses 请求不访问后端，返回 503，消息为
Exceed global concurrency limit.。AI 确认并补充既有错误码
concurrency_limit_exceeded。该预测符合共用控制器的合同，进入作者抽取
共享执行函数第一版；尚未实现第二接口，不能把预测记为跨接口实测。

作者完成共享函数第一版，AI review 指出 endpoint 缺少 await，以及误用
http_request.stream 方法作为布尔值。作者修正为 return await 和 request.stream
后复核通过：完整 336 passed，2 条已有依赖弃用警告，差异检查通过。
共享函数复用原控制器并参数化正文、model、stream 和后端路径，原有取消、
fallback、流清理及观测测试通过。当前仅验证 Chat 抽取，Responses endpoint
尚未实现，跨接口共享限额与 route 观测仍待下一步验证。
