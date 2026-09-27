import asyncio

import httpx
import pytest
from prometheus_client.parser import text_string_to_metric_families

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.metrics import GatewayMetrics
from infergate.router import Backend, RoundRobinRouter
from infergate.token_bucket import TokenBucketLimiter


def test_gauge_reads_limiter_changes_and_is_isolated():
    limiter = ConcurrencyLimiter(2)
    metrics = GatewayMetrics(limiter)
    other = GatewayMetrics(ConcurrencyLimiter(2))

    def current():
        return metrics.registry.get_sample_value("infergate_active_requests")

    assert current() == 0
    assert limiter.try_acquire()
    assert current() == 1
    assert limiter.try_acquire()
    assert current() == 2
    assert not limiter.try_acquire()
    assert current() == 2
    limiter.release()
    assert current() == 1
    limiter.release()
    assert current() == 0
    assert other.registry.get_sample_value("infergate_active_requests") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["normal", "cancelled", "read_error"])
async def test_scrape_observes_live_stream_and_returns_to_zero(ending):
    blocked = asyncio.Event()
    release = asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: hello\n\n"
            blocked.set()
            await release.wait()
            if ending == "read_error":
                raise httpx.ReadError("stream interrupted")

    def handler(request):
        return httpx.Response(200, stream=Stream())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as backend:
        app = create_app(
            RoundRobinRouter({"test": [Backend("a", "http://a")]}),
            BackendClient(backend), TokenBucketLimiter(2, 1), ConcurrencyLimiter(1),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            async def scrape():
                response = await client.get("/metrics")
                assert response.status_code == 200
                return next(
                    s.value for f in text_string_to_metric_families(response.text)
                    for s in f.samples if s.name == "infergate_active_requests"
                )

            assert await scrape() == 0
            task = asyncio.create_task(client.post(
                "/v1/chat/completions", headers={"X-InferGate-Key": "key"},
                json={"model": "test", "messages": [{"role": "user", "content": "hi"}],
                      "stream": True},
            ))
            try:
                await asyncio.wait_for(blocked.wait(), timeout=1)
                assert await scrape() == 1
                if ending == "cancelled":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    release.set()
                    if ending == "read_error":
                        with pytest.raises(httpx.ReadError):
                            await task
                    else:
                        assert (await task).status_code == 200
                assert await scrape() == 0
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
