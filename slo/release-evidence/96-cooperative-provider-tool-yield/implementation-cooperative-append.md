# 96.a.2 T1 — restricted cooperative append-once (bounded subset)

**Status:** READY for the bounded T1 append-once subset only. Not complete T1,
not A.8/A.9/A.12 closed, not the silent-provider milestone, and not a completion
claim.

Baseline `message-queue` / `82c3f5c6de9345af34a673a3d975366ca8c1624c`.
Cwd for every command: `/root/Code/slo-message-queue/slo`.

## Scope delivered

Source:

- `history/store_protocol.py` — added
  `append_cooperative_event_once(*, event) -> SessionHistoryEventDAO` beside the
  existing `append_message_application_once`.
- `history/filesystem_store.py` — added the restricted public port, a dedicated
  validator call and shared private raw append-once mechanics. The application
  path still runs `project_message_application`; the cooperative path runs
  `validate_cooperative_history_event` and then the same `_append_once_sync`
  raw-ID/digest scan, high-water repair, redaction verification and
  fsync-then-metadata commit. The writer remains a shielded worker joined before
  the history lock is released, including repeated caller cancellation.
- `history/tree_store.py` — delegates cooperative bytes to the flat owner without
  tree enrichment and advances its cursor only for a newer persisted event.
- `history/dao.py` — added the restricted validator for marked
  `tool_call`/`tool_result` records and cooperative/no-start `run_retrying`
  records. It requires `tool_group_v1` or `cooperative_yield_v1` (not both),
  checks kind, opening/not-started disposition, attempt/iteration correlation,
  ordered distinct call IDs, deterministic UUID5 event IDs, result-only status,
  and no invented `ToolMessage` on no-start.
- `history/message_contract_reconciler.py` — fixed the settlement error code from
  `cooperative_yield_settlement` to the spec's
  `cooperative_yield_settlement_failed`. The prior three terminal exclusions and
  the no-automatic-live-retry predicate are unchanged; this turn only corrected
  the fixed code string.

Tests:

- `tests/agents/slo_agent/messaging/test_history_cooperative_append.py` — 14
  collected tests across both real adapters (flat and tree) covering exact
  persisted readback, equal-ID/equal-digest dedup without a second raw line,
  conflicting digest, wrong/unknown identity, unmarked/unknown records,
  no-start and cooperative diagnostic records, high-water repair after a durable
  line and stale metadata, redaction change fail-closed, repeated-cancellation
  worker join before lock release, tree canonical-byte/cursor preservation, and
  duplicate raw identity plus raw corruption fail-closed.
- `tests/agents/slo_agent/history/test_settlement_failure.py` — 3 collected tests
  covering the terminal family and the corrected fixed code.

Not delivered: raw-group startup/context/compaction validator, producers or
consumers, T2 provider race, tools policy, TUI activation. No raw group validator
was added. No new SQL schema, dependency, config flag, IPC target or process.

## Exact receipts

Environment for every pytest/static command (exported inline, no
`environments/tests.env` exists):

```sh
cd /root/Code/slo-message-queue/slo
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
```

### RED (test-first, before the production append API existed)

Log: `logs/turn5-retry2-append-red.log`

```sh
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' -q \
  tests/agents/slo_agent/messaging/test_history_cooperative_append.py \
  tests/agents/slo_agent/history/test_settlement_failure.py
```

Recorded **exit 1; 13 failed, 2 passed, 2 warnings in 1.68s**. The failures are
the missing `append_cooperative_event_once` attribute and the pre-fix settlement
code assertion. This RED chronology covers the original 15-test set. The later
raw-duplicate/raw-corruption proof (2 parameterized cases) was added after the
implementation as extra verification and is **not** presented as RED evidence.

### GREEN focused

Logs: `logs/turn5-retry2-append-green.log` (pre-format) and
`logs/turn5-retry2-append-green-final-postformat.log` (final).

Same command as RED. Final recorded **exit 0; 17 passed, 2 warnings in 1.83s**
(14 cooperative + 3 settlement collected).

Per-file collection truth:

| File | Collected |
|---|---|
| `tests/agents/slo_agent/messaging/test_history_application.py` | 29 |
| `tests/agents/slo_agent/messaging/test_history_cooperative_append.py` | 14 |
| `tests/agents/slo_agent/history/test_settlement_failure.py` | 3 |

### Normal application regressions (scoped real-boundary set)

Log: `logs/turn5-retry2-append-regression.log`

```sh
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' -q \
  tests/agents/slo_agent/messaging/test_history_application.py \
  tests/agents/slo_agent/messaging/test_delivery.py \
  tests/agents/slo_agent/history/test_message_contract_reconciler.py \
  tests/agents/slo_agent/history/test_projector.py \
  tests/agents/slo_agent/messaging/test_provider_settlement_guard.py \
  tests/agents/slo_agent/tool_execution/test_tool_group_metadata.py \
  tests/agents/slo_agent/history/test_cooperative_yield_metadata.py
```

Recorded **exit 0; 225 passed, 320 warnings in 67.73s**.

### Scoped static

Log: `logs/turn5-retry2-append-static.log`

```sh
poetry run black --check <7 changed files>
poetry run mypy <5 changed source files>
```

Final recorded **Black exit 0, 7 files unchanged; mypy exit 0, no issues in 5
source files**. The first pre-format Black check found 5 files needing
reformatting; that intermediate exit 1 is retained in the same log and was fixed
before the final recheck. This is scoped static evidence only; the full static
gate remains unrun.

## Safety and test-boundary audit

- New tests use real `tmp_path` JSONL roots and both real adapters. They do not
  mock the stores or the filesystem and do not patch private methods. The
  repeated-cancellation test uses the existing `CompletionGate` executor seam
  from `test_queue_closure.py`; the redaction test uses the existing
  `monkeypatch.setenv` convention for an injected credential.
- The consented deploy-worker `tmp_path/bin/curl` chmod 0755 fixture was not
  requested or exercised. No executable/system/package/infrastructure mutation.
- Pre-existing dirty `SLO.md`, `docs/`, prior evidence and
  `preflight-blocker.md` (SHA-256
  `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`) were not
  modified. No commit, push, merge, PR or nested agent.

## Honest limits and remainder

1. **Unknown-write / fsync fault injection is not directly proven.** The
   implementation reuses the existing raw append-once path, which fsyncs before
   the metadata rewrite and returns only after the durable write. The scoped tests
   prove readback, dedup, conflict, duplicate raw ID, raw corruption, redaction
   and high-water repair, but they do not inject an unknown reply or fsync failure.
   That proof remains for the next bounded T1 increment.
2. **Raw group validator/startup/context/compaction barriers are not implemented.**
   A.8/A.9/A.12 remain open. Producers/consumers are deliberately not activated.
3. **Full suite remains BLOCKED.** `make test PYTEST_WORKERS=6` was not run
   because the complete non-E2E suite executes unauthorized executable fixtures;
   no exclusion/subset/serial substitute is claimed. Full static `make lint` was
   not run.
4. **Count correction:** the earlier "13 passed" figure is not a valid total for
   this run and is superseded. The accurate figures are **17 focused passed** and
   **225 scoped regression passed**. The 13 figure appears to be a prior partial
   count; it was not reproduced here and must not be used as the current total.
5. Independent early review of this append increment, final review and completion
   are not performed or claimed.
