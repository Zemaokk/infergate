# Verify an installation

Use Python 3.13 with the lockfile. These checks verify the revision you run;
[dated acceptance evidence](../reference/validation.md) describes prior runs.
Write fresh outputs to a separate directory, leaving dated evidence unchanged.

## Check the checkout

```sh
uv sync --locked --no-editable
uv run --no-sync python scripts/check_docs.py
uv run --no-sync python -m compileall -q src scripts
uv run --no-sync python -m pytest -q
git diff --check
```

The documentation check validates current links and published evidence hashes. Pytest checks
request handling, state transitions, cleanup, observation, and benchmark evidence
boundaries. A test count is a dated observation, not a release version.

## Check real loopback HTTP

With ports 8000–8002 free:

```sh
uv run --no-sync python scripts/verify_m2.py --output /tmp/infergate-m2-new.json
```

The script starts and cleans up its own application processes. It checks seven
scenario groups for quota, concurrency, fallback, rejection order, and recovery.
For logs, metrics, and traces across actual services, follow
[Observe requests](observe-requests.md#run-the-controlled-integration-check).

## Check the container package

With Docker Engine/Compose available and port 8000 free:

```sh
docker compose config --quiet
uv run --no-sync python scripts/verify_m4.py --output /tmp/infergate-packaging-new.json
```

The verifier builds an image and starts its own three-service project. It
checks non-root UID, non-editable installation, ordinary/SSE requests, routing,
stop/recovery, and all-backend rejection. It writes JSON evidence and removes
its containers/network. It refuses an existing project name; `--project` selects
a different name. Do not interrupt someone else's service to free a port.

## Read the result

Require a passing result and successful cleanup. Retain failed evidence instead
of overwriting it with a later success. The [CI workflow](../../.github/workflows/ci.yml)
runs tests and isolated container verification on push, pull requests, or manual
dispatch. A local run does not establish that a hosted job has passed.

Saved benchmark archives can be checked and redrawn with
[Redraw saved benchmarks](redraw-benchmarks.md). Model integration requires a
separate backend; [Connect a model backend](connect-backend.md) describes that check.
