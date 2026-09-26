# InferGate

A learning-driven, production-style LLM inference gateway built incrementally from first principles.

The current architecture, scope, milestones, and engineering constraints are documented in [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md).

The learning and AI contribution boundaries are documented in [docs/COLLABORATION_CONTRACT.md](docs/COLLABORATION_CONTRACT.md).

API direction: Chat Completions is the M0 compatibility baseline; a non-streaming Responses API adapter is planned after the shared gateway core is complete. See [ADR-0001](docs/decisions/0001-api-surface.md).

For the original M0 workflow, see the [M0 full workflow guide](docs/M0/FULL_WORKFLOW_GUIDE.md).
The M1 streaming and backend-health acceptance record is in
[docs/M1/ACCEPTANCE.md](docs/M1/ACCEPTANCE.md).

## Current status

M0 and M1 are complete. M2 is at the contract and author-prediction stage;
no M2 traffic-control behavior is implemented yet. See the
[M2 work plan](docs/M2/WORKPLAN.md).

InferGate currently provides:

- a validated `POST /v1/chat/completions` endpoint with non-streaming and
  streaming passthrough;
- model-aware round-robin routing that skips unhealthy backends and restores
  them after a successful health probe;
- parallel startup probes, periodic `GET /health` checks, and `503` when no
  backend is healthy;
- transparent backend status, body, and `Content-Type` forwarding;
- stable `400`, `502`, and `503` gateway error mappings; and
- automated coverage for validation, routing, transport failures, streaming
  cleanup, and the gateway request path.

## Run locally

Install the project and run the test suite:

```bash
uv sync
uv run pytest -q
```

Start the two mock backends in separate terminals:

```bash
uv run uvicorn infergate.mock_backend:app --host 127.0.0.1 --port 8001
```

```bash
uv run uvicorn infergate.mock_backend:app --host 127.0.0.1 --port 8002
```

Start InferGate in a third terminal:

```bash
uv run uvicorn infergate.runtime:app --host 127.0.0.1 --port 8000
```

Send the same request repeatedly:

```bash
curl -i http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "mock-model",
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

The `X-InferGate-Backend` response header alternates between `backend-a` and
`backend-b` while both are healthy. To see streaming bytes arrive separately:

```bash
curl -N -i http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "mock-model",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": true
  }'
```

The mock backend waits briefly between its first SSE event and `[DONE]`.
Stopping one backend removes it from routing after the next probe; stopping
both leaves the gateway running but makes requests return `503`. A restarted
backend rejoins after one successful probe.
