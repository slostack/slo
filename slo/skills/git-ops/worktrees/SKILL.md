---
name: worktrees
description: Use git worktrees for latest-main reads, parallel branches, and reviewer/writer
  isolation without disturbing the current checkout.
when_to_use: Use when you need clean main context or parallel branch work while preserving
  the user's current working tree.
group: git-ops
kind: skill
---

# Worktrees

## Skill summary

- **Name:** `worktrees`
- **Description:** Use git worktrees for latest-main reads, parallel branches, and reviewer/writer isolation without disturbing the current checkout.
- **When to use:** Use when you need clean main context or parallel branch work while preserving the user's current working tree.
- **Group:** `git-ops`
- **Kind:** `skill`

## Examples

- The user asks: "Inspect origin/main without touching my current branch."
- You want a separate clean checkout for a reviewer session or an alternate implementation path.

## Guidance

## Goal

Use git worktrees to inspect `origin/main` or work on parallel branches without
disturbing the user's current checkout.

## Preferred Use Cases

- Read the latest `main` while the current branch is dirty.
- Spin up a reviewer checkout alongside a writer checkout.
- Compare two implementation approaches in parallel.
- Prepare a clean branch from `origin/main` without branch-hopping.

## Workflow

1. Fetch the latest remote state:
   ```bash
   git fetch origin main
   ```
2. Add a read-only-style main worktree when you only need clean context:
   ```bash
   git worktree add ../.worktrees/<repo>-main origin/main
   ```
3. Add a new branch worktree when you need to make changes in parallel:
   ```bash
   git worktree add -b <branch-name> ../.worktrees/<repo>-<purpose> origin/main
   ```
4. Do the investigation or implementation in the new path.
5. Remove the worktree when finished:
   ```bash
   git worktree remove ../.worktrees/<repo>-<purpose>
   ```
6. If worktrees are impossible in the current environment, only then fall back to
   stash → checkout → restore, and record the original branch / status first.

## Non-Negotiables

- Do not disturb the user's current working tree when a worktree will do.
- Clean up temporary worktrees when the task is complete.
- If you fall back to stash/checkout, restore the original state exactly.
