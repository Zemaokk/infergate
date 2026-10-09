# ADR-0006: Organize documentation by reader need

- Status: Superseded by [ADR-0007](0007-publish-current-documentation.md)
- Recorded: 2026-10-08
- Decision authority: project author's documentation-refactoring request

## Context

Milestone folders combine contracts, work plans, instructions, and acceptance
records. Readers need current operating guidance while historical experiments
must remain auditable. The author requested Diátaxis, ADRs, Keep a Changelog,
and a single archive folder, excluding the completed root README from edits.

## Decision

Organize current content as tutorials, how-to guides, reference, and explanation.
Use sequential ADRs for individual consequential choices and a root changelog
for noteworthy changes. Preserve ADR-0001 verbatim. Label later records about
existing behavior as retrospective instead of assigning invented decision dates.

Archive the pre-migration documentation and evidence under
`docs/archive/2026-10-08/`, preserving their original relative tree. Rebase only
Markdown links that leave that tree. Preserve historical prose and code blocks;
hash all archived files and retain original hashes in a manifest. Non-Markdown
evidence remains byte-identical.

Keep the root README unchanged. Retain navigation pages at its linked uppercase
document paths and a byte-identical plot at its existing image URL. Move the
benchmark source-snapshot documentation path and CI integrity-check working
directory to the new layout.

## Consequences and alternatives

Readers can distinguish current instructions from dated evidence. Compatibility
pages add a small amount of navigation maintenance but avoid breaking existing
README links. Historical commands may contain original machine paths; they are
records, not current instructions. Current commands live in the how-to guides.

Renaming everything in place would break links and erase the old organization.
Keeping full duplicated current guides at old paths would create competing
sources of truth. Both alternatives were rejected for this migration.

## References

[Diátaxis](https://diataxis.fr/),
[ADR guidance](https://github.com/architecture-decision-record/architecture-decision-record),
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
[current publication policy](0007-publish-current-documentation.md).
