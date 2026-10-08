# Your first request

In this tutorial you will start InferGate with two mock backends, send two
ordinary requests, and watch a streamed response. You need Docker Engine with
Compose, curl, and a free port 8000. The mocks generate fixed text; no model or
GPU is needed.

## Start the demo

From the repository root, run:

```sh
docker compose up --build -d --wait
```

Compose starts `backend-a`, `backend-b`, and `gateway`. Wait for the command to
finish successfully before continuing. The gateway is at `127.0.0.1:8000`.

## Send an ordinary request

```sh
curl -i http://127.0.0.1:8000/v1/chat/completions   -H 'Content-Type: application/json'   -H 'X-InferGate-Key: tutorial'   -d '{"model":"mock-model","messages":[{"role":"user","content":"hello"}]}'
```

Expect HTTP 200, a JSON `chat.completion`, and an `X-InferGate-Backend` header.
In a fresh demo with no other business traffic, the first request selects A.
Wait for the quota to refill, then send the same request again:

```sh
sleep 1.1
curl -i http://127.0.0.1:8000/v1/chat/completions   -H 'Content-Type: application/json'   -H 'X-InferGate-Key: tutorial'   -d '{"model":"mock-model","messages":[{"role":"user","content":"hello"}]}'
```

The header now identifies B. You have observed round-robin routing across two
healthy backends. Health probes do not advance that routing cursor.

## Read a stream

Use a separate quota label for this request:

```sh
curl -N -i http://127.0.0.1:8000/v1/chat/completions   -H 'Content-Type: application/json'   -H 'X-InferGate-Key: tutorial-stream'   -d '{"model":"mock-model","messages":[{"role":"user","content":"hello"}],"stream":true}'
```

Expect HTTP 200 with `text/event-stream`, a `data:` event, and a later
`data: [DONE]` event. `-N` disables curl's output buffering. The mock inserts a
short delay between events, so the response arrives incrementally.

## Inspect and stop

```sh
curl http://127.0.0.1:8000/metrics
docker compose logs gateway
docker compose down
```

Metrics contain finalized request and backend-attempt observations. Gateway
logs contain a JSON completion record for each business request. The final
command removes this demo's containers and network.

You have exercised ordinary and streaming Chat through the gateway. To use
Python directly, follow [Run locally](../how-to/run-locally.md). To replace the
mocks, follow [Connect a model backend](../how-to/connect-backend.md). The
[API reference](../reference/api.md) lists validation and failure behavior.
