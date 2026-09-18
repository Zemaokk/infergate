from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictBool

from infergate.backend_client import BackendClient, BackendTransportError
from infergate.router import NoBackendAvailableError, RoundRobinRouter


class ChatCompletionRequest(BaseModel):
    model_config = {"extra": "allow"}
    model: str
    stream: StrictBool = False


def create_app(router: RoundRobinRouter, backend_client: BackendClient) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def create_chat_completion(request: ChatCompletionRequest) -> Response:
        payload = request.model_dump(exclude_unset=True)
        model = request.model

        # 拒绝 stream: true
        if request.stream:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "message": "Streaming is not supported in M0.",
                        "type": "invalid_request_error",
                        "param": "stream",
                        "code": None,
                    }
                },
            )

        # 选择模型，如果无可用，报503
        try:
            backend = router.select(model=model)
        except NoBackendAvailableError:
            error_response = JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "message": "No backend is available for the requested model.",
                        "type": "gateway_error",
                        "param": None,
                        "code": "no_backend_available",
                    }
                },
            )
            return error_response

        # 调用 backend_client 发送请求，连接失败报 502
        try:
            backend_response = await backend_client.forward(
                backend=backend, path="/v1/chat/completions", payload=payload
            )
        except BackendTransportError:
            error_response = JSONResponse(
                status_code=502,
                headers={"X-InferGate-Backend": backend.id},
                content={
                    "error": {
                        "message": "Cannot connect to backend.",
                        "type": "gateway_error",
                        "param": None,
                        "code": "backend_transport_failure",
                    }
                },
            )
            return error_response

        # 构造请求头
        headers = {"X-InferGate-Backend": backend.id}
        if backend_response.content_type is not None:
            headers["Content-Type"] = backend_response.content_type

        r = Response(
            content=backend_response.body,
            status_code=backend_response.status_code,
            headers=headers,
        )
        return r

    return app
