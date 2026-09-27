import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestObservation:
    def __init__(self, started_at: float):
        self.started_at = started_at
        self.attempt = 0  # 记录尝试连接backend次数
        self.first_byte_sec = None
        self.outcome = None
        self.total_time = None
        self.is_finish = False
        self.pending_outcome: str | None = None
        self.pending_reason: str | None = None
        self.status_code: int | None = None
        self.response_complete = False

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

    def make_result(self, outcome: str, reason: str | None = None):
        if self.is_finish:
            return
        self.pending_outcome = outcome
        self.pending_reason = reason


class RequestObservationMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"] == "/v1/chat/completions"
        ):
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        observation = RequestObservation(started_at=time.monotonic())
        state["observation"] = observation

        async def observed_send(message: Message) -> None:
            await send(message)
            # Record only events successfully accepted by the next ASGI layer.
            if message["type"] == "http.response.start":
                observation.status_code = message["status"]
            elif message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                observation.response_complete = True

        await self.app(scope, receive, observed_send)
