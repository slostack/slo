---
name: show_git_diff
description: Show the Git diff (HEAD versus worktree) for one repository file as structured before/after content.
when_to_use: Use when the operator asks what changed in a file, or after editing a file to confirm its diff.
group: tui
kind: skill
---

# show_git_diff

## Skill summary

- **Name:** `show_git_diff`
- **Description:** Show one safe Git diff as structured before/after content.
- **When to use:** When an operator asks what changed in a repository file.
- **Group:** `tui`
- **Kind:** `skill`

## Examples

- The operator asks: "What changed in `src/tui/app.py`?"
- You have edited one file and need to verify its repository diff before reporting.

## Guidance

Use the `show_git_diff` tool to inspect one repository file against its committed
`HEAD` version.

## When to use it

- The operator asks what changed in a named file.
- You have edited a file and need to verify the resulting diff before reporting it.

## How to call it

Pass `repository_relative_path` as a forward-slash path relative to the repository
root, for example `src/tui/app.py`. Do not use absolute paths, traversal (`..`), or
`.git/` paths.

## How to read the result

The tool returns JSON containing:

- `repository_relative_path`: normalized repository path.
- `base_content`: `HEAD` text, empty for a newly added file.
- `changed_content`: worktree text, empty for a deleted file.
- `file_state`: `modified`, `added`, `deleted`, or `unchanged`.

An `unchanged` result with both content fields empty is a safe unavailable-diff
stub (for example, invalid path, binary, oversized, missing, or decoding failure).
Tell the operator the diff could not be loaded; do not invent changes.

The operator can use `/diff <repository-relative-path>` to open the same content
in Slo's full-screen diff viewer. The slash command is interactive; this tool
returns structured data for reasoning.
