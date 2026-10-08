# ADR-0001：以 Chat Completions 建立基线，并规划 Responses adapter

- 状态：Accepted
- 日期：2026-09-04
- 决策者：项目作者

## 背景

InferGate 需要选择第一版公开 API。OpenAI 官方文档建议新项目优先尝试 Responses API，以使用最新的平台能力；Responses API 还支持 conversation state、reasoning configuration、built-in tools、MCP tools 和更丰富的 response status。与此同时，Chat Completions 仍是官方文档中的受支持接口。

参考：

- [Create a model response](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [Chat Completions](https://developers.openai.com/api/reference/cli/resources/chat/subresources/completions)

InferGate 的首要目标不是构建依赖 OpenAI 托管能力的 agent application，而是学习和实现模型请求之前的基础设施层，包括 routing、health、backpressure、retry 和 observability。

如果第一步直接实现 Responses API 的完整语义，`input/output items`、状态管理、工具调用和多种 streaming events 会扩大 M0 的学习范围。相反，如果项目永久只支持 Chat Completions，又会限制它对现代接口的适应性。

## 决策

1. M0 使用 `POST /v1/chat/completions` 的最小非流式子集建立端到端转发闭环。
2. routing、backend registry、admission control、rate limiting 和 observability 必须与具体公开 API 解耦。
3. Chat Completions 和 Responses 分别由薄的 API adapter 处理；shared gateway core 不依赖 `messages`、`input`、`choices` 或 `output` 等协议专属结构。
4. 第一版不在 Chat Completions 与 Responses 之间进行语义转换。请求和响应沿同一种协议转发，避免网关虚构后端不支持的能力。
5. M4 增加 `POST /v1/responses` 的最小非流式 adapter，用它验证 shared gateway core 可以被第二种接口复用。
6. Responses streaming 属于后续扩展，不阻塞第一版交付；只有在 non-streaming adapter 通过兼容性测试后才进入实现。
7. README 必须区分已经实现的接口与 planned support，不提前宣称双接口支持。

目标结构：

```text
Client
  |
  +--> /v1/chat/completions adapter --+
  |                                    |
  +--> /v1/responses adapter ----------+--> shared gateway core
                                             |-- routing
                                             |-- health
                                             |-- admission / rate limit
                                             |-- observability
                                             +--> backend
```

## 结果

正面结果：

- M0 的协议足够简单，可以集中学习 HTTP forwarding 和 routing state。
- 核心模块不会因为增加第二种客户端协议而重写。
- 最终项目既保留常见兼容入口，也能展示对现代 Responses API 的适配。
- 不承担两种协议之间完整、易出错的翻译责任。

代价与限制：

- 第一阶段不能声称支持 Responses API。
- 需要为两种请求和响应格式维护独立 adapter tests。
- 某些依赖 Responses state 或 hosted tools 的能力不属于第一版网关保证。
- 如果目标 inference backend 不支持 Responses API，M4 adapter 可能只能连接支持该协议的后端；届时必须在 support matrix 中明确记录。

## 未采用的方案

### 只实现 Responses API

没有采用，因为它会在 M0 引入超出 routing 主线的协议复杂度，并缩小早期可连接的后端范围。

### 永久只实现 Chat Completions

没有采用，因为它不能验证网关核心是否真正与公开协议解耦，也无法覆盖现代 Responses client。

### 在两种 API 之间自动转换

没有采用，因为工具调用、状态和 streaming event 并非简单的一一映射。第一版应保持透明转发和能力诚实性。

## 重新评估条件

出现以下任一情况时重新评估本决策：

- 目标 inference backend 的官方接口支持发生明显变化
- Responses adapter 需要修改 shared core 中的协议无关模块
- 用户需求明确要求 stateful Responses、hosted tools 或 background mode
- benchmark 表明 adapter 层引入了不可忽略的性能或内存开销

