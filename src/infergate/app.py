from typing import Annotated, Literal

import anyio
import httpx
from fastapi import FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StrictBool, StrictStr
from starlette.types import Lifespan, Receive, Scope, Send

from infergate.api_errors import create_error_response
from infergate.backend_client import (
    BackendClient,
    BackendStreamResponse,
    BackendTransportError,
)
from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.observability import RequestObservation, RequestObservationMiddleware
from infergate.router import NoBackendAvailableError, RoundRobinRouter
from infergate.token_bucket import TokenBucketLimiter


class ChatMessage(BaseModel):
    model_config = {"extra": "allow"}

    role: Literal["developer", "system", "user", "assistant"]
    content: StrictStr


class ChatCompletionRequest(BaseModel):
    model_config = {"extra": "allow"}

    model: StrictStr
    messages: list[ChatMessage] = Field(min_length=1)
    stream: StrictBool = False


class LimitedStreamingResponse(StreamingResponse):
    """Own the downstream response and one already-acquired concurrency slot."""

    def __init__(
        self,
        response: BackendStreamResponse,
        limiter: ConcurrencyLimiter,
        headers: dict[str, str],
    ) -> None:
        super().__init__(
            content=response.aiter_bytes(),
            status_code=response.status_code,
            headers=headers,
        )
        self.downstream = response
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        observation = scope.get("state", {}).get("observation")
        try:
            await super().__call__(scope, receive, send)
        except BaseException as exc:
            # 在进入清理前保留主要失败；发送端错误已由 middleware 分类。
            if observation is not None:
                if isinstance(exc, anyio.get_cancelled_exc_class()):
                    observation.record_failure("cancelled")
                elif isinstance(exc, httpx.TransportError):
                    observation.record_failure("stream_error")
                else:
                    observation.record_failure("internal_error")
            raise
        finally:
            try:
                # Cleanup also runs when headers fail before body iteration starts.
                with anyio.CancelScope(shield=True):
                    await self.downstream.aclose()
            except BaseException:
                if observation is not None:
                    observation.cleanup_failed = True
                    observation.record_failure("internal_error")
                raise
            finally:
                self.limiter.release()


def create_app(
    router: RoundRobinRouter,
    backend_client: BackendClient,
    key_limiter: TokenBucketLimiter,
    concurrency_limiter: ConcurrencyLimiter,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(RequestObservationMiddleware)

    @app.exception_handler(RequestValidationError)
    async def request_valid_e_handler(
        _request: Request, exc: RequestValidationError
    ) -> Response:
        first_error = exc.errors()[0]

        if first_error["type"] == "json_invalid":
            param = None
        else:
            location = [str(part) for part in first_error["loc"] if part != "body"]
            param = ".".join(location) or None

        observation = getattr(_request.state, "observation", None)
        if observation is not None:
            observation.make_result("rejected", "invalid_request_body")
        return create_error_response(
            status_code=400,
            message="Invalid request body.",
            error_type="invalid_request_error",
            param=param,
        )

    @app.post("/v1/chat/completions")
    async def create_chat_completion(
        http_request: Request,
        request: ChatCompletionRequest,
        x_infergate_key: Annotated[str | None, Header()] = None,
    ) -> Response:

        observation: RequestObservation = http_request.state.observation

        # check key
        # key 合法性检验
        if x_infergate_key is None or not x_infergate_key.strip():
            observation.make_result("rejected", "invalid_infergate_key")
            return create_error_response(
                status_code=400,
                message="Invalid infergate key.",
                error_type="invalid_request_error",
                code="invalid_infergate_key",
                param="X-InferGate-Key",
            )
        # token-bucket 限制检验
        if not key_limiter.allow(key=x_infergate_key):
            observation.make_result("rejected", "rate_limit_exceeded")
            return create_error_response(
                status_code=429,
                message="Too many requests.",
                error_type="invalid_request_error",
                code="rate_limit_exceeded",
            )

        # check total concurrency limit
        if not concurrency_limiter.try_acquire():
            observation.make_result("rejected", "concurrency_limit_exceeded")
            return create_error_response(
                status_code=503,
                message="Exceed global concurrency limit.",
                error_type="gateway_error",
                code="concurrency_limit_exceeded",
            )

        # Endpoint owns the slot until a streaming response takes responsibility.
        handed_off = False
        opened_stream: BackendStreamResponse | None = None
        try:
            payload = request.model_dump(exclude_unset=True)
            model = request.model

            max_attempts = 2
            attempted_backend_ids = set()
            last_error = None
            last_backend = None

            for attempt in range(max_attempts):
                # 选择 backend，如果无可用，报503
                try:
                    backend = router.select(
                        model=model, excluded_backend_ids=attempted_backend_ids
                    )
                except NoBackendAvailableError:
                    if last_error is None:
                        observation.make_result("rejected", "no_backend_available")
                        return create_error_response(
                            status_code=503,
                            message="No backend is available for the requested model.",
                            error_type="gateway_error",
                            code="no_backend_available",
                        )
                    else:
                        observation.make_result(
                            "transport_error", "backend_transport_failure"
                        )
                        return create_error_response(
                            status_code=502,
                            headers={"X-InferGate-Backend": last_backend.id},
                            message="Cannot connect to backend.",
                            error_type="gateway_error",
                            code="backend_transport_failure",
                        )

                attempted_backend_ids.add(backend.id)
                last_backend = backend

                # 调用 backend_client 发送请求，连接失败报 502，这里只处理连接失败/超时
                observation.start_attempt()
                try:
                    if request.stream:
                        backend_response = await backend_client.open_stream(
                            backend=backend,
                            path="/v1/chat/completions",
                            payload=payload,
                        )
                        opened_stream = backend_response
                    else:
                        backend_response = await backend_client.forward(
                            backend=backend,
                            path="/v1/chat/completions",
                            payload=payload,
                        )
                except BackendTransportError as e:
                    last_error = e
                    if not e.retryable or attempt + 1 >= max_attempts:
                        observation.make_result(
                            "transport_error", "backend_transport_failure"
                        )
                        return create_error_response(
                            status_code=502,
                            headers={"X-InferGate-Backend": backend.id},
                            message="Cannot connect to backend.",
                            error_type="gateway_error",
                            code="backend_transport_failure",
                        )
                    continue  # retry
                break  # success

            # 构造请求之前，处理后端的其他错误，如果没有错误先标记为 completed
            if backend_response.status_code >= 400:
                observation.make_result("backend_http_error")
            else:
                observation.make_result("completed")

            # 构造请求头
            headers = {"X-InferGate-Backend": backend.id}
            if backend_response.content_type is not None:
                headers["Content-Type"] = backend_response.content_type

            if request.stream:
                r = LimitedStreamingResponse(
                    response=backend_response,
                    limiter=concurrency_limiter,
                    headers=headers,
                )
                # 移交资源所有权
                handed_off = True
            else:
                r = Response(
                    content=backend_response.body,
                    status_code=backend_response.status_code,
                    headers=headers,
                )

            return r

        except BaseException as exc:
            observation.record_failure(
                "cancelled"
                if isinstance(exc, anyio.get_cancelled_exc_class())
                else "internal_error"
            )
            raise
        # 如果没有移交资源所有权，释放 concurrency 名额
        finally:
            if not handed_off:
                try:
                    # If response construction fails, ownership was never handed off.
                    if opened_stream is not None:
                        with anyio.CancelScope(shield=True):
                            await opened_stream.aclose()
                except BaseException:
                    observation.cleanup_failed = True
                    observation.record_failure("internal_error")
                    raise
                finally:
                    concurrency_limiter.release()

    return app
