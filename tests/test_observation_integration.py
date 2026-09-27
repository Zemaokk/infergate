import httpx
import pytest

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.router import Backend, RoundRobinRouter
from infergate.token_bucket import TokenBucketLimiter


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "scenario, expected_status, expected_calls",
    [
        ("success", 200, ["a"]),
        ("fallback", 200, ["a", "b"]),
        ("both_fail", 502, ["a", "b"]),
        ("no_backup", 502, ["a"]),
        ("no_backend", 503, []),
        ("invalid_body", 400, []),
        ("missing_key", 400, []),
        ("rate_limit", 429, []),
        ("concurrency_limit", 503, []),
        ("backend_400", 400, ["a"]),
        ("backend_503", 503, ["a"]),
        ("read_failure", 502, ["a"]),
    ],
)
async def test_request_observation_counts_actual_backend_calls(
    stream, scenario, expected_status, expected_calls
):
    calls = []
    observations = []

    def handler(request):
        calls.append(request.url.host)
        if scenario in {"both_fail", "no_backup"} or (
            scenario == "fallback" and request.url.host == "a"
        ):
            raise httpx.ConnectError("offline", request=request)
        if scenario == "read_failure":
            raise httpx.ReadTimeout("read failed", request=request)
        body = b"data: hello\n\n" if stream else b'{"result":"hello"}'
        status = (
            int(scenario.removeprefix("backend_"))
            if scenario.startswith("backend_") else 200
        )
        return httpx.Response(status, content=body)

    ids = [] if scenario == "no_backend" else ["a", "b"]
    if scenario == "no_backup":
        ids = ["a"]
    router = RoundRobinRouter(
        {"test-model": [Backend(name, f"http://{name}") for name in ids]}
    )
    limiter = TokenBucketLimiter(capacity=0 if scenario == "rate_limit" else 2, rate=1)
    concurrency = ConcurrencyLimiter(1)
    if scenario == "concurrency_limit":
        assert concurrency.try_acquire()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as backend:
        app = create_app(router, BackendClient(backend), limiter, concurrency)

        # Inspect the real request scope after FastAPI and its middleware run.
        # No production observation callback is needed for this staged integration.
        async def capture(scope, receive, send):
            await app(scope, receive, send)
            observations.append(scope["state"]["observation"])

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=capture), base_url="http://gateway"
        ) as client:
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": stream,
            }
            if scenario == "invalid_body":
                payload["messages"] = []
            headers = {} if scenario == "missing_key" else {"X-InferGate-Key": "test"}
            response = await client.post(
                "/v1/chat/completions", json=payload, headers=headers
            )

    assert response.status_code == expected_status
    assert calls == expected_calls
    assert len(observations) == 1
    assert observations[0].attempt == len(expected_calls)
    assert concurrency.available == (0 if scenario == "concurrency_limit" else 1)
    assert app.state.metrics.registry.get_sample_value("infergate_active_requests") == (
        1 if scenario == "concurrency_limit" else 0
    )
    expected_result = {
        "success": ("completed", None),
        "fallback": ("completed", None),
        "both_fail": ("transport_error", "backend_transport_failure"),
        "no_backup": ("transport_error", "backend_transport_failure"),
        "read_failure": ("transport_error", "backend_transport_failure"),
        "no_backend": ("rejected", "no_backend_available"),
        "invalid_body": ("rejected", "invalid_request_body"),
        "missing_key": ("rejected", "invalid_infergate_key"),
        "rate_limit": ("rejected", "rate_limit_exceeded"),
        "concurrency_limit": ("rejected", "concurrency_limit_exceeded"),
        "backend_400": ("backend_http_error", None),
        "backend_503": ("backend_http_error", None),
    }[scenario]
    observation = observations[0]
    assert observation.status_code == expected_status
    assert observation.response_complete is True
    assert (observation.pending_outcome, observation.pending_reason) == expected_result
    assert observation.outcome == expected_result[0]
    assert observation.reason == expected_result[1]
    assert observation.is_finish is True
    assert observation.total_time >= 0
    metric_labels = {
        "route": "/v1/chat/completions",
        "status": str(expected_status),
        "outcome": expected_result[0],
        "reason": expected_result[1] or "none",
    }
    assert app.state.metrics.registry.get_sample_value(
        "infergate_requests_total", metric_labels
    ) == 1
    assert app.state.metrics.registry.get_sample_value(
        "infergate_request_duration_seconds_count",
        {"route": "/v1/chat/completions", "outcome": expected_result[0]},
    ) == 1
    if stream and scenario in {"success", "fallback", "backend_400", "backend_503"}:
        assert observation.first_byte_sec is not None
        assert 0 <= observation.first_byte_sec <= observation.total_time
    else:
        assert observation.first_byte_sec is None
    first_byte_count = app.state.metrics.registry.get_sample_value(
        "infergate_request_first_byte_seconds_count",
        {"route": "/v1/chat/completions", "outcome": expected_result[0]},
    )
    assert first_byte_count == (1 if observation.first_byte_sec is not None else None)


@pytest.mark.asyncio
async def test_validation_handler_works_for_route_without_observation():
    def unexpected_backend_call(request):
        raise AssertionError("Validation failure must not contact a backend")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(unexpected_backend_call)
    ) as backend:
        app = create_app(
            RoundRobinRouter({}),
            BackendClient(backend),
            TokenBucketLimiter(2, 1),
            ConcurrencyLimiter(1),
        )

        @app.get("/unobserved")
        async def unobserved(value: int):
            return {"value": value}

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            response = await client.get("/unobserved", params={"value": "invalid"})
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
