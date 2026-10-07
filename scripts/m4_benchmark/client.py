"""HTTP load generation and success-only statistics with explicit measurement windows."""

import asyncio
import math
import time
from collections import Counter
from uuid import uuid4

import httpx

PAYLOAD = {"model": "mock-model", "messages": [{"role": "user", "content":
           "Briefly explain what an HTTP gateway does."}], "stream": False}
PATH = "/v1/chat/completions"


def valid_response(body):
    if not isinstance(body, dict):
        return False
    try:
        return (body["object"] == "chat.completion" and body["model"] == "mock-model"
                and bool(body["choices"][0]["message"]["content"].strip())
                and body["choices"][0]["finish_reason"] == "stop")
    except (KeyError, IndexError, TypeError, AttributeError):
        return False


async def request(client, url, *, case, sequence, key="key-a", planned=None, wave=None,
                  payload=None, path=PATH, validator=None, metadata=None, on_record=None):
    trace_id = uuid4().hex
    headers = {"X-InferGate-Key": f"m44-benchmark-{key}",
               "traceparent": f"00-{trace_id}-{uuid4().hex[:16]}-01"}
    started = time.perf_counter()
    record = {"case": case, "sequence": sequence, "wave": wave, "key_alias": key,
              "trace_id": trace_id, "scheduled_at": planned, "started_at": started,
              "scheduling_lag_seconds": None if planned is None else started - planned,
              "status": None, "error_code": None, "client_exception": None,
              "valid_response": False, "usage": None}
    cancelled = False
    try:
        response = await client.post(url + path, json=PAYLOAD if payload is None else payload, headers=headers)
        # Client total time ends once the full body is received; parse separately.
        record["ended_at"] = time.perf_counter()
        record["status"] = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
        record["valid_response"] = response.status_code == 200 and (validator or valid_response)(body)
        if isinstance(body, dict):
            error = body.get("error")
            record["error_code"] = error.get("code") if isinstance(error, dict) else None
            record["usage"] = body.get("usage")
            if metadata is not None:
                record["response_meta"] = metadata(body)
    except httpx.RequestError as exc:
        record["ended_at"] = time.perf_counter()
        # Store class only: exception text can contain URLs or other sensitive content.
        record["client_exception"] = type(exc).__name__
    except asyncio.CancelledError:
        record["ended_at"] = time.perf_counter()
        record["client_exception"] = "CancelledError"
        cancelled = True
    record["duration_seconds"] = record["ended_at"] - started
    if on_record is not None:
        on_record(record)
    if cancelled:
        raise asyncio.CancelledError
    return record


async def closed_loop(client, url, case, concurrency, count, **request_options):
    counter = iter(range(count))
    rows = []

    async def worker():
        for sequence in counter:
            rows.append(await request(client, url, case=case, sequence=sequence, **request_options))

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return rows


async def waves(client, url, case, concurrency, count):
    rows = []
    for wave in range(count):
        barrier = asyncio.Event()

        async def member(index):
            await barrier.wait()
            return await request(client, url, case=case, sequence=wave * concurrency + index,
                                 wave=wave)

        tasks = [asyncio.create_task(member(index)) for index in range(concurrency)]
        barrier.set()
        rows.extend(await asyncio.gather(*tasks))
    return rows


async def fixed_rate(client, url, case, rate, seconds, keys=("key-a",), *, max_lag=0.1):
    """Skip late sends explicitly; never silently catch up or wait for earlier responses."""
    start = time.perf_counter()
    tasks, missed = [], []
    # index/rate < seconds, rather than count rounded down (important for short pilots).
    for index in range(math.ceil(rate * seconds)):
        planned = start + index / rate
        await asyncio.sleep(max(0, planned - time.perf_counter()))
        for key in keys:
            sequence = index * len(keys) + keys.index(key)
            if time.perf_counter() - planned > max_lag:
                missed.append({"case": case, "sequence": sequence, "key_alias": key,
                               "scheduled_at": planned, "reason": "scheduler_late"})
            else:
                tasks.append(asyncio.create_task(request(
                    client, url, case=case, sequence=sequence, key=key, planned=planned)))
    rows = await asyncio.gather(*tasks)
    # Start and end of the planned arrival window are not the observed throughput window.
    return rows, missed, {"arrival_window_start": start,
                          "arrival_window_seconds": seconds,
                          "drain_seconds": max(0, max((r["ended_at"] for r in rows),
                                                     default=start) - start - seconds)}


def percentile(values, fraction):
    """Linear interpolation, position=(n-1)*fraction, recorded in the manifest."""
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def summarize(rows, *, window_start=None, window_end=None):
    success = [row for row in rows if row["valid_response"]]
    durations = [row["duration_seconds"] for row in success]
    window = (max(max(r["ended_at"] for r in rows), window_end or 0)
              - (window_start if window_start is not None else min(r["started_at"] for r in rows))
              if rows else 0)
    categories = Counter(
        "success" if r["valid_response"] else
        f"client:{r['client_exception']}" if r["client_exception"] else
        f"http:{r['status']}:{r['error_code'] or 'invalid_or_backend_response'}"
        for r in rows)
    return {"issued": len(rows), "success": len(success),
            "success_rate": len(success) / len(rows) if rows else None,
            "measurement_seconds": window,
            "success_rps": len(success) / window if window > 0 else None,
            "success_p50_seconds": percentile(durations, 0.5),
            "success_p95_seconds": percentile(durations, 0.95),
            "rejected_p50_seconds": percentile(
                [r["duration_seconds"] for r in rows if r["status"] in (429, 503)], 0.5),
            "categories": dict(categories)}
