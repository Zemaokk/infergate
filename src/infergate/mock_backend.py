import asyncio
import time
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

app = FastAPI()


class Message(BaseModel):
    model_config = {"extra": "allow"}

    role: Literal["developer", "system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model_config = {"extra": "allow"}

    model: str
    messages: list[Message] = Field(min_length=1)
    stream: bool = False


class Choice(BaseModel):
    finish_reason: str
    index: int
    message: Message


class ChatCompletionResponse(BaseModel):
    id: str
    object: str
    created: int
    model: str
    choices: list[Choice]


@app.get("/health")
async def health() -> Response:
    return Response(status_code=200)


async def mock_stream_body() -> AsyncIterator[bytes]:
    yield (
        b'data: {"id":"chatcmpl-mock-001","object":"chat.completion.chunk",'
        b'"choices":[{"delta":{"content":"Hello"}}]}\n\n'
    )
    await asyncio.sleep(0.3)
    yield b"data: [DONE]\n\n"


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    chatcompletionrequest: ChatCompletionRequest,
) -> ChatCompletionResponse | StreamingResponse:
    # 1. 读取 JSON payload
    # 2. 读取请求中的 model
    # 3. 构造符合 API contract 的 mock response
    if chatcompletionrequest.stream:
        return StreamingResponse(mock_stream_body(), media_type="text/event-stream")

    response = ChatCompletionResponse(
        id="chatcmpl-mock-001",
        object="chat.completion",
        created=int(time.time()),
        model=chatcompletionrequest.model,
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=Message(
                    role="assistant",
                    content="This response came from the mock backend.",
                ),
            )
        ],
    )
    # 4. 返回 response
    return response
