---
name: python-conventions
description: Python conventions and detailed implementation/test recipe gateway; preserve FastAPI, SQLAlchemy,
  workers, agents, CLI and Textual capabilities.
when_to_use: Python conventions and detailed implementation/test recipe gateway; preserve FastAPI, SQLAlchemy,
  workers, agents, CLI and Textual capabilities.
group: languages
kind: skill
---

# Python Conventions

## Skill summary

Python conventions and detailed implementation/test recipe gateway; preserve FastAPI, SQLAlchemy, workers, agents, CLI and Textual capabilities.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

This is the Python translation entry point, not a substitute for detailed recipes. Shared obligations: `skills/engineering/engineering-ownership/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md`.

Load siblings by concern:
- Style authorities: named-arguments-and-type-hints, declarative-method-structure, method-docstrings. Preserve explicit types, keyword calls, Google-style contract documentation and the approved declarative service idioms.
- Architecture: application-structure, build-domain-features, build-application-services, bootstrap-project-scaffolding. Preserve model/DAO/service distinctions and invoke orchestration where those recipes apply.
- FastAPI/API: build-routers, build-middleware, api-response-conventions, auth-security-patterns, build-api-documentation, generate-swagger-documentation, test-controllers. Preserve response envelope, namespace, dependency/auth and validation behavior; controller integration uses httpx.AsyncClient, not a blanket TestClient prescription.
- Data: setup-alembic, build-clickhouse-features, test-domain-services, test-app-services. The latter two retain the real database/domain-collaborator harness; use separate orchestration units for fake-based ordering proofs.
- Jobs/events: build-celery-workers, build-event-handlers, build-partitioned-events, build-schedulers-tasks-with-dbos, build-dbos-workflow-orchestration-pattern.
- AI: build-agent-tools, build-react-agent-with-langgraph, graph-gateway-invoke-convention, test-graphs-and-agents.
- Boundaries/tools: build-clients, build-tcp-codec, python-path-and-import-resolution, setup-dependencies-and-tests, switch-environments-and-run-tests, build-vscode-launch-configurations, create-frontend-htmx-jinja2-fastapi-app.
- CLI and TUI stay in `skills/cli/` and `skills/tui/`; integration harnesses stay in `skills/integration-tests/`; Vue stays in `skills/frontend-vue/`.

Read the selected sibling's SKILL.md in full, including examples, assertions and anti-patterns. A project without FastAPI, SQLAlchemy, DBOS or Celery does not acquire those dependencies by using Python. Project commands control environment activation and test runner options. The canonical Python recipes live under `skills/languages/python/`; historical `skills/coding/` paths are migration provenance only.

