import asyncio
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.health import HealthManager
from infergate.health_checker import HealthChecker
from infergate.router import Backend, RoundRobinRouter

BACKEND_TIMEOUT = httpx.Timeout(connect=5.0, pool=5.0, write=30.0, read=30.0)
HEALTH_PROBE_DEADLINE = 2.0
HEALTH_PROBE_INTERVAL = 5.0


def create_runtime_app(
    *,
    backend_transport: httpx.AsyncBaseTransport | None = None,
    probe_transport: httpx.AsyncBaseTransport | None = None,
    probe_deadline_seconds: float = HEALTH_PROBE_DEADLINE,
    probe_interval_seconds: float = HEALTH_PROBE_INTERVAL,
) -> FastAPI:
    backend_http_client = httpx.AsyncClient(
        timeout=BACKEND_TIMEOUT, trust_env=False, transport=backend_transport
    )
    probe_http_client = httpx.AsyncClient(
        timeout=None, trust_env=False, transport=probe_transport
    )

    routes = {
        "mock-model": [
            Backend(id="backend-a", base_url="http://127.0.0.1:8001"),
            Backend(id="backend-b", base_url="http://127.0.0.1:8002"),
        ]
    }

    # 根据 backend.id 对 backend 进行去重
    backends = list(
        {backend.id: backend for group in routes.values() for backend in group}.values()
    )
    health_manager = HealthManager([backend.id for backend in backends])
    health_checker = HealthChecker(
        backends,
        health_manager,
        probe_http_client,
        deadline_seconds=probe_deadline_seconds,
        interval_seconds=probe_interval_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with backend_http_client, probe_http_client:
            await health_checker.run_round()
            probe_task = asyncio.create_task(health_checker.run_forever())
            try:
                yield
            finally:
                probe_task.cancel()
                with suppress(asyncio.CancelledError):
                    await probe_task

    router = RoundRobinRouter(routes=routes, health_manager=health_manager)

    backend_client = BackendClient(backend_http_client)

    return create_app(router=router, backend_client=backend_client, lifespan=lifespan)


app = create_runtime_app()
