import asyncio
from collections.abc import Sequence

import httpx

from infergate.health import HealthManager
from infergate.router import Backend


class HealthChecker:
    def __init__(
        self,
        backends: Sequence[Backend],
        health_manager: HealthManager,
        client: httpx.AsyncClient,
        *,
        deadline_seconds: float = 2.0,
        interval_seconds: float = 5.0,
    ) -> None:
        self.backends = backends
        self.health_manager = health_manager
        self.client = client
        self.deadline_seconds = deadline_seconds
        self.interval_seconds = interval_seconds

    async def probe(self, backend: Backend) -> None:
        url = f"{backend.base_url.rstrip('/')}/health"
        try:
            async with asyncio.timeout(self.deadline_seconds):
                # 使用 stream，拿到请求头后立刻返回
                async with self.client.stream("GET", url) as response:
                    healthy = response.status_code == 200
        except (httpx.TransportError, TimeoutError):
            healthy = False

        self.health_manager.record_probe(backend.id, healthy)

    async def run_round(self) -> None:
        async with asyncio.TaskGroup() as tg:
            for backend in self.backends:
                tg.create_task(self.probe(backend))

    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            await self.run_round()
