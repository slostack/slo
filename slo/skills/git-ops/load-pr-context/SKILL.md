---
name: load-pr-context
description: Collect the current PR's metadata, diff themes, review comments, and
  next actions into one brief.
when_to_use: Use when the user asks about the current PR, wants review context, or
  needs to follow up on feedback.
group: git-ops
kind: skill
---

# Load PR Context

## Skill summary

- **Name:** `load-pr-context`
- **Description:** Collect the current PR's metadata, diff themes, review comments, and next actions into one brief.
- **When to use:** Use when the user asks about the current PR, wants review context, or needs to follow up on feedback.
- **Group:** `git-ops`
- **Kind:** `skill`

## Examples

- The user asks: "What is going on in this PR?"
- You need the PR summary and comment context before responding to review.

## Guidance

## Platform detection

Detect the remote host first, mirroring how `ship-feature` does it:

```bash
git remote get-url origin
```

- URL contains `github.com` → **GitHub path**, use `gh` (the commands below).
- URL contains `gitlab.com` or a self-hosted GitLab host → **GitLab path**, use
  the `glab` equivalent (e.g. `glab mr view <number>`, `glab mr diff <number>`).

The commands in this skill are the GitHub-path examples; use the `glab`
equivalent for GitLab. If the host cannot be determined, ask the user.

## Goal

Build one reliable brief for the current pull request so review, debugging, and
follow-up work start from facts instead of scattered CLI output.

## Workflow

1. Identify the PR.
   - Prefer an explicit PR URL or number from the user.
   - Otherwise derive it from the current branch.
2. Gather the PR metadata:
   ```bash
   gh pr view <number> --json number,title,body,baseRefName,headRefName,url,reviewDecision
   ```
3. Gather the change shape:
   ```bash
   git log --oneline <base>..HEAD
   git diff <base>...HEAD --stat
   ```
4. Gather review comments and discussion threads.
5. If the title or branch includes a ticket ID, note it and load any linked issue context the repo workflow expects.
6. Summarize the PR in a structured brief:
   - identity
   - intent
   - changed surfaces
   - open review feedback
   - risks
   - next recommended actions

## Non-Negotiables

- Do not assume a PR exists for the current branch; verify it.
- Prefer local branch + PR metadata together, not one without the other.
- If multiple PRs could match, ask instead of guessing.
