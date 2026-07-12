---
name: generate-research-md
description: Regenerate the repository docs/RESEARCH.md codebase index.
when_to_use: Use when docs/RESEARCH.md is stale or after structural changes added,
  removed, or moved major components.
group: design-and-analysis
kind: skill
source_prompt: analyze/generate-research-md.md
---

# Generate docs/RESEARCH.md

## Skill summary

- **Name:** `generate-research-md`
- **Description:** Regenerate the repository docs/RESEARCH.md codebase index.
- **When to use:** Use when docs/RESEARCH.md is stale or after structural changes added, removed, or moved major components.
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Source prompt:** `analyze/generate-research-md.md`

## Examples

- The user asks: "Refresh docs/RESEARCH.md after the skills refactor."
- You added new source directories and need the codebase index to reflect them.

## Guidance

Use this prompt when `skills/orientation/research/SKILL.md` is empty, missing sections, or needs to be updated after adding new domains, routers, workers, or integrations.

---

## Goal

Produce a complete `docs/RESEARCH.md` in the repository's `docs/` folder that serves as a **comprehensive codebase index** for AI agents. The file must allow any agent to locate any component — domain, router, service, worker, event handler, or integration — without exhaustive file searching.

---

## Step 1 — Explore the Full Codebase

Read and explore all of the following before writing:

1. `skills/orientation/readme/SKILL.md` — project name, business domain, high-level purpose
2. `pyproject.toml` (or `package.json`) — technology stack versions
3. `config/cfg.py` — environment variable inventory
4. **All files under `src/`** — use Glob and Read tools to map every module
5. **All files under `tests/`** — use to confirm domain and service names
6. **All files under `<feature-specifications-root>/`** — for Confluence page links if available
7. `AGENTS.md` — for any Confluence base URLs or external API links already documented

Use the file structure itself as the source of truth. Do not rely on assumptions or outdated documentation.

---

## Step 2 — Required Sections

`skills/orientation/research/SKILL.md` must contain all of the following sections. Only omit a section if the project genuinely does not have that layer.

---

### 1. Header

```markdown
# docs/RESEARCH.md — [Project Name] Codebase Index

> AI agent reference guide. Read `AGENTS.md` first, then use this file to locate any domain, service, router, worker, or integration.
```

---

### 2. Table of Contents

List all sections with anchor links. Update this whenever sections are added or renamed.

---

### 3. Project Overview

Include:

- What the project does in 1-2 sentences
- High-level architecture description
- Standard control flow (e.g., `router/worker → application service → domain service → DAO → database`)
- A key stats table showing counts of: domain modules, API routers, Celery workers, application services, DB migrations, microapps

Format:

```markdown
## Project Overview

**[Project Name]** is a [brief description].

**Architecture:** [N] independently deployable microapps, [N]+ domain-driven modules, [N]+ Celery workers, [orchestration system].

**Control flow:**
```
router/worker → application service → domain service → DAO → database
```

| Layer | Count |
|-------|-------|
| Domain modules | N |
| API routers | N |
| ...
```

---

### 4. Technology Stack

A table with every major dependency and its version. Derive from `pyproject.toml` or `package.json`.

Format:

```markdown
## Technology Stack

| Category | Technologies |
|----------|-------------|
| API | FastAPI 0.x, Pydantic, OpenAPI |
| ORM | SQLAlchemy 2.0+ async, asyncpg, Alembic |
| ...
```

---

### 5. Confluence Feature Specifications (if applicable)

If the project uses Confluence for feature documentation, provide:

- A note explaining when to fetch Confluence pages
- The base URL for the Confluence space
- A table of all known feature specification pages grouped by topic

Format:

```markdown
## Confluence Feature Specifications

> When building or modifying a feature, fetch the relevant page(s) below to understand the full business intent.
>
> **Base URL:** `https://<org>.atlassian.net/wiki/spaces/<Space>/pages/`

| Step | Page | What it covers |
|------|------|----------------|
| Step N | `Page Title` | Summary of content |
```

If Confluence is not used, omit this section entirely.

---

### 6. Repository Root

List and describe every important file at the repository root level:

```markdown
## Repository Root

| File/Folder | Purpose |
|-------------|---------|
| `main.py` | Application entrypoint — registers microapps, starts DBOS, binds routes |
| `AGENTS.md` | AI agent guidance and coding conventions |
| `docs/RESEARCH.md` | This file — complete codebase index |
| `pyproject.toml` | Dependency manifest and project metadata |
| `config/cfg.py` | Centralised environment variable access |
| `alembic/` | Database migration scripts |
| `environments/` | `.env` files for each environment |
```

---

### 7. Configuration & Connectors

Document the config system:

- How environment variables are accessed (e.g., `cfg("KEY")`)
- Key config groupings (database, redis, external APIs, feature flags)
- List the most important config keys agents need to know about

---

### 8. Database (Alembic or equivalent)

Document:

- Migration tool and location
- How to create and run migrations
- Any important migration conventions

---

### 9. Microapps (`src/apps/`)

For each app under `src/apps/`, list:

- App name (folder)
- What business domain it covers
- Entry point file
- Key services it contains

Format:

```markdown
## Microapps (`src/apps/`)

| App | Business Domain | Entry Point | Key Services |
|-----|----------------|-------------|--------------|
| `app_name` | Description | `src/apps/app_name/app.py` | ServiceA, ServiceB |
```

---

### 10. Domains (`src/domains/`)

This is the **most important section**. For every domain folder under `src/domains/`, list:

- Domain name (folder)
- Database table name (from `model.py`)
- What the domain represents
- Key methods in `service.py` that agents will call

Group by business area. Example groupings: Accounts, Calls, Payments, Messaging, Workers.

Format:

```markdown
## Domains (`src/domains/`)

### Accounts

| Domain | Table | Description | Key service methods |
|--------|-------|-------------|---------------------|
| `account` | `accounts` | Core account record | `get_by_id`, `list_by_client`, `update_status` |
```

---

### 11. Routers (`src/routers/`)

For each router file, list:

- Router file name
- URL prefix
- What endpoints it exposes (method + path + one-line description)

Group by feature area.

Format:

```markdown
## Routers (`src/routers/`)

### Accounts

| File | Prefix | Endpoints |
|------|--------|-----------|
| `account_router.py` | `/accounts` | `GET /` list accounts, `POST /` create account, `GET /{id}` get by ID |
```

---

### 12. Application Services (`src/services/` or `src/apps/*/services/`)

For each application service, list:

- Class name
- What it orchestrates
- Which router or worker invokes it

Format:

```markdown
## Application Services

| Service | Orchestrates | Invoked by |
|---------|-------------|------------|
| `AccountCreateAppService` | Creates account, syncs to SOR, emits event | `POST /accounts` |
```

---

### 13. Tasks & Workers (`src/tasks/`)

For each Celery or DBOS worker, list:

- Task name (as registered)
- File path
- What it does
- What triggers it (beat schedule, event, manual)

Format:

```markdown
## Tasks & Workers (`src/tasks/`)

| Worker | Task name | Trigger | What it does |
|--------|-----------|---------|-------------|
| `sync_accounts_worker` | `tasks.sync_accounts` | Beat: every 15 min | Syncs account status from SOR |
```

---

### 14. Events (`src/events/`)

List every event type and its handler chain:

- Event name / constant
- Where it is published
- Which handler(s) consume it
- What the handler does

---

### 15. Integrations (`src/integrations/`)

For each integration folder, list:

- Service name
- What it provides
- Client file path
- Key methods

---

### 16. Shared Source Modules

Any shared utilities, middleware, auth, or helpers that don't fit in the above categories. List file path and purpose.

---

### 17. Tests (`tests/`)

Map the test directory structure to the source structure:

- List test files and what domain/service/router they test
- Note any important fixtures or factories

---

### 18. Infrastructure & Environments

Document:

- Environment files and what each one is for
- Docker compose setup (if present)
- How to start the application locally
- CI/CD pipeline overview (if known)

---

### 19. Documentation (`skills/`)

A table of every folder under `skills/` and what it contains. This helps agents find existing documentation before creating new files.

---

## Step 3 — Keeping skills/orientation/research/SKILL.md Current

skills/orientation/research/SKILL.md must be updated whenever:

- A new domain module is added to `src/domains/`
- A new router is added to `src/routers/`
- A new application service is created
- A new Celery or DBOS worker is registered
- A new integration is added under `src/integrations/`
- A new Confluence feature specification page is created

The `skills/design-and-analysis/update-documentation-after-code-changes/SKILL.md` file (if present) specifies the exact update procedure for each change type.

---

## Step 4 — Writing Rules

- Every entry must correspond to a real file or entity that currently exists in the repo
- Use the actual table names, class names, and file paths from the source — do not paraphrase
- Confluence page links must be complete URLs, not relative paths
- Group entries by business domain, not alphabetically — agents think in terms of features, not file names
- Keep descriptions to one line — agents need to scan quickly, not read paragraphs
- If a section is partially incomplete, add a `> Note: [N] additional entries not yet catalogued` line so agents know to search manually for uncatalogued items

---

## Step 5 — Validation Checklist

Before saving, confirm:

- [ ] Every folder under `src/domains/` appears in the Domains section
- [ ] Every router file under `src/routers/` appears in the Routers section
- [ ] Every worker registered in `src/tasks/worker.py` appears in the Tasks section
- [ ] Every folder under `src/integrations/` appears in the Integrations section
- [ ] The Table of Contents links match the actual section headings
- [ ] All Confluence URLs are complete (not relative paths)
- [ ] The technology stack matches `pyproject.toml` or `package.json`
