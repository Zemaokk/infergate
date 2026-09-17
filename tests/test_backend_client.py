import httpx
import pytest
import json
from infergate.backend_client import BackendClient, BackendTransportError
from infergate.router import Backend
from test_mock_backend import example_response, test_request

response_body = json.dumps(example_response).encode("utf-8")
error_body = b'{"error":"error_500"}'

@pytest.mark.asyncio
async def test_backend_client_http_200():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://127.0.0.1:8001/v1/chat/completions"
        assert json.loads(request.content) == test_request
        return httpx.Response(
            status_code=200,
            headers={
                "Content-Type": "application/json"
            },
            content=response_body
        )
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend_client = BackendClient(mock_client)

    r = await backend_client.forward(
        Backend(id="chatcmpl-mock-001",base_url="http://127.0.0.1:8001/"),
        path="/v1/chat/completions",
        payload=test_request
    )

    assert r.status_code == 200
    assert r.body == response_body
    assert r.content_type == "application/json"


@pytest.mark.asyncio
async def test_backend_client_http_500():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=500,
            headers={},
            content=error_body
        )
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend_client = BackendClient(mock_client)

    r = await backend_client.forward(
        Backend(id="chatcmpl-mock-001",base_url="http://127.0.0.1:8001/"),
        path="/v1/chat/completions",
        payload=test_request
    )

    assert r.status_code == 500
    assert r.body == error_body
    assert r.content_type is None


@pytest.mark.asyncio
async def test_backend_client_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "Connection failed",
            request=request
        )
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend_client = BackendClient(mock_client)
    with pytest.raises(BackendTransportError) as e:
        await backend_client.forward(
            Backend(id="chatcmpl-mock-001",base_url="http://127.0.0.1:8001/"),
            path="/v1/chat/completions",
            payload=test_request
        )

    e_msg = str(e.value)
    assert "Transport failure for backend chatcmpl-mock-001" in e_msg
    assert isinstance(e.value.__cause__, httpx.ConnectError)