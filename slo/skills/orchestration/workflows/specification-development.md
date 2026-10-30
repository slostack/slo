# Workflow: Specification Development

**Type:** Pipeline
**Governs:** All feature specification work in this repository

Follow [progression and authorization](SKILL.md#progression-and-authorization):
verify phase artifacts, report progress, and ask only for blocking clarification.
External and destructive actions still require explicit operator authorization.

## Scoped guidance and phase handoff contract

**Workflow-turn accounting:** Follow
`skills/orchestration/workflows/SKILL.md#workflow-turns-and-limits`.
Count a full pass through the workflow, not individual phases or agent calls.
Report partial passes and separate harness limits explicitly; never skip review
or treat repeated authoring dispatches as completed workflow turns.
Explicit user instructions override the default workflow-turn and per-turn dispatch
budgets: raise, lower or remove either limit as requested. Record and pass on the
effective limits without resetting consumed counts; runtime caps and other
policies remain separate.

Before Step 1 read `skills/engineering/engineering-routing/SKILL.md` and
`skills/engineering/engineering-testing/SKILL.md`. Record affected languages,
frameworks, test categories, project contracts, selected skill paths and the
actual project verification commands. Pass this record to every phase. Load
language and component recipes on demand; do not impose Python syntax or tooling
on Go, TypeScript or an unsupported language.

Each phase returns a terminal verdict (READY/COMPLETE, REVISE, or FAILED), concrete
artifact paths, requirement-to-evidence mapping, deviations and unresolved blockers.
Verify artifacts exist before advancing. A revision invalidates later review
evidence for the changed documents and everything that depends on them: return to
the responsible phase, retest and re-review.
An execution failure stops progression; a recoverable failed task may be retried
up to three times after the initial attempt, with its cause addressed and within
the current workflow turn's dispatch budget. Never retry an aborted task.
User cancellation is not permission to restart work. Do not claim another agent
independently reviewed work that was reviewed solo.

For dynamic workflows use in-session spawn_sub_agents unless explicitly detached;
ordinary workflow execution does not itself grant permission to spawn. A detached
orchestrator never launches another detached workflow. A missing knowledge base is
non-blocking; follow `skills/design-and-analysis/locate-knowledge-base/SKILL.md`.

## Skills used in this workflow

Load these on demand as each step calls for them, plus the language and component skills selected by the routing record:

| Step | Skill |
|---|---|
| 1 — Overview | `skills/design-and-analysis/feature-specifications/SKILL.md` |
| 2 — Standalone engineering sub-specs | `skills/design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md` |
| 3 — Family verification | `skills/design-and-analysis/feature-specification-verification/SKILL.md` |
| Optional context briefing before Step 1 | `skills/design-and-analysis/gather-feature-context/SKILL.md` |
| Ubiquitous language | `skills/design-and-analysis/ubiquitous-language/SKILL.md` |

```text
request ──► 1. overview.md ──► 2. <NN>.a.n sub-specs + task-list.md ──► 3. family review
                 ▲                        ▲                                   │
                 └──── REVISE: overview ──┴──── REVISE: sub-spec/task list ◄──┘
                                                         READY ──► hand off
```

---

## When to Use

Activate this workflow whenever the operator asks to:

- "Write a feature spec for …"
- "Spec out …"
- "Generate a feature specification …"
- "Plan the implementation of …"
- "Create a spec for [issue, task or design page]"
- break a large feature description into sub-specs

The trigger is intent to produce a specification document.

---

## Pre-conditions

Before the first step begins, confirm:

- The operator has provided a feature description, an issue or task from any source-control or project-management tool, a design page, or a verbal brief.
- `AGENTS.md` and `RESEARCH.md` (or `docs/RESEARCH.md`) have been read when present.
- The knowledge base has been looked for with `skills/design-and-analysis/locate-knowledge-base/SKILL.md`. A missing KB is never a reason to stop.

---

## Steps

### Step 1 — Overview

**Governing skill:** `skills/design-and-analysis/feature-specifications/SKILL.md`

**Input consumed:** the operator's request and its source issue or task. Optionally, a briefing from `gather-feature-context` when the operator asks for one.

**What this step does:** writes `overview.md` for the feature: purpose, current state, the duplicate-code table, domains and data, journeys, module interfaces, behaviour to prove, open decisions and a delivery order of vertical slices. It finishes with the skill's "Before saving" checklist.

**Output produced:** `<feature-specifications-root>/<NN>-<feature>/overview.md`. Never name a spec `request.md`.

**READY condition:** the "Before saving" checklist passes and no duplicate is unresolved. Open decisions are allowed; they carry forward as blockers.

**Context carried forward:** the overview, its open decisions, and the routing record.

---

### Step 2 — Standalone engineering sub-specs

**Governing skill:** `skills/design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md`

**Input consumed:** `overview.md` from Step 1, any existing sub-specs, the implementation repository and the convention skills from the routing record.

**What this step does:** expands each delivery step into one standalone engineering sub-spec: one vertical slice, its current state, ownership and interfaces, schema contract, complete core logic, files and handoff, and acceptance rows backed by behaviour tests (unit tests only for complex computation). Schema work comes first. It then writes `task-list.md` in dependency order.

Every consolidation the overview committed to (delete and replace, encapsulate, re-design) is assigned to a specific sub-spec, sequenced so the replacement lands before or with the deletion.

**Output produced:** `<NN>.a.n-<slice>.md` standalone engineering sub-specs and `task-list.md` beside `overview.md`.

**READY condition:** the skill's review checklist passes. Sub-specs that depend on an open decision are marked BLOCKED, not READY.

**Context carried forward:** the complete family and the list of blockers.

---

### Step 3 — Family verification

**Governing skill:** `skills/design-and-analysis/feature-specification-verification/SKILL.md`

**Input consumed:** the whole family (`overview.md`, every sub-spec, `task-list.md`) and the source issue or task.

**What this step does:** an independent, adversarial review of the whole family, not a rubber stamp. It traces every source requirement to a document, audits each touched layer, searches the code for existing owners of every new artefact, traces the control flow and error paths, checks the overview and each sub-spec against their skills, and checks the family for consistency. Implementation ambiguity in a sub-spec is a CRITICAL gap.

**Output produced:** the Specification Verification Report (in conversation) with the traceability matrix, findings per document and a READY or REVISE verdict.

**On REVISE:**

1. Route each finding to the skill that owns the document: `overview.md` → Step 1; sub-specs and `task-list.md` → Step 2.
2. A change to the overview that alters a contract also sends the affected sub-specs back through Step 2.
3. Re-run Step 3 on the changed documents and everything that depends on them.
4. Each loop counts against the workflow-turn limit.

**READY condition:** the report is complete and no CRITICAL, REDUNDANCY or STRUCTURE gaps remain.

---

Report each phase result and verify its artifacts before advancing. When Step 3 returns READY, state:

> "Specification Development complete — `overview.md` and [N] sub-specs verified READY ([M] BLOCKED on open decisions). Ready to commit, publish, or hand off to implementation. Confirm?"

Commit, publication to any external tool, and implementation each need explicit operator confirmation.

---

## Exit Condition

The workflow is complete when:

- Step 1: `overview.md` passes its checklist.
- Step 2: every delivery step has a sub-spec, and `task-list.md` is acyclic.
- Step 3: the verification verdict is READY.

---

## What Does Not Change

These rules stay in effect throughout. The workflow does not relax them:

- All coding conventions from `AGENTS.md`, `SLO.md` and `CLAUDE.md`.
- Reading the matching convention skills before specifying any layer.
- The knowledge-base consultation in Step 1.
- Confirmation before committing or publishing.
- Ubiquitous language: one name per concept across every document and layer.
- DRY with cohesion: no redundant artefact, entity or domain for work the code already does, and no trivial extraction (such as moving a flush out of its method) that breaks the readability of a cohesive unit. Steps 1 and 2 record and consolidate duplicates; Step 3 independently searches for any that survive.

---

## Quick Reference

```
Trigger: "write a feature spec for X"

Step 1: feature-specifications            → overview.md
Step 2: breakdown-feature-spec-to-tasks   → <NN>.a.n sub-specs + task-list.md
Step 3: feature-specification-verification → READY / REVISE
        REVISE → overview to Step 1, sub-specs to Step 2, then Step 3 again

Verify READY artifacts at every phase; report progress.
Obtain explicit authorization before committing, publishing or implementing.
```
