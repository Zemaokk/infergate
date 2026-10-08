# Usage and configuration

[Documentation index](README.md) · [Architecture](ARCHITECTURE.md) · [Verification](REPRODUCING.md)

Run commands from the repository root. The gateway requires Python 3.13.
The real-model inference environment uses separate dependencies and Python 3.12.

## Docker demo

With Docker Engine/Compose available and port 8000 free:

```sh
docker compose up --build -d --wait
docker compose logs -f gateway
```

The [Compose stack](../../../../compose.yaml) starts two mock backends and one gateway.
The gateway is published at `http://127.0.0.1:8000`; backends are internal
services at `backend-a:8000` and `backend-b:8000`. The demo backends implement
Chat, not Responses. The gateway itself exposes both adapters.

The container health check checks `/metrics` availability. It does not guarantee
inference readiness or healthy backends. The separate observability stack and
OTLP export are not enabled by this command.

Stop the demo with:

```sh
docker compose down
```

## Native Python

The recorded tool version is uv 0.12.2. Install the locked environment and run tests:

```sh
uv sync --locked --no-editable
uv run --no-sync python -m pytest -q
```

Start each of the following in a separate terminal:

```sh
uv run --no-sync uvicorn infergate.mock_backend:app --host 127.0.0.1 --port 8001
```

```sh
uv run --no-sync uvicorn infergate.mock_backend:app --host 127.0.0.1 --port 8002
```

```sh
uv run --no-sync uvicorn infergate.runtime:app --host 127.0.0.1 --port 8000 --workers 1 --log-config configs/logging.json
```

## API requests

### Chat Completions

The gateway validates a string `model`, a nonempty `messages` list, string
message content, and a strict boolean `stream`. Roles are `developer`,
`system`, `user`, or `assistant`. Extra fields are preserved for the backend,
which determines whether they are supported; this is not full API compatibility.

```sh
curl -i http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-InferGate-Key: local-demo' \
  -d '{"model":"mock-model","messages":[{"role":"user","content":"hello"}]}'
```

Admitted successful calls rotate across healthy backends. The response header
`X-InferGate-Backend` identifies the selected backend. For SSE, wait for quota
to refill or use a separate quota label:

```sh
curl -N -i http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-InferGate-Key: stream-demo' \
  -d '{"model":"mock-model","messages":[{"role":"user","content":"hello"}],"stream":true}'
```

The mock emits its first SSE event and `[DONE]` separately, with a short delay.

### Responses

Use a backend that actually supports native `/v1/responses` and set its model
alias in the runtime configuration below. The standard Compose mock cannot
generate Responses. The recorded real validation used vLLM 0.10.1+cu118;
the earlier vLLM 0.8.5 deployment advertised only Chat.

| Field | Gateway rule |
| --- | --- |
| `model`, `input` | Required nonblank strings; input arrays are unsupported |
| `store` | Required strict boolean `false` |
| `instructions` | Optional string or null |
| `max_output_tokens` | Optional integer >=16 or null; booleans rejected |
| `stream`, `background` | Optional strict booleans, only `false` supported |
| Other fields | Rejected with 400 |

Example for a gateway already configured for Qwen on a compatible backend:

```sh
curl -i http://127.0.0.1:8000/v1/responses \
  -H 'Content-Type: application/json' \
  -H 'X-InferGate-Key: responses-demo' \
  -d '{"model":"Qwen2.5-7B-Instruct","input":"Explain an HTTP gateway briefly.","store":false,"max_output_tokens":64}'
```

Omitted fields are not inserted into the forwarded payload; explicit nulls are
preserved. Responses does not translate to Chat. The tested backend omitted
`store` in response JSON, which is forwarded unchanged; a request's
`store=false` does not independently prove backend retention behavior.
The [Responses contract](M4/RESPONSES_CONTRACT.md) retains field-level decisions.

## Runtime configuration

Configuration is read once per app creation. Restart/create a new app to change
it. The model alias must match the backend's served model name.

| Variable | Default | Meaning |
| --- | --- | --- |
| `INFERGATE_MODEL_NAME` | `mock-model` | One nonblank served model alias |
| `INFERGATE_BACKEND_COUNT` | `2` | Exactly `1` or `2` |
| `INFERGATE_BACKEND_A_URL` | `http://127.0.0.1:8001` | Backend A base URL |
| `INFERGATE_BACKEND_B_URL` | `http://127.0.0.1:8002` | Backend B; ignored when count is 1 |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Unset | Optional full OTLP/HTTP trace endpoint |

Configured backend URLs require HTTP(S) and a host, with no userinfo, query,
fragment, or path prefix. Invalid configuration fails at app creation before
HTTP clients are created. Health probes and inference use the same configured URL.

For an existing single vLLM server at port 8001, run the gateway in a separate
terminal/environment:

```sh
INFERGATE_MODEL_NAME=Qwen2.5-7B-Instruct \
INFERGATE_BACKEND_COUNT=1 \
INFERGATE_BACKEND_A_URL=http://127.0.0.1:8001 \
  uv run --no-sync uvicorn infergate.runtime:app --host 127.0.0.1 --port 8000 --workers 1 --log-config configs/logging.json
```

This command starts only the gateway. GPU environment installation, model
startup, and fresh measurement procedures are in [Reproduction](REPRODUCING.md).

## Admission and failure behavior

The defaults are a per-key burst of 2, refill of 1 request/second, and 2 global
concurrent downstream tasks, with no waiting queue. These are code defaults,
not environment-configurable settings. Both APIs share them.

| Condition | Gateway response |
| --- | --- |
| Invalid body or missing/blank key | 400 |
| Key quota exhausted | 429 `rate_limit_exceeded` |
| Global concurrency exhausted | 503 `concurrency_limit_exceeded` |
| No initial healthy candidate for the model | 503 `no_backend_available` |
| Backend transport failure without successful fallback | 502 `backend_transport_failure` |
| Backend returns an HTTP error | Backend status, body, and Content-Type forwarded |

Body validation precedes admission. A concurrency rejection has already consumed
a key token; failures do not refund quota. A fallback uses the same slot and
quota charge. Caller-supplied keys are quota labels, not authentication.

Stopping a backend removes it after a failed probe. Before that update, a
connection error can fall back to the other backend. If both connections fail,
an admitted request returns 502; after both are marked unhealthy, initial
routing returns 503. Successful probes restore eligibility. These status
transitions depend on probe timing.

## Metrics and traces

```sh
curl http://127.0.0.1:8000/metrics
```

The metrics endpoint requires no key and does not count as a business request.
See [Observability](OBSERVABILITY.md) for exact metric definitions and export
configuration, and the [stack guide](../observability/README.md) for
Prometheus, Jaeger, Grafana, and controlled end-to-end checks.
