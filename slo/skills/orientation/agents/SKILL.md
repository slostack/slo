---
name: agents
description: Root entry-point guidance every coding agent follows when it enters a
  repository — which instruction files to read, in what order, and where the per-project
  RESEARCH.md and MEMORY.md live.
when_to_use: Read first when you enter a repository, or when you need the orientation
  rule that tells an agent which deeper skill to open next.
group: orientation
kind: skill
source_prompt: CLAUDE.md
---

# Agent Entry Point

## Skill summary

- **Name:** `agents`
- **Description:** Root entry-point guidance every coding agent follows when it enters a repository — which instruction files to read, in what order, and where the per-project RESEARCH.md and MEMORY.md live.
- **When to use:** Read first when you enter a repository, or when you need the orientation rule that tells an agent which deeper skill to open next.
- **Group:** `orientation`
- **Kind:** `skill`
- **Source prompt:** `CLAUDE.md`

## Examples

- The user asks: "What should the agent read first when it enters this repo?"
- You are defining the repo-entry instructions and need the minimal entry-point contract.
- You are running as Codex, Kimi, or Slo rather than Claude and need the same orientation rules.

## Who this applies to

**Every coding agent**, not just Claude. Claude Code, Codex, Slo, Kimi, and any
other agent that works in this repository follows the rules below. Each agent
family reads its own root instruction file, but they all resolve to the same
orientation contract:

| Agent | Root instruction file it loads | Global copy |
|---|---|---|
| Claude Code | `CLAUDE.md` | `~/.claude/CLAUDE.md` |
| Codex | `AGENTS.md` | `~/.codex/AGENTS.md` |
| Slo | `SLO.md` (falls back to `AGENTS.md`, then `CLAUDE.md`) | `~/.slo/SLO.md` |
| Kimi | `AGENTS.md` | `~/.codex/AGENTS.md` |
| Any other agent | `AGENTS.md` | — |

Read whichever of these exist — the home-directory copy **and** the repo-root
copy. Project instructions specialize general guidance. Conflicting requirements need
an explicit approved exception; locality alone does not silently waive a shared
obligation. Identify both authorities and seek a decision when intent is unclear.

## Guidance

**Multi-language scope:** Begin with `skills/engineering/engineering-routing/SKILL.md`.
Read shared obligations and only affected language/component/framework recipes.
Python-specific examples and commands below are scoped examples, not universal
requirements. For mixed-language work preserve each boundary's approved contract.
Use `skills/engineering/engineering-testing/SKILL.md` for test categories and evidence.

When asked to write, modify, or reason about code in this repository, read
`AGENTS.md` first. Skip this for general questions about syntax, language
semantics, or topics that don't require project context.

After you finish `AGENTS.md`, read the project's `RESEARCH.md` — the index for
the entire project — and its `MEMORY.md` for current state. See **Project
knowledge files** below for where those live.

---

## Project knowledge files

Every project gets two knowledge files. They are **agent-owned**: whichever
agent is working — Claude, Codex, Slo, Kimi, or another — creates them if they
are missing and updates them as work produces new knowledge.

### Canonical location

They live under the Slo home directory, keyed by project name:

```text
${SLO_HOME:-~/.slo}/projects/<project_name>/RESEARCH.md
${SLO_HOME:-~/.slo}/projects/<project_name>/MEMORY.md
```

`SLO_HOME` is the environment variable that roots all Slo data. When it is not
defined, treat it as `~/.slo`. `<project_name>` is the project's directory name
(the basename of the repository checkout).

A repo-root `RESEARCH.md` or `docs/RESEARCH.md` is a **legacy fallback**: read it
if it exists, but write new durable knowledge to the canonical path above so
every agent finds the same file.

### The contract

1. **Read before you plan.** Load both files before planning or changing a
   feature. `RESEARCH.md` tells you why the system is the way it is;
   `MEMORY.md` tells you what is true right now.
2. **Create when missing.** If either file does not exist, create it before
   meaningful implementation work. Do not skip this because the project is small.
3. **Update when work produces learning.** Durable, decision-level learning goes
   to `RESEARCH.md`; changed state and working notes go to `MEMORY.md`.
4. **Neither file is an activity log.** Distill. Do not append a running diary.

Full definitions of both files, and the rule for deciding which one a given fact
belongs in, are in [`readme`](../readme/SKILL.md) under **Project knowledge
files**.

---

## If AGENTS.md or RESEARCH.md is empty

If you open `AGENTS.md` and find it empty or containing only a stub, **stop all
other work** and populate it first:

1. Read [`readme`](../readme/SKILL.md), `pyproject.toml`, and `config/cfg.py`
2. Explore all files under `src/`, `tests/`, and `skills/`
3. Write the populated `AGENTS.md` following the structure in the existing file
   header — see [`generate-agents-md`](../../design-and-analysis/generate-agents-md/SKILL.md)
4. Then populate `${SLO_HOME:-~/.slo}/projects/<project_name>/RESEARCH.md` as a
   full codebase index (every service, workflow, queue, test file) — see
   [`generate-research-md`](../../design-and-analysis/generate-research-md/SKILL.md)
5. Create `${SLO_HOME:-~/.slo}/projects/<project_name>/MEMORY.md` with the
   current state of the work in flight
6. Only then proceed with the original task

The same applies if `RESEARCH.md` is empty — populate it before starting any
coding task.

---

## Workflow Routing — Workflows vs Skills

When the user explicitly says "workflow" or names a formal workflow, **always
load the workflow file directly from `skills/orchestration/workflows/`** —
never substitute a skill with a similar-sounding name.

Named workflows and their exact file paths (use with the `read` tool):

| Workflow | File path |
|---|---|
| Code-Test-Review — implement a spec end-to-end (code → review → completion check) | `skills/orchestration/workflows/code-test-review.md` |
| GitLab Code-Test-Review — the same loop driven from a GitLab issue | `skills/orchestration/workflows/gitlab-code-test-review.md` |
| Specification Development — write a feature spec (context → draft → verify → tasks) | `skills/orchestration/workflows/specification-development.md` |
| Overview — what workflows exist, Pipeline vs Parallel model, evidence-gated progression | `skills/orchestration/workflows/SKILL.md` |

**Critical anti-pattern to avoid:**

| User says | Wrong file | Correct file |
|---|---|---|
| "use the code-test-review workflow" | `skills/coding/code-test-loop/SKILL.md` ✗ | `skills/orchestration/workflows/code-test-review.md` ✓ |
| "run the specification-development workflow" | `skills/design-and-analysis/feature-specifications/SKILL.md` ✗ | `skills/orchestration/workflows/specification-development.md` ✓ |

`code-test-loop` is the coding cadence (write a unit → test → green → repeat). It
is Step 1 *inside* the Code-Test-Review workflow, not the workflow itself.
Loading it instead of the workflow silently drops Step 2 (Code Review) and Step 3
(Completion Check).

---

## Naming & clarity

Always choose **clarity over cleverness** — a name or comment must read plainly to
someone seeing the code for the first time. Ban clever/jargon verbs (no `pump`,
`demux`, `wire`); name a function for exactly what it does. Use the lifecycle verb
vocabulary consistently: `build…` assembles an in-memory object (no persistence,
no goroutines), `Create…` / `Save…` persist an already-built object,
`BuildAndCreate…` does both, and `start…` / `launch…` spawn goroutines/loops
(never folded into `build`). Name producer/consumer pairs across a boundary
`publish…` / `consume…` with a shared noun. Full rules and examples live in
[`naming-and-clarity`](../../coding/naming-and-clarity/SKILL.md);
documentation-comment standards (WHAT/WHO/WHEN) live in
[`method-docstrings`](../../languages/python/method-docstrings/SKILL.md).

---

## Feature requests and specifications

Unless the user explicitly overrides these paths, use:

```text
<feature-requests-root>       = ${SLO_FEATURE_REQUESTS_DIR:-~/.slo/projects/<project_name>/feature-requests}
<feature-specifications-root> = ${SLO_FEATURE_SPECIFICATIONS_DIR:-~/.slo/projects/<project_name>/feature-specifications}
```

One folder per feature. The `overview.md` carries the product framing; each
numbered sibling is one standalone technical sub-spec:

```text
<feature-specifications-root>/
└── 01-example-feature/
    ├── overview.md            # Business + product framing, ends with a brief technical overview
    ├── 01.a.1-first-slice.md  # Technical sub-spec (one of n)
    ├── 01.a.2-second-slice.md
    └── plan.md
```

Follow the style guide in
[`feature-specifications`](../../design-and-analysis/feature-specifications/SKILL.md).

### JIRA solution specifications

Store JIRA ticket solution specifications in
`<feature-specifications-root>/<ticket-id>/`. Each ticket gets its own folder
with a markdown file named `<TICKET-ID>-<Short-Title>.md` following the same
style guide. These specs serve as implementation blueprints that developers can
build from directly.
