import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.health import HealthManager
from infergate.health_checker import HealthChecker
from infergate.router import Backend, RoundRobinRouter
from infergate.token_bucket import TokenBucketLimiter
from infergate.tracing import configure_trace_export, shutdown_trace_provider

logger = logging.getLogger(__name__)

BACKEND_TIMEOUT = httpx.Timeout(connect=5.0, pool=5.0, write=30.0, read=30.0)
HEALTH_PROBE_DEADLINE = 2.0
HEALTH_PROBE_INTERVAL = 5.0


def read_backend_url(env_name: str, default: str) -> str:
    backend_url = os.getenv(env_name, default).strip()
    if not backend_url:
        raise ValueError(f"{env_name} is invalid") from None
    try:
        url = httpx.URL(backend_url)
    except httpx.InvalidURL:
        raise ValueError(f"{env_name} is invalid") from None
    if (
        url.scheme not in ("http", "https")
        or not url.host
        or url.userinfo
        or url.query
        or url.fragment
        or url.path not in ("", "/")
    ):
        raise ValueError(f"{env_name} is invalid") from None
    return backend_url


def create_runtime_app(
    *,
    backend_transport: httpx.AsyncBaseTransport | None = None,
    probe_transport: httpx.AsyncBaseTransport | None = None,
    probe_deadline_seconds: float = HEALTH_PROBE_DEADLINE,
    probe_interval_seconds: float = HEALTH_PROBE_INTERVAL,
    otlp_traces_endpoint: str | None = None,
) -> FastAPI:
    trace_endpoint = (
        otlp_traces_endpoint
        if otlp_traces_endpoint is not None
        else os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
    ).strip()

    routes = {
        "mock-model": [
            Backend(
                id="backend-a",
                base_url=read_backend_url(
                    "INFERGATE_BACKEND_A_URL", "http://127.0.0.1:8001"
                ),
            ),
            Backend(
                id="backend-b",
                base_url=read_backend_url(
                    "INFERGATE_BACKEND_B_URL", "http://127.0.0.1:8002"
                ),
            ),
        ]
    }

    backend_http_client = httpx.AsyncClient(
        timeout=BACKEND_TIMEOUT, trust_env=False, transport=backend_transport
    )
    probe_http_client = httpx.AsyncClient(
        timeout=None, trust_env=False, transport=probe_transport
    )

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
        try:
            if trace_endpoint:
                try:
                    configure_trace_export(app.state.tracer_provider, trace_endpoint)
                except Exception:  # noqa: BLE001
                    # 导出初始化故障不阻止业务；不记录 endpoint 或异常文本。
                    try:
                        logger.warning("Failed to configure trace export")
                    except Exception:  # noqa: BLE001
                        pass
            async with backend_http_client, probe_http_client:
                await health_checker.run_round()
                probe_task = asyncio.create_task(health_checker.run_forever())
                try:
                    yield
                finally:
                    probe_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await probe_task
        finally:
            await shutdown_trace_provider(app.state.tracer_provider)

    router = RoundRobinRouter(routes=routes, health_manager=health_manager)

    backend_client = BackendClient(backend_http_client)

    key_limiter = TokenBucketLimiter(capacity=2, rate=1)

    concurrency_limiter = ConcurrencyLimiter(limit=2)

    return create_app(
        router=router,
        backend_client=backend_client,
        key_limiter=key_limiter,
        concurrency_limiter=concurrency_limiter,
        lifespan=lifespan,
    )


app = create_runtime_app()
