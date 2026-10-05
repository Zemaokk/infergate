"""Verify real Prometheus/Jaeger/Grafana services using three owned gateway processes.

Requires the observability compose stack running and ports 8000-8002 free.
No container is created/stopped here; child application processes are always stopped.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import httpx
from verify_m2 import ROOT, serve as serve_backend, stop, wait_ready


async def eventually(check, timeout=20):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return await check()
        except (AssertionError, httpx.HTTPError, KeyError, IndexError) as exc:
            last_error = exc
            await asyncio.sleep(0.2)
    raise RuntimeError(f"Observation did not become available: {last_error}")


async def verify(output):
    for port in (8000, 8001, 8002):
        with socket.socket() as sock:
            sock.bind(("0.0.0.0", port))
    checks = []
    processes = []
    expected = {}
    evidence = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                "scope": "controlled local HTTP plus running compose observability services",
                "status": "running",
                "checks": checks}
    with tempfile.TemporaryDirectory(prefix="infergate-m3-") as temp:
        handles = []
        log_path = Path(temp) / "gateway.log"
        try:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                # Fail before starting application processes if the stack is absent.
                for name, url in [
                    ("prometheus", "http://127.0.0.1:9090/-/ready"),
                    ("grafana", "http://127.0.0.1:3000/api/health"),
                    ("jaeger", "http://127.0.0.1:16686/"),
                ]:
                    response = await client.get(url)
                    response.raise_for_status()
                    checks.append({"check": name + "_ready", "status": response.status_code})
                for mode, port in [("backend", 8001), ("backend", 8002), ("gateway", 8000)]:
                    handle = open(log_path if mode == "gateway" else Path(temp) / f"{port}.log", "w")
                    handles.append(handle)
                    env = dict(os.environ)
                    env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = "http://127.0.0.1:4318/v1/traces"
                    process = subprocess.Popen(
                        [sys.executable, str(Path(__file__).resolve()), "--serve", mode, "--port", str(port)],
                        cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT,
                    )
                    processes.append(process)
                    await wait_ready(client, f"http://127.0.0.1:{port}" + (
                        "/openapi.json" if mode == "gateway" else "/health"
                    ), process)
                base = "http://127.0.0.1:8000"
                payload = {"model": "mock-model", "messages": [{"role": "user", "content": "M3 acceptance"}]}

                def headers(name, outcome, attempts, include_key=True):
                    trace_id = uuid4().hex
                    expected[trace_id] = {"scenario": name, "outcome": outcome, "attempt_outcomes": attempts}
                    result = {"traceparent": f"00-{trace_id}-123456789abcdef0-01"}
                    if include_key:
                        result["X-InferGate-Key"] = uuid4().hex
                    return result

                response = await client.post(base + "/v1/chat/completions", json=payload,
                    headers=headers("normal", "completed", ["completed"]))
                assert response.status_code == 200
                response = await client.post(base + "/v1/chat/completions", json={**payload, "stream": True},
                    headers=headers("stream", "completed", ["completed"]))
                assert response.status_code == 200 and "[DONE]" in response.text
                # Keep this process alive across scrapes so rate panels have two
                # samples and an actual increment, rather than a single snapshot.
                await asyncio.sleep(6)
                response = await client.post(base + "/v1/chat/completions", json=payload,
                    headers=headers("normal_after_scrape", "completed", ["completed"]))
                assert response.status_code == 200
                response = await client.post(base + "/v1/chat/completions", json={**payload, "stream": True},
                    headers=headers("stream_after_scrape", "completed", ["completed"]))
                assert response.status_code == 200 and "[DONE]" in response.text
                response = await client.post(base + "/v1/chat/completions", json=payload,
                    headers=headers("rejected", "rejected", [], include_key=False))
                assert response.status_code == 400
                async with client.stream("POST", base + "/v1/chat/completions",
                    json={**payload, "stream": True, "acceptance_hold": "m3-cancel"},
                    headers=headers("cancelled_stream", "cancelled", ["cancelled"])) as response:
                    assert response.status_code == 200
                    assert await anext(response.aiter_lines()) == "data: first"
                    cancelled_backend = response.headers["X-InferGate-Backend"]

                async def closed():
                    port = 8001 if cancelled_backend == "backend-a" else 8002
                    response = await client.get(f"http://127.0.0.1:{port}/control/closed/m3-cancel")
                    assert response.json()["closed"]
                await eventually(closed)

                # Align next selection to A; stop only our process, preserving stale health.
                for index in range(2):
                    response = await client.post(base + "/v1/chat/completions", json=payload,
                        headers=headers(f"align_{index}", "completed", ["completed"]))
                    assert response.status_code == 200
                    if response.headers["X-InferGate-Backend"] == "backend-b":
                        break
                else:
                    raise AssertionError("Could not align fallback selection")
                stop(processes[0])
                response = await client.post(base + "/v1/chat/completions", json=payload,
                    headers=headers("fallback", "completed", ["transport_error", "completed"]))
                assert response.status_code == 200 and response.headers["X-InferGate-Backend"] == "backend-b"
                stop(processes[1])
                response = await client.post(base + "/v1/chat/completions", json=payload,
                    headers=headers("both_offline", "transport_error", ["transport_error", "transport_error"]))
                assert response.status_code == 502

                async def log_records():
                    records = []
                    for line in log_path.read_text().splitlines():
                        if line.startswith("{"):
                            record = json.loads(line)
                            if record.get("event") == "request_finished":
                                records.append(record)
                    assert {r["trace_id"] for r in records} == set(expected)
                    return records
                records = await eventually(log_records)
                for record in records:
                    prediction = expected[record["trace_id"]]
                    assert record["outcome"] == prediction["outcome"]
                    assert [a["outcome"] for a in record["backend_attempts"]] == prediction["attempt_outcomes"]

                    async def trace_record():
                        # Jaeger's UI API is intentionally version-specific to the pinned image.
                        response = await client.get("http://127.0.0.1:16686/api/traces/" + record["trace_id"])
                        response.raise_for_status()
                        spans = response.json()["data"][0]["spans"]
                        assert len(spans) == 1 + record["attempt_count"]
                        return spans
                    spans = await eventually(trace_record)
                    root = next(s for s in spans if s["spanID"] == record["span_id"])
                    assert {t["key"]: t["value"] for t in root["tags"]}["infergate.outcome"] == record["outcome"]
                    for attempt in record["backend_attempts"]:
                        span = next(s for s in spans if s["spanID"] == attempt["span_id"])
                        assert any(r["spanID"] == root["spanID"] and r["refType"] == "CHILD_OF" for r in span["references"])
                        assert {t["key"]: t["value"] for t in span["tags"]}["infergate.outcome"] == attempt["outcome"]
                    checks.append({"check": prediction["scenario"], "trace_id": record["trace_id"],
                                   "span_count": len(spans), "outcome": record["outcome"]})

                async def query(expression):
                    response = await client.get("http://127.0.0.1:9090/api/v1/query", params={"query": expression})
                    response.raise_for_status()
                    result = response.json()
                    assert result["status"] == "success" and result["data"]["result"]
                    return float(result["data"]["result"][0]["value"][1])

                async def metrics_match():
                    assert await query('up{job="infergate"}') == 1
                    requests = await query('sum(infergate_requests_total{job="infergate"})')
                    attempts = await query('sum(infergate_backend_attempts_total{job="infergate"})')
                    assert requests == len(records)
                    assert attempts == sum(r["attempt_count"] for r in records)
                    assert await query('infergate_active_requests{job="infergate"}') == 0
                    # Transport failures do not update routing health; probing
                    # is deliberately paused during this controlled scenario.
                    assert await query('sum(infergate_backend_healthy{job="infergate"})') == 2
                    return {"requests": requests, "attempts": attempts,
                            "active_requests": 0, "routing_healthy_backends": 2}
                checks.append({"check": "prometheus_matches_logs", **await eventually(metrics_match)})
                response = await client.get("http://127.0.0.1:3000/api/dashboards/uid/infergate-m3",
                    auth=("admin", "infergate-local"))
                response.raise_for_status()
                dashboard = response.json()["dashboard"]
                assert dashboard["uid"] == "infergate-m3"
                checks.append({"check": "grafana_dashboard_provisioned", "panels": len(dashboard["panels"])})
                evidence["completion_records"] = records
                evidence["status"] = "passed"
        except BaseException as exc:
            evidence["status"] = "failed"
            evidence["error_type"] = type(exc).__name__
            raise
        finally:
            for process in reversed(processes):
                stop(process)
            for handle in handles:
                handle.close()
            evidence["all_application_processes_stopped"] = all(p.poll() is not None for p in processes)
            Path(output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", choices=["gateway", "backend"])
    parser.add_argument("--port", type=int)
    parser.add_argument("--output", default="/tmp/infergate-m3-evidence.json")
    args = parser.parse_args()
    if args.serve == "gateway":
        import uvicorn
        from infergate.runtime import create_runtime_app
        uvicorn.run(create_runtime_app(probe_interval_seconds=3600), host="0.0.0.0", port=args.port,
            log_config=json.loads((ROOT / "configs/logging.json").read_text()))
    elif args.serve == "backend":
        serve_backend("backend", args.port)
    else:
        asyncio.run(verify(args.output))


if __name__ == "__main__":
    main()
