import json

import httpx
import pytest

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.router import Backend, RoundRobinRouter

payload = {
    "model": "test-model",
    "messages": [{"role": "user", "content": "hello"}],
    "temperature": 0.7,
}

backend_body = b'{"id": "response-001", "output": "hello"}'
error_body = b'{"error":"backend_failed"}'


@pytest.mark.asyncio
async def test_gateway_forwards_successful_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://backend-a/v1/chat/completions"
        assert json.loads(request.content) == payload

        return httpx.Response(
            status_code=200,
            content=backend_body,
            headers={"Content-Type": "application/json"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as backend_base_client:
        router = RoundRobinRouter(
            {"test-model": [Backend(id="backend-a", base_url="http://backend-a")]}
        )
        app = create_app(router, BackendClient(backend_base_client))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as gateway_client:
            r = await gateway_client.post(url="/v1/chat/completions", json=payload)

            assert r.status_code == 200
            assert r.content == backend_body
            assert r.headers.get("content-type") == "application/json"
            assert r.headers.get("x-infergate-backend") == "backend-a"


@pytest.mark.asyncio
async def test_gateway_forwards_backend_http_error_without_content_type():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://backend-a/v1/chat/completions"
        assert json.loads(request.content) == payload

        return httpx.Response(
            status_code=500,
            content=error_body,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as backend_base_client:
        router = RoundRobinRouter(
            {"test-model": [Backend(id="backend-a", base_url="http://backend-a")]}
        )
        app = create_app(router, BackendClient(backend_base_client))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as gateway_client:
            r = await gateway_client.post(url="/v1/chat/completions", json=payload)

            assert r.status_code == 500
            assert r.content == error_body
            assert r.headers.get("content-type") is None
            assert r.headers.get("x-infergate-backend") == "backend-a"


@pytest.mark.asyncio
async def test_gateway_returns_503_when_no_backend_is_available():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Backend must not be called")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as backend_base_client:
        router = RoundRobinRouter({})
        app = create_app(router, BackendClient(backend_base_client))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as gateway_client:
            r = await gateway_client.post(url="/v1/chat/completions", json=payload)

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


@pytest.mark.asyncio
async def test_gateway_returns_502_on_backend_transport_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "Connection failed",
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as backend_base_client:
        router = RoundRobinRouter(
            {"test-model": [Backend(id="backend-a", base_url="http://backend-a")]}
        )
        app = create_app(router, BackendClient(backend_base_client))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as gateway_client:
            r = await gateway_client.post(url="/v1/chat/completions", json=payload)

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
async def test_gateway_forwards_explicit_stream_false():
    stream_false_payload = {
        **payload,
        "stream": False,
    }

    def handler(request: httpx.Request):
        assert json.loads(request.content) == stream_false_payload
        return httpx.Response(
            status_code=200,
            content=backend_body,
            headers={"Content-Type": "application/json"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as backend_base_client:
        router = RoundRobinRouter(
            {"test-model": [Backend(id="backend-a", base_url="http://backend-a")]}
        )
        app = create_app(router, BackendClient(backend_base_client))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as gateway_client:
            await gateway_client.post(
                url="/v1/chat/completions", json=stream_false_payload
            )


@pytest.mark.asyncio
async def test_gateway_rejects_stream_true_before_backend_selection():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Backend must not be called")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as backend_base_client:
        router = RoundRobinRouter(
            {"test-model": [Backend(id="backend-a", base_url="http://backend-a")]}
        )
        app = create_app(router, BackendClient(backend_base_client))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as gateway_client:
            r = await gateway_client.post(
                url="/v1/chat/completions", json={**payload, "stream": True}
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
