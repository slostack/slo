---
name: feature-specification-verification
description: Reviewing a draft spec for gaps, ambiguities, and redundant
  functionality that duplicates code the system already has, before implementation
  begins.
when_to_use: Use as a post-hook after writing a spec — surfaces missing decisions,
  underspecified edge cases, and inconsistent acceptance criteria.
group: design-and-analysis
kind: workflow
source_prompt: analyze/feature-specification-verification.md
---

# Verify Feature Specification

## Skill summary

- **Name:** `feature-specification-verification`
- **Description:** Reviewing a draft spec for gaps, ambiguities, and redundant functionality that duplicates code the system already has, before implementation begins.
- **When to use:** Use as a post-hook after writing a spec — surfaces missing decisions, underspecified edge cases, and inconsistent acceptance criteria.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `analyze/feature-specification-verification.md`

## Examples

- The user asks for an end-to-end workflow that fits: Reviewing a draft spec for gaps, ambiguities, and redundant functionality that duplicates code the system already has, before implementation begins.
- Use as a post-hook after writing a spec — surfaces missing decisions, underspecified edge cases, and inconsistent acceptance criteria.

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

Use this prompt to review a feature specification document and identify gaps, ambiguities, and missing coverage before a developer begins implementation.

---

## Purpose

Act as a verification layer for specifications generated using [`feature-specifications.md`](../feature-specifications/SKILL.md). Review the spec against the source JIRA story, codebase architecture, coding conventions, and the **chosen spec mode** to surface anything that was missed, under-specified, or structurally misaligned before implementation begins.

---

## Inputs

The operator must provide:

1. **Feature specification document** — path to the spec file
2. **Source JIRA ticket ID or URL** — the original story/task that prompted the specification

Optional:

3. **Confluence page URL(s)** — if the JIRA ticket links to Confluence specs
4. **Scope constraints** — specific areas to focus the review on
5. **Expected spec mode** — if already known from the PRE hook

---

## Step 1 — Load Context

### 1.1 Read the Feature Specification

Read the spec document in full. Build a mental model of what the spec proposes.

Before judging structure, identify which mode the document is using per [`feature-specifications.md`](../feature-specifications/SKILL.md):

- **Mode A — Business / product feature spec**
- **Mode B — Engineering implementation sub-spec**

If the expected mode was supplied and the document clearly uses the wrong one, record a mode mismatch immediately.

### 1.2 Fetch the Source JIRA Story

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

### 1.4 Read skills/orientation/research/SKILL.md

Read `skills/orientation/research/SKILL.md` to understand existing domains, services, workers, integrations, and adjacent infrastructure the spec should reuse or acknowledge.

---

## Step 2 — JIRA Requirement Traceability

Every requirement in the source ask must map to something in the spec.

### 2.1 Extract All Requirements from JIRA

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
### JIRA Requirement Traceability

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

## Step 5 — Style, Structure, and Mode Review

### 5.1 Shared structure compliance

Verify:

- [ ] the opening reads like an O'Reilly technical book chapter
- [ ] `## Context` opens with `### Changes` or `### Description`
- [ ] `### Big Picture` is present and non-trivial
- [ ] `### Existing structure we are extending` appears when structure matters
- [ ] `### What this document changes` walks from broad to narrow
- [ ] prose does not use `§` references
- [ ] code blocks have prose before them
- [ ] central classes are shown in enough detail to be implementable
- [ ] helper-method docstrings explain what, who, and when
- [ ] call-outs are grouped cleanly rather than stacked
- [ ] file trees are full enough to orient the reader

### 5.2 Mode A — Business / product feature spec review

If the draft is Mode A, verify:

- [ ] product or business framing leads the document
- [ ] user/admin journey is covered when applicable
- [ ] scope / goals / non-goals are explicit
- [ ] rollout / risk / stakeholder boundaries are covered where relevant
- [ ] the spec does not collapse into a narrow technical child slice unless that was intended

### 5.3 Mode B — Engineering implementation sub-spec review

If the draft is Mode B, verify:

- [ ] metadata header exists under the H1
- [ ] title format is compatible with repo numbering (e.g. `02.a.1 — ...`)
- [ ] the canonical numbered structure is present:
  - [ ] `## 1. Context`
  - [ ] `## 2. Why`
  - [ ] `## 3. Current State`
  - [ ] `## 4. Proposed Approach`
  - [ ] `## 5. Domain Introductions`
  - [ ] `## 6. End-to-End Flow`
  - [ ] `## 7. Implementation Details`
  - [ ] `## 8. Tests`
  - [ ] `## 9. Acceptance Criteria`
  - [ ] `## 10. Dependencies`
- [ ] the spec is readable in isolation from the parent spec
- [ ] `Current State` records real symbols / file paths / live truths
- [ ] stale parent-spec text or earlier design drift is called out and corrected when relevant
- [ ] `Proposed Approach` exists before code
- [ ] new noun concepts are introduced before code uses them
- [ ] end-to-end flow is explained before low-level implementation detail
- [ ] implementation order / verification commands / manual smoke are included when applicable
- [ ] dependencies are explicit

### 5.4 Actionability

For both modes, verify:

- [ ] a developer can implement directly from this spec without clarification
- [ ] every file to create or modify has a full path
- [ ] code samples are complete enough to convey intent
- [ ] configuration values and environment variables are listed where relevant
- [ ] dependencies between components are clear

---

## Step 6 — Present the Review

### 6.1 Executive Summary

```markdown
## Specification Review: [TICKET-ID] — [Feature Name]

| Metric | Value |
|---|---|
| **Spec Mode** | Mode A / Mode B |
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

### 6.5 Mode / structure gaps

```markdown
### MODE OR STRUCTURE GAP: [Short description]

**Expected mode:** Mode A / Mode B
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
- [ ] the spec-mode judgment is explicit,
- [ ] Mode B docs were checked for standalone readability and canonical structure when applicable.

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
