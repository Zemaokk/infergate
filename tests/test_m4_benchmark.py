"""Protect benchmark evidence boundaries, not timing-dependent performance targets."""

import asyncio

import httpx
import pytest

from scripts.m4_benchmark.client import fixed_rate, request, summarize, valid_response
from scripts.m4_benchmark.run import aggregate, quota_issues, validate


def row(*, success=True, start=0, end=1, status=None, error=None):
    return {"valid_response": success, "started_at": start, "ended_at": end,
            "duration_seconds": end - start, "status": status or (200 if success else 503),
            "error_code": error, "client_exception": None, "sequence": 0,
            "trace_id": "abc", "key_alias": "key-a"}


def test_fast_rejections_do_not_improve_success_latency_or_success_rate():
    rows = [row(start=0, end=1), row(start=0, end=3)]
    rows += [row(success=False, end=0.001, error="concurrency_limit_exceeded") for _ in range(8)]
    result = summarize(rows)
    assert result["success_rate"] == 0.2
    assert result["success_rps"] == pytest.approx(2 / 3)
    assert result["success_p50_seconds"] == 2
    assert result["success_p95_seconds"] == pytest.approx(2.9)
    assert result["rejected_p50_seconds"] == 0.001


def test_arrival_window_includes_idle_tail_and_drain():
    result = summarize([row(start=10, end=11)], window_start=10, window_end=40)
    assert result["measurement_seconds"] == 30
    drained = summarize([row(start=10, end=45)], window_start=10, window_end=40)
    assert drained["measurement_seconds"] == 35


def test_empty_sample_has_no_invented_latency_or_rate():
    result = summarize([])
    assert result["success_p95_seconds"] is None
    assert result["success_rate"] is None
    assert result["success_rps"] is None


@pytest.mark.parametrize("body", [None, [], {}, {"choices": []},
    {"object": "chat.completion", "model": "mock-model", "choices": [
        {"finish_reason": "stop", "message": {"content": "  "}}]},
    {"object": "chat.completion", "model": "mock-model", "choices": [
        {"finish_reason": "length", "message": {"content": "text"}}]}])
def test_invalid_200_is_not_a_success(body):
    assert not valid_response(body)


@pytest.mark.asyncio
async def test_timeout_remains_an_issued_failure_without_exception_secrets():
    def transport(req):
        raise httpx.ReadTimeout("private endpoint text", request=req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        record = await request(client, "http://test", case="timeout", sequence=0)
    assert record["client_exception"] == "ReadTimeout"
    assert record["status"] is None
    assert record["valid_response"] is False
    assert "private endpoint" not in str(record)
    assert summarize([record])["categories"] == {"client:ReadTimeout": 1}


@pytest.mark.asyncio
async def test_malformed_json_200_remains_invalid():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(200, text="not JSON"))) as client:
        record = await request(client, "http://test", case="malformed", sequence=0)
    assert record["status"] == 200
    assert not record["valid_response"]


@pytest.mark.asyncio
async def test_fixed_rate_can_overlap_without_waiting_for_response():
    active = 0
    peak = 0

    async def transport(req):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return httpx.Response(429, json={"error": {"code": "rate_limit_exceeded"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        rows, missed, window = await fixed_rate(client, "http://test", "rate", 100, 0.035)
    assert len(rows) == 4  # planned at 0, .01, .02, .03, not floor(3.5).
    assert not missed
    assert peak > 1
    assert window["drain_seconds"] > 0


def test_rejection_with_backend_attempt_is_detected():
    rows = [row(success=False, end=0.01, error="concurrency_limit_exceeded")]
    logs = {"abc": {"status_code": 503, "attempt_count": 1, "cleanup_failed": False}}
    issues = validate(rows, "waves", logs, {"calls": 0}, {"calls": 0, "active": 0}, {"active": 0})
    assert any("completion mismatch" in issue for issue in issues)


def test_missing_log_and_capacity_leak_are_detected():
    issues = validate([row()], "overhead", {}, {"calls": 0},
                      {"calls": 1, "active": 1}, {"active": 1})
    assert any("missing completion" in issue for issue in issues)
    assert any("active requests" in issue for issue in issues)


def test_quota_refill_violation_is_detected():
    events = [{"key_alias": "key-a", "checked_at": time, "allowed": True,
               "tokens_after": remaining} for time, remaining in ((0, 1), (0.1, 0.1), (0.2, 0))]
    rows = [row() for _ in events]
    assert quota_issues(rows, {"capacity": 2, "rate": 1, "quota_events": events})


def test_quota_separate_keys_and_refill_match_http_results():
    events = []
    rows = []
    for key in ("key-a", "key-b"):
        for time, allowed, remaining in ((0, True, 1), (0.1, True, 0.1),
                                         (0.2, False, 0.2), (1.1, True, 0.1)):
            events.append({"key_alias": key, "checked_at": time,
                           "allowed": allowed, "tokens_after": remaining})
            r = row(success=allowed, status=200 if allowed else 429)
            r["key_alias"] = key
            rows.append(r)
    assert not quota_issues(rows, {"capacity": 2, "rate": 1, "quota_events": events})


def test_aggregation_keeps_failed_round_visible():
    base = {"group": "overhead", "target": "gateway", "concurrency": 1,
            "offered_rate_per_key": None, "key_count": 1, "success_rate": 1,
            "success_rps": 10, "success_p50_seconds": .01, "success_p95_seconds": .02}
    result = aggregate([{**base, "case": "a", "valid_case": True},
                        {**base, "case": "b", "valid_case": False, "success_rps": 1}])[0]
    assert not result["valid"]
    assert result["cases"] == ["a", "b"]
    assert result["success_rps"] == {"median": 5.5, "min": 1, "max": 10}


@pytest.mark.asyncio
async def test_late_arrivals_are_recorded_as_missed_instead_of_silent_catchup(monkeypatch):
    from types import SimpleNamespace
    from scripts.m4_benchmark import client as module

    now = 10.0

    async def oversleep(_seconds):
        nonlocal now
        now += .2

    monkeypatch.setattr(module, "time", SimpleNamespace(perf_counter=lambda: now))
    monkeypatch.setattr(module, "asyncio", SimpleNamespace(
        sleep=oversleep, gather=asyncio.gather, create_task=asyncio.create_task))
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: pytest.fail("late request should not be issued"))) as client:
        rows, missed, _ = await fixed_rate(client, "http://test", "late", 10, .3)
    assert rows == []
    assert len(missed) == 3
    assert all(r["reason"] == "scheduler_late" for r in missed)


def test_retry_cannot_pick_slow_but_valid_round():
    from scripts.m4_benchmark.retry import failed_cases
    with pytest.raises(ValueError, match="No invalid cases"):
        failed_cases([{"case": "slow", "valid_case": True, "success_rps": 1}])
    assert failed_cases([{"case": "slow", "valid_case": True},
                         {"case": "invalid", "valid_case": False}]) == [
                             {"case": "invalid", "valid_case": False}]


def test_retry_merge_requires_same_workload_and_keeps_failed_retry_visible():
    from scripts.m4_benchmark.retry import merge_cases
    original = {"case": "invalid", "valid_case": False, "group": "rate", "target": "gateway",
                "mode": "rate", "concurrency": 1, "offered_rate_per_key": 2,
                "key_count": 1, "repetition": 2, "requested_count_or_waves": 1, "warmup_count": 0}
    replacement = {**original, "case": "retry", "replaces_invalid_case": "invalid"}
    assert merge_cases([original], [replacement]) == [original]
    replacement["valid_case"] = True
    assert merge_cases([original], [replacement]) == [replacement]
    replacement["offered_rate_per_key"] = 1
    with pytest.raises(ValueError, match="experiment variable"):
        merge_cases([original], [replacement])


@pytest.mark.parametrize("finish", ["stop", "length"])
def test_real_chat_accepts_success_at_output_budget(finish):
    from scripts.m4_benchmark.real import generated
    body = {"object": "chat.completion", "model": "qwen", "choices": [
        {"message": {"content": "An HTTP gateway routes requests."}, "finish_reason": finish}]}
    assert generated(body, "chat", "qwen")
    assert not generated(body, "chat", "other-model")


@pytest.mark.parametrize("extra,valid", [({}, True), ({"store": False}, True),
                                         ({"store": True}, False), ({"status": "incomplete"}, False)])
def test_real_responses_require_completed_text_but_not_store_echo(extra, valid):
    from scripts.m4_benchmark.real import generated
    body = {"object": "response", "model": "qwen", "status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": "A gateway routes traffic."}]}], **extra}
    assert generated(body, "responses", "qwen") is valid


@pytest.mark.asyncio
async def test_real_client_uses_native_path_and_saves_metadata_and_usage():
    from scripts.m4_benchmark.real import generated, payload, response_metadata
    received = []
    def transport(req):
        import json
        assert req.url.path == "/v1/responses"
        assert json.loads(req.content)["store"] is False
        return httpx.Response(200, json={"object": "response", "model": "qwen", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "hello"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 2}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        record = await request(client, "http://test", case="real", sequence=0,
            path="/v1/responses", payload=payload("responses", "qwen"),
            validator=lambda body: generated(body, "responses", "qwen"),
            metadata=lambda body: response_metadata(body, "responses"), on_record=received.append)
    assert record["valid_response"]
    assert record["usage"]["output_tokens"] == 2
    assert record["response_meta"]["output_characters"] == 5
    assert received == [record]


@pytest.mark.asyncio
async def test_cancelled_real_request_is_persisted_before_cancellation_propagates():
    started = asyncio.Event()
    async def transport(req):
        started.set()
        await asyncio.Event().wait()
    records = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        task = asyncio.create_task(request(client, "http://test", case="cancel", sequence=0,
                                           on_record=records.append))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(records) == 1
    assert records[0]["client_exception"] == "CancelledError"
    assert not records[0]["valid_response"]


def test_real_log_check_uses_completed_outcome_and_native_route():
    from scripts.m4_benchmark.real import validate_case
    r = {**row(), "protocol": "chat"}
    logs = {"abc": {"attempt_count": 1, "status_code": 200, "cleanup_failed": False,
                    "outcome": "completed", "route": "/v1/chat/completions"}}
    assert not validate_case([r], logs, {"active": 0, "healthy": True})
    logs["abc"]["route"] = "/v1/responses"
    assert validate_case([r], logs, {"active": 0, "healthy": True})


def test_real_token_summary_reports_missing_usage_without_inventing_counts():
    from scripts.m4_benchmark.real_report import token_summary
    rows = [{"valid_response": True, "usage": {"output_tokens": 64}},
            {"valid_response": True, "usage": None},
            {"valid_response": True, "usage": {"output_tokens": True}},
            {"valid_response": False, "usage": {"output_tokens": 200}}]
    assert token_summary(rows, "responses") == {"samples": 1, "missing": 2,
                                               "min": 64, "max": 64, "mean": 64}
