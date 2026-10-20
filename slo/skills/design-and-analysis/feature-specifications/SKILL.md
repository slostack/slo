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
Specification Development workflow, load `skills/orchestration/workflows/specification-development.md`.
That workflow sequences this skill, independent verification, then task breakdown.
Skim `feature-specification-verification` and `breakdown-feature-spec-to-tasks`
unless the user asks otherwise; `gather-feature-context` remains an on-request
context companion. Do not recursively invoke this skill through the old hooks.

## Slo defaults for request and specification artifacts

**Read the prerequisite design references before drafting.** Read [coding rules](../../coding/coding-rules/SKILL.md) and [code design principles](../../coding/code-design-principles/SKILL.md) before authoring a feature specification. When focused preimplementation design is useful, consult [solution design](../../coding/solution-design/SKILL.md) as an optional companion; it is not mandatory for every feature specification.

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

Identify the local purpose and integration context needed to implement the slice without the parent overview. Link shared contracts to their canonical owners rather than copying them.

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
- graph / gateway invoke convention → `the graph-gateway-invoke-convention recipe`
- API clients → `skills/languages/python/build-clients/SKILL.md`
- API docs / Swagger → `skills/languages/python/build-api-documentation/SKILL.md`, `skills/languages/python/generate-swagger-documentation/SKILL.md`
- ClickHouse features → `skills/languages/python/build-clickhouse-features/SKILL.md`
- Alembic setup → `skills/languages/python/setup-alembic/SKILL.md`
- dependencies / tests → `skills/languages/python/setup-dependencies-and-tests/SKILL.md`
- always-on style → `skills/languages/python/named-arguments-and-type-hints/SKILL.md`, `skills/coding/declarative-method-structure/SKILL.md`, `skills/languages/python/method-docstrings/SKILL.md`, `skills/coding/test-verification-policy/SKILL.md`, `skills/languages/python/application-structure/SKILL.md`

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

### 7 — Plan the reader's route

Plan a short purpose/scope explanation, current → proposed behavior, a useful flow
or dependency diagram, and file-by-file contracts. Introduce unfamiliar terms where
needed, not in a mandatory glossary. Put rationale beside the decision it explains.
For the overview, plan the product journey, boundaries, acceptance and delivery map.
For each child, identify exact owned changes, shared contracts to link, implementation
order, verification commands, and unchanged behavior. Do not plan repeated introductions.

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

**Reader's route:**
- Purpose and scope: <short explanation>
- Current → proposed behavior: <key differences>
- Flow or dependency diagram: <if useful>
- File-by-file contracts: <owning paths and interfaces>
- Shared contracts to link: <canonical definitions and consumer usage>
- Non-obvious algorithms needing bodies: <where signatures are insufficient>
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

**Local context and shared contract links:**
- <local context to explain, or canonical shared definition to link>
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

Every feature requires overview.md and separate standalone engineering sub-specs.
Neither substitutes for the other, including for small features. Retain and check
the complete family when revising one slice. Keep product framing in the overview
and implementation contracts in the children.

### Overview structure

The overview is a feature map, not a combined engineering specification. Explain:

1. What we are building and why.
2. The user or system journey, using a sketch or diagram where useful.
3. Scope, non-goals, ownership and safety boundaries.
4. Delivery map: child specifications and their dependencies.
5. Acceptance, rollout/rollback and current evidence status.

For independent workstreams, link their overviews and separate release gates.
Reconcile stale parent summaries with current child scope and status, without
promoting specification approval to implementation or runtime acceptance.
Keep DTOs, service signatures and detailed algorithms in their owning sub-specs.

### Engineering sub-spec structure

Use this default structure; require the information, not redundant headings:

1. Purpose and scope
2. Current → proposed behavior
3. Design and flow
4. File-by-file implementation contracts
5. Implementation order and dependencies
6. Tests and acceptance criteria

Combine or rename sections when that improves readability. Add Open decisions or
Operational constraints only when needed. Start with what changes, why it matters,
and what the slice owns and excludes. Introduce unfamiliar concepts where needed;
do not narrate every class or helper before showing its definition.

Keep a compact metadata header with current status, owner, update date, parent and
repository/branch when relevant. Preserve the repository's numbered title convention.
Define requiredness, nullability, defaults, bounds and behavior explicitly. Include
unit and functional/integration coverage appropriate to the actual entry point;
mock-only tests do not prove database or transactional behavior.

### File-by-file implementation contracts

Start with an annotated target file tree showing added, changed, moved and removed
files. Use exact repository-relative paths as subsection headings. For each file:

1. State its responsibility and change in one or two sentences.
2. Show the relevant interfaces in syntax-highlighted code using the target language.
3. Explain only behavior and constraints that the declarations do not express.

Use one field per line, explicit types and defaults, complete public signatures,
return types, exact enum/constant values, and imports needed to establish ownership.
Do not replace fields, parameters, enum members, or defaults with ellipses.
Method bodies may be omitted in explicitly labeled interface listings. Include
implementation bodies for non-obvious algorithms, integration seams or ordering
constraints; do not reproduce routine implementations merely to increase detail.
Do not encode classes as semicolon-separated prose or dense table cells, or repeat
a code declaration as a second field inventory. Record errors and resource/transaction
ownership next to the interface. Unresolved material decisions block handoff;
do not silently invent missing contracts during an editorial rewrite.

### Existing behavior versus proposed contracts

For existing behavior, cite actual repository paths and symbols (line references
when useful). Include faithful source excerpts only when they help explain the change;
one citation may support related statements. Do not require a sample per sentence.
For proposed behavior, label code as a proposed interface or implementation and name
its target file. Never imply that proposed code already exists or has been executed.

### Single-source contracts

Define each interface, invariant, algorithm and configuration rule once, with its
owning component. Design explains why; declarations define shape; behavior rules
supply semantics; tests verify the rules; acceptance states observable completion.
Do not restate the complete contract in every section.

A standalone child explains its purpose, owned changes and integration boundaries
without requiring the parent overview. It may link to canonical shared definitions
rather than copying them. Consumers show the relevant import, call signature and
usage; the full shared schema stays with its sole owner. Keep links precise and
check them after restructuring.

### Revision and evidence hygiene

The specification describes the current proposed contract, not its drafting history.
Resolve findings by updating the owning section in place and removing superseded
wording. Preserve findings and resolutions in review reports, not corrective appendices.
Keep workflow IDs, turn/dispatch/retry counters, PRE/POST reports, historical approval
narratives and tool logs outside the specification body. Preserve that evidence in
conversation, PR descriptions or linked review artifacts; do not delete it to shorten
the spec. Keep current status, unresolved decisions and actionable authorization or
safety constraints in the spec. Do not infer runtime evidence from author readiness.

### Presentation rules

Optimize for comprehension, not character count. Use short paragraphs with one main
idea, concrete verbs, descriptive headings and inline code for symbols/paths/literals.
Avoid compressed notation, unexplained abbreviations and section-number shorthand
such as `§`; use descriptive Markdown links. There is no arbitrary word limit.
Remove repetition before removing detail; split responsibilities, not page counts.

- Code: interfaces, schemas, constants and configuration.
- Tables: comparisons, state transitions and compact test matrices.
- Diagrams: dependencies, ownership and transaction boundaries.
- Prose: intent, rationale and exceptions.

Do not put entire schemas or multi-paragraph algorithms into table cells. Diagrams
should replace repetitive explanation rather than add another version of it.

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

The overview owns the full journey; a child briefly identifies its slice. For
non-trivial orchestration show ordered calls, external operations, resource ownership,
commit/rollback boundaries and failure exits. Use a diagram or numbered walkthrough,
not both unless each adds information. Pure helpers need no artificial user journey.
For bugs, explain the symptom, expected behavior and actual divergence with relevant
source references; do not repeat the whole walkthrough under multiple headings.

### `## Code Reference` Rules

Apply the file-by-file contract rules above. Introduce each block with a short
explanation of its purpose; avoid silent code dumps and prose that restates each line.
Use repository conventions: Python keyword arguments, Go context-first calls/named-field
structs, TypeScript options objects; explicit types and real identifiers. Use
Python Google-style docstrings, Go godoc, and TypeScript JSDoc as appropriate.
Document public and important helper contracts, including errors and caller ownership.
Full bodies are conditional on ambiguity, not on a class being central to the feature.

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

- field specifications: target-language declarations, one field per line; prose only for additional semantics
- file paths: `src/path/to/file.py`
- dates: `YYYY-MM-DD` unless the surrounding context requires another format
- IDs: always specify concrete type

**Cross-references:**

- point to explicit headings, file paths, and sibling spec paths
- avoid vague references like "as above" when a precise heading is available

---

### Implementation contract completeness

Read the packaged [granularity sample](../../samples/implementation-details-granularity.md)
before drafting or reviewing non-trivial contracts. It illustrates depth, not a
requirement to reproduce its technology or length.

Every slice must identify exact files, symbols and call sites added, changed, moved,
removed or rewired; current versus target behavior; dependencies and implementation
order; input/output contracts, state, errors, configuration, edge cases and unchanged
behavior. Preserve single ownership and explicitly schedule consolidation/deletions.

Specify exact test files, named cases, fixtures/setup, assertions, required levels,
existing tests to update/remove, scoped verification commands and manual smoke where
needed. "Update the service", "handle errors" and "add tests" are insufficient.
Do not leave material placement, API, behavior, failure or test decisions to inference.
Completeness means complete contracts, not exhaustive routine implementation listings.

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
### Check 1.5 — Readability and semantic preservation audit (mandatory)

Use the Draft presentation rules for both overview and children. Accept combined or
renamed sections when the required information is easy to locate. Do not demand prose
merely to fill a template. Verify purpose, changed files, interfaces, flow, failure
behavior, ownership, dependencies and acceptance can be found quickly.

Check that contracts use production-language syntax and each rule has one authority.
Resolve competing definitions and move historical commentary to evidence artifacts.
Check links and reconcile stale family summaries without overstating approval.

When shortening, compare against the source requirements and prior contract:
- Types, requiredness, nullability, defaults and bounds.
- Validation and cross-field invariants.
- Ordering, atomicity, concurrency and idempotency.
- Errors, cancellation, recovery and resource ownership.
- Security, authorization, operational limits and compatibility/migrations.
- Tests, acceptance coverage and intentionally unchanged behavior.

Record missing context or obstructive organization as **NARRATIVE GAP**, misplaced
artifact roles as **STRUCTURE GAP**, and missing material contracts as critical gaps.
All require correction; absent decorative headings alone are not gaps.

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

### Check 4 — Contract examples audit

Verify every proposed interface is complete and belongs to an exact target file.
Check faithful source citations for existing behavior and explicit labels for target
code. Signatures may omit bodies; fields/defaults/parameters may not be hidden.
Require algorithm bodies only when needed to remove behavioral or ordering ambiguity.

### Shared example expectations

Use realistic identifiers, explicit types, relevant imports and language-appropriate
calls. Follow Python Google-style docstrings, Go godoc, and TypeScript JSDoc. Explain
each block briefly without duplicating its declaration. Check canonical shared links
and consumer usage. Overviews need journeys and delivery maps, not DTO listings.
Record missing or ambiguous examples as **EXAMPLE GAP**, with the exact contract or
algorithm to supply. Do not request full listings solely to make a spec longer.



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
- Missing material contract information is automatic **REVISE**; combined or renamed sections are valid.
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
