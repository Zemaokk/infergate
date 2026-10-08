# Contributing

InferGate is an author-led learning project. Read the
[collaboration agreement](docs/COLLABORATION_CONTRACT.md) before changing core
mechanisms. For routing, shared state, streaming, admission, and fallback, the
author writes the first draft, followed by focused review, verification, and
teach-back. Engineering support and documentation may be AI-assisted.

## Make a change

Keep the change scoped to an observable problem. State the affected invariant,
show a reproducible case, and run checks appropriate to its impact. Do not add
protocol support, distributed state, or another routing policy merely to make
the project appear larger. Put separate ideas in a separate proposal.

Install the locked Python 3.13 environment and check:

```sh
uv sync --locked --no-editable
uv run --no-sync python scripts/check_docs.py
uv run --no-sync python -m pytest -q
git diff --check
```

Use [installation verification](docs/how-to/verify-installation.md) for actual
HTTP and packaging checks. Benchmark tool changes need tests that protect
validity, exclusions, and evidence identity; do not write performance assertions
against timing on a shared machine. Preserve failed and invalid experiment data.

## Place documentation by purpose

The [documentation index](docs/README.md) follows [Diátaxis](https://diataxis.fr/):
a tutorial teaches through a complete guided experience; a how-to solves a
specific task; reference states exact facts; explanation develops the reasoning.
Link between them instead of mixing every purpose into every page.

Keep current facts next to their owning source/tests. Date validation claims
and link the evidence. Distinguish reproducing an old report from collecting
new measurements. Do not edit historical results into a new result or use test
counts as a permanent feature claim.

Record consequential choices using the [ADR process](docs/decisions/README.md).
Preserve accepted rationale, and supersede with a new record when necessary.
In [CHANGELOG](CHANGELOG.md), add noteworthy changes under Unreleased using
only relevant categories: Added, Changed, Deprecated, Removed, Fixed, Security.
Record an actual release date only when a release occurs; do not synthesize a
release history from commits or milestone dates.

## Preserve navigation and evidence

The root README's existing uppercase documentation links have compatibility
pages. Keep those pages short and point them to the canonical document.
The legacy M4 plot path is retained for the README image; its bytes match the
archived original. The [2026-10-08 archive](docs/archive/2026-10-08/README.md) is a
historical snapshot with hashes. New verification output belongs in a new path,
not inside that snapshot. Any necessary correction should explain the original
record and add a clearly dated erratum rather than silently altering evidence.

The documentation checker verifies local links and archived hashes. Remote links
are reviewed against primary sources when the affected claims change; the
checker does not make network requests.

## Hand off the result

Describe behavior, validation, and remaining limits. Offer one concise English
Conventional Commit message for a substantial independent task. A suggested
message does not authorize committing, pushing, changing visibility, or deploying.
