---
name: feature-specifications
description: Author feature specifications through Gather context, Draft, Self-check and Revise; preserve product framing and standalone engineering detail.
when_to_use: Use whenever drafting or revising a feature specification. Independent verification and task breakdown remain separate skills sequenced by the specification-development workflow.
group: design-and-analysis
kind: skill
source_prompt: analyze/feature-specifications.md
---

# Feature Specifications

## Skill summary

- **Name:** `feature-specifications`
- **Description:** The authoritative authoring skill: Gather context → Draft → Self-check → Revise.
- **When to use:** Write, generate, spec out, or revise a feature specification.
- **Group:** `design-and-analysis`
- **Kind:** `skill`

## Examples

- Write a feature spec from a ticket or verbal brief.
- Revise a technical child slice after review without losing its product context.
- Self-check an overview and its engineering sub-specs before independent review.

## Guidance

Run all four stages in order. Context gathering is mandatory before the first
heading; self-check is mandatory immediately after every draft or revision,
before commit, wiki publication, developer handoff, task breakdown or implementation.
Fetch any referenced JIRA / Confluence / GitLab issue first to scope the research.
Do not skip checks because “we just wrote it”. A specification without the context
bundle and clean self-check report is incomplete.

This is an authoring skill, not a formal workflow. When the operator requests the
Specification Development workflow, load `skills/design-and-analysis/workflows/specification-development.md`.
That workflow sequences this skill, independent verification, then task breakdown.
Skim `feature-specification-verification` and `breakdown-feature-spec-to-tasks`
unless the user asks otherwise; `gather-feature-context` remains an on-request
context companion. Do not recursively invoke this skill through the old hooks.

## Artifact paths and skill discovery

Resolve artifact roots in this order: explicit user instruction → repository
project override → the environment/home defaults below. In the Slo repository,
CLAUDE.md mandates repo-local `feature-requests/` and `specifications/` (the latter
is a symlink to the canonical root). Do not silently replace this project override
with a home-directory default. Never name a specification `request.md`; that name
belongs only to incoming request artifacts.

Every feature requires **overview.md** with product framing and one or more
**standalone engineering sub-specs** in separate files. There is no document-mode
selection, overview-only deliverable, or combined-document exception, even for a
small feature. When revising an existing slice, retain and verify the complete
family rather than treating that slice as a substitute for the other artifacts.
Lightweight execution tickets may link to a complete sub-spec; they never replace it.

**Skill discovery.** Use the active skill catalog's `file_path` for each named
skill, including user overrides. Resolve vendored locations through `config.cfg`
(`SKILLS_LOCATION` / `SKILLS_DIR`), not an assumed installation directory:

1. `SLO_SKILLS_DIR` when set and non-empty; an invalid explicit override must
   surface as a missing location, not silently fall back.
2. The populated `skills` directory under the runtime-resolved `SLO_HOME`.
3. The package-adjacent `skills` directory discovered from the installed Slo
   package (or the equivalent directory in a development checkout).

Use `config.cfg.USER_SKILLS_DIR` and `USER_WORKFLOWS_DIR` for personal content.
They honor `SLO_USER_SKILLS_DIR` and `SLO_USER_WORKFLOWS_DIR`, respectively,
otherwise using `user_skills` and `user_workflows` under the resolved Slo home.
Slo resolves its home from `SLO_HOME` or the current user's home via `Path.home()`.
Do not invent environment variables or hard-code a username, operating-system
home prefix, Python version, package-manager layout, or absolute skill path.
Paths written as `skills/<group>/...` in these instructions are logical library
references; resolve them against the discovered library, not the caller's working
directory. Relative Markdown links remain relative to the containing skill file.
If required locations cannot be found, report the missing configuration and ask
rather than guessing. Preserve personal-skill override precedence.

**Write for humans first.** Use simple, direct language throughout, and lean on visual representation — ASCII diagrams, numbered user journeys, before/after trees, and tables — wherever a picture makes the change quicker to understand than prose.

**Artifact paths.** After applying the precedence above, the generic defaults are:

```text
<feature-requests-root> = <SLO_FEATURE_REQUESTS_DIR or resolved-Slo-home/projects/<project_name>/feature-requests>
<feature-specifications-root> = <SLO_FEATURE_SPECIFICATIONS_DIR or resolved-Slo-home/projects/<project_name>/feature-specifications>
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

## Gather context

### 1 — Load global guardrails

Read these in order. They define how this codebase is allowed to be written, regardless of the feature being specified:

1. The global `CLAUDE.md` discovered for the current user — global ground rules (named arguments, type hints, declarative methods, env handling).
2. `CLAUDE.md` — repo-scoped instructions.
3. `AGENTS.md` — agent operating instructions for this repo.
4. `RESEARCH.md` — index of services, workflows, queues, and test layout.
5. `<project-memory>/MEMORY.md` — point-in-time project memory.

Note any guardrail that constrains the spec.

---

Also load home and repo copies of SLO.md, CLAUDE.md and AGENTS.md when present,
using Slo project-context discovery and the resolved current-user home, plus maintained project
RESEARCH.md / docs/RESEARCH.md and MEMORY.md. Repository instruction precedence
wins over the generic reading order. Record every constraint.

### Declare artifacts

Use the single-family definition below. Record `Producing: overview + standalone
engineering sub-specs` and list the overview and every planned sub-spec. Both parts
are always required; record existing artifacts being retained or revised as well.
The overview covers product behavior, user/admin journeys, multi-layer design,
requirements traceability and rollout. Children cover one parent-linked technical
slice, boundary, refactor, deletion, wiring or CLI/TUI/runtime change.

### 3 — Load Knowledge Base context

The KB at `$SLO_KB_DIR/` is the durable cross-session memory. Read it scoped to the feature.

**Knowledge base discovery is non-blocking.** Locate the KB with `skills/design-and-analysis/locate-knowledge-base/SKILL.md`
first. When no KB is found, tell the user, offer to create one, record
"no knowledge base found" in the Context Bundle, and continue to the surface inventory.

1. Read the KB entry point (`Welcome.md` or `index.md`; `Home.md` in older vaults) to refresh the index.
2. For each KB folder whose scope overlaps the feature, read its `index.md` and any clearly relevant entry.
3. Specifically scan each visited README's **"I saw this error, what now?"** table for failure modes the spec must pre-empt.

Map feature surface → folder (illustrative for an order-management platform; use the vault's real folders):

| Feature touches | KB folder |
|---|---|
| FastAPI backend, domain DAOs/services, middleware, env | `orders_service/` |
| Payments, refunds, tokenization | `payments_service/` |
| SMS/email notifications, provider integrations | `notifications_service/` |
| Vue 3 SPA, Pinia, `useAgentStream` | `admin_ui/` |
| Coding conventions / structure | `conventions/` |
| Tests (pytest async, mocks) | `testing/` |
| Feature → plan → wiki workflow | `workflow/` |
| Deploy, secrets, infra | `deployment/` |

---

### 4 — Inventory the affected surface area

Use Glob / Grep / Read to enumerate the code the spec will touch or sit next to. Do **not** rely on names alone — read enough of each file to confirm its responsibility.

Cover, at minimum, whichever of these layers the feature touches:

- **Domains** — `src/domains/<area>/{model,dao,service}.py`
- **Application services** — `src/services/<area>/*_app_service.py`
- **Routers / API surface** — `src/controllers/**` or equivalent FastAPI routers
- **Workers / schedulers / events** — `src/tasks/**`, DBOS workflows, Celery registration, event handlers
- **Agents / tools** — `src/agents/**`
- **Frontend** — Vue components, composables, stores
- **Database** — Alembic versions, ClickHouse DDL, indexes
- **Integrations** — `src/integrations/**`
- **Deployment** — `deployment/**`, stack files, Makefile targets, env vars
- **Existing specifications** — parent specs, sibling specs, or earlier plan files if this feature is being added in phases

For every affected file, capture:

- file path,
- one-line role summary,
- the convention it already follows that the spec must mirror,
- whether it is current truth, adjacent context, or stale prior design text.

### Extra requirement when producing a technical sub-spec

When this pass produces a technical sub-spec, build two additional inventories:

1. **Current-state truths** — the exact symbols, method names, runtime behaviors, file paths, and constraints that are true in code today.
2. **Stale or drifting prior design text** — older specs, parent-spec snippets, comments, or docs that are now inaccurate or incomplete and that the new sub-spec must correct explicitly.

If the sub-spec is supposed to be standalone, identify which parent-spec facts must be restated locally so the implementer does not need to keep switching documents.

---

### 4.5 — Identify redundancy and consolidation candidates

The surface inventory answers "what will this feature sit next to". This step answers the harder question: **what already does this work?**

A spec drafted without that answer creates redundant artefacts, entities, and domains — the existing implementation may be doing the same work wholly, doing part of it, or already owning the responsibility the new design is about to duplicate. Two owners for one responsibility is confusion that outlives the feature, so the duplication has to be found here, before a line of the spec is written.

For every capability the feature implies — each domain, model, DAO, service, application service, router, worker, event, agent, tool, client, CLI command, config key, or frontend store it will likely need — search the code for an existing owner. Search by behavior, not by the name the ask happens to use: the existing component is usually named differently, which is exactly why it gets missed.

Record each hit:

| Capability the feature needs | Existing owner (`file:line`) | Overlap | Consolidation candidate |
|---|---|---|---|
| ... | ... | wholly / partially / adjacent responsibility | delete-and-replace / encapsulate / re-design |

State the expected consolidation form using the single definition in
[DRY design](#dry-design-no-redundant-artefacts-entities-or-domains): delete and
replace, encapsulate, or re-design. Do not invent a parallel owner.

Also note, for each adjacent responsibility, where the boundary should fall and what interface the new work should use to reach across it. Those boundaries must be documented in the spec's prose and in the docstrings or comments of its code samples.

If nothing overlaps, say so explicitly — "no existing owner found for X" is a finding, not an omission.

---
### 5 — Read the matching code-convention prompts

Once you know the surface area, read **every** matching rule under `skills/coding/`. Err toward reading more rather than fewer — a missed convention is the most common source of spec rework.

Common mappings (read all that apply):

- application services → `skills/coding/build-application-services/SKILL.md`
- domain features → `skills/coding/build-domain-features/SKILL.md`
- FastAPI routers → `skills/coding/build-routers/SKILL.md`
- middleware → `skills/coding/build-middleware/SKILL.md`
- event handlers → `skills/coding/build-event-handlers/SKILL.md`
- partitioned events → `skills/coding/build-partitioned-events/SKILL.md`
- Celery workers → `skills/coding/build-celery-workers/SKILL.md`
- DBOS workflows → `skills/coding/build-dbos-workflow-orchestration-pattern/SKILL.md`
- DBOS schedulers / tasks → `skills/coding/build-schedulers-tasks-with-dbos/SKILL.md`
- LangGraph agents → `skills/coding/build-react-agent-with-langgraph/SKILL.md`
- agent tools → `skills/coding/build-agent-tools/SKILL.md`
- graph / gateway invoke convention → `skills/coding/graph-gateway-invoke-convention/SKILL.md`
- API clients → `skills/coding/build-clients/SKILL.md`
- API docs / Swagger → `skills/coding/build-api-documentation/SKILL.md`, `skills/coding/generate-swagger-documentation/SKILL.md`
- ClickHouse features → `skills/coding/build-clickhouse-features/SKILL.md`
- Alembic setup → `skills/coding/setup-alembic/SKILL.md`
- dependencies / tests → `skills/coding/setup-dependencies-and-tests/SKILL.md`
- always-on style → `skills/coding/named-arguments-and-type-hints/SKILL.md`, `skills/coding/declarative-method-structure/SKILL.md`, `skills/coding/method-docstrings/SKILL.md`, `skills/coding/test-verification-policy/SKILL.md`, `skills/coding/application-structure/SKILL.md`

For Vue / TS work, also read the relevant `skills/frontend-vue/` convention files.

---

### 6 — Capture second-order requirements

Beyond what the feature *does*, the spec must respect the nuanced choices already baked into the system. Walk this checklist and record concrete numbers or patterns drawn from the code and KB, not assumptions.

- **Scale & throughput**
- **Latency budgets**
- **Concurrency & idempotency**
- **Logging & observability**
- **Error model**
- **Security & auth**
- **Data lifecycle**
- **Naming & conventions**
- **Testing posture**
- **Deployment posture**
- **Cross-repo impact**

Anything noted here becomes a requirement the spec must address, either inline or as an explicit defer / out-of-scope note.

---

### 7 — Plan the human-readable narrative sections

Per [Draft](#draft), every spec opens with narrative context before low-level implementation detail. Plan those sections during the context stage — they are not afterthoughts.

The opening should read like an **O'Reilly technical book chapter**: start with the problem and the runtime or business story, orient the reader in the existing system, and only then descend into classes, files, and methods.

For the spec you are about to write, decide:

- **Changes vs Description** — which heading the spec should use, and why.
- **Big Picture** — what just happened upstream, what this plan owns, and what downstream work depends on it.
- **Existing structure we are extending** — what current tree the reader must see before implementation discussion starts.
- **What this document changes** — runtime or product change first, then file-level change, then component-level change.
- **Per-component prose** — every domain, service, router, worker, integration, component, or utility that must appear in prose before it appears later in code.
- **Call-out plan** — which decisions belong together in one structured call-out.
- **Journey** — whether the feature is part of a larger user or system journey.
- **Control flows** — which orchestrations need step-by-step walkthroughs.
- **Code-sample depth** — which classes need full examples with class docstring, main public method, and core helpers.

### Extra planning requirements for the overview

When this pass produces the overview, also plan:

- the business problem framing,
- the requirements / scope / non-goals split,
- user/admin lifecycle or rollout sequencing,
- cross-repo or stakeholder boundaries,
- whether a later breakdown into engineering child specs is likely.

### Extra planning requirements for a technical sub-spec

When this pass produces a technical sub-spec, also plan:

- the metadata header fields available (`Status`, `Owner`, `Last updated`, `Parent spec`, `Branch`, `Repo`, `Approx. size`),
- the `Why` section — why this slice exists independently,
- the `Current State` section — the live code truths the spec must record,
- the `Proposed Approach` section — the concise design decision before code,
- the `Domain Introductions` section — every new noun that needs conceptual introduction,
- the `End-to-End Flow` section — the specific runtime slice this sub-spec owns,
- implementation order,
- verification commands,
- manual smoke guidance,
- what remains intentionally unchanged,
- what stale parent-spec snippets or prior plan text must be corrected explicitly,
- what facts must be restated locally to keep the sub-spec standalone.

---

### 8 — Synthesize the context bundle

Before drafting the spec, produce a short synthesis block in the conversation. This is the **context stage's deliverable**. Keep it tight; it is the brief the spec writer will work from.

```markdown
### PRE-Hook Context Bundle — <feature title or ticket id>

**Source ask:** <1-2 sentences from the operator / JIRA / Confluence>

**Producing:** overview + standalone engineering sub-specs
**Family artifacts:** <overview.md and all numbered sub-spec paths>

**Affected surface area:**
- <file path>:<line range> — <role + convention to mirror>
- …

**Conventions in force:**
- <rule file> — <one-line takeaway>
- …

**Second-order requirements:**
- Scale: <...>
- Latency: <...>
- Logging: <...>
- Idempotency / concurrency: <...>
- Testing: <...>
- Deployment: <...>

**Redundancy and consolidation candidates:**
- <capability> — already owned by <existing symbol at file:line> (<wholly | partially | adjacent>) → <delete-and-replace | encapsulate | re-design>
- <capability> — no existing owner found; genuinely new
- Boundaries to document: <where the responsibility line falls, and the interface across it>

**KB lessons to apply:**
- <KB entry path> — <one-line failure mode to pre-empt>
- …

**Open questions for the operator (if any):**
- <question> — <why it blocks the spec>

**Narrative plan:**
- *Changes or Description:* <which heading the spec should use, and why>
- *Big Picture:* <upstream → this → downstream>
- *Existing structure to show:* <which current tree the reader needs>
- *What this document changes:* <runtime/product first, then file-level, then component-level>
- *Per-component prose to write:* <each domain/service/router/worker/component that needs prose before code>
- *Decision call-out:* <which decisions should be grouped into one structured call-out>
- *Journey context:* <if applicable>
- *Control flows to walk through:* <if applicable>
- *Code samples that must be full-detail:* <which classes / methods need low-ambiguity examples>
```

### Additional required bundle content when producing a technical sub-spec

When this pass produces a technical sub-spec, extend the bundle with:

```markdown
**Current-state truths to record:**
- <real symbol / file / runtime truth>
- …

**Stale or drifting prior design text to correct:**
- <old spec path or snippet> — <what is stale>
- …

**Standalone facts to restate locally:**
- <parent-spec fact the child spec must repeat>
- …

**Implementation-order / verification plan:**
- Implementation order: <ordered list>
- Verification commands: <scoped format/lint/test commands>
- Manual smoke: <interactive or runtime checks, if applicable>
- Intentionally unchanged: <what remains untouched>
```

If any open question would materially change the spec, pause and ask the operator before writing. Otherwise proceed to [Draft](#draft) with this bundle in mind.

---

### Context handoff

The synthesis block above is the only artefact the context stage produces. The spec writer must read it before the first heading of the specification, and every section of the spec must trace back to one or more bullets in the bundle. Anything not covered by the bundle must be flagged in the spec as an explicit assumption.

## Draft

### One Specification, Product Framing *and* Engineering Detail Together

> **There is a single specification shape.** It is **not** a choice between a "business" document and an "engineering" document — every feature needs both, and they live together as one family:
>
> - an **`overview.md`** that carries the product/business framing and ends with a brief technical overview, and
> - one or more **technical sub-specs** (`01.a.1`, `01.a.2`, …) that each own one implementation slice in full engineering detail.
>
> Even a single-slice feature has an overview and a separate standalone engineering sub-spec. Keep the overview focused on product framing and put implementation-ready detail in numbered sub-specs — **never one without the other**.
>
> **Write for two audiences at once.** The overview and the narrative must be plain enough for a human to follow with no prior context; the sub-specs must be precise enough for an implementation agent to build from with no follow-up questions. Simple language throughout. Gradual context. Introduce existing concepts before you change them.
>
> **Both parts are mandatory.** A request to revise one file does not waive the other artifacts or permit an incomplete family to be marked READY.
>
> **Open like an O'Reilly chapter.** Every specification — the overview and every child sub-spec — must begin with the problem and the runtime or business story, orient the reader inside the existing system, then progressively narrow into components and code. Do **not** jump straight into method names or low-level implementation details before the reader understands the change in plain English.
>
> Use a mix of narrative, numbered steps, ASCII diagrams, and tables to orient the reader. Avoid silent code dumps or silent prose. Every behavioral claim must be grounded in a real code sample with a `file:line` citation. This document is for the user *and* the AI, so lay emphasis on readability and clarity.

---
### Shared Opening Requirements

### Mandatory opening section: `## Context`

The `## Context` block is always required. It must contain, in order:

1. **`### Changes`** or **`### Description`** — use `Changes` when the plan modifies existing behavior; use `Description` when the plan introduces something new.
2. **`### Big Picture`** — 1-2 paragraphs explaining where this work sits in the larger rollout, what just happened upstream, what this plan owns, and what downstream work depends on it.
3. **`### Existing structure we are extending`** — show the surrounding file/folder layout that already exists today when structure matters. Prefer fuller trees over overly-truncated diagrams.
4. **`### What this document changes`** — walk from broad change to narrow change: runtime or product behavior first, then file-level changes, then component-level changes.

When the plan resolves an ambiguity, stale design, or self-check finding, add a sub-section under `## Context` named:

- `### Ambiguity #<n> resolution`
- `### Bug #<n> resolution`
- `### CRITICAL #<n> resolution`

That section must explicitly state the issue and the chosen resolution.

### Additional mandatory opening rules

- Use **one structured call-out** with bold labels instead of stacking several one-line call-outs back-to-back.
- Do **not** use `§` references in prose. Prefer explicit headings, file paths, or short phrases like "in the builder example below".
- Every named domain, service, router, worker, component, view, or utility that later appears in code must appear in prose first.

---

### Canonical Structure

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

### DRY Design: No Redundant Artefacts, Entities, or Domains

A specification written without checking the code first will happily invent functionality that **already exists**. The existing implementation may be doing the same work wholly, doing part of it, or already owning the responsibility the new design is about to duplicate. Every such duplicate is a defect in the design, not a harmless extra: two components now claim the same responsibility, neither is authoritative, and every future reader has to guess which one to change.

Our design must always keep the system **DRY**. Responsibilities are **single, isolated, and clean**. Boundaries between them are distinguishable and stated in the comments and docstrings, and adjacent responsibilities are reached through **explicit interfaces** rather than through duplicated logic.

Concretely, before the spec proposes any new domain, model, DAO, service, application service, router, worker, event, agent, tool, client, CLI command, or frontend store:

- search the code for something that already does that work, or owns the responsibility it belongs under — the duplicate is usually named differently, which is exactly why it gets missed;
- if something exists, the spec must consolidate rather than add. Consolidation takes one of three forms:
  1. **Delete and replace** — remove the existing functionality and replace it with the new construct, naming the files and symbols to delete and the call sites to repoint;
  2. **Encapsulate** — fold the new behavior into the existing component, elegantly and within the rules of our conventions, so a single owner remains;
  3. **Re-design** — reshape the existing component so it honors the conventions and absorbs the new functionality, eliminating the redundant behavior instead of growing a parallel implementation;
- state the resulting responsibility boundary in prose, show it in the docstrings or comments of the code samples, and name the interface adjacent components use to reach it.

The self-check stage runs a mandatory consolidation pass over the entities and data structures the spec introduces and treats any surviving redundancy as an automatic REVISE. Writing the consolidation into the spec up front is how that pass comes back clean.

---

### Journey and Flow Sections

### `## Full Feature Walk Through` and the journey it owns

The overview's `## Full Feature Walk Through` covers the full surrounding journey. When a sub-spec owns only a slice of a larger user-facing or system-facing journey, restate the surrounding journey briefly and call out which slice this sub-spec owns. Numbered steps or an ASCII diagram are both acceptable.

Skip the journey framing only when the work is purely cross-cutting (e.g. logging utility, base controller, tiny internal helper).

### `## Control Flow: <hot-path-name> (Step-by-Step)`

For each non-trivial request path or workflow the plan ships, give a step-by-step ASCII or numbered walkthrough. Name every middleware, every private helper, every commit boundary, and every external call. End with a one-sentence atomicity or consistency guarantee.

This section is mandatory for any non-trivial orchestration. Domain-only specs may omit it.

---
### Ideal Behavior First, Then the Problem — With Real Code

This principle is not confined to bug specs. **Every** specification must walk the reader through the ideal behavior of the system before (or alongside) describing the problem or change: a detailed, plain-English narrative of how the components should interact when everything works correctly. Establish the ideal, *then* describe the problem or change against it.

Both the ideal-behavior walkthrough and the problem/change description must embed **real code samples taken from the actual codebase**, with `file:line` references — not pseudocode or invented signatures. The reader must see the concrete code the narrative is about.

For a bug report specifically, use these three ordered sections:

1. **Describe the bug** — lead with the observed symptom and concise defect plus a one-sentence cause. Never open with the broken control flow in isolation.
2. **Ideal behavior** — a detailed walkthrough of how the components should have interacted, with real code samples.
3. **Reiterate the problem** — pinpoint the exact step, boundary or line where actual behavior diverges from the ideal, showing the real code.

---

### `## Code Reference` Rules

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

- named arguments at Python call sites (Go named-field structs / context-first calls and TypeScript named options objects follow their own conventions),
- explicit types on every signature,
- declarative method structure,
- Python Google-style docstrings; Go godoc; TypeScript JSDoc, following applicable language skills,
- real identifiers and realistic values.

In a technical sub-spec, embed the **full corrected example locally** rather than assuming the reader will consult the parent overview.

---

### Writing Style

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

### Visual Aids & Formatting

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

### Implementation Guidance

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

### Consistency Rules

**Naming:**

- Python: snake_case for fields, files, and variables; use the applicable Go or TypeScript naming conventions for those languages
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

### Key Principles

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

### Important: Implementation Details Are the Implementation Contract

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

## Self-check

### Requirements architecture and failure audit

Perform a complete author-owned audit before the checks below. This replaces the
old POST hook's nested formal-review invocation, not its coverage. Use the full
[verification procedure](../feature-specification-verification/SKILL.md) as an audit
checklist, including Steps 1–7 and all layer/error/traceability checks; do not claim
this author pass is independent or invoke a second review inside it.

Re-read source requirements (including comments, implicit requirements and descopes),
map each to Covered / Partially Covered / Not Covered / Intentionally Excluded with
spec sections, and retain the complete Task/JIRA traceability matrix. Re-read relevant
conventions and RESEARCH.md. Check domain, application, worker, router, event,
integration, database/ClickHouse, admin UI and test layers. Trace every hop from real
entry point to terminal state, valid/invalid state transitions and cross-repo data
flow. Check DB failure, external errors, malformed input, missing entities, timeout
and concurrency. Independently substantiate novelty against adjacent code, not names.
Review actionability, artifact structure and implementation-details granularity against
the packaged sample. Substantiate findings, remove false positives, distinguish
CRITICAL/MINOR/AMBIGUOUS and respect intentional exclusions. Record the resulting
verification findings, layer checklist and requirement matrix with the author report;
every gap becomes a revision action. No outstanding critical gap may pass READY.

### Caller-burden check

Apply [Module-depth design guidance](../../coding/declarative-method-structure/SKILL.md#module-depth-design-guidance)
to proposed interfaces in Python, Go and TypeScript using each language's conventions.
Show what callers must know about constructors, ordering, flags and errors; what
complexity the existing owner actually owns; and whether its internals can change
without callers. One gateway alone proves nothing. Prefer meaningful outcomes and
cohesive private helpers, not wrappers or unrelated responsibility mergers. Preserve
thin adapters, security, compatibility, typing, naming, gateways and tests. Document
retry limits, cancellation, durability and meaningful errors. Record evidence-based
design observations separately: depth is advisory, not an automatic REVISE or an
exemption from the hard ~8-line extraction rule.

### Check 0 — Confirm which artefact(s) the draft covers

Read the PRE-Hook Context Bundle and confirm the draft covers the declared artifacts
under [the single-family contract](#one-specification-product-framing-and-engineering-detail-together).
Require overview.md with product framing and one or more standalone engineering sub-specs
in separate files. A missing part is a STRUCTURE GAP, including for small features.

If the draft is missing a required part, or a document uses the wrong structure for what it is (an overview written as a narrow engineering slice, or a sub-spec written as a broad product doc), record:

```markdown
**STRUCTURE GAP:** <expected artefact> — <what the draft currently reads like>
- Why this matters: <why the structure is misaligned>
- Required correction: <how to restructure or add the missing half>
```

A structure mismatch, or a missing required part, is an automatic **REVISE**.

---
### Check 1.5 — Human-readable narrative and structure audit (mandatory)

Per [Draft](#draft), every spec and every broken-down child spec must open with the human-readable narrative sections before low-level implementation detail.

### Shared opening audit (overview and every sub-spec)

Confirm each of these is present and non-trivial:

| Section | Required | What "present" means |
|---|---|---|
| `## Context` → `### Changes` **or** `### Description` | Always | Uses `Changes` when existing behavior is being modified and `Description` when something new is being introduced. Explains in plain English what should be different after the feature lands. |
| `## Context` → `### Big Picture` | Always | 1-2 paragraphs naming upstream and downstream work. Not a 1-line stub. |
| `## Context` → `### Existing structure we are extending` | When applicable | Shows enough current structure to orient the reader. |
| `## Context` → `### What this document changes` | Always | Walks from broad runtime or product change to file-level change to component-level change. Every named artefact in `## Code Reference` later must appear here first in prose. |
| `## Context` → `### <Ambiguity #|Bug #|CRITICAL #> resolution` | When applicable | If the draft is correcting stale design text or self-check findings, the resolution is named explicitly. |
| Opening structured call-out | When applicable | Uses one grouped call-out with bold labels for related decisions. No stack of one-line call-outs. |
| Prose intro before every code block in `## Code Reference` | Always | 1-3 sentences in plain English per code block. Silent code dumps are a gap. |
| Full-detail class examples where central | When applicable | Central classes include class docstring, main public method, and core helpers. Helper-method docstrings explain what the method does, who invokes it, and when it runs. |

### Overview audit — product framing

If the draft is the **overview**, also confirm:

- the opening reads like an O'Reilly textbook chapter led by product or business framing,
- the surrounding journey is explained when the feature is user-facing,
- scope / goals / non-goals are explicit,
- broad feature behavior is explained before technical implementation detail,
- the document does not read like a narrow engineering child slice unless that was intended.

### Technical sub-spec audit — engineering structure

If the draft is a **technical sub-spec**, all of the following are mandatory unless the operator explicitly asked for a different structure:

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

For every missing, stub-only, or wrong-structure section, record:

```markdown
**NARRATIVE GAP:** <section> — <what is missing>
- Where in the spec: <heading path>
- What to add: <concrete prose or structure change>
```

If **any** mandatory section is missing or stub-only, the verdict is automatically **REVISE**.

---

### Check 2 — Cross-check the spec against the code-convention prompts

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
- always-on style — language-appropriate named inputs and explicit types; Python Google-style docstrings, Go godoc, TypeScript JSDoc; declarative methods and one test per decision branch
- logging / observability — helper usage, structured fields, correlation IDs

For each violation, record:

```markdown
**CONVENTION GAP:** <rule file> — <one-line summary>
- Where in the spec: <section / code block>
- What to change: <concrete edit>
```

---

### Check 2.5 — DRY consolidation pass (mandatory)

Apply [DRY design](#dry-design-no-redundant-artefacts-entities-or-domains) unconditionally, even for greenfield work. Re-search rather than trusting the initial inventory.

#### 2.5.1 — Inventory what the spec introduces

List every new artefact the draft proposes: domains, models, DAOs, services, application services, routers, workers, events, agents, tools, clients, config keys, CLI commands, and frontend stores or components.

#### 2.5.2 — Search the code for the same or adjacent responsibility

For each artefact, search the codebase for something that already does that work — wholly, partially, or under a different name. Use the PRE-Hook Context Bundle's affected-surface inventory as the starting point, then widen the search: the duplicate is usually named differently, which is exactly why the draft missed it.

Classify each artefact:

| Verdict | Meaning |
|---|---|
| **Genuinely new** | No existing component owns this responsibility or any part of it. |
| **Duplicate** | An existing component already does this work wholly. |
| **Partial overlap** | An existing component does part of this work, or owns the responsibility this work belongs under. |
| **Adjacent** | A neighbouring component owns a related responsibility; the boundary between the two must be drawn and documented explicitly. |

#### 2.5.3 — Consolidate

Anything not classified **Genuinely new** must be consolidated in the spec before it can be READY. Use the three consolidation forms defined in Draft. For delete-and-replace, also name migration or data-backfill implications.

Whichever form is chosen, the spec must state the resulting responsibility boundary in prose and show it in the docstrings or comments of the code samples, along with the interface adjacent components use to reach it.

For every unconsolidated artefact, record:

```markdown
**REDUNDANCY GAP:** <new artefact> — duplicates / overlaps <existing symbol at file:line>
- Overlap: <wholly | partially | adjacent responsibility>
- Consolidation: <delete-and-replace | encapsulate | re-design>
- Required edit: <what the spec must say — files to delete, owner to keep, boundary to document, interface to expose>
```

Any unresolved **REDUNDANCY GAP** is an automatic **REVISE**. A spec that adds a second owner for an existing responsibility is not READY, no matter how well it is written.

---
### Check 3 — Granularity check

A spec that tries to do too much produces inconsistent implementations and stale wiki pages. Decide whether the spec should be split before it leaves self-check.

Split the spec if any of these are true:

- it spans more than ~3 architectural layers,
- it introduces more than one new domain,
- it mixes backend feature work with frontend feature work with deployment changes,
- it contains more than ~10 numbered workflow steps end-to-end,
- the traceability matrix has more than ~15 distinct requirements,
- different requirements have different stakeholders and can ship independently.

### Structure-aware split guidance

- The **overview** may stay broad — it is the parent that later breaks into child sub-specs.
- A **technical sub-spec** should stay narrow. If it starts to read like a parent roadmap instead of one technical slice, split it.
- When splitting, the child technical slices should become **standalone technical sub-specs**, not vague mini-business docs.

If a split is warranted:

1. Apply the local split analysis from [`breakdown-feature-spec-to-tasks`](../breakdown-feature-spec-to-tasks/SKILL.md), without publishing tasks or recursively authoring through that skill. Final task breakdown follows independent verification.
2. Produce a dependency-ordered task list.
3. Replace the monolithic body with one parent overview plus one child spec per task.

If no split is needed, record **Granularity: OK — fits in a single spec**.

---

### Check 4 — Example richness audit

A developer should be able to implement directly from the spec without follow-up questions. Walk the spec and verify that examples are present and convention-compliant.

For every section that introduces code or schema, the spec must show sufficiently full examples for the artefact being written.

### Shared example expectations

- realistic identifiers and values,
- real file paths,
- imports when needed for understanding,
- language-appropriate named inputs (Python keyword arguments, Go named-field structs, TypeScript options objects),
- explicit types,
- Python Google-style docstrings, Go godoc, TypeScript JSDoc on public and important helper methods, following applicable language skills,
- prose before every code block.

### Overview emphasis

For the **overview**, examples should be broad enough to make the system change concrete:

- domain models,
- DAOs,
- representative app-service or endpoint examples,
- workflow or API examples,
- test examples where they anchor acceptance criteria.

### Technical sub-spec emphasis

For a **technical sub-spec**, examples should be implementation-brief quality:

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

### Check 5 — Test coverage validation

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

## Revise and hand off

Aggregate the findings from all self-checks into a single revision plan:

```markdown
### POST-Hook Report — <feature title or ticket id>

| Metric | Value |
|---|---|
| Artefact | <overview | technical sub-spec NN.a.n> |
| JIRA requirements covered | X / Y (Z%) |
| Architectural layers verified | X / Y |
| Narrative gaps | N |
| Convention gaps | N |
| Redundancy gaps | N |
| Example gaps | N |
| Test gaps | N |
| Granularity | OK / SPLIT |
| Spec verdict | READY / REVISE |
```

Rules:

- Any non-zero **Narrative gap** count is automatic **REVISE**.
- Any non-zero **Redundancy gap** count is automatic **REVISE**.
- Any **structure mismatch**, or a missing required part, is automatic **REVISE**.
- Any missing mandatory technical-sub-spec section is automatic **REVISE**.
- Any missing prose before code blocks is automatic **REVISE**.

Then:

- If verdict is **REVISE**: edit the spec directly to close every critical gap, re-run the complete self-check, and repeat until READY.
- If verdict is **READY**: post the report in the conversation and stop authoring.
  Author READY is not independent approval. Hand the spec, context bundle, complete
  traceability matrix and self-check findings to independent verification exactly once:
  workflow Step 2, or the separate verification skill when used standalone. Return its
  findings to this authoring skill; revise and rerun self-check before re-review.
  Preserve the historical `PRE-Hook Context Bundle` and `POST-Hook Report` labels as
  compatibility aliases for Context Bundle and Author Self-check Report.

---

### Handoff

After author READY and independent verification with no outstanding CRITICAL gaps,
the next step depends on the operator's ask. Seek explicit confirmation before commit,
publication or external task creation; a local split analysis does not authorize it:

- commit and publish,
- break down into tasks,
- implement the feature,
- hand the spec to a developer.

Keep the self-check report in the conversation or PR description so the next reviewer can see what was already checked.
