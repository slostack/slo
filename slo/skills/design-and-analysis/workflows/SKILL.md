---
name: workflows
description: "Overview of Slo's formal workflow system: pipeline vs parallel execution,
  context handoff, confirmation behavior, the named workflows available for explicit
  use, and the routing rules: 'dynamic workflows' / 'dyanmic workflows' (no detach
  qualifier) = sync in-session execution via spawn_sub_agents; a detach-qualified
  request ('headless' / 'detached' / 'independent' dynamic workflows, or a named
  workflow with detach wording) = detached headless orchestrator via launch_workflow;
  a detached orchestrator never calls launch_workflow."
when_to_use: 'Use only when the user explicitly asks about workflows, asks to use a
  named workflow, wants a compound task executed through a formal multi-step workflow
  instead of ad-hoc skill loading, or says "dynamic workflows" / "dyanmic workflows"
  to request in-session orchestrated multi-agent workflow execution. Note: an
  unqualified "dynamic workflows" phrase runs in-session (sync dynamic workflow); only
  a detach-qualified phrase ("headless dynamic workflows", "detached dynamic
  workflows", "independent dynamic workflows") routes to the headless-orchestration
  skill.'
group: design-and-analysis
kind: skill
source_prompt: workflows/overview.md
---

# Workflows

## Skill summary

- **Name:** `workflows`
- **Description:** Overview of Slo's formal workflow system: pipeline vs parallel execution, context handoff, confirmation behavior, the named workflows available for explicit use, and the routing rules: "dynamic workflows" / "dyanmic workflows" (no detach qualifier) = sync in-session execution via spawn_sub_agents; a detach-qualified request ("headless" / "detached" / "independent" dynamic workflows, or a named workflow with detach wording) = detached headless orchestrator via launch_workflow; a detached orchestrator never calls launch_workflow.
- **When to use:** Use only when the user explicitly asks about workflows, asks to use a named workflow, wants a compound task executed through a formal multi-step workflow instead of ad-hoc skill loading, or says `dynamic workflows` / `dyanmic workflows` to request in-session orchestrated multi-agent workflow execution. An unqualified "dynamic workflows" phrase runs in-session (sync dynamic workflow); a detach-qualified phrase routes to the headless-orchestration skill.
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Source prompt:** `workflows/overview.md`

## Examples

- The user asks: "What workflows does Slo support?"
- The user asks: "Use the formal workflow system for this task instead of improvised routing."
- Another skill explicitly tells you to load a named workflow before continuing.
- The user asks: "Use dynamic workflows for this task." Treat that as a sync in-session orchestrator / multi-agent workflow request (not as detachment); run the workflow in this session via spawn_sub_agents.
- The user asks: "Use headless dynamic workflows for this task." That is a detach-qualified request — route to the headless-orchestration skill instead.

## Available workflows and their sub-skills (read this first)

You do not need to open a workflow file to learn what it depends on — the full
roster is here:

| Workflow file | Type | Sub-skills it sequences |
|---|---|---|
| [specification-development.md](specification-development.md) | Pipeline | `feature-specifications-pre-hook`, `feature-specifications`, `feature-specifications-post-hook`, `feature-specification-verification`, `breakdown-feature-spec-to-tasks` |
| [code-test-review.md](code-test-review.md) | Pipeline | `code-test-loop`, `review-feature-code`, `is-the-feature-completed` (+ always-on `named-arguments-and-type-hints`, `declarative-method-structure`, `method-docstrings`, `test-verification-policy`) |
| [gitlab-code-test-review.md](gitlab-code-test-review.md) | Pipeline | Code-Test-Review sub-skills + `git-ops/gitlab-issues`, `git-ops/ship-feature` |

## Guidance

## Specialized-use rule

This is a **specialized skill**.

Load it only when:
- the user explicitly asks about workflows,
- the user explicitly asks to execute a named workflow,
- or another skill explicitly routes the task into the formal workflow system.

If the user says `dynamic workflows` or `dyanmic workflows` **without a detach qualifier**, treat that phrase as an explicit request to run the workflow in-session via `spawn_sub_agents` (sync dynamic workflow). If the user adds a detach qualifier — "headless", "detached", or "independent" applied to the request, or detach wording like "in the background" / "without blocking" — route to the `headless-orchestration` skill instead (headless dynamic workflow). A detached orchestrator never calls `launch_workflow`.

Do **not** load this skill as an always-on default for normal coding or analysis work.

# Workflow Prompts — Overview

Workflows are structured, multi-step instruction sequences that direct an agent through a compound task. Each step in a workflow is a prompt or rule that already exists in the system. The workflow's job is to sequence those prompts, pass context between them, and enforce completion before moving to the next step.

Any agent capable of following sequential instructions and loading prompt files can execute a workflow. These are not Claude-specific. They are model-agnostic operation plans.

---

## What a Workflow Is Not

A workflow is not a script. It is not a chain of API calls. It is an instruction set that tells an *agent* — operating within its usual tool-and-context environment — how to sequence a compound task that would be too large or too error-prone to handle as a single flat prompt.

A workflow prompt defines:

- the **type** of the workflow (Pipeline or Parallel),
- the **ordered steps** and which prompt file governs each,
- **what context must be passed** between steps,
- **when to pause for confirmation** (manual mode vs. auto mode),
- **the exit condition** — what "done" means for the whole workflow.

---

## Workflow Types

### Pipeline

Steps execute **in order**. The output of each step is consumed — in whole or in part — by the next step. No step starts until the previous step is complete and its outputs are available in context.

Use Pipeline when:

- steps have a strict dependency chain (you cannot spec a feature before gathering context; you cannot verify a spec that does not exist yet),
- the output of step N is required input for step N+1,
- concurrent execution would produce conflicting or redundant work,
- the full context window is needed to correctly execute later steps.

A Pipeline workflow may spawn sub-agents within a single step, but the *steps themselves* are sequential.

### Parallel

Steps (or groups of steps) execute **concurrently**. Sub-agents, threads, or independently-dispatched prompts work on different parts of the problem at the same time. Results are collected and synthesized after all concurrent work completes.

Use Parallel when:

- steps are independent of each other (no shared mutable state, no dependency between their outputs),
- the problem can be cleanly decomposed into non-overlapping sub-problems,
- latency matters more than sequential clarity,
- a single agent cannot hold all the context needed across all sub-problems simultaneously.

A Parallel workflow requires explicit synthesis once all branches complete. The synthesis step is always a single sequential step that merges results.

---

## Invariants — These Always Hold

Regardless of workflow type, these rules are non-negotiable:

1. **AGENTS.md remains in force.** Every rule in `AGENTS.md` for this repository governs the agent throughout the entire workflow. A workflow prompt does not override, suspend, or narrow the rules in `AGENTS.md`.

2. **The agent retains full access to all tools and prompts.** While executing any step, the agent may read additional prompt files, search the KB, use grep/glob/read tools, and consult any rule file it judges relevant. The workflow specifies the mandatory steps; it does not prevent the agent from consulting the full system.

3. **Each step must complete before the next begins (Pipeline).** Completing a step means: the step's prompt has been executed fully, its outputs exist in the conversation, and any required confirmation has been received.

4. **Context accumulates across steps.** The agent carries forward everything produced by prior steps — context bundles, PRE-hook outputs, verification reports, task lists. Later steps should explicitly reference earlier outputs rather than re-deriving them from scratch.

5. **No step may be skipped.** A step that produces no useful output for a particular feature is still executed — it simply returns a minimal output (e.g. "Granularity: OK — no split needed"). The workflow steps are always executed; the outputs vary by feature.

6. **Coding tasks must follow the code-test loop.** When a workflow step involves writing or modifying code, the code+test cadence from `code-test-loop.md` applies within that step. No 500-line dumps. Write → test → green → next unit.

---

## Confirmation Behavior

### Manual Mode

In manual mode (the default when the agent is operating interactively and the user has not explicitly granted autonomous execution):

- The agent **stops at the end of each step** and presents its outputs to the operator.
- The agent **explicitly states which step just completed** and **which step comes next**.
- The agent waits for one of: explicit confirmation ("proceed", "looks good", "continue"), a correction ("revise step 2 before moving on"), or a stop instruction ("stop here").
- The agent does **not** proceed to the next step without a signal from the operator.

### Auto Mode

In auto mode (when the user has explicitly asked the agent to run to completion, or the agent is operating in an autonomous-execution context):

- The agent runs all steps to completion without pausing for per-step confirmation.
- The agent **logs a brief progress marker** at the start and end of each step (e.g., "Starting Step 2 — Verification…", "Step 2 complete.").
- The agent **pauses and seeks confirmation at the end of the full workflow** before any committing, publishing, or externally-visible actions (pushing code, posting to JIRA, publishing to the wiki).
- If any step produces a verdict of REVISE (e.g. the POST hook), the agent resolves the revision inline and re-runs that step before continuing, rather than pausing to ask.

---

## What Counts as a Step Completion

A step is complete when all of the following are true:

1. Every sub-procedure in the step's governing prompt has been executed.
2. The step's output artefact exists in the conversation (a context bundle, a verification report, a task list, a set of green tests, etc.).
3. Any verdict that triggers a loop (REVISE, failing test) has been resolved — the loop exits with the correct terminal state before the step is marked done.
4. If the step produced a document (spec, task breakdown, review report), that document is either inline in the conversation or written to the correct file path.

---

## Context Passing Between Steps

When a workflow passes from step N to step N+1, the agent must explicitly anchor the transition:

```
Step N is complete. Output: [one-line summary of what the step produced].
Proceeding to Step N+1: [step name].
Carrying forward: [what context from step N is being used in step N+1].
```

This narration serves two purposes: it makes the handoff visible to the operator, and it forces the agent to confirm that the prior step's output is actually available before invoking the next step's prompt.

---

## How to Read a Workflow Prompt

Each workflow prompt in this folder defines a named workflow. Its structure is:

1. **Name and Type** — the workflow's identifier and whether it is Pipeline or Parallel.
2. **When to Use** — the trigger condition (what user request or task type activates this workflow).
3. **Steps** — an ordered list of steps. Each step names the governing prompt file, states what input it consumes, and states what output it produces.
4. **Context carried forward** — explicit statement of what each step passes to the next.
5. **Exit condition** — what "the workflow is complete" means for the specific workflow.
6. **Confirmation points** — where in the workflow the agent pauses for confirmation (manual mode) vs. where it may proceed autonomously (auto mode).

---

## Available Workflows

| Workflow | Type | Trigger |
|---|---|---|
| [Specification Development](specification-development.md) | Pipeline | User asks to write, spec out, or generate a feature specification |
| [Code-Test-Review](code-test-review.md) | Pipeline | User asks to implement a feature spec or build a feature |
| [GitLab Code-Test-Review](gitlab-code-test-review.md) | Pipeline | User asks to implement a feature spec in a GitLab repo (issues + MR lifecycle) |

---

## Adding New Workflows

When a new compound task recurs enough to warrant a workflow:

1. Identify the ordered steps and the prompt files that govern each.
2. Determine whether steps are sequentially dependent (Pipeline) or independent (Parallel).
3. Write the workflow prompt in this folder following the structure above.
4. Add a row to the Available Workflows table in this file.
5. If the workflow has a natural CLI/Make trigger, add a row to the ubiquitous-language table in `skills/design-and-analysis/ubiquitous-language/SKILL.md`.

Keep workflow prompts short and directive. The detail lives in the step prompt files. The workflow prompt's job is sequencing, context passing, and confirmation — not re-documenting what each step already explains.
