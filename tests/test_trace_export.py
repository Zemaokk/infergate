import asyncio
from threading import Event

import httpx
import pytest
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from infergate.runtime import create_runtime_app
from infergate.tracing import shutdown_trace_provider


@pytest.mark.asyncio
@pytest.mark.parametrize("export_fails", [False, True])
async def test_runtime_enables_background_export_and_shuts_it_down(monkeypatch, export_fails):
    batches = []
    closed = []
    options = []

    class Exporter(SpanExporter):
        def export(self, spans):
            batches.append(tuple(spans))
            return SpanExportResult.FAILURE if export_fails else SpanExportResult.SUCCESS

        def shutdown(self):
            closed.append(True)

    def factory(**kwargs):
        options.append(kwargs)
        return Exporter()

    monkeypatch.setattr("infergate.tracing.OTLPSpanExporter", factory)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"ok"))
    app = create_runtime_app(
        probe_transport=transport, backend_transport=transport,
        otlp_traces_endpoint="http://collector:4318/v1/traces",
    )
    # No exporter or worker is created at import/factory time.
    assert options == []
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway"
        ) as client:
            response = await client.post(
                "/v1/chat/completions", headers={"X-InferGate-Key": "test"},
                json={"model": "mock-model", "messages": [{"role": "user", "content": "hi"}]},
            )
            assert response.status_code == 200
            labels = {"route": "/v1/chat/completions", "status": "200",
                      "outcome": "completed", "reason": "none"}
            assert app.state.metrics.registry.get_sample_value("infergate_requests_total", labels) == 1
    assert options == [{"endpoint": "http://collector:4318/v1/traces", "timeout": 2.0}]
    spans = [span for batch in batches for span in batch]
    assert len(spans) == 2
    assert all(span.resource.attributes["service.name"] == "infergate" for span in spans)
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["", None])
async def test_export_is_opt_in_and_env_endpoint_is_read_at_factory(monkeypatch, endpoint):
    calls = []
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://collector:4318/v1/traces")
    monkeypatch.setattr("infergate.runtime.configure_trace_export", lambda *args: calls.append(args))
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    app = create_runtime_app(
        probe_transport=transport, backend_transport=transport, otlp_traces_endpoint=endpoint
    )
    async with app.router.lifespan_context(app):
        assert len(calls) == (0 if endpoint == "" else 1)
    if calls:
        assert calls[0][1] == "http://collector:4318/v1/traces"


@pytest.mark.asyncio
async def test_export_initialization_failure_does_not_prevent_runtime_startup(monkeypatch):
    def broken_configure(*args):
        raise ValueError("private endpoint details")

    monkeypatch.setattr("infergate.runtime.configure_trace_export", broken_configure)
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    app = create_runtime_app(
        probe_transport=transport, backend_transport=transport,
        otlp_traces_endpoint="http://collector:4318/v1/traces",
    )
    async with app.router.lifespan_context(app):
        assert app.state.tracer_provider is not None


@pytest.mark.asyncio
async def test_shutdown_wait_has_deadline_and_does_not_block_event_loop():
    entered = Event()
    release = Event()
    exited = Event()

    class SlowProvider:
        def shutdown(self):
            entered.set()
            release.wait(2)
            exited.set()

    try:
        shutdown = asyncio.create_task(shutdown_trace_provider(SlowProvider(), timeout_seconds=0.05))
        assert await asyncio.to_thread(entered.wait, 1)
        assert await asyncio.wait_for(shutdown, 1) is False
        assert not exited.is_set()
    finally:
        release.set()
        assert await asyncio.to_thread(exited.wait, 1)


@pytest.mark.asyncio
async def test_shutdown_failure_is_isolated():
    class BrokenProvider:
        def shutdown(self):
            raise ValueError("shutdown failed")

    assert await shutdown_trace_provider(BrokenProvider()) is False


@pytest.mark.asyncio
async def test_actual_otlp_exporter_encodes_spans_and_closes_http_transport(monkeypatch):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    sent = []
    closed = []

    class Response:
        status_code = 200
        reason = "OK"
        error = None

        def content(self):
            return b""

        def headers(self):
            return {}

    class Transport:
        def request(self, method, url, *, headers=None, timeout=None, data=None):
            sent.append((method, url, headers, timeout, data))
            return Response()

        def close(self):
            closed.append(True)

        def is_connection_error(self, error):
            return False

    monkeypatch.setattr(
        "infergate.tracing.OTLPSpanExporter",
        lambda **kwargs: OTLPSpanExporter(**kwargs, _transport=Transport()),
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"private-response"))
    app = create_runtime_app(
        probe_transport=transport, backend_transport=transport,
        otlp_traces_endpoint="http://collector:4318/v1/traces",
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway"
        ) as client:
            response = await client.post(
                "/v1/chat/completions", headers={"X-InferGate-Key": "private-key"},
                json={"model": "mock-model", "messages": [{"role": "user", "content": "private-prompt"}]},
            )
            assert response.status_code == 200
    spans = []
    for method, url, headers, timeout, data in sent:
        assert method == "POST"
        assert url == "http://collector:4318/v1/traces"
        assert {key.lower(): value for key, value in headers.items()}["content-type"] == "application/x-protobuf"
        assert 0 < timeout <= 2.0
        assert b"private-" not in data
        message = ExportTraceServiceRequest.FromString(data)
        spans.extend(span for resource in message.resource_spans
                     for scope in resource.scope_spans for span in scope.spans)
    assert len(spans) == 2
    request = next(span for span in spans if span.name == "POST /v1/chat/completions")
    attempt = next(span for span in spans if span.name == "backend_attempt")
    assert request.trace_id == attempt.trace_id
    assert attempt.parent_span_id == request.span_id
    assert closed == [True]
