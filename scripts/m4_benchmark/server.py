"""Loopback-only benchmark services, assembled without changing production defaults."""

import argparse
import asyncio
import socket
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.health import HealthManager
from infergate.health_checker import HealthChecker
from infergate.mock_backend import app as original_mock
from infergate.router import Backend, RoundRobinRouter
from infergate.runtime import BACKEND_TIMEOUT, HEALTH_PROBE_DEADLINE, HEALTH_PROBE_INTERVAL
from infergate.token_bucket import TokenBucketLimiter
from infergate.tracing import shutdown_trace_provider


class DelayedMock:
    """Pure ASGI delay; /health and diagnostics do not enter business counters."""

    def __init__(self, delay: float):
        self.delay = delay
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.app = FastAPI()
        self.app.include_router(original_mock.router)

        @self.app.get("/bench/state")
        async def state():
            return {"calls": self.calls, "active": self.active,
                    "max_active": self.max_active, "delay_seconds": self.delay}

    async def __call__(self, scope, receive, send):
        business = (scope["type"] == "http" and scope["method"] == "POST"
                    and scope["path"] == "/v1/chat/completions")
        if not business:
            return await self.app(scope, receive, send)
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            await self.app(scope, receive, send)
        finally:
            self.active -= 1


class AuditedLimiter(TokenBucketLimiter):
    """Record actual quota decision times only in quota/order experiments."""

    def __init__(self, capacity, rate):
        super().__init__(capacity, rate)
        self.events = []

    def allow(self, key, price=1):
        allowed = super().allow(key, price)
        bucket = self.buckets[key]
        self.events.append({"key_alias": key.removeprefix("m44-benchmark-"),
                            "checked_at": bucket.last_update, "allowed": allowed,
                            "tokens_after": bucket.tokens})
        return allowed


def gateway(backend_url: str, limit: int, capacity: float, rate: float):
    backend = Backend(id="backend-a", base_url=backend_url)
    health = HealthManager([backend.id])
    backend_http = httpx.AsyncClient(timeout=BACKEND_TIMEOUT, trust_env=False)
    probe_http = httpx.AsyncClient(timeout=None, trust_env=False)
    checker = HealthChecker([backend], health, probe_http,
                            deadline_seconds=HEALTH_PROBE_DEADLINE,
                            interval_seconds=HEALTH_PROBE_INTERVAL)
    limiter = ConcurrencyLimiter(limit)
    quota = (AuditedLimiter(capacity, rate) if capacity == 2
             else TokenBucketLimiter(capacity, rate))

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with backend_http, probe_http:
                await checker.run_round()
                task = asyncio.create_task(checker.run_forever())
                try:
                    yield
                finally:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
        finally:
            await shutdown_trace_provider(app.state.tracer_provider)

    app = create_app(
        router=RoundRobinRouter({"mock-model": [backend]}, health),
        backend_client=BackendClient(backend_http),
        key_limiter=quota,
        concurrency_limiter=limiter,
        lifespan=lifespan,
    )

    @app.get("/bench/state")
    async def state():
        return {"active": limit - limiter.available, "limit": limit,
                "capacity": capacity, "rate": rate,
                "healthy": health.is_healthy(backend.id),
                "quota_events": getattr(quota, "events", [])}

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("mock", "gateway"))
    parser.add_argument("--fd", type=int, required=True)
    parser.add_argument("--backend-url")
    parser.add_argument("--limit", type=int, default=32)
    parser.add_argument("--capacity", type=float, default=100_000)
    parser.add_argument("--rate", type=float, default=100_000)
    parser.add_argument("--delay", type=float, default=0)
    args = parser.parse_args()
    app = (DelayedMock(args.delay) if args.role == "mock"
           else gateway(args.backend_url, args.limit, args.capacity, args.rate))
    config = uvicorn.Config(
        app, log_config=str(Path(__file__).resolve().parents[2] / "configs/logging.json"),
        access_log=True, workers=1, timeout_graceful_shutdown=5,
    )
    # Parent reserves a loopback port and hands its socket to this child; no port race.
    with socket.socket(fileno=args.fd) as listener:
        asyncio.run(uvicorn.Server(config).serve(sockets=[listener]))


if __name__ == "__main__":
    main()
