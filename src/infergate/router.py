from dataclasses import dataclass


@dataclass(frozen=True)
class Backend:
    id: str
    base_url: str


class NoBackendAvailableError(Exception):
    pass


class RoundRobinRouter:
    def __init__(self, routes: dict[str, list[Backend]]) -> None:
        self.routes = routes
        self.cursors = {model: 0 for model in routes}

    def select(self, model: str) -> Backend:
        if model not in self.routes or not self.routes[model]:
            raise NoBackendAvailableError

        index = self.cursors[model]
        self.cursors[model] = (self.cursors[model] + 1) % len(self.routes[model])
        return self.routes[model][index]
