# 96.a.2 T1 — strict live tool-group guard (bounded foundation)

**Status:** implementation slice READY. This is a preparatory foundation, not an
early runnable milestone, not provider wiring, and not a claim that A12 is fully
closed. No commit, push, merge, PR, or nested agents.

**Baseline:** `message-queue` / `82c3f5c6de9345af34a673a3d975366ca8c1624c`.
**Cwd for every command:** `/root/Code/slo-message-queue/slo`.

## Scope delivered

Owner file only: `src/agents/slo_agent/history/message_contract_reconciler.py`
plus its owning test module.

- Added `UnsettledToolGroupError` with fixed safe text `unsettled_tool_group`.
- Added non-mutating `MessageContractReconciler.require_settled_live(*, messages)`.
  It validates, and never repairs:
  - one assistant group at a time; non-tool or result-list boundaries while a
    group is pending are rejected (interleaving / missing result);
  - strict source-ordered call→result pairing;
  - nonblank, distinct, non-reused call IDs across the provider context;
  - nonblank result IDs; orphan, duplicate, and out-of-order results rejected;
  - `invalid_tool_calls`, partial or non-mapping tool-call structures rejected;
  - open calls at list end rejected.
- Historical `reconcile` behavior preserved, except `_heal_dangling_tool_calls`
  placeholders now carry `status="error"` (spec §6.1). Healing remains legacy
  repair only and is never proof of live settlement.

No provider guard integration, no tool policy/DAO, no history metadata or store
changes in this slice.

## Test-first receipts

RED (before production change) — collection error for the missing symbol, then:

```bash
cd /root/Code/slo-message-queue/slo
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo \
  SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 \
  SLO_HERDR_DISABLED=1 \
  SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked \
  COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' \
  tests/agents/slo_agent/history/test_message_contract_reconciler.py
```

Status: **1 collection error** — `ImportError: cannot import name
'UnsettledToolGroupError'`.

GREEN (same command after implementation): **26 passed, 2 warnings**.

Regression (existing normal real client → session → SQLite/history journey plus
projector):

```bash
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' \
  tests/agents/slo_agent/messaging/test_delivery.py \
  tests/agents/slo_agent/history/test_projector.py
```

Status: **122 passed, 315 warnings**, 67.26s. This is the audited real normal
journey and projector regression, not a substitute for the blocked full gate.

Static scoped:

- `poetry run black --check <both changed files>` → 2 files unchanged.
- `poetry run mypy src/agents/slo_agent/history/message_contract_reconciler.py`
  → success, no issues.

## Fixture/safety audit for the tests actually run

- `tests/agents/slo_agent/history/test_message_contract_reconciler.py`: pure
  in-memory message lists; no tmp writes, subprocess, chmod, or executable.
- `tests/agents/slo_agent/messaging/test_delivery.py`: `tmp_path` history/
  SQLite only; no executable fixture (grep for `chmod|write_regular_executable|
  subprocess|executable` returned nothing).
- `tests/agents/slo_agent/history/test_projector.py`: same audit, nothing found.
- Shared autouse fixtures (`isolated_slo_home`) create only temp directories and
  rebind paths; `fake_herdr` is opt-in and was not requested.

Full gate remains **BLOCKED / UNVERIFIED**: `make test PYTEST_WORKERS=6` is not
run because the default non-E2E suite executes unauthorized executable fixtures
(`safety-audit.md` §3). No exclusion, subset, or re-mark is offered as a
substitute. No executable artifact was created or modified.

## A12 disposition

Closed, with evidence, only the **bounded strict live-guard portion** of A12:

- exact ordered pairing of pending/seen IDs, malformed/blank/reused/duplicate
  IDs, `invalid_tool_calls`/partial structures, interleaving/orphan/missing
  results;
- live guard never heals;
- historical healing placeholders now use `status='error'`.

Remaining A12 (not claimed here): capability identity by original tool object /
exact invocation task, duplicate-registration rejection, illegal transition
errors, result-status retention through replay metadata, marked-group compaction
atomicity, and provider/session guard integration. Those belong to later
T1/T3/provider-wiring slices and their own reviews.

## Accounting

- Workflow turn 1 started, 0 completed.
- Dispatches: 3 prior, this is dispatch 4 of 20.
- Turn limit 60.
- Prior execution retry: audit-handoff only; none in this task.
- No abort was retried.
- Model: primary DeepSeek with default reasoning; no fallback.

## Preservation

- Pre-existing dirty `slo/SLO.md`, untracked `slo/docs/`, and durable-composer
  evidence untouched.
- `preflight-blocker.md` byte-preserved:
  `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`.
- `routing.md` and `acceptance.md` unchanged.
