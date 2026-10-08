# Streaming and failures

The difficult boundary in an asynchronous gateway is the lifetime of admitted
work. Returning a response object from an endpoint does not mean its body has
finished running. InferGate makes that ownership transfer explicit.

## A slot follows the downstream work

For buffered responses, the endpoint holds the slot while reading the backend
body, then releases it before sending the buffered response to the client.
The active gauge therefore measures downstream capacity, not every HTTP response
still being transmitted.

For streams, the endpoint owns the slot and opened backend stream until
`LimitedStreamingResponse` construction succeeds. The response then owns body
iteration, downstream close, and release. Its outer execution covers header
sending as well as body iteration. A failure before the first chunk must still
close the stream; putting cleanup only inside the body generator would miss it.
Construction failure leaves ownership with the endpoint.

Close is cancellation-shielded and runs before releasing the slot. Release still
runs if close raises. Holding capacity through cleanup avoids advertising a free
slot while the previous stream is still owned. Shielding does not impose a close
deadline: a stalled close can retain capacity, and a continuously producing
stream has no total generation deadline. These limits are explicit in
[configuration](../reference/configuration.md).

[Lifecycle tests](../../tests/test_app.py) cover normal completion, read
failure, disconnect, cancellation, header/body send failure, close failure, and
response-construction failure. [ADR-0004](../decisions/0004-transfer-stream-ownership.md)
records the ownership choice.

## Fallback has a narrow replay boundary

Only `ConnectError` and `ConnectTimeout` permit a second backend attempt. The
router excludes the previously attempted backend, and the request retains its
one token charge and slot. Read, write, and pool errors, HTTP error responses,
and errors in an opened stream do not qualify.

Once execution or streamed output may have begun, replay can duplicate work or
produce an incoherent client response. Even connection-only fallback is not an
end-to-end exactly-once guarantee. The implementation bounds the kinds and
number of attempts it will make; it does not prove backend side effects.
See [ADR-0003](../decisions/0003-limit-backend-fallback.md) and
[retry tests](../../tests/test_retry.py).

## Health is a snapshot

HealthChecker updates stored routing state independently of business requests.
Startup probes run in parallel; periodic rounds do not overlap. A stopped server
may still be marked healthy until the next failed probe. Before that update, a
request may try a connection and return 502 if fallback cannot succeed. After
the update, initial routing can reject it with 503 and zero attempts. Successful
probes restore eligibility. Neither status transition has a fixed wall-clock
sequence independent of probe timing.

A `/metrics` container check establishes that the gateway serves metrics, not
that a model is ready. Likewise, the healthy gauge reports stored state rather
than issuing a new probe at scrape time.

## Admission and observation describe different boundaries

Key quota is consumed before concurrency is checked. With no waiting queue,
excess concurrency returns 503 immediately, after consuming that quota. Later
failure does not refund it. This discourages repeated rejected work from being
free and keeps accounting deterministic; it does not implement fair scheduling.
[ADR-0002](../decisions/0002-reject-excess-work.md) explains the no-queue decision.

Observation outlives endpoint execution and finishes after response cleanup.
A fallback is one request with two attempts. A stream may send HTTP 200 before
ending as `cancelled` or `stream_error`. Request outcome and HTTP status must
therefore remain separate. Attempt metrics are submitted when the whole request
finalizes, even if the first attempt ended earlier. The
[observability reference](../reference/observability.md) defines the measurements;
[ADR-0005](../decisions/0005-separate-request-attempt-observations.md) records the choice.
