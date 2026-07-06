---
name: claude
description: Root entry-point guidance for the prompt library.
when_to_use: Read when you need the first-orientation rule that tells an agent which
  deeper prompt to open next.
group: orientation
kind: skill
source_prompt: CLAUDE.md
---

# CLAUDE.md Entry Point

## Skill summary

- **Name:** `claude`
- **Description:** Root entry-point guidance for the prompt library.
- **When to use:** Read when you need the first-orientation rule that tells an agent which deeper prompt to open next.
- **Group:** `orientation`
- **Kind:** `skill`
- **Source prompt:** `CLAUDE.md`

## Examples

- The user asks: "What should the agent read first when it enters this repo?"
- You are defining the repo-entry instructions and need the minimal CLAUDE.md contract.

## Guidance

When asked to write, modify, or reason about code in this repository, read `AGENTS.md` first. Skip this for general questions about syntax, language semantics, or topics that don't require project context.

After you finish the AGENTS.md read the skills/orientation/research/SKILL.md which is an index for the entire project

## If AGENTS.md or skills/orientation/research/SKILL.md is empty

If you open `AGENTS.md` and find it empty or containing only a stub, **stop all other work** and populate it first:

1. Read `skills/orientation/readme/SKILL.md`, `pyproject.toml`, `config/cfg.py`
2. Explore all files under `src/`, `tests/`, `code_prompts/`
3. Write the populated `AGENTS.md` following the structure in the existing file header
4. Then populate `skills/orientation/research/SKILL.md` as a full codebase index (every service, workflow, queue, test file)
5. Only then proceed with the original task

The same applies if `skills/orientation/research/SKILL.md` is empty — populate it before starting any coding task.

## Workflow Routing — Workflows vs Skills

When the user explicitly says "workflow" or names a formal workflow, **always load the workflow file directly from `skills/design-and-analysis/workflows/`** — never substitute a skill with a similar-sounding name.

Named workflows and their exact file paths (use with the `read` tool):

| Workflow | File path |
|---|---|
| Code-Test-Review — implement a spec end-to-end (code → review → completion check) | `skills/design-and-analysis/workflows/code-test-review.md` |
| Specification Development — write a feature spec (context → draft → verify → tasks) | `skills/design-and-analysis/workflows/specification-development.md` |
| Overview — what workflows exist, Pipeline vs Parallel model, confirmation behavior | `skills/design-and-analysis/workflows/SKILL.md` |

**Critical anti-pattern to avoid:**

| User says | Wrong file | Correct file |
|---|---|---|
| "use the code-test-review workflow" | `skills/coding/code-test-loop/SKILL.md` ✗ | `skills/design-and-analysis/workflows/code-test-review.md` ✓ |
| "run the specification-development workflow" | `skills/design-and-analysis/feature-specifications/SKILL.md` ✗ | `skills/design-and-analysis/workflows/specification-development.md` ✓ |

`code-test-loop` is the coding cadence (write a unit → test → green → repeat). It is Step 1 *inside* the Code-Test-Review workflow, not the workflow itself. Loading it instead of the workflow silently drops Step 2 (Code Review) and Step 3 (Completion Check).

---

## JIRA Solution Specifications

Store JIRA ticket solution specifications in `<feature-specifications-root>/<ticket-id>/`. Each ticket gets its own folder with a markdown file named `<TICKET-ID>-<Short-Title>.md` following the style guide in `skills/design-and-analysis/feature-specifications/SKILL.md`. These specs serve as implementation blueprints that developers can build from directly.
