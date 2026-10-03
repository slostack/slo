---
name: is-the-feature-completed
description: Estimating implementation completeness against a spec.
when_to_use: Use to assess what remains before declaring a feature done — checklist-style
  traversal of acceptance criteria vs. what shipped.
group: design-and-analysis
kind: skill
source_prompt: analyze/is-the-feature-completed.md
---

# Is The Feature Completed?

## Skill summary

- **Name:** `is-the-feature-completed`
- **Description:** Estimating implementation completeness against a spec.
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

Analyze a feature requirement against the current codebase to produce a completion assessment: what percentage is done, what percentage is missing, which files implement the completed parts, and what specific work remains — with file paths, code snippets, and implementation guidance derived from adjacent features that follow the same patterns.

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

From the specification, extract a concrete checklist of what "done" looks like. Categorize by implementation layer:

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

Read the relevant code-prompt files from `skills/coding/` to understand the implementation patterns expected for each layer. This ensures you know what a "complete" implementation looks like in this codebase.

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
4. Read the adjacent feature's complete implementation across all layers

### 2.3 Read Existing Implementations

For any files found (complete or partial), read them in full. Do not assume a file's existence means the implementation is complete — verify the content matches what the spec requires.

---

## Step 3 — Assess Completion

### 3.1 Score Each Deliverable

For each expected deliverable from Step 1.2, assign a status:

| Status | Meaning |
|--------|---------|
| **Done** | Fully implemented and matches spec requirements |
| **Partial** | File exists but implementation is incomplete or diverges from spec |
| **Not Started** | No evidence of implementation in the codebase |

### 3.2 Calculate Completion Percentage

```
Completion % = (Done count + Partial count * 0.5) / Total deliverables * 100
Incompletion % = 100 - Completion %
```

Weight the deliverables by effort if appropriate — a missing Alembic migration is smaller than a missing application service with 5 steps. Use your judgment to adjust weights, but state your reasoning.

### 3.3 Infrastructure Assessment

Separately assess how much supporting infrastructure already exists:

- Does the base class / abstract pattern exist? (e.g., `BaseStrategyListExporterAppService`)
- Do the enums, constants, and configuration keys exist?
- Is the database schema ready (columns in the source table, etc.)?
- Are adjacent features implemented that can be copied as templates?

This produces a second metric: **Infrastructure Readiness %** — how much of the scaffolding is already in place.

---

## Step 4 — Present The Assessment

### 4.1 Summary Table

```markdown
## Feature Completion Assessment

| Metric | Value |
|--------|-------|
| **Feature** | [Feature name] |
| **Source** | [Confluence URL / JIRA ticket / description] |
| **Completion** | XX% |
| **Incompletion** | XX% |
| **Infrastructure Readiness** | XX% |
```

### 4.2 Detailed Status By Layer

Present a table showing every expected deliverable, its status, and the implementing file (if any):

```markdown
### Status By Component

| Layer | Component | Status | File(s) |
|-------|-----------|--------|---------|
| Database | `sms_list` CH table | Not Started | — |
| Domain | `SMSListService` | Not Started | — |
| App Service | `SMSListExporterAppService` | Not Started | — |
| Worker | `sms_list_exporter_worker` | Not Started | — |
| Config | `JobType.SMS_LIST_EXPORTER` | Not Started | — |
| Database | `ai_call_list` CH table | Done | `src/apps/.../ai_call_list/service.py` |
```

### 4.3 Existing Implementation Files

If the feature is partially or fully implemented, list every file that contributes to it:

```markdown
### Implemented Files

- `src/apps/decision_strategy/domains/ai_call_list/service.py` — ClickHouse table, MV, S3 export
- `src/apps/decision_strategy/services/ai_call_list_exporter_app_service.py` — Export orchestration
- `src/apps/decision_strategy/tasks/dbos_workers/ai_call_list_exporter_worker.py` — DBOS worker
```

### 4.4 Pending Items

For each deliverable that is **Not Started** or **Partial**, provide:

1. **What needs to be built** — one-line description
2. **Where it goes** — full file path
3. **Pattern to follow** — the adjacent feature file to use as a template
4. **Key differences** — what changes from the template (e.g., different filter conditions, different column names, different enum values)
5. **Code snippet** — a succinct, representative code sample showing the core logic. Not the full file — just enough to convey the implementation shape and the specific differences from the template.

Structure this as a numbered list ordered by dependency (foundational items first).

```markdown
### Pending Implementation

**1. Add `DECISION_STRATEGY_SMS_LIST_EXPORTER` to JobType enum**

- **File:** `src/domains/jobs/constant.py`
- **Pattern:** Existing `DECISION_STRATEGY_AI_CALL_LIST_EXPORTER` entry
- **Change:** Add new enum value

  ```python
  DECISION_STRATEGY_SMS_LIST_EXPORTER = "DecisionStrategySmsListExporter"
  ```

**2. Create `SMSListService` domain service**

- **File:** `src/apps/decision_strategy/domains/sms_list/service.py` (new)
- **Pattern:** `src/apps/decision_strategy/domains/ai_call_list/service.py`
- **Key differences:**
  - Filter: `sms_flag = true AND sms_to IS NOT NULL AND sms_suppression_reason IS NULL`
  - Bucketing: `sms_send_time_utc` / `sms_send_time_local` instead of `phone_call_time_*`
  - Table name: `sms_list`, MV name: `mv_sms_list`

  ```python
  # Core MV filter (the main difference from ai_call_list)
  WHERE
      dt.sms_flag = true
      AND dt.sms_to IS NOT NULL
      AND dt.sms_suppression_reason IS NULL
  ```
```

### 4.5 Dependency Graph

If there are multiple pending items, show their dependency order:

```
1. JobType enum additions
    ├──→ 2. SMSListService (CH table + MV)
    │       └──→ 3. SMSListExporterAppService
    │               └──→ 4. sms_list_exporter_worker (DBOS)
    └──→ 5. EmailListService (CH table + MV)
            └──→ 6. EmailListExporterAppService
                    └──→ 7. email_list_exporter_worker (DBOS)
```

---

## Step 5 — Verify Your Assessment

Before presenting results:

- [ ] Every "Done" item was verified by reading the actual file content, not just checking file existence
- [ ] Every "Not Started" item was confirmed by searching for multiple possible naming conventions (the feature might exist under a different name)
- [ ] The adjacent feature used as a template was read in full
- [ ] Code snippets in pending items reflect the actual differences from the template, not generic placeholders
- [ ] The completion percentage accounts for effort weighting where appropriate
- [ ] Infrastructure readiness is assessed separately from feature-specific completion

---

## Conventions

- **Always search before concluding "Not Started"** — try at least 3 naming variations (e.g., `sms_list`, `smsList`, `sms_worklist`, `sms_send_list`)
- **Read, don't assume** — a file's existence doesn't mean it's complete. Read it and verify.
- **Be specific about differences** — don't say "similar to X but for SMS". Say exactly which filter conditions, column names, enum values, and S3 paths differ.
- **Order pending items by dependency** — foundational work first, consumer work last
- **Include the full file path** for every file mentioned — both existing and to-be-created
- **Reference code prompts** — when a pending item should follow a specific code-prompt pattern, mention it (e.g., "follows `skills/languages/python/build-domain-features/SKILL.md` pattern")
