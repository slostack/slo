# RH4 — rewrite snapshot/current-active validation repair

**Status: RH4 repaired at focused/journey level. A.2 remains PARTIAL / INCOMPLETE.**
Baseline unchanged: repo `message-queue`, HEAD
`82c3f5c6de9345af34a673a3d975366ca8c1624c`, application root
`/root/Code/slo-message-queue/slo`.

## Requirement

Spec 96.a.2 §6.3.5 and A8/A12: never remove an unresolved group or silently lose
a group at any rewrite entry point. Audit archives do not make a stale rewrite
safe. RH4's source defect was that `compact_to_boundary` reread/compared active
history only when `messaging_compaction_id` was supplied, and compatibility
`truncate_to_compaction_boundary` never did.

## Change

`src/agents/slo_agent/history/filesystem_store.py`

- `_require_current_active_snapshot_sync` (`:1714`) runs while the existing
  store serialization lock is held. It rereads the CURRENT active history
  through `_load_events_sync`, validates every raw marked group with
  `SessionHistoryProjector.validate_tool_groups`, and compares the complete
  ordered snapshot digest with the caller-supplied source. Mismatch raises
  `MessageStoreError`; unresolved active groups raise
  `UnsettledToolGroupError`; a missing active log preserves
  `FileNotFoundError`.
- `_compact_to_boundary_sync` (`:1625`) calls it before the messaging branch,
  metadata read, candidate construction, archive, activation or metadata write.
  This covers non-messaging/direct compaction too.
- `_truncate_to_compaction_boundary_sync` (`:1693`) calls it before boundary
  resolution and the compatibility candidate/archive/activation path.
- Tree remains a byte-preserving delegate; both adapters therefore use the same
  check under the same flat-store lock.

No selection, A.1 message coverage, projection, append-once, summary guard,
metadata, archive naming, dependency, framework or executable behavior changed.
Existing compatibility success and group-cut pinning remain intact.

## Tests first

`tests/agents/slo_agent/history/test_compaction_tool_groups.py`

- `test_rewrite_refuses_stale_source_after_new_marked_group` (`:377`) runs for
  flat and tree adapters and both public rewrite APIs. It captures a valid
  snapshot, appends a new settled marked group (opening + result), then calls
  `compact_to_boundary` without a messaging id or
  `truncate_to_compaction_boundary` with the earlier snapshot. It asserts
  refusal, byte-identical active log and metadata, no candidate/archive, and
  both the new opening and result still present.
- `test_compatibility_truncation_pins_cut_inside_group_and_keeps_it_whole`
  (`:430`) runs for flat and tree adapters. Compatibility truncation succeeds,
  the cut inside the group pins to the group's first opening, the whole group
  remains, and the summary `first_kept_entry_id` names the actual pin.
- New tests use real temp-root JSONL files and public store APIs only; no
  monkeypatch, private test patch or substitute framework.

RED was captured by temporarily removing the two new call sites from the source
under test, then restoring them; tests themselves were never patched. Restored
source hash below is the final tested source.

## Exact evidence

Common cwd: `/root/Code/slo-message-queue/slo`.

Environment for every pytest command:

```bash
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
```

RED:

```bash
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' \
  tests/agents/slo_agent/history/test_compaction_tool_groups.py -q
```

exit `1`; `4 failed, 10 passed`. Full raw log:
`logs/turn7-rh4-red.log` (`sha256 18d376d4386b960a523cb785a6af25ffeb30f9b43b995cb3d8570493bad7815c`).

GREEN, same argv:

exit `0`; `14 passed`. Full raw log:
`logs/turn7-rh4-green.log` (`sha256 6305da212b1de827c3b00dd50142155a58b2a532dee7da4a637429ededfe199b`).

Scoped regression, same environment/argv, these modules:

```bash
tests/agents/slo_agent/history/test_compaction_tool_groups.py
tests/agents/slo_agent/history/test_compaction_transaction.py
tests/agents/slo_agent/history/test_filesystem_store_compaction.py
tests/agents/slo_agent/messaging/test_history_application.py
tests/agents/slo_agent/messaging/test_retained_recovery.py
tests/agents/slo_agent/history/test_message_contract_reconciler.py
tests/agents/slo_agent/history/test_openrouter_writer_secrecy.py
```

Combined exit `0`; `137 passed` (final formatting run: `14 passed` + `123 passed`).
Raw logs: `logs/turn7-rh4-regression-first-attempt.log` (the first attempt
recorded `1 failed, 136 passed`; the strict raw reader rejected a pre-existing
compatibility fixture whose compatibility path intentionally does not advance
metadata), `logs/turn7-rh4-regression.log` (final `123 passed`), plus the green
`14 passed` log above. The repair uses the existing public `_load_events_sync`
active-history read, preserving that compatibility behavior while still
comparing exact ordered snapshots.

Static, scoped:

```bash
poetry run black --check src/agents/slo_agent/history/filesystem_store.py \
  tests/agents/slo_agent/history/test_compaction_tool_groups.py   # exit 0
poetry run mypy src/agents/slo_agent/history/filesystem_store.py \
  tests/agents/slo_agent/history/test_compaction_tool_groups.py   # exit 1
git diff --check -- <same two files>                              # exit 0
```

Black is clean (`logs/turn7-rh4-black-check.log`, sha256
`36cd8d248acf30768dfac09822c95c36dfc7c0ae3c30250129d50ef265213c37`). Mypy has
two pre-existing `BaseMessage` attribute errors at
`test_compaction_tool_groups.py:253-254`, unchanged prior assertions; no new
source error. Raw log `logs/turn7-rh4-mypy.log`
(`sha256 3d95090eb528271abd018f7623f8a6dd95122d246a94f5de7269953908f7fd7b`).
No static baseline is claimed as established.

Final tested hashes:

- `src/agents/slo_agent/history/filesystem_store.py`
  `22ffee414d2979c2927cb1fa29b1532118ec3f6ae1e0eaccc4ad3023652237ba`
- `tests/agents/slo_agent/history/test_compaction_tool_groups.py`
  `ec39ee647d1b3d6692965a62040324af76312859713f3a74fc323aad8de20a48`

## Preserved and not done

- RH1, RH2 and RH3 repairs and existing messaging coverage/select path preserved.
- No full `make test PYTEST_WORKERS=6` run; remains BLOCKED by other fixture
  consent. No exclusions/substitutes/mode evasion. Full static gate remains
  UNRUN.
- No T2, interrupted-context §6.4.5, producer/consumer activation, tools, TUI,
  package/installer/herdr/system/infrastructure or git write. No nested agents.
- Only consented executable fixture (existing deploy-worker temp `bin/curl`) was
  not run; no executable mutation.
- Unrelated dirty `SLO.md`, `docs/` and prior reports preserved.

Counters: turn **7**, dispatch **5/20**; prior partial counts
**7/4/4/8/8/11**; ceiling **60 turns**; **12** prior execution retries; no abort
retried. This repair consumed no execution retry and makes no final-review,
completion or milestone-acceptance claim.
