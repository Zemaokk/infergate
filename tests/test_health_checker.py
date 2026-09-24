import asyncio

import httpx
import pytest

from infergate.health import HealthManager
from infergate.health_checker import HealthChecker
from infergate.router import Backend


@pytest.mark.asyncio
async def test_probe_round_runs_backends_concurrently_and_records_status() -> None:
    started: set[str] = set()
    both_started = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.add(request.url.host)
        if len(started) == 2:
            both_started.set()
        await both_started.wait()
        status = 200 if request.url.host == "backend-a" else 503
        return httpx.Response(status)

    health = HealthManager(["a", "b"])
    backends = [Backend("a", "http://backend-a"), Backend("b", "http://backend-b")]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        checker = HealthChecker(backends, health, client)
        await asyncio.wait_for(checker.run_round(), timeout=1.0)

    assert started == {"backend-a", "backend-b"}
    assert health.is_healthy("a")
    assert not health.is_healthy("b")


@pytest.mark.asyncio
async def test_transport_failure_marks_backend_unhealthy() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("backend unavailable")

    health = HealthManager(["a"])
    health.record_probe("a", True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        checker = HealthChecker([Backend("a", "http://backend-a")], health, client)
        await checker.run_round()

    assert not health.is_healthy("a")


@pytest.mark.asyncio
async def test_probe_has_overall_deadline() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return httpx.Response(200)

    health = HealthManager(["a"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        checker = HealthChecker(
            [Backend("a", "http://backend-a")],
            health,
            client,
            deadline_seconds=0.01,
        )
        await asyncio.wait_for(checker.run_round(), timeout=1.0)

    assert not health.is_healthy("a")


@pytest.mark.asyncio
async def test_cancelled_probe_does_not_record_a_failure() -> None:
    started = asyncio.Event()

    async def handler(_request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(10)
        return httpx.Response(200)

    health = HealthManager(["a"])
    health.record_probe("a", True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        checker = HealthChecker([Backend("a", "http://backend-a")], health, client)
        probe_task = asyncio.create_task(checker.run_round())
        await started.wait()
        probe_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await probe_task

    assert health.is_healthy("a")


@pytest.mark.asyncio
async def test_next_round_waits_until_previous_round_finishes() -> None:
    active_probes = 0
    max_active_probes = 0
    completed_rounds = 0
    two_rounds_done = asyncio.Event()

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal active_probes, max_active_probes, completed_rounds
        active_probes += 1
        max_active_probes = max(max_active_probes, active_probes)
        await asyncio.sleep(0.02)
        active_probes -= 1
        completed_rounds += 1
        if completed_rounds == 2:
            two_rounds_done.set()
        return httpx.Response(200)

    health = HealthManager(["a"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        checker = HealthChecker(
            [Backend("a", "http://backend-a")],
            health,
            client,
            interval_seconds=0.01,
        )
        task = asyncio.create_task(checker.run_forever())
        try:
            await asyncio.wait_for(two_rounds_done.wait(), timeout=1.0)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert completed_rounds == 2
    assert max_active_probes == 1
