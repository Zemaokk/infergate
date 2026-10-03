import asyncio
import json
import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from infergate.observability import RequestObservationMiddleware


def tracing_fixture():
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome, expected_status",
    [("completed", StatusCode.OK), ("rejected", StatusCode.UNSET),
     ("stream_error", StatusCode.ERROR), ("cancelled", StatusCode.ERROR)],
)
async def test_request_span_matches_final_outcome_and_log_ids(outcome, expected_status, caplog):
    caplog.set_level(logging.INFO, logger="infergate.observability")
    provider, exporter = tracing_fixture()
    original = asyncio.CancelledError("private exception") if outcome == "cancelled" else None

    async def app(scope, receive, send):
        observation = scope["state"]["observation"]
        observation.make_result("rejected" if outcome == "rejected" else "completed")
        if outcome in {"stream_error", "cancelled"}:
            observation.record_failure(outcome)
        if original is not None:
            raise original
        await send({"type": "http.response.start", "status": 400 if outcome == "rejected" else 200})
        await send({"type": "http.response.body", "body": b"private body"})

    async def receive():
        raise AssertionError("unexpected receive")

    async def send(message):
        pass

    scope = {"type": "http", "method": "POST", "path": "/v1/chat/completions"}
    middleware = RequestObservationMiddleware(app, tracer=provider.get_tracer("test"))
    try:
        if original is None:
            await middleware(scope, receive, send)
        else:
            with pytest.raises(asyncio.CancelledError) as caught:
                await middleware(scope, receive, send)
            assert caught.value is original
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.kind is SpanKind.SERVER
        assert span.parent is None
        assert span.status.status_code is expected_status
        assert span.attributes["infergate.outcome"] == outcome
        assert "private" not in str(span.attributes)
        assert span.events == ()
        log = json.loads([r for r in caplog.records if r.levelno == logging.INFO][0].getMessage())
        assert log["trace_id"] == f"{span.context.trace_id:032x}"
        assert log["span_id"] == f"{span.context.span_id:016x}"
        assert span.attributes["infergate.request_id"] == log["request_id"]
    finally:
        provider.shutdown()


@pytest.mark.asyncio
async def test_span_stays_open_until_cleanup_returns():
    provider, exporter = tracing_fixture()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def app(scope, receive, send):
        scope["state"]["observation"].make_result("completed")
        try:
            await send({"type": "http.response.body", "body": b""})
        finally:
            entered.set()
            await release.wait()

    async def receive():
        raise AssertionError("unexpected receive")

    async def send(message):
        pass

    task = asyncio.create_task(RequestObservationMiddleware(
        app, tracer=provider.get_tracer("test")
    )({"type": "http", "method": "POST", "path": "/v1/chat/completions"}, receive, send))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert exporter.get_finished_spans() == ()
    finally:
        release.set()
        await task
        provider.shutdown()
    assert len(exporter.get_finished_spans()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["start", "finish", "end"])
async def test_tracing_failure_does_not_change_business_or_prevent_metrics(failure_stage):
    calls = []

    class BrokenSpan:
        def get_span_context(self):
            from opentelemetry.trace import INVALID_SPAN_CONTEXT
            return INVALID_SPAN_CONTEXT

        def set_attribute(self, *args):
            if failure_stage == "finish":
                raise ValueError("attribute failed")

        def set_status(self, *args):
            pass

        def end(self):
            calls.append("end")
            if failure_stage == "end":
                raise ValueError("export failed")

    class BrokenTracer:
        def start_span(self, *args, **kwargs):
            if failure_stage == "start":
                raise ValueError("start failed")
            return BrokenSpan()

    original = RuntimeError("business failed")

    async def app(scope, receive, send):
        raise original

    async def unused(*args):
        pass

    def metrics(observation):
        calls.append(observation.outcome)

    with pytest.raises(RuntimeError) as caught:
        await RequestObservationMiddleware(app, metrics, BrokenTracer())(
            {"type": "http", "method": "POST", "path": "/v1/chat/completions"}, unused, unused
        )
    assert caught.value is original
    assert calls[-1] == "internal_error"
    if failure_stage != "start":
        assert calls[0] == "end"
