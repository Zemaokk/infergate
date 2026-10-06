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
        request = Request(app_scope)
        assert request.state.existing is marker
        assert request.state.observation.started_at == 10.0
        assert request.state.observation.is_finished is False
        assert await app_receive() is incoming
        await app_send(outgoing)

    await RequestObservationMiddleware(app)(scope, receive, send)
    assert sent == [outgoing]
    assert scope["state"]["observation"].is_finished is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope",
    [
        {"type": "lifespan"},
        {"type": "websocket", "path": "/v1/chat/completions"},
        {"type": "http", "method": "GET", "path": "/v1/chat/completions"},
        {"type": "http", "method": "GET", "path": "/metrics"},
        {"type": "http", "method": "GET", "path": "/v1/responses"},
        {"type": "http", "method": "POST", "path": "/v1/unknown"},
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
            observation.start_attempt("a", observation.started_at)
            await entered.wait()
        else:
            entered.set()
            assert observation.attempts == 0
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
    assert observations[0].attempts == 1
    assert observations[1].attempts == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("last_chunk_flags", [{"more_body": False}, {}])
async def test_response_signals_update_after_send_and_do_not_finish_before_cleanup(
    last_chunk_flags,
):
    scope = {"type": "http", "method": "POST", "path": "/v1/chat/completions"}
    messages = [
        {"type": "http.response.start", "status": 200, "headers": []},
        {"type": "http.response.body", "body": b"first", "more_body": True},
        {"type": "http.response.body", "body": b"", **last_chunk_flags},
    ]
    forwarded = []

    async def receive():
        raise AssertionError("Unexpected receive")

    async def send(message):
        observation = scope["state"]["observation"]
        if message["type"] == "http.response.start":
            assert observation.status_code is None
        assert observation.response_complete is False
        forwarded.append(message)

    async def app(scope, receive, send):
        observation = scope["state"]["observation"]
        await send(messages[0])
        assert observation.status_code == 200
        await send(messages[1])
        assert observation.response_complete is False
        await send(messages[2])
        assert observation.response_complete is True
        # The response's cleanup can still be running at this point.
        assert observation.is_finished is False
        assert observation.total_time is None

    await RequestObservationMiddleware(app)(scope, receive, send)
    assert len(forwarded) == len(messages)
    assert all(actual is original for actual, original in zip(forwarded, messages))


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", ["http.response.start", "http.response.body"])
@pytest.mark.parametrize("error_type", [OSError, asyncio.CancelledError])
async def test_failed_send_does_not_record_success_and_preserves_exception(
    fail_at, error_type
):
    scope = {"type": "http", "method": "POST", "path": "/v1/chat/completions"}
    failure = error_type("send interrupted")

    async def receive():
        raise AssertionError("Unexpected receive")

    async def send(message):
        if message["type"] == fail_at:
            raise failure

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"last", "more_body": False})

    with pytest.raises(error_type) as captured:
        await RequestObservationMiddleware(app)(scope, receive, send)
    assert captured.value is failure
    observation = scope["state"]["observation"]
    assert observation.status_code == (None if fail_at == "http.response.start" else 200)
    assert observation.response_complete is False
    assert observation.is_finished is True
    assert observation.outcome == "cancelled"
