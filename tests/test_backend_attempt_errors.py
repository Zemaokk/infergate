import asyncio
import time

import httpx
import pytest

from infergate.app import create_app
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.router import Backend, RoundRobinRouter
from infergate.token_bucket import TokenBucketLimiter


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure", ["cancelled", "internal_error"])
async def test_backend_call_failure_finishes_attempt_and_releases_slot(stream, failure):
    entered = asyncio.Event()
    observations = []

    class FailingClient:
        async def forward(self, **kwargs):
            entered.set()
            if failure == "cancelled":
                await asyncio.Event().wait()
            raise RuntimeError("backend adapter failed")

        open_stream = forward

    limiter = ConcurrencyLimiter(1)
    app = create_app(
        RoundRobinRouter({"test": [Backend("a", "http://a")]}),
        FailingClient(), TokenBucketLimiter(2, 1), limiter,
    )

    async def capture(scope, receive, send):
        try:
            await app(scope, receive, send)
        finally:
            observations.append(scope["state"]["observation"])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=capture), base_url="http://gateway"
    ) as client:
        task = asyncio.create_task(client.post(
            "/v1/chat/completions",
            headers={"X-InferGate-Key": "test"},
            json={"model": "test", "messages": [{"role": "user", "content": "hi"}],
                  "stream": stream},
        ))
        await asyncio.wait_for(entered.wait(), 1)
        if failure == "cancelled":
            task.cancel()
        with pytest.raises(asyncio.CancelledError if failure == "cancelled" else RuntimeError):
            await task

    observation = observations[0]
    assert observation.outcome == failure
    assert observation.attempts == 1
    attempt = observation.backend_attempts[0]
    assert attempt.outcome == failure
    assert attempt.is_finished
    assert 0 <= attempt.total_time <= observation.total_time
    assert limiter.available == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
async def test_stream_construction_failure_waits_for_cleanup_and_finishes_attempt(
    monkeypatch, close_fails
):
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()
    scopes = []
    closed_at = []

    class Stream:
        status_code = 200
        content_type = "text/event-stream"

        async def aclose(self):
            cleanup_entered.set()
            await cleanup_release.wait()
            closed_at.append(time.monotonic())
            if close_fails:
                raise RuntimeError("close failed")

    class Client:
        async def open_stream(self, **kwargs):
            return Stream()

    def fail_construction(*args, **kwargs):
        raise ValueError("response construction failed")

    monkeypatch.setattr("infergate.app.LimitedStreamingResponse", fail_construction)
    limiter = ConcurrencyLimiter(1)
    app = create_app(
        RoundRobinRouter({"test": [Backend("a", "http://a")]}),
        Client(), TokenBucketLimiter(2, 1), limiter,
    )

    async def capture(scope, receive, send):
        scopes.append(scope)
        await app(scope, receive, send)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=capture), base_url="http://gateway"
    ) as client:
        task = asyncio.create_task(client.post(
            "/v1/chat/completions",
            headers={"X-InferGate-Key": "test"},
            json={"model": "test", "messages": [{"role": "user", "content": "hi"}],
                  "stream": True},
        ))
        try:
            await asyncio.wait_for(cleanup_entered.wait(), 1)
            observation = scopes[0]["state"]["observation"]
            attempt = observation.backend_attempts[0]
            assert not attempt.is_finished
            assert not observation.is_finished
            assert limiter.available == 0
        finally:
            cleanup_release.set()
            with pytest.raises(RuntimeError if close_fails else ValueError):
                await task

    assert observation.outcome == "internal_error"
    assert observation.cleanup_failed is close_fails
    assert attempt.outcome == "internal_error"
    assert attempt.is_finished
    assert attempt.started_at + attempt.total_time >= closed_at[0]
    assert limiter.available == 1
