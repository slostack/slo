---
name: gather-feature-context
description: 'Optional, on-request companion that produces a source-backed context briefing for operator sign-off; the signed-off briefing feeds feature-specifications as input. Provides language-aware (Python, Go, TypeScript), framework-neutral tracing and an evidence-backed behavior map.'
when_to_use: 'Use on-request only when the operator asks for a source-backed briefing to sign off before the overview is written. Ordinary specification work starts directly with feature-specifications.'
group: design-and-analysis
kind: workflow
source_prompt: analyze/gather-feature-context.md
---

# Gather Feature Context

## Skill summary

- **Name:** `gather-feature-context`
- **Description:** Gathers business, architecture, code and source evidence into one briefing the operator signs off. The briefing is an input to [`feature-specifications`](../feature-specifications/SKILL.md#inputs), which writes `overview.md`.
- **When to use:** On request, when the operator wants to review the context before design starts.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `analyze/gather-feature-context.md`

## Examples

- "Gather the business and technical context for this feature before we write the spec."
- "Prepare a source-backed briefing for my sign-off, then write the overview."
- Without such a request, specification work starts directly with `feature-specifications`.

## Guidance

Decide whether a briefing is needed, then run Steps 1–6 in order and stop for sign-off before handing off.

## Where this fits

```text
(optional) gather-feature-context ──► briefing ──► operator sign-off
                                                        │
                                                        ▼
            feature-specifications ──► overview.md ──► breakdown-feature-spec-to-tasks ──► verification
```

| Question | Answer |
|---|---|
| Is it required? | No. It is optional and not a second default pre-hook. |
| What does it produce? | One briefing in the conversation, ready to paste forward. |
| Who consumes it? | [`feature-specifications`](../feature-specifications/SKILL.md#inputs), as an input. |
| What does it not do? | Design the feature, write `overview.md` or sub-specs, or write code. |
| Workflow | [Specification Development](../../orchestration/workflows/specification-development.md), optional step before Step 1. |

**Skip it** when the operator says so ("skip the briefing", "I already have the context"). Continue with `feature-specifications` and reuse whatever context was supplied.

**Context check.** Before the heavy steps, decide whether the conversation already holds the business, application and implementation context. If it does, summarise it and ask whether to skip. If not, ask for what is missing (issue or task link, design page, subject area, owning service). **Never invent context.**

## Artifact paths

Use the canonical [artifact paths and skill discovery](../feature-specifications/SKILL.md#artifact-paths-and-skill-discovery) rules, including project-local precedence. This companion defines no competing roots or defaults.

---

## Inputs

**Required** (ask if missing):

1. **Subject** — the feature name or short description (e.g. "partial-shipment split").
2. **Anchor** — at least one of:
   - an issue or task from any source-control or project-management tool;
   - a design page, wiki or knowledge-base page;
   - a merge request, pull request or branch;
   - a clear plain-language statement of the problem.

**Optional:** scope hints (repositories, services, prior work) and explicit out-of-scope areas.

If only a subject is given, ask whether an issue, task or design page exists. Proceed without one only after the operator confirms none exists.

**Repositories in scope.** Use the workspace file's member repositories when one exists; otherwise follow the operator's scope hints. Skip prompt/tooling libraries and anything marked out of scope.

---

## Step 1 — Preserve git state

Read the **latest main** of each repository without disturbing the operator's working tree. Prefer, in order:

| Option | When | How |
|---|---|---|
| Worktree (default) | Always, when possible | `git fetch origin main` then `git worktree add -B context-gather-<YYYYMMDD> ../.worktrees/<repo>-context origin/main` |
| Stash and checkout | Worktrees not viable | Record `git status` and `git rev-parse HEAD`, `git stash push -u -m "context-gather-<YYYYMMDD>"`, check out `origin/main`; restore afterwards |
| Read-only remote | Clone missing or stale, or operator prefers | Hosting CLI or connector |

Record per repository: original branch, original commit SHA and the path actually read.

---

## Step 2 — Business context

Answer two questions, in this order:

1. **Domain:** what does the concept mean in the industry? Explain it as an outsider would. Example: a *partial shipment* fulfils one order across several deliveries when not all lines are in stock, which affects invoicing and customer-visible status.
2. **Product:** what problem does this solve for our business, and for whom?

Lead the briefing with the domain explanation; a shared vocabulary is the cheapest guard against an off-target spec.

### Sources and their status

| Source | What it contributes | If absent |
|---|---|---|
| Knowledge base | Terminology, architecture, decisions, conventions, known limitations | Record "no KB found"; discovery is non-blocking |
| Issue tracker / wiki | Requirements, acceptance criteria, comments, linked designs (any source-control or project-management tool) | Record unavailable; ask the operator; proceed on confirmation |
| Code | Actual wiring, execution paths, persistence, integrations, configuration | Record unavailable and surface the verification gap |
| Documentation / READMEs | Structure, setup, APIs, operations, test instructions | Record empty or unavailable |
| Tests | Behavioral contracts, edge cases, fixtures, boundaries | Record empty if inspected without findings |

- Discover the KB with [`locate-knowledge-base`](../locate-knowledge-base/SKILL.md); read its entry point, the repository index and gotchas.
- Give every source a status: **consulted-with-findings**, **empty** (inspected, nothing relevant) or **unavailable** (no connector, access or source). Never skip a source silently.
- Report material **contradictions** between code, documentation and issues. Do not resolve them by assumption; ask which contract governs.
- Follow linked design documents, discussions and runbooks. If a design document would be expected for this area and none is found, ask the operator for one and note its absence.
- Use authoritative external references, with citations, only when internal sources are thin.

### Capture

Keep enough that `feature-specifications` can use it without re-querying:

- **Glossary** — each term or acronym, a one-line definition and its source.
- **Goal** — the outcome the feature unlocks (compliance, operator UX, scale, risk).
- **Stakeholders** — who asks and who is affected.
- **Constraints** — regulatory, contractual, SLA, deadline, budget.
- **Prior art** — earlier designs, specs and decisions in the area.
- **Links** — issue, design-page, KB and external references, kept for verbatim quotes later.

**Confirm before moving on.** Phrase the domain framing and the business goal back in one sentence each and ask the operator to confirm. If nothing is found, say so; do not fabricate.

---

## Step 3 — Current state (application and technical)

Describe the system **as it exists today** in the area the feature touches.

Read `RESEARCH.md`, `AGENTS.md` and the applicable conventions first. Use [`find-how-it-works`](../find-how-it-works/SKILL.md) for deeper tracing. Record real `path:symbol` references and handoffs, and open each one to confirm it.

The guides below show a typical order to trace. Follow the repository as it actually is.

### Python

A discovery guide, not a mandated architecture; do not invent layers. Covers web, CLI, worker and event-driven entry points.

Bootstrap → route or command registration → middleware/dependencies → handler → application service → domain behavior → persistence/external clients → response/error handling → tests.

### Go

A discovery guide, not a mandated architecture; do not invent layers. Covers web, CLI, worker and event-driven entry points.

Entrypoint/wiring → router or command registration → middleware → handler → application/domain services → repositories/clients → response/error handling → tests. Trace context propagation and cancellation where relevant.

### TypeScript

A discovery guide, not a mandated architecture; do not invent layers. Covers web, CLI, worker and event-driven entry points.

Workspace/package bootstrap → route, controller or UI entry point → middleware/providers → application services or state/data access → domain behavior → persistence/external APIs → response/rendering/error handling → tests. Keep frontend component paths distinct from backend request paths and trace their real shared boundary.

### Verify the schema (mandatory)

Every table, column, type and nullability the briefing names must be verified, never inferred from a sibling spec, a past conversation or an analogous table.

- **Sources:** the ORM model, migration directory, schema definition or protobuf, and/or permitted live data through the project's documented development-database path (KB-referenced where present). Never assume connection strings.
- **Record:** actual names, types, nullability, constraints, indexes, relationships and real enum values, quoted, with the source named. Mark existing versus proposed.
- **Gate:** if neither source nor permitted data is available, **stop and surface the gap** to the operator before the overview is written.

---

## Step 4 — Existing owners and precedents

The system may already do part or all of the work, usually under a different name. Search by behavior, not by the feature's name, for data structures, helpers and services.

- **Closest analogous feature:** its path, language, framework, layout and boundaries.
- **Existing owners:** one row per proposed artefact, in the same shape `feature-specifications` uses for its duplicate-code table.

| Proposed artefact | Existing owner (path:symbol) | Overlap | Consolidation |
|---|---|---|---|
| `<proposed name>` | `<path:symbol>` or "No existing owner found" | duplicate / partial / adjacent / none | compose / encapsulate / extend owner / delete-and-replace |

- **Conventions:** select them through [`engineering-routing`](../../engineering/engineering-routing/SKILL.md) for the languages actually present; do not impose Python idioms elsewhere.
- **Gotchas:** from `KB/<repo>/gotchas.md` that the design must respect.

---

## Step 5 — The briefing

Produce one scannable briefing, ordered to match what [`feature-specifications`](../feature-specifications/SKILL.md#inputs) needs. Keep each section short; link rather than repeat.

```markdown
# Context Briefing — <Subject>

## 1. Business context
- Domain framing (confirmed): <one paragraph>
- Goal: <outcome the feature unlocks>
- Stakeholders: <list>
- Constraints: <regulatory / contractual / deadline>
- Source issue or task: <link + status>; design page: <link, or "none found, confirmed">
- Glossary: <term — definition — source>

## 2. Behavior map (current state)
- Entry points: <path:symbol>
- Control flow today: <numbered steps with path:symbol>
- Event and job flow: <actual events, tasks, completion boundaries>
- Gaps the feature must close: <bullets>

## 3. Domains and data found
- Domains touched: <name — what it owns today>
- Verified schema: <quoted names, types, nullability; source; existing vs proposed>

## 4. Journeys today
- <journey — trigger — steps — outcome — where failure is handled>

## 5. Existing owners and duplicate-code candidates
| Proposed artefact | Existing owner (path:symbol) | Overlap | Consolidation |
- Closest analogous feature: <path + one line>

## 6. Constraints, conventions and gotchas
- Applicable convention skills: <paths>
- Gotchas in scope: <bullets>
- Material contradictions: <code vs docs vs issues; decision needed>

## 7. Knowledge-base citations
- <KB file § section — fact it supports>

## 8. Source status and hygiene
- Source status: <each source — consulted-with-findings / empty / unavailable — why>
- Repos read: <branch + SHA + path>; worktrees/stashes: <cleanup status>

## 9. Open questions
- <what is unknown — what it blocks — who can answer>
```

Stop here and wait for user sign-off (or an explicit "go ahead") before handing the briefing to `feature-specifications`. The operator may waive sign-off; they will say so.

---

## Step 6 — Cleanup

After sign-off (or after the overview is written, depending on the flow):

- Remove worktrees created in Step 1 (`git worktree remove ...`).
- If a stash was pushed, restore the original branch and `git stash pop`.
- Confirm in one line that every repository is back to its pre-gather state.

---

## Principles

| Principle | In practice |
|---|---|
| Ask before assuming | A short question is cheaper than a wrong spec. |
| Never invent | A missing source is recorded as missing, not filled in. |
| Verify, never paraphrase | Quote schema and symbols from their real source; stop and surface gaps. |
| Non-disruptive | The working tree looks identical afterwards; worktrees by default. |
| Business first | The briefing leads with *why*, then *where*. |
| Surface gaps and duplicates | Say what is missing and what already exists, so the overview keeps one owner per responsibility. |
| Name what you found | Report the language and framework the trace actually found; a guide's order is not the repository's architecture. |
| Hand off cleanly | The briefing is ready to paste into `feature-specifications`. |
