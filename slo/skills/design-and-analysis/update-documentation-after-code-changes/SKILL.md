---
name: update-documentation-after-code-changes
description: After any non-trivial change — update docs/RESEARCH.md and code-prompts
  as needed.
when_to_use: Use post-merge or after a significant feature lands.
group: design-and-analysis
kind: workflow
source_prompt: update-documentation-after-code-changes.md
---

# Update Documentation After Code Changes

## Skill summary

- **Name:** `update-documentation-after-code-changes`
- **Description:** After any non-trivial change — update docs/RESEARCH.md and code-prompts as needed.
- **When to use:** Use post-merge or after a significant feature lands.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `update-documentation-after-code-changes.md`

## Examples

- The user asks: "Update documentation after code changes after this change."
- You are at the close-out phase and need the right post-change documentation workflow.

## Guidance

After completing any code change — feature, refactor, bug fix, or convention change — you must review and update the relevant documentation before the task is considered done.

---

## What to Update

### 1. RESEARCH.md — Codebase Index

Update `RESEARCH.md` whenever a code change alters the **structure, purpose, or interface** of a component.

| Change Type | Action |
|---|---|
| New domain, router, service, worker, agent, or tool added | Add a row to the relevant table |
| File or directory renamed or moved | Update the path in the relevant table |
| File or directory removed | Remove the row from the relevant table |
| New utility method or helper added to a shared module (e.g., `base.py`) | Add it to the utilities/methods table for that module |
| New configuration key or environment variable introduced | Add it to the Configuration Keys table |
| New migration created | Add it to the Database (Alembic) table |
| New test directory or test file category added | Add it to the Tests section |
| Technology added or removed from the stack | Update the Technology Stack table |
| Key stats changed (new domain, new agent, etc.) | Update the Key Stats table |

**Do not update** RESEARCH.md for:
- Bug fixes or logic changes that don't alter a component's described purpose
- Adding a test for an already-described service
- Internal refactoring with no change to public responsibility

### 2. Convention Documents — Code Prompts

Update the authoritative coding skill in `skills/coding/` for generic conventions, or the matching language-owned skill under `skills/languages/{python,go,typescript}/` for language-specific conventions.

| Change Type | Action |
|---|---|
| New architectural pattern introduced (e.g., a new return type convention) | Update the relevant code-prompt or create a new one |
| Existing convention changed (e.g., error handling now returns `[]` instead of strings) | Update the relevant code-prompt to reflect the new convention |
| Convention document contains an example that no longer matches the code | Update the example to match the current implementation |
| A skeleton or template in a code-prompt is outdated | Update it to reflect the canonical implementation |

**Do not update** code prompts for:
- One-off implementation details that don't represent a convention
- Changes that only affect a single file with no pattern implications

### 3. AGENTS.md — Agent Guidance

Update `AGENTS.md` when:
- A new code-prompt document is created (add it to the table)
- The agent/tool table changes (new agent, renamed tool, etc.)
- The architecture overview changes (new source directories, new control flows)

---

## Workflow

After completing a code change:

1. **Scan your changes** — review the files you modified, added, or removed.
2. **Check RESEARCH.md** — does the codebase index still accurately describe the components you touched? Update if not.
3. **Check code prompts** — did your change establish or modify a convention? Update the relevant code-prompt.
4. **Check AGENTS.md** — did you add a new code-prompt, agent, or tool? Update the table.
5. **Verify consistency** — ensure that examples in code-prompts match the actual implementation. If a code-prompt says "return an error string" but the code now returns `[]`, the code-prompt must be updated.

---

## Why This Matters

Documentation drift is silent technical debt. When convention documents describe one pattern but the code follows another, every future change risks introducing inconsistencies. Keeping documentation in sync with the code ensures that:

- AI agents generate code that follows current conventions, not outdated ones
- New contributors onboard to the actual architecture, not a stale description
- Code reviews catch deviations from documented standards
