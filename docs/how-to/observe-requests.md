# Observe requests

Use the separate local stack to inspect request counts, latency distributions,
and traces. You need Docker Engine/Compose and the installed Python gateway.
Ports 3000, 4318, 9090, and 16686 must be free. For the controlled verification,
ports 8000–8002 must also be free.

## Start the stack

```sh
docker compose -f observability/compose.yaml config --quiet
docker compose -f observability/compose.yaml up -d
```

The pinned images are Prometheus 3.15.0, Jaeger 2.21.0, and Grafana 13.2.3.
Open Prometheus at `http://127.0.0.1:9090`, Jaeger at
`http://127.0.0.1:16686`, or Grafana at `http://127.0.0.1:3000`.
Grafana's local demo login is `admin` / `infergate-local`. Open the
**InferGate 本地可观测性** dashboard in the InferGate folder. Data sources and
the eleven panels are provisioned automatically.

Prometheus connects to `host.docker.internal:8000/metrics`. The Compose file
provides a Linux host-gateway mapping. The host gateway must bind to
`0.0.0.0:8000` to permit container scraping; the observation UIs bind only to
host loopback.

## Run the controlled integration check

Ensure 8000–8002 are free, then run:

```sh
uv run --no-sync python scripts/verify_m3.py --output /tmp/infergate-m3-new.json
```

The script starts its own mock backends and gateway, verifies nine business
requests and ten backend attempts against real logs, Prometheus, and Jaeger,
and checks Grafana provisioning. It temporarily uses a 3600s probe interval to
trigger fallback deterministically after stopping a backend. Production defaults
are unchanged. It saves passed/failed evidence and stops its application
processes, leaving the observation containers running.

A passing run establishes this controlled integration. It does not measure
production performance. The script uses Jaeger 2.21's UI HTTP API; revalidate
that integration when upgrading images. Inspect [dated validation](../reference/validation.md)
for the previous checked run and screenshot scope.

## Inspect your own traffic

Start the two native mocks as described in [Run locally](run-locally.md), then
start the host gateway in a third terminal:

```sh
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces   uv run --no-sync uvicorn infergate.runtime:app --host 0.0.0.0 --port 8000 --workers 1 --log-config configs/logging.json
```

Send the [tutorial requests](../tutorials/first-request.md#send-an-ordinary-request).
Find the completion record's `trace_id` in Jaeger. A successful fallback has one
request span and two sibling CLIENT spans. Check final outcome as well as HTTP
status: a stream can send 200 before failing. Prometheus series appear after
their first observation; rates need multiple scrapes. Missing first-byte samples
should remain No data. This timing is not model TTFT.

If Grafana is empty, confirm that the Prometheus target is up, that the host
binding permits scraping, and that business requests have completed. See the
[observability reference](../reference/observability.md) for exact semantics.

## Stop

Stop the foreground gateway/mocks with Ctrl-C, then:

```sh
docker compose -f observability/compose.yaml down
```

This retains Prometheus/Grafana named volumes. Jaeger traces live in memory and
are lost on restart. The application Compose stack is managed separately.
