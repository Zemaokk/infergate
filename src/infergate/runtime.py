from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from infergate.app import create_app
from infergate.backend_client import BackendClient
from infergate.router import Backend, RoundRobinRouter

BACKEND_TIMEOUT = httpx.Timeout(connect=5.0, pool=5.0, write=30.0, read=30.0)


def create_runtime_app() -> FastAPI:
    backend_http_client = httpx.AsyncClient(timeout=BACKEND_TIMEOUT, trust_env=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with backend_http_client:
            yield

    router = RoundRobinRouter(
        {
            "mock-model": [
                Backend(
                    id="backend-a",
                    base_url="http://127.0.0.1:8001",
                ),
                Backend(
                    id="backend-b",
                    base_url="http://127.0.0.1:8002",
                ),
            ]
        }
    )

    backend_client = BackendClient(backend_http_client)

    return create_app(router=router, backend_client=backend_client, lifespan=lifespan)


app = create_runtime_app()
