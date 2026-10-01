import asyncio

import httpx
import pytest
from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client.parser import text_string_to_metric_families

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.metrics import GatewayMetrics
from infergate.observability import RequestObservation, RequestObservationMiddleware
from infergate.router import RoundRobinRouter
from infergate.token_bucket import TokenBucketLimiter


def test_histogram_aggregates_known_durations_and_registry_is_independent():
    metrics = GatewayMetrics(ConcurrencyLimiter(1))
    separate = GatewayMetrics(ConcurrencyLimiter(1))
    for duration in (0.5, 2.0):
        observation = RequestObservation(10.0)
        observation.status_code = 200
        observation.make_result("completed")
        observation.response_complete = True
        if observation.finish(10.0 + duration):
            metrics.record_request(observation)
        if observation.finish(99.0):
            metrics.record_request(observation)
    labels = {"route": "/v1/chat/completions", "outcome": "completed"}
    assert metrics.registry.get_sample_value(
        "infergate_request_duration_seconds_count", labels
    ) == 2
    assert metrics.registry.get_sample_value(
        "infergate_request_duration_seconds_sum", labels
    ) == 2.5
    assert metrics.registry.get_sample_value(
        "infergate_request_duration_seconds_bucket", {**labels, "le": "1.0"}
    ) == 1
    assert separate.registry.get_sample_value(
        "infergate_request_duration_seconds_count", labels
    ) is None


def test_unfinished_observation_is_not_counted():
    metrics = GatewayMetrics(ConcurrencyLimiter(1))
    metrics.record_request(RequestObservation(10.0))
    samples = [sample for family in metrics.registry.collect() for sample in family.samples]
    assert [(s.name, s.value) for s in samples] == [("infergate_active_requests", 0)]


@pytest.mark.parametrize(
    "first_byte, outcome",
    [(None, "cancelled"), (0.0, "completed"), (0.5, "completed"), (0.5, "stream_error")],
)
def test_first_byte_export_omits_missing_samples_but_preserves_zero_and_failure(
    first_byte, outcome
):
    metrics = GatewayMetrics(ConcurrencyLimiter(1))
    observation = RequestObservation(10.0)
    if first_byte is not None:
        observation.record_first_byte(10.0 + first_byte)
    if outcome == "completed":
        observation.make_result(outcome)
        observation.response_complete = True
    else:
        observation.record_failure(outcome)
    observation.finish(12.0)
    metrics.record_request(observation)
    labels = {"route": "/v1/chat/completions", "outcome": outcome}
    count = metrics.registry.get_sample_value(
        "infergate_request_first_byte_seconds_count", labels
    )
    total = metrics.registry.get_sample_value(
        "infergate_request_first_byte_seconds_sum", labels
    )
    assert count == (None if first_byte is None else 1)
    assert total == first_byte


@pytest.mark.asyncio
async def test_metrics_endpoint_is_parseable_excluded_and_app_specific():
    def unexpected_call(request):
        raise AssertionError("No backend should be contacted")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected_call)) as backend:
        def new_app():
            return create_app(
                RoundRobinRouter({}), BackendClient(backend),
                TokenBucketLimiter(2, 1), ConcurrencyLimiter(1),
            )

        first, second = new_app(), new_app()
        assert first.state.metrics.registry is not second.state.metrics.registry
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=first), base_url="http://gateway"
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                headers={"X-InferGate-Key": "secret-key-sentinel"},
                json={"model": "arbitrary-model-sentinel", "messages": [
                    {"role": "user", "content": "private-prompt-sentinel"}
                ]},
            )
            assert response.status_code == 503
            first_scrape = await client.get("/metrics")
            second_scrape = await client.get("/metrics")
        assert first_scrape.status_code == 200
        assert "infergate_backend_healthy" not in first_scrape.text
        assert first_scrape.headers["content-type"] == CONTENT_TYPE_LATEST
        assert first_scrape.text == second_scrape.text
        samples = [s for f in text_string_to_metric_families(first_scrape.text) for s in f.samples]
        requests = [s for s in samples if s.name == "infergate_requests_total"]
        assert len(requests) == 1
        assert requests[0].value == 1
        assert requests[0].labels == {
            "route": "/v1/chat/completions", "status": "503",
            "outcome": "rejected", "reason": "no_backend_available",
        }
        for private_value in (
            "secret-key-sentinel", "arbitrary-model-sentinel", "private-prompt-sentinel"
        ):
            assert private_value not in first_scrape.text
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=second), base_url="http://gateway"
        ) as client:
            untouched = await client.get("/metrics")
        samples = [s for f in text_string_to_metric_families(untouched.text) for s in f.samples]
        assert [(s.name, s.value) for s in samples] == [("infergate_active_requests", 0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome, status", [("stream_error", 200), ("cancelled", None)])
async def test_failure_records_once_with_actual_status(outcome, status):
    metrics = GatewayMetrics(ConcurrencyLimiter(1))
    scope = {"type": "http", "method": "POST", "path": "/v1/chat/completions"}
    error = (
        RuntimeError("stream failed")
        if outcome == "stream_error" else asyncio.CancelledError()
    )

    async def app(scope, receive, send):
        if status is not None:
            await send({"type": "http.response.start", "status": status, "headers": []})
        scope["state"]["observation"].record_failure(outcome)
        raise error

    async def receive():
        raise AssertionError("Unexpected receive")

    async def send(message):
        pass

    with pytest.raises(type(error)) as caught:
        await RequestObservationMiddleware(
            app, record_request_metrics=metrics.record_request
        )(scope, receive, send)
    assert caught.value is error
    assert metrics.registry.get_sample_value("infergate_requests_total", {
        "route": "/v1/chat/completions", "status": str(status) if status is not None else "none",
        "outcome": outcome, "reason": "none",
    }) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
async def test_metrics_callback_failure_does_not_change_business_result(failure, caplog):
    scope = {"type": "http", "method": "POST", "path": "/v1/chat/completions"}
    calls = []
    error = failure("original error") if failure is not None else None

    def broken_metrics(observation):
        calls.append(observation)
        raise ValueError("metric failure")

    async def app(scope, receive, send):
        if error is not None:
            raise error
        scope["state"]["observation"].make_result("completed")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        raise AssertionError("Unexpected receive")

    async def send(message):
        pass

    middleware = RequestObservationMiddleware(app, record_request_metrics=broken_metrics)
    if error is None:
        await middleware(scope, receive, send)
    else:
        with pytest.raises(failure) as caught:
            await middleware(scope, receive, send)
        assert caught.value is error
    assert len(calls) == 1
    assert calls[0].is_finished is True
    expected_outcome = "completed"
    if failure is asyncio.CancelledError:
        expected_outcome = "cancelled"
    elif error is not None:
        expected_outcome = "internal_error"
    assert calls[0].outcome == expected_outcome
    assert "Failed to record request metrics" in caplog.text


def test_attempt_samples_keep_fallback_results_durations_and_single_submission():
    metrics = GatewayMetrics(ConcurrencyLimiter(1))
    separate = GatewayMetrics(ConcurrencyLimiter(1))
    observation = RequestObservation(0.0)
    a = observation.start_attempt("a", 0.0)
    b = observation.start_attempt("b", 0.3)
    a.finish("transport_error", 0.2)
    b.finish("completed", 1.1)
    metrics.record_request(observation)
    a_labels = {"backend": "a", "outcome": "transport_error"}
    b_labels = {"backend": "b", "outcome": "completed"}
    assert metrics.registry.get_sample_value("infergate_backend_attempts_total", a_labels) is None
    observation.make_result("completed")
    observation.response_complete = True
    if observation.finish(1.2):
        metrics.record_request(observation)
    if observation.finish(2.0):
        metrics.record_request(observation)
    for labels, duration in [(a_labels, 0.2), (b_labels, 0.8)]:
        assert metrics.registry.get_sample_value("infergate_backend_attempts_total", labels) == 1
        assert metrics.registry.get_sample_value(
            "infergate_backend_attempt_duration_seconds_count", labels
        ) == 1
        assert metrics.registry.get_sample_value(
            "infergate_backend_attempt_duration_seconds_sum", labels
        ) == pytest.approx(duration)
        assert separate.registry.get_sample_value("infergate_backend_attempts_total", labels) is None
    assert metrics.registry.get_sample_value(
        "infergate_requests_total",
        {"route": "/v1/chat/completions", "status": "none", "outcome": "completed", "reason": "none"},
    ) == 1


def test_attempt_export_keeps_zero_duration_and_skips_unfinished_attempt():
    metrics = GatewayMetrics(ConcurrencyLimiter(1))
    observation = RequestObservation(0.0)
    completed = observation.start_attempt("a", 0.0)
    observation.start_attempt("b", 0.0)
    completed.finish("transport_error", 0.0)
    observation.record_failure("internal_error")
    observation.finish(1.0)
    metrics.record_request(observation)
    labels = {"backend": "a", "outcome": "transport_error"}
    assert metrics.registry.get_sample_value("infergate_backend_attempts_total", labels) == 1
    assert metrics.registry.get_sample_value(
        "infergate_backend_attempt_duration_seconds_sum", labels
    ) == 0.0
    samples = [s for f in metrics.registry.collect() for s in f.samples]
    assert not any(s.labels.get("backend") == "b" for s in samples)
