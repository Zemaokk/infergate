# M4.3 最小非流式 Responses adapter：合同准备

**状态：2026-10-06，准备阶段，未实现。** B 类：共同定义合同，作者写关键路径
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

当前仅完成合同准备。下一小步是定义非流式字段子集与共享执行边界，尚未进入
核心实现；benchmark workload 仍由作者在 M4.4 先设计。
