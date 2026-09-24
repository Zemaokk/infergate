# M1 验收记录 — 2026-09-24

M1 的流式转发、超时和健康检查行为通过了自动化测试与本地三进程验收。
作者也完成了协作约定中的 teach-back：一次探测失败只影响后续选路，不会改变
已经选中该 backend 的流式请求；backend 后续探测成功后可以重新进入路由。

## 自动化测试证据

| 验收要求 | 测试证据 |
| --- | --- |
| 首个 chunk 在完整响应结束前到达；字节内容和顺序不变 | `tests/test_app.py` 中的受控流及直接 ASGI 测试；`tests/test_runtime.py::test_streaming_request_uses_healthy_backend_and_preserves_body` |
| 下游响应在正常结束、读取错误、取消和客户端断开后关闭 | `tests/test_app.py` 中的流式响应生命周期测试 |
| 下游响应头到达前的传输失败映射为 502；向客户端提交响应后的失败只终止流，不注入新的网关错误 | `tests/test_app.py` 中的传输错误及 ASGI 响应测试 |
| 跳过不健康 backend；恢复后重新参与选路；全部不健康时返回 503 且不发送推理请求 | `tests/test_router.py` 和 `tests/test_runtime.py` 中的健康状态测试 |
| 探测超时、传输失败、并行执行及探测轮次不重叠 | `tests/test_health_checker.py` |
| 原有非流式路径仍可用 | 完整的 `pytest -q` 测试集 |

## 本地进程验收

在 8001、8002 端口分别启动两个 `infergate.mock_backend:app` 进程，
并在 8000 端口启动 `infergate.runtime:app`。重复发送非流式请求，先后得到
`200`，响应头 `X-InferGate-Backend` 分别为 `backend-a` 和 `backend-b`。
停止 A 并等待下一轮探测后，请求仍通过 B 返回 `200`。再停止 B，网关返回
`503 no_backend_available`。重新启动 A 并等待探测后，请求恢复为通过 A 返回
`200`。

仅运行 A 时，一次真实 HTTP 流式请求在开始后约 0.02 秒收到第一个 SSE 事件，
约 0.30 秒后收到 `[DONE]`。这证明该次运行发生了增量发送，**不是延迟基准测试**。
验收结束后已停止临时启动的进程。

本地 mock 流只提供固定的两个事件，不代表真实推理服务，也不能覆盖所有网络故障。

## 结论边界

完整自动化测试集共 **51 项通过**。本地回环地址上的真实进程验证了健康切换和
增量流式发送。客户端断开后的清理通过直接 ASGI 测试验证，未进行真实网络断开
实验。本记录不对负载表现、benchmark、生产 backend 或多进程健康状态共享作出结论。
