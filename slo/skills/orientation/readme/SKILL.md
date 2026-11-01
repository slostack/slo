---
name: readme
description: Overview of the skill library, its families, the documentation triad,
  and the per-project RESEARCH.md / MEMORY.md knowledge files.
when_to_use: Read when you need to understand how the skill library is organized,
  which skill family applies, or where a project's RESEARCH.md and MEMORY.md live.
group: orientation
kind: skill
source_prompt: README.md
---

# Skill Library README

## Skill summary

- **Name:** `readme`
- **Description:** Overview of the skill library, its families, the documentation triad, and the per-project RESEARCH.md / MEMORY.md knowledge files.
- **When to use:** Read when you need to understand how the skill library is organized, which skill family applies, or where a project's RESEARCH.md and MEMORY.md live.
- **Group:** `orientation`
- **Kind:** `skill`
- **Source prompt:** `README.md`

## Examples

- The user asks: "How is the skill library structured?"
- You need a high-level map before drilling into a specific convention file.
- You need to know where to write durable project knowledge versus current state.

## Guidance

**Multi-language scope:** Begin with `skills/engineering/engineering-routing/SKILL.md`.
Read shared obligations and only affected language/component/framework recipes.
Python-specific examples and commands below are scoped examples, not universal
requirements. For mixed-language work preserve each boundary's approved contract.
Use `skills/engineering/engineering-testing/SKILL.md` for test categories and evidence.

The skill library is a set of coding instruction files that teach any agent —
Claude, Codex, Slo, Kimi, or another — how to build features in a codebase:
folder structure, naming conventions, patterns for services, workers, routers,
and tests. They are the institutional knowledge that makes an agent produce code
that looks like your team wrote it.

Skills are read **on demand**. The agent reads [`INDEX.md`](../../INDEX.md) when
a task starts, matches the task against a skill's `description` and
`when_to_use`, then reads that skill's `SKILL.md` and follows it. Do not preload
the whole library.

---

## Project knowledge files

Two files carry a project's accumulated knowledge. They are **agent-owned**:
whichever agent is working creates them when missing and updates them as work
produces new knowledge. This applies to Claude, Codex, Slo, Kimi, and any other
agent.

### Where they live

```text
${SLO_HOME:-~/.slo}/projects/<project_name>/RESEARCH.md
${SLO_HOME:-~/.slo}/projects/<project_name>/MEMORY.md
```

`SLO_HOME` roots all Slo data. **When `SLO_HOME` is not defined, treat it as
`~/.slo`.** `<project_name>` is the project's directory name — the basename of
the repository checkout.

Older projects keep these at the repo root (`RESEARCH.md`, `docs/RESEARCH.md`) or,
under Claude Code, as an auto-managed memory index at
`<project-memory>/MEMORY.md`. Read those if they exist — but write new knowledge
to the canonical paths above, so every agent family converges on one file.

### RESEARCH.md — distilled project knowledge

Every project must have one. If it is missing, create it before meaningful
implementation work.

**Purpose:** the curated, project-specific "why the system is the way it is." It
holds:

- domain concepts and ubiquitous language,
- architectural decisions and constraints,
- important workflows and integration contracts,
- known failure modes and mistakes to avoid,
- operational, deployment, performance, and security constraints,
- decisions future agents must understand.

**Key rule:** read it before planning or changing a feature; update it when work
produces durable learning. It is **not** a raw activity log — it is distilled,
stable knowledge.

Generate or regenerate it with
[`generate-research-md`](../../design-and-analysis/generate-research-md/SKILL.md).
Keep it under 1000 lines — it is an index and a decision record, not
documentation.

### MEMORY.md — point-in-time project memory

**Purpose:** the current, mutable state of the project — what is happening now
and recent context — as opposed to `RESEARCH.md`'s durable, decision-level
knowledge. The authoring context stage loads it and labels it
`<project-memory>/MEMORY.md — point-in-time project memory`.

Every project must have one. If it is missing, create it when you first do
meaningful work in the project, and keep it current as state changes.

### The distinction

| | `RESEARCH.md` | `MEMORY.md` |
|---|---|---|
| **Timescale** | Durable / long-lived | Point-in-time / current |
| **Content** | Architecture, domain language, decisions, failure modes | Present state, recent context, working notes |
| **Updated when** | Work yields lasting learning | State changes as work proceeds |
| **Not for** | Activity logs | A permanent architectural record |

Roughly: **`RESEARCH.md` = "what is permanently true and why"; `MEMORY.md` =
"what is true right now."** Skills that draft specs — notably
[`feature-specifications`](../../design-and-analysis/feature-specifications/SKILL.md)
in its
[read-before-writing step](../../design-and-analysis/feature-specifications/SKILL.md#read-before-writing) —
read **both**: the stable design context and the live state, before a spec is
drafted.

### Who reads and writes them

| Agent | Entry file it loads first | Then reads |
|---|---|---|
| Claude Code | `CLAUDE.md` (+ `~/.claude/CLAUDE.md`) | `AGENTS.md` → `RESEARCH.md` → `MEMORY.md` |
| Codex | `AGENTS.md` (+ `~/.codex/AGENTS.md`) | `RESEARCH.md` → `MEMORY.md` |
| Slo | `SLO.md` (+ `~/.slo/SLO.md`) | `AGENTS.md` → `RESEARCH.md` → `MEMORY.md` |
| Kimi | `AGENTS.md` | `RESEARCH.md` → `MEMORY.md` |
| Any other agent | `AGENTS.md` | `RESEARCH.md` → `MEMORY.md` |

The orientation rule itself lives in [`agents`](../agents/SKILL.md).

---

## The documentation triad

Three files give an agent full context about a project. They reference each
other.

### Entry point — `CLAUDE.md` / `AGENTS.md` / `SLO.md`

The **first file an agent reads** when it enters a repository. It acts as a
gatekeeper:

```text
When asked to write, modify, or reason about code in this repository,
read AGENTS.md first. Skip this for general questions.
```

**How to use:**

- Place at the repository root.
- Keep it short — it should only point to `AGENTS.md` and the project's
  `RESEARCH.md`.
- Add project-specific overrides here (spec storage paths, special conventions).
- The canonical contract is in [`agents`](../agents/SKILL.md).

### `AGENTS.md` — agent guidance

The **operating manual** for agents working in the codebase:

- **Coding conventions table** — links to every skill with a one-line purpose.
- **External API references** — links to vendor API docs.
- **Architecture overview** — control flow, application structure.
- **Analysis guides** — how to trace features, write specs, generate docs.
- **Testing patterns** — fixtures, factories, mocking conventions.

**How to use:** place at the repository root; update the conventions table when
you add or remove a skill; regenerate with
[`generate-agents-md`](../../design-and-analysis/generate-agents-md/SKILL.md)
after major project changes.

### `RESEARCH.md` — codebase index and decision record

A complete map of the project so agents can locate anything without exhaustive
file searching: technology stack, spec links, services, domains, routers,
application services, workers, events, integrations, tests, infrastructure.

**How to use:** keep it at
`${SLO_HOME:-~/.slo}/projects/<project_name>/RESEARCH.md`; generate it with
[`generate-research-md`](../../design-and-analysis/generate-research-md/SKILL.md);
update it after adding domains, routers, workers, or integrations — see
[`update-documentation-after-code-changes`](../../design-and-analysis/update-documentation-after-code-changes/SKILL.md).

---

## Library layout

```text
skills/
├── INDEX.md                    # Generated index — the agent's routing table
├── orientation/                # Entry-point rules and this map
├── design-and-analysis/        # Specs, reviews, debugging, workflows, orchestration
│   └── workflows/              # Named multi-step workflows (not skills)
├── coding/                     # Language, framework, and layer conventions
├── git-ops/                    # Branching, commits, PRs, releases, worktrees
├── cli/                        # Typer CLI conventions
├── tui/                        # Textual TUI conventions
├── integration-tests/          # Cross-service integration testing
├── frontend-vue/               # Vue 3 / TypeScript conventions
├── presentation/               # HTML and PDF output formats
└── user-content/               # Authoring personal skills and workflows
```

Resolve personal overrides through `config.cfg.USER_SKILLS_DIR` and
`USER_WORKFLOWS_DIR`: `SLO_USER_SKILLS_DIR` / `SLO_USER_WORKFLOWS_DIR` override
the `user_skills` / `user_workflows` directories under Slo’s resolved home.
Use the active catalog’s file paths; do not assume an installation layout.
Vendored discovery honors `SLO_SKILLS_DIR`, then a populated skills tree under
`SLO_HOME`, then the package-adjacent skills tree. See
[skill discovery](../../design-and-analysis/feature-specifications/SKILL.md#artifact-paths-and-skill-discovery).

**Adding or editing a skill:** edit the `skills/<group>/<slug>/SKILL.md` file,
then run `make build-skill-index` to regenerate `INDEX.md`. Never hand-edit
`INDEX.md`.

---

## Workflows — load the workflow file, not a similarly-named skill

When the user says "workflow" or names one, load the file from
`skills/orchestration/workflows/` directly.

| Workflow | File |
|---|---|
| Code-Test-Review | [`workflows/code-test-review.md`](../../orchestration/workflows/code-test-review.md) |
| GitLab Code-Test-Review | [`workflows/gitlab-code-test-review.md`](../../orchestration/workflows/gitlab-code-test-review.md) |
| Specification Development | [`workflows/specification-development.md`](../../orchestration/workflows/specification-development.md) |
| Overview of the workflow system | [`workflows/SKILL.md`](../../orchestration/workflows/SKILL.md) |

[`code-test-loop`](../../coding/code-test-loop/SKILL.md) is **not** the
Code-Test-Review workflow — it is Step 1 inside it. Loading it instead silently
drops the review and completion-check steps.

---

# Skill Reference

## Orientation

| Skill | What it covers |
|---|---|
| [`agents`](../agents/SKILL.md) | Root entry-point rule for every agent: which instruction files to read, in what order, and where `RESEARCH.md` / `MEMORY.md` live |
| [`readme`](./SKILL.md) | This file — library map, documentation triad, project knowledge files |

## Design and Analysis

### Specifications

| Skill | What it covers |
|---|---|
| [`feature-specifications`](../../design-and-analysis/feature-specifications/SKILL.md) | Writes a feature's `overview.md`: domains, journeys, interfaces, open decisions |
| [`feature-specification-verification`](../../design-and-analysis/feature-specification-verification/SKILL.md) | Reviewing a draft spec for gaps, ambiguities, and redundant functionality |
| [`gather-feature-context`](../../design-and-analysis/gather-feature-context/SKILL.md) | Pulls domain, business, current-state, and implementation context into a sign-off briefing |
| [`breakdown-feature-spec-to-tasks`](../../design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md) | Expands `overview.md` into standalone engineering sub-specs and a dependency-ordered task list |
| [`specification-development`](../../design-and-analysis/specification-development/SKILL.md) | Pipeline: overview → sub-specs → family verification |
| [`implement-feature-request`](../../design-and-analysis/implement-feature-request/SKILL.md) | End-to-end: feature request → specs → code → tests → review → docs |

### Understanding and debugging

| Skill | What it covers |
|---|---|
| [`find-how-it-works`](../../design-and-analysis/find-how-it-works/SKILL.md) | Trace a feature end-to-end through an unfamiliar codebase |
| [`explain-how-it-works`](../../design-and-analysis/explain-how-it-works/SKILL.md) | Guided-lesson style for explaining a feature, commit, or subsystem, with mandatory diagrams |
| [`debug-by-isolation`](../../design-and-analysis/debug-by-isolation/SKILL.md) | Canonical five-phase debugging approach — isolate before solving |
| [`describe-a-problem`](../../design-and-analysis/describe-a-problem/SKILL.md) | Granular format for describing any problem before a fix is proposed |
| [`is-the-feature-completed`](../../design-and-analysis/is-the-feature-completed/SKILL.md) | Estimating implementation completeness against a spec |

### Review

| Skill | What it covers |
|---|---|
| [`review-feature-code`](../../design-and-analysis/review-feature-code/SKILL.md) | Reviewing a feature implementation against its spec |
| [`code-test-review`](../../design-and-analysis/code-test-review/SKILL.md) | Pipeline: specification or task slice → tested code → review findings → completion assessment |
| [`development-reviews`](../../design-and-analysis/development-reviews/SKILL.md) | Two-agent review handshake protocol |

### Conventions and knowledge

| Skill | What it covers |
|---|---|
| [`derive-new-convention`](../../design-and-analysis/derive-new-convention/SKILL.md) | Deriving a new repeatable convention when no existing skill covers the pattern |
| [`ubiquitous-language`](../../design-and-analysis/ubiquitous-language/SKILL.md) | One concept, one canonical name across CLI, services, DAOs, APIs, frontend |
| [`generate-agents-md`](../../design-and-analysis/generate-agents-md/SKILL.md) | Regenerate `AGENTS.md` from the current codebase |
| [`generate-research-md`](../../design-and-analysis/generate-research-md/SKILL.md) | Regenerate the project `RESEARCH.md` codebase index |
| [`update-documentation-after-code-changes`](../../design-and-analysis/update-documentation-after-code-changes/SKILL.md) | Keep `RESEARCH.md` and skills in sync after any non-trivial change |
| [`update-knowledge-base`](../../design-and-analysis/update-knowledge-base/SKILL.md) | Session-end incremental update of the Obsidian KB |
| [`distill-learnings`](../../design-and-analysis/distill-learnings/SKILL.md) | Capture non-obvious solutions and patterns to `LEARNINGS.md` |

### Orchestration

| Skill | What it covers |
|---|---|
| [`orchestrator`](../../orchestration/orchestrator/SKILL.md) | Gateway that decides which skill or workflow to load next; routes dynamic-workflow requests |
| [`workflows`](../../orchestration/workflows/SKILL.md) | The workflow system: pipeline vs parallel, context handoff, routing rules |
| [`headless-orchestration`](../../orchestration/headless-orchestration/SKILL.md) | Launch a named workflow as a **detached** headless orchestrator — only on an explicit detach qualifier |

## Coding

### Architecture and structure

| Skill | What it covers |
|---|---|
| [`application-structure`](../../languages/python/application-structure/SKILL.md) | **Start here.** Folder layout, env config, DB setup, app architecture |
| [`bootstrap-project-scaffolding`](../../languages/python/bootstrap-project-scaffolding/SKILL.md) | Creating a brand-new project or service |
| [`build-routers`](../../languages/python/build-routers/SKILL.md) | FastAPI endpoints, OpenAPI docs, response wrappers |
| [`build-domain-features`](../../languages/python/build-domain-features/SKILL.md) | Domain entities — the `dao.py` / `model.py` / `service.py` pattern |
| [`build-application-services`](../../languages/python/build-application-services/SKILL.md) | Orchestration logic — the `invoke()` pattern, router → service → domain |
| [`build-middleware`](../../languages/python/build-middleware/SKILL.md) | FastAPI cross-cutting middleware (DB sessions, request tracking, auth) |
| [`api-response-conventions`](../../coding/api-response-conventions/SKILL.md) | `SuccessResponseDAO` / `FailureResponseDAO` shapes |
| [`graph-gateway-invoke-convention`](../../languages/python/graph-gateway-invoke-convention/SKILL.md) | Gateway invoke convention for graph entry points and orchestration seams |

### Workers and events

| Skill | What it covers |
|---|---|
| [`build-celery-workers`](../../languages/python/build-celery-workers/SKILL.md) | Celery tasks — naming, registration, routes, beat |
| [`build-dbos-workflow-orchestration-pattern`](../../languages/python/build-dbos-workflow-orchestration-pattern/SKILL.md) | Multi-step durable workflows with DBOS queues and recursive watchers |
| [`build-schedulers-tasks-with-dbos`](../../languages/python/build-schedulers-tasks-with-dbos/SKILL.md) | DBOS init, DB pool config, scheduled tasks |
| [`build-event-handlers`](../../languages/python/build-event-handlers/SKILL.md) | Event handler routing and dispatch |
| [`build-partitioned-events`](../../languages/python/build-partitioned-events/SKILL.md) | Event partitioning via consistent hashing |

### AI and agents

| Skill | What it covers |
|---|---|
| [`build-react-agent-with-langgraph`](../../languages/python/build-react-agent-with-langgraph/SKILL.md) | LangGraph ReAct loops — state, nodes, routing, graph assembly |
| [`build-agent-tools`](../../languages/python/build-agent-tools/SKILL.md) | LangChain `@tool` conventions — schema DAO + tool class + thin bridge |
| [`test-graphs-and-agents`](../../languages/python/test-graphs-and-agents/SKILL.md) | Testing LangGraph agents with the `FauxChatModel` pattern |

### External systems

| Skill | What it covers |
|---|---|
| [`build-clients`](../../languages/python/build-clients/SKILL.md) | External API clients (aiohttp/httpx), DAOs, error handling, testing |
| [`build-clickhouse-features`](../../languages/python/build-clickhouse-features/SKILL.md) | ClickHouse clients, migrations, DAOs, S3, queries |
| [`build-tcp-codec`](../../languages/python/build-tcp-codec/SKILL.md) | Length-prefixed TCP codec — framing, header, checksum, size bounds |
| [`auth-security-patterns`](../../languages/python/auth-security-patterns/SKILL.md) | Password hashing (bcrypt + SHA-256 pre-hash) and JWT session design |

### Frontend (server-rendered)

| Skill | What it covers |
|---|---|
| [`create-frontend-htmx-jinja2-fastapi-app`](../../languages/python/create-frontend-htmx-jinja2-fastapi-app/SKILL.md) | Server-rendered FastAPI + Jinja2 + HTMX frontends |

### Code quality

| Skill | What it covers |
|---|---|
| [`code-review-rules`](../../languages/python/code-review-rules/SKILL.md) | Fast-pass checklist of non-negotiable hard rules — a violation is a blocker |
| [`declarative-method-structure`](../../coding/declarative-method-structure/SKILL.md) | Shared Tell, don't ask — flat structure, early returns, and coherent decomposition; read the language specialization afterward |
| [`naming-and-clarity`](../../coding/naming-and-clarity/SKILL.md) | Self-describing names, Build/Create/BuildAndCreate and publish/consume verbs |
| [`method-docstrings`](../../languages/python/method-docstrings/SKILL.md) | Google-style docstrings on every method and function |
| [`named-arguments-and-type-hints`](../../languages/python/named-arguments-and-type-hints/SKILL.md) | Keyword arguments and explicit type hints everywhere |
| [`code-test-loop`](../../coding/code-test-loop/SKILL.md) | The coding cadence — code → test → green → next chunk |

### Testing

| Skill | What it covers |
|---|---|
| [`test-verification-policy`](../../coding/test-verification-policy/SKILL.md) | Coverage and decision-path checklist before declaring tests done |
| [`test-domain-services`](../../languages/python/test-domain-services/SKILL.md) | Testing domain services — Pydantic DAOs, service methods, persistence |
| [`test-app-services`](../../languages/python/test-app-services/SKILL.md) | Testing application services with mocked dependencies |
| [`test-controllers`](../../languages/python/test-controllers/SKILL.md) | Testing FastAPI routers via `TestClient` |
| [`setup-dependencies-and-tests`](../../languages/python/setup-dependencies-and-tests/SKILL.md) | Postgres, Docker, `conftest.py`, transactional fixtures |
| [`switch-environments-and-run-tests`](../../languages/python/switch-environments-and-run-tests/SKILL.md) | Environment switching and test execution |

### Setup and tooling

| Skill | What it covers |
|---|---|
| [`setup-alembic`](../../languages/python/setup-alembic/SKILL.md) | Initialising and managing Alembic migrations |
| [`python-path-and-import-resolution`](../../languages/python/python-path-and-import-resolution/SKILL.md) | `PYTHONPATH` convention and import-failure debugging |
| [`build-api-documentation`](../../languages/python/build-api-documentation/SKILL.md) | Redoc + FastAPI API docs |
| [`generate-swagger-documentation`](../../languages/python/generate-swagger-documentation/SKILL.md) | OpenAPI / Swagger docs across multiple services |
| [`build-vscode-launch-configurations`](../../languages/python/build-vscode-launch-configurations/SKILL.md) | Authoring VS Code launch configurations |

## Git Ops

| Skill | What it covers |
|---|---|
| [`git-ops-orchestrator`](../../git-ops/git-ops-orchestrator/SKILL.md) | Gateway — routes a git request into the right branching, commit, PR, or worktree skill |
| [`branching-and-commit-conventions`](../../git-ops/branching-and-commit-conventions/SKILL.md) | Git safety rails, branch naming, commit messages, PR guardrails |
| [`create-feature-branch`](../../git-ops/create-feature-branch/SKILL.md) | Create a task-scoped feature branch from the latest main |
| [`sync-main`](../../git-ops/sync-main/SKILL.md) | Refresh local main from remote without clobbering in-flight work |
| [`commit-and-push`](../../git-ops/commit-and-push/SKILL.md) | Stage, confirm the message, commit safely, push to the correct upstream |
| [`generate-pr-description`](../../git-ops/generate-pr-description/SKILL.md) | Generate a PR title and body from branch, commits, diff, and template |
| [`create-pull-request`](../../git-ops/create-pull-request/SKILL.md) | Open a PR against the correct base branch |
| [`load-pr-context`](../../git-ops/load-pr-context/SKILL.md) | Collect PR metadata, diff themes, review comments, next actions |
| [`fix-pr-review`](../../git-ops/fix-pr-review/SKILL.md) | Address review comments, integrate base safely, rerun verification, push |
| [`ship-feature`](../../git-ops/ship-feature/SKILL.md) | Commit → push → open MR/PR → merge → checkout main and pull |
| [`gitlab-issues`](../../git-ops/gitlab-issues/SKILL.md) | Publish specification files to GitLab Issues and manage labels and state with `glab` |
| [`worktrees`](../../git-ops/worktrees/SKILL.md) | Git worktrees for latest-main reads, parallel branches, reviewer/writer isolation |
| [`release-process`](../../git-ops/release-process/SKILL.md) | Release a new version of slo — bump, MR, merge, tag, publish installer |

## CLI

| Skill | What it covers |
|---|---|
| [`cli-readme`](../../cli/cli-readme/SKILL.md) | Orientation for the CLI family — read first |
| [`build-typer-cli-apps`](../../cli/build-typer-cli-apps/SKILL.md) | User-facing Python CLIs with Typer + Rich, default TUI launch, subcommands |
| [`build-cli-commands`](../../cli/build-cli-commands/SKILL.md) | Eighteen hard rules for adding an operator-facing CLI verb end-to-end |
| [`build-cli-command-class`](../../cli/build-cli-command-class/SKILL.md) | Command class conventions — naming, the three required methods, `execute()` discipline |
| [`build-cli-modules`](../../cli/build-cli-modules/SKILL.md) | Module standards — `@handle_cli_errors`, two-console discipline, polling, retry, dry-run gate |

## TUI

| Skill | What it covers |
|---|---|
| [`tui-readme`](../../tui/tui-readme/SKILL.md) | Orientation for the Textual TUI family — read first |
| [`build-textual-tuis`](../../tui/build-textual-tuis/SKILL.md) | Textual TUIs with explicit app/router/renderer/widget boundaries |
| [`tui-scheduled-operations`](../../tui/tui-scheduled-operations/SKILL.md) | Operate scheduled tasks from an interactive TUI session |
| [`tui-scheduled-workflows`](../../tui/tui-scheduled-workflows/SKILL.md) | Supervise dynamic workflows, recover stalled orchestrators, clean up monitors |
| [`slodiff`](../../tui/slodiff/SKILL.md) | Show the git diff (HEAD vs worktree) for one file as structured before/after content |

## Integration Tests

| Skill | What it covers |
|---|---|
| [`01-test-setup`](../../integration-tests/01-test-setup/SKILL.md) | Stack setup, Docker orchestration, DB seeding, env isolation. **Hard Constraints** block at the top |
| [`02-test-execution`](../../integration-tests/02-test-execution/SKILL.md) | Authoring scenarios with pytest, pytest-bdd, Playwright |
| [`03-teardown-and-reporting`](../../integration-tests/03-teardown-and-reporting/SKILL.md) | Cleanup, dependency-ordered DB reset, reporting |
| [`04-scenario-conventions`](../../integration-tests/04-scenario-conventions/SKILL.md) | File organization, fixture layering, step-def patterns, mock server design |
| [`05-step-definitions-with-domain-helpers`](../../integration-tests/05-step-definitions-with-domain-helpers/SKILL.md) | Step defs that consume domain helpers from source repos |
| [`06-generate-feature-requests`](../../integration-tests/06-generate-feature-requests/SKILL.md) | Drafting the feature-request docs that precede integration tests |
| [`07-debugging-failing-tests`](../../integration-tests/07-debugging-failing-tests/SKILL.md) | **The 7-step methodology** for any integration-test failure |
| [`08-generating-test-plans`](../../integration-tests/08-generating-test-plans/SKILL.md) | Detailed test plans before writing complex integration tests |
| [`09-plan-to-code`](../../integration-tests/09-plan-to-code/SKILL.md) | Converting a test plan into code, scenario by scenario |
| [`10-cardinal-rules-and-anti-patterns`](../../integration-tests/10-cardinal-rules-and-anti-patterns/SKILL.md) | Hard NOs and ALWAYS-DOs. **Read before any integration-test change** |
| [`11-integration-test-investigation-format`](../../integration-tests/11-integration-test-investigation-format/SKILL.md) | Structured writeup format for integration-test failures |

## Frontend / Vue

| Skill | What it covers |
|---|---|
| [`vue-coding-conventions`](../../frontend-vue/vue-coding-conventions/SKILL.md) | Mandatory Vue 3 / TypeScript conventions — read first |
| [`build-vue-components`](../../frontend-vue/build-vue-components/SKILL.md) | The 3-layer pattern mirroring the backend (component / composable / API) |
| [`build-websocket-endpoints`](../../frontend-vue/build-websocket-endpoints/SKILL.md) | Real-time WebSocket bridges between Vue and backend agents |
| [`01-vue-fundamentals`](../../frontend-vue/01-vue-fundamentals/SKILL.md) | Tutorial: templates, directives, reactivity basics |
| [`02-typescript-essentials`](../../frontend-vue/02-typescript-essentials/SKILL.md) | Tutorial: TypeScript essentials for Vue components |
| [`03-composition-api`](../../frontend-vue/03-composition-api/SKILL.md) | Tutorial: Composition API patterns |
| [`04-pinia-state-management`](../../frontend-vue/04-pinia-state-management/SKILL.md) | Tutorial: Pinia state management |
| [`05-vue-router`](../../frontend-vue/05-vue-router/SKILL.md) | Tutorial: Vue Router setup and navigation |
| [`06-composables`](../../frontend-vue/06-composables/SKILL.md) | Tutorial: writing and using composables |
| [`07-websocket-integration`](../../frontend-vue/07-websocket-integration/SKILL.md) | Tutorial: WebSocket integration in Vue |
| [`08-bootstrap-scss-theming`](../../frontend-vue/08-bootstrap-scss-theming/SKILL.md) | Tutorial: Bootstrap + SCSS theming |

## Presentation

| Skill | What it covers |
|---|---|
| [`present-as-html`](../../presentation/present-as-html/SKILL.md) | Self-contained HTML — scroll-snap slide deck or paged documents, Slo design language |
| [`present-as-single-page`](../../presentation/present-as-single-page/SKILL.md) | One long scrolling page with a hero, anchored sections, optional sticky TOC |
| [`present-as-pdf-book`](../../presentation/present-as-pdf-book/SKILL.md) | Print-ready O'Reilly-style PDF via WeasyPrint — cover, TOC, part dividers, callouts |

## User Content

| Skill | What it covers |
|---|---|
| [`create-user-skill`](../../user-content/create-user-skill/SKILL.md) | Create a personal skill at the runtime-resolved `USER_SKILLS_DIR` |
| [`create-user-workflow`](../../user-content/create-user-workflow/SKILL.md) | Create a personal pipeline workflow at the runtime-resolved `USER_WORKFLOWS_DIR` |

---

## Configuration placeholders

Some skills use `{{PLACEHOLDER}}` variables for project-specific values. After
copying a skill into a project, search and replace:

| Placeholder | Description | Example |
|---|---|---|
| `{{PROJECT_NAME}}` | Project name | `MyApp` |
| `{{project_module}}` | Python module name (lowercase) | `myapp` |
| `{{MONOREPO_NAME}}` | Monorepo name, if applicable | `orders-platform` |
| `{{API_BASE_URL}}` | API base URL | `https://api.example.com` |
| `{{DOMAIN}}` | Domain name | `example.com` |
| `{{PRODUCT_NAME}}` | Product identifier | `MyProduct` |

Most files are already generic and require no replacement.
