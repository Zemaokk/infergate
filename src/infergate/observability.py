import time

from starlette.types import ASGIApp, Receive, Scope, Send


class RequestObservation:
    def __init__(self, started_at: float):
        self.started_at = started_at
        self.attempt = 0
        self.first_byte_sec = None
        self.outcome = None
        self.total_time = None
        self.is_finish = False

    def start_attempt(self):
        if self.is_finish:
            return
        self.attempt += 1

    def record_first_byte(self, first_byte_out: float):
        if self.is_finish or self.first_byte_sec is not None:
            return
        self.first_byte_sec = first_byte_out - self.started_at

    def finish(self, outcome: str, finish_time: float) -> bool:
        if self.is_finish:
            return False
        self.outcome = outcome
        self.is_finish = True
        self.total_time = finish_time - self.started_at
        return True


class RequestObservationMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"] == "/v1/chat/completions"
        ):
            state = scope.setdefault("state", {})
            state["observation"] = RequestObservation(started_at=time.monotonic())

        await self.app(scope, receive, send)
