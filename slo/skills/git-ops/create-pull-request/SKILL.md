---
name: create-pull-request
description: Open a pull request against the correct base branch using a generated,
  template-aware title and body.
when_to_use: Use after the branch is pushed and the user wants a pull request created
  or prepared.
group: git-ops
kind: workflow
---

# Create Pull Request

## Skill summary

- **Name:** `create-pull-request`
- **Description:** Open a pull request against the correct base branch using a generated, template-aware title and body.
- **When to use:** Use after the branch is pushed and the user wants a pull request created or prepared.
- **Group:** `git-ops`
- **Kind:** `workflow`

## Examples

- The user asks: "Open a PR for this branch."
- You already pushed the branch and now need the exact PR-creation flow.

## Guidance

## Platform detection

Detect the remote host before choosing a CLI, mirroring how `ship-feature` does it:

```bash
git remote get-url origin
```

- URL contains `github.com` → **GitHub path**, use `gh` (the commands below).
- URL contains `gitlab.com` or a self-hosted GitLab host → **GitLab path**, use
  `glab` (e.g. `glab mr create --title ... --description ... --target-branch main`).

The commands in this skill are the GitHub-path examples; for GitLab use the
`glab` equivalent. If the host cannot be determined, ask the user.

## Goal

Open a pull request against the right base branch with a title and body that were
prepared deliberately rather than improvised at the last second.

## Workflow

1. Verify the branch is pushed and is not `main`.
2. Generate the title and body first with `generate-pr-description`.
3. Confirm the base branch.
   - Default to `main` unless the repo or the user says otherwise.
4. If GitHub CLI authentication is missing, stop and tell the user to run:
   ```bash
   gh auth login
   ```
5. Create the PR:
   ```bash
   gh pr create --title "<title>" --body "<body>" --base main
   ```
6. Return the PR URL.
7. If the repo uses PR notifications or follow-up threads, mention that next step to the user.

## Non-Negotiables

- Never open a PR from `main`.
- Never skip the title/body generation step when a repo template exists.
- Do not auto-merge or delete branches unless the user explicitly asks.
