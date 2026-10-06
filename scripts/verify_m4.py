"""Build and verify an isolated three-container mock stack, then remove it."""

import argparse
import asyncio
import json
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REQUEST = {"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]}


async def verify(client, compose, evidence):
    sequence = 0

    async def request(stream=False):
        nonlocal sequence
        sequence += 1
        return await client.post(
            "/v1/chat/completions",
            json={**REQUEST, "stream": stream},
            headers={"X-InferGate-Key": f"m4-check-{sequence}"},
        )

    async def wait_health(a, b):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = await client.get("/metrics")
            response.raise_for_status()
            values = {}
            for line in response.text.splitlines():
                for name in ("backend-a", "backend-b"):
                    if line.startswith(f'infergate_backend_healthy{{backend="{name}"}} '):
                        values[name] = float(line.split()[-1])
            if values == {"backend-a": a, "backend-b": b}:
                evidence.setdefault("health_states", []).append(values)
                return
            await asyncio.sleep(0.2)
        raise AssertionError(f"Health state did not reach A={a}, B={b}")

    await wait_health(1, 1)
    routed = []
    for _ in range(4):
        response = await request()
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == (
            "This response came from the mock backend."
        )
        routed.append(response.headers["X-InferGate-Backend"])
    assert routed == ["backend-a", "backend-b"] * 2
    evidence["round_robin"] = routed

    sequence += 1
    blocks = []
    arrival = []
    started = time.monotonic()
    async with client.stream(
        "POST", "/v1/chat/completions", json={**REQUEST, "stream": True},
        headers={"X-InferGate-Key": f"m4-check-{sequence}"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for chunk in response.aiter_bytes():
            if chunk:
                blocks.append(chunk)
                arrival.append(time.monotonic() - started)
    expected = (
        b'data: {"id":"chatcmpl-mock-001","object":"chat.completion.chunk",'
        b'"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        b'data: [DONE]\n\n'
    )
    assert b"".join(blocks) == expected
    assert len(blocks) >= 2 and b"[DONE]" not in blocks[0]
    evidence["stream"] = {"body_preserved": True, "chunk_arrival_seconds": arrival}

    await asyncio.to_thread(compose, "stop", "backend-a")
    await wait_health(0, 1)
    peers = []
    for _ in range(3):
        response = await request()
        assert response.status_code == 200
        peers.append(response.headers["X-InferGate-Backend"])
    assert peers == ["backend-b"] * 3
    evidence["a_stopped_routes"] = peers

    await asyncio.to_thread(compose, "start", "backend-a")
    await wait_health(1, 1)
    restored = []
    for _ in range(2):
        response = await request()
        assert response.status_code == 200
        restored.append(response.headers["X-InferGate-Backend"])
    assert set(restored) == {"backend-a", "backend-b"}
    evidence["restored_routes"] = restored

    await asyncio.to_thread(compose, "stop", "backend-a", "backend-b")
    await wait_health(0, 0)
    response = await request()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "no_backend_available"
    evidence["all_stopped"] = {"status": 503, "code": "no_backend_available"}
    response = await client.get("/metrics")
    assert "infergate_active_requests 0.0" in response.text
    evidence["active_requests_final"] = 0
    evidence["request_count"] = sequence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", default="infergate-m4-verify")
    args = parser.parse_args()

    def compose(*commands):
        return subprocess.run(
            ["docker", "compose", "-f", str(ROOT / "compose.yaml"),
             "-p", args.project, *commands],
            cwd=ROOT, check=True, capture_output=True, text=True, timeout=300,
        ).stdout

    # Never stop an existing stack or an unrelated service on the published port.
    if compose("ps", "--all", "--quiet").strip():
        raise RuntimeError("Verification project already has containers; use another --project")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8000))
    evidence = {"started_at": datetime.now(timezone.utc).isoformat(), "project": args.project}
    cleanup_needed = False
    try:
        cleanup_needed = True
        print("Building and starting mock stack", flush=True)
        compose("up", "--build", "-d", "--wait", "--wait-timeout", "90")
        evidence["containers"] = compose("ps", "--format", "json")
        evidence["installed_runtime"] = compose(
            "exec", "-T", "gateway", "python", "-c",
            "import os, sys, infergate; from pathlib import Path; "
            "assert os.getuid() == 10001; "
            "assert 'site-packages' in infergate.__file__; "
            "assert not Path('/app/src').exists(); "
            "print(os.getuid(), sys.version, infergate.__file__)",
        ).strip()
        evidence["image"] = json.loads(subprocess.check_output(
            ["docker", "image", "inspect", "infergate:m4-dev"], text=True,
        ))[0]
        async def run():
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", trust_env=False, timeout=10) as client:
                await verify(client, compose, evidence)
        asyncio.run(run())
        evidence["status"] = "passed"
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            evidence["command_stderr"] = exc.stderr
        raise
    finally:
        try:
            if cleanup_needed:
                evidence["completion_logs"] = compose("logs", "--no-color", "gateway")
        finally:
            try:
                if cleanup_needed:
                    compose("down", "--timeout", "15")
                    evidence["cleaned_up"] = True
            finally:
                evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(f"Passed; evidence: {args.output}")


if __name__ == "__main__":
    main()
