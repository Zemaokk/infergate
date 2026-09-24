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

    def select(self, model: str) -> Backend:
        if model not in self.routes or not self.routes[model]:
            raise NoBackendAvailableError

        # construct index list:
        index = self.cursors[model]
        index_list = []
        for i in range(len(self.routes[model])):
            index_list.append((index + i) % len(self.routes[model]))

        if self.health_manager is None:
            self.cursors[model] = (index + 1) % len(self.routes[model])
            return self.routes[model][index]

        for i in index_list:
            if self.health_manager.is_healthy(self.routes[model][i].id):
                # update index
                self.cursors[model] = (i + 1) % len(self.routes[model])
                return self.routes[model][i]

        raise NoBackendAvailableError
