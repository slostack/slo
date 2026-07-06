# Workflow: Code-Test-Review

**Type:** Pipeline
**Governs:** All feature implementation work in this repository

## Skills used in this workflow

Load these on demand as each step calls for them — you do not need to read any
other skill file to run this workflow:

| Step | Skill |
|---|---|
| 1 — Code + Test Loop | `skills/coding/code-test-loop/SKILL.md` |
| 2 — Code Review | `skills/design-and-analysis/review-feature-code/SKILL.md` |
| 3 — Completion Check | `skills/design-and-analysis/is-the-feature-completed/SKILL.md` |
| Always-on conventions | `skills/coding/named-arguments-and-type-hints/SKILL.md`, `skills/coding/declarative-method-structure/SKILL.md`, `skills/coding/method-docstrings/SKILL.md`, `skills/coding/test-verification-policy/SKILL.md` |
| Manual vs. auto mode | `skills/design-and-analysis/workflows/SKILL.md#confirmation-behavior` |

---

## When to Use

Activate this workflow whenever the operator asks to:

- "Implement this feature spec"
- "Build [feature] based on the spec"
- "Code up [task / ticket / spec]"
- "Implement [task from the breakdown]"
- Complete a task produced by the [Specification Development Workflow](specification-development.md)

The trigger is intent to go from a specification (or a single task extracted from a spec) to running, tested code. Confirmation-seeking at the end of each step depends on [manual vs. auto mode](SKILL.md#confirmation-behavior).

---

## Pre-conditions

Before the first step begins, confirm:

- **A dedicated feature branch is checked out.** Never implement directly on `main`. If the current branch is `main`, create a feature branch first using the naming convention: `<TICKET-ID>-<short-kebab-description>` when a ticket ID is available (e.g. `AGI-42-session-rename`), or `feature-<short-kebab-description>` when there is no ticket (e.g. `feature-refresh-skills-index`). Use `git checkout -b <branch-name>` from an up-to-date `main`.
- A specification document, JIRA task, or clear feature description is available. The agent must have something to implement against — a task without a spec is not ready for this workflow.
- `AGENTS.md` and `RESEARCH.md` have been read (or are already in context).
- The relevant KB folders have been consulted for the feature's surface area.
- The always-on rules are loaded: `named-arguments-and-type-hints.md`, `declarative-method-structure.md`, `method-docstrings.md`, `test-verification-policy.md`.
- All applicable `build-*.md` files for the layers this task touches have been read. Do not write a single line of code for a layer whose build rules have not been loaded.

If any pre-condition is not met, satisfy it before entering Step 1.

---

## Steps

### Step 1 — Code + Test Loop

**Governing skill:** `skills/coding/code-test-loop/SKILL.md`

**Input consumed:**
- The feature specification or task description
- All loaded `build-*.md` conventions for the task's layers
- RESEARCH.md for existing patterns to mirror

**What this step does:**

Implement the feature by working through each implementation unit in dependency order (migrations → domain models/DAOs → domain services → application services → routers → workers → frontend). For each unit:

1. Write the implementation unit (one function, class, route handler, migration, or component — bounded scope, single purpose).
2. Write the tests for that unit (one test per decision point, per `test-verification-policy.md`).
3. Run the tests and confirm green.
4. Run the surrounding suite (the file's whole test module or the containing folder) to confirm no regressions.
5. Only then start the next unit.

The agent must not write more than ~50 lines without running the corresponding tests. Writing all code first and testing at the end is a violation of this step.

**Coding conventions that apply within this step (all of them, always):**

- Named arguments on every call with 2+ arguments — `named-arguments-and-type-hints.md`
- Type hints on every function signature and return type — `named-arguments-and-type-hints.md`
- Google-style docstrings on all public methods — `method-docstrings.md`
- Declarative method structure — no nested if-else, one decision per method, guard clauses at the top — `declarative-method-structure.md`
- Service namespace prefixes on every `app.include_router(...)` — `/la/api/v1`, `/v/api/v1`, etc.
- Ubiquitous language — one concept, one name across every layer — `ubiquitous-language.md`
- Three-file domain pattern — `model.py`, `dao.py`, `service.py` — `build-domain-features.md`
- `invoke()` orchestration pattern for application services — `build-application-services.md`
- New models registered in `src/models/model.py` for Alembic — `build-domain-features.md`

**When running tests:**

```bash
loadenv environments/test.env
PYTHONPATH=${PWD} poetry run pytest -sv tests/path/to/test_file.py::TestClass
```

After all individual units pass, run the full suite before moving to Step 2:

```bash
loadenv environments/test.env
PYTHONPATH=${PWD} poetry run pytest -sv tests/
```

**Output produced:**

- All implementation files written to their correct file paths
- All corresponding test files written and passing
- Full test suite green (no regressions)
- A brief implementation log in conversation: which files were created/modified, which tests cover which decision points

**READY condition:** every decision point in the new code is covered by a passing test, the full suite is green, no failing tests were left disabled or skipped.

**Context carried forward to Step 2:**
- The list of files created and modified
- The test coverage map (which tests cover which units)
- The full suite green status
- Any implementation decisions made that deviate from the spec (must be surfaced explicitly)

---

**[MANUAL MODE — PAUSE]**

Present a summary of what was implemented: files created, files modified, test count, any deviations from spec. State:

> "Step 1 complete — implementation is in place and all tests are green. Proceeding to Step 2 (Code Review) unless you would like to review the implementation first."

Wait for confirmation before continuing.

---

### Step 2 — Code Review

**Governing skill:** `skills/design-and-analysis/review-feature-code/SKILL.md`

**Input consumed:**
- The specification document (or task description) from the pre-conditions
- The implementation files from Step 1
- The test coverage map from Step 1

**What this step does:**

Conduct a structured review of the Step 1 implementation against the specification. The review is not a style pass — it is a completeness, correctness, and convention audit.

Follow the full review process from `review-feature-code.md`:

1. Load the specification and extract all requirements as a checklist.
2. Inventory every implementation file by layer (domains, app services, routers, workers, migrations).
3. Map each spec requirement to its implementation (Covered / Partial / Not Covered).
4. Trace the end-to-end flow from entry point through all intermediate components to terminal state. Verify that every component in the chain is wired to the next — no dead code, no disconnected workers, no unregistered queues.
5. Analyze test coverage: identify untested production files, missing decision branches, missing error paths, and false-confidence tests (tests that exist but only cover the happy path).
6. Check compliance against all applicable coding conventions.
7. Compile findings into three tiers: Glaring Gaps (must fix), Nice-to-Haves (should fix), Temporary Shortcuts (acknowledged debt).

If Glaring Gaps are found, the agent must return to Step 1 and resolve them before the review is considered complete.

**Output produced:**

- Code Review Report (in conversation or written to a review file) with:
  - Executive Summary
  - Feature Completeness Table (spec requirement vs. implementation status)
  - End-to-End Flow Verification
  - Unit Tests Assessment
  - Convention Adherence
  - Three-tier Findings Summary
  - Architecture Diagram (Mermaid)

**READY condition:** review report is complete; no Glaring Gaps remain unaddressed.

**Context carried forward to Step 3:**
- The Code Review Report
- The final implementation file list (post any Step 2 revisions)
- The feature completeness table

---

**[MANUAL MODE — PAUSE]**

Present the Code Review Report. State:

> "Step 2 complete — code review report is ready. [N glaring gaps / no glaring gaps] found. Proceeding to Step 3 (Completion Check) unless you would like to address findings first."

Wait for confirmation before continuing.

---

### Step 3 — Completion Check

**Governing skill:** `skills/design-and-analysis/is-the-feature-completed/SKILL.md`

**Input consumed:**
- The original specification or task description
- The Code Review Report from Step 2
- The current codebase (post all Step 1 and Step 2 revisions)

**What this step does:**

Run the completion assessment from `is-the-feature-completed.md`. This is a fresh codebase scan against the full set of expected deliverables — it does not assume Step 1 and Step 2 produced a correct result. The assessment:

1. Re-derives the full deliverable checklist from the specification by layer (database, domain, application services, workers, routers, events, integrations, frontend, configuration, tests).
2. Searches the codebase for evidence of each deliverable's implementation.
3. Scores each deliverable as Done, Partial, or Not Started.
4. Calculates completion percentage (with effort weighting where appropriate).
5. Assesses infrastructure readiness (base classes, enums, constants, schema).
6. For any Not Started or Partial items, produces a specific implementation guide: what needs to be built, where it goes, which adjacent feature to mirror, and what the key differences are.
7. If multiple items remain, produces a dependency graph for the remaining work.

If completion is below 100% (or below an operator-specified threshold), the agent must return to Step 1 and implement the missing items before the workflow completes.

**Output produced:**

- Feature Completion Assessment (in conversation):
  - Completion % and Incompletion %
  - Infrastructure Readiness %
  - Status By Layer table
  - Implemented Files list
  - Pending Implementation list (if any) with guidance per pending item
  - Dependency graph (if multiple items remain)

**READY condition:** completion assessment confirms 100% of spec deliverables are implemented and tests are green. (Or the operator explicitly accepts a lower threshold and marks remaining items as deferred scope.)

---

**[MANUAL MODE — PAUSE]**

Present the completion assessment. State:

> "Step 3 complete — feature completion check done. [X]% complete. [Workflow complete / N items remain — returning to Step 1.]"

**[AUTO MODE — FINAL CONFIRMATION]**

Before committing code, pushing a branch, or creating a PR, pause and confirm:

> "Code-Test-Review Workflow complete. Implementation is [X]% complete, all tests green. Ready to commit and open a PR. Confirm?"

---

## Exit Condition

The Code-Test-Review Workflow is complete when:

- Step 1: All implementation units are written, all tests pass, the full suite is green.
- Step 2: Code Review Report is complete, no Glaring Gaps remain.
- Step 3: Completion assessment reaches 100% (or operator accepts explicit deferral), all tests remain green.

---

## What Does Not Change

The following rules remain in effect throughout this workflow:

- The code+test cadence is non-negotiable. Write a unit, test it, run it green, then proceed. No bulk writes.
- All always-on coding conventions from `CLAUDE.md` apply to every line of code written.
- Secret scanning before commit — eye-scan all staged content for API keys, tokens, bcrypt hashes, and private keys before any `git commit`.
- Confirmation before commit, push, or PR — `ALWAYS SEEK CONFIRMATION BEFORE COMMITTING CODE, PUSHING CODE TO REMOTE REPOSITORIES OR MERGING CODE`.
- The agent still needs to gather context. Reading the relevant `build-*.md` and KB entries is required before writing code for a new layer, not optional.

---

## Quick Reference

```
Trigger: "implement [feature spec / task]"

Pre-conditions: spec available, AGENTS.md/RESEARCH.md loaded,
                all build-*.md for the task's layers loaded

Step 1: Code + Test Loop (write unit → test → green → repeat until done)
        └─ Output: all files written, full suite green

Step 2: Code Review (spec completeness, flow wiring, test coverage, conventions)
        └─ Output: review report; return to Step 1 if Glaring Gaps found

Step 3: Completion Check (fresh scan; percentage score; pending guidance)
        └─ Output: completion assessment; return to Step 1 if incomplete

[MANUAL] pause at end of each step
[AUTO]   run to completion, confirm before commit/push/PR
```
