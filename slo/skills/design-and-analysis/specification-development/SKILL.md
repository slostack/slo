---
name: specification-development
description: Pipeline workflow for taking a feature brief through the specification overview, standalone engineering sub-specs, and independent family verification.
when_to_use: Use when the user explicitly asks to write, spec out, plan, or break down a feature specification from a brief, issue, RFC, or feature request.
group: design-and-analysis
kind: workflow
source_prompt: workflows/specification-development.md
---

# Specification Development

## Skill summary

- **Name:** `specification-development`
- **Description:** Pipeline workflow for taking a feature brief through the specification overview, standalone engineering sub-specs, and independent family verification.
- **When to use:** Use when the user explicitly asks to write, spec out, plan, or break down a feature specification from a brief, issue, RFC, or feature request.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `workflows/specification-development.md`

## Examples

- The user asks: "Write a feature spec for this new capability."
- The user asks: "Plan the implementation of this issue before coding."
- The user asks: "Break this large feature into sub-specs."

## Guidance

This index entry is a pointer. The full, authoritative workflow lives in one
place to avoid drift:

> **Load and follow `skills/orchestration/workflows/specification-development.md`.**

That file lists the sub-skills it sequences at the top, then defines the three
pipeline steps (Overview → Standalone engineering sub-specs → Family verification,
with REVISE routed back to the owning step), the spec-file naming rule
(`<NN>-<feature>/overview.md` plus `<NN>.a.n-<slice>.md`; never `request.md`),
evidence-gated progression, and the exit condition. Do not re-derive the steps
from this entry — read the workflow file and execute it.

One rule is worth stating here because it governs every step: the design must
stay **DRY without losing cohesion**. A generated specification frequently
proposes functionality that already exists in the code — wholly, partially, or
as the responsibility an existing component already owns. The overview and each
sub-spec record a duplicate-code table and consolidate by composition,
encapsulation, extending the existing owner, or delete-and-replace; verification
searches independently for any duplicate that survives. Consolidation never
extracts trivial steps, such as a flush, out of the method they complete.

Sub-skills the workflow sequences (loaded on demand per step):

- Step 1 — `skills/design-and-analysis/feature-specifications/SKILL.md` (overview)
- Step 2 — `skills/design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md` (standalone engineering sub-specs)
- Step 3 — `skills/design-and-analysis/feature-specification-verification/SKILL.md` (family verification)
