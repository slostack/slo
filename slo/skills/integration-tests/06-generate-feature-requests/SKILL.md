---
name: 06-generate-feature-requests
description: 'Integration tests: drafting the feature-request docs that precede integration
  tests.'
when_to_use: Use when capturing what behavior a new integration test should verify.
group: integration-tests
kind: workflow
source_prompt: integration-tests/06-generate-feature-requests.md
---

# Generating Integration Test Feature Requests

## Skill summary

- **Name:** `06-generate-feature-requests`
- **Description:** Integration tests: drafting the feature-request docs that precede integration tests.
- **When to use:** Use when capturing what behavior a new integration test should verify.
- **Group:** `integration-tests`
- **Kind:** `workflow`
- **Source prompt:** `integration-tests/06-generate-feature-requests.md`

## Examples

- The user asks for an end-to-end workflow that fits: Integration tests: drafting the feature-request docs that precede integration tests.
- Use when capturing what behavior a new integration test should verify.

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

Guide the creation of feature request documents for the `integration_tests` repository. A feature request is the planning artifact that precedes all test implementation — it specifies what to test, what the preconditions are, what assertions to make, and how the test code should be structured. No integration test should be written without a feature request.

Feature requests live at `<feature-requests-root>/` and are numbered sequentially (e.g., `09-first-party-sms-outbound-notification.md`).

---

## When To Create a Feature Request

Create a feature request when:

1. A new feature specification describes cross-service behavior that integration tests should cover
2. A ticket implements a workflow spanning multiple services (orders_service, notifications_service, admin_ui, payments_service)
3. An existing feature has been significantly refactored and existing integration tests may need updating or new scenarios
4. A production incident reveals a gap in cross-service test coverage

---

## Step 1: Gather Source Material

### Read the Feature Specification

If specs live in Confluence, use the Atlassian MCP tools to fetch the page content. The cloud ID is `<atlassian-cloud-id>`.

```
mcp__claude_ai_Atlassian__getConfluencePage(
    cloudId="<atlassian-cloud-id>",
    pageId="<page-id>",
    contentFormat="markdown"
)
```

Extract the page ID from the Confluence URL:
- `<confluence-base-url>/wiki/spaces/<space>/pages/<page-id>/...`

Read the specification thoroughly. Identify:
- What is changing (new service, new routing logic, new data flow)
- What stays the same (regression boundaries)
- The data flow from entry point to final state
- External service dependencies (the fulfillment partner, the SMS provider, the payment gateway)
- Database tables affected
- Events published

### Orient in the Codebase

Read the reference files in each relevant repository:

| Repository | Files to Read |
| --- | --- |
| `integration_tests` | `AGENTS.md`, `RESEARCH.md` |
| `orders_service` | `AGENTS.md`, `RESEARCH.md` |
| `notifications_service` | `AGENTS.md`, `RESEARCH.md` (if notifications are involved) |
| `admin_ui` | `AGENTS.md`, `RESEARCH.md` (if admin UI is involved) |
| `payments_service` | `AGENTS.md`, `RESEARCH.md` (if payments are involved) |

These files are comprehensive indexes — use them to locate specific services, routers, domain models, events, and workers without guessing.

### Read the Actual Implementation

After reading the specification, **verify what is actually implemented** in the source code. The spec describes the design intent; the code is the truth. For each major component mentioned in the specification:

1. **Find the file** — use the RESEARCH.md index or grep for class/function names
2. **Read the implementation** — confirm method signatures, field names, routing logic, error handling
3. **Read the unit tests** — they reveal edge cases, expected behavior, and the service's test contract
4. **Note discrepancies** — if the code differs from the specification, the feature request should reflect the code, not the spec

This step is non-negotiable. Feature requests that parrot the spec without verifying the code produce integration tests that test the wrong thing.

### Study Existing Feature Requests

Read 2-3 existing feature requests to internalize the format:

```
<feature-requests-root>/03-csv_import_order_creation_partner/request.md
<feature-requests-root>/08-primary-order-bundle/request.md
<feature-requests-root>/09-first-party-sms-outbound-notification/request.md
```

---

## Step 2: Write the Feature Request

### Document Structure

Every feature request follows this structure. All sections are mandatory.

```markdown
# Cross-Service Integration Test: <Feature Name>

**Date:** <YYYY-MM-DD>
**Status:** Awaiting confirmation to proceed
**Repos in scope:** <comma-separated list>
**Spec:** `<page title>`
**Ticket:** `<ticket-id>`

---

## Feature Description And Context
## Existing Code Paths
## Feature Detection
## Setup
## Integration Test Code
## Teardown
## Key Code References
## Related Feature Requests
## Related Scenarios
```

### Section Details

#### Feature Description And Context

2-3 paragraphs explaining:
- What the feature does in business terms
- Why it exists (what problem it solves, what it replaces)
- What changes vs. what stays the same
- Which services are involved

Do NOT copy-paste the specification. Synthesize it into a concise explanation focused on what integration tests need to verify.

#### Existing Code Paths

This section maps the feature's implementation to actual files, classes, and methods in the source repositories. For each major component:

- **File path** (relative to the repository root)
- **Class name** and key method signatures
- **Line numbers** where routing decisions, data transformations, or state changes happen
- **DAO/model fields** that the tests will need to seed or assert against

Use tables for field mappings. Use code blocks for method signatures. Reference specific line numbers so test authors can navigate directly to the code.

This section answers: "What code exists today that the integration tests will exercise?"

#### Feature Detection

This is the core section. It identifies every testable scenario with:

**Per scenario:**
1. **Scenario number and title** — sequential, descriptive
2. **Description** — 1-2 sentences on what this scenario verifies
3. **Preconditions** — numbered list of every database record, configuration setting, and service state required before the test action
4. **Action** — the specific API call, event, or trigger that kicks off the workflow
5. **Assertions** — checkbox list of every verifiable outcome (database state, event payload, API response, error behavior)

**Scenario categories to always consider:**

| Category | Example |
| --- | --- |
| **Happy path** | Feature works as designed with all data present |
| **Missing optional data** | Nullable fields are null — feature still works |
| **Routing/branching** | Feature correctly routes to the right code path based on input |
| **Regression** | Existing behavior for other tenants/flows is unchanged |
| **Error handling** | Missing required data, service unavailable, invalid state |
| **Event publishing** | Correct events are published with correct payloads |
| **Configuration-driven behavior** | Feature behavior changes based on SystemConfiguration values |

**Precondition detail level:** List every database record by table name and the specific field values that matter. Integration tests seed data directly — they need exact column names and values, not abstract descriptions.

**Assertion detail level:** Each assertion is a single, testable statement. Use the format:
```
- [ ] `<table>.<field>` = `<expected_value>` (or is `None`, or is NOT `None`)
```

#### Setup

Numbered list of everything needed before tests run:

1. **Database records** — each table, with the specific fields and values to seed
2. **Environment configuration** — env vars needed (with `ORDERS_IT_` prefix for test harness vars)
3. **Mock services** — which external services need mocks, and which don't
4. **Docker services** — which compose files to start
5. **Special considerations** — workers that need to be enabled, event history to assert against, etc.

#### Integration Test Code

Concrete code examples showing:

1. **Fixtures** — complete fixture function for seeding the test context (using domain helper conventions from `05-step-definitions-with-domain-helpers.md`)
2. **Step definitions** — example `@given`, `@when`, `@then` functions following the four-section layout (from `04-scenario-conventions.md`)
3. **DB assertion helpers** — new query functions needed in `tests/helpers/db_assertions.py`
4. **Polling patterns** — async wait functions for eventually-consistent operations

Code examples must follow ALL conventions from the integration test prompt suite:
- Sync step functions using `run_async()` for async operations
- `context` dict for state passing between steps
- `parsers.parse()` for parameterized steps
- Domain helpers in `src/domains/orders_service/` (not raw SQL in steps)
- Named arguments at all call sites
- Google-style docstrings
- `create_/update_/delete_/build_` naming convention (never `seed_/setup_/teardown_`)

#### Teardown

Numbered list of records to delete, in reverse FK dependency order. Note which records the existing `teardown_tenant()` handles and which need new delete methods.

#### Key Code References

Table with columns: Step | File | Class/Method

Maps each phase of the workflow to its implementation. This is the lookup table that test authors use to find the code they're testing.

#### Related Feature Requests and Scenarios

Links to related documents in the `<workspace>/` directory. This connects the feature request to the broader test planning context.

---

## Step 3: Seek Confirmation

After writing the feature request, present a summary to the user with:

1. The number of scenarios identified
2. A table mapping each scenario to what it verifies
3. Any open questions or ambiguities discovered during research
4. Any discrepancies between the spec and the actual code

Wait for user confirmation before proceeding to test implementation.

---

## Quality Checklist

Before presenting the feature request for review:

- [ ] **Spec read** — page fetched and understood
- [ ] **Source code verified** — every file, class, and method referenced in the doc has been read in the actual codebase (not assumed from the spec)
- [ ] **Unit tests reviewed** — existing unit test coverage identified to avoid duplication
- [ ] **All scenarios cover cross-service behavior** — not internal logic that unit tests already cover
- [ ] **Preconditions are complete** — every database record needed is listed with table name and field values
- [ ] **Assertions are specific** — each assertion names a table, field, and expected value
- [ ] **Happy path AND edge cases** — at minimum: happy path, missing optional data, regression for unchanged flows, error handling
- [ ] **Code examples follow conventions** — matches patterns in prompts 01 through 05
- [ ] **Teardown is complete** — every created record has a corresponding delete step
- [ ] **Key Code References table** — every workflow step maps to a file and method
- [ ] **No duplicate coverage** — integration tests verify cross-service wiring, not internal logic
- [ ] **File numbered correctly** — sequential number matching the feature-requests directory

---

## Anti-Patterns

| Anti-Pattern | Why It's Wrong | What To Do Instead |
| --- | --- | --- |
| Copy-pasting the spec as the feature description | Specs describe design intent, not implementation truth | Synthesize the spec into test-relevant context; verify against actual code |
| Writing scenarios that test internal method logic | Unit tests already cover this; integration tests add no value | Focus on cross-service API calls, event propagation, end-to-end data flow |
| Listing preconditions as abstract concepts ("a tenant exists") | Test authors need exact table names and field values to write seed SQL | List every record: table name, column names, specific values |
| Assertions that check "the API returns success" | Success doesn't mean the right thing happened | Assert on database state, event payloads, mock server received requests |
| Skipping the "Existing Code Paths" section | Without it, test authors guess at field names and routing logic | Read the code; document file paths, line numbers, method signatures |
| Writing 20+ scenarios for a single feature | Most features need 5-10 scenarios; more indicates testing internal branches | Collapse similar scenarios; focus on distinct cross-service behaviors |
| Feature requests without code examples | The gap between "what to test" and "how to test" is where mistakes happen | Include fixtures, step definitions, and assertion helpers |

---

## File Naming Convention

```
<number>-<kebab-case-feature-name>.md
```

The number is the next sequential integer after the highest existing file in `<feature-requests-root>/`. Check the directory before creating the file.

Examples:
- `03-csv_import_order_creation_partner.md`
- `08-primary-order-bundle.md`
- `09-first-party-sms-outbound-notification.md`
