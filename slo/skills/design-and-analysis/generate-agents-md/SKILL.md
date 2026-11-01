---
name: generate-agents-md
description: Regenerate the repository AGENTS.md file from the current codebase.
when_to_use: Use when AGENTS.md is stale, incomplete, or needs to reflect new conventions,
  components, or architecture.
group: design-and-analysis
kind: skill
source_prompt: analyze/generate-agents-md.md
---

# Generate AGENTS.md

## Skill summary

- **Name:** `generate-agents-md`
- **Description:** Regenerate the repository AGENTS.md file from the current codebase.
- **When to use:** Use when AGENTS.md is stale, incomplete, or needs to reflect new conventions, components, or architecture.
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Source prompt:** `analyze/generate-agents-md.md`

## Examples

- The user asks: "Regenerate AGENTS.md after the new CLI and TUI landed."
- You changed project conventions and need the root agent guide to match reality.

## Guidance

Use this prompt when `AGENTS.md` is empty, missing sections, or needs to be regenerated after significant project changes.

---

## Goal

Produce a complete `AGENTS.md` at the repository root that serves as the **primary AI agent entry point** for the project. The file must allow any AI agent to orient itself, understand coding conventions, navigate the codebase, and produce consistent code — without needing to ask follow-up questions.

---

## Step 1 — Read These Files First

Before writing anything, read the following files in order:

1. `README.md` — project purpose, setup instructions, how to run locally
2. `pyproject.toml` (or `package.json`) — dependency list, project name, scripts
3. `config/cfg.py` (or equivalent config entrypoint) — environment variable inventory
4. `skills/coding/coding-rules/SKILL.md` plus the applicable language/framework/test owners — coding standards and architectural patterns
5. All files under `skills/design-and-analysis/` — documentation and analysis conventions
6. `src/` directory structure — identify microapps, domains, routers, services, workers, events, integrations

Explore the full `src/` tree before writing. Do not rely on assumptions.

---

## Step 2 — Required Sections

`AGENTS.md` must contain all of the following sections. Omit a section only if it genuinely does not apply to this project.

### 1. Header

```markdown
# AGENTS.md

This file provides guidance for AI agents working with the [Project Name] codebase.
It serves as the primary entry point for understanding conventions, architecture, and how to build features.
```

---

### 2. Coding Guidelines & Conventions

A table listing every file under `skills/coding/` with a one-line description of its purpose.

Format:

```markdown
## Coding Guidelines & Conventions

Generic coding standards and architectural patterns are documented in `skills/coding/`; language-specific recipes are documented under `skills/languages/`.
Agents **must** consult these files before writing or modifying code.

| File | Purpose |
|------|---------|
| `filename.md` | Short description |
```

Mark the most important entry-point file as `**Start here.**`

---

### 3. External API References

A table of every external third-party service the project integrates with, linking to its API documentation.

Format:

```markdown
## External API References

| Service | API Docs |
|---------|----------|
| **ServiceName** | [Docs URL](https://...) — brief description of what endpoints are available |
```

If API docs URLs are not known, note that they should be added here.

---

### 4. Application Architecture

Document the actual control flow of the application. Include:

- The standard request/event processing path (e.g., `router → service → DAO → database`)
- A list of microapps or top-level modules under `src/apps/` (if present), with a one-line description of each
- Any background processing pipelines (Celery, DBOS, NATS, etc.)

Format:

```markdown
## Application Architecture

The standard control flow is:

```
router/worker → application service → domain service → DAO → database
```

### Microapps (`src/apps/`)

| App | Purpose |
|-----|---------|
| `app_name` | Description |
```

---

### 5. Analyzing the Codebase

Link to the analysis guides in `skills/design-and-analysis/`.

Format:

```markdown
## Analyzing the Codebase

The ``skills/design-and-analysis/`` directory contains guides for navigating and documenting the codebase.

| File | Purpose |
|------|---------|
| `find-how-it-works/SKILL.md` | How to trace a feature from entry point through to database |
| `feature-specifications/SKILL.md` | How to write a feature's specification overview (`overview.md`) |
| `generate-agents-md/SKILL.md` | How to generate or regenerate this AGENTS.md file |
| `generate-research-md/SKILL.md` | How to generate or regenerate RESEARCH.md |
```

---

### 6. Feature Documentation & Reference Implementations

Link to the `<feature-specifications-root>/` directory.

```markdown
## Feature Documentation & Reference Implementations

The ``<feature-specifications-root>/`` directory contains specifications for completed features.
Use these as reference material and as templates when writing new feature specifications.

> Feature documentation will be added here as features are implemented.
```

---

### 7. Feature Requests & Implementation Plans

Link to the `<feature-requests-root>/` directory. If feature requests exist, list them in a table.

---

### 8. Writing Unit Tests

Document:

- Testing framework (e.g., `pytest` + `pytest-asyncio`)
- How to run tests (exact command, including any env loading)
- `tests/` directory structure with a short description of each folder
- Key conventions: fixture pattern, database isolation, mocking approach

Format:

```markdown
## Writing Unit Tests

### Testing Infrastructure

- **Framework:** `pytest` with `pytest-asyncio` (session-scoped event loop)
- **Run tests:** `loadenv environments/.env.local && poetry run pytest -s tests/`
- ...

### Test Directory Structure

```
tests/
├── conftest.py     # Master fixture setup
├── factory.py      # Test data factories
├── domains/        # Domain service tests
├── services/       # Application service tests
...
```

### Common Testing Patterns
[Show key patterns with code examples]
```

---

### 9. Diagrams & Visual Documentation

Specify the diagramming tool and diagram types to use. Example:

```markdown
## Diagrams & Visual Documentation

Use **Mermaid** syntax for all diagrams in specification documents.
Useful types: `sequenceDiagram`, `stateDiagram-v2`, `graph LR`, `flowchart`.
```

---

### 10. RESEARCH.md Reference

Add a pointer to RESEARCH.md:

```markdown
## Codebase Index

See ``RESEARCH.md`` for a complete index of every domain, router, service, worker, event handler, and integration in this repository.
When building or modifying a feature, consult RESEARCH.md first to find existing implementations before writing new code.
To regenerate RESEARCH.md, follow ``skills/design-and-analysis/generate-research-md/SKILL.md``.
```

---

## Step 3 — Writing Rules

- Use present tense throughout
- Use imperative voice for agent instructions ("Read X before...", "Consult Y when...")
- All file references must be relative markdown links
- Tables must be used wherever multiple items of the same type are listed
- Keep section descriptions concise — one line per file/service/microapp is sufficient
- Do not invent content — every link, path, and description must correspond to something that actually exists in the repo
- If a section applies but is not yet populated (e.g., no feature docs yet), include the section header with a `> Note:` stub rather than omitting it entirely

---

## Step 4 — Validation Checklist

Before saving, confirm:

- [ ] Every generic file in `skills/coding/` and every applicable language owner is represented in the Coding Guidelines table
- [ ] Every file in `skills/design-and-analysis/` is listed in the Analyzing the Codebase table
- [ ] The test run command is correct and matches the project's `Makefile` or README
- [ ] All markdown links resolve to real files
- [ ] The architecture section reflects the actual `src/` structure
- [ ] RESEARCH.md is referenced and the regeneration prompt is linked
