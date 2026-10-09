# Workflow: Specification Development

**Type:** Pipeline
**Governs:** All feature specification work in this repository

## Skills used in this workflow

Load these on demand as each step calls for them — you do not need to read any
other skill file to run this workflow:

| Step | Skill |
|---|---|
| 1 — Author (gather/draft/self-check/revise) | `skills/design-and-analysis/feature-specifications/SKILL.md` |
| 2 — Verification | `skills/design-and-analysis/feature-specification-verification/SKILL.md` |
| 3 — Task breakdown | `skills/design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md` |
| Ubiquitous language | `skills/design-and-analysis/ubiquitous-language/SKILL.md` |
| Manual vs. auto mode | `skills/design-and-analysis/workflows/SKILL.md#confirmation-behavior` |

---

## When to Use

Activate this workflow whenever the operator asks to:

- "Write a feature spec for …"
- "Spec out …"
- "Generate a feature specification …"
- "Plan the implementation of …"
- "Create a spec for [JIRA ticket or Confluence page]"
- break a large feature description into tasks or sub-specs

The trigger is intent to produce a specification document. Confirmation-seeking at the end of each step depends on [manual vs. auto mode](SKILL.md#confirmation-behavior).

---

## Pre-conditions

Before the first step begins, confirm:

- The operator has provided a feature description, JIRA ticket, Confluence URL, or verbal brief.
- `AGENTS.md` and `docs/RESEARCH.md` have been read (or are already in context). If either is empty, populate it before proceeding — see the CLAUDE.md instruction on empty `AGENTS.md` / `docs/RESEARCH.md`.
- The knowledge base has been looked for with `skills/design-and-analysis/locate-knowledge-base/SKILL.md`. This check is
  non-blocking: read the entry point (`Welcome.md` or `index.md` under
  `$SLO_KB_DIR`) when it exists. When no KB is found, tell the user, offer to
  create one, and continue the workflow without it. A missing KB is never a
  reason to stop.

---

## Steps

### Step 1 — Feature Specification (Gather context → Draft → Self-check → Revise)

**Governing skill:** `skills/design-and-analysis/feature-specifications/SKILL.md`

Execute its Gather context → Draft → Self-check → Revise stages in order.

**Input consumed:** the operator's feature description, ticket, or brief.

**What this step does:**

Execute the Gather context stage first. The Gather context stage produces the **Context Bundle** — a structured synthesis of: specification family, affected surface area, conventions in force, second-order requirements, KB lessons, and the narrative plan. The bundle must exist in the conversation before any spec text is drafted.

Apply the style guide from `skills/design-and-analysis/feature-specifications/SKILL.md` to draft the specification. Every feature must have overview.md with product framing and one or more separate standalone engineering sub-specs. Declare the complete family before drafting; neither part is optional and small features do not combine them into one file.

### Required implementation-details pass — do not skim

Before the draft is eligible for the Self-check stage, perform a dedicated implementation-details pass for every engineering slice. `## 7. Implementation Details` is the most important part of the specification: it is the coding agent's implementation contract, not a high-level recap. Read the packaged granularity sample at `skills/samples/implementation-details-granularity.md` as the required standard; it is shipped with Slo and is therefore available in installed environments.

The pass must ensure the sub-spec leaves no material implementation decision ambiguous. It must name the exact repository-relative files and folders involved; exact symbols and call sites to add, change, remove, or rewire; implementation order; current and target behavior; input/output, state, error, configuration, edge-case, and unchanged-behavior rules; convention-compliant implementation-ready code detail for non-trivial work; and consolidation or deletion work needed to preserve single ownership.

The same pass must prescribe validation rather than merely saying “add tests”: identify exact test file paths, existing tests to update or replace, new test scenarios or names, fixtures/setup, expected assertions, required test levels, verification commands, and manual smoke steps where applicable. The prescribed code and tests must honor the conventions established by the Context Bundle. If an implementing agent could reasonably make different choices about code placement, behavior, or test coverage, revise the draft before running the Self-check stage.

Once the spec body is drafted, execute the Self-check stage. Independent verification runs once at Step 2, not nested in authoring. The Self-check stage runs the complete author-owned requirements/architecture/flow/error audit, audits narrative sections, cross-checks against coding conventions, **always runs the DRY consolidation pass**, assesses granularity, audits example richness, and validates test coverage. If the verdict is REVISE, edit the spec in place and re-run the Self-check stage until the verdict is READY.

The consolidation pass is the step that keeps the system design DRY. A generated specification frequently proposes functionality that already exists in the code — doing the same work wholly, doing part of it, or owning the responsibility the new design duplicates. Redundant artefacts, entities, and domains cause confusion that outlives the feature, so every artefact the spec introduces is checked against the existing code and consolidated by deleting and replacing it, encapsulating it within our conventions, or re-designing the existing component to absorb the new functionality. Responsibilities stay single, isolated, and clean, with distinguishable boundaries documented in the comments and explicit interfaces to adjacent responsibilities. Any surviving redundancy is an automatic REVISE.

**Output produced:**

- Context Bundle (in conversation)
- Product overview written to `specifications/<number>-<title>/overview.md`, plus
  one or more separate standalone engineering sub-specs in the same family
  - The primary spec document is always named `overview.md` inside its numbered folder.
  - Sub-specs (drafted in Step 1 and refined during Step 3 breakdown) follow `<spec-number>.<letter>.<index>-<title>.md`
    (e.g., `28.a.1-moonshot-credential-lane.md`). Never name a spec file `request.md`.
- Author Self-check Report (in conversation, verdict = READY)

**READY condition:** Self-check stage returns READY. No outstanding REVISE loops.

**Context carried forward to Step 2:**
- The full specification document
- The Author Self-check Report (especially the JIRA traceability matrix and any open questions)
- The Context Bundle (specification family, affected surface area, conventions in force)

---

**[MANUAL MODE — PAUSE]**

Present the completed spec and the Author Self-check Report to the operator. State:

> "Step 1 complete — specification is READY per the Self-check stage. Proceeding to Step 2 (Verification) unless you would like to revise first."

Wait for confirmation before continuing.

---

### Step 2 — Feature Specification Verification

**Governing skill:** `skills/design-and-analysis/feature-specification-verification/SKILL.md`

**Input consumed:**
- The specification document from Step 1
- The Author Self-check Report from Step 1
- The JIRA ticket (if provided — fetch it if not already in context)

**What this step does:**

Run the full verification procedure from `feature-specification-verification.md`. This is an independent, adversarial review of the spec produced in Step 1 — not a rubber-stamp. It re-derives requirements from the JIRA source of truth, maps them against the spec, audits the full architectural stack for completeness, independently searches the code for existing owners of every artefact the spec introduces, traces the control flow, checks for missing error paths, and assesses specification family and structure compliance independently. It must also verify the implementation-details contract as a CRITICAL gate: granular code placement, symbol-level changes and behavior, convention compliance, and concrete test coverage must leave no material ambiguity for the implementing agent.

The verification must produce a formal report with:
- JIRA Requirement Traceability Matrix
- Architectural layer checklist results
- Redundancy gaps (if any) — treated as CRITICAL
- Critical gaps (if any)
- Minor gaps (if any)
- Ambiguities (if any)
- Family/structure gaps (if any)
- Executive summary with pass/fail/revision verdict

If CRITICAL gaps are found, the agent must return to Step 1 and revise the specification before completing Step 2.

**Output produced:**

- Specification Verification Report (in conversation) with executive summary and full traceability matrix

**READY condition:** verification report is complete; no CRITICAL gaps remain unaddressed.

**Context carried forward to Step 3:**
- The specification document (potentially revised by Step 2's findings)
- The Specification Verification Report
- The dependency structure and requirements list from the traceability matrix

---

**[MANUAL MODE — PAUSE]**

Present the Specification Verification Report. State:

> "Step 2 complete — verification report is ready. [N critical gaps / no critical gaps] found. Proceeding to Step 3 (Task Breakdown) unless you would like to address findings first."

Wait for confirmation before continuing.

---

### Step 3 — Breakdown to Tasks

**Governing skill:** `skills/design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md`

**Input consumed:**
- The final verified specification from Steps 1–2
- The Specification Verification Report (especially the traceability matrix and dependency notes)
- The JIRA parent ticket and project key (the operator must supply these if not already provided)

**What this step does:**

Decompose the verified specification into dependency-ordered implementation tasks. Keep the product overview and map each implementation task to standalone engineering sub-specs; create or refine the required sub-specs rather than selecting a document mode. Group cohesive work, split at dependency boundaries, identify parallelizable tasks, and prefer single-repo tasks.

Each child task must:
- Open with the human-readable narrative sections required by `skills/design-and-analysis/feature-specifications/SKILL.md` for its artifact role
- Carry any consolidation work the spec committed to — the deletions, replacements, encapsulations, and re-designs that keep the system DRY belong in the dependency-ordered tasks, not in a follow-up nobody schedules
- Include every relevant code sample from the source spec in exactly one task
- State explicit acceptance criteria (specific and testable)
- Reference the adjacent feature or pattern to follow

After writing all tasks, produce an ASCII dependency graph showing which tasks block which, which can be parallelized, and the critical path.

If a JIRA project key was provided, push the tasks to JIRA as sub-tasks of the parent issue. Report the full summary table with actual issue keys and the dependency graph.

**Output produced:**

- Dependency-ordered task list (in conversation)
- Per-task standalone engineering sub-specs linked to the product overview
- ASCII dependency graph
- JIRA sub-tasks created (if project key was provided), with summary table

**READY condition:** task list is complete, dependency graph has no cycles, every code sample from the source spec appears in exactly one task, JIRA tasks are created if applicable.

---

**[MANUAL MODE — PAUSE]**

Present the task breakdown and dependency graph. State:

> "Step 3 complete — specification is broken down into [N] tasks. [JIRA sub-tasks created / not pushed to JIRA.] Workflow complete."

**[AUTO MODE — FINAL CONFIRMATION]**

Before creating any JIRA sub-tasks or publishing the spec to the wiki, pause and confirm with the operator:

> "Specification Development Workflow complete. Ready to [create JIRA sub-tasks / publish to wiki / hand off to developer]. Confirm?"

---

## Exit Condition

The Specification Development Workflow is complete when:

- Step 1: The specification is drafted, Self-check stage returns READY.
- Step 2: Verification report is complete, no CRITICAL gaps remain.
- Step 3: Tasks are broken down with dependency graph, JIRA sub-tasks created (if applicable).

---

## What Does Not Change

The following rules remain in effect throughout this workflow. The workflow does not relax or override them:

- All coding conventions from `AGENTS.md` and the always-on rules in `CLAUDE.md`.
- The requirement to read matching `build-*.md` files before specifying any layer that a spec touches.
- The KB consultation requirement — the Gather context stage's Step 3 is not optional.
- The requirement to seek confirmation before committing or publishing (`ALWAYS SEEK CONFIRMATION BEFORE COMMITTING CODE`).
- Ubiquitous language — every concept introduced in the spec must follow the single-name-across-all-layers rule from `ubiquitous-language.md`.
- DRY design — no step of this workflow may produce a spec that adds a redundant artefact, entity, or domain for work the code already does. Responsibilities stay single, isolated, and clean, with documented boundaries and explicit interfaces to adjacent responsibilities. The Self-check stage's consolidation pass in Step 1 and the redundancy review in Step 2 both enforce this, and Step 3's child tasks must carry the deletions and re-designs that consolidation requires.

---

## Quick Reference

```
Trigger: "write a feature spec for X"

Step 1: Gather context → Draft → Self-check → Revise (loop until READY)
        └─ Output: spec document + Author Self-check Report

Step 2: Verification (adversarial; returns to Step 1 if CRITICAL gaps)
        └─ Output: verification report with traceability matrix

Step 3: Task breakdown → dependency graph → JIRA push (if applicable)
        └─ Output: child specs + dependency graph + JIRA sub-tasks

[MANUAL] pause at end of each step
[AUTO]   run to completion, confirm before publishing/committing
```
