# InferGate

A learning-driven, production-style LLM inference gateway built incrementally from first principles.

The current architecture, scope, milestones, and engineering constraints are documented in [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md).

The learning and AI contribution boundaries are documented in [docs/COLLABORATION_CONTRACT.md](docs/COLLABORATION_CONTRACT.md).

API direction: Chat Completions is the M0 compatibility baseline; a non-streaming Responses API adapter is planned after the shared gateway core is complete. See [ADR-0001](docs/decisions/0001-api-surface.md).

For the original M0 workflow, see the [M0 full workflow guide](docs/M0/FULL_WORKFLOW_GUIDE.md).
The M1 streaming and backend-health acceptance record is in
[docs/M1/ACCEPTANCE.md](docs/M1/ACCEPTANCE.md).

## Current status

M0, M1, and the scoped single-process M2 implementation are complete.
M2 passed 122 automated tests and seven local HTTP acceptance scenarios.
See the [M2 acceptance record and limitations](docs/M2/ACCEPTANCE.md).
M3 observability has not started.

InferGate currently provides:

- a validated `POST /v1/chat/completions` endpoint with non-streaming and
  streaming passthrough;
- model-aware round-robin routing that skips unhealthy backends and restores
  them after a successful health probe;
- parallel startup probes, periodic `GET /health` checks, and `503` when no
  backend is healthy;
- transparent backend status, body, and `Content-Type` forwarding;
- per-key token bucket limits with `429` rejection;
- process-wide concurrency limits with immediate `503` rejection and streaming cleanup;
- at most two backend attempts, with fallback only for connection establishment failures;
- stable `400`, `429`, `502`, and `503` gateway error mappings; and
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
  -H 'X-InferGate-Key: local-demo' \
  -d '{
    "model": "mock-model",
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

The local defaults are a burst capacity of 2 requests per key, replenished at
1 request/second, and 2 concurrent downstream tasks across all keys. Rapidly
repeating a key can return `429`; excess global concurrency returns `503`.
Use `X-InferGate-Key` as a quota label, not an authentication credential.

For admitted requests, `X-InferGate-Backend` alternates between `backend-a` and
`backend-b` while both are healthy. Wait for quota to refill before this streaming example:

```bash
curl -N -i http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-InferGate-Key: local-demo' \
  -d '{
    "model": "mock-model",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": true
  }'
```

The mock backend waits briefly between its first SSE event and `[DONE]`.
Stopping one backend removes it from routing after the next probe; before that
probe, a connection failure can fall back to the other backend. If both fail to
connect, an admitted request returns `502`; after probes mark both unhealthy,
initial routing returns `503 no_backend_available`. A restarted backend rejoins
after one successful probe.

## Reproduce M2 acceptance

With ports 8000–8002 unused:

```bash
uv run python scripts/verify_m2.py --output /tmp/infergate-m2-evidence.json
```

The script starts and stops its own three processes, using controlled mock
streams and a temporary 3600-second health-probe interval to exercise fallback
before health updates. Production runtime defaults remain unchanged.
Key-state cleanup, multi-process quotas, total request deadlines, and performance
validation remain outside this acceptance; see the limitations linked above.

## M3 request metrics (initial slice)

With the gateway running, scrape `GET /metrics` (no key required):

```bash
curl http://127.0.0.1:8000/metrics
```

- `infergate_requests_total{route,status,outcome,reason}` counts finalized business
  requests, including validation/admission rejections and interrupted streams.
- `infergate_request_duration_seconds{route,outcome}` is a histogram of gateway
  request duration through response execution and cleanup, in seconds. Buckets
  range from 0.01 to 300 seconds plus infinity; they are initial design choices,
  not measured latency targets.

Each app owns an independent, single-process registry. Metrics scrapes are not
business requests. Labels exclude caller keys, arbitrary model names and body
content. A stream may have status `200` and outcome `stream_error`; do not infer
success from status alone. Status `none` means this observer did not successfully
send headers before finalization. Series appear after their first observation.

`infergate_request_first_byte_seconds{route,outcome}` records time from request
entry to the first nonempty backend stream chunk, including any fallback time.
It is not TTFT or client receive latency. Samples are exported at request
finalization, grouped by final outcome. Missing first bytes produce no sample;
an observed zero duration is retained. Non-streaming responses do not sample it.

Backend-attempt, concurrency and health metrics are not exported yet.
Prometheus server, Grafana, structured completion logs and tracing are later M3
steps; `/metrics` only exposes the current in-process aggregates.
