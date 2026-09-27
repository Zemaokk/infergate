import httpx
import pytest
from prometheus_client.parser import text_string_to_metric_families

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.health import HealthManager
from infergate.health_checker import HealthChecker
from infergate.metrics import GatewayMetrics
from infergate.router import Backend, RoundRobinRouter
from infergate.token_bucket import TokenBucketLimiter


def test_health_metrics_are_deduplicated_read_live_and_isolated():
    health = HealthManager(["a", "b", "not-routed"])
    metrics = GatewayMetrics(ConcurrencyLimiter(1))
    metrics.track_backend_health(["a", "b", "a"], health)
    separate = GatewayMetrics(ConcurrencyLimiter(1))
    separate.track_backend_health(["a"], HealthManager(["a"]))

    def state(backend):
        return metrics.registry.get_sample_value("infergate_backend_healthy", {"backend": backend})

    assert state("a") == 0
    assert state("b") == 0
    health.record_probe("a", True)
    assert state("a") == 1
    assert state("b") == 0
    assert state("not-routed") is None
    assert separate.registry.get_sample_value("infergate_backend_healthy", {"backend": "a"}) == 0
    health.record_probe("a", False)
    health.record_probe("b", True)
    assert state("a") == 0
    assert state("b") == 1


@pytest.mark.asyncio
async def test_scrape_reflects_health_probes_and_matches_routing_without_extra_probes():
    probe_status = {"a": 200, "b": 503}
    probe_calls = []

    def handler(request):
        if request.url.path == "/health":
            probe_calls.append(request.url.host)
            return httpx.Response(probe_status[request.url.host])
        return httpx.Response(200, json={"backend": request.url.host})

    backends = [Backend("a", "http://a"), Backend("b", "http://b")]
    health = HealthManager(["a", "b"])
    router = RoundRobinRouter({"test": backends, "alias": [backends[0]]}, health)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as backend_client:
        checker = HealthChecker(backends, health, backend_client)
        app = create_app(
            router, BackendClient(backend_client), TokenBucketLimiter(10, 1),
            ConcurrencyLimiter(2),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            async def scrape():
                response = await client.get("/metrics")
                assert response.status_code == 200
                samples = [
                    s for f in text_string_to_metric_families(response.text)
                    for s in f.samples if s.name == "infergate_backend_healthy"
                ]
                assert len(samples) == 2
                return {s.labels["backend"]: s.value for s in samples}

            assert await scrape() == {"a": 0, "b": 0}
            assert probe_calls == []
            await checker.run_round()
            assert await scrape() == {"a": 1, "b": 0}
            assert len(probe_calls) == 2
            payload = {"model": "test", "messages": [{"role": "user", "content": "hi"}]}
            response = await client.post(
                "/v1/chat/completions", json=payload, headers={"X-InferGate-Key": "key"}
            )
            assert response.json()["backend"] == "a"
            probe_status.update(a=503, b=200)
            await checker.run_round()
            assert await scrape() == {"a": 0, "b": 1}
            assert len(probe_calls) == 4
            response = await client.post(
                "/v1/chat/completions", json=payload, headers={"X-InferGate-Key": "key"}
            )
            assert response.json()["backend"] == "b"
