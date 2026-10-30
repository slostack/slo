---
name: code-test-loop
description: 'Verify small observable behaviors incrementally, reuse valid evidence, and complete runnable slices before expanding scope.'
when_to_use: Use as the default cadence whenever writing or modifying code; complements
  test-verification-policy (which dictates what must be tested) by specifying when
  those tests run.
group: coding
kind: workflow
source_prompt: code-test-loop.md
---

# Code + Test Loop

## Skill summary

- **Name:** `code-test-loop`
- **Description:** Verify small observable behaviors incrementally and complete runnable slices before expanding scope.
- **When to use:** Use as the default cadence whenever writing or modifying code; complements test-verification-policy (which dictates what must be tested) by specifying when those tests run.
- **Group:** `coding`
- **Kind:** `workflow`
- **Source prompt:** `code-test-loop.md`

## Examples

- The user asks for an end-to-end workflow that fits: Operating rhythm for coding sessions: never write a large block of code without testing the last small block first. Code → test → green → next chunk.
- Use as the default cadence whenever writing or modifying code; complements test-verification-policy (which dictates what must be tested) by specifying when those tests run.

## Prerequisite guidance

Before implementation, read the project instructions and use
`skills/engineering/engineering-routing/SKILL.md` to select the smallest
sufficient skill set. The effective hand-off order is:

project context → shared engineering ownership/testing →
`skills/coding/coding-rules/SKILL.md` → applicable language root →
applicable feature/framework/test recipes → bounded implementation and
verification.

Read `skills/engineering/engineering-ownership/SKILL.md` and
`skills/engineering/engineering-testing/SKILL.md` for shared authority, then
read the applicable language guidance (for example,
`skills/languages/python/`, `skills/languages/typescript/`, or
`skills/languages/go/`) and applicable feature/framework guidance. Applicable
specifics override generic defaults on the relevant point; unresolved
specific-to-specific conflicts require an explicit decision. This is prompt
routing and hand-off guidance, not an enforced runtime classifier.

## Guidance

**Authority and applicability:** Shared incremental cadence only. Read
`skills/engineering/engineering-testing/SKILL.md` for coverage/evidence and
`skills/engineering/engineering-routing/SKILL.md` for language selection.
**Go uses test-first** via `skills/languages/go/go-recipe-code-test-loop/SKILL.md`;
implementation-first examples below apply to the retained Python/TypeScript
cadence, not Go. Tooling examples apply only to their named stack. This cadence
never substitutes for the full workflow.

### ⚠ Disambiguation — Are You Looking for the Code-Test-Review Workflow?

**If the user's request contained any of these phrases or intents:**
- "use the code-test-review workflow"
- "run the code-test-review workflow"
- "implement this spec" / "build this feature" (end-to-end, not just coding)
- any multi-step pipeline: code → review → completion check

**→ STOP. Do not continue reading this skill.**

Load the full workflow file instead:

```
skills/orchestration/workflows/code-test-review.md
```

This skill (`code-test-loop`) is the **coding cadence only** — write one unit, test it, go green, repeat. It is **Step 1 inside** the Code-Test-Review workflow. Loading this skill when the user asked for the workflow silently drops:

- Step 2 — Code Review (`skills/design-and-analysis/review-feature-code/SKILL.md`)
- Step 3 — Completion Check (`skills/design-and-analysis/is-the-feature-completed/SKILL.md`)

Only continue reading this file if:
1. The user specifically asked for the coding cadence / code-test loop on its own, OR
2. You are already inside Step 1 of the Code-Test-Review workflow and need the loop rules.

---

**The cadence:** select one small observable behavior → implement and test it in
language-approved order → verify → extend. Preserve user-requested test-first.
This skill owns cadence; [test verification](../test-verification-policy/SKILL.md)
owns evidence adequacy. Neither replaces final review or completion.

## The rule

1. Name the behavior, acceptance item, affected boundaries and test command before editing.
2. Implement one bounded behavioral increment, following the selected language cadence.
   A cohesive change may cross a few files or layers; line count is not its boundary.
3. Reuse existing evidence where applicable, add missing assertions and run focused tests.
4. Run affected surrounding suites at coherent checkpoints, earlier for cross-cutting changes.
5. Extend only after the increment is verified. Run full agreed gates before final acceptance.

Never bulk-write the feature and defer testing. If failures are hard to localize,
shrink the increment. Do not disable assertions or rewrite expectations merely to
obtain green. Classify failure as an implementation defect, incorrect test oracle,
environment problem or reproduced baseline failure. Change an oracle only with
contract evidence. A baseline exception requires explicit approval; unavailable
verification is blocked, not passing.

## Why this matters

Small feedback cycles localize defects while complete behaviors expose wiring
problems. Progress means acceptance evidence, not private methods or tests counted.

## What "small unit" means in practice

| Change | Behavioral increment and evidence |
|---|---|
| API | One request reaches the real handler/service and returns its specified result |
| Lifecycle | One operation completes or cancels with its owned resources accounted for |
| UI | One user action produces its observable state through the real application boundary |
| Migration | One schema change applies and rolls back under the project contract |
| Skills/documentation | One policy change is discoverable, internally consistent and reference-valid |

Use the lowest-cost faithful test boundary. Integration testing is valid; inability
to isolate a private helper is not by itself a reason to refactor. Refactor when
coupling causes a concrete correctness, maintainability or verification problem.
Preserve architecture, naming, typing, documentation and resource-ownership conventions.

---


## When the loop applies extra-strict

These situations are loop-sensitive — skipping the cadence here
historically caused half-day diagnoses in this codebase:

- **Refactors that change wire shape** (e.g. envelope rename, column
  rename). Migrate one router, run its tests, fix the assertions, GREEN.
  Then the next router. Don't migrate 5 routers + 5 test files at once.
- **DAO field additions/renames.** Add field, run the existing service
  tests, fix breakage, GREEN. Then move on.
- **DBOS workflows.** Each workflow function gets its decision-point
  tests before another workflow consumes it.
- **Agent-style code generation (LLMs writing code).** Same rule — the
  agent writes a unit, runs the test, GREEN, then writes the next.
  Agents that "write everything then run pytest" produce code that
  ages badly under review.

---

## When the loop relaxes

- **One-shot scripts** (under ~30 LOC, run once, then deleted) — no
  test required, no loop.
- **Pure config edits** (e.g. one env var added, one Make target).
  Verify with a manual smoke instead — `make help` parses, `loadenv
  && echo $X` returns the right value.
- **Type-only changes** (TypeScript interface field additions where
  no logic is touched) — `tsc --noEmit` is the equivalent verification.

---

## The cadence applied to a 500-line task

Bad: write all layers, then discover at the end that the entry point never calls them.
Good: wire one representative journey, verify its observable result, then extend
one behavior at a time with required failure-path tests. Size is a warning signal,
not a fixed line-count gate.

## When a sub-agent is doing the work

Delegate only when authorized by the orchestration policy. Give the agent a closure
target: acceptance ID, missing behavior, owned files/boundaries, verification command
and completion condition. Keep implementation and its tests together.

A handoff reports behavior completed, exact tests/results, remaining acceptance
items or blocker, and the next action with its expected closure. Test counts and
"INCOMPLETE" alone do not explain progress. Apply the convergence checkpoint in
`skills/orchestration/workflows/SKILL.md` when repeated continuations do not close work.


## See also

- [skills/coding/test-verification-policy/SKILL.md](../test-verification-policy/SKILL.md) — what
  evidence establishes adequate coverage.
- [skills/coding/declarative-method-structure/SKILL.md](../declarative-method-structure/SKILL.md) —
  cohesive decomposition; read the language specialization for syntax-specific rules.
- [skills/languages/python/build-application-services/SKILL.md](../../languages/python/build-application-services/SKILL.md) — the
  Python application-service conventions; methods need not map 1-to-1 to loop iterations.

---

## Reference in your CLAUDE.md

This rule belongs in the "Always-on rules" section of your CLAUDE.md:

```markdown
@<workspace>/skills/coding/code-test-loop/SKILL.md
```

Adding it there ensures every coding session loads the cadence
expectations on entry.

