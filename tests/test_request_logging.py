import asyncio
import json
import logging

import pytest

from infergate.observability import RequestObservationMiddleware


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("log_fails", [False, True])
@pytest.mark.parametrize("metrics_fail", [False, True])
async def test_completion_log_and_metrics_are_independent_and_preserve_original_error(
    failure, log_fails, metrics_fail, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="infergate.observability")
    error = failure("original") if failure else None
    calls = []
    if log_fails:
        def broken_log(*args, **kwargs):
            raise ValueError("handler failed")
        monkeypatch.setattr("infergate.observability.logger.info", broken_log)
        monkeypatch.setattr("infergate.observability.logger.warning", broken_log)

    def record_metrics(observation):
        assert observation.is_finished
        calls.append(observation)
        if metrics_fail:
            raise ValueError("metrics failed")

    async def app(scope, receive, send):
        observation = scope["state"]["observation"]
        if error:
            raise error
        observation.make_result("completed")
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"private body"})

    async def receive():
        raise AssertionError("unexpected receive")

    async def send(message):
        pass

    scope = {"type": "http", "method": "POST", "path": "/v1/chat/completions"}
    middleware = RequestObservationMiddleware(app, record_metrics)
    if failure:
        with pytest.raises(failure) as caught:
            await middleware(scope, receive, send)
        assert caught.value is error
    else:
        await middleware(scope, receive, send)
    assert len(calls) == 1
    records = [json.loads(r.getMessage()) for r in caplog.records if r.levelno == logging.INFO]
    assert len(records) == (0 if log_fails else 1)
    if records:
        assert records[0]["event"] == "request_finished"
        assert records[0]["request_id"] == calls[0].request_id
        assert records[0]["outcome"] == calls[0].outcome
        assert "private body" not in json.dumps(records)


@pytest.mark.asyncio
async def test_completion_log_is_written_without_metrics_callback(caplog):
    caplog.set_level(logging.INFO, logger="infergate.observability")

    async def app(scope, receive, send):
        scope["state"]["observation"].make_result("rejected", "no_backend_available")
        await send({"type": "http.response.start", "status": 503})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        raise AssertionError("unexpected receive")

    async def send(message):
        pass

    await RequestObservationMiddleware(app)(
        {"type": "http", "method": "POST", "path": "/v1/chat/completions"}, receive, send
    )
    records = [json.loads(r.getMessage()) for r in caplog.records]
    assert len(records) == 1
    assert records[0]["status_code"] == 503
    assert records[0]["outcome"] == "rejected"
    assert records[0]["backend_attempts"] == []
