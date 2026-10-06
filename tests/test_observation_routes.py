import asyncio
import json
import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.metrics import GatewayMetrics
from infergate.observability import RequestObservationMiddleware


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
async def test_overlapping_routes_match_observations_logs_metrics_and_spans(
    rejected, caplog
):
    """Exercise middleware finalization; this does not register API endpoints."""
    caplog.set_level(logging.INFO, logger="infergate.observability")
    routes = ("/v1/chat/completions", "/v1/responses")
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    metrics = GatewayMetrics(ConcurrencyLimiter(1))
    both_entered = asyncio.Event()
    observations = {}
    status = 400 if rejected else 200
    outcome = "rejected" if rejected else "completed"
    reason = "invalid_request_body" if rejected else None

    async def app(scope, receive, send):
        observation = scope["state"]["observation"]
        observations[scope["path"]] = observation
        if len(observations) == 2:
            both_entered.set()
        await both_entered.wait()
        assert observation.route == scope["path"]
        observation.make_result(outcome, reason)
        await send({"type": "http.response.start", "status": status})
        await send({"type": "http.response.body", "body": b"{}"})

    async def receive():
        raise AssertionError("Unexpected receive")

    async def send(message):
        pass

    middleware = RequestObservationMiddleware(
        app, metrics.record_request, provider.get_tracer("test")
    )
    try:
        await asyncio.wait_for(asyncio.gather(*(
            middleware(
                {"type": "http", "method": "POST", "path": route}, receive, send
            ) for route in routes
        )), timeout=1)
        assert observations[routes[0]] is not observations[routes[1]]
        records = [json.loads(record.getMessage()) for record in caplog.records
                   if record.name == "infergate.observability"
                   and record.levelno == logging.INFO]
        assert len(records) == 2
        assert {record["route"] for record in records} == set(routes)
        for record in records:
            assert record["status_code"] == status
            assert record["outcome"] == outcome
            assert record["reason"] == reason
            assert record["attempt_count"] == 0
            assert record["backend_attempts"] == []
            assert record["first_byte_sec"] is None
        for route in routes:
            labels = {"route": route, "status": str(status),
                      "outcome": outcome, "reason": reason or "none"}
            assert metrics.registry.get_sample_value(
                "infergate_requests_total", labels
            ) == 1
            assert metrics.registry.get_sample_value(
                "infergate_request_duration_seconds_count",
                {"route": route, "outcome": outcome},
            ) == 1
            assert observations[route].is_finished
        spans = exporter.get_finished_spans()
        assert len(spans) == 2
        spans_by_request = {
            span.attributes["infergate.request_id"]: span for span in spans
        }
        for record in records:
            span = spans_by_request[record["request_id"]]
            assert span.name == f"POST {record['route']}"
            assert span.attributes["http.route"] == record["route"]
    finally:
        provider.shutdown()
