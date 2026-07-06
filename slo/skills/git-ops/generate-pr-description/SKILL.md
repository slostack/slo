---
name: generate-pr-description
description: Generate a PR title and body from the branch, commits, diff, and repository
  PR template.
when_to_use: Use when the user wants PR-ready text before opening the pull request.
group: git-ops
kind: skill
---

# Generate PR Description

## Skill summary

- **Name:** `generate-pr-description`
- **Description:** Generate a PR title and body from the branch, commits, diff, and repository PR template.
- **When to use:** Use when the user wants PR-ready text before opening the pull request.
- **Group:** `git-ops`
- **Kind:** `skill`

## Examples

- The user asks: "Draft the PR description for this branch."
- You need a template-aware PR body instead of writing one from scratch.

## Guidance

## Platform detection

Detect the remote host first, mirroring how `ship-feature` does it:

```bash
git remote get-url origin
```

- URL contains `github.com` → **GitHub path**: the PR-template location below
  (`.github/PULL_REQUEST_TEMPLATE.md`) and the `gh`-oriented flow apply.
- URL contains `gitlab.com` or a self-hosted GitLab host → **GitLab path**: look
  for a merge-request template under `.gitlab/merge_request_templates/` instead,
  and hand off to `glab mr create` rather than `gh pr create`.

The workflow below is the GitHub-path example; use the `glab` equivalent for GitLab.

## Goal

Produce a PR title and body that actually match the branch, diff, and repository
template instead of improvising a vague summary.

## Workflow

1. Gather git context:
   ```bash
   git rev-parse --abbrev-ref HEAD
   git log --oneline main..HEAD
   git diff main...HEAD --stat
   ```
2. Load the repository PR template if it exists.
   - Start with `.github/PULL_REQUEST_TEMPLATE.md`.
   - If there are multiple templates, choose the one closest to the changed area.
3. Derive the PR title.
   - Prefer the repo's own title convention.
   - Otherwise use the ticket ID plus an imperative summary when one is available.
4. Fill every template section with real content from the diff.
   - Explain **why** the change exists.
   - Summarize **what** changed.
   - Record **how it was verified**.
   - Call out **risks / rollout concerns** honestly.
5. If no template exists, output a concise fallback body with sections for Summary,
   Verification, and Risks.
6. Return the title and full body ready for `create-pull-request`.

## Non-Negotiables

- Do not leave placeholder text unfilled.
- Do not dump a raw diff as the PR description.
- If the repo has a PR template, use it instead of inventing your own structure.
