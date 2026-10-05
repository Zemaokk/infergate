import httpx
import pytest
from opentelemetry.context import Context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import get_current_span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.observability import BackendAttemptObservation
from infergate.router import Backend, RoundRobinRouter
from infergate.token_bucket import TokenBucketLimiter


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("flags", [None, "01", "00"])
async def test_each_backend_receives_its_own_attempt_context(stream, fallback, flags):
    provider = TracerProvider(shutdown_on_exit=False)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    received = []
    observations = []
    upstream_trace_id = "123456789abcdef0123456789abcdef0"
    propagator = TraceContextTextMapPropagator()

    def handler(request):
        assert "X-InferGate-Key" not in request.headers
        assert "baggage" not in request.headers
        parent = get_current_span(propagator.extract(
            dict(request.headers), context=Context()
        )).get_span_context()
        assert parent.is_valid and parent.is_remote
        received.append((request.url.host, parent, dict(request.headers)))
        if fallback and request.url.host == "a":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, content=b"data: hello\n\n" if stream else b"ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as backend:
        app = create_app(
            RoundRobinRouter({"test": [Backend("a", "http://a"), Backend("b", "http://b")]}),
            BackendClient(backend), TokenBucketLimiter(2, 1), ConcurrencyLimiter(1),
            tracer_provider=provider,
        )

        async def capture(scope, receive, send):
            await app(scope, receive, send)
            observations.append(scope["state"]["observation"])

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=capture), base_url="http://gateway"
            ) as client:
                headers = {"X-InferGate-Key": "private-key", "baggage": "secret=private"}
                if flags is not None:
                    headers["traceparent"] = f"00-{upstream_trace_id}-123456789abcdef0-{flags}"
                    headers["tracestate"] = "vendor=value"
                response = await client.post(
                    "/v1/chat/completions", headers=headers,
                    json={"model": "test", "messages": [{"role": "user", "content": "hi"}],
                          "stream": stream},
                )
            assert response.status_code == 200
            observation = observations[0]
            assert len(received) == observation.attempts == (2 if fallback else 1)
            for (backend_id, parent, headers), attempt in zip(
                received, observation.backend_attempts, strict=True
            ):
                assert backend_id == attempt.backend_id
                assert f"{parent.trace_id:032x}" == observation.trace_id
                assert f"{parent.span_id:016x}" == attempt.span_id
                assert attempt.span_id != observation.span_id
                if flags is not None:
                    assert f"{parent.trace_id:032x}" == upstream_trace_id
                    assert headers["tracestate"] == "vendor=value"
                    assert headers["traceparent"].endswith("-" + flags)
            assert len({parent.span_id for _, parent, _ in received}) == len(received)
            if flags == "00":
                # Context still propagates when the parent declines recording.
                assert exporter.get_finished_spans() == ()
            else:
                assert len(exporter.get_finished_spans()) == 1 + len(received)
        finally:
            provider.shutdown()


def test_trace_injection_failure_returns_empty_carrier_and_does_not_finish_attempt(monkeypatch):
    attempt = BackendAttemptObservation("a", 0.0)
    assert attempt.build_trace_headers() == {}
    attempt.span = object()

    def broken_inject(self, carrier, **kwargs):
        carrier["traceparent"] = "partial"
        raise ValueError("propagation failed")

    monkeypatch.setattr("infergate.observability.set_span_in_context", lambda *args: Context())
    monkeypatch.setattr(TraceContextTextMapPropagator, "inject", broken_inject)
    assert attempt.build_trace_headers() == {}
    assert not attempt.is_finished
