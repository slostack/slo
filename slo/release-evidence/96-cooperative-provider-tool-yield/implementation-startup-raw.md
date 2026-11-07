# Implementation — startup raw marked-group validation (96.a.2 §6.3.1)

**Status:** bounded T1 startup slice implemented and focused-green. **A.2 remains
PARTIAL / INCOMPLETE.** No producer activation, compaction barrier, provider race,
tools policy, TUI activation, final review or completion is claimed.

Baseline `82c3f5c6de9345af34a673a3d975366ca8c1624c`, repo `message-queue`,
application root `/root/Code/slo-message-queue/slo`.

## Scope delivered

Spec `96.a.2` §6.3.1 startup/readiness obligation:

- `SloAgentSession._require_settled_raw_tool_groups()` reads **every**
  `application_evidence` page with the existing bounded page seam, assembles the
  raw active events in append order, and calls
  `SessionHistoryProjector.validate_tool_groups(events=...)` **once**.
- It runs inside `_reconcile_message_applications`, which startup executes under
  the ownership/history barrier (`_start_messaging_owned` holds
  `self._history_barrier`). It runs before compaction reconciliation, any SQLite
  state transition (`reset_unprepared_claims`) and replay projection.
- No page-local validation and no early readiness: an unresolved marked group in
  an otherwise excluded/incomplete turn still fails startup. Marker/metadata
  problems fail closed with `UnsettledToolGroupError`; no fake legacy healing and
  no readiness publication occurs.
- A failed startup still unwinds through `_release_messaging_resources`, so the
  A.1 store close and execution-lease release path is preserved.
- The later `_load_message_history` / projector validation remains in place; the
  new startup check is the required raw-page-assembly barrier before it.

## Test-first chronology

New file `tests/agents/slo_agent/messaging/test_startup_raw_tool_groups.py`
was written first and run against the baseline barrier absence:

1. **RED exit 1, 4 failed, 4 passed** —
   `logs/turn6-dispatch7-startup-raw-groups-red.log`.
   The four failures are the flat/tree unresolved-opening and unknown-metadata
   startup proofs, which reach the later projection (`AssertionError: startup
   projected history before validating raw tool groups`) instead of failing at
   the startup barrier.
2. Implementation added; focused **GREEN exit 0, 8 passed** —
   `logs/turn6-dispatch7-startup-raw-groups-green.log`.
3. After scoped Black formatting, focused re-run **exit 0, 8 passed** —
   `logs/turn6-dispatch7-startup-raw-groups-green-final.log`.
4. Affected regression set **exit 0, 246 passed** —
   `logs/turn6-dispatch7-startup-raw-groups-regression.log`.

Both real adapters (`FilesystemSessionHistoryStore`,
`TreeBasedFilesystemSessionHistoryStore`) are exercised by every case. The proofs
use real sessions, real SQLite messaging state and real temporary JSONL history.
Two one-method subclasses only configure existing seams: one forces
`application_evidence(..., limit=1)` so a settled group spans every page, and one
makes an early `load_events` projection impossible so a missing startup barrier
cannot be hidden by the later context check.

Cases:

| Case | Expectation |
|---|---|
| Unresolved opening in an incomplete/excluded turn | startup fails `UnsettledToolGroupError`, before projection |
| Unknown `tool_group_v1` schema version | startup fails `UnsettledToolGroupError`, before projection |
| First full opening + affirmative no-start marker | startup succeeds, readiness true, real `LocalSessionMessagingClient` composes |
| Settled two-call group split over one-event evidence pages | assembled across pages, startup succeeds |

## Evidence

| Item | Value |
|---|---|
| RED command | `PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' -q tests/agents/slo_agent/messaging/test_startup_raw_tool_groups.py` |
| RED result | exit 1, 4 failed, 4 passed, 2 warnings |
| GREEN result | exit 0, 8 passed, 2 warnings |
| Regression result | exit 0, 246 passed, 324 warnings, 75.88s |
| Regression files | new file + `test_delivery.py`, `test_retained_recovery.py`, `test_injected_activation.py`, `test_provider_settlement_guard.py`, `test_history_application.py`, `test_projector_tool_groups.py`, `test_projector.py`, `test_message_contract_reconciler.py` |
| Scoped Black | exit 0, both changed files unchanged — `logs/turn6-dispatch7-startup-raw-groups-static.log` |
| Scoped mypy | exit 1, **pre-existing** `types-PyYAML` missing stub in `src/agents/slo_agent/skills/service.py:13`; no new error in this change |
| Source hash | `1d3ba140bb1f40bf014ae3ef3b670a8885a17d2fd41a2d92480c56bc1cf0cdef` (`sessions/service.py`) |
| Test hash | `dbe190d10581f3791268fa6420e8a08ab6975cd1ed663e4e4cb830d67e604b7c` (`test_startup_raw_tool_groups.py`) |

Environment for every run: `SLO_ENV=test`, `SLO_ROOT_DIR=$PWD`, `SLO_APP_DIR=$PWD`,
`SLO_APP_NAME=slo`, `SLO_LOG_FORMAT=text`, `SLO_DEFAULT_MODEL_NAME=gpt-5.4`,
`SLO_AUTO_VISUALIZE=0`, `SLO_HERDR_DISABLED=1`,
`SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked`, `COLUMNS=120`,
`LINES=40`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=$PWD`, cwd application root.

## Still open

- Compaction validation before select/write/remove is **not** wired.
- Interrupted provider-context exclusion (§6.4.5) is **not** in this slice.
- Producers, T2 provider control/race/cleanup, tools policy, TUI activation,
  full A1–A14, independent final review and completion remain pending.
- `make test PYTEST_WORKERS=6` remains **BLOCKED** by executable-fixture consent;
  full static is **UNRUN**; YAML-stub baseline remains **UNESTABLISHED**.
- Counters: actual **turn 6, this dispatch 7/20** (prior partial calls
  7/4/4/8/8), 60-turn ceiling, ten prior execution retries with **none in this
  task**, no abort retried. Log filenames prefixed `turn7-` elsewhere are
  historical labels, not a new turn. No commit, push, merge, PR, nested agent,
  package, system, installer or executable mutation.
