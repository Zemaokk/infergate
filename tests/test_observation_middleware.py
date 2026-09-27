import asyncio

import pytest
from starlette.requests import Request

from infergate.observability import RequestObservationMiddleware


@pytest.mark.asyncio
async def test_observation_is_available_through_request_state_and_messages_pass_through(
    monkeypatch,
):
    monkeypatch.setattr("infergate.observability.time.monotonic", lambda: 10.0)
    marker = object()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "state": {"existing": marker},
    }
    incoming = {"type": "http.request", "body": b"invalid json", "more_body": False}
    outgoing = {"type": "http.response.body", "body": b"error"}
    sent = []

    async def receive():
        return incoming

    async def send(message):
        sent.append(message)

    async def app(app_scope, app_receive, app_send):
        assert app_scope is scope
        assert app_receive is receive
        assert app_send is send
        request = Request(app_scope)
        assert request.state.existing is marker
        assert request.state.observation.started_at == 10.0
        assert request.state.observation.is_finish is False
        assert await app_receive() is incoming
        await app_send(outgoing)

    await RequestObservationMiddleware(app)(scope, receive, send)
    assert sent == [outgoing]
    assert scope["state"]["observation"].is_finish is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope",
    [
        {"type": "lifespan"},
        {"type": "websocket", "path": "/v1/chat/completions"},
        {"type": "http", "method": "GET", "path": "/v1/chat/completions"},
        {"type": "http", "method": "GET", "path": "/metrics"},
    ],
)
async def test_other_scopes_pass_through_without_observation(scope):
    calls = []

    async def receive():
        raise AssertionError("Middleware should not consume messages")

    async def send(message):
        raise AssertionError("Middleware should not generate messages")

    async def app(app_scope, app_receive, app_send):
        calls.append(app_scope)
        assert app_scope is scope
        assert app_receive is receive
        assert app_send is send

    await RequestObservationMiddleware(app)(scope, receive, send)
    assert len(calls) == 1
    assert "state" not in scope


@pytest.mark.asyncio
async def test_overlapping_requests_have_independent_observations():
    entered = asyncio.Event()
    observations = []

    async def receive():
        raise AssertionError("Unexpected receive")

    async def send(message):
        raise AssertionError("Unexpected send")

    async def app(scope, receive, send):
        observation = scope["state"]["observation"]
        observations.append(observation)
        if len(observations) == 1:
            observation.start_attempt()
            await entered.wait()
        else:
            entered.set()
            assert observation.attempt == 0
        assert scope["state"]["observation"] is observation

    middleware = RequestObservationMiddleware(app)
    first = {"type": "http", "method": "POST", "path": "/v1/chat/completions"}
    second = dict(first)
    await asyncio.wait_for(
        asyncio.gather(
            middleware(first, receive, send), middleware(second, receive, send)
        ),
        timeout=1,
    )
    assert observations[0] is not observations[1]
    assert observations[0].attempt == 1
    assert observations[1].attempt == 0
