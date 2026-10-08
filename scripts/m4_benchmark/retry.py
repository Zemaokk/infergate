"""Retry invalid local cases only; preserve and explicitly exclude the original cases."""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .run import ROOT, aggregate, save_case, service, write_json


def failed_cases(cases):
    failures = [case for case in cases if not case["valid_case"]]
    if not failures:
        raise ValueError("No invalid cases to retry; do not select slow valid rounds")
    return failures


def merge_cases(original, retried):
    failed = {case["case"]: case for case in failed_cases(original)}
    replacements = {}
    for case in retried:
        name = case["replaces_invalid_case"]
        if name not in failed or name in replacements:
            raise ValueError("Retry must name a unique originally invalid case")
        for field in ("group", "target", "mode", "concurrency", "offered_rate_per_key",
                      "key_count", "repetition", "requested_count_or_waves", "warmup_count"):
            if case[field] != failed[name][field]:
                raise ValueError(f"Retry changed experiment variable: {field}")
        replacements[name] = case
    return [replacements.get(case["case"], case)
            if replacements.get(case["case"], case)["valid_case"] else case for case in original]


async def rerun(source, output, failures):
    results = []
    async with httpx.AsyncClient(timeout=10, trust_env=False,
                                 limits=httpx.Limits(max_connections=32, max_keepalive_connections=32)) as client:
        for original in failures:
            group = original["group"]
            if group not in ("rate", "waves", "overhead"):
                raise ValueError(f"Unsupported failed group: {group}; inspect manually")
            case = "retry-" + original["case"]
            async with service(output, case + "-mock", "mock", "--delay",
                               .2 if group == "waves" else 0) as backend:
                async with service(output, case + "-gateway", "gateway", "--backend-url",
                                   backend["url"], "--limit", 2 if group == "waves" else 32,
                                   "--capacity", 2 if group == "rate" else 100000,
                                   "--rate", 1 if group == "rate" else 100000) as gateway:
                    result = await save_case(
                        output, client, case=case, group=group, target=original["target"],
                        gateway=gateway, backend=backend, mode=original["mode"],
                        concurrency=original["concurrency"],
                        count=original["requested_count_or_waves"],
                        warmup=original["warmup_count"], rate=original["offered_rate_per_key"],
                        seconds=original.get("arrival_window_seconds"),
                        keys=tuple(original["per_key"]), repetition=original["repetition"])
                    result["replaces_invalid_case"] = original["case"]
                    result["original_issues"] = original["issues"]
                    results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    summary = json.loads((source / "summary.json").read_text())
    original_manifest = json.loads((source / "manifest.json").read_text())
    if original_manifest["profile"] != "local" or original_manifest["source_changed_during_run"]:
        raise ValueError("Only unchanged formal local runs may use this retry tool")
    # The measured client, service and validation implementation must stay identical.
    for relative, digest in original_manifest["source_sha256"].items():
        if relative.endswith(("BENCHMARK_CONTRACT.md", "docs/reference/benchmarks.md")):
            continue
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Source changed since original measurement: {relative}")
    failures = failed_cases(summary["cases"])
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    write_json(output / "original-summary.json", summary)
    write_json(output / "original-manifest.json", original_manifest)
    (output / "retry-source.py").write_bytes(Path(__file__).read_bytes())
    manifest = {**original_manifest, "started_utc": started, "original_evidence": str(source),
                "original_started_utc": original_manifest["started_utc"],
                "retry_command": sys.argv, "outcome": "running"}
    write_json(output / "manifest.json", manifest)
    try:
        retried = asyncio.run(rerun(source, output, failures))
        effective = merge_cases(summary["cases"], retried)
        valid = all(case["valid_case"] for case in effective)
        write_json(output / "summary.json", {
            "cases": effective, "aggregate": aggregate(effective), "all_valid": valid,
            "excluded_invalid_cases": failures, "retry_cases": retried,
            "original_evidence": str(source)})
        manifest["outcome"] = "passed" if valid else "invalid_cases"
    except BaseException as exc:
        manifest["outcome"] = "failed"
        manifest["exception_class"] = type(exc).__name__
        raise
    finally:
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["source_changed_during_run"] = [
            relative for relative, digest in original_manifest["source_sha256"].items()
            if not relative.endswith(("BENCHMARK_CONTRACT.md", "docs/reference/benchmarks.md"))
            and hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest]
        write_json(output / "manifest.json", manifest)
    if not valid or manifest["source_changed_during_run"]:
        raise SystemExit(1)
    print(f"Merged evidence: {output}")


if __name__ == "__main__":
    main()
