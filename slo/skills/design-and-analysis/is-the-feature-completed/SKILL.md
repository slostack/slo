---
name: is-the-feature-completed
description: Verify acceptance criteria against the original specification, current implementation and executable evidence.
when_to_use: Use to assess what remains before declaring a feature done — checklist-style
  traversal of acceptance criteria vs. what shipped.
group: design-and-analysis
kind: skill
source_prompt: analyze/is-the-feature-completed.md
---

# Is The Feature Completed?

## Skill summary

- **Name:** `is-the-feature-completed`
- **Description:** Verify acceptance against the original specification and current evidence.
- **When to use:** Use to assess what remains before declaring a feature done — checklist-style traversal of acceptance criteria vs. what shipped.
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Source prompt:** `analyze/is-the-feature-completed.md`

## Examples

- The user asks for help with: Estimating implementation completeness against a spec.
- Use to assess what remains before declaring a feature done — checklist-style traversal of acceptance criteria vs. what shipped.

## Guidance

**Multi-language scope:** Begin with `skills/engineering/engineering-routing/SKILL.md`.
Read shared obligations and only affected language/component/framework recipes.
Python-specific examples and commands below are scoped examples, not universal
requirements. For mixed-language work preserve each boundary's approved contract.
Use `skills/engineering/engineering-testing/SKILL.md` for test categories and evidence.

Use this prompt when you need to assess how much of a feature (from a Confluence spec, JIRA ticket, or verbal description) has actually been implemented in the codebase, and what remains.

---

## Purpose

Verify the agreed acceptance checklist against the original specification and current
implementation/evidence. Completion is an evidence gate, not an estimated percentage.
Reuse the current routing record, read relevant authoritative rules, and validate
changed inputs. Do not rederive unrelated context or assume author/reviewer READY
means the work is correct. Explicit deferrals and baseline exceptions remain visible.

---



## Inputs

The operator must provide at least one of:

1. **Confluence page URL(s)** — the feature specification to evaluate against
2. **JIRA ticket ID or URL** — a requirement or story describing the feature
3. **Feature description** — a plain-text description of the feature to assess

Optional:

4. **Scope narrowing** — specific sub-features or components to focus on (e.g., "just the SMS and Email lists, not the call lists")

---

## Step 1 — Understand The Requirement

### 1.1 Gather The Specification

Fetch the feature specification from the provided source:

- **Confluence pages** — use MCP tools or WebFetch to retrieve page content. If authentication fails, check for local copies in `<feature-specifications-root>/` or ask the user to provide the content.
- **JIRA tickets** — fetch the ticket description and any linked Confluence pages.
- **Verbal descriptions** — clarify with the user until you have a concrete list of expected deliverables.

If the specification references sub-pages or child features, fetch those too. The goal is a complete picture of what the feature requires.

### 1.2 Extract Expected Deliverables

Reconcile the existing acceptance IDs against the original specification. Add a missing item only with its source requirement or concrete correctness/safety defect; recommendations do not invent scope. Organize required deliverables by journey, using layers as a secondary omission check:

| Layer | Examples |
|-------|----------|
| **Database** | Alembic migrations, new tables, column additions, indexes |
| **Domain** | Models, DAOs, domain services (CRUD, business logic) |
| **Application Services** | Orchestration services following the `invoke()` pattern |
| **Workers** | Celery tasks, DBOS workflows, scheduled jobs |
| **Routers / API** | HTTP endpoints, request/response schemas |
| **Events** | Event definitions, handlers, NATS subscriptions |
| **ClickHouse** | Tables, materialized views, S3 export queries |
| **Integrations** | External API clients, vendor connectors |
| **Admin UI** | Templates, frontend routes, HTMX components |
| **Configuration** | Environment variables, constants, enums, feature flags |
| **Tests** | Unit tests, integration tests, fixtures |

Not every feature touches every layer. Only include layers that the specification requires.

### 1.3 Read Code Prompts

Read `skills/coding/coding-rules/SKILL.md`, then the applicable generic, language, framework, and test owners to understand the implementation patterns expected for each layer. This ensures you know what a "complete" implementation looks like in this codebase.

---

## Step 2 — Search The Codebase

### 2.1 Direct Search

For each expected deliverable, search the codebase for evidence of implementation:

- **Glob** for expected file paths (e.g., `src/domains/sms_list/**/*.py`)
- **Grep** for domain-specific keywords (e.g., `sms_list`, `email_list`, `SMS_LIST_EXPORTER`)
- **Grep** for class names, table names, enum values, and constants mentioned in the spec
- **Check migrations** — search `alembic/versions/` for table or column names
- **Check constants/enums** — look for new enum values in relevant constant files
- **Check workers** — search `src/tasks/` and `src/tasks/dbos_workers/` for new task registrations
- **Check tests** — search `tests/` for test files covering the feature

### 2.2 Adjacent Feature Analysis

If the feature is partially or fully absent, identify the closest analogous feature that IS implemented. This is critical for producing actionable implementation guidance.

Search strategy:

1. Look for sibling implementations in the same app or domain (e.g., if `ai_call_list` exists but `sms_list` doesn't, `ai_call_list` is the analogue)
2. Look for features that share the same base class or pattern (e.g., subclasses of the same abstract service)
3. Look for features mentioned alongside the missing one in the spec or RESEARCH.md
4. Read the relevant adjacent implementation when it helps resolve an actual gap; do not require unrelated full-feature reading

### 2.3 Read Existing Implementations

For any files found (complete or partial), read them in full. Do not assume a file's existence means the implementation is complete — verify the content matches what the spec requires.

---

## Step 3 — Assess Completion

### 3.1 Score Each Deliverable

For each acceptance ID assign an evidence-backed status:

| Status | Meaning |
|--------|---------|
| **Done** | Required behavior is implemented, wired and verified by appropriate current evidence |
| **Partial** | Some required behavior or wiring is missing or incorrect |
| **Not Started** | Search found no implementation |
| **Unverified** | Implementation exists but required evidence is missing, stale or blocked |
| **Deferred** | Operator approved explicit deferral; record authority, scope and consequence |

### 3.2 Calculate Completion Percentage

Do not use weighted percentages or half-credit for partial items as an acceptance
gate. Report verified counts against stable acceptance IDs. If the operator requests
an estimate, label its assumptions; a percentage cannot establish readiness or hide
one critical missing item. Only explicit deferral changes the accepted delivery scope.

### 3.3 Infrastructure Assessment

Check infrastructure only where a requirement depends on it: schema, configuration,
registration, adapters and resource ownership. Record concrete blockers and evidence,
not a speculative infrastructure-readiness percentage. A working scaffold is not a
verified user journey.

---



## Step 4 — Present The Assessment

### 4.1 Summary Table

Report feature/spec source, verdict, verified/required acceptance counts, required
verification gates, independent review status and explicit exceptions/deferrals.
For an assessment-only request, report status without silently starting implementation.

### 4.2 Detailed Status By Layer

Use a compact table: acceptance ID | source | journey/boundary | status | implementation
paths | executable evidence | remaining blocker. Layer labels are optional aids,
not extra requirements. Distinguish code inspection from tests actually executed.

### 4.3 Existing Implementation Files

Reference the implementing files and current evidence; file existence alone is not
proof. Reuse valid evidence when its inputs are unchanged; revalidate affected proof
after revisions. Do not require a fresh full scan of unrelated components.

### 4.4 Pending Items

For each missing, partial or unverified item give its source, evidence gap, affected
path, next action and closure condition. Give adjacent patterns or code snippets only
when they help resolve a real implementation gap. Identify environment/authorization
blockers separately; never silently replace a required gate with weaker evidence.

### 4.5 Dependency Graph

When several pending items have meaningful dependencies, show their order. Otherwise
a short ordered list suffices. Do not manufacture diagrams or new implementation scope.

---



## Step 5 — Verify Your Assessment

Before presenting results:

- [ ] Original-spec reconciliation accounts for every required acceptance item
- [ ] Done items have current implementation, wiring and appropriate passing evidence
- [ ] Unverified/blocked/skipped checks are not counted as passing
- [ ] Final independent review is accepted and its blockers are closed
- [ ] Required gates pass with no introduced regressions; exceptions have explicit approval
- [ ] Each pending item cites its source and closure condition
- [ ] Explicit deferrals are authorized and visible, not silently removed from the checklist

**READY:** every nondeferred requirement is verified, independent final review is
accepted, required gates pass and no unresolved blockers remain. **REVISE:** concrete
implementation/evidence gaps remain; return to the responsible implementation phase,
retest and re-review affected changes. Report an external blocker as incomplete;
execution failure is FAILED, not approval. Never invent a waiver to finish the loop.

## Conventions

Search before declaring an item absent; use relevant alternate names rather than a
fixed search-count ritual. Read the actual implementation. Keep source and evidence
paths precise, preserve applicable coding conventions, and order pending work by
real dependencies. Completion verifies the contract; it does not create a new one.
