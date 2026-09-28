# Release evidence templates

This directory holds **blank operator templates**, not release results. Copy the
canonical template to the canonical specifications directory before recording a
release. Do not fill, commit, or publish a template as evidence unless its
commands were actually run and their artifacts retained.

## Operator process

1. Resolve the canonical specifications root from the release checkout:
   `readlink -f specifications`.
2. Create `<canonical-specifications-root>/release-evidence/<tag>.md` from
   [`template.md`](template.md).
3. Record the exact immutable tag and commit, timestamps, command lines, exit
   statuses, and redacted failures. Never record credentials or unredacted
   environment values.
4. Attach or link durable CI artifacts (wheel hash, Linux matrix, macOS gate,
   hosted URL/hash) before treating the release verification as complete.

The template is repository-local only because this checkout has no writable
`specifications/` symlink target.
