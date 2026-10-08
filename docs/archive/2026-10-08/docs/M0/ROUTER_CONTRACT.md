# M0 Round-Robin Router Contract

**Status:** Accepted  
**Scope:** Model-aware round-robin selection across configured backends

The M0 router selects backends in a fixed cyclic order. It contains no HTTP
logic and does not inspect request payloads other than the requested model name.

## Definitions

A `Backend` contains:

- `id`: a stable identifier used for gateway metadata;
- `base_url`: the address used to send requests to the backend.

The routing table groups backends by model name:

```text
dict[str, list[Backend]]
```

## Input

The router is initialized with a routing table. Each call to `select()` receives
the requested model name.

## State

The router stores one cursor per configured model:

```text
dict[str, int]
```

Each cursor identifies the backend to select on the next call. Its initial value
is `0`.

## Output

`select()` returns the selected `Backend`, including both its `id` and
`base_url`.

## State transition

For a requested model:

1. Look up its backend list.
2. Read the model's current cursor.
3. Select the backend at that index.
4. Advance the cursor using:

   ```text
   next_cursor = (current_cursor + 1) % len(backends)
   ```

5. Store the new cursor and return the selected backend.

## Failure behavior

Raise `NoBackendAvailableError` when:

- the requested model is not configured; or
- the requested model has an empty backend list.

A failed selection must not update any cursor. The router does not assign an
HTTP status to this failure; the API layer will later convert it into
`503 Service Unavailable`.

## Example

Given:

- backend A: `id="backend-a"`, `base_url="http://localhost:8001"`;
- backend B: `id="backend-b"`, `base_url="http://localhost:8002"`;
- the backend order `[A, B]`; and
- an initial cursor of `0`.

Five calls to `select()` produce:

| Call | Selected backend | Cursor after selection |
| ---: | --- | ---: |
| 1 | backend A | 1 |
| 2 | backend B | 0 |
| 3 | backend A | 1 |
| 4 | backend B | 0 |
| 5 | backend A | 1 |

## M0 invariants

1. Selection order follows the configured backend order.
2. Each model advances its own cursor independently.
3. A successful selection advances exactly one cursor exactly once.
4. A failed selection changes no state.
5. The router returns backend identity and location, not only a URL.
6. The router reports domain failures and does not construct HTTP responses.

## Out of scope for M0

- health-aware selection;
- weighted routing;
- load-aware selection;
- concurrent access guarantees;
- retry and fallback behavior.
