import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi.responses import StreamingResponse

from infergate import token_bucket
from infergate.app import create_app, stream_backend_body
from infergate.backend_client import BackendClient, BackendStreamResponse
from infergate.router import Backend, RoundRobinRouter
from infergate.token_bucket import TokenBucketLimiter

basic_payload = {
    "model": "test-model",
    "messages": [{"role": "user", "content": "hello"}],
    "temperature": 0.7,
}

message_payload = {
    "model": "test-model",
    "messages": [
        {
            "role": "user",
            "content": "hello",
            "name": "test-user",
        }
    ],
}

backend_body = b'{"id": "response-001", "output": "hello"}'
error_body = b'{"error":"backend_failed"}'


class ControlledBackendStream:
    def __init__(self) -> None:
        self.release_second_chunk = asyncio.Event()
        self.waiting_for_second_chunk = asyncio.Event()
        self.closed = False

    async def _chunks(self) -> AsyncGenerator[bytes]:
        yield b"data: first\n\n"
        self.waiting_for_second_chunk.set()
        await self.release_second_chunk.wait()
        yield b"data: second\n\n"

    def aiter_bytes(self) -> AsyncGenerator[bytes]:
        return self._chunks()

    async def aclose(self) -> None:
        self.closed = True


class FailingBackendStream:
    def __init__(self, error_type: type[httpx.TransportError]) -> None:
        self.closed = False
        self.error_type = error_type

    async def _chunks(self) -> AsyncGenerator[bytes]:
        yield b"data: first\n\n"
        raise self.error_type("Backend stream failed")

    def aiter_bytes(self) -> AsyncGenerator[bytes]:
        return self._chunks()

    async def aclose(self) -> None:
        self.closed = True


def make_default_router() -> RoundRobinRouter:
    return RoundRobinRouter(
        {
            "test-model": [
                Backend(
                    id="backend-a",
                    base_url="http://backend-a",
                )
            ]
        }
    )


Handler = Callable[[httpx.Request], httpx.Response]


@asynccontextmanager
async def gateway_client(
    handler: Handler,
    router: RoundRobinRouter | None = None,
    limiter: TokenBucketLimiter | None = None,
) -> AsyncGenerator[httpx.AsyncClient]:
    router = router if router is not None else make_default_router()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as backend_http_client:
        app = create_app(
            router,
            BackendClient(backend_http_client),
            limiter if limiter is not None else TokenBucketLimiter(100, 1),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://gateway",
            headers={"X-InferGate-Key": "test-key"},
        ) as client:
            yield client


@pytest.mark.asyncio
async def test_stream_backend_body_closes_response_after_normal_exhaustion():
    response = ControlledBackendStream()
    response.release_second_chunk.set()
    body = stream_backend_body(cast(BackendStreamResponse, response))

    chunks = [chunk async for chunk in body]

    assert chunks == [b"data: first\n\n", b"data: second\n\n"]
    assert response.closed


@pytest.mark.asyncio
async def test_stream_backend_body_closes_response_when_cancelled():
    response = ControlledBackendStream()
    body = stream_backend_body(cast(BackendStreamResponse, response))

    assert await anext(body) == b"data: first\n\n"
    assert not response.closed

    next_chunk = asyncio.create_task(anext(body))
    await response.waiting_for_second_chunk.wait()
    next_chunk.cancel()

    with pytest.raises(asyncio.CancelledError):
        await next_chunk

    assert response.closed


@pytest.mark.asyncio
async def test_streaming_response_closes_downstream_on_client_disconnect():
    response = ControlledBackendStream()
    body = stream_backend_body(cast(BackendStreamResponse, response))
    streaming_response = StreamingResponse(body, media_type="text/event-stream")
    first_chunk_sent = asyncio.Event()
    sent_messages: list[dict[str, object]] = []

    async def receive() -> dict[str, str]:
        await first_chunk_sent.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)
        if (
            message["type"] == "http.response.body"
            and message.get("body") == b"data: first\n\n"
        ):
            first_chunk_sent.set()

    await streaming_response(
        {"type": "http", "asgi": {"spec_version": "2.3"}},
        receive,
        send,
    )

    assert first_chunk_sent.is_set()
    assert not response.release_second_chunk.is_set()
    assert response.closed
    assert not any(
        message.get("body") == b"data: second\n\n" for message in sent_messages
    )


@pytest.mark.parametrize("error_type", [httpx.ReadError, httpx.ReadTimeout])
@pytest.mark.asyncio
async def test_stream_backend_body_closes_response_after_read_error(error_type):
    response = FailingBackendStream(error_type)
    body = stream_backend_body(cast(BackendStreamResponse, response))

    assert await anext(body) == b"data: first\n\n"

    with pytest.raises(error_type):
        await anext(body)

    assert response.closed


@pytest.mark.asyncio
async def test_stream_read_timeout_after_headers_does_not_send_gateway_error():
    response = FailingBackendStream(httpx.ReadTimeout)
    body = stream_backend_body(cast(BackendStreamResponse, response))
    streaming_response = StreamingResponse(
        body, status_code=200, media_type="text/event-stream"
    )
    sent_messages: list[dict[str, object]] = []

    async def receive() -> dict[str, str]:
        return {"type": "http.request"}

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)

    with pytest.raises(httpx.ReadTimeout):
        await streaming_response(
            {"type": "http", "asgi": {"spec_version": "2.4"}},
            receive,
            send,
        )

    starts = [
        message for message in sent_messages if message["type"] == "http.response.start"
    ]
    bodies = [
        message.get("body")
        for message in sent_messages
        if message["type"] == "http.response.body"
    ]
    assert [message["status"] for message in starts] == [200]
    assert bodies == [b"data: first\n\n"]
    assert response.closed


# happy path test
@pytest.mark.asyncio
async def test_gateway_forwards_successful_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://backend-a/v1/chat/completions"
        assert json.loads(request.content) == basic_payload

        return httpx.Response(
            status_code=200,
            content=backend_body,
            headers={"Content-Type": "application/json"},
        )

    async with gateway_client(handler) as client:
        r = await client.post(url="/v1/chat/completions", json=basic_payload)

    assert r.status_code == 200
    assert r.content == backend_body
    assert r.headers.get("content-type") == "application/json"
    assert r.headers.get("x-infergate-backend") == "backend-a"


# 报 500 错误时，无 content_type
@pytest.mark.asyncio
async def test_gateway_forwards_backend_http_error_without_content_type():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://backend-a/v1/chat/completions"
        assert json.loads(request.content) == basic_payload

        return httpx.Response(
            status_code=500,
            content=error_body,
        )

    async with gateway_client(handler) as client:
        r = await client.post(url="/v1/chat/completions", json=basic_payload)

    assert r.status_code == 500
    assert r.content == error_body
    assert r.headers.get("content-type") is None
    assert r.headers.get("x-infergate-backend") == "backend-a"


# 无可用 backend 时报 503
@pytest.mark.asyncio
async def test_gateway_returns_503_when_no_backend_is_available():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Backend must not be called")

    async with gateway_client(handler, RoundRobinRouter({})) as client:
        r = await client.post(url="/v1/chat/completions", json=basic_payload)

    assert r.status_code == 503
    assert r.json() == {
        "error": {
            "message": "No backend is available for the requested model.",
            "type": "gateway_error",
            "param": None,
            "code": "no_backend_available",
        }
    }
    assert r.headers.get("content-type") == "application/json"
    assert r.headers.get("x-infergate-backend") is None


# 通信 backend 错误时报 502
@pytest.mark.asyncio
async def test_gateway_returns_502_on_backend_transport_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "Connection failed",
            request=request,
        )

    async with gateway_client(handler) as client:
        r = await client.post(url="/v1/chat/completions", json=basic_payload)

    assert r.status_code == 502
    assert r.json() == {
        "error": {
            "message": "Cannot connect to backend.",
            "type": "gateway_error",
            "param": None,
            "code": "backend_transport_failure",
        }
    }
    assert r.headers["content-type"] == "application/json"
    assert r.headers["x-infergate-backend"] == "backend-a"


@pytest.mark.asyncio
async def test_gateway_returns_502_on_non_streaming_body_read_timeout():
    class TimedOutBody(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncGenerator[bytes]:
            yield b"partial response"
            raise httpx.ReadTimeout("Timed out while reading backend body")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=TimedOutBody())

    async with gateway_client(handler) as client:
        response = await client.post("/v1/chat/completions", json=basic_payload)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "backend_transport_failure"
    assert response.headers["x-infergate-backend"] == "backend-a"


# gateway 应无修改转发显式 stream = false 的请求
@pytest.mark.asyncio
async def test_gateway_forwards_explicit_stream_false():
    stream_false_payload = {
        **basic_payload,
        "stream": False,
    }

    def handler(request: httpx.Request):
        assert json.loads(request.content) == stream_false_payload
        return httpx.Response(
            status_code=200,
            content=backend_body,
            headers={"Content-Type": "application/json"},
        )

    async with gateway_client(handler) as client:
        r = await client.post(url="/v1/chat/completions", json=stream_false_payload)
        assert r.status_code == 200


# 测试 stream = true 的请求
@pytest.mark.asyncio
async def test_gateway_forwards_streaming_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {**basic_payload, "stream": True}
        return httpx.Response(
            status_code=200,
            content=b"data: first\n\ndata: second\n\n",
            headers={"Content-Type": "text/event-stream"},
        )

    async with gateway_client(handler) as client:
        r = await client.post(
            url="/v1/chat/completions", json={**basic_payload, "stream": True}
        )
        assert r.status_code == 200
        assert r.content == b"data: first\n\ndata: second\n\n"
        assert r.headers["content-type"] == "text/event-stream"
        assert r.headers.get("x-infergate-backend") == "backend-a"


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
@pytest.mark.asyncio
async def test_gateway_returns_502_when_stream_open_fails(error_type):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("Backend failed before response headers", request=request)

    async with gateway_client(handler) as client:
        response = await client.post(
            url="/v1/chat/completions",
            json={**basic_payload, "stream": True},
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "backend_transport_failure"
    assert response.headers["x-infergate-backend"] == "backend-a"


# gateway 不对未知 message 参数修改，直接发送给 client -> backend
@pytest.mark.asyncio
async def test_gateway_preserves_unknown_message_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == message_payload
        return httpx.Response(
            status_code=200,
            content=backend_body,
            headers={"Content-Type": "application/json"},
        )

    async with gateway_client(handler) as client:
        r = await client.post(url="/v1/chat/completions", json=message_payload)
    assert r.status_code == 200


# gateway 应拒绝非法 message 请求
@pytest.mark.parametrize(
    ("invalid_payload", "expected_param"),
    [
        ({"model": "test-model"}, "messages"),
        ({"model": "test-model", "messages": []}, "messages"),
        (
            {
                "model": "test-model",
                "messages": [{"role": "invalid-role", "content": "hello"}],
            },
            "messages.0.role",
        ),
        (
            {
                "model": "test-model",
                "messages": [{"role": "user", "content": 123}],
            },
            "messages.0.content",
        ),
    ],
)
@pytest.mark.asyncio
async def test_gateway_rejects_invalid_messages(invalid_payload, expected_param):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Backend must not be called")

    async with gateway_client(handler) as client:
        r = await client.post(url="/v1/chat/completions", json=invalid_payload)
        assert r.status_code == 400
        assert r.json() == {
            "error": {
                "message": "Invalid request body.",
                "type": "invalid_request_error",
                "param": expected_param,
                "code": None,
            }
        }


# gateway 应拒绝非严格 Bool 类型的 stream 参数
@pytest.mark.asyncio
async def test_non_bool_stream():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Backend must not be called")

    async with gateway_client(handler) as client:
        r = await client.post(
            url="/v1/chat/completions", json={**basic_payload, "stream": "false"}
        )
        assert r.status_code == 400
        assert r.json() == {
            "error": {
                "message": "Invalid request body.",
                "type": "invalid_request_error",
                "param": "stream",
                "code": None,
            }
        }


@pytest.mark.asyncio
async def test_gateway_round_robins_across_two_backends():
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))

        return httpx.Response(
            status_code=200,
            content=backend_body,
            headers={"Content-Type": "application/json"},
        )

    backend_ids: list[str] = []

    router = RoundRobinRouter(
        {
            "test-model": [
                Backend(id="backend-a", base_url="http://backend-a"),
                Backend(id="backend-b", base_url="http://backend-b"),
            ]
        }
    )
    async with gateway_client(handler, router=router) as client:
        for _ in range(5):
            response = await client.post(
                "/v1/chat/completions",
                json=basic_payload,
            )

            assert response.status_code == 200
            backend_ids.append(response.headers["x-infergate-backend"])

    assert backend_ids == [
        "backend-a",
        "backend-b",
        "backend-a",
        "backend-b",
        "backend-a",
    ]

    assert requested_urls == [
        "http://backend-a/v1/chat/completions",
        "http://backend-b/v1/chat/completions",
        "http://backend-a/v1/chat/completions",
        "http://backend-b/v1/chat/completions",
        "http://backend-a/v1/chat/completions",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, "", "   "])
async def test_invalid_key_is_rejected_before_admission(key):
    limiter = TokenBucketLimiter(1, 1)
    router = make_default_router()

    def handler(_request):
        raise AssertionError("Invalid key must not reach backend")

    async with gateway_client(handler, router, limiter) as client:
        del client.headers["X-InferGate-Key"]
        headers = {} if key is None else {"X-InferGate-Key": key}
        response = await client.post(
            "/v1/chat/completions", json=basic_payload, headers=headers
        )

    assert response.status_code == 400
    assert limiter.buckets == {}
    assert router.cursors["test-model"] == 0
    assert response.json()["error"] == {
        "message": "Invalid infergate key.",
        "type": "invalid_request_error",
        "param": "X-InferGate-Key",
        "code": "invalid_infergate_key",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_rate_limit_rejects_without_routing_and_keeps_keys_independent(
    monkeypatch, stream
):
    monkeypatch.setattr(token_bucket, "time", SimpleNamespace(monotonic=lambda: 0.0))
    limiter = TokenBucketLimiter(1, 1)
    calls = []
    router = RoundRobinRouter(
        {"test-model": [Backend("a", "http://a"), Backend("b", "http://b")]}
    )

    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(200, content=b"data: hello\n\n" if stream else backend_body)

    async with gateway_client(handler, router, limiter) as client:
        payload = {**basic_payload, "stream": stream}
        first = await client.post("/v1/chat/completions", json=payload)
        cursor_before = router.cursors["test-model"]
        rejected = await client.post("/v1/chat/completions", json=payload)
        assert router.cursors["test-model"] == cursor_before
        other = await client.post(
            "/v1/chat/completions", json=payload, headers={"X-InferGate-Key": "other"}
        )

    assert [first.status_code, rejected.status_code, other.status_code] == [200, 429, 200]
    assert calls == ["a", "b"]
    assert rejected.json()["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["transport", "http"])
async def test_backend_failure_does_not_refund_rate_limit(monkeypatch, failure):
    monkeypatch.setattr(token_bucket, "time", SimpleNamespace(monotonic=lambda: 0.0))
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if failure == "transport":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(500, content=error_body)

    async with gateway_client(handler, limiter=TokenBucketLimiter(1, 1)) as client:
        first = await client.post("/v1/chat/completions", json=basic_payload)
        second = await client.post("/v1/chat/completions", json=basic_payload)

    assert first.status_code == (502 if failure == "transport" else 500)
    assert second.status_code == 429
    assert calls == 1
