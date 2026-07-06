---
name: 09-plan-to-code
description: 'Integration tests: converting a test plan into code, scenario by scenario.'
when_to_use: Use after a plan is written (08-generating-test-plans) to land the test
  code.
group: integration-tests
kind: workflow
source_prompt: integration-tests/09-plan-to-code.md
---

# Converting a Test Plan into Code

## Skill summary

- **Name:** `09-plan-to-code`
- **Description:** Integration tests: converting a test plan into code, scenario by scenario.
- **When to use:** Use after a plan is written (08-generating-test-plans) to land the test code.
- **Group:** `integration-tests`
- **Kind:** `workflow`
- **Source prompt:** `integration-tests/09-plan-to-code.md`

## Examples

- The user asks for an end-to-end workflow that fits: Integration tests: converting a test plan into code, scenario by scenario.
- Use after a plan is written (08-generating-test-plans) to land the test code.

## Slo defaults for request and specification artifacts

Unless the user explicitly overrides these paths, use:

```text
<feature-requests-root> = ${SLO_FEATURE_REQUESTS_DIR:-~/.slo/projects/<project_name>/feature-requests}
<feature-specifications-root> = ${SLO_FEATURE_SPECIFICATIONS_DIR:-~/.slo/projects/<project_name>/feature-specifications}
```

Use one folder per feature:

```text
<feature-requests-root>/
└── 01-example-feature/
    └── request.md

<feature-specifications-root>/
└── 01-example-feature/
    ├── overview.md
    ├── 01.a-sub-step.md
    └── plan.md
```

## Guidance

## Purpose

Convert a confirmed test plan (from `<feature-specifications-root>/`) into working integration test code using an **incremental, one-scenario-at-a-time** methodology. Each scenario is implemented, executed, and verified green before the next begins. Lessons learned from each scenario directly inform the implementation of the next.

This prompt exists because the alternative — writing all test code upfront and then running the full suite — produces compounding failures that are expensive to debug. When five scenarios fail simultaneously, the root causes blur together. When one scenario fails, the root cause is obvious.

---

## The Iron Rule

**One scenario at a time. Green before you move on.**

Never implement multiple scenarios in a single pass. Never defer "I'll fix that later." Each scenario is a self-contained cycle:

```
Read plan for scenario N
  → Implement the code for scenario N
  → Run ONLY scenario N
  → Debug until green
  → Record what you learned
  → Apply lessons to scenario N+1
  → As you finish verify you've not broken other working tests.
```

---

## When to Use This Prompt

Use this prompt when:

1. A confirmed test plan exists at `integration_tests/<feature-specifications-root>/`. This is a sample, these could exist at a different location
2. The user asks you to implement the tests from the plan
3. You have read and understood prompts 01 through 08 in this series

**Do not skip straight to code.** Read the plan fully before writing a single line. The plan is your contract — if something in the plan is wrong, surface it before implementing.

---

## Before You Start: Pre-Implementation Checklist

### Read the full plan

Read every section of the plan document. Do not skim. You need to internalize:

- **Section 4 (Scenarios)** — how many scenarios, what order, what depends on what
- **Section 5 (Setup)** — every domain, every column, every file that needs to exist
- **Section 6 (Code)** — the representative patterns and file structure
- **Section 7 (Execution Order)** — the dependency-ordered file creation sequence

### Verify infrastructure is running

Before writing any code, verify the test infrastructure per the plan's "Pre-Run Verification" section:

```bash
# API health
curl -sf http://localhost:18080/o/health

# Container status
docker ps --format "table {{.Names}}\t{{.Status}}" | grep orders_it_
```

If infrastructure is down, fix it first. Do not write code against a broken environment — you will not be able to tell whether failures are yours or the environment's.

### Identify the scenario order

Not all scenarios are equal. Implement them in this order:

1. **The baseline/happy-path scenario first** — it exercises the full Background setup and the core data flow. If this doesn't work, nothing else will.
2. **The core feature scenario second** — the new behavior being tested. It builds on the baseline's infrastructure.
3. **Alternative/negative scenarios after** — they reuse the Background and vary specific conditions.
4. **Regression scenarios last** — they confirm existing behavior is unchanged.

The plan's Section 4 usually lists scenarios in this order already. If it doesn't, reorder mentally before starting.

---

## Phase 1: Shared Infrastructure (Before Any Scenario)

Some code is shared across all scenarios and must exist before any scenario can run. Implement these first, following the plan's Section 7 (Execution Order):

### 1a. Domain helpers

Create or modify domain helper files in `src/domains/orders_service/`. These are the `create_*`, `update_*`, `delete_*` functions that scenarios depend on. Follow the conventions in prompt `05-step-definitions-with-domain-helpers.md`:

- One table = one domain module
- `create_/update_/delete_/build_` naming only
- `async` functions with `db: AppDBClient` as first parameter
- Named arguments at all call sites
- Google-style docstrings

### 1b. Fixture data generators

Create or modify fixture modules in `tests/fixtures/`. These are pure functions that return data (CSV strings, mapping dicts). No side effects.

### 1c. Assertion and polling helpers

Add new query functions to `tests/helpers/db_assertions.py` and new `wait_for_*` wrappers to `tests/helpers/polling.py` as specified in the plan.

### 1d. Teardown updates

Update `src/domains/orders_service/teardown.py` if the plan specifies new tables that need cleanup. Add delete methods in the correct position within the reverse FK dependency chain.

### 1e. Feature file (all scenarios)

Write the complete `.feature` file with Background and all Scenarios. The Gherkin is the specification — it can be written in full because it contains no implementation logic. Having the full feature file up front lets you see the big picture while implementing one scenario at a time.

### 1f. Conftest scaffolding

Create the scenario conftest (`tests/conftest_{scenario}.py`) with:
- Session-scoped fixtures (mock servers, DB pool)
- Function-scoped fixtures (context dict, client aliases)
- Autouse fixtures (mock reset, teardown)

Register it in `tests/conftest.py`.

**Do not write the step definition file yet.** That happens scenario by scenario.

---

## Phase 2: Implement One Scenario at a Time

For each scenario, follow this exact cycle. No shortcuts.

### Step 1: Read the plan for this scenario

Re-read Section 4 for this specific scenario. Identify:

- **What Given steps are needed** beyond the shared Background
- **What When step triggers the action**
- **What Then steps make assertions** — the exact table, column, and expected value
- **What context keys flow between steps**

### Step 2: Write the step definitions for this scenario only

In the step definitions file (`tests/step_defs/test_{scenario}_steps.py`):

- Add the `@scenario` declaration for this one scenario
- Implement the `@given`, `@when`, `@then` steps that this scenario needs
- If this is the first scenario, you are also implementing the shared Background steps

**Do not implement steps for other scenarios.** If a later scenario needs a step that this scenario also uses, implement it now with the correct abstraction level. But do not implement steps that only future scenarios need.

### Step 3: Run this scenario alone

```bash
cd /path/to/integration_tests
loadenv environments/local.env && poetry run pytest -s tests/step_defs/test_{scenario}_steps.py::test_{this_scenario_function} -v
```

Run **only this one scenario**. Not the full file. Not the full suite. One scenario.

### Step 4: Debug until green

If the scenario fails:

1. **Read the error message carefully.** Classify it using the failure categories from prompt `07-debugging-failing-tests.md`.
2. **Trace the failure to its root cause.** Do not guess. Read container logs, query the database, check the mock server's `/mock/requests` endpoint.
3. **Make the minimal fix.** Change only what is broken. Do not refactor, do not improve, do not "while I'm here" other code.
4. **Re-run only this scenario.** Confirm the fix works before moving on.

Common first-scenario failures:

| Failure | Likely cause |
| --- | --- |
| `401 Unauthorized` | API key not seeded, or clock skew |
| `TimeoutError` waiting for CSV import | Celery worker not running, or `SOR_ENABLED` not set |
| `None` where a record is expected | Domain mapping key mismatch, or internal_key not on DAO |
| `ForeignKeyViolationError` on teardown | Missing table in teardown order |
| Step function not found | `@scenario` declaration missing or Gherkin text doesn't match step pattern exactly |

### Step 5: Record what you learned

After the scenario passes, note any lessons that affect subsequent scenarios. These are not abstract observations — they are concrete facts:

- "The `mapped_order` record takes ~8 seconds to appear; set polling timeout to 15s minimum"
- "The `tenant_details` domain helper needs `is_bundled` as an explicit parameter, not a default"
- "The teardown must delete `order_bundles` before `orders` — added to `_RACEABLE_CHILD_TABLES`"
- "The Gherkin step `an order CSV is uploaded` must include the row count in the pattern because the polling helper needs `expected_count`"

These lessons become inputs to the next scenario's implementation. Each subsequent scenario benefits from the accumulated knowledge of all prior scenarios.

### Step 6: Move to the next scenario

Only after the current scenario is green. Repeat Steps 1-5.

When implementing the second and subsequent scenarios:

- **Reuse existing steps** — if a step from a previous scenario applies, use it as-is
- **Parameterize if needed** — if two scenarios use the same step pattern with different values, convert to `parsers.parse()` now
- **Do not break existing scenarios** — after implementing a new scenario, run ALL implemented scenarios to confirm no regressions:

```bash
loadenv environments/local.env && poetry run pytest -s tests/step_defs/test_{scenario}_steps.py -v
```

This is the only time you run multiple scenarios — after adding a new one, to catch regressions.

---

## Phase 3: Full Suite Verification

After all scenarios pass individually:

1. Run the entire step definition file:
   ```bash
   loadenv environments/local.env && poetry run pytest -s tests/step_defs/test_{scenario}_steps.py -v
   ```

2. Run the full test suite to confirm no cross-scenario interference:
   ```bash
   loadenv environments/local.env && poetry run pytest -s tests/ -v
   ```

3. If any test fails that passed individually, the cause is **shared state pollution** — check teardown completeness and fixture isolation.

---

## The Learning Loop in Practice

The iterative approach is not just about catching bugs early. It is about building a **mental model of the system under test** that improves with each scenario.

### Scenario 1 teaches you:
- How long async processing actually takes (not what you estimated)
- Which environment variables the container actually needs
- Whether the mock server's response format matches what the code expects
- Whether the teardown order is actually correct

### Scenario 2 benefits from:
- Accurate polling timeouts (not default guesses)
- Known-good Background steps (no re-debugging setup)
- Correct mock server configuration
- Proven teardown that doesn't leave orphaned records

### Scenario N benefits from:
- A complete library of working steps to reuse
- Confidence that the shared infrastructure is solid
- Knowledge of the system's actual behavior (not the spec's description)
- Understanding of which assertions need polling and which are synchronous

### What to do when a later scenario reveals a problem with an earlier one

Sometimes Scenario 3 reveals that the Background setup from Scenario 1 was subtly wrong — it worked for Scenario 1 by coincidence but fails for Scenario 3's different inputs.

When this happens:

1. **Fix the shared infrastructure** (Background steps, domain helpers, fixtures)
2. **Re-run ALL previously passing scenarios** — confirm they still pass with the fix
3. **Then continue with the current scenario**

Do not hack around the problem by adding scenario-specific workarounds. Fix it at the root.

---

## Anti-Patterns

| Anti-pattern | Why it fails | What to do instead |
| --- | --- | --- |
| Write all steps for all scenarios, then run | Failures compound — 5 broken scenarios produce 15 interleaved errors | One scenario at a time |
| Copy-paste step implementations from the plan without understanding | Plan shows representative code, not production code; subtle differences cause failures | Use plan patterns as guides, write code that fits the actual infrastructure |
| Skip running after implementing a scenario because "it's simple" | Simple scenarios reveal infrastructure problems that complex scenarios hide | Always run. No exceptions. |
| Fix a failing scenario by weakening the assertion | Weak assertions pass but don't verify the feature | Fix the code or the setup, not the assertion |
| Implement all Background steps as one giant function | When Background fails, you can't tell which step broke | Each Background step is a separate `@given` function |
| Move to the next scenario while the current one is failing | You lose the context of what's broken when you context-switch | Green before you move on |
| "Fix" a timeout by increasing it to 120s | The real issue is a missing env var or a dead worker | Diagnose the root cause; reasonable timeouts are 15-30s |
| Re-run the full suite after every single change | A full suite run takes minutes; a single scenario takes seconds | Run only the current scenario until green |

---

## Communication Cadence

Keep the user informed at natural milestones:

1. **Before starting** — confirm the scenario order and total count: "The plan has 4 scenarios. I'll implement them in order: baseline, bundle reuse, no-sibling fallback, regression."
2. **After each scenario passes** — brief status: "Scenario 1 (baseline) passes. Learned that mapped_order polling needs 15s. Moving to Scenario 2."
3. **When stuck on a failure** — share what you've tried and what you suspect: "Scenario 2 fails at the bundle assertion. I've verified the order exists and `client_user_id` is populated. Checking whether `is_bundled` is set on `tenant_details`."
4. **After all scenarios pass** — final summary with any lessons worth remembering.

Do not dump raw test output. Summarize what passed, what failed, and what you did about it.

---

## Checklist: Completing a Scenario

Before marking a scenario as done:

- [ ] The `@scenario` declaration exists and matches the Gherkin exactly
- [ ] All `@given`, `@when`, `@then` steps for this scenario are implemented
- [ ] The scenario runs and passes in isolation (`pytest ... ::test_this_scenario`)
- [ ] All previously passing scenarios still pass (`pytest ... test_{scenario}_steps.py`)
- [ ] No `time.sleep()` calls — use `poll_until` / `wait_for_*` helpers
- [ ] No hardcoded IDs or timestamps — use context values from setup steps
- [ ] Assertion messages are explicit: `assert x == y, f"Expected {y}, got {x}"`
- [ ] Teardown cleans up all records created by this scenario
- [ ] Lessons learned are noted for subsequent scenarios

---

## Checklist: Completing All Scenarios

Before declaring the plan fully implemented:

- [ ] Every scenario in the plan's Section 4 has a passing `@scenario` test
- [ ] The full step definition file passes end-to-end
- [ ] The full test suite passes (no regressions in other test files)
- [ ] Teardown is complete — no orphaned records after any test
- [ ] All new domain helpers follow the conventions in prompt 05
- [ ] All new files follow the naming conventions in prompt 04
- [ ] The conftest is registered in `tests/conftest.py`
- [ ] No secrets committed (API keys, passwords, connection strings)
