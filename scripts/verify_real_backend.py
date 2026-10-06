"""Check a real Chat Completions backend directly; this is not a benchmark."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--model", default="Qwen2.5-7B-Instruct")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = {"started_at": datetime.now(timezone.utc).isoformat(), "model": args.model}
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": "Briefly explain what an HTTP gateway does."}],
        "temperature": 0, "max_tokens": 64,
    }
    try:
        with httpx.Client(base_url=args.base_url, timeout=120, trust_env=False) as client:
            health = client.get("/health")
            health.raise_for_status()
            evidence["health_status"] = health.status_code
            models = client.get("/v1/models")
            models.raise_for_status()
            evidence["models"] = models.json()
            assert args.model in {row["id"] for row in models.json()["data"]}
            response = client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            evidence["non_streaming"] = response.json()
            assert response.json()["model"] == args.model
            assert response.json()["choices"][0]["message"]["content"]
            events, arrival, content, done = [], [], [], False
            started = time.monotonic()
            with client.stream("POST", "/v1/chat/completions", json={**payload, "stream": True}) as response:
                response.raise_for_status()
                assert response.headers["content-type"].startswith("text/event-stream")
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    value = line[6:]
                    if value == "[DONE]":
                        done = True
                        continue
                    assert not done
                    event = json.loads(value)
                    assert event["model"] == args.model
                    events.append(event)
                    arrival.append(time.monotonic() - started)
                    for choice in event["choices"]:
                        content.append(choice.get("delta", {}).get("content") or "")
            assert done and events and "".join(content)
            evidence["streaming"] = {
                "events": events, "done": done, "text": "".join(content),
                "client_event_arrival_seconds": arrival,
            }
        evidence["status"] = "passed"
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = str(exc)
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(f"Passed; evidence: {args.output}")


if __name__ == "__main__":
    main()
