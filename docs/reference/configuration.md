# Configuration reference

Runtime configuration is read once by `create_runtime_app()` in
[runtime.py](../../src/infergate/runtime.py). Changes require a new app or
process. The supported deployment uses one worker.

## Environment variables

| Variable | Default | Rule |
| --- | --- | --- |
| `INFERGATE_MODEL_NAME` | `mock-model` | One nonblank served model alias |
| `INFERGATE_BACKEND_COUNT` | `2` | Exactly the string `1` or `2` |
| `INFERGATE_BACKEND_A_URL` | `http://127.0.0.1:8001` | Backend A origin |
| `INFERGATE_BACKEND_B_URL` | `http://127.0.0.1:8002` | Backend B origin; ignored when count is 1 |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Unset | Optional full OTLP/HTTP traces endpoint, including `/v1/traces` |

Backend URLs require HTTP(S) and a host, with no userinfo, query, fragment, or
path prefix. Invalid configuration fails before creating HTTP clients. Inference
and probes use the same configured origin. Both HTTPX clients use
`trust_env=False`; environment proxy settings are not applied to these clients.
The generic `OTEL_EXPORTER_OTLP_ENDPOINT` alone does not enable trace export.

## Fixed runtime defaults

These are code defaults, not environment variables or a general settings API.

| Setting | Value | Scope |
| --- | --- | --- |
| Token bucket capacity | 2 requests | Per caller key |
| Token refill | 1 request/second | Per caller key |
| Concurrency capacity | 2 | Shared across both public APIs |
| Waiting queue | None | Excess work rejected immediately |
| Backend attempts | At most 2 | Only connection-establishment failures permit fallback |
| HTTPX connect / pool timeout | 5s / 5s | Inference HTTP operations |
| HTTPX write / read timeout | 30s / 30s | Inference HTTP operations |
| Probe deadline | 2s | Each health probe |
| Probe interval | 5s | Delay after a probe round completes |

There is no total generation deadline or stream-close deadline. Startup probes
run in parallel; periodic rounds do not overlap. The key-state dictionary has
no eviction. Multiple workers create independent state and registries.

## Observation defaults

The [logging configuration](../../configs/logging.json) enables completion
records on `infergate.observability` at INFO. The app factory does not install
logging handlers itself. Trace export, when enabled, uses a 2048-span queue,
256-span batches, a 1s schedule, and a 2s HTTP export timeout. Shutdown waits up
to 5s for provider cleanup in a daemon thread; this does not guarantee delivery.
See [Observability](observability.md) for precise lifecycle semantics.

## Container and local service addresses

| Service | Address | Configuration |
| --- | --- | --- |
| Application gateway | `127.0.0.1:8000` | [compose.yaml](../../compose.yaml) |
| Mock backends in application Compose | `backend-a:8000`, `backend-b:8000` | Internal service network |
| Prometheus UI | `127.0.0.1:9090` | [observability Compose](../../observability/compose.yaml) |
| Jaeger UI / OTLP receiver | `127.0.0.1:16686` / `127.0.0.1:4318/v1/traces` | Separate observation stack |
| Grafana UI | `127.0.0.1:3000` | Local demo login: `admin` / `infergate-local` |

The gateway image runs non-root (UID 10001), installs non-editably, and checks
`/metrics` for container health. Observation services are not started by the
application Compose stack. Prometheus scrapes every 5s with 24h retention;
Jaeger uses in-memory trace storage. Prometheus and Grafana use named volumes.
