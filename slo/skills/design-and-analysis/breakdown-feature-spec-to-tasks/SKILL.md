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

## Artifact paths and authoring contract

Use [the canonical authoring artifact paths and skill discovery](../feature-specifications/SKILL.md#artifact-paths-and-skill-discovery).
Repository overrides win over generic defaults. Every family requires overview.md
with product framing and separate standalone engineering sub-specs. Neither part
can substitute for the other, even for small features.

## Guidance

## Purpose

Split a feature specification into cohesive, dependency-ordered JIRA sub-tasks that engineers can pick up independently without stepping on each other's work. Each task includes full context, relevant code samples from the source spec, and clear acceptance criteria.

Follow the single-family contract in [`feature-specifications.md`](../feature-specifications/SKILL.md): the product overview and standalone engineering sub-specs are always required together.

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

Read `skills/coding/coding-rules/SKILL.md` and the applicable language/framework/test skills before proceeding. Build a bounded mental model of the implementation patterns, naming conventions, testing standards, and architectural boundaries.

### 1.3 Fetch the parent issue

Use `getJiraIssue` to get the parent issue details.

### 1.4 Inventory the complete specification family

Locate overview.md and all standalone engineering sub-specs. If the source is one
narrow slice, locate its overview and sibling specs before task breakdown. If a
required artifact is missing, return to authoring; do not replace it with a ticket.
A complete narrow sub-spec may be divided into lightweight execution tickets,
provided each ticket links to that implementation-ready contract. Broad features
need multiple cohesive sub-specs, split at layer and runtime dependency boundaries.

---

### 1.5 Catalog the consolidation work

The parent spec's author self-check ran a DRY consolidation pass, so the spec may commit to deleting existing functionality, encapsulating new behavior inside an existing component, or re-designing a component so it absorbs the new work instead of a redundant parallel implementation.

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

### Required family breakdown

- **Product overview:** journey, scope, rollout and stakeholder framing.
- **Standalone engineering sub-specs:** narrow, independently implementable slices.
- **Execution tickets:** dependency-ordered work linked to the corresponding sub-spec.

Never substitute a broad product summary for an engineering sub-spec.

---

## Step 3 — Write Each Sub-Task

## Step 3.1 Map each task to its engineering sub-spec

For each task, identify the standalone engineering sub-spec that owns its code,
control flow, runtime behavior or technical boundary. Create or refine that
sub-spec if needed. Lightweight execution tickets link to the full contract;
they do not create an alternative specification shape.

## Step 3.2 Title format

Use an active verb phrase.

Examples:

- `DB migration and domain layer for VendorNormalizationRule`
- `Backend API for vendor normalization rules`
- `02.a.1 — Owning One Agent Session Per Process`

If the repository already uses numbered engineering sub-specs, preserve that numbering convention.

## Step 3.3 Required body structure

Every standalone engineering sub-spec must open with the human-readable narrative sections required by [`feature-specifications.md`](../feature-specifications/SKILL.md). Retain the product framing in its overview as well.

### Product framing retained in the overview

Keep the following product context in the family overview. For broad slices, carry
relevant context into the engineering sub-spec without replacing its engineering structure.

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

### Required standalone engineering sub-spec

Every technical child slice requires this structure. Follow the `02.a.1` onward pattern.

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

Additional rules for standalone engineering sub-specs:

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

| # | Key | Summary | Dependencies | Repo | Engineering sub-spec |
|---|---|---|---|---|---|
| 1 | AGI-XXXX | ... | None | repo-name | <numbered sub-spec path> |

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
- [ ] every technical child slice is written as a **standalone engineering sub-spec**
- [ ] standalone engineering sub-specs include current-state truths, end-to-end flow, implementation details, tests, and dependencies

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
