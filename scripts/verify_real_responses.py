"""Verify native Responses directly and through InferGate; not a benchmark."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from prometheus_client.parser import text_string_to_metric_families


def snapshot(response):
    return {"status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "body": response.text}


def assert_generated(response, model):
    response.raise_for_status()
    value = response.json()
    assert value["object"] == "response"
    assert value["model"] == model
    # Some native backends omit this response field; request intent is explicit.
    if "store" in value:
        assert value["store"] is False
    assert any(content.get("text", "").strip()
               for item in value["output"] if item["type"] == "message"
               for content in item["content"] if content["type"] == "output_text")


def verify(backend, gateway, model, evidence):
    manifest = backend.get("/openapi.json")
    manifest.raise_for_status()
    assert "post" in manifest.json()["paths"]["/v1/responses"]
    evidence["backend_declares_responses"] = True
    version = backend.get("/version")
    version.raise_for_status()
    evidence["backend_version"] = version.json()
    payload = {"model": model, "input": "Briefly explain what an HTTP gateway does.",
               "store": False, "max_output_tokens": 64}
    evidence["payload"] = payload
    response = backend.post("/v1/responses", json=payload)
    evidence["direct"] = snapshot(response)
    assert_generated(response, model)
    evidence["gateway_responses"] = []
    for index, optional in enumerate(({}, {"instructions": None, "stream": False, "background": False})):
        response = gateway.post("/v1/responses", json={**payload, **optional},
                                headers={"X-InferGate-Key": f"m43-response-{index}"})
        evidence["gateway_responses"].append(snapshot(response))
        assert_generated(response, model)
    evidence["rejections"] = []
    for invalid in ({"store": True}, {"stream": True}, {"input": "   "},
                    {"previous_response_id": "unsupported"}):
        response = gateway.post("/v1/responses", json={**payload, **invalid})
        evidence["rejections"].append(snapshot(response))
        assert response.status_code == 400
        assert response.json()["error"]["message"] == "Invalid request body."
    response = gateway.post("/v1/chat/completions", headers={"X-InferGate-Key": "m43-chat"}, json={
        "model": model, "messages": [{"role": "user", "content": "Say hello."}],
        "max_tokens": 32,
    })
    evidence["chat_regression"] = snapshot(response)
    response.raise_for_status()
    assert response.json()["choices"][0]["message"]["content"].strip()
    metrics = gateway.get("/metrics")
    metrics.raise_for_status()
    evidence["metrics"] = metrics.text
    samples = [sample for family in text_string_to_metric_families(metrics.text)
               for sample in family.samples]
    active, = [s.value for s in samples if s.name == "infergate_active_requests"]
    assert active == 0
    rejected, = [s.value for s in samples if s.name == "infergate_requests_total"
                 and s.labels == {"route": "/v1/responses", "status": "400",
                                  "outcome": "rejected", "reason": "invalid_request_body"}]
    assert rejected == 4  # Run against a fresh dedicated gateway.


def verify_logs(path, offset, evidence):
    deadline = time.monotonic() + 5
    while True:
        with path.open() as log:
            log.seek(offset)
            records = []
            for line in log:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("event") == "request_finished":
                    records.append(record)
        if len(records) >= 7 or time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    evidence["completion_logs"] = records
    assert len(records) == 7
    for record, status, attempts in zip(records, [200, 200, 400, 400, 400, 400, 200],
                                        [1, 1, 0, 0, 0, 0, 1]):
        assert record["status_code"] == status
        assert record["attempt_count"] == attempts
        assert record["cleanup_failed"] is False
        assert record["first_byte_sec"] is None
        assert record["route"] == ("/v1/responses" if record is not records[-1]
                                    else "/v1/chat/completions")
        if status == 400:
            assert record["reason"] == "invalid_request_body"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8002")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8003")
    parser.add_argument("--model", default="Qwen2.5-7B-Instruct")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gateway-log", type=Path)
    args = parser.parse_args()
    evidence = {"started_at": datetime.now(timezone.utc).isoformat(),
                "model": args.model, "backend_url": args.backend_url,
                "gateway_url": args.gateway_url}
    log_offset = args.gateway_log.stat().st_size if args.gateway_log else None
    try:
        with httpx.Client(base_url=args.backend_url, timeout=120, trust_env=False) as backend:
            with httpx.Client(base_url=args.gateway_url, timeout=120, trust_env=False,
                             headers={"X-InferGate-Key": "m43-verification"}) as gateway:
                verify(backend, gateway, args.model, evidence)
        if args.gateway_log:
            verify_logs(args.gateway_log, log_offset, evidence)
        evidence["status"] = "passed"
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = str(exc)
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(f"Passed; evidence: {args.output}")


if __name__ == "__main__":
    main()
