# Changelog

Noteworthy changes to this project are recorded here, following
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Documentation organized into tutorials, how-to guides, reference, and explanation.
- An ADR index, template, and explicitly retrospective records for admission,
  fallback, stream ownership, and request/attempt observations.
- Development guidance and automated local-link/evidence-integrity checks.
- Dedicated asset and evidence directories with SHA256 checksums.

### Changed

- README and documentation links point directly to current guides.
- Legacy documents remain local under a Git-ignored directory; compatibility
  pages are removed from the published tree.
- CI and benchmark source snapshots use the reorganized documentation paths.

No release date is inferred from milestone acceptance or the package metadata's
`0.1.0`. This changelog begins with the documentation migration.
[Dated validation results](docs/reference/validation.md) summarize the accepted
first-version scope.
