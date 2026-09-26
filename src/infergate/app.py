from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StrictBool, StrictStr
from starlette.types import Lifespan

from infergate.api_errors import create_error_response
from infergate.backend_client import (
    BackendClient,
    BackendStreamResponse,
    BackendTransportError,
)
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


# 转发并确保关闭下游 streaming response
async def stream_backend_body(response: BackendStreamResponse) -> AsyncIterator[bytes]:
    try:
        async for chunk in response.aiter_bytes():
            yield chunk
    finally:
        await response.aclose()


def create_app(
    router: RoundRobinRouter,
    backend_client: BackendClient,
    limiter: TokenBucketLimiter,
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
        payload = request.model_dump(exclude_unset=True)

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
            if not limiter.allow(key=x_infergate_key):
                return create_error_response(
                    status_code=429,
                    message="Too many requests.",
                    error_type="invalid_request_error",
                    code="rate_limit_exceeded",
                )

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
            r = StreamingResponse(
                content=stream_backend_body(backend_response),
                status_code=backend_response.status_code,
                headers=headers,
            )
        else:
            r = Response(
                content=backend_response.body,
                status_code=backend_response.status_code,
                headers=headers,
            )

        return r

    return app
