---
name: feature-specifications-pre-hook
description: Context-gathering pass that runs before drafting or revising a feature
  specification with feature-specifications. Loads KB, MEMORY.md, repo guardrails
  (CLAUDE.md / AGENTS.md / RESEARCH.md), code conventions, and the current state of
  the affected surface so the resulting spec respects existing patterns.
when_to_use: Use as the mandatory pre-hook for feature-specifications.
group: design-and-analysis
kind: workflow
source_prompt: analyze/feature-specifications-pre-hook.md
---

# Feature Specifications — PRE Hook

## Skill summary

- **Name:** `feature-specifications-pre-hook`
- **Description:** Context-gathering pass that runs before drafting or revising a feature specification with feature-specifications. Loads KB, MEMORY.md, repo guardrails (CLAUDE.md / AGENTS.md / RESEARCH.md), code conventions, and the current state of the affected surface so the resulting spec respects existing patterns.
- **When to use:** Use as the mandatory pre-hook for feature-specifications.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `analyze/feature-specifications-pre-hook.md`

## Examples

- The user asks for an end-to-end workflow that fits: Context-gathering pass that runs before drafting or revising a feature specification with feature-specifications. Loads KB, MEMORY.md, repo guardrails (CLAUDE.md / AGENTS.md / RESEARCH.md), code conventions, and the current state of the affected surface so the resulting spec respects existing patterns.
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

## Purpose

A context-gathering pass that runs **before** the agent drafts or revises a feature specification using [`feature-specifications.md`](../feature-specifications/SKILL.md). The goal is to load every piece of background knowledge the spec must respect — durable knowledge (KB), point-in-time memory (MEMORY.md), repo guardrails (skills/orientation/claude/SKILL.md / AGENTS.md / skills/orientation/research/SKILL.md), code conventions, and the current state of the affected surface area — so the resulting spec is consistent with the rest of the system instead of inventing patterns from scratch.

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

1. `~/.claude/skills/orientation/claude/SKILL.md` — global ground rules (named arguments, type hints, declarative methods, env handling).
2. `skills/orientation/claude/SKILL.md` — repo-scoped instructions.
3. `AGENTS.md` — agent operating instructions for this repo.
4. `skills/orientation/research/SKILL.md` — index of services, workflows, queues, and test layout.
5. `<project-memory>/MEMORY.md` — point-in-time project memory.

Note any guardrail that constrains the spec.

---

## Step 2 — Choose the spec mode

Before reading the implementation surface in detail, decide which mode the document belongs to per [`feature-specifications.md`](../feature-specifications/SKILL.md).

### Mode A — Business / product feature spec

Choose this when the document is primarily about:

- product or business behavior,
- user/admin journeys,
- multi-layer feature design,
- requirements traceability,
- broad rollout framing.

### Mode B — Engineering implementation sub-spec

Choose this when the document is primarily about:

- one technical slice of a larger feature,
- a parent-spec child step,
- an architectural boundary or runtime seam,
- a refactor, deletion, wiring change, CLI/TUI/runtime behavior change,
- a low-ambiguity implementation chapter like `02.a.1` through `02.a.6`.

### What to record

State the choice explicitly in the PRE-Hook Context Bundle:

- `**Spec mode:** Business / product feature spec`
- `**Spec mode:** Engineering implementation sub-spec`

If the mode is unclear, ask the operator or state the inference and why.

---

## Step 3 — Load Knowledge Base context

The KB at `$SLO_KB_DIR/` is the durable cross-session memory. Read it scoped to the feature.

1. Always read `KB/Home.md` (or the vault's index page) to refresh the index.
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

### Extra requirement for Mode B

If the spec mode is **Engineering implementation sub-spec**, build two additional inventories:

1. **Current-state truths** — the exact symbols, method names, runtime behaviors, file paths, and constraints that are true in code today.
2. **Stale or drifting prior design text** — older specs, parent-spec snippets, comments, or docs that are now inaccurate or incomplete and that the new sub-spec must correct explicitly.

If the sub-spec is supposed to be standalone, identify which parent-spec facts must be restated locally so the implementer does not need to keep switching documents.

---

## Step 5 — Read the matching code-convention prompts

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

### Extra planning requirements for Mode A

If the spec mode is **Business / product feature spec**, also plan:

- the business problem framing,
- the requirements / scope / non-goals split,
- user/admin lifecycle or rollout sequencing,
- cross-repo or stakeholder boundaries,
- whether a later breakdown into engineering child specs is likely.

### Extra planning requirements for Mode B

If the spec mode is **Engineering implementation sub-spec**, also plan:

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

**Spec mode:** <Business / product feature spec | Engineering implementation sub-spec>

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

### Additional required bundle content for Mode B

When the spec mode is **Engineering implementation sub-spec**, extend the bundle with:

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
