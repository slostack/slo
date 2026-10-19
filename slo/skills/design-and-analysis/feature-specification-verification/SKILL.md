---
name: feature-specification-verification
description: Reviewing a draft spec for gaps, ambiguities, and redundant
  functionality that duplicates code the system already has, before implementation
  begins.
when_to_use: Use for independent adversarial review after author self-check, or standalone review of an existing spec — surfaces missing decisions,
  underspecified edge cases, and inconsistent acceptance criteria.
group: design-and-analysis
kind: workflow
source_prompt: analyze/feature-specification-verification.md
---

# Verify Feature Specification

## Skill summary

- **Name:** `feature-specification-verification`
- **Description:** Reviewing a draft spec for gaps, ambiguities, and redundant functionality that duplicates code the system already has, before implementation begins.
- **When to use:** Use for independent adversarial review after author self-check, or standalone review of an existing spec — surfaces missing decisions, underspecified edge cases, and inconsistent acceptance criteria.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `analyze/feature-specification-verification.md`

## Examples

- The user asks for an end-to-end workflow that fits: Reviewing a draft spec for gaps, ambiguities, and redundant functionality that duplicates code the system already has, before implementation begins.
- Use for independent adversarial review after author self-check, or standalone review of an existing spec — surfaces missing decisions, underspecified edge cases, and inconsistent acceptance criteria.

## Artifact paths and authoring contract

Use [the canonical authoring artifact paths and skill discovery](../feature-specifications/SKILL.md#artifact-paths-and-skill-discovery).
Repository overrides win over generic defaults. Every family requires overview.md
with product framing and separate standalone engineering sub-specs. Neither part
can substitute for the other, even for small features.

## Guidance

Use this prompt to review a feature specification document and identify gaps, ambiguities, and missing coverage before a developer begins implementation.

---

## Purpose

Act as a verification layer for specifications generated using [`feature-specifications.md`](../feature-specifications/SKILL.md). Review the spec against the source JIRA story, codebase architecture, coding conventions, and the **expected structure** (an overview vs a technical sub-spec, within the single specification family) to surface anything that was missed, under-specified, or structurally misaligned before implementation begins.

---

This is separate independent verification, not the author self-audit. Run the full
procedure even when the author report says READY. Return findings to
[authoring](../feature-specifications/SKILL.md#revise-and-hand-off). READY requires a
complete report and no outstanding CRITICAL gaps. Standalone reviews do not require
a previous author report; gather missing context and use the source ask when no JIRA
story exists. Do not recursively invoke author self-check during independent review.

## Inputs

The operator must provide:

1. **Feature specification document** — path to the spec file
2. **Source JIRA ticket ID or URL** — the original story/task that prompted the specification

Optional:

3. **Confluence page URL(s)** — if the JIRA ticket links to Confluence specs
4. **Scope constraints** — specific areas to focus the review on
5. **Expected artefact** (overview or technical sub-spec) — if already known from the Context Bundle

---

## Step 1 — Load Context

### 1.1 Read the Feature Specification

Read the spec document in full. Build a mental model of what the spec proposes.

Before judging structure, identify which artefact of the single specification family the document is, per [`feature-specifications.md`](../feature-specifications/SKILL.md). There is one spec shape — an **overview** plus one or more **technical sub-specs** — not a choice between a business document and an engineering document:

- **the overview** (`overview.md`) — product/business framing plus a brief technical overview;
- **a technical sub-spec** (`NN.a.n`) — one standalone engineering slice.

If the expected artefact was supplied and the document clearly uses the wrong structure for what it is, record a structure mismatch immediately.

Require both family artifacts even when reviewing a single revised file: locate
its overview.md and standalone engineering sub-specs and verify they remain
consistent. A missing overview or separate engineering sub-spec is a CRITICAL
STRUCTURE GAP; return it to authoring. No combined-document or partial-family
exception is permitted.

### 1.2 Fetch the Source JIRA Story

> This may not always be present or needed. 

Use `getJiraIssue` to fetch the original ticket. Extract:

- summary and description,
- acceptance criteria,
- comments,
- linked issues,
- subtasks,
- attachments,
- any linked Confluence pages.

### 1.3 Read Codebase Convention Files

Read the relevant code-prompt files to understand what a correct implementation looks like in this codebase. Err toward reading more rather than fewer.

### 1.4 Read RESEARCH.md

Read `RESEARCH.md` to understand existing domains, services, workers, integrations, and adjacent infrastructure the spec should reuse or acknowledge.

---

## Step 2 — Task/JIRA Requirement Traceability 

Every requirement in the source ask must map to something in the spec.

### 2.1 Extract All Requirements from Task Specification/JIRA

Parse the ticket into a numbered list of discrete requirements, including explicit requirements, implicit requirements, clarifications in comments, and descoped items.

### 2.2 Map Each Requirement to the Spec

For each extracted requirement, determine its coverage:

| Status | Meaning |
|---|---|
| **Covered** | The spec explicitly addresses this requirement with implementation detail |
| **Partially Covered** | The spec mentions it but lacks sufficient detail |
| **Not Covered** | The spec does not address it |
| **Intentionally Excluded** | The spec or ticket explicitly defers it |

### 2.3 Present the Traceability Matrix

```markdown
### Task/JIRA Requirement Traceability

| # | Requirement (from JIRA) | Spec Coverage | Spec Section | Notes |
|---|---|---|---|---|
| 1 | ... | Covered | ... | ... |
```

---

## Step 3 — Architectural Completeness Review

For each layer the spec touches, verify that the implementation is complete end-to-end.

### 3.1 Domain Layer Checklist

For every new or modified domain, verify the spec includes:

- [ ] `model.py`
- [ ] `dao.py`
- [ ] `service.py`
- [ ] Alembic migration or explicit instruction to generate one
- [ ] FK relationships and back-populates where needed
- [ ] indexes aligned to query patterns

### 3.2 Application Service Layer Checklist

For every application service, verify:

- [ ] file path follows conventions
- [ ] `invoke()` entry point is defined
- [ ] step-by-step control flow is documented
- [ ] error handling is described
- [ ] DB session / transaction boundaries are described
- [ ] dependencies are listed

### 3.3 Worker / Task Layer Checklist

For every worker or background task, verify:

- [ ] registration
- [ ] schedule if applicable
- [ ] idempotency
- [ ] failure handling / retry
- [ ] payload shape

### 3.4 Router / API Layer Checklist

For every endpoint, verify:

- [ ] HTTP method and path
- [ ] request schema
- [ ] response schema
- [ ] auth / authz
- [ ] OpenAPI docs expectations
- [ ] registration

### 3.5 Event Layer Checklist

For every event, verify:

- [ ] event name or type
- [ ] payload shape
- [ ] publisher
- [ ] subscriber(s)
- [ ] handler registration
- [ ] idempotency

### 3.6 Integration Layer Checklist

For every external interaction, verify:

- [ ] client location
- [ ] auth
- [ ] timeout / rate-limit / error handling
- [ ] config
- [ ] retry strategy

### 3.7 Database / ClickHouse Layer Checklist

- [ ] Postgres migrations
- [ ] ClickHouse DDL if applicable
- [ ] materialized views if applicable
- [ ] replication if applicable
- [ ] S3 paths if applicable

### 3.8 Admin UI Layer Checklist

If the spec touches the admin UI, verify:

- [ ] templates
- [ ] routes
- [ ] static assets if needed
- [ ] navigation wiring

### 3.9 Test Coverage Checklist

- [ ] unit tests
- [ ] integration tests
- [ ] router tests
- [ ] worker tests
- [ ] fixtures
- [ ] test file paths matching source layout

---

## Step 4 — Design & Control Flow Review

### 4.1 Trace the Full Control Flow

Starting from the entry point, trace the complete path through the system and verify the spec documents every hop.

Common gaps:

- app service described but router / caller missing,
- worker described but trigger missing,
- event published but no subscriber named,
- database or export work described but delivery path missing.

### 4.2 Check State Transitions

If the feature involves state changes, verify:

- valid states are enumerated,
- transitions are defined,
- invalid transitions are rejected,
- transition triggers are documented.

### 4.3 Check Data Flow Across Repositories

If the workspace spans multiple repos, verify whether the spec acknowledges all required repo touches.

### 4.4 Check for Missing Error Paths

For each operation, ask what happens if:

- DB write fails,
- external API errors,
- input is malformed,
- referenced entity is missing,
- the operation times out,
- the operation runs concurrently.

---

## Step 4.5 — Redundancy and DRY Review

Architectural completeness asks whether the spec builds enough. This step asks the opposite question: **does the spec build something the system already has?**

A specification frequently proposes functionality that already exists in the code. The existing implementation may be doing the same work wholly, doing part of it, or already owning the responsibility the new design duplicates. The result is redundant artefacts, entities, and domains — two owners for one responsibility, neither authoritative. That is a CRITICAL defect, not a stylistic nit.

For every artefact the spec introduces — domain, model, DAO, service, application service, router, worker, event, agent, tool, client, config key, CLI command, frontend store — verify:

- [ ] the spec names the existing component that owns this responsibility today, or states explicitly that none exists
- [ ] where an owner exists, the spec consolidates rather than adds, by one of:
  - [ ] **delete and replace** — existing functionality removed, replaced by the new construct, with files/symbols to delete and call sites to repoint named
  - [ ] **encapsulate** — new behavior folded into the existing component within the rules of our conventions, leaving a single owner
  - [ ] **re-design** — existing component reshaped to honor the conventions and absorb the new functionality, eliminating the redundant behavior
- [ ] responsibilities remain **single, isolated, and clean** — no artefact in the spec shares an owner with another
- [ ] boundaries between adjacent responsibilities are distinguishable and documented in the comments or docstrings of the spec's code samples
- [ ] adjacent responsibilities are reached through an explicit interface, not through duplicated logic
- [ ] data structures and entities are consolidated — the spec does not introduce a second model, DAO, or payload shape for a concept that already has one
- [ ] naming follows `ubiquitous-language` — a second name for an existing concept is duplication in disguise

Search the codebase independently rather than trusting the spec's claim of novelty. The duplicate is usually named differently, which is exactly why the draft missed it.

Record each finding using the **REDUNDANCY** format in Step 6.5a.

---

## Step 5 — Style and Structure Review

### 5.1 Readability and contract review

Apply the [authoring presentation contract](../feature-specifications/SKILL.md#presentation-rules)
and [packaged sample](../../samples/implementation-details-granularity.md).
Accept combined or renamed sections when all required information remains clear.
Do not request prose merely to satisfy a heading template.

Verify a reader can readily locate purpose/scope, current versus proposed behavior,
changed files and ownership, public interfaces, state transitions, failure behavior,
transaction/resource boundaries, dependencies, tests and acceptance criteria.

Return REVISE for interfaces reconstructed from compressed prose, competing versions
of a contract, historical commentary obscuring current requirements, or material
constraints hidden in unrelated sections. Keep workflow evidence separately linked;
correct authoritative sections in place rather than appending review history.

### 5.2 Overview review

Verify product framing, user/system journey, scope/non-goals, safety and ownership,
child delivery/dependency map, rollout/rollback and acceptance status. An overview
need not reproduce DTOs or implementations. Check stale parent summaries against
current children without mistaking specification review for runtime acceptance.
Independent workstreams retain independent release gates.

### 5.3 Engineering contract review

Treat material implementation ambiguity as a **CRITICAL** gap:

- Every created, modified, moved or deleted file has an exact repository-relative
  path, owner and named symbols/call sites.
- Interfaces use syntax-highlighted target-language declarations, complete fields,
  parameters, enum values and defaults. Requiredness is not confused with nullability.
- Source claims cite real paths/symbols; proposed code is labeled, not asserted to exist.
- Signature-only bodies are acceptable when behavior is fully specified. Non-obvious
  algorithms and ordering-sensitive seams include sufficient implementation detail.
- Shared contracts have one definition; consumers link it and show integration usage.
- Implementation order, configuration, failure paths and unchanged behavior are explicit.
- Test files, cases, fixtures/setup, assertions, levels, commands and relevant manual
  smoke steps are concrete. Code and tests follow the selected repository conventions.

A standalone child explains its owned changes without requiring the parent overview;
it may link canonical shared contracts. Do not require duplicate schemas or full
routine class implementations merely for standalone readability.

### 5.4 Semantic preservation when shortening

Compare the revised specification with source requirements and the prior contract:

- Types, requiredness, nullability, defaults and bounds.
- Validation and cross-field invariants.
- Ordering, atomicity, concurrency, and idempotency.
- Errors, cancellation, recovery and resource ownership.
- Security, authorization and operational constraints.
- Compatibility and migration requirements.
- Test and acceptance coverage, exclusions and unchanged behavior.

Concision is not permission to weaken the contract. Removed historical examples may
be consolidated, but every material requirement must still map to its authoritative
section and evidence plan. Missing material semantics are CRITICAL, not style nits.

---

## Step 6 — Present the Review

### 6.1 Executive Summary

```markdown
## Specification Review: [TICKET-ID] — [Feature Name]

| Metric | Value |
|---|---|
| **Artefact** | overview / technical sub-spec |
| **JIRA Requirements Covered** | X / Y (Z%) |
| **Architectural Layers Complete** | X / Y |
| **Redundancy Gaps Found** | N |
| **Critical Gaps Found** | N |
| **Minor Gaps Found** | N |
| **Style / Structure Compliance** | Pass / Partial / Fail |
```

### 6.2 Critical Gaps

```markdown
### CRITICAL: [Short description]

**What's missing:** ...
**Why it matters:** ...
**JIRA requirement:** ...
**Suggested addition:** ...
```

### 6.3 Minor Gaps

```markdown
### MINOR: [Short description]

**What's missing:** ...
**Suggested addition:** ...
```

### 6.4 Ambiguities

```markdown
### AMBIGUOUS: [Short description]

**The ambiguity:** ...
**Interpretation A:** ...
**Interpretation B:** ...
**Recommendation:** ...
```

### 6.5a Redundancy gaps

```markdown
### REDUNDANCY: [Short description]

**New artefact:** ...
**Existing owner:** `path/to/file.py:LINE` — ...
**Overlap:** wholly / partially / adjacent responsibility
**Why it matters:** ...
**Consolidation:** delete-and-replace / encapsulate / re-design
**Required correction:** <what the spec must say — files to delete, owner to keep, boundary to document, interface to expose>
```

Treat every redundancy gap as CRITICAL.

### 6.5 Structure gaps

```markdown
### STRUCTURE GAP: [Short description]

**Expected artefact:** overview / technical sub-spec
**Observed issue:** ...
**Why it matters:** ...
**Required correction:** ...
```

### 6.6 JIRA Traceability Matrix

Include the full table from Step 2.3.

### 6.7 Cross-Repository Impact

Include a table if the feature requires changes in repos not covered by the spec.

---

## Step 7 — Verify Your Review

Before presenting results:

- [ ] every critical gap is substantiated,
- [ ] every redundancy claim cites the existing owner by `file:line`,
- [ ] no false positives,
- [ ] adjacent features were checked to confirm the gap is real,
- [ ] the review is actionable,
- [ ] JIRA comments were read,
- [ ] the artefact judgment (overview vs technical sub-spec) is explicit,
- [ ] technical sub-specs were checked for standalone readability and required information and readable organization when applicable.
- [ ] implementation details were reviewed as the implementation contract: granular file placement, symbol-level behavior, convention compliance, and concrete test coverage leave no material ambiguity for the coding agent.

---

## Conventions

- Be specific, not vague.
- Cite the relevant code-prompt file when flagging a convention gap.
- Distinguish CRITICAL vs MINOR.
- Respect intentional exclusions.
- Check all relevant repos.
- Read before judging.
- When the draft is an engineering implementation sub-spec, treat missing `Current State`, missing drift correction, or dependence on the parent spec as serious structural defects, not stylistic nits.
- Treat redundancy as a design defect. A spec that adds a second owner for a responsibility the code already has must be revised to consolidate — delete and replace, encapsulate, or re-design — before it is approved.
