import json

import httpx
import pytest
from test_mock_backend import example_response, test_request

from infergate.backend_client import BackendClient, BackendTransportError
from infergate.router import Backend

response_body = json.dumps(example_response).encode("utf-8")
error_body = b'{"error":"error_500"}'


@pytest.mark.asyncio
async def test_backend_client_http_200():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://127.0.0.1:8001/v1/chat/completions"
        assert json.loads(request.content) == test_request
        return httpx.Response(
            status_code=200,
            headers={"Content-Type": "application/json"},
            content=response_body,
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend_client = BackendClient(mock_client)

    r = await backend_client.forward(
        Backend(id="chatcmpl-mock-001", base_url="http://127.0.0.1:8001/"),
        path="/v1/chat/completions",
        payload=test_request,
    )

    assert r.status_code == 200
    assert r.body == response_body
    assert r.content_type == "application/json"


@pytest.mark.asyncio
async def test_backend_client_http_500():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=500, headers={}, content=error_body)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend_client = BackendClient(mock_client)

    r = await backend_client.forward(
        Backend(id="chatcmpl-mock-001", base_url="http://127.0.0.1:8001/"),
        path="/v1/chat/completions",
        payload=test_request,
    )

    assert r.status_code == 500
    assert r.body == error_body
    assert r.content_type is None


@pytest.mark.asyncio
async def test_backend_client_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection failed", request=request)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend_client = BackendClient(mock_client)
    with pytest.raises(BackendTransportError) as e:
        await backend_client.forward(
            Backend(id="chatcmpl-mock-001", base_url="http://127.0.0.1:8001/"),
            path="/v1/chat/completions",
            payload=test_request,
        )

    e_msg = str(e.value)
    assert "Transport failure for backend chatcmpl-mock-001" in e_msg
    assert isinstance(e.value.__cause__, httpx.ConnectError)


@pytest.mark.asyncio
async def test_backend_client_opens_stream_without_reading_it_eagerly():
    class TrackingStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.iterated = False
            self.closed = False

        async def __aiter__(self):
            self.iterated = True
            yield b"data: first\n\n"
            yield b"data: second\n\n"

        async def aclose(self) -> None:
            self.closed = True

    stream = TrackingStream()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://127.0.0.1:8001/v1/chat/completions"
        assert json.loads(request.content) == test_request
        return httpx.Response(
            status_code=200,
            headers={"Content-Type": "text/event-stream"},
            stream=stream,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend_client = BackendClient(client)
        response = await backend_client.open_stream(
            Backend(id="backend-a", base_url="http://127.0.0.1:8001/"),
            path="/v1/chat/completions",
            payload=test_request,
        )

        assert response.status_code == 200
        assert response.content_type == "text/event-stream"
        assert not stream.iterated
        assert not stream.closed
        assert b"".join([chunk async for chunk in response.aiter_bytes()]) == (
            b"data: first\n\ndata: second\n\n"
        )

        await response.aclose()

        assert stream.iterated
        assert stream.closed


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
@pytest.mark.asyncio
async def test_backend_client_open_stream_maps_transport_error(error_type):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("Backend failed", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend_client = BackendClient(client)

        with pytest.raises(BackendTransportError) as exc_info:
            await backend_client.open_stream(
                Backend(id="backend-a", base_url="http://127.0.0.1:8001/"),
                path="/v1/chat/completions",
                payload=test_request,
            )

    assert isinstance(exc_info.value.__cause__, error_type)
