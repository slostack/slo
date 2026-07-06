---
name: sync-main
description: Refresh local main from remote safely, without clobbering in-flight work.
when_to_use: Use before starting a new task or whenever the user asks to pull the
  latest main branch.
group: git-ops
kind: skill
---

# Sync Main

## Skill summary

- **Name:** `sync-main`
- **Description:** Refresh local main from remote safely, without clobbering in-flight work.
- **When to use:** Use before starting a new task or whenever the user asks to pull the latest main branch.
- **Group:** `git-ops`
- **Kind:** `skill`

## Examples

- The user asks: "Pull the latest main before we start."
- You want a fresh branch base and need to make sure local `main` matches origin first.

## Guidance

## Goal

Refresh local `main` from remote **without clobbering uncommitted work**.

## Workflow

1. Inspect the current state first:
   ```bash
   git status --short --branch
   ```
2. If the current checkout is dirty and the user only needs the latest `main`
   for reading, comparison, or context gathering, stop and use `worktrees` instead.
3. If the user explicitly wants in-place `main` updated while the current checkout
   is dirty, ask before stashing, checking out, or moving branches.
4. When it is safe to update local `main`:
   ```bash
   git fetch origin
   git checkout main
   git pull origin main
   ```
5. If the repo uses a different default branch, detect it first and substitute it
   consistently instead of assuming `main`.
6. Report the resulting branch and whether it is up to date with origin.

## Non-Negotiables

- Never discard or stash user changes without confirmation.
- Never pretend a dirty checkout is safe just because `git pull` would fail loudly.
- Prefer `worktrees` over branch-hopping when the task is read-only or comparative.
