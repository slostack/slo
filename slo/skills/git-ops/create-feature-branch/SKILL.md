---
name: create-feature-branch
description: Create a task-scoped feature branch from the latest main using repo conventions
  or safe Slo defaults.
when_to_use: Use when new implementation or debugging work needs its own branch rather
  than happening on main.
group: git-ops
kind: skill
---

# Create Feature Branch

## Skill summary

- **Name:** `create-feature-branch`
- **Description:** Create a task-scoped feature branch from the latest main using repo conventions or safe Slo defaults.
- **When to use:** Use when new implementation or debugging work needs its own branch rather than happening on main.
- **Group:** `git-ops`
- **Kind:** `skill`

## Examples

- The user asks: "Create a branch for AGI-1234 before we code."
- You finished planning and need a clean task branch from updated `main`.

## Guidance

## Goal

Create a clean task branch from the latest base branch using repo conventions or
the Slo defaults from `branching-and-commit-conventions`.

## Workflow

1. Ensure the base branch is fresh.
   - If local `main` is stale, run `sync-main` first.
   - If the current working tree must remain untouched, use `worktrees` instead.
2. Inspect the current checkout:
   ```bash
   git status --short --branch
   ```
3. If there are uncommitted changes on `main`, do not branch blindly. Ask whether
   the branch should be created from dirty `HEAD` or from a clean updated base.
4. Derive the branch name.
   - Repo-local naming convention wins.
   - Otherwise default to `<TICKET-ID>-<short-kebab-description>`.
   - If there is no ticket, use `feature-<short-kebab-description>`.
5. When the base and branch name are clear:
   ```bash
   git checkout -b <branch-name>
   ```
6. Confirm the new current branch with:
   ```bash
   git rev-parse --abbrev-ref HEAD
   ```

## Non-Negotiables

- Never start implementation work directly on `main`.
- One branch should correspond to one focused task or feature slice.
- If the task is exploratory or parallel to existing work, prefer `worktrees` over repeatedly switching branches.
