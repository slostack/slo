# Release evidence — `<tag>` (TEMPLATE: not evidence)

> Copy this file to `<canonical-specifications-root>/release-evidence/<tag>.md`.
> Replace every placeholder only with observed, redacted evidence. This blank
> file never asserts that a release succeeded.

## Identity

| Field | Observed value |
| --- | --- |
| Immutable tag | `<tag>` |
| Commit SHA | `<commit>` |
| Operator / CI pipeline | `<identifier>` |
| Started / finished (UTC) | `<timestamps>` |

## Build and local pipx recovery

| Check | Command / artifact | Exit | Timestamp (UTC) | Notes |
| --- | --- | --- | --- | --- |
| Wheel build | `<command>` | `<exit>` | `<time>` | `<artifact path>` |
| Wheel SHA-256 | `sha256sum <wheel>` | `<exit>` | `<time>` | `<hash>` |
| Disposable local-wheel pipx install | `<command>` | `<exit>` | `<time>` | `<pipx root>` |
| Direct pipx regeneration | `<command>` | `<exit>` | `<time>` | `<plain script observed>` |
| Tagged finalization + hostile import proof | `<command>` | `<exit>` | `<time>` | `<wrapper/hash>` |

## Required CI release gates

| Gate | Command / URL | Exit | Timestamp (UTC) | Artifact / redacted failure |
| --- | --- | --- | --- | --- |
| Linux non-E2E matrix | `<CI job / command>` | `<exit>` | `<time>` | `<artifact>` |
| Black format check | `poetry run black --check src/ tests/` | `<exit>` | `<time>` | `<artifact/failure>` |
| Static lint | `make lint` | `<exit>` | `<time>` | `<artifact/failure>` |
| macOS hosted installer | `<GitLab macOS job>` | `<exit>` | `<time>` | `<artifact/failure>` |
| Hosted installer URL/hash | `<URL>; sha256sum>` | `<exit>` | `<time>` | `<URL/hash>` |

## Redacted failures and exceptions

- `<timestamp> — <gate> — <redacted diagnostic> — <disposition>`

## Sign-off

- Evidence collected by: `<operator>`
- Review status: `<pending / accepted / rejected>`
- This record contains no credentials, tokens, home paths, or unredacted
  environment values: `<confirmed>`
