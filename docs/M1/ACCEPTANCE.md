# M1 Technical Acceptance — 2026-09-24

M1's streaming, timeout, and health behaviors passed the automated suite and a
local three-process smoke test. The author teach-back in the collaboration
contract remains a separate learning checkpoint.

## Automated evidence

| Requirement | Test evidence |
| --- | --- |
| First chunk precedes complete body; bytes and order preserved | `tests/test_app.py` controlled stream and direct ASGI tests; `tests/test_runtime.py::test_streaming_request_uses_healthy_backend_and_preserves_body` |
| Downstream response closes after completion, read error, cancellation, and client disconnect | `tests/test_app.py` streaming lifecycle tests |
| Failure before streaming response headers maps to 502; failure after commitment terminates without a new gateway error | `tests/test_app.py` transport and ASGI response tests |
| Unhealthy backend is skipped; recovery restores it; none healthy returns 503 without inference traffic | `tests/test_router.py` and `tests/test_runtime.py` health cases |
| Probe timeout, transport failure, concurrency, and non-overlapping rounds | `tests/test_health_checker.py` |
| Existing non-streaming behavior remains available | Full `pytest -q` suite |

## Local process smoke test

Started two `infergate.mock_backend:app` processes on ports 8001/8002 and
`infergate.runtime:app` on port 8000. Repeated non-streaming requests returned
`200` with `X-InferGate-Backend: backend-a`, then `backend-b`. After stopping A
and waiting for a probe, requests returned `200` via B. After stopping B as
well, the gateway returned `503 no_backend_available`. Restarting A restored
`200` via A after a probe.

With A running, one real HTTP streaming request received the first SSE event
approximately 0.02 s after starting, then `[DONE]` approximately 0.30 s later.
This verifies incremental delivery for that run, not a latency benchmark. The
temporary processes were stopped after verification.

The local mock stream supplies a deterministic two-event response. It does not
model a production inference server or all possible network failures.
