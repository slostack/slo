# Implementation — T1 compaction keeps marked tool groups whole

**Status:** bounded compaction slice implemented and focused-green. **A.2 remains
PARTIAL / INCOMPLETE.** No producer activation, provider race (T2), tools policy
(T3), TUI activation (T4), full gates, final review or completion is claimed.

Baseline `82c3f5c6de9345af34a673a3d975366ca8c1624c`, repo `message-queue`,
application root `/root/Code/slo-message-queue/slo`.

## Scope delivered

Spec `96.a.2` §6.3.5 and acceptance A8/A12 compaction obligations:

- **Validate raw groups before select/write/remove.** `SessionHistoryProjector`
  now exposes `compaction_retain_sequence(*, events, retain_from_sequence)`; it
  reconstructs and settles every raw marked group through the existing
  `_validated_tool_group_states` owner (shared with `validate_tool_groups`) and
  raises `UnsettledToolGroupError` for any unresolved/malformed group.
  `FilesystemSessionHistoryStore._select_message_compaction_sync` calls
  `validate_tool_groups` on the actual active raw events before computing
  coverage. `_resolve_retain_boundary_sequence` calls
  `compaction_retain_sequence` before `_build_post_compaction_events`, so both
  `compact_to_boundary` and the compatibility
  `truncate_to_compaction_boundary` fail before writing or archiving.
- **Never slice a marked group.** A requested cut that falls inside a group
  (`start < boundary <= end`) is lowered to the group's first event. The whole
  settled or disposed group is therefore either retained whole in the tail or,
  when wholly before the cut, removed whole. No partial opening/result/marker
  can survive.
- **Boundary metadata stays truthful.** `_compact_to_boundary_sync` resolves the
  pinned boundary before building the summary and writes the actual first
  retained event id into `first_kept_entry_id`. The compatibility
  `truncate_to_compaction_boundary` retargets a caller summary through
  `_summary_at_boundary`. `SessionHistoryProjector._context_event_slice` also
  resolves the summary pointer against raw events and applies the same pin, so
  replay cannot drop pinned members even when a summary points at a disposed
  opening that projection later excludes.
- **Disposed no-start groups are audit-only.** They contain no `messaging_v1`,
  so their removals require no A.1 message-application coverage. They are still
  validated and never sliced. A.1 message-application selection and coverage
  logic is otherwise unchanged; `selection.message_ids` is still computed only
  from `messaging_v1` events before the pinned boundary.

## Test-first chronology

1. New file `tests/agents/slo_agent/history/test_compaction_tool_groups.py` was
   written first and run against the pre-change store:
   **RED exit 1, 6 failed, 2 passed**,
   `logs/turn6-dispatch10-compaction-groups-red.log`.
   Failures: settled cut, disposed cut, and unresolved-excluded-turn on both
   adapters. The two passing cases were the non-slicing "boundary after group"
   case on each adapter, which already worked.
2. Implementation added as described above.
3. Focused GREEN: **exit 0, 8 passed**,
   `logs/turn6-dispatch10-compaction-groups-green.log`.
4. Scoped affected regression rerun after formatting: **exit 0, 309 passed**,
   `logs/turn6-dispatch10-compaction-groups-regression-final.log`.
5. Scoped static: Black `--check` exit 0; mypy on both changed source files
   exit 0, `logs/turn6-dispatch10-compaction-groups-static.log`.

Every new proof writes/reads real temporary JSONL through both
`FilesystemSessionHistoryStore` and `TreeBasedFilesystemSessionHistoryStore` and
drives the real `select_message_compaction` / `compact_to_boundary` commands. No
private method patching, mocks or harness. The unresolved proof asserts active
log and metadata bytes are identical and no archive/candidate file exists.

## Evidence

| Item | Value |
|---|---|
| RED command | `PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' -q tests/agents/slo_agent/history/test_compaction_tool_groups.py` |
| RED result | exit 1, 6 failed, 2 passed, 2 warnings |
| GREEN command | same runner over the new file |
| GREEN result | exit 0, 8 passed, 2 warnings |
| Regression command | same runner over the 17 scoped files listed below |
| Regression result | exit 0, 309 passed, 2 warnings |
| Static | scoped Black `--check` exit 0; mypy on `projector.py` and `filesystem_store.py` exit 0 |
| Raw logs | `logs/turn6-dispatch10-compaction-groups-{red,green,regression,regression-final,static}.log` |
| Source hash `projector.py` | `c62194473c4791c7fa4dd6ae614e20838f511371b1a77d228d5c57f48d327d36` |
| Source hash `filesystem_store.py` | `d1b52a79277ca6be85f22441610af90a28f238a447177e21dda6b9d12eaeef41` |
| Test hash | `a0a54d53d51991ecbfa5604c20e461dd57898ecaba27e4822aab655e411c8fb1` |

Regression files: `test_compaction_tool_groups.py`,
`test_projector_tool_groups.py`, `test_projector_compaction.py`,
`test_projector.py`, `test_projector_recovery.py`,
`test_message_contract_reconciler.py`, `test_filesystem_store_compaction.py`,
`test_compaction_transaction.py`, `test_filesystem_store.py`,
`test_tree_store.py`, `test_cooperative_yield_metadata.py`,
`test_settlement_failure.py`, `test_history_file_certification.py`,
`messaging/test_history_application.py`,
`messaging/test_history_cooperative_append.py`,
`test_session_manual_compaction.py`, `test_session_compaction_integration.py`.

Environment for every run: `SLO_ENV=test`, `SLO_ROOT_DIR=$PWD`,
`SLO_APP_DIR=$PWD`, `SLO_APP_NAME=slo`, `SLO_LOG_FORMAT=text`,
`SLO_DEFAULT_MODEL_NAME=gpt-5.4`, `SLO_AUTO_VISUALIZE=0`,
`SLO_HERDR_DISABLED=1`,
`SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked`, `COLUMNS=120`,
`LINES=40`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=$PWD`, cwd application root.

## Still open (bounded remainder)

- **T1 startup/context** raw validation is done at focused level from the prior
  slice; this slice closes the compaction select/write/remove barrier only.
- Interrupted provider-context exclusion (§6.4.5) is still **not** implemented.
- Producers/consumers, T2 provider control/race/cleanup, T3 tools policy and
  T4 TUI activation remain **not started** in this assignment.
- `make test PYTEST_WORKERS=6` remains **BLOCKED** by executable-fixture
  consent; no skip/xfail/subset substitute. Full static gate remains **UNRUN**;
  YAML-stub baseline remains **UNESTABLISHED**.
- Independent `gpt-6.1-sol` high-reasoning final review and completion remain
  separately pending; author receipts do not substitute.

## Constraints preserved

- Only consented executable fixture remains existing
  `tests/cli/test_deploy_install_worker.py` `tmp_path/bin/curl` chmod 0755,
  child-only PATH, verified temp roots — **not run**. No other executable
  mutation; no package/system/installer/infrastructure/git writes or nested
  agents.
- Unrelated dirty `SLO.md`, `docs/`, prior evidence and immutable preflight sha
  `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`
  are preserved.
- Counters: actual turn 6, this dispatch **10/20**; 60-turn max; prior partial
  turns 7/4/4/8/8 calls; this is retry 2 of 3; ten prior execution retries; no
  abort retried. No commit, push, merge, PR or nested agents.
