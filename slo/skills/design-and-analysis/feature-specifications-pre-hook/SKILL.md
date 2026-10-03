---
name: feature-specifications-pre-hook
description: Context-gathering pass that runs before drafting or revising a feature
  specification with feature-specifications. Loads KB, MEMORY.md, repo guardrails
  (CLAUDE.md / AGENTS.md / docs/RESEARCH.md), code conventions, and the current
  state of the affected surface so the resulting spec respects existing patterns,
  and identifies the existing owners the spec must consolidate with instead of
  duplicating.
when_to_use: Use as the mandatory pre-hook for feature-specifications.
group: design-and-analysis
kind: workflow
source_prompt: analyze/feature-specifications-pre-hook.md
---

# Feature Specifications — PRE Hook

## Skill summary

- **Name:** `feature-specifications-pre-hook`
- **Description:** Context-gathering pass that runs before drafting or revising a feature specification with feature-specifications. Loads KB, MEMORY.md, repo guardrails (CLAUDE.md / AGENTS.md / docs/RESEARCH.md), code conventions, and the current state of the affected surface so the resulting spec respects existing patterns, and identifies the existing owners the spec must consolidate with instead of duplicating.
- **When to use:** Use as the mandatory pre-hook for feature-specifications.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `analyze/feature-specifications-pre-hook.md`

## Examples

- The user asks for an end-to-end workflow that fits: Context-gathering pass that runs before drafting or revising a feature specification with feature-specifications. Loads KB, MEMORY.md, repo guardrails (CLAUDE.md / AGENTS.md / docs/RESEARCH.md), code conventions, and the current state of the affected surface so the resulting spec respects existing patterns, and identifies the existing owners the spec must consolidate with instead of duplicating.
- Use as the mandatory pre-hook for feature-specifications.

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

**Multi-language scope:** Begin with `skills/engineering/engineering-routing/SKILL.md`.
Read shared obligations and only affected language/component/framework recipes.
Python-specific examples and commands below are scoped examples, not universal
requirements. For mixed-language work preserve each boundary's approved contract.
Use `skills/engineering/engineering-testing/SKILL.md` for test categories and evidence.

## Purpose

A context-gathering pass that runs **before** the agent drafts or revises a feature specification using [`feature-specifications.md`](../feature-specifications/SKILL.md). The goal is to load every piece of background knowledge the spec must respect — durable knowledge (KB), point-in-time memory (MEMORY.md), repo guardrails (CLAUDE.md / AGENTS.md / RESEARCH.md), code conventions, and the current state of the affected surface area — so the resulting spec is consistent with the rest of the system instead of inventing patterns from scratch.

Treat this hook as **non-optional**. Do not produce a feature specification until every step below has been completed and the synthesis at the end exists in the conversation.

---

## When to invoke

Invoke this hook automatically whenever the operator asks for:

- "Write a feature spec for …"
- "Generate a feature specification …"
- "Spec out …"
- any task that will end with a document produced under `<feature-requests-root>/`, `<feature-specifications-root>/<ticket-id>/…`, or a repo `specifications/` folder and uses [`feature-specifications.md`](../feature-specifications/SKILL.md) as its style guide.

If a JIRA / Confluence / GitLab issue is referenced, fetch it first — its content drives which areas of the codebase and KB you read.

---

## Step 1 — Load global guardrails

Read these in order. They define how this codebase is allowed to be written, regardless of the feature being specified:

1. `~/.claude/CLAUDE.md` — global ground rules (named arguments, type hints, declarative methods, env handling).
2. `CLAUDE.md` — repo-scoped instructions.
3. `AGENTS.md` — agent operating instructions for this repo.
4. `RESEARCH.md` — index of services, workflows, queues, and test layout.
5. `<project-memory>/MEMORY.md` — point-in-time project memory.

Note any guardrail that constrains the spec.

---

## Step 2 — Decide which artefact(s) this pass produces

Before reading the implementation surface in detail, decide which part(s) of the single specification family this pass is writing, per [`feature-specifications.md`](../feature-specifications/SKILL.md). There is **one** specification shape, not a choice between a "business" document and an "engineering" document. Every non-trivial feature needs **both** halves, and they live together as one family:

- **the overview** (`overview.md`) — carries the product/business framing and ends with a brief technical overview;
- **one or more technical sub-specs** (`01.a.1`, `01.a.2`, …) — each a standalone engineering chapter owning one implementation slice.

A tiny, single-slice feature may fold both halves into one document. A larger feature keeps the overview thin and pushes depth into numbered sub-specs. Either way, produce both halves unless the operator explicitly asks for just the overview or just a single sub-spec.

### The overview half covers

- product or business behavior,
- user/admin journeys,
- multi-layer feature design,
- requirements traceability,
- broad rollout framing.

### Each technical sub-spec half covers

- one technical slice of a larger feature,
- a parent-overview child step,
- an architectural boundary or runtime seam,
- a refactor, deletion, wiring change, CLI/TUI/runtime behavior change,
- a low-ambiguity implementation chapter like `02.a.1` through `02.a.6`.

### What to record

State in the PRE-Hook Context Bundle which artefact(s) this pass will produce:

- `**Producing:** overview + technical sub-specs`
- `**Producing:** overview only`
- `**Producing:** technical sub-spec <NN.a.n> only`

If the operator asked for only one half, state that inference and why. Otherwise assume both halves are in scope.

---

## Step 3 — Load Knowledge Base context

The KB at `$SLO_KB_DIR/` is the durable cross-session memory. Read it scoped to the feature.

**Knowledge base discovery is non-blocking.** Locate the KB with `skills/design-and-analysis/locate-knowledge-base/SKILL.md`
first. When no KB is found, tell the user, offer to create one, record
"no knowledge base found" in the Context Bundle, and continue to Step 4.

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

## Step 4 — Inventory the affected surface area

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

## Step 4.5 — Identify redundancy and consolidation candidates

The surface inventory answers "what will this feature sit next to". This step answers the harder question: **what already does this work?**

A spec drafted without that answer creates redundant artefacts, entities, and domains — the existing implementation may be doing the same work wholly, doing part of it, or already owning the responsibility the new design is about to duplicate. Two owners for one responsibility is confusion that outlives the feature, so the duplication has to be found here, before a line of the spec is written.

For every capability the feature implies — each domain, model, DAO, service, application service, router, worker, event, agent, tool, client, CLI command, config key, or frontend store it will likely need — search the code for an existing owner. Search by behavior, not by the name the ask happens to use: the existing component is usually named differently, which is exactly why it gets missed.

Record each hit:

| Capability the feature needs | Existing owner (`file:line`) | Overlap | Consolidation candidate |
|---|---|---|---|
| ... | ... | wholly / partially / adjacent responsibility | delete-and-replace / encapsulate / re-design |

Consolidation candidates take one of three forms, and the PRE hook should state which one it expects:

1. **Delete and replace** — the existing functionality is removed and replaced by the new construct.
2. **Encapsulate** — the new behavior is folded into the existing component, within the rules of our conventions, so a single owner remains.
3. **Re-design** — the existing component is reshaped to honor the conventions and absorb the new functionality, eliminating redundant behavior rather than growing a parallel implementation.

Also note, for each adjacent responsibility, where the boundary should fall and what interface the new work should use to reach across it. Those boundaries must be documented in the spec's prose and in the docstrings or comments of its code samples.

If nothing overlaps, say so explicitly — "no existing owner found for X" is a finding, not an omission.

---

## Step 5 — Read the matching code-convention prompts

Once you know the surface area, read **every** matching rule under `skills/coding/`. Err toward reading more rather than fewer — a missed convention is the most common source of spec rework.

Common mappings (read all that apply):

- application services → `skills/languages/python/build-application-services/SKILL.md`
- domain features → `skills/languages/python/build-domain-features/SKILL.md`
- FastAPI routers → `skills/languages/python/build-routers/SKILL.md`
- middleware → `skills/languages/python/build-middleware/SKILL.md`
- event handlers → `skills/languages/python/build-event-handlers/SKILL.md`
- partitioned events → `skills/languages/python/build-partitioned-events/SKILL.md`
- Celery workers → `skills/languages/python/build-celery-workers/SKILL.md`
- DBOS workflows → `skills/languages/python/build-dbos-workflow-orchestration-pattern/SKILL.md`
- DBOS schedulers / tasks → `skills/languages/python/build-schedulers-tasks-with-dbos/SKILL.md`
- LangGraph agents → `skills/languages/python/build-react-agent-with-langgraph/SKILL.md`
- agent tools → `skills/languages/python/build-agent-tools/SKILL.md`
- graph / gateway invoke convention → `skills/languages/python/graph-gateway-invoke-convention/SKILL.md`
- API clients → `skills/languages/python/build-clients/SKILL.md`
- API docs / Swagger → `skills/languages/python/build-api-documentation/SKILL.md`, `skills/languages/python/generate-swagger-documentation/SKILL.md`
- ClickHouse features → `skills/languages/python/build-clickhouse-features/SKILL.md`
- Alembic setup → `skills/languages/python/setup-alembic/SKILL.md`
- dependencies / tests → `skills/languages/python/setup-dependencies-and-tests/SKILL.md`
- always-on style → `skills/languages/python/named-arguments-and-type-hints/SKILL.md`, `skills/languages/python/declarative-method-structure/SKILL.md`, `skills/languages/python/method-docstrings/SKILL.md`, `skills/coding/test-verification-policy/SKILL.md`, `skills/languages/python/application-structure/SKILL.md`

For Vue / TS work, also read the relevant `skills/frontend-vue/` convention files.

---

## Step 6 — Capture second-order requirements

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

## Step 7 — Plan the human-readable narrative sections

Per [`feature-specifications.md`](../feature-specifications/SKILL.md), every spec opens with narrative context before low-level implementation detail. Plan those sections during the PRE hook — they are not afterthoughts.

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

## Step 8 — Synthesize the context bundle

Before drafting the spec, produce a short synthesis block in the conversation. This is the **PRE hook's deliverable**. Keep it tight; it is the brief the spec writer will work from.

```markdown
### PRE-Hook Context Bundle — <feature title or ticket id>

**Source ask:** <1-2 sentences from the operator / JIRA / Confluence>

**Producing:** <overview + technical sub-specs | overview only | technical sub-spec NN.a.n only>

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

If any open question would materially change the spec, pause and ask the operator before writing. Otherwise proceed to [`feature-specifications.md`](../feature-specifications/SKILL.md) with this bundle in mind.

---

## Hand-off

The synthesis block above is the only artefact the PRE hook produces. The spec writer must read it before the first heading of the specification, and every section of the spec must trace back to one or more bullets in the bundle. Anything not covered by the bundle must be flagged in the spec as an explicit assumption.
