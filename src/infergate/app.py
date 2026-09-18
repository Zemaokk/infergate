from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from infergate.backend_client import BackendClient
from infergate.router import NoBackendAvailableError, RoundRobinRouter


class ChatCompletionRequest(BaseModel):
    model_config = {"extra": "allow"}
    model: str


def create_app(router: RoundRobinRouter, backend_client: BackendClient) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def create_chat_completion(request: ChatCompletionRequest) -> Response:
        payload = request.model_dump()
        model = request.model

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

        backend_response = await backend_client.forward(
            backend=backend, path="/v1/chat/completions", payload=payload
        )

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
