---
name: feature-specifications
description: Style guide for writing technical feature specifications.
when_to_use: 'Use when authoring a spec from scratch — covers structure, scope, acceptance
  criteria, sequencing. Default workflow: load feature-specifications-pre-hook first
  (pre-hook), then this, then feature-specifications-post-hook (post-hook). The older
  gather-feature-context and feature-specification-verification skills remain available
  as legacy companions when explicitly requested.'
group: design-and-analysis
kind: workflow
source_prompt: analyze/feature-specifications.md
---

# Style Guide for Technical Feature Documentation

## Skill summary

- **Name:** `feature-specifications`
- **Description:** Style guide for writing technical feature specifications.
- **When to use:** Use when authoring a spec from scratch — covers structure, scope, acceptance criteria, sequencing. Default workflow: load feature-specifications-pre-hook first (pre-hook), then this, then feature-specifications-post-hook (post-hook). The older gather-feature-context and feature-specification-verification skills remain available as legacy companions when explicitly requested.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `analyze/feature-specifications.md`

## Examples

- The user asks for an end-to-end workflow that fits: Style guide for writing technical feature specifications.
- Use when authoring a spec from scratch — covers structure, scope, acceptance criteria, sequencing. Default workflow: load feature-specifications-pre-hook first (pre-hook), then this, then feature-specifications-post-hook (post-hook). The older gather-feature-context and feature-specification-verification skills remain available as legacy companions when explicitly requested.

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

## Required Hooks

This prompt is wrapped by two non-optional hooks. The agent must run them in order, without being asked:

1. **PRE hook — [`feature-specifications-pre-hook.md`](../feature-specifications-pre-hook/SKILL.md).** Run this *before* writing a single line of the spec. It loads skills/orientation/claude/SKILL.md, AGENTS.md, skills/orientation/research/SKILL.md, MEMORY.md, the Knowledge Base, the affected code surface, the relevant `build-*.md` conventions, and the second-order requirements (scale, latency, logging, idempotency, deployment posture). Its output — the **PRE-Hook Context Bundle** — is the brief this style guide is applied against. Do not draft the spec until the bundle exists in the conversation.

2. **POST hook — [`feature-specifications-post-hook.md`](../feature-specifications-post-hook/SKILL.md).** Run this *immediately after* the spec body is drafted (or revised). It invokes [`feature-specification-verification.md`](../feature-specification-verification/SKILL.md), cross-checks the spec against every applicable code-convention prompt, decides whether the scope should be split via [`breakdown-feature-spec-to-tasks.md`](../breakdown-feature-spec-to-tasks/SKILL.md), audits example richness, validates the human-readable narrative sections enumerated below, validates test coverage per `skills/coding/test-verification-policy/SKILL.md`, and validates the chosen spec mode. If the verdict is REVISE, the agent edits the spec in place and re-runs the hook until it returns READY. Only a READY verdict makes the spec eligible for commit / wiki publication / hand-off.

A feature specification produced without both hooks is considered incomplete.

---

## Mandatory Spec Mode Selection

Every feature specification must explicitly choose one of these two modes **before drafting begins**. The chosen mode must be written into the PRE-Hook Context Bundle.

### Mode A — Business / product feature spec

Use this mode when the document is primarily explaining:

- the product or business ask,
- a multi-layer feature spanning backend, frontend, workflows, and rollout,
- user/admin journeys,
- requirements traceability back to JIRA / Confluence / stakeholders,
- what the organization is building and why.

This mode still needs technical detail, but the document is led by product intent and lifecycle.

### Mode B — Engineering implementation sub-spec

Use this mode when the document is primarily explaining:

- one technical slice of a larger feature,
- one architectural boundary or runtime seam,
- a refactor, deletion, wiring change, runtime behavior shift, or implementation phase,
- a child spec that engineers should be able to implement directly,
- a document like `02.a.1` through `02.a.6` under `specifications/02-slo-tui-cli/`.

This mode is a **standalone engineering chapter**. It must read like an O'Reilly implementation guide: why this slice exists, what is true in the code today, what earlier design text is stale, what this sub-spec changes, the end-to-end flow it owns, and the concrete code/tests needed to land it.

### Mode-selection heuristics

Default to **Business / product feature spec** when:

- the ask starts from product intent or business behavior,
- the spec spans multiple layers or repos as one feature,
- the feature is still being shaped at the requirements level,
- the document is the parent overview that later breaks down into technical slices.

Default to **Engineering implementation sub-spec** when:

- the ask references a parent spec,
- the document is one dependency-ordered child task or technical slice,
- the main goal is to make one implementation seam low-ambiguity,
- the feature is mostly about control flow, runtime architecture, session/wiring behavior, deletion, migration, or internal component structure.

If the mode is unclear, ask the operator or state the inference explicitly before drafting.

---

## Shared Opening Requirements (Both Modes)

Every feature specification and every broken-down child spec must open like an **O'Reilly technical book chapter**: begin with the problem and the runtime or business story, orient the reader inside the existing system, then progressively narrow into components and code. Do **not** jump straight into method names or low-level implementation details before the reader understands the change in plain English.

### Mandatory opening section: `## Context`

The `## Context` block is always required. It must contain, in order:

1. **`### Changes`** or **`### Description`** — use `Changes` when the plan modifies existing behavior; use `Description` when the plan introduces something new.
2. **`### Big Picture`** — 1-2 paragraphs explaining where this work sits in the larger rollout, what just happened upstream, what this plan owns, and what downstream work depends on it.
3. **`### Existing structure we are extending`** — show the surrounding file/folder layout that already exists today when structure matters. Prefer fuller trees over overly-truncated diagrams.
4. **`### What this document changes`** — walk from broad change to narrow change: runtime or product behavior first, then file-level changes, then component-level changes.

When the plan resolves an ambiguity, stale design, or POST-hook finding, add a sub-section under `## Context` named:

- `### Ambiguity #<n> resolution`
- `### Bug #<n> resolution`
- `### CRITICAL #<n> resolution`

That section must explicitly state the issue and the chosen resolution.

### Additional mandatory opening rules

- Use **one structured call-out** with bold labels instead of stacking several one-line call-outs back-to-back.
- Do **not** use `§` references in prose. Prefer explicit headings, file paths, or short phrases like "in the builder example below".
- Every named domain, service, router, worker, component, view, or utility that later appears in code must appear in prose first.

---

## Mode-Specific Canonical Structures

## Mode A — Business / product feature spec

Use this mode for parent specs and broad feature documents. The exact headings may vary slightly by feature, but the following structure is the default target:

1. `## Context`
2. `## The journey this plan owns a slice of` *(when applicable)*
3. `## Scope` / `## Goals` / `## Non-goals`
4. `## Current product or system behavior`
5. `## Proposed behavior`
6. `## Domain / API / workflow / UI changes`
7. `## Code Reference`
8. `## Tests`
9. `## Acceptance Criteria`
10. `## Risks / rollout / dependencies`

Use this mode when the reader needs strong product and business framing before technical depth.

## Mode B — Engineering implementation sub-spec

Use this mode for child technical slices and implementation-ready engineering chapters. This mode should look like `02.a.1` onward under `specifications/02-slo-tui-cli/`.

### Required metadata header

Engineering implementation sub-specs must begin with a compact metadata line under the H1. Include, when known:

- `Status`
- `Owner`
- `Last updated`
- `Parent spec`
- `Branch`
- `Repo`
- `Approx. size`

### Required title format

Engineering implementation sub-spec titles may use either of these formats:

- `Step 02.a.1 — Owning One Agent Session Per Process`
- `02.a.1 — Owning One Agent Session Per Process`

Do **not** force everything into `Step N - ...` if the repo's spec numbering scheme already uses forms like `02.a.1`.

### Required numbered structure

Engineering implementation sub-specs must use this canonical structure unless the operator explicitly asks for a different one:

1. `## 1. Context`
2. `## 2. Why`
3. `## 3. Current State`
4. `## 4. Proposed Approach`
5. `## 5. Domain Introductions`
6. `## 6. End-to-End Flow`
7. `## 7. Implementation Details`
8. `## 8. Tests`
9. `## 9. Acceptance Criteria`
10. `## 10. Dependencies`

### Additional engineering-sub-spec requirements

- The document must be **standalone**. A developer should not need to keep flipping back to the parent spec to understand the slice.
- `## 3. Current State` must record what is true in code **today**: real symbols, real file paths, current constraints, and any live deltas from older design text.
- If earlier specs or snippets are stale, say so explicitly and correct them in the new spec.
- `## 4. Proposed Approach` must explain the design decision in plain English before code appears.
- `## 5. Domain Introductions` must define each new noun conceptually before it is used in flow or code sections.
- `## 6. End-to-End Flow` must walk the reader through the runtime slice this sub-spec owns, even if a later control-flow section dives deeper.
- `## 7. Implementation Details` should include implementation order, verification commands, and manual smoke guidance when applicable.
- `## 10. Dependencies` must clearly state what blocks this slice and what it blocks downstream.

---

## Journey and Flow Sections

### `## The journey this plan owns a slice of`

Use this section whenever the plan is part of a larger user-facing or system-facing journey. Walk the reader through the full surrounding journey and call out which slice this plan owns. Numbered steps or an ASCII diagram are both acceptable.

Skip it only when the plan is purely cross-cutting (e.g. logging utility, base controller, tiny internal helper).

### `## Control Flow: <hot-path-name> (Step-by-Step)`

For each non-trivial request path or workflow the plan ships, give a step-by-step ASCII or numbered walkthrough. Name every middleware, every private helper, every commit boundary, and every external call. End with a one-sentence atomicity or consistency guarantee.

This section is mandatory for any non-trivial orchestration. Domain-only specs may omit it.

---

## `## Code Reference` Rules

Every code block in `## Code Reference` must be preceded by 1-3 sentences of plain English explaining what the snippet does and why it is shaped that way. Silent code dumps are banned.

If a class is central to the feature, do **not** show only a stub signature. Show:

- the class docstring,
- the main public entry point,
- the core helper methods that define its behavior.

Helper-method docstrings must explain:

- **what** the method does,
- **who** usually invokes it,
- **when** it is used in the flow.

Code examples must be low-ambiguity and implementation-ready. Use:

- named arguments at call sites,
- explicit type hints on every signature,
- declarative method structure,
- Google-style docstrings,
- real identifiers and realistic values.

When a spec is Mode B, embed the **full corrected example locally** rather than assuming the reader will consult the parent spec.

---

## Writing Style

### Tone & voice

- Professional but conversational
- Direct and declarative
- Use first-person plural (`we`) when it improves readability
- Explain technical terms when introduced
- Make the opening read like an O'Reilly technical book chapter
- Prefer explicit headings and file paths over shorthand references

### Sentence structure

- Use active voice predominantly
- Keep sentences scannable
- Mix explanatory sentences with short, punchy ones
- Use transition phrases to connect concepts

### Clarity techniques

- Use concrete examples with real paths, values, and identifiers
- Show before/after states when relevant
- Use parenthetical clarifications only when they genuinely reduce ambiguity
- Break sequence-heavy paragraphs into bullets

### Call-outs

- Use call-outs for important notes, decisions, warnings, or background
- Prefer **one grouped call-out** with bold labels over many stacked micro call-outs
- Example labels: `**Runtime strategy:**`, `**Documentation strategy:**`, `**Testing posture:**`

---

## Visual Aids & Formatting

Use:

- inline code for file paths, identifiers, and literal values,
- sufficiently full file trees when structure matters,
- numbered workflows with nested sub-steps where needed,
- tables for inventories, decision logs, or field specifications,
- fenced code blocks with language identifiers,
- file paths before or inside code blocks.

When the surrounding structure matters, show both:

- the existing structure before the change,
- the target structure after the change.

Do not over-truncate trees if that makes the reader lose orientation.

---

## Implementation Guidance

Always include, when applicable:

- full paths for files to create,
- full paths for files to modify,
- exact components being introduced or changed,
- dependencies and prerequisites,
- event triggers and workflow sequences,
- error handling approach,
- configuration values and environment expectations,
- tests to add,
- scoped formatting / lint / test commands,
- manual smoke steps for interactive or runtime-heavy features.

Engineering implementation sub-specs should also state:

- what remains intentionally unchanged,
- what prior design text is now stale,
- what exact corrections the new spec is locking in.

---

## Consistency Rules

**Naming:**

- snake_case for fields, files, and variables
- PascalCase for class names and model names
- kebab-case for URL path segments and wiki/page slugs where appropriate
- keep terminology stable throughout

**Formatting:**

- field specifications: `field_name (Type): constraints`
- file paths: `src/path/to/file.py`
- dates: `YYYY-MM-DD` unless the surrounding context requires another format
- IDs: always specify concrete type

**Cross-references:**

- point to explicit headings, file paths, and sibling spec paths
- avoid vague references like "as above" when a precise heading is available

---

## Key Principles

1. **Completeness** — every implementation detail a developer needs.
2. **Clarity** — technical precision without ambiguity.
3. **Context** — explain why decisions were made, not just what to build.
4. **Practicality** — real code, real file paths, real examples.
5. **Traceability** — clear connections between related components and upstream asks.
6. **Scannability** — structure that supports quick navigation.
7. **Progressiveness** — move from simple to complex, broad to narrow.
8. **Progressive disclosure** — runtime or business story first, then structure, then components, then code.
9. **Low-ambiguity code samples** — code examples are part of the implementation brief, not decoration.
10. **Mode fidelity** — choose the correct spec mode and follow its structure rigorously.
11. **Standalone engineering slices** — Mode B specs must stand on their own.
12. **Drift correction** — when older spec text is stale, say so explicitly and correct it.

---

**For AI:** When generating documentation in this style:

- Choose and declare the correct spec mode before writing.
- Prioritize developer efficiency — the spec should be directly implementable.
- Keep the opening human-readable and gradual, like an O'Reilly chapter.
- Preserve implementation rigor while improving readability.
- Use the exact structure required by the chosen mode.
- Include concrete examples with realistic data and file paths.
- Show the complete picture: why, current truth, proposed shape, flow, code, tests, and dependencies.
- Think like a developer reading this at 2am trying to implement the feature without follow-up questions.
