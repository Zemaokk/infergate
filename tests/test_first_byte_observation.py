from types import SimpleNamespace

import httpx
import pytest

from infergate.app import LimitedStreamingResponse
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.observability import BackendAttemptObservation, RequestObservation


@pytest.mark.asyncio
@pytest.mark.parametrize("first_nonempty", [b" ", b"\n", b"data: hello\n\n"])
async def test_first_byte_is_recorded_on_read_before_send_without_prefetch(
    monkeypatch, first_nonempty
):
    clock = SimpleNamespace(now=10.0)
    monkeypatch.setattr("infergate.app.time", SimpleNamespace(monotonic=lambda: clock.now))
    observation = RequestObservation(10.0)
    attempt = observation.start_attempt("b", 10.25)
    chunks_read = []

    class Stream:
        status_code = 200

        async def aiter_bytes(self):
            for when, chunk in [(10.25, b""), (10.5, first_nonempty), (12.0, b"later")]:
                clock.now = when
                chunks_read.append(chunk)
                yield chunk

    response = LimitedStreamingResponse(Stream(), ConcurrencyLimiter(1), {}, observation, attempt)
    iterator = response.body_iterator
    assert chunks_read == []
    assert await anext(iterator) == b""
    assert observation.first_byte_sec is None
    assert attempt.first_byte_sec is None
    assert chunks_read == [b""]
    assert await anext(iterator) == first_nonempty
    # No send() has occurred; the sample already exists at the read boundary.
    assert observation.first_byte_sec == 0.5
    assert attempt.first_byte_sec == 0.25
    assert chunks_read == [b"", first_nonempty]
    assert await anext(iterator) == b"later"
    assert observation.first_byte_sec == 0.5
    assert attempt.first_byte_sec == 0.25
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_empty_stream_or_failure_before_nonempty_chunk_has_no_sample(fail):
    observation = RequestObservation(10.0)
    attempt = observation.start_attempt("b", 10.25)

    class Stream:
        status_code = 200

        async def aiter_bytes(self):
            yield b""
            if fail:
                raise httpx.ReadError("read failed before first byte")

    response = LimitedStreamingResponse(Stream(), ConcurrencyLimiter(1), {}, observation, attempt)
    iterator = response.body_iterator
    assert await anext(iterator) == b""
    with pytest.raises(httpx.ReadError if fail else StopAsyncIteration):
        await anext(iterator)
    assert observation.first_byte_sec is None
    assert attempt.first_byte_sec is None


@pytest.mark.asyncio
async def test_send_failure_does_not_erase_already_read_first_byte(monkeypatch):
    monkeypatch.setattr("infergate.app.time", SimpleNamespace(monotonic=lambda: 10.5))
    observation = RequestObservation(10.0)
    attempt = observation.start_attempt("b", 10.25)

    class Stream:
        status_code = 200
        closed = False

        async def aiter_bytes(self):
            yield b"hello"

        async def aclose(self):
            self.closed = True

    stream = Stream()
    limiter = ConcurrencyLimiter(1)
    assert limiter.try_acquire()
    response = LimitedStreamingResponse(stream, limiter, {}, observation, attempt)

    async def receive():
        raise AssertionError("ASGI 2.4 response should not poll receive")

    async def send(message):
        if message["type"] == "http.response.start":
            assert observation.first_byte_sec is None
        else:
            assert observation.first_byte_sec == 0.5
            raise RuntimeError("send failed")

    with pytest.raises(RuntimeError, match="send failed"):
        await response(
            {"type": "http", "asgi": {"spec_version": "2.4"},
             "state": {"observation": observation}}, receive, send
        )
    assert observation.first_byte_sec == 0.5
    assert attempt.first_byte_sec == 0.25
    assert attempt.outcome == "internal_error"
    assert attempt.is_finished
    assert stream.closed
    assert limiter.available == 1


@pytest.mark.parametrize("offset", [0.0, 0.25])
def test_attempt_first_byte_keeps_first_sample_and_ignores_updates_after_finish(offset):
    attempt = BackendAttemptObservation("b", 10.0)
    attempt.record_first_byte(10.0 + offset)
    attempt.record_first_byte(11.0)
    assert attempt.first_byte_sec == offset
    attempt.finish("stream_error", 12.0)
    attempt.record_first_byte(13.0)
    assert attempt.first_byte_sec == offset
    untouched = BackendAttemptObservation("a", 10.0)
    untouched.finish("transport_error", 10.0)
    untouched.record_first_byte(11.0)
    assert untouched.first_byte_sec is None


@pytest.mark.asyncio
async def test_attempt_first_byte_is_recorded_without_request_observation(monkeypatch):
    monkeypatch.setattr("infergate.app.time", SimpleNamespace(monotonic=lambda: 10.0))
    attempt = BackendAttemptObservation("a", 10.0)

    class Stream:
        status_code = 200

        async def aiter_bytes(self):
            yield b"\n"

    response = LimitedStreamingResponse(
        Stream(), ConcurrencyLimiter(1), {}, backend_attempt_observation=attempt
    )
    assert await anext(response.body_iterator) == b"\n"
    assert attempt.first_byte_sec == 0.0
    await response.body_iterator.aclose()
