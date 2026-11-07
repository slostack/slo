# Feature 96 A.1 Change2 retry 1 — bounded repair plan

Status: implementation checkpoint, not approved specification or Step1 readiness.
Sources: canonical HTML `96.a.1-session-owned-durable-delivery.html` (draft/REVISE), `assets/a1-runnable-core.md`, `assets/a1-implementation-walkthrough.md`; continuation ledger read first. User authorizes module-only work.

## Routing and baseline

Active skill root `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`; SKILL_DIR unset. Read project AGENTS/CLAUDE/SLO, both RESEARCH files, repository workflows/SKILL.md and code-test-review.md in full. Read ledger-selected shared engineering routing/testing/ownership, coding rules/design/cadence/test policy/declarative skills and Python root/style/domain/application/testing recipes in full. SQLite-specific project contract overrides SQLAlchemy/Postgres/Alembic examples. User test-first overrides Python default cadence. No nested agents, commit or push. Ledger remains orchestrator-owned.

Python 3.11.7 resolves through pyenv to `/root/.pyenv/versions/slo-harness/bin/python`; expected named slo interpreter absent. Pydantic 2.13.5 / SQLite 3.45.1. No installation changes. Safe Makefile fallback environment (no tests.env) used: SLO_ENV=test, SLO_ROOT_DIR/SLO_APP_DIR/PYTHONPATH=cwd, SLO_APP_NAME=slo, SLO_LOG_FORMAT=text, SLO_DEFAULT_MODEL_NAME=gpt-5.4, SLO_AUTO_VISUALIZE=0, SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked, COLUMNS=120, LINES=40. Baseline focused 95 passed, affected 2413 passed; receipts adjacent. No baseline waiver exists.

## Reconciliation decisions

- Runnable-core “What the A.1 queue accepts” overrides detailed workflow/channel effect assumptions: keep valid shared data types but do not activate B.2 acceptance/effect success or external D.1 recovery. Session capability policy under future queue mutex remains the authority; store is not scheduler or authorization API.
- HTML detailed DAO contract says both agent-session notes and channel transcript notes in one bullet (lines 1805ff); runnable-core local transcript-note allowance wins for local A.1. Channel capability remains unavailable.
- HTML store core DDL and later explicit note-boundary index define schema 1; no added B.1/B.2 initial tables. Existing migration_items is explicitly in quoted core DDL but does not authorize D.1 import. Later upgrades require versioned migration.
- HTML ownership section (`#srcagentsslo_agentmessagingownershippy`) requires join on acquisition and release, no-follow containment and unsupported-platform outcome. Existing shield-only implementation fails that contract; repair before store expansion.
- HTML store section requires canonical JSON, identity/body agreement, claim-note, paged identity/compaction/observation reads, stable evidence/idempotency and uncertain-write sealing. Existing passing skeleton-era tests are not evidence of these missing contracts.
- Canonical application identity in HTML delivery section is UUID5(session UUID, `message:` + message UUID), recorded_at=admitted_at and turn_id=boundary.run_id. Existing random claim IDs and generic user_message test events do not meet it; a subsequent test-first store increment must repair these, not preserve a false oracle.

## Ordered increments and risks

1. M3 safe ownership paths and repeated cancellation: public acquire/release against real tmp-owned files, injected bounded executor barrier where needed (not filesystem/flock mocks); verify contention, cleanup and idempotent joined release. No full session lifecycle claim.
2. M1 demonstrated DAO repairs: canonical UTF-8, anchored IDs/hashes, UTC and cross-record evidence; RED then minimal GREEN per behavior.
3. M2 actual store repairs: safe dedicated-worker startup/close, atomic validated schema, admission/duplicate/rollback/full/locked/corrupt behavior, deterministic application evidence, retention/local recovery, compaction and paging. Preserve existing partial files/tests; do not bulk-fill unsupported methods.
4. Run focused and affected checkpoint, scoped Black/mypy, diff review; produce compact requirement map and finite remainder if dispatch cannot close all M2/M3.

Full make test / make lint remain required before overall Step1 acceptance after remaining messaging modules. Queue/client/delivery and session/history/agent/TUI integration are outside this dispatch. Independent early feedback/final Review/Completion belong to orchestrator.
