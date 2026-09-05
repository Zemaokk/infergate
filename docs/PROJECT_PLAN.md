# InferGate 项目蓝图

> 状态：Living document（随着实现更新，但不随意扩大范围）

项目中的作者与 AI 分工、提示阶梯和交付保护线见 [COLLABORATION_CONTRACT.md](COLLABORATION_CONTRACT.md)。

## 1. 一句话目标

InferGate 是一个位于客户端与 LLM 推理服务之间的轻量级网关：它统一接收 OpenAI-compatible 请求，并负责路由、流量控制、故障处理和可观测性，而不负责执行模型推理。

```text
Client
  |
  v
InferGate
  |-- API adapters
  |     |-- /v1/chat/completions (M0)
  |     +-- /v1/responses (planned)
  |-- request validation
  |-- routing
  |-- rate limiting / backpressure
  |-- retry / fallback
  |-- metrics / tracing
  |
  +--> Model Backend A (mock -> vLLM)
  +--> Model Backend B (mock -> vLLM)
```

## 2. 要解决的问题

直接调用单个模型服务在本地实验中足够，但当用户、模型实例和请求数量增加后，会出现一组网关层问题：

- 应该把请求发给哪个健康的后端？
- 后端繁忙时应该继续接收、排队还是拒绝请求？
- 某个后端失败时，能否安全重试或切换？
- 如何限制单个调用方对共享资源的占用？
- 如何测量排队时间、首 token 延迟、总延迟和吞吐量？
- 如何在不改变客户端接口的情况下替换模型后端？

InferGate 的价值是集中解决这些问题，让客户端不需要了解后端实例的数量、地址和运行状态。

## 3. 系统边界

### InferGate 负责

- 提供一个精简的 OpenAI-compatible HTTP API
- 维护后端实例的状态并选择后端
- 转发普通响应和 streaming 响应
- 实施限流、并发上限和有界等待
- 处理超时、可重试错误和 fallback
- 记录请求、token、延迟、错误和队列指标
- 提供可复现的 benchmark 工具

### InferGate 不负责

- 训练、微调或量化模型
- 实现 Transformer、attention 或 KV cache
- 替代 vLLM、llama.cpp 等 inference engine
- 第一阶段支持 Kubernetes、自动扩缩容或多机部署
- 第一阶段实现完整的 OpenAI API
- 在没有数据前宣称某种路由策略性能更好

## 4. 核心请求流程

每个请求都应当经历一条可以解释和测量的路径：

```text
receive
  -> validate
  -> admit or reject
  -> select a healthy backend
  -> forward
  -> stream or return response
  -> record outcome
```

实现任何功能时，都回答四个问题：

1. 输入是什么？
2. 组件持有什么状态？
3. 输出是什么？
4. 失败时发生什么？

## 5. 组件划分

| 组件 | 单一职责 | 典型状态 |
| --- | --- | --- |
| API layer | 校验请求并返回兼容响应 | 尽量无状态 |
| Backend client | 与一个模型后端通信 | URL、timeout |
| Backend registry | 保存后端的运行状态 | healthy、active requests |
| Router | 根据状态选择一个后端 | round-robin cursor 等 |
| Admission control | 决定接收、等待或拒绝 | 并发数、queue depth |
| Rate limiter | 限制调用方的请求速率 | tokens、last refill time |
| Observability | 记录系统行为 | metrics、trace context |
| Benchmark client | 产生可重复的负载 | concurrency、workload |

组件应当通过小而明确的接口协作，避免把所有逻辑都写进 API handler。

## 6. 迭代路线与验收标准

### M0：最小转发闭环

范围：

- 两个 mock backends
- 一个 `/v1/chat/completions` endpoint
- round-robin routing
- 非 streaming 请求转发
- 最小自动化测试

完成标准：连续请求会在两个后端之间轮换；后端身份可从响应中验证；测试可以重复证明这一行为。

### M1：流式传输与后端健康

范围：

- streaming passthrough
- 请求 timeout
- health check
- unhealthy backend 暂时退出路由
- 客户端断开时取消下游请求

完成标准：流式响应不会被网关完整缓冲；单个后端失效时，健康后端仍能服务请求。

### M2：负载保护与公平性

范围：

- per-key token bucket rate limiter
- 全局并发上限
- bounded queue 或明确的快速拒绝策略
- retry / fallback policy

完成标准：过载行为是有限且可预测的；不会因为无限等待或无限重试拖垮网关。

### M3：可观测性

范围：

- Prometheus metrics
- structured logging
- OpenTelemetry tracing
- Grafana dashboard

重点指标：

- request count 和 error rate
- end-to-end latency（p50 / p95 / p99）
- queue time
- time to first token（TTFT）
- output tokens/s
- active requests 和 queue depth
- backend health 与路由分布

完成标准：能够从指标和 trace 判断延迟发生在排队、网关还是模型后端。

### M4：真实后端与可复现实验

范围：

- 接入至少一个 OpenAI-compatible inference backend，例如 vLLM
- 增加 `/v1/responses` 的最小非流式 adapter，复用 shared gateway core
- Docker Compose 本地启动
- benchmark workload
- CI、使用说明和架构说明

实验变量：

- concurrency
- prompt length / output length
- routing strategy
- cache on / off（如果实现缓存）

完成标准：第三方可以按文档启动系统、复现实验，并从原始结果生成性能图表。

## 7. 第一版成功的定义

项目不以“功能数量最多”为成功标准。第一版成功需要同时满足：

- Correct：请求和 streaming 内容没有被错误修改
- Bounded：并发、排队、timeout 和 retry 都有明确上限
- Observable：关键阶段有指标，错误可以定位
- Testable：路由与失败行为能用 mock backend 稳定复现
- Explainable：作者能够说明每个状态、策略和 trade-off
- Reproducible：启动与 benchmark 步骤可由其他人重复执行

## 8. 实现原则

1. 先用 mock backend 验证网关语义，再接真实 GPU 服务。
2. 每个 milestone 都保持可运行、可测试，不积累一个“大爆炸式”集成。
3. 先做最简单且可验证的策略，再用 benchmark 决定是否增加复杂度。
4. 明确区分 gateway latency、queue latency 和 backend latency。
5. retry 必须有条件和次数上限；streaming 已经输出后默认不能透明重试。
6. 代码中的共享可变状态必须明确其并发访问方式。
7. AI 可以生成样板和协助检查，但核心状态机、路由和流控逻辑由作者理解并主导实现。

## 9. 当前决策

| 决策 | 选择 | 原因 |
| --- | --- | --- |
| 实现语言 | Python | 已有基础，适合先学习异步服务与系统设计 |
| Web framework | FastAPI | 类型清晰，支持 async 与 streaming |
| 下游 HTTP client | HTTPX | 支持 async 和 streaming |
| 第一种路由 | Round-robin | 状态简单，行为容易验证 |
| 初始后端 | Mock server | 无需 GPU，可以构造延迟和失败 |
| API 策略 | M0 实现 `/v1/chat/completions` 子集；M4 增加 `/v1/responses` 非流式 adapter | 先学习网关核心，再验证核心与公开协议解耦；见 [ADR-0001](decisions/0001-api-surface.md) |

## 10. 当前下一步

只开始 M0。先定义 Chat Completions 的最小请求与响应，再分别实现 mock backend、backend client 和 round-robin router，最后由 API layer 把它们连接起来。当前不实现 Responses API，但核心模块不得依赖 Chat Completions 专属字段。
