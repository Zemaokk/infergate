import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from test_app import CountingConcurrencyLimiter, basic_payload, gateway_client

from infergate import token_bucket
from infergate.health import HealthManager
from infergate.router import Backend, RoundRobinRouter
from infergate.token_bucket import TokenBucketLimiter


def router_for(*ids, health=None):
    return RoundRobinRouter(
        {"test-model": [Backend(key, f"http://{key}") for key in ids]}, health
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ConnectTimeout])
async def test_fallback_reuses_admission_and_returns_second_backend(
    monkeypatch, stream, error_type
):
    monkeypatch.setattr(token_bucket, "time", SimpleNamespace(monotonic=lambda: 0.0))
    limiter = TokenBucketLimiter(1, 1)
    concurrency = CountingConcurrencyLimiter()
    calls = []
    payload = {**basic_payload, "stream": stream}
    body = b"data: hello\n\n" if stream else b'{"result":"hello"}'
    health = HealthManager(["a", "b"])
    for key in ("a", "b"):
        health.record_probe(key, True)

    def handler(request):
        calls.append(request.url.host)
        assert json.loads(request.content) == payload
        assert concurrency.available == 0
        assert concurrency.releases == 0
        assert limiter.buckets["test-key"].tokens == 0
        if request.url.host == "a":
            raise error_type("connection failed", request=request)
        return httpx.Response(200, content=body, headers={"Content-Type": "text/plain"})

    async with gateway_client(
        handler, router_for("a", "b", health=health), limiter, concurrency
    ) as client:
        response = await client.post("/v1/chat/completions", json=payload)
        assert calls == ["a", "b"]
        assert response.status_code == 200
        assert response.content == body
        assert response.headers["content-type"] == "text/plain"
        assert response.headers["X-InferGate-Backend"] == "b"
        assert concurrency.releases == 1
        assert concurrency.available == 1
        rejected = await client.post("/v1/chat/completions", json=payload)
    assert rejected.status_code == 429
    assert calls == ["a", "b"]
    assert concurrency.releases == 1
    assert health.is_healthy("a")


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_two_failures_do_not_try_third_backend(stream):
    calls = []
    concurrency = CountingConcurrencyLimiter()

    def handler(request):
        calls.append(request.url.host)
        raise httpx.ConnectError("offline", request=request)

    async with gateway_client(
        handler, router_for("a", "b", "c"), concurrency_limiter=concurrency
    ) as client:
        response = await client.post(
            "/v1/chat/completions", json={**basic_payload, "stream": stream}
        )
    assert calls == ["a", "b"]
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "backend_transport_failure"
    assert response.headers["X-InferGate-Backend"] == "b"
    assert concurrency.available == 1
    assert concurrency.releases == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("unhealthy_peer", [False, True])
async def test_no_fallback_candidate_preserves_last_failure(stream, unhealthy_peer):
    health = HealthManager(["a", "b"])
    health.record_probe("a", True)
    router = router_for("a", "b", health=health) if unhealthy_peer else router_for("a")
    calls = []

    def handler(request):
        calls.append(request.url.host)
        raise httpx.ConnectTimeout("offline", request=request)

    async with gateway_client(handler, router) as client:
        response = await client.post(
            "/v1/chat/completions", json={**basic_payload, "stream": stream}
        )
    assert calls == ["a"]
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "backend_transport_failure"
    assert response.headers["X-InferGate-Backend"] == "a"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.WriteError, httpx.PoolTimeout, 503])
async def test_nonretryable_outcome_never_reaches_healthy_peer(stream, failure):
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if failure == 503:
            return httpx.Response(503, content=b"backend busy")
        raise failure("failed", request=request)

    async with gateway_client(handler, router_for("a", "b")) as client:
        response = await client.post(
            "/v1/chat/completions", json={**basic_payload, "stream": stream}
        )
    assert calls == ["a"]
    assert response.headers["X-InferGate-Backend"] == "a"
    if failure == 503:
        assert response.status_code == 503
        assert response.content == b"backend busy"
    else:
        assert response.status_code == 502


@pytest.mark.asyncio
async def test_cancellation_during_second_attempt_does_not_retry_again():
    entered = asyncio.Event()
    concurrency = CountingConcurrencyLimiter()
    calls = []

    async def handler(request):
        calls.append(request.url.host)
        if request.url.host == "a":
            raise httpx.ConnectError("offline", request=request)
        entered.set()
        await asyncio.Event().wait()

    async with gateway_client(
        handler, router_for("a", "b", "c"), concurrency_limiter=concurrency
    ) as client:
        task = asyncio.create_task(client.post("/v1/chat/completions", json=basic_payload))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert concurrency.available == 0
            assert concurrency.releases == 0
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert calls == ["a", "b"]
    assert concurrency.available == 1
    assert concurrency.releases == 1
