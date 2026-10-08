# Metrics, logs, and tracing

[Documentation index](README.md) · [Architecture](ARCHITECTURE.md) · [Run locally](USAGE.md)

InferGate observes the complete request lifecycle and each actual backend
attempt separately. The same observations feed metrics, structured completion
logs, and OpenTelemetry spans.

## Request and attempt semantics

| Scenario | Request observation | Backend attempts |
| --- | --- | --- |
| Admission rejection | One rejected request | None |
| A connection fails, B completes | One completed request | A transport error, B completed |
| Client disconnects after HTTP 200 | One cancelled request | Opened attempt cancelled |

A fallback produces one request span with two sibling CLIENT attempt spans.
Context propagation alone does not create spans in uninstrumented clients or
model services. See [M3 acceptance](M3/ACCEPTANCE.md) for checked traces.

## Metrics reference

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

## Completion logs and trace context

The gateway startup command loads `configs/logging.json`. Each business request
emits one JSON completion record to stderr after cleanup, with its request ID,
final result and ordered backend-attempt details. Uvicorn server/access logs keep
their normal format. Completion logs exclude keys, bodies and exception text.
Logging and metric submission failures do not change business results.
The application factory does not install handlers; other launchers must configure
the `infergate.observability` logger at INFO to enable these records.

Each app creates an OpenTelemetry request span, ending after response cleanup.
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
and controlled acceptance script are described in [observability/README.md](../observability/README.md).
Docker Desktop integration passed on 2026-10-05 and was checked again on
2026-10-08 with 9 requests and 10 attempts; see the [acceptance record](M3/ACCEPTANCE.md).
Dashboard screenshots are from the 2026-10-05 rendering check.

## Dashboard and evidence

![Grafana request and latency panels](M3/evidence/grafana-2026-10-05.jpg)

The screenshot is a dated local demonstration. Setup, service addresses,
controlled integration checks, and shutdown are documented in the
[observability stack guide](../observability/README.md). These services run
separately from the application Compose stack.

[Back to documentation](README.md)
