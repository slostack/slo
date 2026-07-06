---
name: code-test-review
description: Pipeline workflow for turning a specification or task slice into tested code, structured review findings, and a completion assessment.
when_to_use: Use when the user explicitly asks to implement a spec, build a planned task, or take a verified feature slice from specification to tested code.
group: design-and-analysis
kind: workflow
source_prompt: workflows/code-test-review.md
---

# Code-Test-Review

## Skill summary

- **Name:** `code-test-review`
- **Description:** Pipeline workflow for turning a specification or task slice into tested code, structured review findings, and a completion assessment.
- **When to use:** Use when the user explicitly asks to implement a spec, build a planned task, or take a verified feature slice from specification to tested code.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `workflows/code-test-review.md`

## Examples

- The user asks: "Implement this feature spec."
- The user asks: "Build this task from the breakdown."
- The user asks: "Take this planned slice from spec to code."

## Guidance

This index entry is a pointer. The full, authoritative workflow lives in one
place to avoid drift:

> **Load and follow `skills/design-and-analysis/workflows/code-test-review.md`.**

That file lists the sub-skills it sequences at the top, then defines the three
pipeline steps (Code + Test Loop → Code Review → Completion Check), the manual
vs. auto confirmation behavior, and the exit condition. Do not re-derive the
steps from this entry — read the workflow file and execute it.

Sub-skills the workflow sequences (loaded on demand per step):

- Step 1 — `skills/coding/code-test-loop/SKILL.md`
- Step 2 — `skills/design-and-analysis/review-feature-code/SKILL.md`
- Step 3 — `skills/design-and-analysis/is-the-feature-completed/SKILL.md`
- Always-on — `named-arguments-and-type-hints`, `declarative-method-structure`,
  `method-docstrings`, `test-verification-policy` (all under `skills/coding/`)
