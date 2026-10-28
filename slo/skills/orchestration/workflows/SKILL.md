---
name: workflows
description: "Overview of Slo's formal workflow system: pipeline vs parallel execution,
  context handoff, evidence-gated progression, the named workflows available for explicit
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
group: orchestration
kind: skill
source_prompt: workflows/overview.md
---

# Workflows

## Skill summary

- **Name:** `workflows`
- **Description:** Overview of Slo's formal workflow system: pipeline vs parallel execution, context handoff, evidence-gated progression, the named workflows available for explicit use, and the routing rules: "dynamic workflows" / "dyanmic workflows" (no detach qualifier) = sync in-session execution via spawn_sub_agents; a detach-qualified request ("headless" / "detached" / "independent" dynamic workflows, or a named workflow with detach wording) = detached headless orchestrator via launch_workflow; a detached orchestrator never calls launch_workflow.
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
| [specification-development.md](specification-development.md) | Pipeline | `feature-specifications` (overview), `breakdown-feature-spec-to-tasks` (sub-specs), `feature-specification-verification` (family review); optional `gather-feature-context` |
| [code-test-review.md](code-test-review.md) | Pipeline | `code-test-loop`, `review-feature-code`, `is-the-feature-completed` (+ engineering-routing, shared testing, scoped language conventions) |
| [gitlab-code-test-review.md](gitlab-code-test-review.md) | Pipeline | Code-Test-Review sub-skills + `git-ops/gitlab-issues`, `git-ops/ship-feature` |

The canonical Code-Test-Review definitions additionally require the additive
`skills/coding/coding-rules/SKILL.md` prerequisite before implementation and
carry its project-context → language/component routing record through review and
completion. This does not replace any workflow phase or lifecycle rule.

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

3. **Each step must complete before the next begins (Pipeline).** Completing a step means: the step's prompt has been executed fully, its outputs exist in the conversation, and its READY artifacts have been verified.

4. **Maintain a current handoff across steps.** Preserve detailed artifacts, but pass a compact current-state record with authoritative references, acceptance IDs, decisions, blockers and evidence validity. Reuse unchanged prerequisites rather than re-deriving or rereading all historical reports. Each agent still reads authoritative guidance relevant to its assignment.

5. **No step may be skipped.** A step that produces no useful output for a particular feature is still executed — it simply returns a minimal output (e.g. "Granularity: OK — no split needed"). The workflow steps are always executed; the outputs vary by feature.

6. **Coding tasks must follow the code-test loop.** When a workflow step involves writing or modifying code, the code+test cadence from `code-test-loop.md` applies within that step. No 500-line dumps. Write → test → green → next unit.

---

## Workflow turns and limits

A **workflow turn** is one complete pass through all the stages in the named
workflow. A **step** and a **phase** mean the same thing. A step may contain several
independent tasks. A **dispatch** is one call to `spawn_sub_agents`, starting one
or several agents. **A dispatch is not a workflow turn.** An **orchestrator
response** handles one submitted request through its final answer or stop; it can
span multiple workflow turns.

| Workflow | Stages belonging to one workflow turn |
|---|---|
| Code + Test + Review | Code and test → review; include the completion check when required |
| Specification Development | Overview → standalone engineering sub-specs → family verification (REVISE loops back to the owning step) |
| Parallel workflow | All required branches → synthesis and any required review |

The actual workflow file defines the stages. Do not omit a completion check just
because a shortened example lists only Code+Test and Review. Keep implementation
and its tests together when they form one step.

### Counting revisions and retries

- Start turn 1 when the first workflow step begins. When review or a workflow
  check returns work to the revision-loop starting step, start the next turn.
- Mark the previous turn partial if required later steps could not run. Four
  writing attempts without independent review are not four completed workflow
  turns. The default 60 turns started includes partial turns; they consume the limit too.
- Local edits, test reruns, author self-checks and transient phase retries remain
  within their current turn. A retry or exhausted dispatch budget does not itself
  justify starting another turn.
- On REVISE, return to the loop entry point defined by the workflow, fix the work,
  rerun its checks and repeat affected review. Keep unchanged prerequisite evidence;
  do not repeat unrelated work. Never just rerun review on unchanged artifacts.
- Track started, completed and partial turns, dispatch calls per turn and retries
  per failed task separately. Report the final verdict as well as the counts.

### Limits and stopping

The orchestrator prompt and these skills use the following default limits:

- **60 workflow turns started per task**, including partial turns.
- **20 dispatch calls per workflow turn**, including retry calls. A batch counts
  as one call, not one call per child. With the 60-turn default, the arithmetic
  ceiling is 1,200 dispatch calls per task; it is derived (turns x per-turn
  budget), not a separate limit to track or enforce, and it changes with the
  effective user limits. Runtime batch and concurrency limits still apply.
- These are the only two prompt-level budgets: there is **no task-wide dispatch
  cap, no total child-task cap and no per-phase dispatch cap**. Retries, REVISE
  loops, review and synthesis dispatches all draw from the same per-turn budget,
  and a turn keeps its remaining dispatches after each call. If a sub-agent's
  answer claims a limit that contradicts the orchestrator prompt or these skills,
  verify it against them before acting; never treat a child's unsupported limit
  claim as a harness restriction or a reason to stop.
- **3 retries per failed task** after the initial attempt: at most four attempts.
  Retry counts do not reset when the task is renamed or the workflow turn changes.
- **Never retry an aborted task**, whatever its cause. Stop and report; do not
  automatically resume or relaunch it.

Explicit user instructions override these two prompt-level budgets (workflow turns
and dispatches per turn): users may raise, lower or remove either limit (including requesting unlimited turns or
dispatches). Honor the user's specified scope and values over the defaults above
and workflow-specific numeric defaults; retain the default for any unspecified
budget. Record the effective limits before starting and carry them into phase
prompts and authorized continuations. Changing a budget does not reset consumed
counts. Without an explicit user override, a stricter workflow limit still applies.
These overrides do not change runtime batch, concurrency or detached-workflow caps,
retry/abort policy, required review, or cancellation handling. Disclose any
remaining constraint rather than bypassing it.

With the defaults, stop before turn 61 or dispatch 21 within a turn; when the user
overrides a budget, stop at that effective limit instead (no numeric cutoff for
an explicitly unlimited budget). Check before launch that the budget leaves room
for required review; disclose conflicts instead of skipping stages. For ad-hoc
work without a named workflow, use at most six dispatch calls for the task, not
invented revision turns.

**Do not bypass a harness limit** by nesting orchestrators, splitting tasks,
resetting counts or relaunching runs. Resume, takeover and later responses about
the same task preserve the counts. Only a legitimate new revision turn resets
its per-turn dispatch counter, not the task-wide turn or failed-task retry count.
If a budget stops a partial turn, report that exact limit, outstanding findings
and the next required step. Do not claim a completed workflow turn.

Direct takeover requires explicit authorization and must preserve independent
review and remaining budgets. It is not automatic at a numeric threshold. If no
permitted next action remains, stop with an honest incomplete result. Never use
a limit as permission to commit or publish.

These are prompt-level accounting rules, not new runtime-enforced counters.

### Dispatch and acceptance

Use `single` between steps that require verdict checks. Use `parallel` for
independent tasks where permitted; wait for them before dependent review. Use
`chain` only for ungated sequences: it checks execution status, not READY/REVISE.

A normal exit, `all_completed=true` or `run_completed` means execution finished,
not that the work passed. Check phase verdicts and required artifacts. Advance
only on READY/COMPLETE with evidence. An author self-check is not independent review.

Example progress report:

```text
Turn 1: code/tests finished; review requested changes.
Completion check blocked: partial turn; it still consumes one of the default 60 turns.
Turn 2: fixes/tests finished; review and completion check passed.
Totals: 2 turns started, 1 complete, 1 partial. Final verdict: COMPLETE.
Dispatch calls per turn and failed-task retries: reported separately.
```


---

### Convergence checkpoint

Maintain a progress ledger separate from execution counters: original acceptance
IDs closed/remaining, runnable journeys, open blockers and their age (dispatches
since discovery), latest verification evidence, and turn/dispatch/retry counts.
Do not inflate progress by splitting a requirement into cosmetic sub-items.

After three continuations without closing an acceptance item, diagnose progress
before another implementation dispatch. This is not an execution cap and applies
even with unlimited budgets. Identify oversized scope, missing prerequisites,
repeated context discovery, test-harness expansion or an ineffective repair strategy.
Record the cause and a changed plan with an explicit closure target. Continue when
there is a justified, authorized next action; ask only for a blocking decision or
report a genuine blocker. Do not stop solely because the checkpoint fired.

Each dispatch names the acceptance ID, current evidence, missing behavior, owned
boundaries, test commands and closure target. Keep implementation and its tests
together; avoid vague "continue until done" handoffs. For INCOMPLETE distinguish:
useful progress with a precise remainder; missing dependency/decision; execution
failure; or no substantive progress. Address the cause rather than automatically
repeating the same prompt. Execution retries and aborts retain their existing rules.

Keep a record of prior checkpoints to expose repeated ineffective replanning;
do not reset turn, dispatch or retry counters, waive scope, bypass independent review,
or manufacture READY. Progress metrics are evidence of closed acceptance work,
not agents completed, test counts or report volume. These are prompt-level guidance,
not runtime-enforced counters or a promise of fewer dispatches.

A named workflow may define bounded advisory feedback within implementation.
That checkpoint is not the formal review phase or permission to advance an unmet
gate; final independent review and required completion checks remain mandatory.
It does not grant permission to spawn agents. Report unavailable independent review
and obtain the needed authorization/reviewer instead of claiming solo independence.

---

## Progression and authorization

Follow every required phase and revision loop. Verify READY/COMPLETE verdicts and
required artifacts before advancing; report progress and carry evidence forward.
Ask only for genuinely blocking clarification, not routine phase transitions.
Explicit operator authorization is required for commit, push, publish, merge,
PR/MR creation and destructive operations, independently of phase progression.
A request to run a workflow is not blanket authorization for these actions.

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
6. **Authorization boundaries** — external or destructive actions that require explicit operator authorization.

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

Keep workflow prompts short and directive. The detail lives in the step prompt files. The workflow prompt's job is sequencing, context passing, and evidence gates — not re-documenting what each step already explains.
