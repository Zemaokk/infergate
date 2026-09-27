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
        body = b"data: hello\n\n" if stream else b'{"result":"hello"}'
        return httpx.Response(200, content=body)

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
