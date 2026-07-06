---
name: fix-pr-review
description: Address PR review comments, integrate the latest base branch safely,
  rerun verification, and push the follow-up.
when_to_use: Use when the user asks to fix PR comments, resolve conflicts, or make
  the branch mergeable after review.
group: git-ops
kind: workflow
---

# Fix PR Review

## Skill summary

- **Name:** `fix-pr-review`
- **Description:** Address PR review comments, integrate the latest base branch safely, rerun verification, and push the follow-up.
- **When to use:** Use when the user asks to fix PR comments, resolve conflicts, or make the branch mergeable after review.
- **Group:** `git-ops`
- **Kind:** `workflow`

## Examples

- The user asks: "Fix the PR review comments and push the updates."
- A PR is blocked on feedback or base-branch conflicts and needs a clean follow-up pass.

## Guidance

## Goal

Address PR feedback cleanly: understand the review state, integrate the latest
base branch safely, fix the requested issues, verify the result, and push the
follow-up without making git history worse.

## Workflow

1. Load `load-pr-context` first so the current review state is explicit.
2. Classify comments into:
   - required fix
   - suggested improvement
   - question / clarification
3. Refresh the branch against the latest base branch.
   - Follow repo instructions if they specify merge vs rebase.
   - If the repo is silent, prefer merging the updated base branch instead of force-push-heavy rebasing.
4. Fix the applicable comments and resolve conflicts.
5. Run the relevant formatter and tests for the changed area.
6. Stage specific files only, propose a follow-up commit message, commit, and push.
7. Report what was fixed, what was intentionally skipped, and what still needs a human decision.

## Non-Negotiables

- Do not silently ignore comments.
- Do not force-push by default.
- Do not claim a PR is mergeable without rerunning the relevant verification.
