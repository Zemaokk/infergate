# Contributing

For changes to routing, shared state, streaming, admission, or fallback,
start with the [architecture](docs/explanation/architecture.md) and the relevant
[decision records](docs/decisions/README.md). Describe the behavior being changed
and the tests that establish the new contract.

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

Link directly to canonical pages under `docs/tutorials`, `docs/how-to`,
`docs/reference`, `docs/explanation`, and `docs/decisions`. Keep README links
aligned when a page moves; do not add compatibility copies of old guides.

Published figures live in `docs/assets/`; machine-readable validation data and
portable benchmark data live in `docs/evidence/`. The checksums there use
repository-relative paths. Preserve evidence bytes; record a new run separately
instead of replacing a dated result. Update the checksum list when deliberately
adding evidence.

`docs/archive/` is a local-only backup ignored by Git. Current pages must not link
to it, and checks must work when it is absent. The documentation checker validates
local navigation and published evidence checksums. It does not fetch remote URLs.

## Hand off the result

Describe behavior, validation, and remaining limits. Offer one concise English
Conventional Commit message for a substantial independent task. A suggested
message does not authorize committing, pushing, changing visibility, or deploying.
