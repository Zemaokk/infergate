import asyncio

import httpx
import pytest

from infergate.app import LimitedStreamingResponse
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.observability import RequestObservationMiddleware


class LifecycleStream:
    status_code = 200

    def __init__(self, mode, close_fails):
        self.mode = mode
        self.close_fails = close_fails
        self.entered = asyncio.Event()
        self.closed = False

    async def aiter_bytes(self):
        self.entered.set()
        if self.mode == "blocked":
            await asyncio.Event().wait()
        yield b"data: hello\n\n"
        if self.mode == "read_error":
            raise httpx.ReadError("broken stream")

    async def aclose(self):
        self.closed = True
        if self.close_fails:
            raise RuntimeError("cleanup failed")


def setup_response(stream, spec="2.4"):
    scope = {
        "type": "http", "method": "POST", "path": "/v1/chat/completions",
        "asgi": {"spec_version": spec},
    }
    limiter = ConcurrencyLimiter(1)
    assert limiter.try_acquire()
    response = LimitedStreamingResponse(stream, limiter, {})

    async def app(scope, receive, send):
        scope["state"]["observation"].make_result("completed")
        await response(scope, receive, send)

    async def send(message):
        pass

    return scope, limiter, RequestObservationMiddleware(app), send


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", ["2.3", "2.4"])
@pytest.mark.parametrize("mode", ["normal", "read_error"])
@pytest.mark.parametrize("close_fails", [False, True])
async def test_stream_finalization_preserves_primary_error_after_cleanup(
    spec, mode, close_fails
):
    stream = LifecycleStream(mode, close_fails)
    scope, limiter, middleware, send = setup_response(stream, spec)

    async def receive():
        await asyncio.Event().wait()

    if close_fails or mode == "read_error":
        error = RuntimeError if close_fails else httpx.ReadError
        with pytest.raises(error):
            await middleware(scope, receive, send)
    else:
        await middleware(scope, receive, send)

    observation = scope["state"]["observation"]
    expected = "stream_error" if mode == "read_error" else (
        "internal_error" if close_fails else "completed"
    )
    assert observation.outcome == expected
    assert observation.status_code == 200
    assert observation.response_complete is (mode == "normal")
    assert observation.cleanup_failed is close_fails
    assert observation.is_finish is True
    assert observation.total_time >= 0
    assert stream.closed
    assert limiter.available == 1


@pytest.mark.asyncio
async def test_finish_waits_for_cleanup_after_last_body():
    entered_cleanup = asyncio.Event()
    release_cleanup = asyncio.Event()

    class DelayedCleanupStream(LifecycleStream):
        async def aclose(self):
            entered_cleanup.set()
            await release_cleanup.wait()
            await super().aclose()

    stream = DelayedCleanupStream("normal", False)
    scope, limiter, middleware, send = setup_response(stream)

    async def receive():
        await asyncio.Event().wait()

    task = asyncio.create_task(middleware(scope, receive, send))
    try:
        await asyncio.wait_for(entered_cleanup.wait(), timeout=1)
        observation = scope["state"]["observation"]
        assert observation.response_complete is True
        assert observation.is_finish is False
        assert observation.total_time is None
        assert limiter.available == 0
    finally:
        release_cleanup.set()
        await task
    assert observation.outcome == "completed"
    assert observation.is_finish is True
    assert stream.closed
    assert limiter.available == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
@pytest.mark.parametrize("cancellation", ["disconnect", "task_cancel"])
async def test_disconnect_or_task_cancel_remains_primary_if_cleanup_fails(
    close_fails, cancellation
):
    stream = LifecycleStream("blocked", close_fails)
    spec = "2.3" if cancellation == "disconnect" else "2.4"
    scope, limiter, middleware, send = setup_response(stream, spec)

    async def receive():
        await stream.entered.wait()
        return {"type": "http.disconnect"}

    task = asyncio.create_task(middleware(scope, receive, send))
    await asyncio.wait_for(stream.entered.wait(), timeout=1)
    if cancellation == "task_cancel":
        task.cancel()
    if close_fails:
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await task
    elif cancellation == "task_cancel":
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task

    observation = scope["state"]["observation"]
    assert observation.outcome == "cancelled"
    assert observation.reason is None
    assert observation.cleanup_failed is close_fails
    assert observation.response_complete is False
    assert observation.is_finish is True
    assert stream.closed
    assert limiter.available == 1
