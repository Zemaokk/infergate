import asyncio
import json
import logging
from contextlib import asynccontextmanager

import httpx
import pytest

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.router import Backend, RoundRobinRouter
from infergate.token_bucket import TokenBucketLimiter


RESPONSE_PAYLOAD = {"model": "test-model", "input": "hello", "store": False}
CHAT_PAYLOAD = {
    "model": "test-model", "messages": [{"role": "user", "content": "hello"}]
}


@asynccontextmanager
async def gateway(handler, *, backends=None, capacity=20, concurrency=1):
    if backends is None:
        backends = [Backend(id="a", base_url="http://backend-a")]
    key_limiter = TokenBucketLimiter(capacity, 0)
    concurrency_limiter = ConcurrencyLimiter(concurrency)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as backend:
        app = create_app(
            RoundRobinRouter({"test-model": backends}), BackendClient(backend),
            key_limiter, concurrency_limiter,
        )
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway",
                headers={"X-InferGate-Key": "test-key"},
            ) as client:
                yield client, app, key_limiter, concurrency_limiter
        finally:
            app.state.tracer_provider.shutdown()


def completion_logs(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records
            if record.name == "infergate.observability"
            and record.levelno == logging.INFO]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400, 500])
@pytest.mark.parametrize("optional", [{}, {
    "instructions": None, "max_output_tokens": None,
    "stream": False, "background": False,
}])
async def test_response_payload_path_and_http_response_pass_through(status, optional):
    calls = []
    payload = {**RESPONSE_PAYLOAD, **optional, "input": "  hello\nworld  "}
    body = b'{"id":"resp-test","status":"incomplete","output":[]}'

    def handler(request):
        calls.append(request)
        return httpx.Response(status, content=body,
                              headers={"Content-Type": "application/json; charset=utf-8"})

    async with gateway(handler, backends=[
        Backend(id="a", base_url="http://backend-a"),
        Backend(id="b", base_url="http://backend-b"),
    ]) as (client, app, _, limiter):
        response = await client.post("/v1/responses", json=payload)
        assert response.status_code == status
        assert response.content == body
        assert response.headers["content-type"] == "application/json; charset=utf-8"
        assert len(calls) == 1  # HTTP errors must not trigger fallback.
        assert calls[0].url.path == "/v1/responses"
        assert json.loads(calls[0].content) == payload
        assert limiter.available == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {"store": 0}, {"input": " \n "}, {"stream": True}, {"tools": []},
])
async def test_invalid_body_is_observed_before_key_quota_and_backend(invalid, caplog):
    caplog.set_level(logging.INFO, logger="infergate.observability")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"output": []})

    async with gateway(handler, capacity=1) as (client, app, key_limiter, limiter):
        response = await client.post("/v1/responses", json={**RESPONSE_PAYLOAD, **invalid},
                                     headers={"X-InferGate-Key": " "})
        assert response.status_code == 400
        assert response.json()["error"]["message"] == "Invalid request body."
        assert key_limiter.buckets == {}
        assert calls == []
        assert limiter.available == 1
        record, = completion_logs(caplog)
        assert record["route"] == "/v1/responses"
        assert record["outcome"] == "rejected"
        assert record["reason"] == "invalid_request_body"
        assert record["attempt_count"] == 0
        assert record["first_byte_sec"] is None
        assert app.state.metrics.registry.get_sample_value("infergate_requests_total", {
            "route": "/v1/responses", "status": "400", "outcome": "rejected",
            "reason": "invalid_request_body",
        }) == 1
        assert (await client.post("/v1/responses", json=RESPONSE_PAYLOAD)).status_code == 200


@pytest.mark.asyncio
async def test_missing_key_does_not_contact_backend():
    def handler(request):
        raise AssertionError("Backend must not be contacted")

    async with gateway(handler) as (client, _, key_limiter, limiter):
        client.headers.pop("X-InferGate-Key")
        response = await client.post("/v1/responses", json=RESPONSE_PAYLOAD)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_infergate_key"
        assert key_limiter.buckets == {}
        assert limiter.available == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("first_route", ["/v1/chat/completions", "/v1/responses"])
async def test_both_routes_consume_the_same_key_quota(first_route):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={})

    payloads = {"/v1/chat/completions": CHAT_PAYLOAD, "/v1/responses": RESPONSE_PAYLOAD}
    second_route = next(route for route in payloads if route != first_route)
    async with gateway(handler, capacity=1) as (client, _, _, limiter):
        assert (await client.post(first_route, json=payloads[first_route])).status_code == 200
        response = await client.post(second_route, json=payloads[second_route])
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "rate_limit_exceeded"
        assert calls == [first_route]
        assert limiter.available == 1


@pytest.mark.asyncio
async def test_chat_stream_blocks_responses_until_cleanup(caplog):
    caplog.set_level(logging.INFO, logger="infergate.observability")
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    class HeldStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"data: first\n\n"
            entered.set()
            await release.wait()
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            self.closed = True

    stream = HeldStream()

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(200, stream=stream,
                                  headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json={"output": []})

    async with gateway(handler) as (client, app, _, limiter):
        task = asyncio.create_task(client.post(
            "/v1/chat/completions", json={**CHAT_PAYLOAD, "stream": True}
        ))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert limiter.available == 0
            response = await client.post("/v1/responses", json=RESPONSE_PAYLOAD)
            assert response.status_code == 503
            assert response.json()["error"]["message"] == "Exceed global concurrency limit."
            assert response.json()["error"]["code"] == "concurrency_limit_exceeded"
            assert calls == ["/v1/chat/completions"]
            record, = completion_logs(caplog)
            assert record["route"] == "/v1/responses"
            assert record["attempt_count"] == 0
        finally:
            release.set()
            await asyncio.wait_for(task, 1)
        assert stream.closed
        assert limiter.available == 1
        assert (await client.post("/v1/responses", json=RESPONSE_PAYLOAD)).status_code == 200
        assert app.state.metrics.registry.get_sample_value("infergate_active_requests") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_mode, status, attempts", [
    ("none", 503, 0), ("connect_error", 502, 2), ("fallback", 200, 2),
])
async def test_no_backend_and_connection_fallback_release_capacity(
    backend_mode, status, attempts, caplog
):
    caplog.set_level(logging.INFO, logger="infergate.observability")
    calls = []

    def handler(request):
        calls.append(request)
        if backend_mode == "connect_error" or len(calls) == 1:
            raise httpx.ConnectError("Unavailable", request=request)
        return httpx.Response(200, json={"output": []})

    backends = [] if backend_mode == "none" else [
        Backend(id="a", base_url="http://backend-a"),
        Backend(id="b", base_url="http://backend-b"),
    ]
    async with gateway(handler, backends=backends) as (client, _, _, limiter):
        response = await client.post("/v1/responses", json=RESPONSE_PAYLOAD)
        assert response.status_code == status
        assert len(calls) == attempts
        assert all(request.url.path == "/v1/responses" for request in calls)
        assert len({request.url.host for request in calls}) == attempts
        record, = completion_logs(caplog)
        assert record["route"] == "/v1/responses"
        assert record["attempt_count"] == attempts
        assert limiter.available == 1


@pytest.mark.asyncio
async def test_cancelled_responses_releases_shared_capacity(caplog):
    caplog.set_level(logging.INFO, logger="infergate.observability")
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("Must be cancelled")

    async with gateway(handler) as (client, _, _, limiter):
        task = asyncio.create_task(client.post("/v1/responses", json=RESPONSE_PAYLOAD))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert limiter.available == 0
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert limiter.available == 1
        record, = completion_logs(caplog)
        assert record["route"] == "/v1/responses"
        assert record["outcome"] == "cancelled"
        assert record["attempt_count"] == 1
