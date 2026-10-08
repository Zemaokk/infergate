# Run locally

Use Docker for the three-service mock demo, or run the gateway and mocks as
native Python processes. The mocks support Chat only. For a guided walkthrough,
see [Your first request](../tutorials/first-request.md).

## Docker

With Docker Engine/Compose available and port 8000 free:

```sh
docker compose up --build -d --wait
docker compose logs -f gateway
```

The [application stack](../../compose.yaml) publishes only the gateway at
`127.0.0.1:8000`. Internal backend addresses are `backend-a:8000` and
`backend-b:8000`. The gateway container runs as UID 10001. Its health check
checks `/metrics` availability; it does not establish inference readiness.

Press Ctrl-C to leave log following, then stop the stack:

```sh
docker compose down
```

## Native Python

Use Python 3.13 and uv (recorded tool version: 0.12.2). Install from the lockfile:

```sh
uv sync --locked --no-editable
```

Run each command in its own terminal:

```sh
uv run --no-sync uvicorn infergate.mock_backend:app --host 127.0.0.1 --port 8001
```

```sh
uv run --no-sync uvicorn infergate.mock_backend:app --host 127.0.0.1 --port 8002
```

```sh
uv run --no-sync uvicorn infergate.runtime:app --host 127.0.0.1 --port 8000 --workers 1 --log-config configs/logging.json
```

Send the [tutorial requests](../tutorials/first-request.md#send-an-ordinary-request).
Stop each foreground process with Ctrl-C when finished. Use one worker:
quota, capacity, routing, and health state are process-local. The `infergate`
console command still prints a scaffold greeting; launch the Uvicorn app above.

## If a request fails

A 400 means body/key validation failed; use the tutorial payload and a nonblank
`X-InferGate-Key`. After 429, allow the key quota to refill. A concurrency 503
means both slots were occupied; a `no_backend_available` 503 means routing
found no healthy candidate. Inspect backend logs and allow a successful probe
round after recovery. See the [error reference](../reference/api.md#errors)
for the distinction between these responses.

Configuration is in the [configuration reference](../reference/configuration.md).
For metrics and traces across services, follow [Observe requests](observe-requests.md).
