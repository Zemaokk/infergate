"""Run local M4 experiments: python -m scripts.m4_benchmark.run --profile pilot."""

import argparse
import asyncio
import json
import hashlib
import os
import platform
import signal
import socket
import statistics
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import httpx

from .client import PAYLOAD, closed_loop, fixed_rate, request, summarize, waves

ROOT = Path(__file__).resolve().parents[2]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@asynccontextmanager
async def service(directory, name, role, *options):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    log_path = directory / f"{name}.log"
    command = [sys.executable, "-m", "scripts.m4_benchmark.server", role,
               "--fd", str(listener.fileno()), *map(str, options)]
    process = None
    with log_path.open("w") as log:
        try:
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log,
                                       pass_fds=(listener.fileno(),))
            listener.close()
            async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                for _ in range(300):
                    if process.poll() is not None:
                        raise RuntimeError(f"{name} exited; see {log_path}")
                    try:
                        response = await client.get(url + "/bench/state")
                        if response.status_code == 200:
                            state = response.json()
                            if role == "mock" or state.get("healthy"):
                                break
                    except httpx.RequestError:
                        pass
                    await asyncio.sleep(0.1)
                else:
                    raise RuntimeError(f"{name} readiness timed out; see {log_path}")
            yield {"url": url, "log": log_path, "command": command,
                   "pid": process.pid}
        finally:
            listener.close()
            if process is not None and process.poll() is None:
                # Only stop a child this context created; never reuse an old PID.
                process.send_signal(signal.SIGTERM)
                try:
                    await asyncio.to_thread(process.wait, 10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait)


async def state(client, service):
    response = await client.get(service["url"] + "/bench/state")
    response.raise_for_status()
    return response.json()


async def completion_records(path, trace_ids):
    # Response bytes may reach the client just before middleware finalizes its log.
    found = {}
    for _ in range(100):
        for line in path.read_text().splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and value.get("trace_id") in trace_ids:
                found[value["trace_id"]] = value
        if len(found) == len(trace_ids):
            return found
        await asyncio.sleep(0.02)
    return found


def quota_issues(rows, gateway_state):
    """Check observed HTTP decisions against refill at server decision timestamps."""
    issues = []
    buckets = {}
    events = gateway_state.get("quota_events", [])
    for event in events:
        key, now = event["key_alias"], event["checked_at"]
        tokens, previous = buckets.get(key, (gateway_state["capacity"], now))
        available = min(gateway_state["capacity"], tokens + (now - previous) * gateway_state["rate"])
        allowed = available >= 1
        remaining = available - int(allowed)
        if event["allowed"] != allowed or abs(event["tokens_after"] - remaining) > 1e-6:
            issues.append(f"quota decision violates refill contract for {key}")
        buckets[key] = (remaining, now)
    for key in {r["key_alias"] for r in rows}:
        observations = [r for r in rows if r["key_alias"] == key]
        decisions = [e for e in events if e["key_alias"] == key]
        if len(observations) != len(decisions):
            issues.append(f"quota observation count mismatch for {key}")
        elif sum(e["allowed"] for e in decisions) != sum(r["status"] != 429 for r in observations):
            issues.append(f"HTTP result differs from quota decisions for {key}")
    return issues


def validate(rows, group, records, before_backend, after_backend, gateway_state):
    issues = []
    success = sum(r["valid_response"] for r in rows)
    expected = {"overhead": set(), "waves": {(503, "concurrency_limit_exceeded")},
                "rate": {(429, "rate_limit_exceeded")},
                "order": {(503, "concurrency_limit_exceeded"),
                          (429, "rate_limit_exceeded")}}[group]
    for row in rows:
        if not row["valid_response"] and (row["status"], row["error_code"]) not in expected:
            issues.append(f"unexpected response at sequence {row['sequence']}")
        if records is not None:
            log = records.get(row["trace_id"])
            if log is None:
                issues.append(f"missing completion at sequence {row['sequence']}")
            elif (log["status_code"] != row["status"] or log["cleanup_failed"]
                  or log["attempt_count"] != (1 if row["valid_response"] else 0)):
                issues.append(f"completion mismatch at sequence {row['sequence']}")
    if after_backend["calls"] - before_backend["calls"] != success:
        issues.append("backend call delta differs from valid successes")
    if after_backend["active"] != 0 or gateway_state["active"] != 0:
        issues.append("active requests did not return to zero")
    if group in ("rate", "order"):
        issues.extend(quota_issues(rows, gateway_state))
    return issues


async def save_case(directory, client, *, case, group, target, gateway, backend,
                    mode, concurrency=1, count=1, rate=None, seconds=None,
                    keys=("key-a",), repetition=0, warmup=0):
    url = backend["url"] if target == "direct" else gateway["url"]
    if warmup:
        warmed = await closed_loop(client, url, case + "-warmup", concurrency, warmup)
        if not all(r["valid_response"] for r in warmed):
            raise RuntimeError(f"Warmup failed for {case}; server logs retained")
    before = await state(client, backend)
    extra, missed = {}, []
    if mode == "closed":
        rows = await closed_loop(client, url, case, concurrency, count)
    elif mode == "waves":
        rows = await waves(client, url, case, concurrency, count)
    else:
        rows, missed, extra = await fixed_rate(client, url, case, rate, seconds, keys)
    # Save raw data before validation so failed rounds remain inspectable.
    with (directory / "requests.jsonl").open("a") as stream:
        for row in rows:
            row.update(group=group, target=target, repetition=repetition,
                       concurrency=concurrency, offered_rate_per_key=rate)
            stream.write(json.dumps(row) + "\n")
    with (directory / "missed.jsonl").open("a") as stream:
        for row in missed:
            stream.write(json.dumps(row) + "\n")
    records = (await completion_records(gateway["log"], {r["trace_id"] for r in rows})
               if target == "gateway" else None)
    after = await state(client, backend)
    gateway_state = await state(client, gateway)
    issues = validate(rows, group, records, before, after, gateway_state)
    if missed or any((r["scheduling_lag_seconds"] or 0) > 0.1 for r in rows):
        issues.append("arrival scheduler missed or delayed planned requests by >100ms")
    # Prove post-wave recovery; use a different key, exclude this diagnostic from metrics.
    recovery = None
    if group == "waves":
        recovery = await request(client, gateway["url"], case=case + "-recovery",
                                 sequence=0, key="recovery")
        if not recovery["valid_response"]:
            issues.append("post-wave recovery request failed")
        if after["max_active"] > 2:
            issues.append("slow backend observed more than two simultaneous requests")
        expected_waves = sum(
            sum(r["valid_response"] for r in rows if r["wave"] == wave)
            == min(concurrency, 2) for wave in range(count))
        extra["waves_with_expected_split"] = expected_waves
        extra["waves_total"] = count
        if expected_waves != count:
            issues.append("some waves did not exhibit the intended overlap/split")
    result = {"case": case, "group": group, "target": target,
              "repetition": repetition, "concurrency": concurrency,
              "mode": mode, "requested_count_or_waves": count, "warmup_count": warmup,
              "offered_rate_per_key": rate, "key_count": len(keys),
              **summarize(rows, window_start=extra.get("arrival_window_start"),
                          window_end=(extra["arrival_window_start"] + seconds
                                      if mode == "rate" else None)),
              **extra, "missed": len(missed), "valid_case": not issues,
              "issues": issues, "backend_before": before, "backend_after": after,
              "gateway_state_after": gateway_state, "recovery": recovery,
              "per_key": {key: summarize([r for r in rows if r["key_alias"] == key],
                            window_start=extra.get("arrival_window_start"),
                            window_end=(extra["arrival_window_start"] + seconds
                                        if mode == "rate" else None)) for key in keys}}
    write_json(directory / f"{case}.json", result)
    print(f"{case}: {result['success']}/{result['issued']} success, "
          f"valid={result['valid_case']}", flush=True)
    return result


async def order_check(directory, client, backend, gateway):
    """Hold slots with other keys, then spend the target key's default two tokens."""
    before = await state(client, backend)
    holders = [asyncio.create_task(request(client, gateway["url"], case="order-hold",
                                          sequence=i, key=f"holder-{i}")) for i in range(2)]
    target_rows = []
    occupied = False
    try:
        for _ in range(100):
            if (await state(client, gateway))["active"] == 2:
                occupied = True
                break
            await asyncio.sleep(0.005)
        if not occupied:
            raise RuntimeError("could not occupy both slots for order check")
        for i in range(3):
            target_rows.append(await request(client, gateway["url"], case="order-target",
                                             sequence=i, key="target"))
    finally:
        holder_rows = await asyncio.gather(*holders)
    rows = holder_rows + target_rows
    with (directory / "requests.jsonl").open("a") as stream:
        for row in rows:
            row.update(group="order", target="gateway", repetition=0)
            stream.write(json.dumps(row) + "\n")
    records = await completion_records(gateway["log"], {r["trace_id"] for r in rows})
    after = await state(client, backend)
    issues = validate(rows, "order", records, before, after, await state(client, gateway))
    observed = [(r["status"], r["error_code"]) for r in target_rows]
    expected = [(503, "concurrency_limit_exceeded")] * 2 + [(429, "rate_limit_exceeded")]
    if observed != expected:
        issues.append("expected target sequence: concurrency 503, concurrency 503, key 429")
    if target_rows[-1]["ended_at"] - target_rows[0]["started_at"] >= 1:
        issues.append("target burst exceeded one refill interval")
    result = {"case": "order", "group": "order", "valid_case": not issues,
              "issues": issues, "target_statuses": observed,
              "backend_before": before, "backend_after": after}
    write_json(directory / "order.json", result)
    print(f"order: {observed}, valid={result['valid_case']}", flush=True)
    return result


def aggregate(results):
    groups = {}
    for row in results:
        if row["group"] == "order":
            continue
        key = (row["group"], row["target"], row["concurrency"],
               row["offered_rate_per_key"], row["key_count"])
        groups.setdefault(key, []).append(row)
    output = []
    for key, rows in groups.items():
        entry = dict(zip(("group", "target", "concurrency", "rate", "keys"), key))
        entry.update(cases=[r["case"] for r in rows], valid=all(r["valid_case"] for r in rows))
        for metric in ("success_rate", "success_rps", "success_p50_seconds", "success_p95_seconds"):
            values = [r[metric] for r in rows if r[metric] is not None]
            entry[metric] = ({"median": statistics.median(values), "min": min(values),
                              "max": max(values)} if values else None)
        output.append(entry)
    return output


async def run(args, directory):
    pilot = args.profile == "pilot"
    repetitions = 1 if pilot else 3
    results = []
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=32)
    async with httpx.AsyncClient(timeout=10, trust_env=False, limits=limits) as client:
        async with service(directory, "mock-fast", "mock") as backend:
            async with service(directory, "gateway-overhead", "gateway",
                               "--backend-url", backend["url"]) as gateway:
                for repetition in range(repetitions):
                    for concurrency in (1, 2, 4, 8):
                        targets = ("direct", "gateway") if repetition % 2 == 0 else ("gateway", "direct")
                        for target in targets:
                            case = f"overhead-r{repetition}-c{concurrency}-{target}"
                            results.append(await save_case(
                                directory, client, case=case, group="overhead", target=target,
                                gateway=gateway, backend=backend, mode="closed",
                                concurrency=concurrency, count=40 if pilot else 1000,
                                repetition=repetition, warmup=5 if pilot else 50))
            for repetition in range(repetitions):
                for rate, keys in [(r, ("key-a",)) for r in (0.5, 1, 2, 5)] + [(2, ("key-a", "key-b"))]:
                    case = f"rate-r{repetition}-q{rate}-k{len(keys)}"
                    async with service(directory, "gateway-" + case, "gateway",
                                       "--backend-url", backend["url"], "--capacity", 2,
                                       "--rate", 1) as gateway:
                        results.append(await save_case(
                            directory, client, case=case, group="rate", target="gateway",
                            gateway=gateway, backend=backend, mode="rate", rate=rate,
                            seconds=4 if pilot else 30, keys=keys, repetition=repetition))
        async with service(directory, "mock-slow", "mock", "--delay", 0.2) as backend:
            async with service(directory, "gateway-waves", "gateway",
                               "--backend-url", backend["url"], "--limit", 2) as gateway:
                for repetition in range(repetitions):
                    for concurrency in (1, 2, 4, 8):
                        results.append(await save_case(
                            directory, client, case=f"waves-r{repetition}-c{concurrency}",
                            group="waves", target="gateway", gateway=gateway, backend=backend,
                            mode="waves", concurrency=concurrency, count=3 if pilot else 100,
                            repetition=repetition))
        async with service(directory, "mock-order", "mock", "--delay", 2) as backend:
            async with service(directory, "gateway-order", "gateway", "--backend-url",
                               backend["url"], "--limit", 2, "--capacity", 2, "--rate", 1) as gateway:
                results.append(await order_check(directory, client, backend, gateway))
    write_json(directory / "summary.json", {"cases": results, "aggregate": aggregate(results),
                                            "all_valid": all(r["valid_case"] for r in results)})
    return all(r["valid_case"] for r in results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("pilot", "local"), default="pilot")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Never overwrite evidence from a prior run.
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    git = lambda *options: subprocess.check_output(["git", *options], cwd=ROOT, text=True).strip()
    manifest = {"started_utc": datetime.now(timezone.utc).isoformat(), "profile": args.profile,
                "command": sys.argv, "git_commit": git("rev-parse", "HEAD"),
                "git_status": git("status", "--short"), "platform": platform.platform(),
                "machine": platform.machine(), "cpu_count": os.cpu_count(),
                "python": sys.version, "packages": {name: version(name) for name in
                ("infergate", "fastapi", "httpx", "uvicorn", "opentelemetry-sdk")},
                "payload": PAYLOAD, "client_timeout_seconds": 10, "client_pool": 32,
                "gateway_workers": 1, "backend_count": 1,
                "backend_timeout_seconds": {"connect": 5, "pool": 5, "write": 30, "read": 30},
                "probe_deadline_seconds": 2, "probe_interval_seconds": 5,
                "logging_config": "configs/logging.json", "otlp_export": False,
                "percentile_method": "linear interpolation: (n-1)*fraction",
                "arrival_max_lag_seconds": 0.1,
                "scope": "local HTTP controlled mock; not real GPU inference"}
    write_json(directory / "manifest.json", manifest)
    # Capture dirty sources as well as commit identity, so uncommitted tool versions survive.
    sources = directory / "sources"
    sources.mkdir()
    source_paths = [*(ROOT / "scripts/m4_benchmark").glob("*.py"),
                    *(ROOT / "src/infergate").rglob("*.py"),
                    ROOT / "configs/logging.json", ROOT / "docs/reference/benchmarks.md"]
    manifest["source_sha256"] = {}
    for source in source_paths:
        relative = source.relative_to(ROOT)
        destination = sources / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_bytes()
        destination.write_bytes(content)
        manifest["source_sha256"][str(relative)] = hashlib.sha256(content).hexdigest()
    write_json(directory / "manifest.json", manifest)
    (directory / "working-tree.patch").write_text(git("diff", "HEAD"))
    try:
        valid = asyncio.run(run(args, directory))
        manifest["outcome"] = "passed" if valid else "invalid_cases"
    except BaseException as exc:
        manifest["outcome"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        manifest["exception_class"] = type(exc).__name__
        raise
    finally:
        manifest["source_changed_during_run"] = [
            relative for relative, digest in manifest["source_sha256"].items()
            if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest]
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(directory / "manifest.json", manifest)
    print(f"Evidence: {directory}")
    if not valid or manifest["source_changed_during_run"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
