---
name: specification-development
description: Pipeline workflow for taking a feature brief through context gathering, spec drafting, verification, and dependency-ordered task breakdown.
when_to_use: Use when the user explicitly asks to write, spec out, plan, or break down a feature specification from a brief, ticket, RFC, or feature request.
group: design-and-analysis
kind: workflow
source_prompt: workflows/specification-development.md
---

# Specification Development

## Skill summary

- **Name:** `specification-development`
- **Description:** Pipeline workflow for taking a feature brief through context gathering, spec drafting, verification, and dependency-ordered task breakdown.
- **When to use:** Use when the user explicitly asks to write, spec out, plan, or break down a feature specification from a brief, ticket, RFC, or feature request.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `workflows/specification-development.md`

## Examples

- The user asks: "Write a feature spec for this new capability."
- The user asks: "Plan the implementation of this ticket before coding."
- The user asks: "Break this large feature into child specs and tasks."

## Guidance

This index entry is a pointer. The full, authoritative workflow lives in one
place to avoid drift:

> **Load and follow `skills/design-and-analysis/workflows/specification-development.md`.**

That file lists the sub-skills it sequences at the top, then defines the three
pipeline steps (Spec with PRE/POST hooks → Verification → Task breakdown), the
spec-file naming rule (`specifications/<number>-<title>/overview.md`; never
`request.md`), the manual vs. auto confirmation behavior, and the exit
condition. Do not re-derive the steps from this entry — read the workflow file
and execute it.

Sub-skills the workflow sequences (loaded on demand per step):

- Step 1 — `feature-specifications-pre-hook`, `feature-specifications`,
  `feature-specifications-post-hook` (all under `skills/design-and-analysis/`)
- Step 2 — `skills/design-and-analysis/feature-specification-verification/SKILL.md`
- Step 3 — `skills/design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md`
