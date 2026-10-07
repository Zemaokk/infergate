"""Native real-model HTTP benchmark; run on the GPU host, never through SSH forwarding."""

import argparse
import asyncio
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import httpx

from .client import PAYLOAD, closed_loop, summarize
from .run import ROOT, aggregate, completion_records, service, state, write_json


PROMPT = PAYLOAD["messages"][0]["content"]


def response_text(body, protocol):
    if protocol == "chat":
        return body["choices"][0]["message"]["content"]
    return "".join(content.get("text", "") for item in body["output"]
                   if item.get("type") == "message" for content in item["content"]
                   if content.get("type") == "output_text")


def generated(body, protocol, model):
    try:
        if body["model"] != model or not response_text(body, protocol).strip():
            return False
        if protocol == "chat":
            # Reaching a requested output budget is a completed HTTP generation, too.
            return (body["object"] == "chat.completion" and
                    body["choices"][0]["finish_reason"] in ("stop", "length"))
        return (body["object"] == "response" and body["status"] == "completed"
                and ("store" not in body or body["store"] is False))
    except (KeyError, IndexError, TypeError, AttributeError):
        return False


def response_metadata(body, protocol):
    try:
        text = response_text(body, protocol)
        length = len(text)
    except (KeyError, IndexError, TypeError, AttributeError):
        length = None
    return {"output_characters": length, "response_body": body}


def payload(protocol, model):
    if protocol == "chat":
        return {"model": model, "messages": [{"role": "user", "content": PROMPT}],
                "stream": False, "max_tokens": 64, "temperature": 0}
    return {"model": model, "input": PROMPT, "store": False, "max_output_tokens": 64}


def validate_case(rows, records, gateway_state):
    issues = []
    for row in rows:
        if not row["valid_response"]:
            issues.append(f"invalid response at sequence {row['sequence']}: "
                          f"status={row['status']}, code={row['error_code']}, "
                          f"exception={row['client_exception']}")
        if records is not None:
            record = records.get(row["trace_id"])
            if (record is None or record["attempt_count"] != 1 or record["status_code"] != 200
                    or record["cleanup_failed"] or record["outcome"] != "completed"
                    or record["route"] != ("/v1/chat/completions" if row["protocol"] == "chat" else "/v1/responses")):
                issues.append(f"completion log mismatch at sequence {row['sequence']}")
    if gateway_state["active"] != 0 or not gateway_state["healthy"]:
        issues.append("gateway was not healthy and idle after the case")
    return issues


async def measure(args, output):
    cases = []
    async with httpx.AsyncClient(timeout=120, trust_env=False,
                                 limits=httpx.Limits(max_connections=32, max_keepalive_connections=32)) as client:
        health = await client.get(args.backend + "/health")
        health.raise_for_status()
        schema = await client.get(args.backend + "/openapi.json")
        schema.raise_for_status()
        if not all(path in schema.json()["paths"] for path in ("/v1/chat/completions", "/v1/responses")):
            raise ValueError("Backend does not advertise both native protocols")
        backend_version = await client.get(args.backend + "/version")
        backend_version.raise_for_status()
        write_json(output / "backend-version.json", backend_version.json())
        async with service(output, "gateway-real", "gateway", "--backend-url", args.backend,
                           "--model", args.model, "--limit", 2) as gateway:
            for repetition in range(1 if args.profile == "pilot" else 3):
                for protocol in ("chat", "responses"):
                    path = "/v1/chat/completions" if protocol == "chat" else "/v1/responses"
                    for concurrency in (1, 2):
                        targets = ("direct", "gateway") if repetition % 2 == 0 else ("gateway", "direct")
                        for target in targets:
                            case = f"real-r{repetition}-{protocol}-c{concurrency}-{target}"
                            url = args.backend if target == "direct" else gateway["url"]
                            options = {"payload": payload(protocol, args.model), "path": path,
                                       "validator": lambda body: generated(body, protocol, args.model),
                                       "metadata": lambda body: response_metadata(body, protocol)}
                            def save_record(row, *, warmup=False):
                                row.update(group="real", protocol=protocol, target=target,
                                           repetition=repetition, concurrency=concurrency, warmup=warmup)
                                name = "warmup.jsonl" if warmup else "requests.jsonl"
                                with (output / name).open("a") as stream:
                                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                            warmed = await closed_loop(
                                client, url, case + "-warmup", concurrency, 2 if args.profile == "pilot" else 5,
                                **options, on_record=lambda row: save_record(row, warmup=True))
                            if not all(row["valid_response"] for row in warmed):
                                raise RuntimeError(f"Warmup failed: {case}; raw warmup data retained")
                            rows = await closed_loop(client, url, case, concurrency,
                                                     4 if args.profile == "pilot" else 50,
                                                     **options, on_record=save_record)
                            records = (await completion_records(gateway["log"], {r["trace_id"] for r in rows})
                                       if target == "gateway" else None)
                            after = await state(client, gateway)
                            issues = validate_case(rows, records, after)
                            # Reuse aggregation by giving protocols distinct groups.
                            result = {"case": case, "group": f"real-{protocol}", "protocol": protocol,
                                      "target": target, "repetition": repetition,
                                      "concurrency": concurrency, "offered_rate_per_key": None,
                                      "key_count": 1, **summarize(rows), "valid_case": not issues,
                                      "issues": issues, "gateway_state_after": after}
                            write_json(output / f"{case}.json", result)
                            cases.append(result)
                            write_json(output / "summary.json", {"cases": cases,
                                       "aggregate": aggregate(cases), "all_valid": all(c["valid_case"] for c in cases)})
                            print(f"{case}: {result['success']}/{result['issued']} success; "
                                  f"p95={result['success_p95_seconds']}s; valid={not issues}", flush=True)
                            if issues:
                                raise RuntimeError(f"Invalid case: {case}; fix before further GPU measurements")
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="http://127.0.0.1:8002")
    parser.add_argument("--model", default="Qwen2.5-7B-Instruct")
    parser.add_argument("--profile", choices=("pilot", "real"), default="pilot")
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = httpx.URL(args.backend)
    if url.scheme != "http" or url.host != "127.0.0.1" or url.userinfo or url.query or url.fragment or url.path not in ("", "/"):
        raise ValueError("Run on GPU host with a numeric loopback backend URL")
    args.backend = args.backend.rstrip("/")
    environment = json.loads(args.environment.read_text())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    import infergate
    installed = Path(infergate.__file__).parent
    sources = [*(ROOT / "scripts/m4_benchmark").glob("*.py"),
               ROOT / "configs/logging.json", *[p for p in installed.glob("*.py") if not p.name.startswith("._")]]
    manifest = {"profile": args.profile, "scope": "real native nonstreaming HTTP; repeated warm prompt",
                "started_utc": datetime.now(timezone.utc).isoformat(), "command": sys.argv,
                "python": sys.version, "platform": platform.platform(), "environment": environment,
                "client_timeout_seconds": 120, "client_pool": 32, "otlp_export": False,
                "gateway_limit": 2, "key_capacity": 100000, "key_refill_rate": 100000,
                "payloads": {p: payload(p, args.model) for p in ("chat", "responses")},
                "backend_timeout_seconds": {"connect": 5, "pool": 5, "write": 30, "read": 30},
                "packages": {name: version(name) for name in ("infergate", "fastapi", "httpx", "uvicorn")},
                "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    for source in sources:
        relative = (Path("installed-infergate") / source.name if source.parent == installed
                    else source.relative_to(ROOT))
        destination = output / "sources" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    write_json(output / "manifest.json", manifest)
    try:
        cases = asyncio.run(measure(args, output))
        manifest["outcome"] = "passed" if all(c["valid_case"] for c in cases) else "invalid_cases"
    except BaseException as exc:
        manifest["outcome"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        manifest["exception_class"] = type(exc).__name__
        raise
    finally:
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["source_changed_during_run"] = [str(p) for p in sources
            if hashlib.sha256(p.read_bytes()).hexdigest() != manifest["source_sha256"][str(p)]]
        write_json(output / "manifest.json", manifest)
    if manifest["outcome"] != "passed" or manifest["source_changed_during_run"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
