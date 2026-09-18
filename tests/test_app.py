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
