---
name: git-ops-orchestrator
description: Gateway workflow for routing a git request into the right branching,
  commit, PR, or worktree skill.
when_to_use: Use when the user asks for git help and you need to decide whether the
  next step is syncing main, branching, committing, opening a PR, loading PR context,
  fixing review feedback, or using a worktree.
group: git-ops
kind: workflow
---

# Git Ops Orchestrator

## Skill summary

- **Name:** `git-ops-orchestrator`
- **Description:** Gateway workflow for routing a git request into the right branching, commit, PR, or worktree skill.
- **When to use:** Use when the user asks for git help and you need to decide whether the next step is syncing main, branching, committing, opening a PR, loading PR context, fixing review feedback, or using a worktree.
- **Group:** `git-ops`
- **Kind:** `workflow`

## Examples

- The user asks: "Help me get this branch ready for a PR." Route into the smallest relevant git-ops workflow.
- The user asks: "I need the latest main without disturbing my current changes." Route into the worktree flow.

## Guidance

## Routed skills

This orchestrator can route into every git-ops skill:

- `branching-and-commit-conventions` — the policy all other git-ops skills assume
- `sync-main` — refresh local `main`
- `create-feature-branch` — cut a task branch from updated `main`
- `commit-and-push` — safe stage → commit → push flow
- `generate-pr-description` — template-aware PR title and body
- `create-pull-request` — open the PR against the right base
- `load-pr-context` — build a brief for the current PR
- `fix-pr-review` — address review comments / conflicts
- `worktrees` — non-disruptive latest-main or parallel-branch work
- `ship-feature` — full end-to-end lifecycle (commit → push → PR/MR → merge → back to main)
- `release-process` — cut a versioned release (bump, tag, publish)
- `gitlab-issues` — create/manage GitLab issues

## Goal

Route a git-related request into the **smallest safe git workflow** needed next.
Use this skill to avoid mixing branch creation, commit policy, PR generation,
and review follow-up into one fuzzy instruction.

## Routing Order

1. **Need the policy first?**
   - Load `branching-and-commit-conventions` when the user is asking what rules apply,
     or when later git steps would otherwise guess.
2. **Need the latest base branch?**
   - Load `sync-main` when the user asks to pull the latest `main`.
   - Load `worktrees` instead when the current checkout must remain untouched.
3. **Need a new branch for new work?**
   - Load `create-feature-branch` after `sync-main`.
4. **Need to save local work?**
   - Load `commit-and-push`.
5. **Need a PR?**
   - Load `generate-pr-description` first, then `create-pull-request`.
6. **Need to understand or fix an existing PR?**
   - Load `load-pr-context` to read the PR.
   - Load `fix-pr-review` when the task is to address review comments or conflicts.
7. **Need the full ship lifecycle in one go?**
   - Load `ship-feature` when the user asks to ship / land / "commit, push, PR, and merge"
     an already-implemented feature end-to-end. (Confirm-first by default; auto-merge is opt-in.)
8. **Need to cut a release?**
   - Load `release-process` when the user asks to release a version, bump the version, or tag/publish.
9. **Working on GitLab issues?**
   - Load `gitlab-issues` when the user asks to create, list, or manage GitLab issues.

## Output Format

Return a short ordered list:

```text
Relevant git-ops skills:
1. <skill-name> — why it applies now
2. <skill-name> — why it applies next
```

If none apply, return `Relevant git-ops skills: none`.
