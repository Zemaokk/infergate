# ADR-0007: Publish current documentation and keep legacy notes local

- Status: Accepted
- Recorded: 2026-10-08
- Supersedes: [ADR-0006](0006-organize-project-documentation.md)

## Context

The documentation migration retained historical guides and compatibility pages.
The current publication requirement is to keep only the new documentation in
version control while preserving old files locally. Fresh checkouts must still
contain the figures and measurement data needed to inspect reported results.

## Decision

Ignore `docs/archive/` and remove its files from the Git index without deleting
the local copies. Retire the uppercase compatibility pages and link directly to
canonical pages from README and all current documentation.

Keep referenced figures in `docs/assets/` and machine-readable verification and
benchmark data in `docs/evidence/`. Preserve their bytes and publish checksums
using repository-relative paths. Current guides and CI must work without the
local archive. The documentation checker skips legacy notes and rejects links
from current pages into that directory.

## Consequences and alternatives

A fresh checkout has one published documentation structure and enough data to
redraw the recorded benchmarks. Old external URLs to retired pages may no longer
resolve. Keeping compatibility pages was rejected because it would retain the
redundant entry points this change removes. Deleting local historical files was
unnecessary; removing them from the index and ignoring them meets the requirement.

Ignoring files does not remove them from earlier Git commits. This change does
not rewrite repository history.

## Evidence

[Documentation index](../README.md), [published results](../reference/validation.md),
[checksums](../evidence/SHA256SUMS), [documentation checker](../../scripts/check_docs.py).
