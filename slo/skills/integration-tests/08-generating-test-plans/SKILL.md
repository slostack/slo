---
name: 08-generating-test-plans
description: 'Integration tests: generating detailed test plans before writing complex
  integration test code.'
when_to_use: Use when the scenarios are non-trivial and you need a plan before coding.
group: integration-tests
kind: workflow
source_prompt: integration-tests/08-generating-test-plans.md
---

# Generating Integration Test Plans

## Skill summary

- **Name:** `08-generating-test-plans`
- **Description:** Integration tests: generating detailed test plans before writing complex integration test code.
- **When to use:** Use when the scenarios are non-trivial and you need a plan before coding.
- **Group:** `integration-tests`
- **Kind:** `workflow`
- **Source prompt:** `integration-tests/08-generating-test-plans.md`

## Examples

- The user asks for an end-to-end workflow that fits: Integration tests: generating detailed test plans before writing complex integration test code.
- Use when the scenarios are non-trivial and you need a plan before coding.

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

Generate a detailed, unambiguous test plan document from a feature request before writing any test code. The plan is the contract between the person who understands the feature and the AI (or developer) who implements the tests. A good plan eliminates guesswork at implementation time. A bad plan forces the implementer to re-discover context that the plan author already had.

This prompt defines the exact sections, the required level of detail per section, and the research methodology that must be followed when producing a test plan.

---

## When to Use This Prompt

Use this prompt when a feature request file exists at `<feature-requests-root>/` and asks you to generate a plan. The plan goes into `integration_tests/<feature-specifications-root>/`.

**Do not write test code until the plan is confirmed.** The workflow is:

1. Read the feature request
2. Research the codebase (this prompt tells you how)
3. Generate the plan document
4. Seek confirmation
5. Only then implement

---

## Research Phase — What to Read Before Writing a Single Line of the Plan

The plan cannot be generated from the feature request alone. You must read actual source code and actual test infrastructure. Skipping any of these steps produces a plan with gaps that the implementer will hit during coding.

### Step 1: Read the Feature Specification

Read the documents referenced in the feature request:

- **Confluence pages** — use the Atlassian MCP tool with cloud ID `<atlassian-cloud-id>` and the tiny link ID from the URL (the part after `/wiki/x/`)
- **Tickets** — use the Atlassian MCP tool or `gh` CLI
- **Code PRs** — if the feature request references a PR, read its diff

Extract from these:
- What changed and why
- Which tables have new columns
- Which services have new logic
- What the expected behavior is before and after the change

### Step 2: Read the Source Code in orders_service

Trace the feature's code path end-to-end. For every file mentioned in the spec or ticket:

1. **Read the model** — know the exact column names, types, nullability, defaults, constraints
2. **Read the service** — know the business logic methods, their signatures, what they query
3. **Read the application service** — know the orchestration flow, what calls what
4. **Read the worker/event handler** — know what triggers the code (Celery task? NATS event? API call?)

You are looking for:
- **Gate conditions** — what must be true for the feature to activate (e.g., `tenant_details.is_bundled == true`)
- **Data dependencies** — what records must exist before the feature logic runs (e.g., `line_item.client_user_id` must be populated via attribute mapping)
- **Branching logic** — what are the different paths through the code (e.g., "if no sibling → new bundle; if sibling has bundle → reuse")

### Step 3: Read the Existing Integration Test Infrastructure

Read these files in the `integration_tests` repo:

| What to read | Why |
| --- | --- |
| All `.feature` files in `tests/features/` | Know what scenarios already exist, avoid duplication |
| The step definition files in `tests/step_defs/` | Know the existing step patterns, how context flows, how fixtures are used |
| All domain helpers in `src/domains/orders_service/` | Know what create/update/delete helpers already exist |
| `tests/fixtures/attribute_mappings.py` | Know the existing mapping structures — placement, domain, SOR |
| `tests/fixtures/csv_imports.py` | Know the existing CSV column set and row data patterns |
| `tests/helpers/db_assertions.py` | Know what query helpers exist for assertions |
| `tests/helpers/polling.py` | Know what polling wrappers exist |
| `tests/helpers/api_client.py` | Know the API client methods available |
| `tests/conftest.py` | Know which conftest plugins are registered |
| `tests/conftest_*.py` | Know the fixture layering pattern (session/function/autouse) |
| `src/domains/orders_service/teardown.py` | Know the teardown order and what tables are cleaned up |

### Step 4: Read the Coding Convention Prompts

Read these before writing the plan so the plan's code examples conform:

| File | What it governs |
| --- | --- |
| `skills/integration-tests/04-scenario-conventions/SKILL.md` | File organization, naming, fixture layering, step patterns |
| `skills/integration-tests/05-step-definitions-with-domain-helpers/SKILL.md` | Domain helper structure, naming conventions, composability rules |

### Step 5: Read the Admin UI Code (if applicable)

If the feature involves the admin UI upload flow or any UI-driven action, also read the relevant code in `admin_ui`.

---

## Plan Document Structure

The plan document has **seven mandatory sections** in this exact order. Do not skip or merge sections. Each section exists because it answers a distinct question the implementer will have.

### File naming

`{NN}-{short-kebab-name}.md` in `<feature-specifications-root>/`. The number follows the last existing plan file.

---

### Section 1: Goal

**Question it answers:** "What are we testing and why?"

One paragraph. State the feature name, the ticket, and the core behavior being tested. Do not rehash the full spec — just enough context for someone who has never seen the ticket to understand the scope.

```markdown
## Goal

Test the **bundle reuse** feature (ISSUE-1234) for bundled tenants: when a new order
for the same partner customer is uploaded via a second CSV import, the system must reuse
the existing bundle — demoting the old primary order and promoting the new one —
instead of creating a separate bundle.
```

---

### Section 2: Feature Description and Context

**Question it answers:** "What does this feature do, technically?"

Three sub-sections:

1. **Problem** — what was wrong before. One sentence.
2. **Solution** — what the code does now. Numbered steps, each one sentence. Reference the actual method name and class.
3. **Key preconditions** — bullet list of what must be true for the feature to activate. These become the Background steps in the feature file.

---

### Section 3: Existing Code Paths

**Question it answers:** "Where is the code I need to understand?"

A table mapping each relevant source file (in `orders_service` or other service repos) to what it does for this feature. Include:

- The full relative file path (from the service repo root)
- The specific method/class name
- A one-line description of its role

Follow the table with an **ASCII data flow diagram** showing the execution path from trigger (e.g., CSV import) through each service/worker to the final database writes. This diagram is not decorative — it shows the implementer what happens in what order so they know where to insert assertions.

```markdown
### Data flow

```
Order CSV import
  → placement_mappings: "Customer_Ref" → internal_key "client_user_id"
  → domain_mappings: "client_user_id" → {"line_item": "client_user_id"}
  → Celery worker creates order, customer, line_item (with client_user_id)
  → _is_tenant_bundled() checks tenant_details.is_bundled
  → _create_order_bundle_for_bundled_tenant():
      if no client_user_id → new bundle
      elif no sibling line_items → new bundle
      elif sibling has bundle → reuse bundle (demote + promote)
      else → new bundle
```
```

---

### Section 4: Feature Detection — Scenarios to Test

**Question it answers:** "What behavioral scenarios need test coverage?"

Start with a **Background** sub-section listing numbered preconditions shared across all scenarios. These become the `Background:` block in the `.feature` file.

Then list each scenario with:
- **Scenario title** — becomes the Gherkin `Scenario:` name
- **Given** — any scenario-specific setup beyond the Background
- **When** — the action(s) performed
- **Then** — bullet list of every assertion. Be specific: name the table, the column, the expected value.

Include at minimum:
- A **baseline scenario** (happy path, first use)
- The **core feature scenario** (the new behavior being tested)
- A **negative/alternative scenario** (what happens when the feature gate is off, or a different input is used)
- A **regression scenario** (existing behavior that must not break)

Each assertion in the Then block must be verifiable by querying the database or checking the mock server. Do not include vague assertions like "the system should behave correctly."

---

### Section 5: Setup — Every Domain, Every Attribute, Every File

**Question it answers:** "What exact database records must exist, with what exact column values, in what files?"

This is the most critical section of the plan. It eliminates all ambiguity about test setup. The implementer should be able to write every `@given` step and every domain helper by reading only this section.

#### Structure

List domains in **FK dependency order** (parent → child). Number them sequentially. For each domain:

```markdown
### Domain N: `{table_name}`

**Table:** `{table_name}`
**Source model:** `{absolute path to the SQLAlchemy model in the service repo}`
**Integration test helper:** `{absolute path to the domain helper in the integration test repo}` — `{function_name}()` ({STATUS})
**Status:** {One of: "Already exists. No changes needed." | "EXISTING, needs new variant" | "NEW FILE. Does not exist yet."}

{If this is a new or critical domain: one paragraph explaining WHY this record must exist. Reference the exact line of source code that reads it. For example: "The `_is_tenant_bundled()` method at line ~865 of `upsert_customer_and_order_app_service.py` calls `TenantDetailService.get_by_tenant_id()` and checks `tenant_detail.is_bundled`."}

| Column | Value | Notes |
|--------|-------|-------|
| `{column_name}` | `{exact value or formula}` | {Why this value matters, or "Default"} |

**Stored in context:** `context["{key}"]` — {what it's used for downstream}
```

#### Column value rules

- **Show the exact value**, not a description. Write `"direct_sale"`, not "the service type".
- For auto-generated values, show the pattern: `"it-tenant-{uuid12}"`.
- For FK references, show the notation: `FK → tenants.id`.
- For JSON columns, show the **full JSON structure** or reference the builder function that produces it.
- For columns with server defaults that you rely on, list them explicitly with value "Default server_default". Do not omit them silently — the implementer needs to know you considered them.
- If a column varies between scenarios, add a column per scenario variant to the table.

#### When the helper file is NEW

Include:
1. The exact file path to create
2. The exact function signatures (name, parameters with types, return type)
3. The exact SQL statement
4. A note about which columns can be omitted due to server defaults

#### When the helper file needs MODIFICATION

Include:
1. The exact function to add (signature + docstring)
2. For fixture data (like attribute mappings), show the **full dict** that the new variant produces, not just the diff. The implementer should not have to mentally merge dicts.

#### Domain categories

Not all domains are database tables. The plan must also cover:

- **Mock servers** — what port, what endpoints, what they return, whether they already exist
- **CSV fixture data** — the exact column list, the exact row values (as a table with every column), the generator function signatures, and any uniquification rules (e.g., "suffix Order_Number but NOT Customer_Ref")
- **Assertion targets** — tables written by the system under test (not seeded by us). List the columns to assert, the expected values per scenario, and the assertion helper function (existing or to-be-created with exact SQL)
- **Polling helpers** — the new `wait_for_*` functions needed, with full implementation
- **Teardown** — the exact change to `teardown.py` (import line, insertion point, function call)

#### End with a summary table

After all domains, include a summary table:

```markdown
### Setup Summary — All Domains at a Glance

| # | Domain | Table | Status | File |
|---|--------|-------|--------|------|
| 1 | Tenant | `tenants` | EXISTING | `src/domains/orders_service/tenants.py` |
| 2 | ... | ... | ... | ... |
```

---

### Section 6: Integration Test Code — Implementation Details

**Question it answers:** "What files do I create/modify, and what patterns do I follow?"

Sub-sections:

1. **File structure** — an ASCII tree showing every NEW and MODIFIED file with a comment indicating NEW or MODIFY
2. **Fixture data snippets** — code blocks showing new CSV column constants, row data constants, and generator functions
3. **Attribute mapping snippets** — the new mapping dicts and builder functions
4. **Key step patterns** — example `@given`, `@when`, `@then` implementations for the most important steps (especially any that differ from existing patterns)
5. **Conftest notes** — whether the scenario needs its own conftest or can share an existing one, and why

This section shows **representative code**, not the complete implementation. Its purpose is to demonstrate the patterns so the implementer does not have to infer them. Show:
- One `@given` step that seeds the new domain
- One `@when` step that performs the feature-specific action
- One `@then` step that makes the critical assertion

---

### Section 7: Execution Order

**Question it answers:** "In what order should I implement the files?"

A numbered list of files to create/modify, ordered by dependency:
1. Domain helpers first (no dependencies)
2. Fixture data (depends on domain helpers for mapping awareness)
3. Assertion helpers (no test dependencies)
4. Polling helpers (no test dependencies)
5. Teardown updates (depends on domain helpers)
6. Feature file (depends on knowing the scenarios)
7. Step definitions (depends on all of the above)
8. Conftest (depends on knowing the fixture needs)
9. Conftest registration (last — wires everything together)

---

## Pre-Run Verification — Workers and Environment

Before running the tests, the plan must document what infrastructure the tests depend on and how to verify it is running. Tests that silently fail because a Celery worker isn't consuming its queue or an environment variable is missing waste hours of debugging.

### Required in the plan

Add a section between "Execution Order" and the first test run that covers:

1. **Required Celery workers and their queues.** For the CSV import → order creation flow, these are:
   - `celery_worker_general` consuming `create_staged_import_row_worker_queue`, `stream_event_handler_worker_queue`
   - `celery_worker_batch_run` consuming `batch_run_execution_worker_queue`
   
   Reference the launch script at `docker/scripts/launch_all_orders_service.sh` which documents all processes.

2. **Required environment variables.** The orders_service container must have:
   - `SOR_ENABLED=true` — gates order creation logic; without it, client validation blocks order upsert with `"Fields phone_number, full_name, ... must not be null"`
   - `SOR_NAME=partner` — identifies the SOR system
   - `PARTNER_BASE_URL=http://host.docker.internal:18090` — points to the mock fulfillment partner server on host
   - `USE_NATS_PUBLISHER=true` — enables event publishing
   - `USE_NATS_CONSUMER=true` — enables NATS stream consumer
   
   These are provided by `environments/local.env.partner` and injected via the `docker-compose.partner-mock.yml` override.

3. **Container launch command.** The correct way to start the stack for integration tests is:
   ```bash
   docker compose \
     -f docker/docker-compose.orders_service.yml \
     -f docker/docker-compose.partner-mock.yml \
     up -d
   ```
   Starting without the partner-mock override will cause all CSV-import-based tests to fail silently (the import reaches `processed` but no orders are created).

4. **Verification commands.** Before running tests, verify:
   ```bash
   # API is healthy
   curl -sf http://localhost:18080/o/health
   
   # Celery workers are consuming queues (check via Flower)
   curl -sf http://localhost:18080/flower/api/workers 2>/dev/null | python -m json.tool | head -20
   
   # Or check container logs for worker startup
   docker logs orders_it_api 2>&1 | grep "celery_worker"
   ```

---

## Quality Checklist

Before presenting the plan for confirmation, verify:

- [ ] **Every scenario's Background lists all preconditions** — no implicit setup
- [ ] **Every domain has a column-value table** — no "just use defaults" without showing what the defaults are
- [ ] **Every new file has exact function signatures** with parameter types and return types
- [ ] **Every new SQL statement is written out** — not described in prose
- [ ] **Every modified file names the specific function(s) to add** and shows the code
- [ ] **Every assertion names the table, column, and expected value** — not "should be correct"
- [ ] **Fixture uniquification rules are explicit** — which columns get suffixed, which must not
- [ ] **Teardown changes specify the exact insertion point** in the existing delete order
- [ ] **Context keys are documented** — every `context["key"]` that a Given step sets is listed with what downstream steps use it
- [ ] **The data flow diagram traces from trigger to database write** — no gaps in the chain
- [ ] **Status labels are honest** — "EXISTING" means you verified the file exists and has the needed function; "NEW" means you verified it does not exist
- [ ] **Source model paths are absolute** — the implementer should be able to open the file without searching
- [ ] **No section says "TBD", "to be determined", or "similar to existing"** — if you don't know, research it before writing the plan
- [ ] **Required Celery workers and queues are documented** — name the worker, the queue, and what it does in the test flow
- [ ] **Required environment variables are documented** — especially `SOR_ENABLED`, `SOR_NAME`, `PARTNER_BASE_URL`
- [ ] **Container launch command uses the partner-mock override** — `docker compose -f ... -f docker-compose.partner-mock.yml up -d`

---

## Anti-Patterns — What Makes a Plan Fail

| Anti-pattern | Why it fails | What to do instead |
| --- | --- | --- |
| "Use the existing attribute mapping" | Implementer doesn't know if the existing mapping has the new field | Show the full dict with the new field highlighted |
| "Create a tenant_detail record" | Implementer doesn't know which columns to set or what values | Show the column-value table with every column that matters |
| "Assert the bundle is reused" | Implementer doesn't know what SQL to run or what column to check | Write: "Assert `order_bundles.bundle_id` is the same UUID for both order_ids" |
| "Add a new domain helper" | Implementer doesn't know the function signature, the SQL, or where to put it | Show the file path, function signature, SQL, and which existing file to model it after |
| "Similar to the CSV import test" | Forces the implementer to re-read the CSV import test and figure out what's similar | Copy the relevant pattern inline with the specific values for this scenario |
| Omitting server-default columns from the table | Implementer doesn't know if you intentionally omitted them or forgot | List them with "Default server_default" in the Notes column |
| Describing a CSV row in prose | Implementer has to mentally construct the row | Use a column-value table with every field |
| "The fixture will handle uniquification" | Implementer doesn't know which columns to suffix | State explicitly: "Suffix columns at index 0 (Order_Number) and 11 (Ref). Do NOT suffix index 19 (Customer_Ref)." |

---

## Example Reference

See `<workspace>/integration_tests/<feature-specifications-root>/08-primary-order-bundle/plan.md` as a reference implementation of this prompt. It was the first plan generated following this methodology and demonstrates all seven sections at the required level of detail.
