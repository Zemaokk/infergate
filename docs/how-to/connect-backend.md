# Connect a model backend

This guide assumes an inference server is already running. For installation
and measurement on a GPU host, use [Collect model benchmarks](collect-model-benchmarks.md).
The gateway environment is Python 3.13; the recorded vLLM environment is a
separate Python 3.12 environment.

## Check the server directly

Confirm that `/health` responds successfully, `/v1/models` advertises the served
alias, and the server's OpenAPI exposes the protocol you will use. Send a direct
request and check nonempty generation before adding the gateway. A Chat endpoint
does not imply native Responses support.

The recorded Chat/SSE integration used Qwen2.5-7B-Instruct with vLLM 0.8.5.
Native Responses was checked separately with vLLM 0.10.1+cu118. These are dated
[validation records](../reference/validation.md), not guarantees for other servers.

## Configure a single backend

For a server at `127.0.0.1:8001` serving the alias below:

```sh
INFERGATE_MODEL_NAME=Qwen2.5-7B-Instruct INFERGATE_BACKEND_COUNT=1 INFERGATE_BACKEND_A_URL=http://127.0.0.1:8001   uv run --no-sync uvicorn infergate.runtime:app --host 127.0.0.1 --port 8000 --workers 1 --log-config configs/logging.json
```

The URL is an origin, without `/v1` or another path prefix. The gateway adds
the protocol path. A single-backend configuration ignores B. Change the alias
and origin to match your server; restart the gateway after changes.

## Check both paths you need

Ordinary Chat:

```sh
curl -i http://127.0.0.1:8000/v1/chat/completions   -H 'Content-Type: application/json'   -H 'X-InferGate-Key: model-chat'   -d '{"model":"Qwen2.5-7B-Instruct","messages":[{"role":"user","content":"Explain an HTTP gateway briefly."}],"max_tokens":64}'
```

On a server with native Responses:

```sh
curl -i http://127.0.0.1:8000/v1/responses   -H 'Content-Type: application/json'   -H 'X-InferGate-Key: model-responses'   -d '{"model":"Qwen2.5-7B-Instruct","input":"Explain an HTTP gateway briefly.","store":false,"max_output_tokens":64}'
```

Check HTTP status, returned model, and generated text. Responses should report
completed status for the benchmark's success criterion. The standard Compose
mock cannot perform this check. No translation to Chat takes place.

## Add a second instance

Set `INFERGATE_BACKEND_COUNT=2` and configure both A and B origins. Both must
serve the same configured model alias. Start with direct checks of both servers,
then check routing through the gateway. Use distinct quota labels or wait for
refill when repeating requests. Stop only the gateway process you started when
finished; this guide does not manage the existing model server.

See [Configuration](../reference/configuration.md) for defaults and URL rules,
and [Streaming and failures](../explanation/streaming-and-failures.md) for
health timing and connection fallback behavior.
