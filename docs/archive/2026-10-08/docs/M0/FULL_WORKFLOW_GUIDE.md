# InferGate M0 全流程作业指南

> 风格：课程作业 handout  
> 目标：从当前仓库状态完成一个可运行、可测试、可解释的最小推理网关  
> 预计用时：8–12 小时（不含扩展题）  
> 当前模式：learning mode；核心控制流由作者理解并主导实现

## 0. 你最终要交付什么

M0 完成后，本地应同时运行三个 HTTP 服务：

```text
                         +--------------------------+
                         | mock backend A           |
Client                   | http://127.0.0.1:8001   |
  |                      +--------------------------+
  | POST /v1/chat/completions          ^
  v                                     |
+--------------------------+            |
| InferGate                |------------+
| http://127.0.0.1:8000    |
| validate -> select       |------------+
| -> forward -> respond    |            |
+--------------------------+            v
                         +--------------------------+
                         | mock backend B           |
                         | http://127.0.0.1:8002   |
                         +--------------------------+
```

对同一个模型连续发送四个有效请求时，响应头
`X-InferGate-Backend` 应依次为：

```text
backend-a, backend-b, backend-a, backend-b
```

M0 不只是“请求能通”。以下行为必须同时成立：

1. `stream: true` 在选择 backend 之前被拒绝。
2. 请求中的未知字段被原样转发，不由 gateway 删除。
3. backend 返回的 body 被当作不透明字节，不解析、不重建。
4. backend 的 `4xx`/`5xx` 是正常 HTTP 结果，由 gateway 原样返回。
5. 连接失败或超时才是 transport failure，由 gateway 映射为 `502`。
6. M0 不重试，因此一次客户端请求至多产生一次 backend 请求。
7. `httpx.AsyncClient` 在应用生命周期内复用，而不是每次请求新建。

## 1. 作业边界

### 1.1 本次要实现

- 一个 `POST /v1/chat/completions` gateway endpoint；
- M0 请求校验；
- 已有 round-robin router 与 gateway 的集成；
- 非流式 HTTP backend client；
- `AsyncClient` 的创建、复用和关闭；
- backend HTTP 响应的透明回传；
- gateway 自身错误的稳定映射；
- 单元测试、组件测试和端到端测试；
- 两个 mock backend 的本地手工验收。

### 1.2 明确不做

- streaming；
- retry、fallback 或 health check；
- authentication 或通用请求头转发；
- 并发上限、排队或 rate limiting；
- metrics、tracing 或 benchmark；
- Responses API adapter；
- weighted、load-aware 或 health-aware routing；
- 完整复制 OpenAI API。

遇到“顺便加上更生产级的功能”的冲动时，先检查它是否在上面的列表中。
M0 的价值是把一条最小请求路径做正确，而不是功能数量。

## 2. 开始前：建立基线

在仓库根目录执行：

```bash
uv sync
uv run pytest -q
```

当前 M0 基线共有 24 个测试通过。依赖库产生的 deprecation warning
不等于功能测试失败，但应保留原始输出，避免把真正的失败误判成 warning。

再阅读以下文件，顺序不要颠倒：

1. [`API_contract.md`](API_contract.md)：客户端可见的协议；
2. [`ROUTER_CONTRACT.md`](ROUTER_CONTRACT.md)：backend 选择及 cursor 状态；
3. [`BACKEND_CLIENT_CONTRACT.md`](BACKEND_CLIENT_CONTRACT.md)：HTTP 传输边界；
4. [`REQUEST_PATH.md`](REQUEST_PATH.md)：三条端到端控制流；
5. [`COLLABORATION_CONTRACT.md`](../COLLABORATION_CONTRACT.md)：作者与 AI 的分工。

### 2.1 当前仓库状态

| 能力 | 当前状态 | 本作业动作 |
| --- | --- | --- |
| API contract | 已接受 | 实现并验证 |
| mock backend | 已实现 | 保持最小，补必要测试 |
| round-robin router | 已实现 | 集成，不重写策略 |
| backend client contract | Draft | teach-back 后接受并实现 |
| gateway endpoint | 未实现 | 实现 |
| application lifecycle | 未实现 | 实现 |
| 集成与端到端测试 | 未实现 | 实现 |

### 2.2 第一个决策检查点：400 还是 422

现有文档存在一个必须在实现前消除的歧义：

- `REQUEST_PATH.md` 对 `stream: true` 指定 `400 Bad Request`；
- `API_contract.md` 的 validation error 段落仍写有 `400 / 422`；
- FastAPI/Pydantic 的默认 schema validation 通常产生 `422`。

建议的 M0 统一规则是：所有 gateway-owned 请求校验失败均返回稳定的 `400`；
不要让错误状态取决于校验发生在 Pydantic 还是自定义函数中。若接受此规则，先更新
contract，再写测试。若决定保留 `422`，则必须逐类列出哪些错误为 `400`、哪些为
`422`，不能把行为留给框架偶然决定。

**检查问题：** 为什么“测试当前碰巧返回多少”不能替代协议决策？

## 3. 总体数据流与所有权

实现前，先能不用代码解释下面的流程：

```text
raw client request
  -> parse JSON
  -> validate gateway-owned fields
  -> select backend for payload["model"]
  -> forward the original payload
  -> receive HTTP response OR transport exception
  -> construct client-facing response in API layer
```

组件边界如下：

| 组件 | 输入 | 持有状态 | 输出/失败 |
| --- | --- | --- | --- |
| Validator | 原始 JSON object | 无 | 允许继续或 validation error |
| Router | model name | 每个 model 的 cursor | `Backend` 或 `NoBackendAvailableError` |
| Backend client | backend、path、payload | 共享 `AsyncClient` | `BackendResponse` 或 `BackendTransportError` |
| API layer | 客户端请求 | 依赖引用 | 最终 HTTP response |
| Mock backend | Chat Completions 请求 | 尽量无状态 | 可预测的 backend response |

API layer 是 orchestration boundary：它按顺序调用其他组件，并把领域错误转换成客户端
可见的 HTTP 结果。Router 不应 import FastAPI；backend client 也不应生成 `502`。

## 4. Problem 0 — 契约复述与测试清单（30–45 分钟）

在写实现前，建立一张“场景—预期结果”表。至少包含：

| 场景 | 是否选择 backend | 是否调用 backend | 客户端结果 |
| --- | ---: | ---: | --- |
| 有效请求 | 是 | 是 | 保留 backend status/body/content-type，增加 backend header |
| `stream: true` | 否 | 否 | gateway validation error |
| 未配置 model | 尝试但失败 | 否 | `503 Service Unavailable` |
| backend 返回 `429` | 是 | 是 | 原样 `429`，不重试 |
| backend 返回 `500` + 非 JSON body | 是 | 是 | 原样 `500` 和 body，不重试 |
| connect timeout | 是 | 尝试一次 | gateway `502 Bad Gateway` |

### 必答题

1. 为什么 backend 的 `500` 不应转换为 `BackendTransportError`？
2. 为什么 response body 应保存为 `bytes`，而不是 `dict`？
3. 如果 omitted `stream` 在 gateway 中解释为 `false`，为什么不能自动把
   `"stream": false` 注入转发 payload？
4. 为什么 `NoBackendAvailableError` 应由 API layer 映射为 `503`？
5. M0 没有 retry 时，round-robin cursor 在 backend 请求失败后是否回退？依据是什么？

最后一题现有 contract 没有显式定义“回退”。按当前调用顺序，成功选择已经推进 cursor，
后续 transport failure 不应隐式撤销选择。若你不同意，先修改契约，不要在异常处理中偷偷
改变 router 状态。

### 验收标准

- 你能画出上述数据流；
- 每种失败都能指出“错误最初由哪个组件产生”；
- 测试清单在写代码前已经存在。

## 5. Problem 1 — 实现 HTTP backend client（1.5–2 小时）

建议新增：

```text
src/infergate/backend_client.py
tests/test_backend_client.py
```

### 5.1 Public interface

根据 contract，模块至少需要表达：

```python
@dataclass(frozen=True)
class BackendResponse:
    status_code: int
    body: bytes
    content_type: str | None


class BackendTransportError(Exception):
    ...


class BackendClient:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        ...

    async def forward(
        self,
        backend: Backend,
        path: str,
        payload: dict[str, object],
    ) -> BackendResponse:
        ...
```

这只是接口骨架，不规定你的内部变量名或 URL 拼接辅助函数。

### 5.2 实现约束

- 复用注入的 `AsyncClient`；
- 使用 JSON request body；
- 读取完整 response body 后再返回，因为 M0 非 streaming；
- 只提取 `status_code`、原始 bytes 和可选 `Content-Type`；
- 不调用 `raise_for_status()`；
- 捕获 HTTPX 的 transport exception 边界，而不是宽泛的 `Exception`；
- 使用 exception chaining 保留根因；
- 不 retry；
- 不 import FastAPI；
- 不读取 `choices`、`message`、`usage` 等应用层字段。

### 5.3 URL 拼接陷阱

你必须为以下组合写测试或明确限制：

```text
base_url = "http://127.0.0.1:8001"
path     = "/v1/chat/completions"
```

不要用未经思考的字符串相加产生双斜杠，也不要让 path 覆盖 `base_url` 中可能存在的
前缀路径。M0 可以选择一个简单且写入 contract 的规范，例如：配置的 `base_url`
只包含 scheme、host、port，可选末尾 `/`；`path` 必须以 `/` 开头。

### 5.4 必需测试

使用 `httpx.MockTransport` 或等价的进程内 transport，使测试不依赖真实端口：

1. `200` response：status、bytes、content-type 全部保留；
2. `429` response：作为普通 `BackendResponse` 返回；
3. `500` 且 body 不是 JSON：bytes 不变；
4. 缺少 `Content-Type`：结果为 `None`；
5. transport exception：转换为 `BackendTransportError`，且 `__cause__` 为原异常；
6. 请求 method、URL 和 JSON payload 符合预期；
7. 一次 `forward()` 只发起一次请求。

不要只 mock `BackendClient.forward()` 自己；那样只能证明 mock 会返回你指定的值，不能
证明真实 HTTPX 边界正确。

### 5.5 完成检查

```bash
uv run pytest -q tests/test_backend_client.py
```

建议提交信息：

```text
feat: add the M0 HTTP backend client
```

## 6. Problem 2 — 定义 gateway 请求校验（1–1.5 小时）

目标不是构造一个新的、只含已知字段的 Pydantic object；目标是检查 gateway 拥有的
约束，同时保留原始 payload 供转发。

建议把“解析”和“校验”看作两个不同动作：

```text
request bytes -> JSON value -> verify it is an object -> validate owned fields
                                         |
                                         +-> keep original object
```

### 6.1 Gateway-owned fields

至少检查：

- 根 JSON 值是 object；
- `model` 存在且为 string；
- `messages` 存在、为非空 list；
- 每个 message 为 object；
- 每个 message 的 `role` 属于 contract 允许集合；
- 每个 message 的 `content` 为 string；
- `stream` 缺省或为 boolean `false`；
- `stream: true` 被明确拒绝；
- `stream` 的其他类型被拒绝。

### 6.2 Preservation tests

使用一个带未知字段的 payload：

```json
{
  "model": "mock-model",
  "messages": [
    {
      "role": "user",
      "content": "hello",
      "future_message_field": {"keep": true}
    }
  ],
  "future_top_level_field": [1, 2, 3]
}
```

测试 backend 收到的 object 与客户端 object 等价，而且 omitted `stream` 仍然 omitted。
不要用“最终 backend 也返回 200”间接代替 payload equality assertion。

### 6.3 框架默认行为陷阱

如果直接把 endpoint 参数声明为严格 Pydantic model，FastAPI 可能在你的 orchestration
代码运行前返回默认 `422`，并且 model serialization 可能丢弃字段或注入默认值。
这不是说不能用 Pydantic，而是你必须证明：

- 错误格式符合 M0 contract；
- status code 符合 Problem 0 的决策；
- 未知字段与 omitted 字段的 forwarding semantics 没有改变。

### 必需测试

- malformed JSON；
- 根值不是 object；
- 缺少 `model`；
- 空 `messages`；
- 非法 role；
- `stream: true`；
- `stream: "false"`；
- unknown fields preserved；
- omitted `stream` remains omitted；
- validation failure 不调用 router 和 backend client。

## 7. Problem 3 — 组装 gateway application（2–3 小时）

建议新增：

```text
src/infergate/app.py
tests/test_app.py
```

也可以把 dependency wiring 放入单独模块，但 M0 不需要复杂容器。

### 7.1 Application lifecycle

目标生命周期：

```text
application startup
  -> create one httpx.AsyncClient with bounded timeout
  -> create BackendClient using that AsyncClient
  -> make dependencies available to endpoint

serve many requests
  -> reuse the same AsyncClient and its connection pool

application shutdown
  -> close AsyncClient exactly once
```

使用 FastAPI lifespan 或等价的显式机制。不要在 module import 时创建难以关闭的全局
client，也不要在每个 handler 内使用 `async with httpx.AsyncClient()`。

### 7.2 Dependency construction

M0 的默认 routing table 可以是：

```python
{
    "mock-model": [
        Backend("backend-a", "http://127.0.0.1:8001"),
        Backend("backend-b", "http://127.0.0.1:8002"),
    ]
}
```

测试不应依赖这两个真实地址。让 app factory 或 dependency override 能注入测试 router
和测试 backend client。重点不是搭建抽象框架，而是避免测试只能启动真实网络服务。

### 7.3 Endpoint control flow

伪代码层面的顺序必须固定：

```text
parse and validate
select exactly one backend
forward exactly once
if backend response exists:
    preserve status/body/content-type
    add X-InferGate-Backend
if no backend exists:
    return gateway 503
if transport fails:
    return gateway 502
```

### 7.4 Response construction

不要使用 `return backend_response.json()`。这会：

- 假设 body 一定是 JSON；
- 重新序列化并改变字节；
- 可能改变空白、字符转义或数字表现；
- 无法透明处理 backend 的纯文本错误。

应由 API layer 使用 raw bytes 构造 response，设置 backend status 和可选
`Content-Type`，再添加 `X-InferGate-Backend`。

### 7.5 错误映射

建议把 gateway 自己产生的错误统一为稳定结构：

```json
{
  "error": {
    "message": "...",
    "type": "gateway_error",
    "param": null,
    "code": "backend_transport_failure"
  }
}
```

至少定义：

| 领域结果 | HTTP status | `code` 建议值 |
| --- | ---: | --- |
| 无可用 backend | 503 | `no_backend_available` |
| transport failure | 502 | `backend_transport_failure` |

不要把原始 exception 文本直接暴露给客户端；它可能包含内部主机名或连接细节。测试和
日志可以保留根因，客户端 response 使用稳定、有限的信息。

### 7.6 必需 app 测试

1. 两次请求选择不同 backend，第三次回到第一个；
2. `X-InferGate-Backend` 与实际传给 backend client 的 `Backend.id` 一致；
3. backend `200` 的 body bytes 完全相同；
4. backend `429` 和 `500` 的 status/body/content-type 完全保留；
5. transport failure 变为 `502`，不进行第二次 `forward()`；
6. 未配置 model 变为 `503`，不调用 `forward()`；
7. invalid request 在 router 之前停止；
8. 两个 model 的 cursor 独立；
9. response 缺少 content-type 时，不伪造 backend content-type；
10. gateway metadata 不写入 backend response body。

### 7.7 Entry point

当前 `pyproject.toml` 的 FastAPI entrypoint 指向 mock backend。完成 gateway app 后，必须
明确区分启动 gateway 与启动 mock backend 的命令。可以保留显式 module path：

```bash
uv run uvicorn infergate.mock_backend:app --port 8001
uv run uvicorn infergate.mock_backend:app --port 8002
uv run uvicorn infergate.runtime:app --port 8000
```

若修改 `[tool.fastapi]` 默认入口，README 必须同步说明默认启动的是哪个服务。

建议提交信息：

```text
feat: connect the M0 gateway request path
```

## 8. Problem 4 — 分层测试策略（1.5–2 小时）

测试应按故障定位能力分层，而不是把所有行为塞进一个端到端测试。

### 8.1 Layer A：纯单元测试

- router cursor 与失败不变式；
- validation 的输入分类；
- URL 构造等纯函数（若存在）。

失败时通常说明本模块逻辑错误，不涉及网络或应用生命周期。

### 8.2 Layer B：HTTP 组件测试

- `BackendClient` + `httpx.MockTransport`；
- gateway app + 注入的 fake/recording backend client；
- lifespan 是否正确创建和关闭资源。

该层验证接口边界，但不依赖真实端口，因此应当快速、确定性强。

### 8.3 Layer C：进程级端到端测试

至少保留一个可重复的测试或脚本，真实启动两个 mock backends 和 gateway，然后发送
连续请求。这一层证明 wiring、端口、URL 和序列化边界一起工作。

不要用 Layer C 替代前两层：端到端失败只能告诉你“系统没通”，往往不能指出哪个
invariant 被破坏。

### 8.4 Test doubles 的最低能力

用于 app 测试的 recording backend client 应记录：

- 被调用次数；
- 每次收到的 `Backend`；
- path；
- payload；
- 按测试配置返回 response 或抛出 transport error。

这样测试才能证明顺序、选择和“恰好一次”，而不只是最终 status。

### 8.5 全量检查

```bash
uv run pytest -q
git diff --check
```

如项目后续加入 formatter、linter 或 type checker，再把它们加入验收；不要在本作业中
为了“看起来完整”临时引入一整套没有配置共识的工具。

## 9. Problem 5 — 手工端到端验收（45–60 分钟）

打开三个终端，在仓库根目录分别运行：

```bash
uv run uvicorn infergate.mock_backend:app --host 127.0.0.1 --port 8001
```

```bash
uv run uvicorn infergate.mock_backend:app --host 127.0.0.1 --port 8002
```

```bash
uv run uvicorn infergate.runtime:app --host 127.0.0.1 --port 8000
```

第四个终端发送请求：

```bash
curl -i http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "mock-model",
    "messages": [{"role": "user", "content": "hello"}],
    "client_metadata": {"must_survive": true}
  }'
```

重复四次并记录 `X-InferGate-Backend`。然后执行以下故障注入：

### 9.1 Unsupported streaming

把 payload 改为 `"stream": true`。确认：

- 返回约定的 validation status；
- 两个 backend 均未收到请求；
- router cursor 没有因为该请求推进。

### 9.2 Unknown model

把 `model` 改为 `unknown-model`。确认返回 `503`，且没有 backend HTTP 请求。

### 9.3 Transport failure

停止即将被选择的 backend，再发送有效请求。确认：

- 返回 `502`；
- gateway 没有自动改发另一个 backend；
- 下一次请求按已经推进的 round-robin cursor 选择后续 backend。

最后恢复服务并确认正常请求仍能工作。

## 10. 最终验收清单

### 功能正确性

- [ ] 有效请求完成 gateway -> backend -> client 闭环；
- [ ] 连续请求严格按配置顺序 round-robin；
- [ ] 每个 model 的 cursor 独立；
- [ ] unknown fields 被原样转发；
- [ ] omitted `stream` 未被注入 payload；
- [ ] backend body bytes 未被解析或重建；
- [ ] backend status 与 content-type 被保留；
- [ ] backend `4xx`/`5xx` 不被当作 transport failure；
- [ ] transport failure 返回 `502` 且不 retry；
- [ ] 无 backend 返回 `503`；
- [ ] validation failure 不选择也不调用 backend；
- [ ] response 含正确的 `X-InferGate-Backend`。

### 资源与边界

- [ ] 一个 app lifecycle 复用一个 `AsyncClient`；
- [ ] shutdown 时 client 被关闭；
- [ ] router 不依赖 FastAPI；
- [ ] backend client 不生成客户端 HTTP response；
- [ ] API layer 不解释 backend body；
- [ ] 客户端看不到内部 exception 文本；
- [ ] M0 没有悄悄加入 retry、health check 或 streaming。

### 工程质量

- [ ] 全量测试通过；
- [ ] 测试不依赖执行顺序；
- [ ] 单元测试不要求真实端口；
- [ ] 至少一次真实三进程验收成功；
- [ ] README 有启动、测试和手工验证入口；
- [ ] `git diff --check` 通过；
- [ ] 没有提交 `.DS_Store`、`__pycache__` 或临时日志。

### 理解验收

- [ ] 能从客户端开始口述完整 happy path；
- [ ] 能区分 backend HTTP error 与 transport failure；
- [ ] 能解释 cursor 在每条失败路径上是否变化；
- [ ] 能解释为何复用 `AsyncClient`；
- [ ] 能预测一个新测试的结果；
- [ ] 能不依赖 AI 完成一次小改动。

## 11. 评分 rubric（100 分）

| 项目 | 分值 | 满分标准 |
| --- | ---: | --- |
| Contract consistency | 10 | validation status、错误结构与文档无歧义 |
| Request preservation | 15 | unknown/omitted 字段语义不变 |
| Router integration | 15 | 顺序、独立 cursor、失败路径均正确 |
| Backend client | 20 | opaque bytes、HTTP error、transport error、单次请求边界正确 |
| Lifecycle | 10 | client 正确复用和关闭，可测试 |
| API orchestration | 15 | 状态/headers/error mapping 正确，职责清晰 |
| Test quality | 10 | 正反例、故障注入、恰好一次与边界断言充分 |
| Reproducibility | 5 | 第三方可按 README 启动和验收 |

以下任一项应阻止 M0 被标记为完成：

- 调用 `raise_for_status()` 导致 backend `4xx`/`5xx` 丢失；
- 通过 JSON parse/serialize 重建 backend body；
- transport failure 自动 retry；
- endpoint 内每次新建 `AsyncClient`；
- validation 后转发的是重建 payload 而不是原始 payload；
- 只有 happy-path 测试；
- 无法解释 cursor 或错误所有权。

## 12. 常见故障与定位顺序

### Gateway 返回 422，而测试期待 400

先检查请求是否在进入自定义 validation 之前就被 FastAPI/Pydantic 拒绝。不要只修改测试
去接受当前结果；回到 Problem 0 的 contract 决策。

### Unknown fields 消失或出现默认 `stream: false`

检查是否先构造了 Pydantic model，再用 `model_dump()` 作为转发 payload。验证和转发
使用的数据对象可能被错误耦合。

### Backend 500 被变成 502

检查是否调用了 `raise_for_status()`，或捕获了过宽的 exception。收到 HTTP response
就不是 transport failure。

### Body 内容看起来一样，但 byte equality 测试失败

检查 gateway 是否做了 `response.json()` 后重新序列化。JSON 语义相等不代表 bytes
相等，M0 contract 要求透明 body。

### 每次请求都选择 backend A

检查 router 是否在每个请求中被重新构造。Router cursor 必须跨请求存在于同一个 app
实例中。

### 第二个测试意外选择 backend B

测试之间可能共享了同一个 mutable router。每个测试应构造独立 app/dependencies，除非
测试明确验证连续请求。

### 关闭测试时出现 unclosed client warning

检查 app 测试是否进入 lifespan，以及 `AsyncClient` 的所有者是否与关闭责任一致。

### 手工测试连接被拒绝

按从内到外的顺序定位：backend 端口是否监听 -> gateway 配置 URL 是否正确 -> gateway
端口是否监听 -> curl path/method 是否正确。不要一开始就修改业务逻辑。

## 13. 建议的提交顺序

保持每个提交可测试，避免一个“大爆炸式”提交：

1. `docs: resolve the M0 validation contract`
2. `feat: add the M0 HTTP backend client`
3. `test: cover M0 validation and payload preservation`
4. `feat: connect the M0 gateway request path`
5. `test: add M0 gateway integration coverage`
6. `docs: document M0 startup and verification`

如果某一步只修一个小 review 问题，可以并入相关提交，不必机械地为每个改动创建提交。

## 14. M0 完成后的复盘

用一页以内回答：

1. 我现在能解释哪些以前不能解释的 HTTP/async 概念？
2. 哪些 task 由我主导，哪些由 AI 主导？
3. 哪个 bug 最能说明 M0 的一个 invariant？
4. 哪些行为已经被自动化测试证明？
5. 哪些行为只做过手工验证？
6. 如果加入并发请求，当前 router 有什么尚未解决的状态问题？
7. 进入 M1 前，哪些 M0 技术债必须解决，哪些可以明确推迟？

完成复盘后再开始 streaming 和 health check。M1 会改变 response lifecycle、取消传播和
失败边界；如果 M0 的非流式路径还不能清楚解释，直接叠加 streaming 会让问题更难定位。

## 15. 扩展题（不计入 M0 完成条件）

只有全部验收通过后再做：

1. **Property-based routing test**：对任意 backend 数量与调用次数验证循环序列。
2. **Config parsing**：从环境或配置文件构造 routing table，并验证重复 backend id。
3. **Structured internal logging**：记录 backend id 与 transport failure，但不改变客户端
   response。
4. **Concurrency experiment**：证明当前 router 在并发调用下的行为，并为 M1 写 decision
   note；不要在没有测试的情况下直接加锁。

扩展题的结果应产生证据或决策，不应静默改变 M0 contract。
