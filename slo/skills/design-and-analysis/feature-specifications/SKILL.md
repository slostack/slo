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
- Use when authoring a spec from scratch — covers structure, scope, acceptance criteria, sequencing.

**Default workflow:**
- load feature-specifications-pre-hook first (pre-hook),
- then this,
- then feature-specifications-post-hook (post-hook).

The older gather-feature-context and feature-specification-verification skills remain available as legacy companions when explicitly requested.

## Slo defaults for request and specification artifacts

**Read the prerequisite design references before drafting.** Read [coding rules](../../coding/coding-rules/SKILL.md) and [code design principles](../../coding/code-design-principles/SKILL.md) before authoring a feature specification so its design follows the project's baseline rules. When a feature needs focused preimplementation design, consult [solution design](../../coding/solution-design/SKILL.md) as an optional companion; it is appropriate before implementation, but it is not mandatory for every feature specification.

**Read the companion feature-development skills first.** Unless the user asks you not to, skim the sibling skills in this group before drafting — they carry the hooks, verification, and task-breakdown steps this guide leans on, and they keep the spec consistent with the rest of the Slo workflow:

- `feature-specifications-pre-hook` — the PRE hook that builds the context bundle
- `feature-specifications-post-hook` — the POST hook that verifies and decides on splitting
- `feature-specification-verification` — the verification pass
- `breakdown-feature-spec-to-tasks` — splitting an approved spec into tasks
- `gather-feature-context` — legacy context companion (on request)

**Skill location.** These live under the Slo skill library at
`~/.local/pipx/venvs/slo/lib/python3.11/site-packages/skills/design-and-analysis/`,
with personal overrides under `~/.slo/user_skills/`. Inside a repo checkout they mirror to
`skills/design-and-analysis/`.

**Write for humans first.** Use simple, direct language throughout, and lean on visual representation — ASCII diagrams, numbered user journeys, before/after trees, and tables — wherever a picture makes the change quicker to understand than prose.

**Load the project's rules before drafting.** A spec is only as grounded as the conventions it honors. Read whichever of these exist, home-directory copy and repo-root copy both:

- `~/.slo/SLO.md` and a root `SLO.md`
- `~/.claude/CLAUDE.md` and a root `CLAUDE.md`
- `~/.codex/AGENTS.md` and a root `AGENTS.md`
- a project `RESEARCH.md` and a project `MEMORY.md`, when the project maintains them

**Artifact paths.** Unless the user explicitly overrides these paths, use:

```text
<feature-requests-root> = ${SLO_FEATURE_REQUESTS_DIR:-~/.slo/projects/<project_name>/feature-requests}
<feature-specifications-root> = ${SLO_FEATURE_SPECIFICATIONS_DIR:-~/.slo/projects/<project_name>/feature-specifications}
```

**Expected structure.** One folder per feature. The `overview.md` carries the product framing and ends with the brief technical overview; each numbered sibling is one standalone technical sub-spec:

```text
<feature-requests-root>/
└── 01-example-feature/
    └── request.md

<feature-specifications-root>/
└── 01-example-feature/
    ├── overview.md            # Overview → Brief Technical Overview (business + product framing)
    ├── 01.a.1-first-slice.md  # Technical Sub-Spec (one of n)
    ├── 01.a.2-second-slice.md
    └── plan.md
```

## Guidance

## Required Hooks

This prompt is wrapped by two non-optional hooks. The agent must run them in order, without being asked:

1. **PRE hook — [`feature-specifications-pre-hook.md`](../feature-specifications-pre-hook/SKILL.md).** Run this *before* writing a single line of the spec. It loads CLAUDE.md, AGENTS.md, RESEARCH.md, MEMORY.md, the Knowledge Base, the affected code surface, the relevant `build-*.md` conventions, and the second-order requirements (scale, latency, logging, idempotency, deployment posture). Its output — the **PRE-Hook Context Bundle** — is the brief this style guide is applied against. Do not draft the spec until the bundle exists in the conversation.

2. **POST hook — [`feature-specifications-post-hook.md`](../feature-specifications-post-hook/SKILL.md).** Run this *immediately after* the spec body is drafted (or revised). It invokes [`feature-specification-verification.md`](../feature-specification-verification/SKILL.md), cross-checks the spec against every applicable code-convention prompt, always runs the DRY consolidation pass over the entities and data structures the spec introduces, decides whether the scope should be split via [`breakdown-feature-spec-to-tasks.md`](../breakdown-feature-spec-to-tasks/SKILL.md), audits example richness, validates the human-readable narrative sections enumerated below, and validates test coverage per `skills/coding/test-verification-policy/SKILL.md`. If the verdict is REVISE, the agent edits the spec in place and re-runs the hook until it returns READY. Only a READY verdict makes the spec eligible for commit / wiki publication / hand-off.

A feature specification produced without both hooks is considered incomplete.

---

## One Specification, Product Framing *and* Engineering Detail Together

> **There is a single specification shape.** It is **not** a choice between a "business" document and an "engineering" document — every non-trivial feature needs both, and they live together as one family:
>
> - an **`overview.md`** that carries the product/business framing and ends with a brief technical overview, and
> - one or more **technical sub-specs** (`01.a.1`, `01.a.2`, …) that each own one implementation slice in full engineering detail.
>
> A tiny, single-slice feature may fold both halves into one document. A larger feature keeps the overview thin and pushes the depth into numbered sub-specs. Either way, the reader always gets the product story first and the implementation-ready detail second — **never one without the other**.
>
> **Write for two audiences at once.** The overview and the narrative must be plain enough for a human to follow with no prior context; the sub-specs must be precise enough for an implementation agent to build from with no follow-up questions. Simple language throughout. Gradual context. Introduce existing concepts before you change them.
>
> **Only depart from carrying both halves** when the user explicitly asks for just the overview or just a single sub-spec. When they do, state that inference before drafting.
>
> **Open like an O'Reilly chapter.** Every specification — the overview and every child sub-spec — must begin with the problem and the runtime or business story, orient the reader inside the existing system, then progressively narrow into components and code. Do **not** jump straight into method names or low-level implementation details before the reader understands the change in plain English.
>
> Use a mix of narrative, numbered steps, ASCII diagrams, and tables to orient the reader. Avoid silent code dumps or silent prose. Every behavioral claim must be grounded in a real code sample with a `file:line` citation. This document is for the user *and* the AI, so lay emphasis on readability and clarity.

---

## Shared Opening Requirements

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

## Canonical Structure

Every feature specification progresses through the same arc: product intent → the existing landscape and its gaps → a walk-through of the change a human can follow → a brief technical map → the deep technical sub-specs. The overview owns the first four; the sub-specs own the fifth, one slice at a time.

### The `overview.md` — product framing and technical map

1. **`## Overview`**
   - Describe the business / product ask.
   - Describe the entire feature being implemented and what it addresses.
   - Say what the organization or team is building, and **why**.

2. **`## Overview — Existing Feature`**
   - **What exists today and its challenges** — the current behavior and where it falls short.
   - **What is needed** — the gap between today and the goal.
   - **The changes required** — the shape of the work at a high level.

3. **`## Full Feature Walk Through`**
   - Walk the reader through a simple journey, describing the control flow from a functional or visual perspective — what is going to happen, step by step.
   - Use visual aids: ASCII diagrams, a numbered user journey, before/after sketches. User journeys are usually the best example vehicle.
   - **Trace requirements.** When the request alludes to a JIRA / Confluence / project-management story, pull it in through the available connectors (or ask the operator for access) and tie the walk-through back to those requirements.

4. **`## A Brief Technical Overview`**
   - The things the sub-specs will cover in greater detail.
   - A quick walk-through of all the changes, without granular detail.
   - Highlight, at a **class or method level**, what gets changed to reach the goal — enough to map the feature onto the code, not enough to implement it yet.
   - List the child sub-specs and the slice each one owns, in dependency order.

### The technical sub-specs — one standalone engineering chapter per slice

> Each sub-spec is a **standalone engineering chapter**. It must read like an O'Reilly implementation guide: why this slice exists, what is true in the code today, what earlier design text is stale, what this sub-spec changes, the end-to-end flow it owns, and the concrete code and tests needed to land it. Use the simplest language. Design it for humans *and* for the specificity agents need.

Each technical sub-spec (`01.a.1` … `01.a.n`) is a child of the overview and covers **one** technical slice. It must:

- describe **how it fits into the larger solution** and what the outcome will be when this slice is done;
- state the **architectural boundary** it owns in clear terms;
- carry the actual change — a refactor, deletion, wiring change, runtime-behavior shift, or implementation phase — with **code-level implementation detail** that honors the conventions in the applicable skills and leaves **no ambiguity** for the implementing agent;
- be directly implementable by an engineer without flipping back to the parent overview;
- follow the repo's numbering scheme (e.g. `02.a.1` … `02.a.6` under `specifications/02-slo-tui-cli/`).

**Required metadata header.** Begin each sub-spec with a compact metadata line under the H1, including when known: `Status`, `Owner`, `Last updated`, `Parent spec`, `Branch`, `Repo`, `Approx. size`.

**Required title format.** Either form is acceptable — do not force `Step N - ...` if the repo already uses `02.a.1`:

- `Step 02.a.1 — Owning One Agent Session Per Process`
- `02.a.1 — Owning One Agent Session Per Process`

**Required numbered structure** (unless the operator explicitly asks for a different one):

1. `## 1. Context`
2. `## 2. Why` — why this slice exists and what it unlocks.
3. `## 3. Current State` — what is true in code **today**: real symbols, real file paths, current constraints, and any live deltas from older design text. If earlier specs or snippets are stale, say so explicitly and correct them here.
4. `## 4. Proposed Approach` — the design decision in plain English before any code appears.
5. `## 5. Domain Introductions` — define each new noun conceptually before it is used in the flow or code.
6. `## 6. End-to-End Flow` — walk the reader through the runtime slice this sub-spec owns.
7. `## 7. Implementation Details` — code-level detail, implementation order, verification commands, and manual smoke guidance where applicable. Honor the conventions in the applicable skills.
8. `## 8. Tests` — see the test requirements below.
9. `## 9. Acceptance Criteria`
10. `## 10. Dependencies` — what blocks this slice and what it blocks downstream.

**Tests a sub-spec must specify:**

- **Unit tests** that verify a single behavior in isolation.
- **Functional tests** that exercise the whole workflow this slice owns, starting from wherever the journey actually begins — a controller, a worker, or a CLI invocation — and driving it end to end, creating the right state for each assertion and asserting on the real output. A shallow mock-only test is not a functional test where project conventions require integration, transactional, or end-to-end verification.

---

## DRY Design: No Redundant Artefacts, Entities, or Domains

A specification written without checking the code first will happily invent functionality that **already exists**. The existing implementation may be doing the same work wholly, doing part of it, or already owning the responsibility the new design is about to duplicate. Every such duplicate is a defect in the design, not a harmless extra: two components now claim the same responsibility, neither is authoritative, and every future reader has to guess which one to change.

Our design must always keep the system **DRY**. Responsibilities are **single, isolated, and clean**. Boundaries between them are distinguishable and stated in the comments and docstrings, and adjacent responsibilities are reached through **explicit interfaces** rather than through duplicated logic.

Concretely, before the spec proposes any new domain, model, DAO, service, application service, router, worker, event, agent, tool, client, CLI command, or frontend store:

- search the code for something that already does that work, or owns the responsibility it belongs under — the duplicate is usually named differently, which is exactly why it gets missed;
- if something exists, the spec must consolidate rather than add. Consolidation takes one of three forms:
  1. **Delete and replace** — remove the existing functionality and replace it with the new construct, naming the files and symbols to delete and the call sites to repoint;
  2. **Encapsulate** — fold the new behavior into the existing component, elegantly and within the rules of our conventions, so a single owner remains;
  3. **Re-design** — reshape the existing component so it honors the conventions and absorbs the new functionality, eliminating the redundant behavior instead of growing a parallel implementation;
- state the resulting responsibility boundary in prose, show it in the docstrings or comments of the code samples, and name the interface adjacent components use to reach it.

The POST hook runs a mandatory consolidation pass over the entities and data structures the spec introduces and treats any surviving redundancy as an automatic REVISE. Writing the consolidation into the spec up front is how that pass comes back clean.

---

## Journey and Flow Sections

### `## Full Feature Walk Through` and the journey it owns

The overview's `## Full Feature Walk Through` covers the full surrounding journey. When a sub-spec owns only a slice of a larger user-facing or system-facing journey, restate the surrounding journey briefly and call out which slice this sub-spec owns. Numbered steps or an ASCII diagram are both acceptable.

Skip the journey framing only when the work is purely cross-cutting (e.g. logging utility, base controller, tiny internal helper).

### `## Control Flow: <hot-path-name> (Step-by-Step)`

For each non-trivial request path or workflow the plan ships, give a step-by-step ASCII or numbered walkthrough. Name every middleware, every private helper, every commit boundary, and every external call. End with a one-sentence atomicity or consistency guarantee.

This section is mandatory for any non-trivial orchestration. Domain-only specs may omit it.

---

## Bug and Analysis Specs: Ideal-Behavior-Then-Problem Structure

A spec that documents a bug, regression, or defect analysis must be structured so the reader understands the *correct* design before being shown where it breaks. Use this required order:

1. **The bug / problem** — lead with the symptom and a concise statement of the defect. What is observed, and what is wrong.
2. **How it should behave (ideal walkthrough)** — a detailed, step-by-step narrative of how the system *should* function in this scenario, walking the runtime end to end. The reader must come away understanding the intended design before the failure is pinpointed.
3. **The problem, restated** — return to the defect and pinpoint exactly where the ideal walkthrough breaks: the specific step, boundary, or line where correct behavior diverges from what actually happens.

Never open a bug spec with the broken control flow in isolation. The ideal walkthrough comes first so the break is legible against a known-good baseline.

---

## Ideal Behavior First, Then the Problem — With Real Code

This principle is not confined to bug specs. **Every** specification must walk the reader through the ideal behavior of the system before (or alongside) describing the problem or change: a detailed, plain-English narrative of how the components should interact when everything works correctly. Establish the ideal, *then* describe the problem or change against it.

Both the ideal-behavior walkthrough and the problem/change description must embed **real code samples taken from the actual codebase**, with `file:line` references — not pseudocode or invented signatures. The reader must see the concrete code the narrative is about.

For a bug report specifically, use these three ordered sections:

1. **Describe the bug** — the symptom plus a one-sentence cause.
2. **Ideal behavior** — a detailed walkthrough of how the components should have interacted, with real code samples.
3. **Reiterate the problem** — restate the defect against the ideal, showing the real code that diverges.

---

## `## Code Reference` Rules

Every code block in `## Code Reference` (and in a sub-spec's `## 7. Implementation Details`) must be preceded by 1-3 sentences of plain English explaining what the snippet does and why it is shaped that way. Silent code dumps are banned. Silent prose is banned too — behavioral claims need a code sample. Every substantive claim about runtime behavior must be grounded in a **real code sample copied faithfully from the actual source, with a `file:line` citation**. This applies everywhere a spec describes how code behaves, and in a bug spec it applies in **both** the ideal-behavior walkthrough and the problem sections. Prose-only descriptions of control flow are not sufficient — show the actual code.

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

In a technical sub-spec, embed the **full corrected example locally** rather than assuming the reader will consult the parent overview.

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

Technical sub-specs should also state:

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
10. **Both halves together** — product framing and engineering detail ship as one family; the overview sets the story, the sub-specs make each slice implementable.
11. **Standalone engineering slices** — each technical sub-spec must stand on its own.
12. **Drift correction** — when older spec text is stale, say so explicitly and correct it.
13. **Code samples as grounding** — every behavioral claim is backed by real source, copied faithfully with a `file:line` citation. Silent prose is banned as surely as silent code dumps.
14. **Ideal before break** — bug and analysis specs walk the correct design end to end before pinpointing where it fails.
15. **DRY design** — never add an artefact, entity, or domain that duplicates work the code already does. Consolidate by deleting and replacing, encapsulating, or re-designing the existing component.
16. **Single, isolated responsibilities** — one owner per responsibility, with distinguishable boundaries documented in the comments and explicit interfaces to adjacent responsibilities.

---

## Important: Implementation Details Are the Implementation Contract

> **This is the most important part of an engineering specification. Do not skim it or treat it as a casual summary.** `## 7. Implementation Details` is the implementation contract for the coding agent: it must provide a granular, code-level representation of how the feature will look and behave, while honoring all applicable repository conventions. An implementing agent must not need to infer file placement, symbol ownership, behavior, error handling, or the tests that prove the change works.

Read the packaged [`implementation-details-granularity.md`](../../samples/implementation-details-granularity.md) sample before drafting or reviewing non-trivial implementation details. It ships with the Slo skill bundle, so this reference is available in both repository checkouts and installed `pipx` environments. Follow its pattern of stating implementation order, identifying exact files and symbols, documenting current versus target behavior, showing full implementation-ready examples where a change is non-obvious, and naming the precise test changes required.

For every implementation slice, this section must explicitly state, as applicable:

- **Where code belongs:** the full repository-relative path of every file to create, modify, move, or delete; the containing folder or package; and why that location is the established owner under the application structure and coding conventions.
- **What changes in each file:** the exact classes, functions, methods, constants, models, types, templates, registrations, and call sites involved. State whether a symbol is added, changed, removed, renamed, or rewired, and identify the adjacent interfaces that must change with it.
- **How the code behaves:** ordered control flow; input, output, and type contracts; state transitions; data ownership; configuration; error and boundary behavior; ordering and idempotency rules; and intentionally unchanged behavior. Resolve every meaningful branch or edge case rather than leaving it for the implementer to decide.
- **How the code should be shaped:** implementation order, signatures and realistic values where they eliminate uncertainty, and complete or before/after code examples for non-trivial changes. Examples must be consistent with the repository's naming, typing, docstring, layering, dependency-injection, and test conventions — they are a build brief, not illustrative pseudocode.
- **What existing code is affected:** real `file:line` references for the current implementation, explicit replacements for stale behavior, and the exact consolidation or deletion required to keep a single owner for each responsibility.
- **How the feature is validated:** exact test file paths; existing tests to update, replace, or remove; new test names or cases; fixtures and setup; the behavior and assertions each test covers; required unit, integration, functional, CLI, or end-to-end coverage as appropriate; and scoped format, lint, type-check, and test commands. Include manual smoke steps when automation cannot fully validate the runtime behavior.

A statement such as “update the service,” “add tests,” or “handle errors” is insufficient. Replace it with the concrete file, symbol, behavior, expected result, and test assertion. If a competent implementing agent could reasonably make two different architectural or behavioral choices from the text, the implementation details are incomplete and the specification must be revised before hand-off.

---

**For AI:** When generating documentation in this style:

- Carry both halves — product overview and technical sub-specs — unless the user explicitly asks for only one.
- Prioritize developer efficiency — the spec should be directly implementable.
- Keep the opening human-readable and gradual, like an O'Reilly chapter.
- Preserve implementation rigor while improving readability.
- Use the canonical structure: Overview → Existing Feature → Full Feature Walk Through → Brief Technical Overview → technical sub-specs.
- Include concrete examples with realistic data and file paths.
- Ground every behavioral claim in a real code sample with a `file:line` citation — never describe control flow in prose alone.
- Before proposing any new artefact, search the code for an existing owner of that responsibility; when one exists, consolidate (delete and replace, encapsulate, or re-design) instead of adding a redundant construct.
- For a bug or analysis spec, lead with the problem, then walk the ideal behavior end to end, then restate exactly where it breaks.
- Show the complete picture: why, current truth, proposed shape, flow, code, tests, and dependencies.
- Think like a developer reading this at 2am trying to implement the feature without follow-up questions.