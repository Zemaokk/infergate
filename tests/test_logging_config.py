import json
from pathlib import Path
import subprocess
import sys


def test_uvicorn_logging_config_emits_one_json_record_when_loaded_twice():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", '''
import asyncio
import logging
from uvicorn import Config
from infergate.observability import RequestObservationMiddleware

# An existing root handler must not duplicate the completion record.
logging.basicConfig(level=logging.INFO)
for _ in range(2):
    Config("infergate.runtime:app", log_config="configs/logging.json")

async def app(scope, receive, send):
    scope["state"]["observation"].make_result("rejected", "no_backend_available")
    await send({"type": "http.response.start", "status": 503})
    await send({"type": "http.response.body", "body": b""})

async def receive():
    raise AssertionError("unexpected receive")

async def send(message):
    pass

asyncio.run(RequestObservationMiddleware(app)(
    {"type": "http", "method": "POST", "path": "/v1/chat/completions"}, receive, send
))
logging.getLogger("uvicorn.error").info("server marker")
'''],
        cwd=root, capture_output=True, text=True, check=True, timeout=10,
    )
    lines = result.stderr.splitlines()
    records = [json.loads(line) for line in lines if line.startswith("{")]
    assert len(records) == 1
    assert records[0]["event"] == "request_finished"
    assert records[0]["status_code"] == 503
    assert records[0]["outcome"] == "rejected"
    assert len(records[0]["request_id"]) == 32
    assert sum("server marker" in line for line in lines) == 1
    assert result.stdout == ""
