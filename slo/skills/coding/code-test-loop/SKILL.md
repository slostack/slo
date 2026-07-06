---
name: code-test-loop
description: 'Operating rhythm for coding sessions: never write a large block of code
  without testing the last small block first. Code → test → green → next chunk.'
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
- **Description:** Operating rhythm for coding sessions: never write a large block of code without testing the last small block first. Code → test → green → next chunk.
- **When to use:** Use as the default cadence whenever writing or modifying code; complements test-verification-policy (which dictates what must be tested) by specifying when those tests run.
- **Group:** `coding`
- **Kind:** `workflow`
- **Source prompt:** `code-test-loop.md`

## Examples

- The user asks for an end-to-end workflow that fits: Operating rhythm for coding sessions: never write a large block of code without testing the last small block first. Code → test → green → next chunk.
- Use as the default cadence whenever writing or modifying code; complements test-verification-policy (which dictates what must be tested) by specifying when those tests run.

## Guidance

### ⚠ Disambiguation — Are You Looking for the Code-Test-Review Workflow?

**If the user's request contained any of these phrases or intents:**
- "use the code-test-review workflow"
- "run the code-test-review workflow"
- "implement this spec" / "build this feature" (end-to-end, not just coding)
- any multi-step pipeline: code → review → completion check

**→ STOP. Do not continue reading this skill.**

Load the full workflow file instead:

```
skills/design-and-analysis/workflows/code-test-review.md
```

This skill (`code-test-loop`) is the **coding cadence only** — write one unit, test it, go green, repeat. It is **Step 1 inside** the Code-Test-Review workflow. Loading this skill when the user asked for the workflow silently drops:

- Step 2 — Code Review (`skills/design-and-analysis/review-feature-code/SKILL.md`)
- Step 3 — Completion Check (`skills/design-and-analysis/is-the-feature-completed/SKILL.md`)

Only continue reading this file if:
1. The user specifically asked for the coding cadence / code-test loop on its own, OR
2. You are already inside Step 1 of the Code-Test-Review workflow and need the loop rules.

---

**The cadence:** never write a large block of code without testing the
last small block first. Code → test → green → next chunk. Repeat.

This is the operating rhythm for every coding session — solo, agentic, or
mixed. It complements [skills/coding/test-verification-policy/SKILL.md](../test-verification-policy/SKILL.md)
(which says *every decision point must be tested*) by specifying *when*
those tests run during development.

---

## The rule

For every coding task that produces more than ~50 lines of new code:

1. **Write a small unit.** A function, a class, a route handler, a
   single Vue component, a migration. Bounded scope, single purpose.
2. **Write the test(s) for that unit.** One per decision point, per the
   verification policy.
3. **Run the test.** Make it pass.
4. **Run the surrounding suite** (the file's whole test module, or the
   module's containing folder). Confirm no regressions.
5. **Only now** start the next unit.

Do NOT:

- Write 500 lines of code, then write tests at the end.
- Write tests but defer running them ("I'll run them at the end").
- Skip "small" units — even a 20-line helper gets a test before its
  caller is written.
- Disable a failing test to keep moving. If it's failing, the unit
  isn't done; fix the code or rewrite the test.

---

## Why this matters

- **A failing test caught early is a 2-line fix; a failing test
  surfaced at the end of a 500-line dump is a 4-hour archaeology
  session** trying to recall which line broke which invariant.
- **The next chunk of code is often shaped by what the previous test
  surfaced.** Writing tests at the end loses that feedback loop —
  you've already committed to a shape that may not survive
  verification.
- **Parallel agents need test-green hand-off points.** When agent A
  finishes a unit and agent B builds on it, agent B has to be able to
  trust that agent A's unit works. The only credible evidence is "this
  test passed in agent A's last run."
- **Acceptance criteria become a worklist, not a sign-off ritual.** A
  spec with 10 acceptance criteria gets implemented as 10 test-driven
  passes through code-write/test-write/run. The acceptance check at
  the end is a final tally, not the first time the work is exercised.

---

## What "small unit" means in practice

| Layer | One unit |
|---|---|
| Domain model + DAO | One file pair, then `pytest tests/domains/<x>/test_<x>_dao.py` |
| Domain service method | One method, then the 3-5 tests covering its decisions |
| Application service | One private method (e.g. `_load_and_validate`), then its tests; only then `_compose_payload`; etc. |
| FastAPI router | One route, then its 200/404/422 tests |
| Pinia store action | One action, then its mocked-API test |
| Vue component | One SFC, then its render + emit tests |
| Pydantic DAO change | The change + the (de)serialisation tests |
| Alembic migration | The migration + an applied/rolled-back smoke check |

If a unit can't be tested in isolation, that's a design smell — it's
probably too tangled with its dependencies. Refactor toward smaller
units before continuing.

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

Bad pattern (a half-day to debug):

```
1. Write all 500 lines of app service + router + DAOs + tests
2. Run pytest. 17 failures.
3. Half a day disentangling which 50 lines broke which test.
4. Find one wrong dataclass field; the rest were cascading from that.
```

Good pattern (a 90-minute green stack):

```
1. Write DAOs (60 LOC). Write DAO tests (20 LOC). Run. GREEN.
2. Write domain service method 1 (40 LOC). Write 3 tests (50 LOC). Run. GREEN.
3. Write domain service method 2 (30 LOC). Write 2 tests (30 LOC). Run. GREEN.
4. Write app service _load_and_validate (25 LOC). Write 2 tests (40 LOC). Run. GREEN.
5. ... continue for each named method ...
9. Write router (30 LOC). Write 3 tests (50 LOC). Run. GREEN.
10. Run the full suite. GREEN.
```

Same total LOC. Different debug burden by an order of magnitude.

---

## When a sub-agent is doing the work

If you delegate to a sub-agent (`Agent` tool), state the cadence
explicitly in the prompt:

> "Work in the code+test loop: implement one private method, write its
> tests, run them, confirm green, then move to the next method. Do NOT
> write all methods first and then test at the end."

If the agent reports back having written 300 lines without intermediate
test runs, that's a deviation worth flagging — the work may pass the
final suite but the *process* is fragile and reproducible bugs will
surface in PR review.

---

## See also

- [skills/coding/test-verification-policy/SKILL.md](../test-verification-policy/SKILL.md) — what
  decision points must be tested.
- [skills/coding/declarative-method-structure/SKILL.md](../declarative-method-structure/SKILL.md) —
  why methods should be small enough to test in isolation.
- [skills/coding/build-application-services/SKILL.md](../build-application-services/SKILL.md) — the
  `invoke()` + named private methods pattern that maps 1-to-1 with
  loop iterations.

---

## Reference in your skills/orientation/claude/SKILL.md

This rule belongs in the "Always-on rules" section of your skills/orientation/claude/SKILL.md:

```markdown
@<workspace>/skills/coding/code-test-loop/SKILL.md
```

Adding it there ensures every coding session loads the cadence
expectations on entry.

