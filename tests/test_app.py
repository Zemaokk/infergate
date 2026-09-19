import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import httpx
import pytest

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.router import Backend, RoundRobinRouter

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
    handler: Handler, router: RoundRobinRouter | None = None
) -> AsyncGenerator[httpx.AsyncClient]:
    router = router if router is not None else make_default_router()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as backend_http_client:
        app = create_app(router, BackendClient(backend_http_client))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway"
        ) as client:
            yield client


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


# gateway 应拒绝 stream = true 的请求
@pytest.mark.asyncio
async def test_gateway_rejects_stream_true_before_backend_selection():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Backend must not be called")

    async with gateway_client(handler) as client:
        r = await client.post(
            url="/v1/chat/completions", json={**basic_payload, "stream": True}
        )
        assert r.status_code == 400
        assert r.json() == {
            "error": {
                "message": "Streaming is not supported in M0.",
                "type": "invalid_request_error",
                "param": "stream",
                "code": None,
            }
        }
        assert r.headers["content-type"] == "application/json"
        assert r.headers.get("x-infergate-backend") is None


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
