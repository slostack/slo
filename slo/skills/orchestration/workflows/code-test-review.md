# Workflow: Code-Test-Review

**Type:** Pipeline
**Governs:** All feature implementation work in this repository

Follow [progression and authorization](SKILL.md#progression-and-authorization):
verify phase artifacts, report progress, and ask only for blocking clarification.
External and destructive actions still require explicit operator authorization.

## Scoped guidance and phase handoff contract

**Workflow-turn accounting:** Follow
`skills/orchestration/workflows/SKILL.md#workflow-turns-and-limits`.
Count a full pass through the workflow, not individual phases or agent calls.
Report partial passes and separate harness limits explicitly; never skip review
or treat repeated authoring dispatches as completed workflow turns.
Explicit user instructions override the default workflow-turn and per-turn dispatch
budgets: raise, lower or remove either limit as requested. Record and pass on the
effective limits without resetting consumed counts; runtime caps and other
policies remain separate. See the shared rules above for defaults and scope.


Before Step 1 read `skills/engineering/engineering-routing/SKILL.md` and
`skills/engineering/engineering-testing/SKILL.md`. Record affected languages,
frameworks, test categories, project contracts, selected skill paths/source tiers,
and actual project verification commands. Pass this record to every phase.
Load language/component recipes on demand; do not impose Python syntax or tooling
on Go, TypeScript or an unsupported language. For Go use the test-first cadence.

## Additive prerequisite handoff

The coding phase also consumes `skills/coding/coding-rules/SKILL.md` before
implementation. The routing record preserves this order: project context →
generic coding rules → applicable language root → applicable feature/framework
recipes → bounded implementation and verification. Applicable specific guidance
overrides the generic default on the affected point; unresolved
specific-to-specific conflicts remain explicit blockers. This is a read and
handoff requirement only; it does not change phase order, review meaning,
completion meaning, or engineering authority.

Each phase returns a terminal verdict (READY/COMPLETE, REVISE, or FAILED), concrete
artifact paths, requirement-to-evidence mapping, exact commands/results, deviations
and unresolved blockers. Verify artifacts exist before advancing; a success exit
code without the required evidence is not READY. Revision changes invalidate later
review/completion evidence: return to the responsible implementation/spec phase,
retest and re-review. An execution failure stops progression; a recoverable failed task may be retried
up to three times after the initial attempt, with its cause addressed and within
the current workflow turn's dispatch budget. Never retry an aborted task, even when
the reported cause is a timeout. User cancellation is not permission to restart work.
Do not claim another agent independently reviewed work that was reviewed solo.

For dynamic workflows use in-session spawn_sub_agents unless explicitly detached;
ordinary workflow execution does not itself grant permission to spawn. A detached
orchestrator never launches another detached workflow. A missing optional knowledge
base is non-blocking; follow `skills/design-and-analysis/locate-knowledge-base/SKILL.md`.

## Skills used in this workflow

Load these on demand as each step calls for them — also load the scoped language/component companions selected by the routing record:

| Step | Skill |
|---|---|
| 1 — Code + Test Loop | `skills/coding/code-test-loop/SKILL.md`, `skills/coding/test-verification-policy/SKILL.md` (how to test) |
| 2 — Code Review | `skills/design-and-analysis/review-feature-code/SKILL.md` |
| 3 — Completion Check | `skills/design-and-analysis/is-the-feature-completed/SKILL.md` |
| Always-on conventions | `skills/engineering/engineering-ownership/SKILL.md`, `skills/engineering/engineering-testing/SKILL.md`, plus selected language roots |


---

## When to Use

Activate this workflow whenever the operator asks to:

- "Implement this feature spec"
- "Build [feature] based on the spec"
- "Code up [task / ticket / spec]"
- "Implement [task from the breakdown]"
- Complete a task produced by the [Specification Development Workflow](specification-development.md)

The trigger is intent to go from a specification (or a single task extracted from a spec) to running, tested code.

---

## Pre-conditions

Before the first step begins, confirm:

- **A dedicated feature branch is checked out.** Never implement directly on `main`. If the current branch is `main`, create a feature branch first using the naming convention: `<TICKET-ID>-<short-kebab-description>` when a ticket ID is available (e.g. `AGI-42-session-rename`), or `feature-<short-kebab-description>` when there is no ticket (e.g. `feature-refresh-skills-index`). Use `git checkout -b <branch-name>` from an up-to-date `main`.
- A specification document, JIRA task, or clear feature description is available. The agent must have something to implement against — a task without a spec is not ready for this workflow.
- `AGENTS.md` and `docs/RESEARCH.md` have been read (or are already in context).
- The relevant KB folders have been consulted for the feature's surface area.
- Shared policies and only the affected language conventions are loaded through the routing record.
- All applicable `build-*.md` files for the layers this task touches have been read. Do not write a single line of code for a layer whose build rules have not been loaded.

If any pre-condition is not met, satisfy it before entering Step 1.

---

## Acceptance contract

Before Step 1, record the original specification, stable acceptance IDs, required
user journeys, critical risks, verification commands/environment, relevant baseline
failures and unresolved decisions. Map requirements to evidence; additions must cite
their source or a concrete defect. Baseline exclusions and scope deferrals require
explicit approval. Do not silently relax mandatory coding conventions or safety rules.
Use the routing record for authoritative language/component guidance instead of
copying language-specific rules into this workflow.

## Steps

## Step 1 — Code + Test Loop

**Governing skill:** `skills/coding/code-test-loop/SKILL.md`

Consume the acceptance contract, current routing record and
`skills/coding/coding-rules/SKILL.md`. Work in bounded behavioral increments,
respecting dependency order within a vertical slice rather than completing every
lower layer before wiring its consumers. Follow language/user test ordering.

### Testing strategy

How to test is owned by `skills/coding/test-verification-policy/SKILL.md`. Apply it in every sub-spec cycle:

- **Behavior first.** Each acceptance criterion is proven by a journey test: real entry point (controller, CLI, TUI, worker, task, scheduler or event) → application service → domain service → persisted state read back.
- **More behavior tests, fewer method tests.** Add workflow, domain or unit tests only for branches the journey test cannot reach cheaply.
- **Real persistence.** Never mock databases, file stores or internal engines.
- **Mocks only for third-party APIs**, at their client boundary. Use stubs passed in through constructors, factories or parameters for everything else.
- **No end-to-end suite per sub-spec.** End-to-end tests cover only integration-layer scenarios (frontend, full install or run cycle, multi-process or multi-node). They run once, as the final check for the feature.

### Runnable

Make the first milestone the smallest representative user journey: real entry point
→ core behavior → observable terminal result. Verify wiring through the real
application boundary; controlled external substitutes must be declared along with
what they cannot prove. For documentation/skills changes, demonstrate the equivalent
consumer path (discovery/loading → usable guidance → reference-valid artifact).
This is progress, not final acceptance or permission to defer required robustness.
If a genuine prerequisite prevents the slice, identify it and its closure target.

### Early integration feedback

After the runnable milestone, get a bounded, independent **agent review**. This section is its full checklist;
`skills/design-and-analysis/review-feature-code/SKILL.md` governs only the Step 2 final review.

- **What it is:** a read-only review by an agent. The reviewer reads the specification, the code and the tests.
- **What it does not do:** it does not run tests, integration suites or end-to-end checks. Test execution belongs to the implementer in Step 1.
- **What it checks**, for each behavior the specification states:
  - Is it implemented, and wired from the real entry point?
  - Is it covered by a test that follows `skills/coding/test-verification-policy/SKILL.md`?
  - Do the architecture and the remaining plan carry any major risk?
- **What it returns:** a short list of stated behaviors that are missing, unwired or untested, with spec section, file path and closure condition.
- **Status:** advisory, except for concrete blockers. It stays inside Step 1; it is not formal phase progression or a completed workflow turn.
- **Scope:** do not demand final coverage from the first slice.
- **Independence:** use only authorized reviewers or sub-agents. If none is available, report the limitation and request the needed review or authorization. Do not call a self-check independent or silently substitute one.
- Final review in Step 2 remains required.

### Acceptance-ready

Extend the slice to all required journeys and critical failure paths. Apply the
requirement-and-risk map in `skills/engineering/engineering-testing/SKILL.md` and
adequacy gate in `skills/coding/test-verification-policy/SKILL.md`.
Run focused tests per increment, affected suites at milestones, and all agreed
full-suite/static/build/race gates before Step 2. Run end-to-end tests only at
the end of the feature, after the last sub-spec cycle, and only where the policy
calls for them. Baseline exceptions need explicit
approval; unavailable checks are unverified. No disabled tests to manufacture green.

**Output:** implementing files, acceptance-to-evidence map, exact commands/results,
baseline dispositions, deviations, early feedback and remaining blockers. Maintain
a compact current handoff; detailed receipts remain referenced, not recopied.

**READY condition:** all nondeferred acceptance items have appropriate passing
evidence, required gates pass with no regressions, mandatory conventions hold and
no unresolved blockers remain. Explicitly list approved exceptions/deferrals.

Report the phase result and verify its required artifacts before advancing.

## Step 2 — Code Review

**Governing skill:** `skills/design-and-analysis/review-feature-code/SKILL.md`

Conduct final independent review against the original specification, acceptance
contract, implementation and current evidence. Trace real end-to-end wiring, inspect
assertion quality, applicable conventions, critical risks and baseline dispositions.
Early feedback does not substitute for this review.

**Output:** verdict, requirement/evidence map, verification limitations and findings
with stable IDs, source/rule or concrete defect, path/evidence and closure condition.
Optional improvements stay nonblocking; acknowledged debt cannot hide a required
contract or safety failure. Diagrams are useful when they clarify complexity, not
mandatory ceremony for every change.

**READY condition:** required review is complete and no blocking findings remain.
On REVISE return to Step 1 with the finite repair list, retest and re-review affected
work. Reuse unchanged evidence but inspect changed boundaries and any new defects.

Report the phase result and verify its required artifacts before advancing.

## Step 3 — Completion Check

**Governing skill:** `skills/design-and-analysis/is-the-feature-completed/SKILL.md`

Independently verify the agreed checklist against the original specification and
current executable evidence. Do not assume author/reviewer verdicts establish truth.
Check all required deliverables, wired journeys, review closure and required gates.
An omitted requirement must cite its source; recommendations cannot invent scope.

**Output:** acceptance status/evidence table, review and gate status, explicit
exceptions/deferrals, and any pending item with its source and closure condition.
Percentages cannot establish readiness. Provide implementation guidance only for
actual gaps; add a dependency graph when it helps resolve multiple pending items.

**READY condition:** every required nondeferred item is verified, final review is
accepted, required gates pass and no unresolved blockers remain. Otherwise return
to Step 1 for implementation gaps and repeat affected verification/review; report
external blockers honestly. Only the operator may approve explicit deferral.

## Exit Condition

- Step 1: acceptance-ready implementation with passing required evidence and gates.
- Step 2: final independent review accepted, with no blocking findings.
- Step 3: original-spec reconciliation confirms no unapproved omissions or unverified
  required items; approved exceptions and deferrals are visible in the final result.



## What Does Not Change

The following rules remain in effect throughout this workflow:

- The code+test cadence is non-negotiable. Follow the selected language test ordering, verify each unit green, then proceed. No bulk writes.
- All always-on coding conventions from `CLAUDE.md` apply to every line of code written.
- Secret scanning before commit — eye-scan all staged content for API keys, tokens, bcrypt hashes, and private keys before any `git commit`.
- Confirmation before commit, push, or PR — `ALWAYS SEEK CONFIRMATION BEFORE COMMITTING CODE, PUSHING CODE TO REMOTE REPOSITORIES OR MERGING CODE`.
- The agent still needs to gather context. Reading the relevant `build-*.md` and KB entries is required before writing code for a new layer, not optional.
- When this workflow runs detached, stop it only with `/workflows abort <workflow-id>` (or `SIGTERM` to the orchestrator pid for a shell launch). Never `pkill` / `kill` its process tree, even to snapshot work before a commit. A raw kill leaves a stale handle that makes every later `launch_workflow` in the session fail with `no evidence-backed correction`. See `skills/orchestration/headless-orchestration/SKILL.md` → "Stopping a running workflow".

---

## Quick Reference

```text
Acceptance contract + routing + baseline
Step 1: Runnable slice → early integration feedback → acceptance-ready hardening + gates
        (journey tests per sub-spec; end-to-end only as the final feature check)
Step 2: Independent final review → bounded repairs through Step 1 when needed
Step 3: Completion check against the original specification and current evidence
```

Use `skills/orchestration/workflows/SKILL.md` for convergence checkpoints, counters,
authorization and stopping rules. A runnable demonstration is not workflow completion.
