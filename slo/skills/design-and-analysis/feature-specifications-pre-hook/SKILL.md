---
name: feature-specifications-pre-hook
description: Compatibility redirect to the Gather context stage of feature-specifications; no separate authoring procedure.
when_to_use: Use only when an older caller names the pre-hook; new callers load feature-specifications.
group: design-and-analysis
kind: skill
source_prompt: analyze/feature-specifications-pre-hook.md
---

# Feature Specifications PRE Hook — Compatibility Redirect

## Skill summary

- **Name:** `feature-specifications-pre-hook`
- **Description:** Compatibility pointer, not an authoritative authoring owner.
- **When to use:** An older installed prompt asks for the PRE hook.
- **Group:** `design-and-analysis`
- **Kind:** `skill`

## Examples

- An old prompt asks for the PRE-Hook Context Bundle before drafting.

## Guidance

Load [feature-specifications — Gather context](../feature-specifications/SKILL.md#gather-context).
Follow its mandatory context stage and produce the Context Bundle (legacy label:
PRE-Hook Context Bundle) before drafting. Continue through Draft, Self-check and
Revise in that same authoritative skill; do not run a second hook procedure.
When a caller already completed that stage for this draft, reuse the bundle and
refresh changed context rather than repeat it. Formal workflow routing remains
`skills/design-and-analysis/workflows/specification-development.md`.
