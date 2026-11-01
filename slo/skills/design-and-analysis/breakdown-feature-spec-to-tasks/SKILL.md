---
name: breakdown-feature-spec-to-tasks
description: Expand a feature specification overview into standalone engineering sub-specs that detail each slice's core logic, interfaces, data changes and behaviour tests, with a concise dependency-ordered task list.
when_to_use: Use after feature-specifications has written overview.md, or when existing sub-specs need more implementation detail, so an agent can implement and test each slice with limited context.
group: design-and-analysis
kind: skill
source_prompt: analyze/breakdown-feature-spec-to-tasks.md
---

# Breakdown Feature Specification Into Sub-Specs

## Skill summary

- **Name:** `breakdown-feature-spec-to-tasks`
- **Purpose:** Flesh out the feature's sub-steps into implementation-ready sub-specifications.
- **Input:** The family's `overview.md` from `feature-specifications`, any existing sub-specs, the implementation repository and applicable conventions.
- **Primary output:** One standalone, detailed sub-spec per cohesive sub-step, using the numbered, table-led template below.
- **Supporting output:** A short `task-list.md` linking the sub-specs in dependency order and identifying safe parallel implementation.
- **Group:** `design-and-analysis`
- **Kind:** `skill`

## Examples

- “Detail the sub-steps in this overview so an agent can implement each one.”
- “Flesh out these sub-specs with interface contracts, core logic and behavioral tests.”
- “Split this solution into small sub-specifications and show their implementation order.”

Use the reusable template below as the presentation model: status callout, compact metadata table, numbered sections, focused ownership/schema/contract tables, core logic, files and handoff, and acceptance and tests with a definition of done.

## Other Relevant Skills

- [`feature-specifications`](../feature-specifications/SKILL.md) — writes the `overview.md` this skill consumes
- [`feature-specification-verification`](../feature-specification-verification/SKILL.md) — reviews the whole family after this skill; REVISE findings on sub-specs come back here
- [`solution-design`](../../coding/solution-design/SKILL.md)
- [`coding-rules`](../../coding/coding-rules/SKILL.md)
- [`naming-and-clarity`](../../coding/naming-and-clarity/SKILL.md)
- [`ubiquitous-language`](../ubiquitous-language/SKILL.md)

## Guidance

### 1. Treat this as specification detailing

This skill sits between the concise overview (`overview.md`) and implementation:

> Overview → standalone engineering sub-specs → family verification → implementation and tests.

The overview explains **what the feature does and its overall shape**. Each sub-spec explains **exactly how one cohesive part should behave**, which existing code owns it, its interface contracts and how to verify the result.

Perform two connected operations:

1. Identify the sub-steps and their dependencies. Reuse existing sub-spec boundaries when they remain cohesive.
2. **Do the main work:** expand each sub-step into a self-contained engineering specification.

Do not stop at a decomposition, dependency graph, task checklist or assignment brief. These are navigation aids, not substitutes for the sub-specifications. Most of the useful detail belongs in the sub-specs, not the index.

**This is documentation authoring, not execution.** Do not implement code, run the generated work, publish externally or spawn agents unless separately authorized. Identifying parallel implementation does not authorize parallel execution.

Keep the supplied product decisions. Do not rewrite the overview or redesign the feature merely to simplify decomposition. Surface a required contract change explicitly.

### 2. Establish sources and conventions

Resolve:

- Overview path and explicit user corrections.
- Existing sub-specifications and their numbering.
- Implementation repository/worktree and relevant application roots.
- Output directory and repository document conventions.
- Referenced designs, decisions and relevant evidence.

Do not confuse a specifications repository with the implementation repository. Infer reliable paths from context; ask for material missing inputs rather than inventing them.

#### Locate the project knowledge base and consult it on demand

Follow `skills/design-and-analysis/locate-knowledge-base/SKILL.md`; discovery is non-blocking.

Before beginning decomposition or sub-specification authoring, resolve the `$SLO_KB_DIR` environment variable, following `design-and-analysis/locate-knowledge-base/SKILL.md`:

- If it names a file (for example `.../KB/Welcome.md` or `index.md`), use that file as the entry point and its parent directory as the KB root.
- If it names a directory, use it as the KB root and open `Welcome.md`, `index.md` or `README.md` inside it, in that order.

From the entry point, locate the relevant project using the supplied project name, repository and feature context. Read enough project overview/context to orient the work. Do not assume a directory name, substitute the skills directory or hard-code a local KB path; ask when the project match is ambiguous.

The knowledge base is a **source of truth** for documented project context, terminology, business rules, architecture, integrations and decisions. You are free to navigate it on demand on **any subject** throughout task breakdown and specification generation—not just at initial discovery or for documents already linked by the overview.

- Search and follow relevant project, shared and cross-project references whenever a question arises about ownership, schemas, interfaces, core logic, dependencies or acceptance behavior. Return as often as needed; no separate permission or fixed reading sequence is required.
- Read selectively for the question at hand rather than loading the entire KB. Carry the relevant conclusions into the owning sub-spec and cite the KB file/page and section in its sources or beside the supported contract.
- Distinguish documented truth from verified current implementation. Continue inspecting actual code and interfaces under §3; KB documentation alone does not prove live schema, deployed behavior or executed tests. Surface conflicts with code, the overview or explicit user corrections instead of silently inventing a resolution. Explicit user constraints and corrections take precedence.
- If `$SLO_KB_DIR` is unset, inaccessible, or the project cannot be located, do not stop. Report the limitation (which paths were checked), ask once for the root or project location, and continue detailing with verified sources. Record missing KB-dependent decisions as blockers and do not mark affected sub-specs READY. Never imply the KB was consulted when it was unavailable.

#### Discover the active skills

- Resolve `SLO_SKILL_DIR` or `SLO_SKILLS_DIR`. If both point to different locations and the active root is unclear, surface the conflict.
- Read the active index and locate the applicable skills. Do not hard-code home directories or installed package versions.
- Read coding rules, code-design principles, naming-and-clarity, ubiquitous-language and specification-authoring guidance.
- Read applicable application structure, domain, application-service, controller, worker, migration and configuration conventions.
- Read test-verification-policy and the relevant language/component test recipes.
- Read repository instructions, README, local rules and test setup.

#### Convention skills by language and layer

Paths are relative to `$SLO_SKILLS_DIR`. Start with the language gateway; use `engineering/engineering-routing/SKILL.md` to select a small sufficient set when the feature spans languages. Always read `coding/test-verification-policy/SKILL.md`. Read every layer the sub-spec touches and list them under **2.2 Skills**.

**Python** — gateway `languages/python/python-conventions/SKILL.md`; all paths under `languages/python/`:

- application services → `build-application-services/SKILL.md`
- domain features → `build-domain-features/SKILL.md`
- FastAPI routers → `build-routers/SKILL.md`
- middleware → `build-middleware/SKILL.md`
- event handlers → `build-event-handlers/SKILL.md`, `build-partitioned-events/SKILL.md`
- Celery workers → `build-celery-workers/SKILL.md`
- DBOS workflows / schedulers → `build-dbos-workflow-orchestration-pattern/SKILL.md`, `build-schedulers-tasks-with-dbos/SKILL.md`
- LangGraph agents / tools → `build-react-agent-with-langgraph/SKILL.md`, `build-agent-tools/SKILL.md`, `graph-gateway-invoke-convention/SKILL.md`
- API clients → `build-clients/SKILL.md`
- API docs → `build-api-documentation/SKILL.md`, `generate-swagger-documentation/SKILL.md`
- ClickHouse → `build-clickhouse-features/SKILL.md`
- migrations → `setup-alembic/SKILL.md`
- dependencies / tests → `setup-dependencies-and-tests/SKILL.md`, `test-app-services/SKILL.md`, `test-controllers/SKILL.md`, `test-domain-services/SKILL.md`
- always-on style → `application-structure/SKILL.md`, `named-arguments-and-type-hints/SKILL.md`, `method-docstrings/SKILL.md`, `coding/declarative-method-structure/SKILL.md` (shared)

**Go** — gateway `languages/go/go-conventions/SKILL.md`; all paths under `languages/go/`:

- application services → `go-build-application-services/SKILL.md`
- domain features → `go-build-domain-features/SKILL.md`
- HTTP handlers / middleware → `go-build-http-handlers/SKILL.md`, `go-build-middleware/SKILL.md`
- auth / security → `go-auth-security/SKILL.md`
- events → `go-build-event-handlers/SKILL.md`, `go-build-partitioned-events/SKILL.md`
- workers / schedulers / workflows → `go-build-workers/SKILL.md`, `go-build-schedulers/SKILL.md`, `go-build-workflow-orchestration/SKILL.md`
- runtime lifecycle → `go-build-lifecycle/SKILL.md`
- API clients / TCP / TUIs → `go-build-clients/SKILL.md`, `go-build-tcp-codec/SKILL.md`, `go-build-tuis/SKILL.md`
- ClickHouse → `go-build-clickhouse-features/SKILL.md`
- API docs / response envelope → `go-recipe-api-documentation/SKILL.md`, `go-recipe-api-response-conventions/SKILL.md`
- migrations → `go-recipe-database-migrations/SKILL.md`
- CLI configuration / modules → `go-recipe-cli-configuration/SKILL.md`, `go-recipe-modules-and-imports/SKILL.md`
- dependencies / tests → `go-recipe-setup-dependencies-and-tests/SKILL.md`, `go-test-handlers/SKILL.md`, `go-test-application-services/SKILL.md`, `go-test-domain-services/SKILL.md`, `go-test-orchestration/SKILL.md`, `go-test-lifecycle/SKILL.md`
- always-on style → `go-declarative-method-structure/SKILL.md`, `go-recipe-code-test-loop/SKILL.md`

**TypeScript** — gateway `languages/typescript/typescript-conventions/SKILL.md`; all paths under `languages/typescript/`:

- application structure → `typescript-application-structure/SKILL.md`
- domain features → `typescript-build-domain-features/SKILL.md`
- routers / middleware → `typescript-build-routers/SKILL.md`, `typescript-build-middleware/SKILL.md`
- auth / security → `typescript-auth-security-patterns/SKILL.md`
- events / LangGraph → `typescript-build-event-handlers/SKILL.md`, `typescript-build-langgraph/SKILL.md`
- API clients → `typescript-build-clients/SKILL.md`
- API docs / response envelope → `typescript-build-api-documentation/SKILL.md`, `typescript-api-response-conventions/SKILL.md`
- dependencies / tests → `typescript-setup-dependencies-and-tests/SKILL.md`, `typescript-test-controllers/SKILL.md`, `typescript-test-app-services/SKILL.md`, `typescript-test-domain-services/SKILL.md`
- always-on style → `typescript-named-arguments-and-type-hints/SKILL.md`, `typescript-declarative-method-structure/SKILL.md`, `typescript-method-docstrings/SKILL.md`

**Vue** — the relevant `frontend-vue/` files, starting with `frontend-vue/vue-coding-conventions/SKILL.md` and `frontend-vue/build-vue-components/SKILL.md`.

Carry the relevant constraints into each sub-spec. “Follow the conventions” alone is insufficient. Do not reproduce the whole skills library or copy unrelated fixture/framework examples.

Explicit user constraints and repository-specific rules take precedence over generic examples. Preserve an explicitly authorized exception; do not silently restore a superseded design. Report genuinely conflicting requirements and missing required guidance.

### 3. Gather code context and consolidate ownership

Before detailing a sub-step, trace its behavior through the current code:

> Entry point → application service → domain owner → persistence or external boundary.

Read the actual callers, writers, schemas, public interfaces and representative tests. Check registration, configuration and lifecycle owners where relevant.

For each responsibility, classify the proposed work:

| Finding | Specification action |
|---|---|
| Already implemented | Reuse the verified interface |
| Partly implemented | Extend the existing owner |
| Duplicated or fragmented | Specify consolidation and affected callers |
| Adjacent but different responsibility | Define a clear boundary |
| Absent | Specify the new entity/service and why it is needed |
| Not verifiable | Record the limitation; do not claim it exists |

Confirm cited `path:symbol` references by opening them. Mark proposed files and interfaces **new**. Treat historical documents as context, not proof of current behavior.

**Consolidation is required specification work:**

- Do not create a parallel domain, reducer, validator or state writer for an existing responsibility.
- Specify the current owner, the extension and the callers that must change.
- If replacement is necessary, include caller migration and removal of redundant code.
- Sequence replacement before or with deletion; avoid unexplained dual writers.
- Keep unrelated cleanup outside the feature.

Place relevant findings beside the behavior they explain in the owning sub-spec. Do not create a large research document that every implementing agent must read.

#### Duplicate-code check

Before specifying any new artefact, search by behaviour, not by name, for existing work that does the same job wholly or partly:

- **Data structures:** models, DAOs, schemas, DTOs, enums, configuration.
- **Code:** helpers, validators, queries, serializers.
- **Functionality:** services, workers, routes, clients.

Record each finding in the owning sub-spec, under **3. Ownership and interfaces**:

| Proposed artefact | Existing owner (path:symbol) | Overlap | Consolidation | Resulting single owner |
|---|---|---|---|---|
| `<proposed name>` | `<path:symbol>` or "No existing owner found" | duplicate / partial / adjacent / none | compose / encapsulate / extend owner / delete-and-replace | `<one owner>` |

- Consolidate by composition or encapsulation so each responsibility has exactly one owner (single responsibility, DRY).
- Name the call sites to repoint and the code to delete, and assign them to files in **8.1 Owned files**.
- "No existing owner found" is an explicit finding, not an empty row.
- An unresolved duplicate is blocking: the sub-spec stays **BLOCKED** or **DRAFT** and cannot be marked READY.

#### Cohesion over line-level DRY

DRY must not destroy cohesion. Consolidate duplicate *responsibilities*, not lines that merely look alike.

- Keep tightly coupled steps in one method so the core logic reads as one unit: a query and its terminating flush or commit, open and close, acquire and release, validate then write.
- Extract only a meaningful, named responsibility. Never specify a separate method for a flush or commit merely to avoid repetition.
- The caller that owns the transaction commits. A domain method flushes its own write so the result is visible, and returns.

Illustrative only. A guarded projection update in a domain service:

```python
# Avoid: the flush is pulled away from the write it completes,
# so the reader must jump to a helper to see the write land.
@staticmethod
async def apply_access_projection(
    *,
    document_id: UUID,
    is_visible: bool,
    access_version: int,
    db_session: AsyncSession,
) -> bool:
    result = await db_session.execute(
        DocumentService._build_projection_update(
            document_id=document_id, is_visible=is_visible, access_version=access_version
        )
    )
    await DocumentService._flush(db_session=db_session)
    return result.scalar_one_or_none() is not None


# Prefer: the guarded update, its flush and the outcome read as one unit.
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

### 4. Identify the sub-specifications

Use existing sub-steps when possible. Split or combine them only to improve cohesion and limited-context implementation.

A good sub-spec owns **one meaningful outcome**, its production changes and its verification. It may span a migration, domain and application service when these are needed to deliver that outcome.

- Each sub-spec groups one vertical piece of functionality end to end; too many unrelated components in one sub-spec make it hard to read, validate and implement.
- Keep core rules and their tests together.
- Prefer a small vertical behavior over one document per architectural layer.
- A shared foundation is appropriate when it has a concrete reusable contract and database-level proof.
- Separate independent collaborators only when their inputs, outputs and ownership are clear.
- Do not produce one sub-spec per file or method.
- Do not defer all tests or unresolved core logic to a final integration sub-spec.

**Limited-context test:** An implementing agent should be able to work from one sub-spec, a short code-reading list, applicable conventions and the relevant prerequisite contract excerpts. It should not need chat history, the whole feature family or another agent's assumptions.

Each behavior in the overview needs an owning sub-spec and a verification scenario. Preserve exact names, state values and architecture decisions across documents.

### 5. Write a standalone sub-spec for each sub-step

Write for an engineer with no prior application context. Start with readiness and compact source/dependency metadata, then the outcome, a bounded reading list and ownership/interfaces before data and core logic. Explain current-to-proposed behavior beside the relevant owner. Stay concise and keep the document visually pleasing to read.

Use short sections, tables, numbered logic and a small diagram where it reduces reading effort. Expand ambiguous decisions—not routine boilerplate. Do not restate the complete overview in every sub-spec.

#### Required sub-spec structure

Use the numbered document shape below, not an unnumbered generic template. Apply the readable-representation rules in §7 throughout, including acceptance, ownership and blockers. Prefer compact tables for fields and interface summaries, short bullets for guarantees, and numbered steps for algorithms. Use focused typed snippets when they clarify a contract; do not force code blocks where a table is clearer.

```markdown
# <ID> — <Concrete sub-step behavior>

> [!warning] Status: **BLOCKED** — <material blocker and affected scope>
> <Decision owner / required answer; distinguish unresolved policy from authorized engineering work.>

| | |
|---|---|
| **Sources** | [Overview — <section>](overview.md#<section>) · [Task list](task-list.md#<row>) |
| **<Application> (<alias>)** | `<verified implementation root>` |
| **<Build / migration wrapper, if relevant>** | `<verified wrapper root>` |
| **Depends on** | <linked prerequisite IDs and contracts, or none> |
| **Hands off to** | <linked consumer sub-specs, or none> |
| **Out of scope** | <explicit non-goals> |

---

## 1. Outcome

<Why this sub-step exists and its observable result.>

> [!important] Invariant
> <The central guarantee this sub-step must preserve.>

---

## 2. Read first

### 2.1 Existing code (<alias>-relative)

| Path | Symbols |
|---|---|
| `<verified path>` | `<relevant symbols and current responsibility>` |

### 2.2 Skills

Skill root **S** = `<resolved active skill root>`

- `<applicable skill paths relative to S>`

### 2.3 Rules

- <Concrete consequences of repository conventions and explicit user decisions.>
- <Compatibility requirements and existing behavior that must remain unchanged.>

---

## 3. Ownership and interfaces

<Identify proposed additions versus verified existing interfaces. Explain reuse,
extension or consolidation and the current-to-proposed change.>

> [!note] Transaction / resource rule
> <Caller ownership, commit/rollback or lifecycle contract, where applicable.>

| Owner / path | Input → output | Contract |
|---|---|---|
| **NEW / CHANGED / EXISTING** `<path>` · `<symbol>` | <named typed inputs and outputs> | <concise responsibility and guarantee> |

**Boundaries**

- <Authoritative versus derived state and which owner may write each.>
- <Collaborator/caller boundaries, consumed prerequisite semantics and compatibility.>
- <Link to detailed contracts below when the summary cannot hold the full interface.>

---

## 4. Schema contract

### 4.1 `<entity / table / data shape>`

<Domain meaning and authoritative owner.>

| Column / field | Type / default | Notes |
|---|---|---|
| `<name>` | <type, nullability, default> | <identity, association or validation rule> |

**Constraints and indexes**

- <Keys, uniqueness, checks and indexes with their purpose.>

**Rules**

- <Retention/privacy rules, immutable evidence and unknown-value semantics.>
- <Migration, backfill and rollout obligations; detail ordering in Core logic.>

---

## 5. Core logic

### 5.1 <Concrete behavior>

<Preconditions, trigger and initial state.>

1. <Exact decision / guard and branch outcome.>
2. <Ordered writes and external effects, transaction and rollback boundaries.>
3. <Observable result and effects that must never occur.>

- <Failure, retry, dedupe, concurrency, cancellation and restart rules as relevant.>
- <Use further named subsections for distinct algorithms and migration sequencing.>
- <Add a small state/flow diagram only when it clarifies the behavior.>

---

## 6. <Feature-specific detailed contract>

### 6.1 `<Named DAO / operation / protocol>` — <owning participant>

<Brief introduction and target path/status; typed signature or field table as useful.>

| Field | Type / requiredness | Meaning |
|---|---|---|
| `<name>` | <type and optional semantics> | <contract> |

- <Validation, defaults, errors, provenance and ownership guarantees.>
- <Precise prerequisite contract excerpts, linked to their authoritative owner.>

### 6.2 `<Guarded operation>`

<Caller/trigger, typed inputs/result, ordered guard algorithm and side effects.>

| Case / outcome | Result |
|---|---|
| <condition or named outcome> | <returned value, persisted effect and forbidden writes> |

---

## 7. <Additional owned contract needed by consumers>

<Use a focused section when needed: read indexes, query contract, recovery,
external protocol or another feature-specific responsibility. Name its consumers.>

---

## 8. Files and handoff

### 8.1 Owned files

| Change | Path |
|---|---|
| NEW / CHANGED / REMOVED / GENERATED | `<path>` — <responsibility> |

**Not edited:** <shared files owned elsewhere and explicit non-owned areas>.

- <Local implementation order, registration and caller migration/removal.>
- <Prerequisites and safe parallel work, including shared-file ownership.>

### 8.2 Exports

<Delivered schema/interfaces and exact transaction or resource guarantees.>

| Consumer | Consumes |
|---|---|
| [<ID>](<sub-spec filename>) | <exported contract and section link> |

> [!important]
> <Critical handoff constraint, such as retaining one authoritative writer.>

---

## 9. Acceptance and tests

<Safe synthetic inputs, disposable environment and the real entry boundary.
How committed results are read back, using fresh sessions where applicable.
Cite reusable fixtures as references, not as executed evidence.>

| ID | WHEN / action | THEN / forbidden outcome | Test (level · file::name) |
|---|---|---|---|
| **A1** · <overview behavior ID, if present> | <preconditions and real entry/action> | <observable/persisted result and prohibited effects> | <behaviour · `tests/...::test_...`> |

**Run:** `<verified test command and working directory>`

### Definition of done

- [ ] <Material blocking decisions resolved, if any>
- [ ] <Required production/schema/interface changes landed>
- [ ] <Actual acceptance outcomes A1–An recorded during implementation>
- [ ] <Required regression/automated checks passed, if assigned>

> [!note]
> <Verification limits and the sibling sub-spec that owns the remaining journey.>
```

**Adaptation rules**

- The status above is illustrative. Use `[!note] Status: **READY**` when the specification is complete, `[!note] Status: **DRAFT**` while incomplete, or `[!warning] Status: **BLOCKED**` with the actual blocker. READY never means implemented or verified in production.
- Keep the opening metadata, numbered sections, focused subsections, separators and final acceptance/checklist shape. Use callouts sparingly for real invariants, warnings and ownership rules.
- Preserve `Outcome`, `Read first`, `Ownership and interfaces`, `Core logic`, `Files and handoff`, and `Acceptance and tests`. `Read first` and `Ownership and interfaces` are the sub-spec's current-state record: what exists today, what is stale in earlier documents, and what changes. Tailor schema and detailed-contract headings to the actual feature. Omit optional sections that have no content and renumber consecutively; do not invent a read-index section, schema change or nine-section quota.
- Fully specify types, requiredness, defaults, errors and guards. Tables summarize; complex semantics belong in focused subsections, not dense cells.
- Put material open questions and their decision owners beside the affected contract and summarize them in the status. Do not mark an affected sub-spec READY.
- Keep the implementation definition of done unchecked while authoring. Specification readiness and implementation acceptance are different claims.
- Preserve verified existing IDs and filenames. For a new family use `<NN>.a.1`, `<NN>.a.2`, … in titles and `<NN>.a.n-<slice>.md` filenames, where `<NN>` is the feature folder number. Use the next letter (`<NN>.b.n`) for a later phase of the same feature.

### 6. Detail core logic completely; leave surroundings as interfaces

**Core logic must be specified, not delegated to the implementer's imagination.**

For each relevant behavior, define:

- Validation, decision precedence, guards and early exits.
- Legal state transitions and the exact conditions for each.
- Identity matching, ambiguity and unknown-value semantics.
- What is created immediately, enriched later, merged, replaced or retained.
- Transaction owner and writes that commit or roll back together.
- External side effects and recovery when they cannot be atomic with storage.
- Deduplication keys, attempt identity, finite retry rules and exhaustion.
- Concurrent branch start/join, stale-result rejection and cancellation ownership.
- Partial-failure persistence, restart recovery and cleanup.
- Privacy and authorization boundaries.

Use numbered algorithms, decision tables or precise pseudocode. A full production implementation is not required. Exact SQL or a short code fragment is useful only when it resolves important query or concurrency semantics.

**Do not write:** “handle failures,” “merge appropriately,” “follow the overview,” or `TODO` where a core decision belongs.

**Surrounding code stays at interface level.** Constructors, serializers, controllers, workers and external adapters need typed contracts and lifecycle obligations, not copied method bodies. If a controller or worker contains a material decision, specify that decision as core behavior rather than hiding it behind an interface.

Every interface identifies:

| Contract element | Detail |
|---|---|
| Caller and trigger | Who invokes it and when |
| Input | Names, types, validation, defaults and optional semantics |
| Result | Returned value and observable state change |
| Errors | Rejection, unavailable dependency and retry behavior |
| Ownership | Transactions, sessions, resources and cleanup |
| Guarantees | Ordering, idempotency, concurrency and forbidden effects |

Use project naming and typed keyword-argument conventions. Put the target file path and **new/changed/existing** label before each code snippet. Never present a proposed API as verified existing code.

#### Example of the required detailing

**Overview statement:** “Retry failed processing a finite number of times.”

**Sub-spec must establish:**

- Which owner records failure and reserves the next attempt.
- Whether the limit includes the first attempt; where the count persists.
- Which failures are eligible and when the retry becomes due.
- The atomic eligibility check and increment.
- How resubmission differs from a new processing attempt.
- How stale completions are rejected and completed evidence is preserved.
- The state and absence of new work after exhaustion.
- Behavioral scenarios proving those outcomes.

Do not invent the retry count if it is a product decision. Record it as a blocker; detail everything that does not depend on that choice.

### 7. Keep sub-specs self-contained, readable and consistent

#### Readable representation is part of contract completeness

Write like a concise technical book: clear headings, simple language and one concept per block. Apply these rules to **every section** of each sub-spec and its index.

- Introduce a contract briefly, show a focused typed snippet when it makes the structure clearer, then explain its meaning and guards in a few short bullets.
- Separate data shapes from persistence changes, state transitions and numbered algorithms. Do not bury concurrency, rollback, provenance or error rules in field lists.
- Ban inline serialized schemas and long semicolon-packed contract paragraphs. Split dense numbered paragraphs into steps and supporting bullets.
- Use tables for compact comparisons, alternatives, states and decisions. If cells contain several concepts or paragraphs, move the detail under a heading rather than building a wall of prose.
- Label snippets **new/proposed**, **changed** or **existing**, with their target paths. Use known repository types and naming. Label pseudocode explicitly; do not present incomplete sketches as executable code.
- Do not invent types, defaults or policy to shorten an example. Preserve every substantive contract, guard, error, blocker, provenance rule and ownership requirement. Unknowns remain explicit.
- Keep complete core logic and self-contained prerequisite contracts. Readability is not permission to omit logic, weaken verification or replace it with boilerplate.

For example, instead of an inline field list followed by several semicolon-separated rules:

**Proposed — `<target-path>`; language-neutral contract pseudocode (not executable):**

```text
Result
  outcome: accepted | stale
```

- `accepted` means the guarded write committed.
- `stale` means the guard rejected the write; nothing changed.

This illustrates presentation only, not a reusable outcome policy. Real documents must retain their actual types, outcomes and complete guards, with the guard algorithm in its own section.

#### Self-contained ownership and consistency

Each sub-spec includes the precise prerequisite semantics its implementation needs, with a link to the authoritative contract owner.

- Repeat essential interface facts, not entire sibling documents.
- Keep one authoritative owner for changing each shared contract.
- State which contract is inherited and which change this sub-spec introduces.
- Verify producer and consumer names, types, errors and state meanings agree.
- Update affected consumers when a contract changes during detailing.
- Preserve existing numbering and documents when refining an existing family; do not create a second competing family.

Classify unresolved items:

- **Local implementation choice:** resolve from inspected code and conventions, with a brief rationale.
- **Material design decision:** identify the question, owner and affected sub-specs; do not silently choose new behavior.
- **External prerequisite:** name needed access, source schema or environment and how to verify it.

A sub-spec is not implementation-ready while its core contract depends on an unanswered question. It can still be authored as **BLOCKED** with the completed portions intact. Unaffected sub-specs may remain ready.

### 8. Specify behavior-first acceptance in the template format

End each sub-spec with `Acceptance and tests`: a short safe-environment paragraph, an `ID | WHEN / action | THEN / forbidden outcome | Test` table and a `Definition of done` checklist. Number scenarios `A1`, `A2`, etc.; link existing overview behavior IDs when available, without inventing them. State the real entry/action, the observable or committed result and the forbidden effects, with the setup and read-back needed to check each one.

**Test priority**, following [`test-verification-policy`](../../coding/test-verification-policy/SKILL.md):

1. **Behaviour tests first.** Drive the slice's outcome end to end from its real entry point through the application service and real persistence. Assert the observable and stored result and what must not happen. One behaviour test may prove several cooperating decisions.
2. **Unit tests for critical computation.** Add focused unit tests only for critical methods with complex computation (parsing, matching, scoring, state rules) where a behaviour test cannot cover the cases economically.
3. **No elaborate harness.** This is how large features are tested without an elaborate Playwright, browser or multi-service integration rig. Reuse the repository's test client, fixtures and disposable database.

Name the test file, test name, level and run command for every A-row. If an environment is unavailable, give a manual read-back check and mark the automated gap explicitly; a manual check never silently replaces a required test.

For Python tests, use ordinary pytest with clear behaviour-driven docstrings, not a BDD framework. For other stacks, use the repository's native test conventions. Do not introduce Gherkin, step registries or scenario runners. Writing scenarios does not authorize running them.

A focused rule scenario can read:

```python
"""WHEN      call_assignment.type == CUSTOMER
AND WHEN  there are no reference phone numbers
THEN      it should return True
"""
```

A journey scenario must state persisted outcomes:

```python
"""WHEN      a stored email is processed successfully
AND WHEN  its initial observation already exists
THEN      the same observation contains the accepted interpretation
AND THEN  Customer history contains one entry for this email
AND THEN  reprocessing does not create another observation or history entry
"""
```

These illustrate scenario descriptions; use the actual feature's names and rules in generated sub-specs.

#### Test from a meaningful boundary to an observable result

| Boundary | Action | Required proof |
|---|---|---|
| Application service → database | Invoke the real service with production-shaped inputs | Read stored records back and assert state plus relevant absence of writes |
| Controller → database | Call the real route with appropriate authentication | Response and database effects; do not mock away the application service |
| DBOS initiation → final state | Submit/invoke the supported real workflow path and await completion | Final persisted outcome, not merely an enqueue call |
| Domain/pure rule | Exercise a dense invariant or decision table | Distinct behavior that journey tests do not prove economically |

For a thin worker, an application-service test with the worker's exact inputs plus a registration/delegation check may satisfy the project's wiring policy. Do not call this DBOS durability proof. Engine retry, scheduling or restart claims require appropriately scoped real-runtime evidence, or an explicit verification blocker.

#### Keep tests effective and small

- Use real disposable databases/files; never mock persistence to claim stored-state coverage.
- Keep the application-service/domain/persistence path under test real.
- Replace external dependencies only at approved injection boundaries, following the active test policy.
- Reuse existing fixtures, factories and test clients. Add only a small justified fixture or injection seam when missing.
- Read results back. Use committed inputs and fresh sessions where cross-session behavior requires them.
- Do not infer a durable commit from a mutated object or test-managed flush.
- Await bounded completion conditions; use controlled clocks/synchronization instead of arbitrary sleeps.
- Obey owned-database, synthetic-data and cleanup safeguards.

Cover meaningful outcomes: success, rejection, missing or ambiguous data, failure cutoff, rollback, duplicates, retry exhaustion, stale results and cancellation where relevant. Assert what must happen **and what must not happen**.

Do not generate a test per method, duplicate every assertion across layers or use fewer lines as a reason to weaken coverage.

Each sub-spec includes its own verification requirements. A final cross-sub-spec check covers remaining integration risks; it does not postpone all testing until the end.

### 9. Add a concise sub-spec index and implementation order

**Schema first:** Always place migrations and schema development before the sub-steps that consume the affected data. Where storage changes are required, the first implementation sub-spec or group must cover the schema, migrations, constraints, defaults and any required backfill, together with their verification. Make dependent application services, controllers and workers explicitly depend on this foundation. Do not defer schema work to an integration sub-spec. If no schema change is needed, state that briefly rather than inventing migration work. Preserve safe expand/backfill/contract deployment sequencing; destructive cleanup migrations must wait until old consumers have been migrated.

After fleshing out the sub-specs, summarize their dependencies. This list is secondary to the specifications.

Follow repository numbering/layout. If none exists, use:

```text
<NN>-<feature>/
├── overview.md               # from feature-specifications
├── task-list.md              # sub-spec links and dependency order
├── <NN>.a.1-<slice>.md       # standalone engineering sub-spec
├── <NN>.a.2-<slice>.md       # standalone engineering sub-spec
└── <NN>.a.3-<slice>.md       # standalone engineering sub-spec
```

Do not create a separate task document that repeats each sub-spec. The list points directly to the authoritative sub-specifications.

| Sub-spec | Outcome | Depends on | Can implement alongside | Readiness |
|---|---|---|---|---|
| `<ID and link>` | `<observable result>` | `<IDs/contracts>` | `<IDs or none>` | READY / BLOCKED / DRAFT |

Include a small dependency diagram if useful, a short coverage map from overview behaviors to sub-specs, and material blockers. Avoid assignment metadata, estimates or operational ledgers unless requested.

**Parallel implementation is safe only when:**

- Prerequisite implementations and verified contracts are available to both agents.
- Neither relies on the other's unfinished implementation or unsettled semantics.
- Shared production files, migration ordering, registries, configuration and fixtures have an explicit owner.
- Writes and responsibilities do not conflict.

Different files or worktrees alone do not prove independence. Assign shared edits to one sub-spec or serialize the work. Distinguish dependencies required to **author the specification** from dependencies required to **implement it**: sub-specs can be detailed before predecessor code exists, using agreed contracts.

Validate the index and all linked sub-spec sections against §7 before reporting readiness. Check dense table cells, inline field lists and long numbered paragraphs as well as code blocks. Use short tables for navigation and comparisons; keep full contracts in focused, readable sections without losing dependency or ownership details.

**READY** describes specification completeness, not completed implementation or permission to skip prerequisites.

### 10. Review the detailed specification family

Before saving, check:

- [ ] The primary deliverables are substantive sub-specs, not a task plan with thin descriptions.
- [ ] Each follows the included template format: ID/title, accurate status callout, compact metadata, consecutively numbered sections, focused tables/bullets, files and handoff, and acceptance and tests with a definition of done.
- [ ] New families use `<NN>.a.n-<slice>.md` naming; existing IDs/layout are preserved. No unrelated feature policy, local path or fixed installed skill root was copied from an example.
- [ ] Acceptance scenarios have stable A-numbered IDs, meaningful actions, observable results and forbidden effects. Each names its behaviour test (or a justified unit test for complex computation) and run command; no elaborate harness is required.
- [ ] Implementation acceptance checkboxes remain unchecked unless supported by actual implementation evidence; authoring completeness is reported separately.
- [ ] Every sub-step explains current behavior, proposed behavior and the reason for the change.
- [ ] Each includes entities, backing data, interfaces, complete core logic and behavioral verification.
- [ ] Existing owners are reused or deliberately consolidated; caller migration/removal is assigned.
- [ ] Each sub-spec has a duplicate-code table covering every proposed artefact, with "No existing owner found" stated explicitly; no sub-spec with an unresolved duplicate is marked READY.
- [ ] Tightly coupled steps (query and flush, open and close, validate then write) stay in one method; nothing trivial was extracted only to avoid repetition.
- [ ] Each sub-spec's **2.2 Skills** lists the matching language gateway and layer convention skills.
- [ ] No essential decision is left to “follow the overview” or implementer guesswork.
- [ ] One sub-spec can be implemented with its bounded context and prerequisite contracts.
- [ ] Shared contracts agree across producers and consumers.
- [ ] Every section, including the index, verification and blockers, follows §7: focused contracts, short explanatory bullets, compact tables and numbered algorithms rather than serialized schemas or semicolon-packed prose.
- [ ] Snippets identify status and target path, reuse known repository types, and clearly label pseudocode; no types or defaults were invented for presentation.
- [ ] Editorial simplification retained all guards, errors, provenance, ownership, blockers and complete core logic; reviewers check meaning as well as layout.
- [ ] Every overview behavior maps to an owning sub-spec and an observable verification scenario.
- [ ] Migrations and schema development are placed first when required; consumers depend on the verified schema foundation, and destructive cleanup respects compatibility.
- [ ] Dependency ordering is acyclic and proposed parallel work has no ownership conflicts.
- [ ] Material unknowns are explicit; affected sub-specs are not marked READY.
- [ ] `$SLO_KB_DIR` was resolved (a file value used as the entry point, a directory value searched for `Welcome.md` / `index.md` / `README.md`) and project context consulted before detailing, or its unavailability and affected blockers are explicit; relevant KB facts and decisions are cited, with conflicts surfaced.
- [ ] Paths, symbols, relative links, commands and fixtures are verified or clearly marked unverified.
- [ ] Documenting scenarios is not presented as executed tests, independent review or implementation completion.

Check Markdown/code fences and diagrams where tooling is available. Report checks actually performed and any render limitations. Preserve unrelated files and the overview unless its revision was explicitly requested.

### 11. Report the result

Report:

- The detailed sub-spec paths and what each now specifies.
- The supporting index and implementation dependency order.
- Important core decisions clarified and existing owners consolidated.
- Blocking questions and document checks performed.

Then hand the whole family (`overview.md`, sub-specs, `task-list.md`) to [`feature-specification-verification`](../feature-specification-verification/SKILL.md). Its REVISE findings on a sub-spec or the task list return to this skill; findings on `overview.md` return to `feature-specifications`. Material contract changes require renewed verification of the affected documents.

Stop after specification authoring. Creating or updating this skill does not execute it against a feature or start implementation.
