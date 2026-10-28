---
name: feature-specifications
description: Write the feature specification overview — what the capability does, who owns each piece of state, the interfaces between modules, and what is still undecided. Standalone engineering sub-specs come next from breakdown-feature-spec-to-tasks.
when_to_use: Use when the operator asks to write or spec out a feature ("write a feature spec for X", "spec out X", "solution design", "identify the domains, entities and interfaces", "explain the flow and how the systems interact"). It produces overview.md of the feature's specification family. Delegate standalone engineering sub-specs and the task list to breakdown-feature-spec-to-tasks; do not write code.
group: design-and-analysis
kind: skill
source_prompt: analyze/feature-specifications.md
---

# Feature Specifications

## Skill summary

- **Name:** `feature-specifications`
- **Description:** The overview of a specification family. It settles the shape of a capability: the plain-language purpose, the domains and their tables, the journeys, the module interfaces and the open decisions, with diagrams wherever a picture explains faster than prose.
- **When to use:** The operator asks for a feature spec, a solution design or approach, or wants domains, entities and interfaces identified. This skill writes `overview.md`; `breakdown-feature-spec-to-tasks` then writes the standalone engineering sub-specs.
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Output:** `<feature-specifications-root>/<NN>-<feature>/overview.md`

## Examples

- "Write a feature spec for importing supplier invoices from the shared mailbox."
- "Spec out reading support emails from a Google Group into the ticketing system."
- "Identify the domain entities, their tables and the interfaces between the systems for this feature."
- "I want to agree the design before we detail the sub-specs."

## Guidance

Work in this order. Each step has its own section below.

1. Resolve the output path (**Artifact paths and skill discovery**).
2. Collect the **Inputs**, and optionally a `gather-feature-context` briefing.
3. Establish knowledge-base context.
4. **Read before writing**: rules, convention skills and the code.
5. Run the **Duplicate-code check**, keeping **cohesion**.
6. Write **The document** for **the reader**, with the right **visual aids**.
7. Pass **Before saving**, then hand off to `breakdown-feature-spec-to-tasks`.

## What this skill is, and is not

> **Remember:** this is a concise specification. It agrees the shape; the sub-specs carry the build detail.

**The overview describes:**

- What the feature does and why it is needed, with light context on what exists today and how the feature affects it.
- The domains and the meaning of each.
- The schema of the backing domains.
- The journeys and workflows, usually owned by application services.
- The entities involved: what each encapsulates and is responsible for.
- The journey those entities take through the workflows, once both have been introduced.
- The scaffold, clearly enough that a developer can picture the control flow.
- The behaviour that must be tested, not the individual test cases.
- The order in which the feature should be built.

**It does not need** granular implementation detail. It does need the interfaces of each application service, controller and worker.

| | This skill | `breakdown-feature-spec-to-tasks` (next step) |
|---|---|---|
| Purpose | Agree the shape, expose the unknowns | Detail each slice so an agent can build and test it with limited context |
| Output | One `overview.md` | One standalone sub-spec per cohesive slice (`NN.a.n-<slice>.md`) plus `task-list.md` in dependency order |
| Detail | Entities, interfaces, interactions | Exact files, symbols, call sites, core logic, error rules and acceptance scenarios |
| Unknowns | Allowed, listed as open decisions | A sub-spec with material ambiguity is not READY |
| Review | Checklist below, then family review | Sub-spec checklist, then family review |
| After it | The operator reviews and decides | `feature-specification-verification` reviews the whole family |

The overview is one half of the specification family; the standalone engineering sub-specs are the other. Neither replaces the other, even for a small feature. Never claim approval, review or passing tests that did not happen.

## Artifact paths and skill discovery

Resolve artifact roots in this order: explicit operator instruction → repository project override → the defaults below. In the Slo repository, `CLAUDE.md` mandates repo-local `feature-requests/` and `specifications/`; do not replace that override with a home-directory default.

```text
<feature-requests-root>       = <SLO_FEATURE_REQUESTS_DIR or resolved-Slo-home/projects/<project_name>/feature-requests>
<feature-specifications-root> = <SLO_FEATURE_SPECIFICATIONS_DIR or resolved-Slo-home/projects/<project_name>/feature-specifications>
```

One folder per feature. Never name a specification `request.md`; that name belongs to incoming requests.

```text
<feature-specifications-root>/
└── 01-example-feature/
    ├── overview.md              # this skill
    ├── task-list.md             # breakdown-feature-spec-to-tasks
    ├── 01.a.1-first-slice.md    # standalone engineering sub-spec
    └── 01.a.2-second-slice.md
```

**Skill discovery.** Use the active skill catalog's `file_path` for each named skill, including user overrides. Vendored locations resolve through `config.cfg` (`SKILLS_LOCATION` / `SKILLS_DIR`), in this order:

1. `SLO_SKILLS_DIR` when set and non-empty. An invalid explicit value is reported as missing, not silently replaced.
2. The populated `skills` directory under the resolved `SLO_HOME`.
3. The package-adjacent `skills` directory of the installed Slo package, or the same directory in a development checkout.

Personal content lives in `config.cfg`'s `USER_SKILLS_DIR` and `USER_WORKFLOWS_DIR` (`SLO_USER_SKILLS_DIR`, `SLO_USER_WORKFLOWS_DIR`, otherwise `user_skills` and `user_workflows` under the Slo home). Paths written as `<group>/<skill>/SKILL.md` are relative to the library root. Do not hard-code a username, home prefix, Python version or package layout. If a required location cannot be found, report it and ask.

## Inputs

Collect these before writing:

1. The operator's request, in their words. Keep every constraint they state, and note any later correction.
2. The source request, issue or task, from whichever source-control or project-management tool holds it. Read its description, acceptance criteria, comments and linked items.
3. The repository path and the area of the code the feature touches.
4. Existing documents on the same area (specs, earlier designs, evidence). Treat historical proposals as inputs, not established facts.
5. The destination folder, resolved as in **Artifact paths and skill discovery**. Do not overwrite an existing `overview.md` without explicit permission.

When the operator wants a source-backed briefing to sign off before design starts, run [`gather-feature-context`](../gather-feature-context/SKILL.md) first and use its briefing as input. It is optional.

## Mandatory first task: establish knowledge-base context

Before design analysis, resolve `$SLO_KB_DIR` following [`locate-knowledge-base`](../locate-knowledge-base/SKILL.md) (`skills/design-and-analysis/locate-knowledge-base/SKILL.md`). Discovery is non-blocking. Do not substitute the skills directory or a hard-coded path.

- If `$SLO_KB_DIR` names a file (for example `.../KB/Welcome.md` or `index.md`), that file is the entry point and its parent directory is the KB root.
- If it names a directory, that directory is the KB root; its entry point is `Welcome.md`, `index.md` or `README.md`, in that order.

1. Open the entry point and the navigation it links. Locate the project by name, repository and feature context; ask if the match is ambiguous.
2. Read the project overview and the guidance relevant to the capability before making design decisions.
3. Treat the KB as the **source of truth** for documented context, terminology, business rules, architecture and decisions. Return to it on any subject while writing.
4. Cite the KB file and section beside the facts it supports. KB documentation is not proof of live schema, deployed behaviour or passing tests. Surface conflicts with code or operator instructions; explicit operator corrections win.
5. If the KB is unset, inaccessible or the project cannot be found, do not stop. Report which paths were checked, ask once for the right location, and continue with verified sources. Record each KB-dependent fact as an open decision. Never imply the KB was consulted when it was not.

## Read before writing

1. The repository rules and project instructions (`AGENTS.md`, `SLO.md`, `CLAUDE.md`, `RESEARCH.md` when present).
2. The design rules: [`solution-design`](../../coding/solution-design/SKILL.md), [`code-design-principles`](../../coding/code-design-principles/SKILL.md) and [`coding-rules`](../../coding/coding-rules/SKILL.md), plus the convention skills in **Convention skills to read**.
3. The knowledge base, as above.
4. **The code itself.**
   - For every responsibility the feature needs, search by behaviour, not by the feature's name.
   - Read the callers, the writers of the state and the existing seams.
   - Record each finding as: exists (reuse it), partly exists (extend its owner), adjacent (draw a boundary) or does not exist (greenfield).
5. Confirm every `path:symbol` you cite by opening it. If something could not be checked, say so in the document.
6. Run the **Duplicate-code check** before proposing any new artefact.

## Convention skills to read

Paths are relative to the skills library root. Start with the language gateway; use `engineering/engineering-routing/SKILL.md` when the feature spans languages. Always read `coding/test-verification-policy/SKILL.md`. Read the layers the design touches:

- **Python** (gateway `languages/python/python-conventions/SKILL.md`)
  - domain features → `languages/python/build-domain-features/SKILL.md`
  - application services → `languages/python/build-application-services/SKILL.md`
  - routers → `languages/python/build-routers/SKILL.md`
  - workers → `languages/python/build-celery-workers/SKILL.md`, `languages/python/build-dbos-workflow-orchestration-pattern/SKILL.md`
  - migrations → `languages/python/setup-alembic/SKILL.md`
- **Go** (gateway `languages/go/go-conventions/SKILL.md`)
  - domain features → `languages/go/go-build-domain-features/SKILL.md`
  - application services → `languages/go/go-build-application-services/SKILL.md`
  - HTTP handlers → `languages/go/go-build-http-handlers/SKILL.md`
  - workers → `languages/go/go-build-workers/SKILL.md`
  - migrations → `languages/go/go-recipe-database-migrations/SKILL.md`
- **TypeScript** (gateway `languages/typescript/typescript-conventions/SKILL.md`)
  - domain features → `languages/typescript/typescript-build-domain-features/SKILL.md`
  - routers → `languages/typescript/typescript-build-routers/SKILL.md`
- **Vue:** `frontend-vue/vue-coding-conventions/SKILL.md`, `frontend-vue/build-vue-components/SKILL.md`

The full per-layer list (middleware, events, clients, tests by layer, always-on style) is in [`breakdown-feature-spec-to-tasks`](../breakdown-feature-spec-to-tasks/SKILL.md#convention-skills-by-language-and-layer).

## Duplicate-code check

Before proposing a new artefact, prove nothing already does its work. Search by behaviour, not by name, for:

- **Data structures:** models, DAOs, schemas, DTOs, enums, configuration.
- **Code:** helpers, validators, queries, serializers.
- **Functionality:** services, workers, routes, clients.

Record each proposed artefact in this table under **Current state**:

| Proposed artefact | Existing owner (path:symbol) | Overlap | Consolidation | Resulting single owner |
|---|---|---|---|---|
| `<proposed name>` | `<path:symbol>` or "No existing owner found" | duplicate / partial / adjacent / none | compose / encapsulate / extend owner / delete-and-replace | `<one owner>` |

- Consolidate by composition or encapsulation so each responsibility has exactly one owner.
- Name the call sites to repoint and the code to delete.
- "No existing owner found" is an explicit finding, not an empty row.
- An unresolved duplicate is blocking: list it first in the open decisions, and do not present the overview as agreed until it is resolved.

## Cohesion over line-level DRY

DRY must not destroy cohesion. Consolidate duplicate *responsibilities*, not lines that merely look alike.

- Keep tightly coupled steps in one method so the logic reads as one unit: a query and its terminating flush or commit, open and close, acquire and release, validate then write.
- Extract only a meaningful, named responsibility. Never extract a flush or commit into its own method merely to avoid repetition.
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

## The reader and the language

Write for a reader who is technical and business-savvy but has **no context on this application**. They know what a queue, a transaction or a foreign key is. They do not know this product's internal terms, how its pieces fit, or why a past decision was made.

- Write clearly and present well: short sections, one idea each, no large blocks of prose.
- Define each internal term once, in one plain sentence, where it first appears. Spell out acronyms on first use.
- Lead with the point, then the detail. Short sentences, concrete verbs, no jargon where an everyday word works.
- Do not explain what any engineer already knows, and do not talk down.
- Use one word per concept everywhere: tables, diagrams, interfaces and prose.

## Visual aids

Pick the diagram by what it has to show. A diagram **adds to** the attribute tables and prose; it never replaces them. Use Mermaid fenced blocks so they render in Markdown viewers, and fall back to ASCII where the target cannot render Mermaid.

| What you need to show | Use | Notes |
|---|---|---|
| How tables relate: keys, cardinality, ownership | **Entity-relationship diagram** (`erDiagram`) | In addition to the per-table attribute tables |
| Objects, what each encapsulates, and any hierarchy | **UML class diagram** (`classDiagram`) | Only the public interface and the collaborators that matter |
| Folder or file layout, nested JSON, light hierarchies | **ASCII tree** | Mark each entry new, changed or removed |
| Who calls whom, in what order, across systems | **Sequence diagram** (`sequenceDiagram`) | One per journey that crosses two or more systems or processes |
| The states of one record and what moves it | **State diagram** (`stateDiagram-v2`) | Label every edge with its trigger and guard |
| The whole journey and its branches | **Flowchart** or a short ASCII overview | One per document, near the top |

Name things following [`naming-and-clarity`](../../coding/naming-and-clarity/SKILL.md) and [`ubiquitous-language`](../ubiquitous-language/SKILL.md). For every diagram:

1. One idea per diagram. Past about 12 nodes (Mermaid) or 20 lines (ASCII), split it.
2. Introduce it with one sentence. Label arrows with the verb and the data that moves ("stores email", "enqueues message id").
3. Use exactly the names used in the tables and interfaces.
4. Do not draw the same flow twice or add a diagram that only decorates.
5. Show failure and recovery paths, not only the happy path.

## The document

**Title:** `# <Product or system> <Feature name>`. No status line, source list or revision history unless the operator asks for one.

The order follows the reader's questions: what is it, what do I need, how does it fit today, what does it manage, how do things move, what are the interfaces, what changes, and what is undecided. **Journeys come after the domains**, because a reader cannot follow a flow through things they have not met.

1. **What this feature does.** Three to six sentences on the problem, then a short numbered list of what the feature does end to end. Note any step not yet designed and where it is tracked in the open decisions.
2. **Prerequisites.** What the developer must obtain before starting: access, accounts, credentials, environments. For each, who grants it and where it comes from. Name secrets by their config key; never include a value.
3. **Approach.**
   - **Problem** and **Recommendation**, each a short paragraph.
   - **Current state:** verified facts with `path:symbol`, what will be reused and what is missing, and the duplicate-code table. Say plainly when the area is greenfield.
   - **One overview diagram** of the whole journey, showing which module owns each step and the states a record passes through.
4. **Domains and data.** A domain is a cohesive responsibility that owns state, defined by its concept and rules, not by a table or a screen.
   - For each domain: what it owns, what it does not own, and its tables.
   - **Entity-relationship diagram**, then an **attribute table** per table: name, type, required, meaning and constraint. Say which record is the authority and which are derived copies.
   - **State diagram** for every record with a lifecycle, with the guard on each transition.
   - **Class diagram** where encapsulation or hierarchy is worth seeing.
   - **ASCII tree** for nested data inside a column or any hierarchy where UML would be heavy.
5. **Journeys and workflows.** The two or three journeys that matter: the normal path, the empty or no-match path, and the failure and recovery path. For each: trigger, ordered steps, state changes, observable outcome and recovery. Add a **sequence diagram** for journeys that cross systems or processes, and a flowchart where the path branches.
6. **Modules, interfaces and caller use.**
   - **Modules table:** module, interface and callers, what it hides, leverage and locality.
   - **The governing question,** stated once: how much useful behaviour can callers and tests exercise through the interface, and how much change can stay inside it?
   - **The deletion test, verbatim:** "If this module disappeared, would complexity disappear too, or would its work have to be repeated across callers?" Answer it for each module, and name the weakest one honestly.
   - **Rules the design decides** (matching precedence, retention, ordering), each inside the module that owns it.
   - **Caller use:** how each entry point is called, and the signatures of the key interfaces (keyword arguments, type hints, no bodies). Put the target file before every snippet as ``**File:** `path` (new|changed)``, one file per snippet.
   - **Promises:** ordering, transaction boundaries, idempotency, ownership, failure and recovery.
7. **Existing code changes.** What is reused, extended and new, and the configuration keys. Show the files as an **ASCII tree** marked new, changed or removed. Describe database changes as operations (create, add column, constraint, index) with deployment order, backfill and rollback limit. End with **the strongest alternative** and why it was or was not chosen.
8. **Tests, limits and next steps.**
   - **Behaviour to prove**, following `coding/test-verification-policy/SKILL.md`. Lead with behaviour tests that drive each journey end to end through the real entry point, application service and persistence, and assert the observable and stored outcome. Add focused unit tests only for critical methods with complex computation (parsing, matching, scoring, state rules). This does not require an elaborate Playwright or integration harness. Say which real components stand in where the policy forbids mocks.
   - Limits that shape operation (batch sizes, one worker at a time, quotas).
   - **Open decisions:** a numbered list. Each says what is unknown, what it blocks and who can answer. Blocking ones first.
   - **Delivery order** in which each step is runnable. Each step is one vertical piece of functionality end to end, so it becomes one sub-spec.
   - End with a one-paragraph takeaway.

## Rules that decide quality

- **One owner per state change.** Every transition, record and rule has exactly one owning module. Where the code already has an owner, reuse or extend it.
- **Facts, proposals, assumptions and open decisions stay separate.** Mark each so a reader can tell what was verified. Mark any departure from the operator's request and say why.
- **Unknowns are information.** If a decision blocks a step, say so and leave it open. Do not invent an answer.
- **Interfaces, not implementations.** Name inputs, outputs, errors and guarantees. Method bodies and line-level wiring belong in the sub-specs.
- **Be honest about side effects and atomicity.** A database write plus a message to a queue is never atomic unless a mechanism makes it so. Say what happens if the process stops between them.
- **Sensitive data.** Say where personal or secret data may live, and where it must not (tables, logs, durable workflow outputs).
- **One name per concept** across tables, interfaces, diagrams and prose.
- **Show, then tell.** Draw relationships, sequences and lifecycles; use prose for why.
- **Length.** As short as the content allows; about 1,000 to 1,500 words is typical. Cut repetition before cutting a contract.

## Before saving

- [ ] The knowledge base was consulted (file value used as entry point, directory value searched for `Welcome.md` / `index.md` / `README.md`), or its absence and the affected open decisions are recorded.
- [ ] KB facts have file and section citations; conflicts and unverified live-state claims are explicit.
- [ ] Every source requirement (request, issue, acceptance criteria, comments) is reflected in the overview or listed as excluded or open.
- [ ] The current state is explained, with verified paths, before the proposal.
- [ ] Every state change has one owning domain; no second owner of an existing responsibility.
- [ ] The duplicate-code table covers every proposed artefact, "No existing owner found" is explicit, call sites to repoint and code to delete are named, and no duplicate is unresolved.
- [ ] Tightly coupled steps (query and flush, open and close, validate then write) stay together; nothing trivial was extracted only to avoid repetition.
- [ ] The matching convention skills were read.
- [ ] Every table has its attributes, and an entity-relationship diagram shows how the tables relate.
- [ ] Every record with a lifecycle has a state diagram with guards.
- [ ] Journeys come after the domains, each with trigger, steps, outcome and recovery, and a sequence diagram where systems interact.
- [ ] Every diagram has one idea, a one-sentence introduction and the same names as the tables.
- [ ] Every interface lists inputs, outputs, errors and promises, and a file path precedes each snippet.
- [ ] The governing question and the verbatim deletion test are answered.
- [ ] Database changes are operations, with order and rollback limits.
- [ ] Behaviour to prove leads with end-to-end behaviour tests; unit tests are limited to complex computation.
- [ ] Failure and recovery are covered, including the crash between a commit and a queue message.
- [ ] Open decisions are numbered, blocking ones first.
- [ ] The delivery order has one vertical slice per step.
- [ ] No claim of approval, implementation, independent review or test execution.
- [ ] Clear and well presented for a reader with no context on the application.
- [ ] Saved at the resolved path; nothing else was overwritten.

Report the saved path, a short summary, the checks you ran and the open decisions. Then ask whether to continue to `breakdown-feature-spec-to-tasks`.

## Relationship to other skills

- [`solution-design`](../../coding/solution-design/SKILL.md) is the rule source this skill specializes. It prescribes the core sections and the verbatim deletion test; this skill adds context, prerequisites, domain and attribute tables, file-labelled snippets and open decisions.
- [`code-design-principles`](../../coding/code-design-principles/SKILL.md) and [`coding-rules`](../../coding/coding-rules/SKILL.md) supply the ownership, depth and naming rules.
- [`gather-feature-context`](../gather-feature-context/SKILL.md) is an optional, on-request briefing that feeds this skill.
- [`breakdown-feature-spec-to-tasks`](../breakdown-feature-spec-to-tasks/SKILL.md) is the next step. It expands `overview.md` into standalone engineering sub-specs and `task-list.md`.
- [`feature-specification-verification`](../feature-specification-verification/SKILL.md) reviews the whole family once both parts exist. Its REVISE findings on `overview.md` come back to this skill.
- [`feature-specification-with-html`](../feature-specification-with-html/SKILL.md) produces the same family as HTML.
- The [Specification Development workflow](../../orchestration/workflows/specification-development.md) sequences these steps.
