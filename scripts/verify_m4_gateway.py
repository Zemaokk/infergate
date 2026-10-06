"""Verify the dedicated remote M4 gateway; briefly stop its owned vLLM process."""

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def wait_for(check, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.5)
    raise TimeoutError("Verification condition did not become true")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, default=Path("/root/infergate-m4"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.work_root
    model = "Qwen2.5-7B-Instruct"
    payload = {"model": model, "messages": [{"role": "user", "content": "Explain an HTTP gateway briefly."}], "max_tokens": 64, "temperature": 0}
    evidence = {"started_at": datetime.now(timezone.utc).isoformat(), "model": model, "backend_count": 1, "unused_b_url": "", "requests": {}}
    backend_stopped = False
    log_offset = (root / "gateway.log").stat().st_size

    def start_backend():
        env = {**os.environ, "M4_WORK_ROOT": str(root), "M4_MODEL_PATH": "/root/shared-nvme/infergate-m4/models/Qwen2.5-7B-Instruct"}
        with (root / "backend.log").open("ab") as log:
            process = subprocess.Popen(["bash", str(root / "start_m4_backend.sh")], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        (root / "backend.pid").write_text(f"{process.pid}\n")
        evidence["restarted_backend_pid"] = process.pid

    try:
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=120, trust_env=False) as gateway, httpx.Client(base_url="http://127.0.0.1:8001", timeout=2, trust_env=False) as backend:
            def metrics():
                response = gateway.get("/metrics")
                response.raise_for_status()
                return response.text

            def healthy(expected):
                value = metrics()
                assert 'backend="backend-b"' not in value
                return f'infergate_backend_healthy{{backend="backend-a"}} {expected}.0' in value

            def backend_ready():
                try:
                    return backend.get("/health").status_code == 200
                except httpx.TransportError:
                    return False

            def post(name, body=payload):
                response = gateway.post("/v1/chat/completions", json=body, headers={"X-InferGate-Key": f"m4-verification-{name}"})
                evidence["requests"][name] = {"status": response.status_code, "body": response.json()}
                return response

            wait_for(lambda: healthy(1), 15)
            evidence["metrics_before"] = metrics()
            assert "infergate_active_requests 0.0" in evidence["metrics_before"]
            response = post("normal")
            response.raise_for_status()
            assert response.json()["model"] == model
            assert response.json()["choices"][0]["message"]["content"]
            events, content, done = [], [], False
            with gateway.stream("POST", "/v1/chat/completions", json={**payload, "stream": True}, headers={"X-InferGate-Key": "m4-verification-stream"}) as response:
                response.raise_for_status()
                assert response.headers["content-type"].startswith("text/event-stream")
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    value = line[6:]
                    if value == "[DONE]":
                        assert not done
                        done = True
                        continue
                    assert not done
                    event = json.loads(value)
                    assert event["model"] == model
                    events.append(event)
                    content.extend(choice.get("delta", {}).get("content") or "" for choice in event["choices"])
            assert done and events and "".join(content)
            evidence["requests"]["stream"] = {"status": 200, "events": events, "done": done, "text": "".join(content)}
            assert post("unknown_model", {**payload, "model": "mock-model"}).status_code == 503
            wait_for(lambda: "infergate_active_requests 0.0" in metrics(), 5)
            pid = int((root / "backend.pid").read_text())
            command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
            assert str(root / "vllm-env/bin/vllm") in command and model in command
            evidence["stopped_backend_pid"] = pid
            os.kill(pid, signal.SIGTERM)
            backend_stopped = True
            wait_for(lambda: not backend_ready(), 30)
            # The regular five-second health round may already have run: retain the observed race.
            immediate = post("immediate_after_stop")
            assert immediate.status_code in (502, 503)
            wait_for(lambda: healthy(0), 15)
            assert post("after_unhealthy_probe").status_code == 503
            evidence["metrics_unhealthy"] = metrics()
            def old_process_exited():
                stat = Path(f"/proc/{pid}/stat")
                return not stat.exists() or stat.read_text().split(")", 1)[1].split()[0] == "Z"
            wait_for(old_process_exited, 30)
            start_backend()
            backend_stopped = False
            wait_for(backend_ready)
            wait_for(lambda: healthy(1), 15)
            response = post("after_recovery")
            response.raise_for_status()
            assert response.json()["model"] == model
            assert response.json()["choices"][0]["message"]["content"]
            wait_for(lambda: "infergate_active_requests 0.0" in metrics(), 5)
            evidence["metrics_after"] = metrics()
            def read_records():
                with (root / "gateway.log").open() as log:
                    log.seek(log_offset)
                    records = []
                    for line in log:
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if record.get("event") == "request_finished":
                            records.append(record)
                return records
            wait_for(lambda: len(read_records()) >= len(evidence["requests"]), 5)
            records = read_records()
            evidence["completion_logs"] = records
            # Sequential requests on a dedicated gateway; reject extra traffic rather than misassociate logs.
            assert len(records) == len(evidence["requests"])
            for request, record in zip(evidence["requests"].values(), records, strict=True):
                request["completion_request_id"] = record["request_id"]
                assert record["status_code"] == request["status"]
                assert record["attempt_count"] == (0 if request["status"] == 503 else 1)
                assert record["reason"] == ("no_backend_available" if request["status"] == 503 else "backend_transport_failure" if request["status"] == 502 else None)
                assert not record["cleanup_failed"]
                assert all(row["backend_id"] == "backend-a" for row in record["backend_attempts"])
            evidence["status"] = "passed"
    except Exception as exc:
        evidence.update(status="failed", error=str(exc))
        raise
    finally:
        if backend_stopped:
            start_backend()
            evidence["restoration_started_after_failure"] = True
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(f"Passed; evidence: {args.output}")


if __name__ == "__main__":
    main()
