---
name: readme
description: Overview of the code-prompt library, its families, and the documentation
  triad.
when_to_use: Read when you need to understand how the prompt library is organized
  or which prompt family applies.
group: orientation
kind: skill
source_prompt: README.md
---

# Prompt Library README

## Skill summary

- **Name:** `readme`
- **Description:** Overview of the code-prompt library, its families, and the documentation triad.
- **When to use:** Read when you need to understand how the prompt library is organized or which prompt family applies.
- **Group:** `orientation`
- **Kind:** `skill`
- **Source prompt:** `README.md`

## Examples

- The user asks: "How is the prompt library structured?"
- You need a high-level map before drilling into a specific convention file.

## Guidance

Coding instruction templates that teach Claude how to build features in your codebase. These are designed to be included in your project's `skills/orientation/claude/SKILL.md` or `AGENTS.md` to establish consistent coding conventions.

## What are code prompts?

Code prompts are detailed instruction files that define **how** to write code in a specific codebase: folder structure, naming conventions, patterns for services/workers/routers/tests, and more. They're the "institutional knowledge" that makes Claude produce code that looks like your team wrote it.

## Directory Structure

```
code-prompts/
├── skills/orientation/readme/SKILL.md                              # This file
├── skills/orientation/claude/SKILL.md                              # Root entry point — tells Claude to read AGENTS.md first
├── AGENTS.md                              # Agent guidance — coding conventions table, architecture, testing patterns
├── skills/orientation/research/SKILL.md                            # Example codebase index — a worked order-management platform index (domains, routers, services, workers, integrations)
├── analyze/                               # Analysis & reporting prompts (not coding — understanding & documenting)
│   ├── feature-specifications.md          # Style guide for writing technical specs
│   ├── find-how-it-works.md               # How to trace a feature through the codebase
│   ├── generate-agents-md.md              # Prompt to generate/regenerate AGENTS.md
│   ├── generate-research-md.md            # Prompt to generate/regenerate skills/orientation/research/SKILL.md
│   ├── daily-morning-standup-report.md    # Generate daily standup summaries from git/JIRA
│   ├── daily-priorities.md                # Generate prioritized daily task lists
│   ├── weekly-update-generator.md         # Generate weekly progress reports
│   └── weekly-bottleneck-report-generator.md  # Identify blockers and bottlenecks
├── skills/coding/application-structure/SKILL.md               # Start here — folder layout, config, middleware
├── skills/coding/build-domain-features/SKILL.md               # Domain-driven design (dao.py, model.py, service.py)
├── skills/coding/build-routers/SKILL.md                       # FastAPI router conventions, response wrappers
├── skills/coding/build-application-services/SKILL.md          # Application service invoke() pattern
├── skills/coding/build-clients/SKILL.md                       # External API client patterns
├── skills/coding/build-event-handlers/SKILL.md                # Event handler routing and dispatch
├── skills/coding/build-celery-workers/SKILL.md                # Celery worker conventions
├── skills/coding/build-dbos-workflow-orchestration-pattern/SKILL.md  # DBOS durable workflows
├── skills/coding/build-schedulers-tasks-with-dbos/SKILL.md    # DBOS task scheduling
├── skills/coding/build-partitioned-events/SKILL.md            # Consistent hashing for event partitioning
├── skills/coding/build-react-agent-with-langgraph/SKILL.md    # LangGraph ReAct agent patterns
├── skills/coding/build-agent-tools/SKILL.md                   # LangChain @tool conventions
├── skills/coding/bootstrap-project-scaffolding/SKILL.md       # Project scaffolding and initial setup
├── skills/coding/generate-swagger-documentation/SKILL.md      # Generate OpenAPI/Swagger docs across services
├── skills/coding/declarative-method-structure/SKILL.md        # Code style — flat code, early returns
├── skills/design-and-analysis/derive-new-convention/SKILL.md              # Meta-prompt — derive conventions when no code-prompt exists
├── skills/design-and-analysis/distill-learnings/SKILL.md                  # Distill reusable insights into workspace-level LEARNINGS.md
├── skills/coding/method-docstrings/SKILL.md                   # Google-style docstrings
├── skills/coding/named-arguments-and-type-hints/SKILL.md      # Named args + type hints policy
├── skills/git-ops/branching-and-commit-conventions/SKILL.md    # Git workflow conventions
├── skills/design-and-analysis/review-feature-code/SKILL.md                 # Structured code review process
├── skills/coding/test-verification-policy/SKILL.md            # Test coverage requirements
├── skills/coding/test-graphs-and-agents/SKILL.md              # Testing LangGraph agents
├── skills/coding/setup-dependencies-and-tests/SKILL.md        # PostgreSQL, Docker, test fixtures
├── skills/coding/setup-alembic/SKILL.md                       # Alembic migration setup
├── skills/coding/switch-environments-and-run-tests/SKILL.md   # Environment switching + test execution
├── skills/coding/python-path-and-import-resolution/SKILL.md   # PYTHONPATH convention
└── skills/design-and-analysis/update-documentation-after-code-changes/SKILL.md  # Keep docs in sync with code
```

## Installation

### Option 1: Copy individual files into your project

The `docs` folder can be added to `.gitignore` and `.dockerignore`. 

```bash
# Copy specific prompts you need
cp claude-md/skills/coding/build-domain-features/SKILL.md /path/to/your/project/docs/code-prompts/
cp claude-md/skills/coding/build-routers/SKILL.md /path/to/your/project/docs/code-prompts/
```

### Option 2: Reference from skills/orientation/claude/SKILL.md

Link your project's `skills/orientation/claude/SKILL.md` to find these files

```markdown
## Coding Conventions

See the code prompts in `docs/code-prompts/` for detailed patterns:
- `Application Structure` — **Start here**
- `Build Domain Features`
- `Build Routers`
...
```

## Configuration

These templates use `{{PLACEHOLDER}}` variables for project-specific values. After copying, search and replace:

| Placeholder | Description | Example |
|---|---|---|
| `{{PROJECT_NAME}}` | Your project name | `MyApp` |
| `{{project_module}}` | Python module name (lowercase) | `myapp` |
| `{{MONOREPO_NAME}}` | Monorepo name (if applicable) | `orders-platform` |
| `{{API_BASE_URL}}` | Your API base URL | `https://api.example.com` |
| `{{DOMAIN}}` | Your domain name | `example.com` |
| `{{PRODUCT_NAME}}` | Product identifier | `MyProduct` |

Most files are already generic and require no placeholder replacement.

---

## Root Documentation Files

These three files form the **documentation triad** that gives Claude full context about your project. They are meant to be placed at your repository root and referenced from each other.

### skills/orientation/claude/SKILL.md — Entry Point

`skills/orientation/claude/SKILL.md` is the **first file Claude reads** when it enters your repository. It acts as a gatekeeper:

```
When asked to write, modify, or reason about code in this repository,
read AGENTS.md first. Skip this for general questions.
```

**How to use:**
- Place at your repository root
- Keep it short — it should only point to `AGENTS.md` and `skills/orientation/research/SKILL.md`
- Add project-specific overrides here (e.g., JIRA spec storage paths, special conventions)

### AGENTS.md — Agent Guidance

`AGENTS.md` is the **operating manual** for AI agents working in your codebase. It contains:

- **Coding conventions table** — links to every code prompt with a one-line purpose description
- **External API references** — links to vendor API docs
- **Architecture overview** — control flow, application structure
- **Analysis guides** — how to trace features, write specs, generate docs
- **Testing patterns** — fixtures, factories, mocking conventions

**How to use:**
- Place at your repository root
- Update the conventions table whenever you add/remove a code prompt
- Reference it from `skills/orientation/claude/SKILL.md` as the primary reading target
- Regenerate it using `skills/design-and-analysis/generate-agents-md/SKILL.md` after major project changes

### skills/orientation/research/SKILL.md — Codebase Index

`skills/orientation/research/SKILL.md` is a **worked example** of the RESEARCH.md pattern — a complete map of a fictional order-management platform. Use it as a reference for what a real index should catalog so agents can locate anything without exhaustive file searching:

- **Technology stack** — versions of all frameworks, databases, tools
- **Wiki/spec links** — business context for every feature area (grouped by feature, one link per page)
- **Services** — every monorepo member and its router prefix
- **Domains** — every domain module with its DAO, model, service files
- **Routers** — every HTTP endpoint controller
- **Application services** — every orchestration service
- **Workers** — every Celery/DBOS background task
- **Events** — every event handler and stream
- **Integrations** — every external API client
- **Tests** — test directory structure and conventions
- **Infrastructure** — Docker, environments, config files

**How to use:**
- Place your project's own index at your repository root
- Generate it using `skills/design-and-analysis/generate-research-md/SKILL.md`
- Update it after adding new domains, routers, workers, or integrations (see `skills/design-and-analysis/update-documentation-after-code-changes/SKILL.md`)
- Keep it under 1000 lines — it's an index, not documentation

---

## Code Prompt Reference

### Architecture & Structure

| File | What it covers |
|------|---------------|
| [skills/coding/application-structure/SKILL.md](../../coding/application-structure/SKILL.md) | **Start here.** Full application folder structure, middleware, config, domains, services, workers |
| [skills/coding/bootstrap-project-scaffolding/SKILL.md](../../coding/bootstrap-project-scaffolding/SKILL.md) | Project scaffolding, initial setup, and directory creation |
| [skills/coding/build-routers/SKILL.md](../../coding/build-routers/SKILL.md) | FastAPI router patterns, base controller, response objects, testing controllers |
| [skills/coding/build-domain-features/SKILL.md](../../coding/build-domain-features/SKILL.md) | Domain-driven design: model.py, dao.py, service.py, events |
| [skills/coding/build-application-services/SKILL.md](../../coding/build-application-services/SKILL.md) | Application service `invoke()` pattern, step methods, orchestration |

### Workers & Events

| File | What it covers |
|------|---------------|
| [skills/coding/build-celery-workers/SKILL.md](../../coding/build-celery-workers/SKILL.md) | Celery worker conventions, async bridging, retry config, context propagation |
| [skills/coding/build-dbos-workflow-orchestration-pattern/SKILL.md](../../coding/build-dbos-workflow-orchestration-pattern/SKILL.md) | DBOS watcher pattern for multi-step durable workflows |
| [skills/coding/build-schedulers-tasks-with-dbos/SKILL.md](../../coding/build-schedulers-tasks-with-dbos/SKILL.md) | DBOS task scheduling, cron workflows, enqueuing |
| [skills/coding/build-event-handlers/SKILL.md](../../coding/build-event-handlers/SKILL.md) | Event handler architecture, base handler routing, filter patterns |
| [skills/coding/build-partitioned-events/SKILL.md](../../coding/build-partitioned-events/SKILL.md) | Event partitioning with consistent hashing |

### External Integrations

| File | What it covers |
|------|---------------|
| [skills/coding/build-clients/SKILL.md](../../coding/build-clients/SKILL.md) | HTTP client patterns (aiohttp/httpx), DAOs, error handling, testing |

### AI & Agents

| File | What it covers |
|------|---------------|
| [skills/coding/build-react-agent-with-langgraph/SKILL.md](../../coding/build-react-agent-with-langgraph/SKILL.md) | LangGraph ReAct agent patterns, state, nodes, routing, graph assembly |
| [skills/coding/build-agent-tools/SKILL.md](../../coding/build-agent-tools/SKILL.md) | LangChain agent tool conventions, @tool decorator, async persistence |
| [skills/coding/test-graphs-and-agents/SKILL.md](../../coding/test-graphs-and-agents/SKILL.md) | Testing LangGraph agents: nodes, routing, graph construction, mocking |

### Code Quality & Conventions

| File | What it covers |
|------|---------------|
| [skills/coding/declarative-method-structure/SKILL.md](../../coding/declarative-method-structure/SKILL.md) | Single decision per method, guard clauses, strategy patterns, no nested conditionals |
| [skills/coding/method-docstrings/SKILL.md](../../coding/method-docstrings/SKILL.md) | Google-style docstrings for services, clients, workers, RPC methods |
| [skills/coding/named-arguments-and-type-hints/SKILL.md](../../coding/named-arguments-and-type-hints/SKILL.md) | Named arguments for 2+ params, explicit type hints everywhere |
| [skills/git-ops/branching-and-commit-conventions/SKILL.md](../../git-ops/branching-and-commit-conventions/SKILL.md) | Branch naming, commit message structure, git workflow |

### Testing

| File | What it covers |
|------|---------------|
| [skills/coding/test-verification-policy/SKILL.md](../../coding/test-verification-policy/SKILL.md) | Every code change needs passing tests covering all decision points |
| [skills/coding/setup-dependencies-and-tests/SKILL.md](../../coding/setup-dependencies-and-tests/SKILL.md) | PostgreSQL setup, Docker Compose, transactional test fixtures |
| [skills/coding/switch-environments-and-run-tests/SKILL.md](../../coding/switch-environments-and-run-tests/SKILL.md) | loadenv helper, environment switching, test execution |

### Integration Tests (cross-service)

| File | What it covers |
|------|---------------|
| [skills/integration-tests/01-test-setup/SKILL.md](../../integration-tests/01-test-setup/SKILL.md) | Stack setup, Docker orchestration, DB seeding, env isolation. **Hard Constraints** block at top — no NATS subs, one service per cluster, ordered Backgrounds, explicit feature-flag preconditions |
| [skills/integration-tests/02-test-execution/SKILL.md](../../integration-tests/02-test-execution/SKILL.md) | Authoring tests with pytest, pytest-bdd, playwright |
| [skills/integration-tests/03-teardown-and-reporting/SKILL.md](../../integration-tests/03-teardown-and-reporting/SKILL.md) | Cleanup, dependency-ordered DB reset, reporting. Includes the `information_schema.referential_constraints` discovery query and two-pass deletes for raceable tables |
| [skills/integration-tests/04-scenario-conventions/SKILL.md](../../integration-tests/04-scenario-conventions/SKILL.md) | File org, fixture layering, step-def patterns, mock server design. Background step ordering + V2 SOR assertion conventions |
| [skills/integration-tests/05-step-definitions-with-domain-helpers/SKILL.md](../../integration-tests/05-step-definitions-with-domain-helpers/SKILL.md) | Step defs that consume domain helpers from source repos. Explicit feature-flag preconditions + snapshot-based assertions |
| [skills/integration-tests/06-generate-feature-requests/SKILL.md](../../integration-tests/06-generate-feature-requests/SKILL.md) | Drafting feature-request docs that precede integration tests |
| [skills/integration-tests/07-debugging-failing-tests/SKILL.md](../../integration-tests/07-debugging-failing-tests/SKILL.md) | **The 7-step methodology** for any integration-test failure — starts with Step 0 service inventory audit |
| [skills/integration-tests/08-generating-test-plans/SKILL.md](../../integration-tests/08-generating-test-plans/SKILL.md) | Generating detailed test plans before writing complex integration tests |
| [skills/integration-tests/09-plan-to-code/SKILL.md](../../integration-tests/09-plan-to-code/SKILL.md) | Converting a test plan into code, scenario-by-scenario |
| [skills/integration-tests/10-cardinal-rules-and-anti-patterns/SKILL.md](../../integration-tests/10-cardinal-rules-and-anti-patterns/SKILL.md) | Hard NOs and ALWAYS-DOs for integration-test work. **Read before any integration-test code change.** Critical rule: no duplicate long-running services across containers |
| [skills/integration-tests/11-integration-test-investigation-format/SKILL.md](../../integration-tests/11-integration-test-investigation-format/SKILL.md) | Structured writeup format for integration-test failures — companion to `skills/design-and-analysis/describe-a-problem/SKILL.md` |

### Setup & Infrastructure

| File | What it covers |
|------|---------------|
| [skills/coding/setup-alembic/SKILL.md](../../coding/setup-alembic/SKILL.md) | Alembic migration setup, env.py config, creating migrations |
| [skills/coding/python-path-and-import-resolution/SKILL.md](../../coding/python-path-and-import-resolution/SKILL.md) | PYTHONPATH convention for src.* import resolution |

### Documentation & Review

| File | What it covers |
|------|---------------|
| [skills/design-and-analysis/review-feature-code/SKILL.md](../../design-and-analysis/review-feature-code/SKILL.md) | Structured code review against specifications |
| [skills/design-and-analysis/update-documentation-after-code-changes/SKILL.md](../../design-and-analysis/update-documentation-after-code-changes/SKILL.md) | When and how to update skills/orientation/research/SKILL.md, AGENTS.md, and code prompts |
| [skills/coding/generate-swagger-documentation/SKILL.md](../../coding/generate-swagger-documentation/SKILL.md) | Generate OpenAPI/Swagger docs across multiple services with per-service sub-agents |
| [skills/design-and-analysis/distill-learnings/SKILL.md](../../design-and-analysis/distill-learnings/SKILL.md) | Distill reusable insights into workspace-level `LEARNINGS.md` after implementation sessions |

---

## Analyze Folder

The `analyze/` subfolder contains prompts for **understanding, documenting, and reporting** on your codebase — not for writing new code.

| File | What it does |
|------|-------------|
| [find-how-it-works.md](../../design-and-analysis/find-how-it-works/SKILL.md) | Trace a feature end-to-end: router -> service -> DAO -> DB. Use when someone asks "how does X work?" |
| [feature-specifications.md](../../design-and-analysis/feature-specifications/SKILL.md) | Style guide for writing implementation blueprints. Follow this when creating specs for new features |
| [generate-agents-md.md](../../design-and-analysis/generate-agents-md/SKILL.md) | Step-by-step prompt to generate or regenerate `AGENTS.md` from the current codebase |
| [generate-research-md.md](../../design-and-analysis/generate-research-md/SKILL.md) | Step-by-step prompt to generate or regenerate `skills/orientation/research/SKILL.md` as a full codebase index |
| `daily-morning-standup-report.md` | Generate a daily standup summary from git history and JIRA tickets |
| `daily-priorities.md` | Generate a prioritized task list for the day based on sprint state |
| `weekly-update-generator.md` | Generate weekly progress reports from commit history and ticket status |
| `weekly-bottleneck-report-generator.md` | Identify blockers, bottlenecks, and risk areas across the team |
