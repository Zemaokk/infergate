from dataclasses import dataclass

from infergate.health import HealthManager


@dataclass(frozen=True)
class Backend:
    id: str
    base_url: str


class NoBackendAvailableError(Exception):
    pass


class RoundRobinRouter:
    def __init__(
        self,
        routes: dict[str, list[Backend]],
        health_manager: HealthManager | None = None,
    ) -> None:
        self.routes = routes
        self.cursors = {model: 0 for model in routes}  # representing next choice
        self.health_manager = health_manager

    def select(
        self,
        model: str,
        excluded_backend_ids: set[str] | None = None,
    ) -> Backend:
        if model not in self.routes or not self.routes[model]:
            raise NoBackendAvailableError

        unavai_backend_ids = set()
        if excluded_backend_ids:
            unavai_backend_ids.update(excluded_backend_ids)
        if self.health_manager:
            unavai_backend_ids.update(
                backend.id
                for backend in self.routes[model]
                if not self.health_manager.is_healthy(backend_id=backend.id)
            )

        index = self.cursors[model]

        # construct index list:
        index_list = []
        for i in range(len(self.routes[model])):
            index_list.append((index + i) % len(self.routes[model]))

        for i in index_list:
            if self.routes[model][i].id not in unavai_backend_ids:
                # update index
                self.cursors[model] = (i + 1) % len(self.routes[model])
                return self.routes[model][i]

        raise NoBackendAvailableError
