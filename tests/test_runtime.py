import asyncio

import httpx
import pytest

from infergate.runtime import BACKEND_TIMEOUT, create_runtime_app


REQUEST = {"model": "mock-model", "messages": [{"role": "user", "content": "hi"}]}


def test_backend_timeout_policy():
    assert BACKEND_TIMEOUT.connect == 5.0
    assert BACKEND_TIMEOUT.pool == 5.0
    assert BACKEND_TIMEOUT.write == 30.0
    assert BACKEND_TIMEOUT.read == 30.0


@pytest.mark.asyncio
async def test_startup_probes_before_serving_and_routes_to_healthy_peer() -> None:
    probe_hosts: list[str] = []
    inference_hosts: list[str] = []

    def probe_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/health"
        probe_hosts.append(request.url.host + ":" + str(request.url.port))
        return httpx.Response(503 if request.url.port == 8001 else 200)

    def backend_handler(request: httpx.Request) -> httpx.Response:
        inference_hosts.append(request.url.host + ":" + str(request.url.port))
        return httpx.Response(200, json={"ok": True})

    app = create_runtime_app(
        probe_transport=httpx.MockTransport(probe_handler),
        backend_transport=httpx.MockTransport(backend_handler),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway"
        ) as client:
            response = await client.post("/v1/chat/completions", json=REQUEST)

    assert sorted(probe_hosts) == ["127.0.0.1:8001", "127.0.0.1:8002"]
    assert response.status_code == 200
    assert response.headers["X-InferGate-Backend"] == "backend-b"
    assert inference_hosts == ["127.0.0.1:8002"]


@pytest.mark.asyncio
async def test_all_backends_unhealthy_returns_503_without_inference() -> None:
    def probe_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    def backend_handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("No inference request should be sent")

    app = create_runtime_app(
        probe_transport=httpx.MockTransport(probe_handler),
        backend_transport=httpx.MockTransport(backend_handler),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway"
        ) as client:
            response = await client.post("/v1/chat/completions", json=REQUEST)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "no_backend_available"


@pytest.mark.asyncio
async def test_periodic_probe_restores_backend_to_routing() -> None:
    backend_a_healthy = False

    def probe_handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 8001:
            return httpx.Response(200 if backend_a_healthy else 503)
        return httpx.Response(200)

    def backend_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    app = create_runtime_app(
        probe_transport=httpx.MockTransport(probe_handler),
        backend_transport=httpx.MockTransport(backend_handler),
        probe_interval_seconds=0.01,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway"
        ) as client:
            first = await client.post("/v1/chat/completions", json=REQUEST)
            assert first.headers["X-InferGate-Backend"] == "backend-b"

            backend_a_healthy = True
            async with asyncio.timeout(1.0):
                while True:
                    await asyncio.sleep(0.01)
                    response = await client.post("/v1/chat/completions", json=REQUEST)
                    if response.headers["X-InferGate-Backend"] == "backend-a":
                        break

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_streaming_request_uses_healthy_backend_and_preserves_body() -> None:
    chunks = [b"data: first\n\n", b"data: second\n\n"]
    stream_closed = False
    inference_ports: list[int | None] = []

    class BackendStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in chunks:
                yield chunk

        async def aclose(self) -> None:
            nonlocal stream_closed
            stream_closed = True

    def probe_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503 if request.url.port == 8001 else 200)

    def backend_handler(request: httpx.Request) -> httpx.Response:
        inference_ports.append(request.url.port)
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=BackendStream(),
        )

    app = create_runtime_app(
        probe_transport=httpx.MockTransport(probe_handler),
        backend_transport=httpx.MockTransport(backend_handler),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway"
        ) as client:
            response = await client.post(
                "/v1/chat/completions", json={**REQUEST, "stream": True}
            )

    assert response.status_code == 200
    assert response.headers["X-InferGate-Backend"] == "backend-b"
    assert response.headers["content-type"] == "text/event-stream"
    assert response.content == b"".join(chunks)
    assert inference_ports == [8002]
    assert stream_closed
