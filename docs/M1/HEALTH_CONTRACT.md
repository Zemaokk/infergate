# M1 Backend Health Contract

**Status:** State and health-aware router first implementation verified; probe loop pending
**Scope:** Health checks, backend eligibility, and model-aware routing

## 1. Goal and existing boundaries

For a model with two configured backends, A and B, a failed A must temporarily
leave the routing set so B can continue serving requests. Once A has recovered,
it must become selectable again. If no backend is eligible for the requested
model, the API layer returns the existing `503 no_backend_available` response.

M1 keeps the existing no-retry rule. A request already sent to a selected
backend is not automatically replayed on another backend. Health changes affect
later selections.

## 2. Ownership to define

The contract must say where the health state for each backend lives, which
component updates it, and what read-only view the router uses when selecting a
backend. A health probe must not be mistaken for a normal inference request.

For each core component, define:

| Component | Input | State owned | Output or failure |
| --- | --- | --- | --- |
| Health checker | Configured backends | Probe client and schedule | Per-backend probe result |
| Backend health state | Probe result | Per-application map by backend ID | Current eligibility |
| Router | Model and current eligibility | Per-model cursor | Backend or `NoBackendAvailableError` |

## 3. Author's first prediction

Assume both A and B serve the same model and start healthy. Predict each step:

1. A health check fails for A while B remains healthy. What is A's new state?
   Which backend may the *next* request select?
2. A request had already selected A immediately before that failed check. Does
   the gateway cancel or replay it, or does the health change apply only to
   later selections?
3. A later health check succeeds for A. Is one success enough to restore A?
   If not, what evidence is required? When may the router choose A again?
4. Both A and B become ineligible. What does `select(model)` report, and what
   does the API layer return?

Then name the smallest state set that can express these answers. It is fine to
start with two states and revise after a counterexample.

### Accepted selection and in-flight behavior

The author decided that a failed probe removes A from subsequent selections,
so B alone receives new requests. One later successful probe restores A.
If both backends are ineligible, the router reports
`NoBackendAvailableError`, which the API maps to `503 no_backend_available`.

The author accepted that health changes affect subsequent selections only. A
request already using A follows its own response, timeout, transport-failure,
or client-disconnect path. The probe result does not cancel or replay it.

The smallest candidate state set is `healthy` and `unhealthy`: a failed probe
moves a backend to `unhealthy`, and a successful probe moves it to `healthy`.
At startup, the gateway probes all configured backends concurrently and waits
for every result before accepting requests. A failed probe marks only that
backend `unhealthy`; it does not prevent the gateway from starting. If all
probes fail, the gateway starts and requests for that model receive `503`
until a later probe restores an eligible backend. This startup rule was
accepted by the author.

### Accepted M1 probe and routing policy

The author accepted these M1 choices:

- Probe each backend with `GET /health`. Exactly HTTP `200` counts as success;
  another status, a timeout, or a transport error counts as failure. The mock
  backend will expose this endpoint without invoking the inference handler.
- Give each probe a 2 s overall deadline. Run a new round 5 s after the previous round
  finishes, with no overlapping rounds. Probe all configured backends in one
  round concurrently. Use a dedicated HTTPX client for probes so inference
  requests do not occupy the probe connection pool.
- One failed probe changes `healthy` to `unhealthy`; one successful probe
  changes `unhealthy` to `healthy`, matching the author's first prediction.
- For M1, ordinary inference HTTP or transport outcomes do not change health
  state. The next probe determines eligibility. This can leave a failed backend
  selectable for up to one probe interval plus its timeout.
- Keep one per-application health map keyed by stable backend ID. The checker
  writes probe outcomes; the router reads the current eligibility. A synchronous
  state update or selection contains no `await`, so tasks in one event loop do
  not interleave midway through either operation. Multi-process sharing is out
  of scope.
- Keep each model's round-robin cursor relative to its configured backend
  order. On selection, scan forward from the cursor, skip unhealthy backends,
  select the first healthy one, then move the cursor just past that backend.
  If none is healthy, raise `NoBackendAvailableError` without moving the cursor.

The health checker, state map, and router must all use the same per-application
backend identities. The author's state and router first implementation is
verified by focused unit tests; runtime wiring remains deferred until startup
probes are implemented.

## 4. First implementation boundary

The author writes the first version of the health state and health-aware
round-robin selection. Start with a small state interface that can record one
probe outcome and answer whether a backend is currently eligible. Then make
`select(model)` consult that live state while retaining the configured backend
order and cursor rule above. AI reviews the first attempt before adding the
checker loop or runtime integration.

## 5. Verification needed after acceptance

- A failed backend is excluded from later selections for its model.
- A healthy peer still serves the model.
- A recovered backend becomes selectable again under the accepted recovery
  rule.
- With no eligible backend, the gateway returns `503` without contacting a
  backend.
- A selection already made is not retroactively changed.
- Repeated probes and concurrent selections do not corrupt health state or
  per-model round-robin behavior.
- Existing M0 and M1 streaming/timeout tests still pass.
