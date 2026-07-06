---
name: commit-and-push
description: Stage the intended files, confirm a repo-appropriate commit message,
  commit safely, and push to the correct upstream branch.
when_to_use: Use when the user explicitly wants local work saved to git or pushed
  to the remote branch.
group: git-ops
kind: workflow
---

# Commit and Push

## Skill summary

- **Name:** `commit-and-push`
- **Description:** Stage the intended files, confirm a repo-appropriate commit message, commit safely, and push to the correct upstream branch.
- **When to use:** Use when the user explicitly wants local work saved to git or pushed to the remote branch.
- **Group:** `git-ops`
- **Kind:** `workflow`

## Examples

- The user asks: "Commit these changes and push the branch."
- You have a reviewed diff and need the safe stage → commit → push sequence.

## Guidance

## Goal

Save the intended work to git, with explicit staging, a confirmed commit message,
and the correct push behavior for first vs subsequent pushes.

## Workflow

1. Verify the branch and status:
   ```bash
   git status --short --branch
   git rev-parse --abbrev-ref HEAD
   ```
2. If the branch is `main`, stop. Route into `create-feature-branch` first.
3. Run the repo's formatter and the right tests for the changed surface when the
   task requires validation. If you skip verification, say so explicitly.
4. Stage only the intended files:
   ```bash
   git add <specific-file-1> <specific-file-2>
   ```
5. Derive the commit message using `branching-and-commit-conventions`.
6. Show the proposed message to the user and wait for confirmation before committing.
7. Commit:
   ```bash
   git commit -m "<confirmed message>"
   ```
8. Decide whether this is the first push for the branch.
   - No upstream yet:
     ```bash
     git push -u origin HEAD
     ```
   - Upstream already exists:
     ```bash
     git push
     ```
9. If this was the first push and the user wants a PR, route into
   `generate-pr-description` and then `create-pull-request`.

## Non-Negotiables

- Never commit unless the user asked for a commit.
- Never default to `git add .` or `git add -A`.
- Never amend or force-push a published commit unless the user explicitly asks.
- Always make the commit message visible to the user before creating the commit.
