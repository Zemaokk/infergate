# InferGate

A learning-driven, production-style LLM inference gateway built incrementally from first principles.

The current architecture, scope, milestones, and engineering constraints are documented in [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md).

The learning and AI contribution boundaries are documented in [docs/COLLABORATION_CONTRACT.md](docs/COLLABORATION_CONTRACT.md).

API direction: Chat Completions is the M0 compatibility baseline; a non-streaming Responses API adapter is planned after the shared gateway core is complete. See [ADR-0001](docs/decisions/0001-api-surface.md).

To implement the current milestone from the existing contracts through local
end-to-end verification, follow the [M0 full workflow guide](docs/M0/FULL_WORKFLOW_GUIDE.md).

## Current status

M0 is complete. InferGate currently provides:

- a validated, non-streaming `POST /v1/chat/completions` endpoint;
- model-aware round-robin routing across two mock backends;
- transparent backend status, body, and `Content-Type` forwarding;
- stable `400`, `502`, and `503` gateway error mappings; and
- automated coverage for validation, routing, transport failures, and the
  complete gateway request path.

## Run M0 locally

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
`backend-b`.
