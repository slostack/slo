# 96.a.2 T1 — validated metadata DAOs (bounded foundation)

**Status:** READY — bounded metadata schema increment only. This is not complete
T1, not the runnable urgent-yield milestone, and not a completion claim.

Baseline `message-queue` / `82c3f5c6de9345af34a673a3d975366ca8c1624c`.
Cwd for every command: `/root/Code/slo-message-queue/slo`.

## Scope delivered

Source:

- `src/agents/slo_agent/tool_execution/dao.py` — `ToolGroupMetadataDAO`
  (strict, frozen, extra-forbid). Enforces schema version 1, canonical attempt
  UUID, canonical group UUID5 derived from `attempt_turn_id` + `tool-group:<iteration>`,
  nonnegative iteration, nonempty/ordered/distinct/bounded-printable call IDs,
  aware UTC `opened_at`, result status limited to `success|error`, and no
  invented status on `not_started`.
- `src/agents/slo_agent/history/dao.py` — `CooperativeYieldMetadataDAO`
  (strict, frozen, extra-forbid). Enforces schema version 1, canonical logical
  run and attempt UUIDs, nonnegative boundary/iteration/high-water, closed
  reason/disposition vocabularies, canonical optional group UUID5, a required
  group for `deferred`, and group correlation to the same attempt/iteration.
  No body, credential, arbitrary exception or provider-private anchor field.
- `src/agents/slo_agent/history/message_contract_reconciler.py` —
  `CooperativeYieldSettlementError` with fixed safe text
  `cooperative_yield_settlement`. It lives beside the existing history
  settlement owner and its shared predicate; importing it introduces no
  runtime/graph cycle. `is_settlement_failure` now classifies both
  `UnsettledToolGroupError` and `CooperativeYieldSettlementError`, so all three
  existing agent/session terminal boundaries reject it before generic retry,
  reconnect, compaction or LLM recovery.

Deliberately not delivered: store protocol/adapters (`append_cooperative_event_once`),
producers/consumers, runtime trace/stream kinds, SQL/schema changes, new
dependencies, pool or TUI activation.

## Test-first receipts

RED (before production; exact log
`release-evidence/96-cooperative-provider-tool-yield/logs/turn4-t1-metadata-red.log`):

```sh
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' -q \
  tests/agents/slo_agent/tool_execution/test_tool_group_metadata.py \
  tests/agents/slo_agent/history/test_cooperative_yield_metadata.py \
  tests/agents/slo_agent/history/test_settlement_failure.py
```

Recorded **exit 2**; three collection `ImportError`s for the not-yet-existing
`ToolGroupMetadataDAO`, `CooperativeYieldMetadataDAO` and
`CooperativeYieldSettlementError`.

GREEN (same command; log `logs/turn4-t1-metadata-green.log`): **exit 0, 27
passed, 2 warnings in 1.35s**.

Normal real client/session SQLite/history regression (log
`logs/turn4-t1-metadata-regression.log`):

```sh
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' -q \
  tests/agents/slo_agent/messaging/test_delivery.py \
  tests/agents/slo_agent/messaging/test_history_application.py \
  tests/agents/slo_agent/history/test_message_contract_reconciler.py
```

Recorded **exit 0, 176 passed, 315 warnings in 68.24s**.

Settlement-predicate surface regression (log
`logs/turn4-t1-metadata-settlement-regression.log`):

```sh
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' -q \
  tests/agents/slo_agent/messaging/test_provider_settlement_guard.py
```

Recorded **exit 0, 7 passed, 7 warnings in 1.59s**.

Scoped static (log `logs/turn4-t1-metadata-static.log`): Black
`6 files would be left unchanged` (exit 0); mypy `Success: no issues found in 6
source files` (exit 0).

All receipts record cwd, UTC time, baseline HEAD, environment (`SLO_ENV=test`,
`SLO_ROOT_DIR`/`SLO_APP_DIR` = cwd, `SLO_APP_NAME=slo`, text logging,
`SLO_DEFAULT_MODEL_NAME=gpt-5.4`, `SLO_AUTO_VISUALIZE=0`,
`SLO_HERDR_DISABLED=1`, placeholder Anthropic key, `COLUMNS/LINES`,
`PYTHONDONTWRITEBYTECODE=1`) and an explicit `[exit_status=…]`.

## Safety and fixture audit

Schema tests are pure in-memory Pydantic construction; no tmp writes,
subprocesses or executables. Regression modules use only pytest `tmp_path`
SQLite/JSONL roots; grep found no chmod/subprocess/executable use in them. The
shared autouse fixture creates only temporary isolated `SLO_HOME` directories.
No executable or system artifact was created or modified; the consented
deploy-worker `bin/curl` fixture was not requested or exercised.

## Gate and review status

- `make test PYTEST_WORKERS=6`: **BLOCKED / UNVERIFIED** by lack of consent for
  other executable fixtures. No subset, exclusion, serial substitute or waiver
  is offered.
- Full static gate: **UNRUN / UNVERIFIED**.
- Independent early review, full scope/gates, independent final review and
  independent completion remain **pending**. None is claimed.
- Remaining next increment: restricted `append_cooperative_event_once` for both
  adapters with exact raw append-once proof; then trusted producers/raw validator
  and T2.

## Preservation and accounting

- Pre-existing dirty `SLO.md`, `docs/`, prior evidence and durable-composer
  files untouched. `preflight-blocker.md` still hashes
  `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`.
- No commit, push, merge, PR, package, system, infrastructure or nested-agent
  action.
- Counters: turn 4, this dispatch **4/20**; prior partial-turn dispatch counts
  **7/4/4**; 60-turn limit. Prior five execution retries (audit 1/provider 1/
  repair 2/proof 1); none in this task; no abort retried.
- Model: assigned primary DeepSeek default; no fallback used.
