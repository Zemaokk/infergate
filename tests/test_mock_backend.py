from fastapi import Response
from fastapi.testclient import TestClient

from infergate.mock_backend import app

client = TestClient(app)

test_request = {
    "model": "mock-model",
    "messages": [
        {"role": "developer", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the longest word in English?"},
    ],
    "stream": False,
}

example_response = {
    "id": "chatcmpl-mock-001",
    "object": "chat.completion",
    "created": 1788508800,
    "model": "mock-model",
    "choices": [
        {
            "finish_reason": "stop",
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "This response came from the mock backend.",
            },
        }
    ],
}


def test_omitted_steam():
    omitted_steam_request = test_request.copy()
    omitted_steam_request.pop("stream")

    response: Response = client.post("/v1/chat/completions", json=omitted_steam_request)

    assert response.status_code == 200


def test_explicit_steam():
    response: Response = client.post("/v1/chat/completions", json=test_request)

    assert response.status_code == 200


def test_normal_response():
    response: Response = client.post("/v1/chat/completions", json=test_request)

    assert response.json()["model"] == "mock-model"
    assert response.json()["object"] == "chat.completion"
    assert type(response.json()["choices"]) == list
    assert response.json()["choices"][0]["message"]["role"] == "assistant"


def test_streaming_response_contains_two_sse_events():
    response = client.post(
        "/v1/chat/completions", json={**test_request, "stream": True}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert response.content.startswith(b"data: {")
    assert response.content.endswith(b"data: [DONE]\n\n")
