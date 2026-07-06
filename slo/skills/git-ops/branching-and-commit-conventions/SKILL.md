---
name: branching-and-commit-conventions
description: Repo-aware git safety rails, branch naming rules, commit message defaults,
  and PR guardrails distilled into one operating policy.
when_to_use: Use before creating a branch, commit, or PR when you need the git rules
  that all of the other git-ops skills assume.
group: git-ops
kind: skill
source_prompt: branching-and-commit-conventions.md
---

# Branching and Commit Conventions

## Skill summary

- **Name:** `branching-and-commit-conventions`
- **Description:** Repo-aware git safety rails, branch naming rules, commit message defaults, and PR guardrails distilled into one operating policy.
- **When to use:** Use before creating a branch, commit, or PR when you need the git rules that all of the other git-ops skills assume.
- **Group:** `git-ops`
- **Kind:** `skill`
- **Source prompt:** `branching-and-commit-conventions.md`

## Examples

- The user asks: "What git conventions should I follow in this repo?"
- You are about to branch or commit and want the policy before touching git.

## Guidance

## Goal

Resolve repo-specific git conventions into one safe operating policy before
branching, committing, pushing, or opening a PR.

## Precedence

1. **Repo-local instructions win.** Read `AGENTS.md`, `skills/orientation/claude/SKILL.md`, `CONTRIBUTING.md`,
   or other repo docs first when they define git rules.
2. **User instructions override defaults** when explicit.
3. **Slo defaults below apply only when the repo is silent or inconsistent.**

## Non-Negotiable Safety Rules

- Never commit directly on `main`.
- Never commit unless the user asked for a commit.
- Never amend a published commit unless the user explicitly asks.
- Never force-push `main` or `master`.
- Stage specific files only; do not default to `git add .` or `git add -A`.
- Check `git status --short --branch` before any branch / commit / push action.
- Prefer `worktrees` when you need clean `main` context without touching the current tree.

## Slo Default Branch Naming

Use the repo's own convention when it exists. Otherwise default to:

- With ticket ID: `<TICKET-ID>-<short-kebab-description>`
- Without ticket ID: `feature-<short-kebab-description>`

Examples:

- `AGI-1234-fix-pr-template-routing`
- `feature-refresh-skills-index`

If the repo already standardizes on lowercase ticket-only names or typed prefixes,
preserve that repo convention instead of rewriting it.

## Slo Default Commit Messages

Use the repo's own commit format when documented. Otherwise default to:

- First substantial commit on a ticket branch: `<TICKET-ID>: <imperative summary>`
- No ticket: `<type>: <imperative summary>` where type is one of `feat`, `fix`, `refactor`, `test`, `docs`, `chore`
- Follow-up commits may use the short typed form (`fix: ...`, `test: ...`)

Keep the subject line short and specific. Add a body only when the repo or the
user wants more detail.

## Commit Co-Author Trailer (single source of truth)

This is the canonical rule that every other git-ops skill defers to. When a
commit is AI-assisted, append this exact trailer as the last line of the commit
message body:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```

Do not hardcode a model version in the trailer. The `noreply@anthropic.com`
address is intentional and must be preserved verbatim.

## Push and PR Defaults

- First push: `git push -u origin HEAD`
- Later pushes: `git push`
- Default PR base: `main`
- Do not force-push review follow-ups unless the user explicitly requests that strategy.

## Companion Skills

- `sync-main` — refresh local `main`
- `create-feature-branch` — cut a task branch from updated `main`
- `commit-and-push` — safe stage → commit → push flow
- `generate-pr-description` and `create-pull-request` — PR preparation and creation
- `load-pr-context` and `fix-pr-review` — review follow-up flows
- `worktrees` — non-disruptive latest-main or parallel-branch work
