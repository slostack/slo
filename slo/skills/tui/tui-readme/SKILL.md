---
name: tui-readme
description: Orientation guide for the Textual TUI prompt family.
when_to_use: Read before working on Textual TUI prompts so you know the TUI-specific
  scope and cross-links.
group: tui
kind: skill
source_prompt: tui/README.md
---

# TUI Prompt Family README

## Skill summary

- **Name:** `tui-readme`
- **Description:** Orientation guide for the Textual TUI prompt family.
- **When to use:** Read before working on Textual TUI prompts so you know the TUI-specific scope and cross-links.
- **Group:** `tui`
- **Kind:** `skill`
- **Source prompt:** `tui/README.md`

## Examples

- The task touches a Textual screen and you need the TUI prompt-family overview first.
- You want the narrow entry point for TUI conventions before opening the detailed build guide.

## Guidance

This subsection covers **Python terminal UIs** built with Textual under `src/tui/`. It focuses on application architecture, widget/screen composition, event routing, Rich rendering, TCSS organization, and testability.

Use this when the feature is a real in-process TUI — not a deploy script, not a browser SPA, and not an operator CLI that happens to print Rich tables.

## Files

| File | Scope |
|---|---|
| [`build-textual-tuis.md`](../build-textual-tuis/SKILL.md) | **Primary reference.** `App` structure, session injection, custom `Message` classes, slash-command routing, renderer adapters, modal flows, TCSS co-location, and pilot-based tests. |

## When to read this

- Adding or modifying `src/tui/app.py`
- Building new Textual widgets, screens, or modal flows
- Wiring slash commands, progress rendering, or transcript adapters
- Refactoring a TUI so widgets stay presentation-focused and domain logic stays in sessions / services

## Cross-links

- Typer CLI conventions — [`../skills/cli/build-typer-cli-apps/SKILL.md`](../../cli/build-typer-cli-apps/SKILL.md)
- Vue frontend conventions — [`../skills/frontend-vue/vue-coding-conventions/SKILL.md`](../../frontend-vue/vue-coding-conventions/SKILL.md)
- Named args + type hints — [`../skills/languages/python/named-arguments-and-type-hints/SKILL.md`](../../coding/named-arguments-and-type-hints/SKILL.md)
- Declarative structure — [`../skills/languages/python/declarative-method-structure/SKILL.md`](../../coding/declarative-method-structure/SKILL.md)
- Method docstrings — [`../skills/languages/python/method-docstrings/SKILL.md`](../../coding/method-docstrings/SKILL.md)
