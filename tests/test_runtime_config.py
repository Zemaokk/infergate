import json
from unittest.mock import patch

import httpx
import pytest

from infergate.runtime import create_runtime_app, read_backend_url


ENV_NAMES = ("INFERGATE_BACKEND_A_URL", "INFERGATE_BACKEND_B_URL")
REQUEST = {"model": "mock-model", "messages": [{"role": "user", "content": "hi"}]}


@pytest.fixture(autouse=True)
def clear_backend_environment(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("name", "default"),
    list(zip(ENV_NAMES, ("http://127.0.0.1:8001", "http://127.0.0.1:8002"))),
)
def test_unset_backend_url_uses_default(name, default):
    assert read_backend_url(name, default) == default


@pytest.mark.parametrize("name", ENV_NAMES)
@pytest.mark.parametrize("value", ["http://backend:8000", " https://backend:8000/ "])
def test_valid_backend_url_is_trimmed(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    assert read_backend_url(name, "unused") == value.strip()


@pytest.mark.parametrize("name", ENV_NAMES)
@pytest.mark.parametrize(
    "value",
    [
        "", "   ", "not-a-url", "ftp://backend:8000", "http:///path",
        "http://backend:bad", "http://user:dummy@backend", "http://backend?x=1",
        "http://backend#part", "http://backend/prefix",
    ],
)
def test_invalid_backend_config_fails_before_client_creation(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with patch("infergate.runtime.httpx.AsyncClient") as client:
        with pytest.raises(ValueError) as error:
            create_runtime_app()
        assert str(error.value) == f"{name} is invalid"
        assert error.value.__suppress_context__
        client.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_custom_backend_urls_are_shared_and_frozen_per_app(monkeypatch, stream):
    probes = []
    calls = []
    chunks = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'

    def probe(request):
        probes.append(str(request.url))
        return httpx.Response(200)

    def backend(request):
        calls.append(str(request.url))
        assert json.loads(request.content)["model"] == "mock-model"
        if stream:
            return httpx.Response(200, content=chunks, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setenv(ENV_NAMES[0], " http://custom-a:8101/ ")
    monkeypatch.setenv(ENV_NAMES[1], "http://custom-b:8102")
    app = create_runtime_app(
        probe_transport=httpx.MockTransport(probe),
        backend_transport=httpx.MockTransport(backend),
    )
    # Changing configuration after creation must not retarget an existing app.
    monkeypatch.setenv(ENV_NAMES[0], "http://new-a:8201")
    monkeypatch.setenv(ENV_NAMES[1], "http://new-b:8202")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://gateway") as client:
            for backend_id in ("backend-a", "backend-b"):
                response = await client.post(
                    "/v1/chat/completions", json={**REQUEST, "stream": stream},
                    headers={"X-InferGate-Key": f"config-{backend_id}"},
                )
                assert response.status_code == 200
                assert response.headers["X-InferGate-Backend"] == backend_id
                if stream:
                    assert response.content == chunks
                else:
                    assert response.json() == {"ok": True}

    assert sorted(probes) == ["http://custom-a:8101/health", "http://custom-b:8102/health"]
    assert calls == ["http://custom-a:8101/v1/chat/completions", "http://custom-b:8102/v1/chat/completions"]

    # A newly created app reads the current environment rather than module globals.
    probes.clear()
    app = create_runtime_app(
        probe_transport=httpx.MockTransport(probe),
        backend_transport=httpx.MockTransport(backend),
    )
    async with app.router.lifespan_context(app):
        assert sorted(probes) == ["http://new-a:8201/health", "http://new-b:8202/health"]
