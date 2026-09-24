class HealthManager:
    def __init__(self, backend_list: list[str]) -> None:
        self.health_state = {backend_id: False for backend_id in backend_list}

    def record_probe(self, backend_id: str, healthy: bool) -> None:
        self.health_state[backend_id] = healthy

    def is_healthy(self, backend_id: str) -> bool:
        if backend_id in self.health_state:
            return self.health_state[backend_id]
        else:
            return False
