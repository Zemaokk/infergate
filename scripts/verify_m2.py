"""Local M2 acceptance against three owned processes on ports 8000-8002.

Run: uv run python scripts/verify_m2.py --output docs/M2/acceptance_evidence.json
Requires these ports to be unused. All child processes are stopped on exit.
The gateway uses production create_runtime_app with probe interval set to 3600s
so stopped backends remain routing candidates during deterministic fallback checks.
"""

import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"
BACKENDS = {"backend-a": 8001, "backend-b": 8002}


def serve(mode, port):
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse

    if mode == "gateway":
        from infergate.runtime import create_runtime_app

        app = create_runtime_app(probe_interval_seconds=3600)
    else:
        app = FastAPI()
        gates = {}
        closed = set()

        @app.get("/health")
        async def health():
            return {"ok": True}

        @app.post("/control/release/{name}")
        async def release(name: str):
            gates[name].set()
            return {"released": name}

        @app.get("/control/closed/{name}")
        async def is_closed(name: str):
            return {"closed": name in closed}

        @app.post("/v1/chat/completions")
        async def completion(request: Request):
            payload = await request.json()
            name = payload.get("acceptance_hold")
            if name:
                gates[name] = asyncio.Event()

            async def body():
                try:
                    yield b"data: first\n\n"
                    if name:
                        await gates[name].wait()
                    yield b"data: [DONE]\n\n"
                finally:
                    if name:
                        closed.add(name)

            if payload.get("stream"):
                return StreamingResponse(body(), media_type="text/event-stream")
            return {"model": payload["model"], "ok": True}

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


async def wait_ready(client, url, process):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited before ready: {url}")
        try:
            response = await client.get(url)
            if response.status_code == 200:
                return
        except httpx.TransportError:
            pass
        await asyncio.sleep(0.05)
    raise RuntimeError(f"Server startup timed out: {url}")


async def verify(output):
    for port in (8000, 8001, 8002):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    evidence = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "loopback HTTP, three owned uvicorn processes, controlled mock backends",
        "configuration": {
            "bucket_capacity": 2, "refill_per_second": 1, "concurrency_limit": 2,
            "max_attempts": 2, "probe_interval_seconds_override": 3600,
        },
        "checks": [],
    }
    processes = {}
    with tempfile.TemporaryDirectory(prefix="infergate-m2-") as temp:
        logs = []
        try:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                for name, port in BACKENDS.items():
                    log = open(Path(temp) / f"{name}.log", "w")
                    logs.append(log)
                    processes[name] = subprocess.Popen(
                        [sys.executable, str(Path(__file__).resolve()),
                         "--serve", "backend", "--port", str(port)],
                        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                    )
                    await wait_ready(client, f"http://127.0.0.1:{port}/health", processes[name])
                log = open(Path(temp) / "gateway.log", "w")
                logs.append(log)
                processes["gateway"] = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()),
                     "--serve", "gateway", "--port", "8000"],
                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                )
                await wait_ready(client, BASE + "/openapi.json", processes["gateway"])
                payload = {"model": "mock-model", "messages": [{"role": "user", "content": "hi"}]}

                async def post(key=None):
                    headers = {} if key is None else {"X-InferGate-Key": key}
                    return await client.post(BASE + "/v1/chat/completions", json=payload, headers=headers)

                def record(name, **details):
                    evidence["checks"].append({"name": name, "passed": True, **details})
                    print(f"PASS {name}", flush=True)

                missing = await post()
                assert missing.status_code == 400
                assert missing.json()["error"]["code"] == "invalid_infergate_key"
                record("missing_key", status=400)

                burst = [await post("rate") for _ in range(3)]
                assert [r.status_code for r in burst] == [200, 200, 429]
                other = await post("other")
                assert other.status_code == 200
                await asyncio.sleep(1.05)
                recovered = await post("rate")
                assert recovered.status_code == 200
                record("per_key_rate_and_recovery", burst=[200, 200, 429], other_key=200, after_refill=200)

                async with AsyncExitStack() as streams:
                    async def hold(name):
                        request = client.build_request(
                            "POST", BASE + "/v1/chat/completions",
                            headers={"X-InferGate-Key": name},
                            json={**payload, "stream": True, "acceptance_hold": name},
                        )
                        response = await client.send(request, stream=True)
                        streams.push_async_callback(response.aclose)
                        assert response.status_code == 200
                        lines = response.aiter_lines()
                        assert await anext(lines) == "data: first"
                        backend = response.headers["X-InferGate-Backend"]
                        return response, lines, f"http://127.0.0.1:{BACKENDS[backend]}"

                    first, first_lines, first_base = await hold("hold-one")
                    second, second_lines, second_base = await hold("hold-two")
                    full = await post("over-capacity")
                    assert full.status_code == 503
                    assert full.json()["error"]["code"] == "concurrency_limit_exceeded"
                    record("two_live_streams_reject_third_request", status=503)

                    released = await client.post(first_base + "/control/release/hold-one")
                    released.raise_for_status()
                    assert "data: [DONE]" in [line async for line in first_lines]
                    assert (await post("after-finish")).status_code == 200
                    record("capacity_after_normal_stream_finish", status=200)

                    await second.aclose()
                    deadline = time.monotonic() + 3
                    while True:
                        state = await client.get(second_base + "/control/closed/hold-two")
                        if state.json()["closed"]:
                            break
                        assert time.monotonic() < deadline, "Downstream stream remained open"
                        await asyncio.sleep(0.02)
                    # Both must enter together: one success alone would miss a leaked slot.
                    third, third_lines, third_base = await hold("after-disconnect-one")
                    fourth, fourth_lines, fourth_base = await hold("after-disconnect-two")
                    record("client_disconnect_closes_downstream_and_restores_both_slots", admitted=2)
                    for name, lines, backend_base in (
                        ("after-disconnect-one", third_lines, third_base),
                        ("after-disconnect-two", fourth_lines, fourth_base),
                    ):
                        response = await client.post(backend_base + "/control/release/" + name)
                        response.raise_for_status()
                        assert "data: [DONE]" in [line async for line in lines]

                # Advance the cursor so the next selection is A, while both are healthy.
                for i in range(2):
                    response = await post(f"align-{i}")
                    assert response.status_code == 200
                    if response.headers["X-InferGate-Backend"] == "backend-b":
                        break
                else:
                    raise AssertionError("Could not align round-robin cursor")
                stop(processes["backend-a"])
                fallback = await post("fallback")
                assert fallback.status_code == 200
                assert fallback.headers["X-InferGate-Backend"] == "backend-b"
                record("stale_healthy_a_connection_failure_falls_back_to_b", status=200, backend="backend-b")
                stop(processes["backend-b"])
                failed = await post("both-offline")
                assert failed.status_code == 502
                assert failed.json()["error"]["code"] == "backend_transport_failure"
                assert failed.headers["X-InferGate-Backend"] == "backend-b"
                record("both_connections_fail", status=502, last_backend="backend-b")
        except BaseException:
            for path in Path(temp).glob("*.log"):
                print(f"{path.name}:\n{path.read_text()[-3000:]}", file=sys.stderr)
            raise
        finally:
            for process in reversed(list(processes.values())):
                stop(process)
            for log in logs:
                log.close()
    evidence["all_child_processes_stopped"] = all(p.poll() is not None for p in processes.values())
    if output:
        Path(output).write_text(json.dumps(evidence, indent=2) + "\n")
    else:
        print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", choices=["gateway", "backend"])
    parser.add_argument("--port", type=int)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    else:
        asyncio.run(verify(args.output))
