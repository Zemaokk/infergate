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
M3 observability is complete within its agreed scope; see the acceptance record.
M4 has started with application packaging; see the [M4 work plan](docs/M4/WORKPLAN.md)
and [packaging contract](docs/M4/PACKAGING_CONTRACT.md). The three-container mock
stack passed packaging integration checks on 2026-10-06; author explanations
and corrections are recorded in the [M4.1 acceptance record](docs/M4/ACCEPTANCE.md).
M4.2 has verified a real Qwen2.5-7B-Instruct backend directly on a leased RTX4090;
gateway integration remains pending. See the [real backend contract](docs/M4/REAL_BACKEND_CONTRACT.md)
and [remote environment evidence](docs/M4/REMOTE_ENVIRONMENT.md).

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

### Docker Compose

With Docker Engine running and host port 8000 available:

```bash
docker compose up --build -d --wait
```

This builds the application and starts two mock backends plus a single-worker
gateway at `http://127.0.0.1:8000`. Backends are reachable inside the Compose
network as `backend-a:8000` and `backend-b:8000`; their ports are not published.
The request examples below work unchanged. Gateway container health checks
verify `/metrics` availability, not inference readiness or backend health.
The stack does not start the separate M3 observability services or enable OTLP export.

```bash
docker compose logs -f gateway
docker compose down
```

Reproduce the packaging checks with port 8000 free:

```bash
uv run python scripts/verify_m4.py --output /tmp/infergate-m4-evidence.json
```

The script builds and starts its own Compose project, checks real HTTP routing,
SSE chunks, backend failure/recovery and all-backend rejection, saves evidence,
and removes its containers. It refuses to reuse an existing project or occupied
port. These are mock integration checks, not model-performance benchmarks.

### Native Python

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
uv run uvicorn infergate.runtime:app --host 127.0.0.1 --port 8000 --log-config configs/logging.json
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

Native runtime backend addresses can be configured with
`INFERGATE_BACKEND_A_URL` and `INFERGATE_BACKEND_B_URL`. When unset they default
to `http://127.0.0.1:8001` and `http://127.0.0.1:8002`. Empty or invalid values
raise `ValueError` at app creation before HTTP clients are created. Both health
probes and inference calls use the configured base URL; changes require a new
app/process. URLs must use HTTP(S), have a host, and contain no userinfo, query,
fragment or path prefix. See the packaging contract for the supported subset.

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

`infergate_active_requests` is a Gauge of occupied global concurrency slots,
read directly from the limiter at scrape time. It includes streaming cleanup
and stays occupied across fallback. For buffered non-streaming responses, the
slot is released before sending to the client, so it does not count all HTTP
responses still being sent. It is a current snapshot, not a historical peak.

`infergate_backend_healthy{backend}` reads the existing HealthManager state for
configured backend IDs: 1 means marked healthy for routing; 0 means marked
unhealthy or not yet probed. It reflects the last stored state, not a fresh
probe or a guarantee that the next request will succeed. Scraping never probes
backends. Apps without a HealthManager omit this metric.

`infergate_backend_attempts_total{backend,outcome}` counts finalized backend
attempts. `infergate_backend_attempt_duration_seconds{backend,outcome}` records
each attempt's duration from its own call start, including cleanup for opened
streams. A failed A followed by successful B produces two attempt samples and
one request sample. Both attempt metrics are submitted at request finalization;
even a finished A remains unexported while B is still streaming. Rejections
before any backend call produce no attempt samples. Labels use configured
backend IDs, never backend URLs or exception text.

`infergate_backend_first_byte_seconds{backend,outcome}` measures each streaming
attempt from its own call start to the first nonempty backend body chunk. It
excludes earlier fallback attempts and is not TTFT or client receive latency.
Samples are submitted at request finalization, grouped by the attempt's final
outcome. Empty streams, failures before the first chunk and non-streaming calls
produce no samples; zero duration and first bytes observed before later failure
are retained. Whitespace chunks count as nonempty.
The gateway startup command loads `configs/logging.json`. Each business request
emits one JSON completion record to stderr after cleanup, with its request ID,
final result and ordered backend-attempt details. Uvicorn server/access logs keep
their normal format. Completion logs exclude keys, bodies and exception text.
Logging and metric submission failures do not change business results.
The application factory does not install handlers; other launchers must configure
the `infergate.observability` logger at INFO to enable these records.

Each app now creates an OpenTelemetry request span, ending after response cleanup.
Completion logs include its `trace_id` and `span_id`; no IDs are metric labels.
Each actual backend attempt has a CLIENT span under that request, with its own
outcome, duration and optional first-byte timing. Fallback attempts are siblings;
opened stream spans remain active through cleanup. Attempt log entries include
their span IDs. Valid incoming W3C `traceparent` headers continue the upstream
trace; missing or invalid headers start a new trace. Only `traceparent` and
`tracestate` are extracted, never baggage or business headers. Backend calls inject
the current attempt's W3C context, including on fallback; caller keys and baggage
are not forwarded. The local Prometheus, Jaeger and Grafana stack has passed
controlled integration checks; `/metrics` exposes current in-process aggregates.

## Trace export

To enable OTLP/HTTP protobuf export, start the gateway with a trace receiver's
full endpoint (including `/v1/traces`):

```bash
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces \
  uv run uvicorn infergate.runtime:app --host 127.0.0.1 --port 8000 --log-config configs/logging.json
```

Start an OTLP receiver separately; this command does not launch one. Without this
variable, spans and log correlation still work but no exporter or batch worker
is installed. Only the traces-specific endpoint enables export in this runtime;
the generic `OTEL_EXPORTER_OTLP_ENDPOINT` alone does not enable it.

The runtime installs one batch processor at startup, with a 2048-span queue,
256-span batches and a 1-second schedule. Export HTTP requests have a 2-second
timeout. Request completion only enqueues spans, so receiver failures do not
change business outcomes or metrics. Export is best effort; queue overflow,
failed sends or interrupted shutdown can lose spans.

After stopping health probes and closing HTTP clients, runtime shutdown asks the
provider to drain and close in a daemon thread, waiting at most 5 seconds without
blocking the event loop. This bounds lifecycle waiting, not forcibly terminating
the SDK operation or guaranteeing delivery; timed-out cleanup can finish later.
Local Jaeger reception and Grafana rendering have been verified.

The local Prometheus/Jaeger/Grafana Compose configuration, provisioned dashboard
and controlled acceptance script are described in [observability/README.md](observability/README.md).
Docker Desktop integration passed on 2026-10-05 with 9 requests and 10 attempts;
see [acceptance evidence](docs/M3/ACCEPTANCE.md). M3 author teach-back is complete.
