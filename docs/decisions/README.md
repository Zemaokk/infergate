# Architecture decision records

Each record describes one consequential choice: its context, decision,
alternatives, and consequences. Current behavior is in the
[reference](../README.md#reference--look-up-the-contract); ADRs preserve why it
was chosen. Their format follows the
[ADR guidance](https://github.com/architecture-decision-record/architecture-decision-record).

| Record | Status | Dating |
| --- | --- | --- |
| [0001: API surface](0001-api-surface.md) | Accepted | Original 2026-09-04 record, preserved verbatim |
| [0002: Reject excess work](0002-reject-excess-work.md) | Accepted, retrospective | Recorded 2026-10-08; existing implementation |
| [0003: Limit fallback](0003-limit-backend-fallback.md) | Accepted, retrospective | Recorded 2026-10-08; existing implementation |
| [0004: Stream ownership](0004-transfer-stream-ownership.md) | Accepted, retrospective | Recorded 2026-10-08; existing implementation |
| [0005: Request/attempt observations](0005-separate-request-attempt-observations.md) | Accepted, retrospective | Recorded 2026-10-08; existing implementation |
| [0006: Documentation organization](0006-organize-project-documentation.md) | Accepted | Author-requested migration, 2026-10-08 |

A retrospective record documents verified behavior; it does not invent the date
on which a historical choice was approved. ADR-0001 contains original planning
language; implementation status is in the [API reference](../reference/api.md).

For a new choice, copy the [template](template.md), use the next four-digit
number and a short lowercase filename, and begin as Proposed. Record the actual
decision authority and date when accepted. Use Accepted, Rejected, Deprecated,
or Superseded as appropriate. Do not rewrite an accepted rationale to match a
new design: create a new record, then add a status/link to the old one.
