from typing import Annotated, Literal

import anyio
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
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                # Cleanup also runs when headers fail before body iteration starts.
                with anyio.CancelScope(shield=True):
                    await self.downstream.aclose()
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

        return create_error_response(
            status_code=400,
            message="Invalid request body.",
            error_type="invalid_request_error",
            param=param,
        )

    @app.post("/v1/chat/completions")
    async def create_chat_completion(
        request: ChatCompletionRequest,
        x_infergate_key: Annotated[str | None, Header()] = None,
    ) -> Response:

        # check key
        if x_infergate_key is None or not x_infergate_key.strip():
            return create_error_response(
                status_code=400,
                message="Invalid infergate key.",
                error_type="invalid_request_error",
                code="invalid_infergate_key",
                param="X-InferGate-Key",
            )
        else:
            if not key_limiter.allow(key=x_infergate_key):
                return create_error_response(
                    status_code=429,
                    message="Too many requests.",
                    error_type="invalid_request_error",
                    code="rate_limit_exceeded",
                )

        # check total concurrency limit
        if not concurrency_limiter.try_acquire():
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

            # 选择 backend，如果无可用，报503
            try:
                backend = router.select(model=model)
            except NoBackendAvailableError:
                return create_error_response(
                    status_code=503,
                    message="No backend is available for the requested model.",
                    error_type="gateway_error",
                    code="no_backend_available",
                )

            # 调用 backend_client 发送请求，连接失败报 502
            try:
                if request.stream:
                    backend_response = await backend_client.open_stream(
                        backend=backend, path="/v1/chat/completions", payload=payload
                    )
                    opened_stream = backend_response
                else:
                    backend_response = await backend_client.forward(
                        backend=backend, path="/v1/chat/completions", payload=payload
                    )
            except BackendTransportError:
                return create_error_response(
                    status_code=502,
                    headers={"X-InferGate-Backend": backend.id},
                    message="Cannot connect to backend.",
                    error_type="gateway_error",
                    code="backend_transport_failure",
                )

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

        # 如果没有移交资源所有权，释放 concurrency 名额
        finally:
            if not handed_off:
                try:
                    # If response construction fails, ownership was never handed off.
                    if opened_stream is not None:
                        with anyio.CancelScope(shield=True):
                            await opened_stream.aclose()
                finally:
                    concurrency_limiter.release()

    return app
