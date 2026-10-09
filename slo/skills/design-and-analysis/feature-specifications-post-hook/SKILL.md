---
name: feature-specifications-post-hook
description: Compatibility redirect to the Self-check and Revise stages of feature-specifications; independent verification remains separate.
when_to_use: Use only when an older caller names the post-hook; new callers load feature-specifications.
group: design-and-analysis
kind: skill
source_prompt: analyze/feature-specifications-post-hook.md
---

# Feature Specifications POST Hook — Compatibility Redirect

## Skill summary

- **Name:** `feature-specifications-post-hook`
- **Description:** Compatibility pointer, not an authoritative authoring owner.
- **When to use:** An older installed prompt asks for the POST hook.
- **Group:** `design-and-analysis`
- **Kind:** `skill`

## Examples

- An older caller asks for a POST-Hook Report after revising a draft.

## Guidance

Load [feature-specifications — Self-check](../feature-specifications/SKILL.md#self-check)
and follow [Revise and hand off](../feature-specifications/SKILL.md#revise-and-hand-off).
Use the existing Context Bundle, gathering missing context first. The Author
Self-check Report retains the legacy label POST-Hook Report. Re-run the complete
self-check after changes, not a second copy of the old procedure. Author READY is
not independent approval: hand off to separate verification once (workflow Step 2
when in the Specification Development workflow), then return findings to authoring.
This redirect never nests another independent review or publishes tasks.
