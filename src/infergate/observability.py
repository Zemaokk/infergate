import logging
import time
from collections.abc import Callable

import anyio
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class BackendAttemptObservation:
    def __init__(self, backend_id: str, started_at: float):
        self.backend_id = backend_id
        self.started_at = started_at
        self.outcome = None
        self.total_time = None
        self.first_byte_sec = None

    @property
    def is_finished(self) -> bool:
        return self.total_time is not None

    def finish(self, outcome: str, now: float):
        if self.is_finished:
            return False

        self.outcome = outcome
        self.total_time = now - self.started_at
        return True

    def record_first_byte(self, now: float) -> None:
        if self.is_finished or self.first_byte_sec is not None:
            return
        self.first_byte_sec = now - self.started_at


class RequestObservation:
    def __init__(self, started_at: float):
        self.started_at = started_at
        self.backend_attempts = []
        self.first_byte_sec = None
        self.outcome = None
        self.total_time: float | None = None
        self.pending_outcome: str | None = None
        self.pending_reason: str | None = None
        self.status_code: int | None = None
        # 最后一块 body 是否已成功交给下一层 ASGI send。
        # 不代表客户端已收齐，也不代表下游清理完成或观测记录已定稿。
        self.response_complete = False
        # 实际执行失败优先于 endpoint 的候选结果；清理错误单独保留。
        self.failure_outcome: str | None = None
        self.cleanup_failed = False
        self.reason: str | None = None

    # 表示该 request 是否完成（定稿）
    @property
    def is_finished(self) -> bool:
        return self.total_time is not None

    # 表示尝试连接后端的次数
    @property
    def attempts(self) -> int:
        return len(self.backend_attempts)

    def start_attempt(
        self, backend_id: str, started_at: float
    ) -> BackendAttemptObservation | None:
        if self.is_finished:
            return None

        backend_attempt_observation = BackendAttemptObservation(backend_id, started_at)
        self.backend_attempts.append(backend_attempt_observation)
        return backend_attempt_observation

    def record_first_byte(self, first_byte_out: float):
        if self.is_finished or self.first_byte_sec is not None:
            return

        self.first_byte_sec = first_byte_out - self.started_at

    def finish(self, now: float) -> bool:
        if self.is_finished:
            return False

        # 执行失败优先；无失败时，body 发完才采用候选结果。
        # 缺失候选或 body 未完成时，保守记录 internal_error。
        outcome = self.failure_outcome
        if outcome is None:
            if self.response_complete:
                outcome = self.pending_outcome or "internal_error"
            else:
                outcome = "internal_error"
        self.outcome = outcome
        self.reason = self.pending_reason if outcome == self.pending_outcome else None
        self.total_time = now - self.started_at
        return True

    def make_result(self, outcome: str, reason: str | None = None):
        if self.is_finished:
            return

        self.pending_outcome = outcome
        self.pending_reason = reason

    def record_failure(self, outcome: str) -> None:
        # 保留先发生的主要失败，避免后续清理异常覆盖取消或读取失败。
        if not self.is_finished and self.failure_outcome is None:
            self.failure_outcome = outcome


class RequestObservationMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        record_request_metrics: Callable[[RequestObservation], None] | None = None,
    ):
        self.app = app
        self.record_request_metrics = record_request_metrics

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
            # 先发送再记录；若发送抛异常或被取消，不误记为成功。
            try:
                await send(message)
            except anyio.get_cancelled_exc_class():
                observation.record_failure("cancelled")
                raise
            except OSError:
                # ASGI 用发送端 OSError 表示连接已关闭。
                observation.record_failure("cancelled")
                raise
            except Exception:
                observation.record_failure("internal_error")
                raise
            if message["type"] == "http.response.start":
                observation.status_code = message["status"]
            elif message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                # body 发完后仍可能执行清理，不能在这里调用 finish()。
                observation.response_complete = True

        async def observed_receive() -> Message:
            message = await receive()
            if (
                message["type"] == "http.disconnect"
                and not observation.response_complete
            ):
                observation.record_failure("cancelled")
            return message

        try:
            await self.app(scope, observed_receive, observed_send)
        except anyio.get_cancelled_exc_class():
            observation.record_failure("cancelled")
            raise
        except BaseException:
            observation.record_failure("internal_error")
            raise
        finally:
            # self.app 已退出：响应发送及其 finally 清理已经结束（可能失败）。
            # 对象根据已有状态定稿，middleware 只决定何时结束和提交。
            if (
                observation.finish(time.monotonic())
                and self.record_request_metrics is not None
            ):
                try:
                    self.record_request_metrics(observation)
                except Exception:  # noqa: BLE001
                    # 此处有意隔离指标回调的普通异常，不替换业务结果或原始异常。
                    logger.warning("Failed to record request metrics")
