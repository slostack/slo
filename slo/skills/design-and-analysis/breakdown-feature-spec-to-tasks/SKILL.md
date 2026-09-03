---
name: breakdown-feature-spec-to-tasks
description: Decomposing an approved Confluence/feature spec into JIRA sub-tasks with
  dependencies.
when_to_use: Use when a spec is signed off and you need to slice it into actionable,
  ordered tasks.
group: design-and-analysis
kind: workflow
source_prompt: analyze/breakdown-feature-spec-to-tasks.md
---

# Breakdown Feature Specification Into JIRA Tasks

## Skill summary

- **Name:** `breakdown-feature-spec-to-tasks`
- **Description:** Decomposing an approved Confluence/feature spec into JIRA sub-tasks with dependencies.
- **When to use:** Use when a spec is signed off and you need to slice it into actionable, ordered tasks.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `analyze/breakdown-feature-spec-to-tasks.md`

## Examples

- The user asks for an end-to-end workflow that fits: Decomposing an approved Confluence/feature spec into JIRA sub-tasks with dependencies.
- Use when a spec is signed off and you need to slice it into actionable, ordered tasks.

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

Split a feature specification into cohesive, dependency-ordered JIRA sub-tasks that engineers can pick up independently without stepping on each other's work. Each task includes full context, relevant code samples from the source spec, and clear acceptance criteria.

This prompt is **mode-aware** per [`feature-specifications.md`](../feature-specifications/SKILL.md): the parent spec may be a broad **Business / product feature spec**, while the child technical slices should often be **Engineering implementation sub-specs**.

---

## Inputs

The operator must provide:

1. **Confluence page URL(s)** or source specification path(s)
2. **Parent JIRA issue**
3. **Project key**
4. **Cloud ID**

---

## Step 1 — Gather Source Material

### 1.1 Fetch the source specifications

Extract and catalog:

- schema definitions,
- code samples,
- endpoint definitions,
- file trees,
- acceptance criteria,
- dependency relationships,
- whether the source spec is acting as a parent overview or already as a narrow implementation slice.

### 1.2 Read code prompts

Read **all** code-prompt files from `skills/coding/` before proceeding. Build a full mental model of the implementation patterns, naming conventions, testing standards, and architectural boundaries.

### 1.3 Fetch the parent issue

Use `getJiraIssue` to get the parent issue details.

### 1.4 Determine the spec-mode split

Decide which of these patterns applies:

- **Pattern A:** parent spec is already one narrow engineering slice → subtasks may remain lightweight task tickets.
- **Pattern B:** parent spec is a broad business/product overview → child technical specs should usually become **Engineering implementation sub-specs**.

Default to **Pattern B** when the parent doc spans multiple layers, multiple runtime seams, or several dependency-ordered phases.

---

### 1.5 Catalog the consolidation work

The parent spec's POST hook ran a DRY consolidation pass, so the spec may commit to deleting existing functionality, encapsulating new behavior inside an existing component, or re-designing a component so it absorbs the new work instead of a redundant parallel implementation.

That work is not optional cleanup — it is what keeps responsibilities single, isolated, and clean. Catalog every consolidation the spec commits to and carry it into the task list:

- deletions and the call sites that must be repointed,
- encapsulations that keep a single owner for a responsibility,
- re-designs of existing components,
- the responsibility boundaries and interfaces the spec documented.

Each of these belongs in a specific dependency-ordered task, sequenced so the replacement lands before or with the deletion. A breakdown that ships the new construct and leaves the redundant one in place has reintroduced exactly the duplication the spec set out to remove.

---

## Step 2 — Identify Components and Dependencies

Decompose the feature into natural implementation layers.

Typical chain:

```text
1. Migration + Model + DAO + Domain Service
2. Utility classes / shared logic
3. Domain method additions
4. Application service integration
5. Router / API endpoints
6. UI / operational surfaces
7. Documentation / rollout / verification
```

### Grouping Principles

- group cohesive work together,
- split at dependency boundaries,
- identify parallelizable work,
- prefer one repo per task when possible,
- prefer single-person tasks,
- when a child task is a real technical slice, write it as an **Engineering implementation sub-spec**, not a vague ticket summary.

### Mode-aware breakdown rule

When the parent is a **Business / product feature spec**, use this shape by default:

- **Parent spec:** broad overview, journey, scope, rollout, stakeholder framing
- **Child specs / subtasks:** narrow engineering slices, each independently implementable, usually Mode B

Do not keep all children in business-spec mode if the actual work is technical and dependency-ordered.

---

## Step 3 — Write Each Sub-Task

## Step 3.1 Decide the child-spec mode

For each child task, decide whether it should be written as:

- a lightweight execution task, or
- a full **Engineering implementation sub-spec**.

If the child task introduces or changes real code, control flow, runtime behavior, or a technical ownership boundary, default to **Engineering implementation sub-spec**.

## Step 3.2 Title format

Use an active verb phrase.

Examples:

- `DB migration and domain layer for VendorNormalizationRule`
- `Backend API for vendor normalization rules`
- `02.a.1 — Owning One Agent Session Per Process`

If the repository already uses numbered engineering sub-specs, preserve that numbering convention.

## Step 3.3 Required body structure

Every child spec must open with the human-readable narrative sections required by [`feature-specifications.md`](../feature-specifications/SKILL.md). The exact structure depends on the chosen mode.

### Child Mode A — Business / product feature spec

Use this only when the child is still a broad feature slice rather than a narrow engineering seam.

Required opening:

- `## Context`
  - `### Changes` or `### Description`
  - `### Big Picture`
  - `### Existing structure we are extending` *(when applicable)*
  - `### What this document changes`
- `## The journey this plan owns a slice of` *(when applicable)*
- `## Control Flow: <hot-path-name> (Step-by-Step)` *(when applicable)*
- `## Code Reference`
- `## Scope`
- `## Acceptance Criteria`
- `## Dependencies`
- `## Repo`

### Child Mode B — Engineering implementation sub-spec

This is the default for technical child tasks. Follow the `02.a.1` onward pattern.

Required structure:

- metadata header under the H1 with available fields (`Status`, `Owner`, `Last updated`, `Parent spec`, `Branch`, `Repo`, `Approx. size`)
- `## 1. Context`
- `## 2. Why`
- `## 3. Current State`
- `## 4. Proposed Approach`
- `## 5. Domain Introductions`
- `## 6. End-to-End Flow`
- `## 7. Implementation Details`
- `## 8. Tests`
- `## 9. Acceptance Criteria`
- `## 10. Dependencies`

Additional rules for child Mode B specs:

- the sub-spec must be readable on its own,
- it must restate current-state truths relevant to the slice,
- it must explicitly correct stale parent-spec snippets when relevant,
- it must include implementation order, verification commands, and manual smoke guidance when applicable,
- every code block must be preceded by prose,
- central classes must include class docstring, main public method, and core helpers,
- helper-method docstrings must explain what the method does, who invokes it, and when it is used.

## Step 3.4 Include code samples

Code samples are mandatory. Include every relevant code sample from the source spec in exactly one child task. Prefer complete implementations over snippets.

Use:

- schema definitions,
- full class implementations,
- method signatures with bodies,
- endpoint definitions and response shapes,
- template snippets,
- file trees showing new vs modified files.

## Step 3.5 Acceptance criteria

Acceptance criteria must be specific and testable. Tie them to behaviors, outputs, or verification commands.

---

## Step 4 — Build Dependency Graph

After writing all tasks, produce an ASCII dependency graph showing:

- which tasks block which,
- which tasks can run in parallel,
- the critical path.

Example:

```text
Task 1: Foundation
    ├──→ Task 2: Shared utilities
    │       ├──→ Task 3: Feature A  ──┐
    │       └──→ Task 4: Feature B    ├──→ Task 5: Integration
    │                                 ┘
    └──→ Task 6: API layer
              └──→ Task 7: UI layer
```

---

## Step 5 — Push to JIRA

### 5.1 Determine issue type

Use `getJiraProjectIssueTypesMetadata` to find the correct sub-task issue type.

### 5.2 Create sub-tasks

For each task, use `createJiraIssue` with:

- `projectKey`
- `issueTypeName`
- `parent`
- `summary`
- `description`
- `contentFormat=markdown`
- inherited `components` and `fixVersions`

### 5.3 Create in dependency order

Create foundational tasks first.

### 5.4 Report results

After all tasks are created, produce a summary table:

| # | Key | Summary | Dependencies | Repo | Mode |
|---|---|---|---|---|---|
| 1 | AGI-XXXX | ... | None | repo-name | Mode B |

Include the dependency graph with actual issue keys.

### 5.5 Tag leads on parent issue

Post the standard comment on the parent issue once subtasks are created.

---

## Quality Checklist

Before pushing to JIRA, verify:

- [ ] every code sample from the source spec is included in exactly one task
- [ ] no task references a component that has not been built by a prior task in the dependency chain
- [ ] each task can be assigned independently without unnecessary merge conflicts
- [ ] acceptance criteria are specific and testable
- [ ] file trees show clearly what is new vs modified
- [ ] the dependency graph has no cycles
- [ ] context paragraphs explain why, not just what
- [ ] code-prompt conventions are referenced where applicable
- [ ] every child spec carries the human-readable narrative opening required by `feature-specifications.md`
- [ ] every technical child slice that needs standalone implementability is written as a **Mode B engineering implementation sub-spec**
- [ ] child Mode B specs include current-state truths, end-to-end flow, implementation details, tests, and dependencies

---

## Conventions

- use active verb phrases for task names,
- always specify the repo,
- always link back to the source spec,
- prefer complete code samples,
- map explicit source-spec acceptance criteria to the appropriate child task,
- when in doubt, favor fewer stronger child specs over many vague tickets,
- when a task is primarily a runtime or architecture seam, do **not** write it as a generic business-feature task — write it as an engineering implementation sub-spec.

## Final Note

Do not forget to include code samples from the original specifications. This is crucial to creating a task that offers clear context and examples.

Always publish the entire task to JIRA. Never truncate for any reason.
