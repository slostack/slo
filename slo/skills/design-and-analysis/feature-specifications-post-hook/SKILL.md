---
name: feature-specifications-post-hook
description: Self-review pass that runs after a feature specification is drafted with
  feature-specifications. Catches gaps, convention drift, oversized scope, weak examples,
  spec-mode mismatches, and missing test coverage before the spec is handed to a developer
  or published.
when_to_use: Use as the mandatory post-hook for feature-specifications.
group: design-and-analysis
kind: workflow
source_prompt: analyze/feature-specifications-post-hook.md
---

# Feature Specifications — POST Hook

## Skill summary

- **Name:** `feature-specifications-post-hook`
- **Description:** Self-review pass that runs after a feature specification is drafted with feature-specifications. Catches gaps, convention drift, oversized scope, weak examples, spec-mode mismatches, and missing test coverage before the spec is handed to a developer or published.
- **When to use:** Use as the mandatory post-hook for feature-specifications.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `analyze/feature-specifications-post-hook.md`

## Examples

- The user asks for an end-to-end workflow that fits: Self-review pass that runs after a feature specification is drafted with feature-specifications. Catches gaps, convention drift, oversized scope, weak examples, spec-mode mismatches, and missing test coverage before the spec is handed to a developer or published.
- Use as the mandatory post-hook for feature-specifications.

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

A self-review pass that runs **after** a feature specification has been drafted using [`feature-specifications.md`](../feature-specifications/SKILL.md). The goal is to catch gaps, convention drift, oversized scope, weak examples, missing test coverage, and **spec-mode mismatches** before the spec is handed to a developer or published to the wiki.

Treat this hook as **non-optional**. A feature spec is not done until this hook has produced a clean report.

---

## When to invoke

Invoke automatically immediately after the spec body is written or revised, and before:

- committing the spec,
- publishing to the GitLab wiki,
- handing the spec to a developer,
- breaking the spec into tasks,
- using the spec as an implementation brief.

If the operator pastes a revised spec back, re-run the hook from Step 1.

---

## Step 0 — Confirm the spec mode

Read the PRE-Hook Context Bundle and confirm which mode the document was supposed to use per [`feature-specifications.md`](../feature-specifications/SKILL.md):

- **Mode A — Business / product feature spec**
- **Mode B — Engineering implementation sub-spec**

If the draft clearly uses the wrong mode, record:

```markdown
**MODE GAP:** <expected mode> — <what mode the draft currently reads like>
- Why this matters: <why the structure is misaligned>
- Required correction: <how to restyle / restructure the document>
```

A mode mismatch is an automatic **REVISE**.

---

## Step 1 — Run formal verification

Apply [`feature-specification-verification.md`](../feature-specification-verification/SKILL.md) end-to-end against the drafted spec. Do not skip steps because "we just wrote it".

The output of this step is the **verification report**. Every gap it surfaces becomes an action item for Step 6.

---

## Step 1.5 — Human-readable narrative and structure audit (mandatory)

Per [`feature-specifications.md`](../feature-specifications/SKILL.md), every spec and every broken-down child spec must open with the human-readable narrative sections before low-level implementation detail.

### Shared opening audit (both modes)

Confirm each of these is present and non-trivial:

| Section | Required | What "present" means |
|---|---|---|
| `## Context` → `### Changes` **or** `### Description` | Always | Uses `Changes` when existing behavior is being modified and `Description` when something new is being introduced. Explains in plain English what should be different after the feature lands. |
| `## Context` → `### Big Picture` | Always | 1-2 paragraphs naming upstream and downstream work. Not a 1-line stub. |
| `## Context` → `### Existing structure we are extending` | When applicable | Shows enough current structure to orient the reader. |
| `## Context` → `### What this document changes` | Always | Walks from broad runtime or product change to file-level change to component-level change. Every named artefact in `## Code Reference` later must appear here first in prose. |
| `## Context` → `### <Ambiguity #|Bug #|CRITICAL #> resolution` | When applicable | If the draft is correcting stale design text or POST-hook findings, the resolution is named explicitly. |
| Opening structured call-out | When applicable | Uses one grouped call-out with bold labels for related decisions. No stack of one-line call-outs. |
| Prose intro before every code block in `## Code Reference` | Always | 1-3 sentences in plain English per code block. Silent code dumps are a gap. |
| Full-detail class examples where central | When applicable | Central classes include class docstring, main public method, and core helpers. Helper-method docstrings explain what the method does, who invokes it, and when it runs. |

### Mode A audit — Business / product feature spec

If the draft is **Mode A**, also confirm:

- the opening reads like an O'Reilly textbook chapter led by product or business framing,
- the surrounding journey is explained when the feature is user-facing,
- scope / goals / non-goals are explicit,
- broad feature behavior is explained before technical implementation detail,
- the document does not read like a narrow engineering child slice unless that was intended.

### Mode B audit — Engineering implementation sub-spec

If the draft is **Mode B**, all of the following are mandatory unless the operator explicitly asked for a different structure:

| Section | Required | What "present" means |
|---|---|---|
| Metadata header under the H1 | Always | Includes available fields like `Status`, `Owner`, `Last updated`, `Parent spec`, `Branch`, `Repo`, `Approx. size`. |
| `## 2. Why` | Always | Explains why this slice exists independently and why it is separated from sibling work. |
| `## 3. Current State` | Always | Records live code truths: real symbols, file paths, runtime behaviors, and constraints that are true today. |
| `## 4. Proposed Approach` | Always | Explains the design decision in plain English before code appears. |
| `## 5. Domain Introductions` | When new nouns exist | Introduces each new concept before the flow or code sections use it. |
| `## 6. End-to-End Flow` | Always for non-trivial slices | Walks the runtime slice this sub-spec owns from start to finish. |
| `## 7. Implementation Details` | Always | Contains full corrected examples, implementation order, and verification guidance where applicable. |
| `## 8. Tests` | Always | Maps tests to the actual logic introduced. |
| `## 9. Acceptance Criteria` | Always | Independently verifiable. |
| `## 10. Dependencies` | Always | States blockers and downstream dependents. |
| Standalone readability | Always | The implementer should not need to keep opening the parent spec to decode the slice. |
| Drift correction | When applicable | If older spec text is stale, the new spec says so explicitly and corrects it. |

For every missing, stub-only, or wrong-mode section, record:

```markdown
**NARRATIVE GAP:** <section> — <what is missing>
- Where in the spec: <heading path>
- What to add: <concrete prose or structure change>
```

If **any** mandatory section is missing or stub-only, the verdict is automatically **REVISE**.

---

## Step 2 — Cross-check the spec against the code-convention prompts

For every layer the spec touches, open the matching rule file under `skills/coding/` and audit the spec for compliance.

Audit checklist:

- application services — `invoke()` orchestration, declarative structure, DB-session semantics
- domain features — `model.py`, `dao.py`, `service.py`, relationships, indexes, Pydantic conventions
- routers — request/response schemas, auth, registration
- workers / DBOS — registration, idempotency, retry, payload shape, schedule
- events — type constant, payload schema, publisher + subscriber
- agents / tools — tool-per-file, prompt separation, gateway conventions
- clients / integrations — auth, retry, errors, config
- Alembic — revision script expectations, model registration
- always-on style — named arguments, type hints, Google-style docstrings, declarative methods, one test per decision branch
- logging / observability — helper usage, structured fields, correlation IDs

For each violation, record:

```markdown
**CONVENTION GAP:** <rule file> — <one-line summary>
- Where in the spec: <section / code block>
- What to change: <concrete edit>
```

---

## Step 3 — Granularity check

A spec that tries to do too much produces inconsistent implementations and stale wiki pages. Decide whether the spec should be split before it leaves this hook.

Split the spec if any of these are true:

- it spans more than ~3 architectural layers,
- it introduces more than one new domain,
- it mixes backend feature work with frontend feature work with deployment changes,
- it contains more than ~10 numbered workflow steps end-to-end,
- the traceability matrix has more than ~15 distinct requirements,
- different requirements have different stakeholders and can ship independently.

### Mode-aware split guidance

- A **Business / product feature spec** may stay broad if it is acting as the parent overview that later breaks into child specs.
- An **Engineering implementation sub-spec** should stay narrow. If it starts to read like a parent roadmap instead of one technical slice, split it.
- When splitting a parent spec, the child technical slices should usually become **Mode B engineering implementation sub-specs**, not vague mini-business specs.

If a split is warranted:

1. Run [`breakdown-feature-spec-to-tasks.md`](../breakdown-feature-spec-to-tasks/SKILL.md).
2. Produce a dependency-ordered task list.
3. Replace the monolithic body with one parent overview plus one child spec per task.

If no split is needed, record **Granularity: OK — fits in a single spec**.

---

## Step 4 — Example richness audit

A developer should be able to implement directly from the spec without follow-up questions. Walk the spec and verify that examples are present and convention-compliant.

For every section that introduces code or schema, the spec must show sufficiently full examples for the chosen mode.

### Shared example expectations

- realistic identifiers and values,
- real file paths,
- imports when needed for understanding,
- named arguments,
- type hints,
- docstrings on public and important helper methods,
- prose before every code block.

### Mode A emphasis

For **Business / product feature specs**, examples should be broad enough to make the system change concrete:

- domain models,
- DAOs,
- representative app-service or endpoint examples,
- workflow or API examples,
- test examples where they anchor acceptance criteria.

### Mode B emphasis

For **Engineering implementation sub-specs**, examples should be implementation-brief quality:

- full corrected class listings for central classes,
- explicit current-state corrections when earlier snippets are stale,
- implementation-order notes,
- verification commands,
- manual smoke steps when runtime behavior matters,
- enough local detail that the parent spec does not need to be open side-by-side.

For every missing or weak example, record:

```markdown
**EXAMPLE GAP:** <section> — <what is missing>
- Suggested fill: <code stub, structure block, or prose addition>
```

---

## Step 5 — Test coverage validation

Open the spec's test section and every section that introduces logic. Verify the test plan against `skills/coding/test-verification-policy/SKILL.md` and the relevant test rule files.

For every new or modified method introduced by the spec, the spec must enumerate:

- each decision point,
- one test per branch,
- fixture / mock strategy,
- negative paths where relevant.

Additionally verify:

- controller tests use the expected test stack if routers are introduced,
- application-service tests live in the correct test namespace,
- domain-service tests live in the correct namespace,
- integration / BDD scenarios are described if the feature has a visible flow,
- test names describe the branch, not just the method.

For every coverage gap, record:

```markdown
**TEST GAP:** <method or scenario> — <which branch is uncovered>
- Suggested addition: <test name + fixture/mock note>
```

---

## Step 6 — Revise the spec in place

Aggregate the findings from Steps 0–5 into a single revision plan:

```markdown
### POST-Hook Report — <feature title or ticket id>

| Metric | Value |
|---|---|
| Spec mode | <Mode A | Mode B> |
| JIRA requirements covered | X / Y (Z%) |
| Architectural layers verified | X / Y |
| Narrative gaps | N |
| Convention gaps | N |
| Example gaps | N |
| Test gaps | N |
| Granularity | OK / SPLIT |
| Spec verdict | READY / REVISE |
```

Rules:

- Any non-zero **Narrative gap** count is automatic **REVISE**.
- Any **mode mismatch** is automatic **REVISE**.
- Any missing mandatory Mode B section is automatic **REVISE**.
- Any missing prose before code blocks is automatic **REVISE**.

Then:

- If verdict is **REVISE**: edit the spec directly to close every critical gap, re-run the hook, and repeat until READY.
- If verdict is **READY**: post the report in the conversation and stop.

---

## Hand-off

When the spec is READY, the next step depends on the operator's ask:

- commit and publish,
- break down into tasks,
- implement the feature,
- hand the spec to a developer.

Keep the POST-hook report in the conversation or PR description so the next reviewer can see what was already checked.
