---
name: feature-specification-verification
description: Reviewing a draft specification family for gaps, ambiguities, and redundant
  functionality that duplicates code the system already has, before implementation
  begins.
when_to_use: Use for independent adversarial review of a specification family (overview plus standalone engineering sub-specs), or standalone review of an existing spec — surfaces missing decisions,
  underspecified edge cases, and inconsistent acceptance criteria.
group: design-and-analysis
kind: workflow
source_prompt: analyze/feature-specification-verification.md
---

# Verify Feature Specification

## Skill summary

- **Name:** `feature-specification-verification`
- **Description:** Reviewing a draft specification family for gaps, ambiguities, and redundant functionality that duplicates code the system already has, before implementation begins.
- **When to use:** Use for independent adversarial review of a specification family, or standalone review of an existing spec — surfaces missing decisions, underspecified edge cases, and inconsistent acceptance criteria.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `analyze/feature-specification-verification.md`

## Examples

- "Review the spec family in `specifications/42-supplier-invoices/` before we build it."
- "Check this sub-spec for gaps and for anything the code already does."
- "Verify the overview and sub-specs against the original issue."

## Skill discovery

Use `skills/INDEX.md` to find the convention skills that apply to the layers and languages the spec touches.

## Guidance

Review a specification family and identify:

- gaps,
- ambiguities,
- missing specifications,
- redundant or duplicate functionality,
- overlapping functionality that should be consolidated to keep systems DRY.

Be careful not to break cohesion. A flush or commit must never be extracted out of the method it completes just to make code DRY. Cohesion matters as much as DRY, because it keeps code easy to read. Illustrative only:

```python
# Correct: the guarded update, its flush and the outcome read as one unit.
# The application service that called this owns the commit.
@staticmethod
async def apply_access_projection(
    *,
    document_id: UUID,
    is_visible: bool,
    access_version: int,
    db_session: AsyncSession,
) -> bool:
    stmt = (
        sa.update(Document)
        .where(Document.id == document_id)
        .where(Document.access_version < access_version)
        .values(is_visible=is_visible, access_version=access_version)
        .returning(Document.id)
    )
    result = await db_session.execute(stmt)
    await db_session.flush()
    return result.scalar_one_or_none() is not None
```

Flag a spec that moves `db_session.flush()` into a `_flush()` helper, or splits the statement from its execution, only to avoid repeated lines.

---

## Purpose

Act as the verification layer for specifications. Review the family against:

- the source request,
- the source issue or task, in whichever source-control or project-management tool holds it,
- the codebase architecture,
- the coding conventions,
- and the **expected structure** of each document (overview or standalone engineering sub-spec)

to surface anything missed, under-specified or structurally misaligned before implementation begins.

---

This is independent verification, not the author's own checklist. Run the full procedure even when the author reports READY.

- READY requires a complete report and no outstanding CRITICAL gaps.
- Return each finding to the skill that owns the failing document:
  - `overview.md` → [`feature-specifications`](../feature-specifications/SKILL.md)
  - sub-specs and `task-list.md` → [`breakdown-feature-spec-to-tasks`](../breakdown-feature-spec-to-tasks/SKILL.md)
- Standalone reviews do not need a previous author report. Gather the missing context from the source request, issue, knowledge base and code.
- Do not rewrite the spec during review; report findings for the owner to fix.

## Inputs

The operator provides at least one of these:

1. **Specification family** — the feature folder, or a single `overview.md` or sub-spec path
2. **Source issue or task** — ID or URL in any source-control or project-management tool
3. **Linked documents** — design pages or briefs the issue references
4. **Scope constraints** — specific areas to focus on
5. **Expected artefact** — overview or standalone engineering sub-spec, if already known

---

## Step 1 — Load Context

### 1.1 Read the specification family

Read every document in full and build a mental model of what is proposed. A family has:

- **`overview.md`** — written by `feature-specifications`: purpose, domains, journeys, interfaces, open decisions and delivery order.
- **Standalone engineering sub-specs** — written by `breakdown-feature-spec-to-tasks`, named `<NN>.a.n-<slice>.md` by convention, one vertical slice each.
- **`task-list.md`** — the sub-specs in dependency order.

When asked to review a single document, still read its siblings so you can judge consistency.

### 1.2 Fetch the source and related context

This may not always exist. When it does, fetch from whichever tool holds it (issue tracker, merge-request system, wiki, knowledge base):

- summary and description,
- acceptance criteria,
- comments,
- linked issues and sub-tasks,
- attachments and linked pages.

### 1.3 Read the conventions

- Load the convention skills that apply (see `skills/INDEX.md`) and the rules in `AGENTS.md`, `SLO.md` or `CLAUDE.md`.
- Load `RESEARCH.md` when it exists.
- Consult the knowledge base for documented project decisions, following [`locate-knowledge-base`](../locate-knowledge-base/SKILL.md).

---

## Step 2 — Requirement Traceability

### 2.1 Extract the requirements

List every requirement from the source request, issue, acceptance criteria and comments, including implicit ones and explicit descopes.

### 2.2 Map each requirement

| Status | Meaning |
|---|---|
| **Covered** | The family addresses it with enough detail to build and test |
| **Partially Covered** | Mentioned, but without enough detail |
| **Not Covered** | Not addressed |
| **Intentionally Excluded** | The spec or source explicitly defers it |

### 2.3 Present the traceability matrix

```markdown
### Requirement Traceability

| # | Source requirement | Coverage | Document and section | Notes |
|---|---|---|---|---|
| 1 | ... | Covered | 42.a.1 §5.2 | ... |
```

---

## Step 3 — Architectural Completeness Review

For each layer the family touches, verify the design is complete end to end. Use `solution-design` and `coding-rules` as overarching guides and defer to the language convention skills.

The checklists vary by project. For a Python project following the Slo skills:

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

  Follow `coding/test-verification-policy/SKILL.md`:

  - [ ] behaviour tests drive each slice end to end from its real entry point through real persistence, and assert stored outcomes and forbidden effects
  - [ ] focused unit tests cover critical methods with complex computation (parsing, matching, scoring, state rules)
  - [ ] no elaborate Playwright or multi-service harness is required to prove the slice
  - [ ] every acceptance row names its test file, test name, level and run command
  - [ ] fixtures are reused or named, and test paths match the source layout

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

- [ ] the spec's duplicate-code table names the existing component that owns this responsibility today, or states explicitly that none exists
- [ ] where an owner exists, the spec consolidates rather than adds, by one of:
  - [ ] **delete and replace** — existing functionality removed, replaced by the new construct, with files/symbols to delete and call sites to repoint named
  - [ ] **encapsulate** — new behavior folded into the existing component within the rules of our conventions, leaving a single owner
  - [ ] **re-design** — existing component reshaped to honor the conventions and absorb the new functionality, eliminating the redundant behavior
- [ ] responsibilities remain **single, isolated, and clean** — no artefact in the spec shares an owner with another
- [ ] boundaries between adjacent responsibilities are distinguishable and documented in the comments or docstrings of the spec's code samples
- [ ] adjacent responsibilities are reached through an explicit interface, not through duplicated logic
- [ ] data structures and entities are consolidated — the spec does not introduce a second model, DAO, or payload shape for a concept that already has one
- [ ] naming follows `ubiquitous-language` — a second name for an existing concept is duplication in disguise
- [ ] consolidation has not broken cohesion — tightly coupled steps such as a write and its flush stay in one method

Search the codebase independently rather than trusting the spec's claim of novelty. The duplicate is usually named differently, which is exactly why the draft missed it.

Record each finding using the **REDUNDANCY** format in Step 6.5.

---

## Step 5 — Style and Structure Review

### 5.1 Readability and contract review

1. The family uses simple language, written for technical readers who are not familiar with the feature.
2. It is concise and well organized: bullet points, tables, diagrams and short sentences instead of large blocks of prose.
3. Code snippets illustrate what is best understood in code.
4. Snippets are complete where understanding depends on them; important sections are not truncated.

Accept combined or renamed sections when the required information is easy to find. Do not demand prose to fill a template.

### 5.2 Overview review

Check `overview.md` against [`feature-specifications`](../feature-specifications/SKILL.md#the-document):

- product framing and context, with the current state verified against code,
- scope and non-goals,
- domains identified and their roles explained concisely, with examples where needed,
- the interfaces each module exposes,
- the journeys mapped onto those domains and interfaces,
- diagrams (entity-relationship, class, sequence, state, flow) where they aid understanding,
- the duplicate-code table,
- open decisions, blocking ones first,
- the delivery order, one vertical slice per step,
- the behaviour to prove.

An overview need not reproduce DTOs or implementations. Open decisions are allowed in the overview; treat one as a gap only when a sub-spec marked READY depends on it. Check that the overview's summaries are not stale against the current sub-specs, and do not mistake specification review for runtime acceptance.

### 5.3 Engineering contract review

Check each sub-spec against [`breakdown-feature-spec-to-tasks`](../breakdown-feature-spec-to-tasks/SKILL.md). Treat material implementation ambiguity as a **CRITICAL** gap:

- Every created, modified, moved or deleted file has an exact repository-relative
  path, owner and named symbols/call sites.
- Interfaces use syntax-highlighted target-language declarations, complete fields,
  parameters, enum values and defaults. Requiredness, nullability, defaults and bounds are explicit, and requiredness is not confused with nullability.
- Source claims cite real paths/symbols; proposed code is labeled, not asserted to exist.
- Signature-only bodies are acceptable when behavior is fully specified. Non-obvious
  algorithms and ordering-sensitive seams include sufficient implementation detail.
- Shared contracts have one definition; consumers link it and show integration usage.
- Implementation order, configuration, failure paths and unchanged behavior are explicit.
- The status (READY, DRAFT or BLOCKED) matches reality: no READY sub-spec depends on an open decision.
- Acceptance rows name behaviour tests first, unit tests only for complex computation, with test files, cases, fixtures, levels and commands.

**Current state.** A sub-spec records what exists today in `Read first` and `Ownership and interfaces` (current → proposed), not under a separate "Current State" heading. Check that it states today's behaviour with verified paths and corrects any earlier document that is now stale. Missing current-state facts or drift correction is a serious gap, wherever the heading.

A standalone sub-spec explains its owned changes without requiring the overview; it may link canonical shared contracts. Do not require duplicate schemas or full routine class implementations merely for standalone readability.

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

### 5.5 Family consistency

- Every overview behaviour and delivery step maps to an owning sub-spec and an acceptance row.
- Names, types, errors and state values agree between the overview, producers and consumers. Flag competing versions of the same contract in different documents.
- Sub-specs follow the `<NN>.a.n-<slice>.md` convention, or the repository's existing numbering.
- `task-list.md` is acyclic, schema work comes first, and proposed parallel work has no shared-file conflicts.

---

## Step 6 — Present the Review

### 6.1 Executive Summary

```markdown
## Specification Review: [Issue ID] — [Feature Name]

| Metric | Value |
|---|---|
| **Documents reviewed** | overview.md, 42.a.1, 42.a.2, task-list.md |
| **Source Requirements Covered** | X / Y (Z%) |
| **Architectural Layers Complete** | X / Y |
| **Redundancy Gaps Found** | N |
| **Critical Gaps Found** | N |
| **Minor Gaps Found** | N |
| **Style / Structure Compliance** | Pass / Partial / Fail |
| **Verdict** | READY / REVISE |
```

### 6.2 Critical Gaps

```markdown
### CRITICAL: [Short description]

**Document:** overview.md / 42.a.n
**What's missing:** ...
**Why it matters:** ...
**Source requirement:** ...
**Suggested addition:** ...
```

### 6.3 Minor Gaps

```markdown
### MINOR: [Short description]

**Document:** ...
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

### 6.5 Redundancy gaps

```markdown
### REDUNDANCY: [Short description]

**Document:** ...
**New artefact:** ...
**Existing owner:** `path/to/file.py:LINE` — ...
**Overlap:** wholly / partially / adjacent responsibility
**Why it matters:** ...
**Consolidation:** delete-and-replace / encapsulate / re-design
**Required correction:** <what the spec must say — files to delete, owner to keep, boundary to document, interface to expose>
```

Treat every redundancy gap as CRITICAL.

### 6.6 Structure gaps

```markdown
### STRUCTURE GAP: [Short description]

**Document:** overview.md / 42.a.n
**Observed issue:** ...
**Why it matters:** ...
**Required correction:** ...
```

### 6.7 Cross-Repository Impact

Include a table if the feature requires changes in repos not covered by the spec.

### 6.8 Verdict and routing

- **READY** — no CRITICAL, REDUNDANCY or STRUCTURE gaps remain.
- **REVISE** — list the findings per document and route them to the owning skill (Purpose, above). After the owner revises, review the changed documents and everything that depends on them again.

---

## Step 7 — Verify Your Review

Before presenting results:

- [ ] every critical gap is substantiated,
- [ ] every redundancy claim cites the existing owner by `file:line`,
- [ ] no false positives,
- [ ] adjacent features were checked to confirm the gap is real,
- [ ] the review is actionable, and every finding names its document,
- [ ] the source issue's comments and linked items were read, when a source exists,
- [ ] the artefact judgment (overview or standalone engineering sub-spec) is explicit for each document,
- [ ] sub-specs were checked for standalone readability, required information and readable organization,
- [ ] implementation details were reviewed as the implementation contract: granular file placement, symbol-level behaviour, convention compliance and concrete test coverage leave no material ambiguity for the coding agent.

---

## Conventions

- Be specific, not vague.
- Use simple language and avoid long paragraphs.
- Present the review clearly for a human reader: short sections, tables and lists rather than large blocks of text.
- Cite the relevant convention skill when flagging a convention gap.
- Distinguish CRITICAL from MINOR.
- Respect intentional exclusions.
- Check all relevant repos.
- Read before judging.
- In a standalone engineering sub-spec, treat missing current-state facts, missing drift correction or dependence on the overview to make sense as serious structural defects, not stylistic nits.
- Treat redundancy as a design defect. A spec that adds a second owner for a responsibility the code already has must be revised to consolidate — delete and replace, encapsulate, or re-design — before it is approved.
