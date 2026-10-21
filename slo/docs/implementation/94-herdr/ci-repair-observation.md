# CI repair — observation lifecycle (TestObservationLifecycle)

Status: **READY** — all 3 target failures corrected with principled fixes and all
exact assertions preserved. Both early-review findings ER-01 and ER-02 are closed
with deterministic RED→GREEN evidence. Owner files: `src/tui/app.py` (edited),
`tests/tui/test_workflow_session_list.py` (edited — one additive regression test,
no existing assertion touched), `tests/tui/test_herdr_init_rollback.py` (edited —
one additive regression test), this report (rewritten). No other files touched.

Environment: `environments/tests.env` sourced, `SLO_HERDR_DISABLED=1`,
`SLO_AUTO_VISUALIZE=0`, `PYTHONPATH=$PWD`. Each failing case run RED first, then
the smallest principled correction, then the full modules plus Herdr
init/replacement/activation regressions.

## CI trace context

`/tmp/herdr-ci-4ab10b0.log`, MR pipeline 2970613678 / job 17338411077, commit
`4ab10b0`. 11 failed / 10490 passed. Three failures belong to this concern:
- `test_mount_registers_one_five_second_timer_and_paints_immediately` — `assert 2 == 1`
- `test_new_session_discards_old_projection` — old service returned rows after `/new`
- `test_teardown_order_is_coordinator_service_sink_panel[new_session]` — missing `service` step

## Failure 1 — two 5.0 s timers (FIXED)

RED: 2 `set_interval(interval=5.0)` calls where 1 expected.

Root cause (diagnosed, not assumed): `on_mount` binds observation
(`_bind_workflow_observation`), then the Herdr mount runtime task
(`_initialize_mounted_delivery` → `_finish_replacement_runtime`) called
`_bind_workflow_observation` again. The second call tore down and rebuilt the
identical owner, registering a second 5.0 s timer. Confirmed by tracing: two
`WorkflowProgressCoordinator.start` calls, one on a coordinator that was closed
mid-bind (`close` ran while the new coordinator's `start` had not yet completed).

Fix (principled): mount and replacement both converge on one runtime delivery
point (`_finish_replacement_runtime`). Introduced
`_ensure_workflow_observation_bound` as the single re-entry point; it rebinds
only when the selected session lost or never had observation, and keeps an
intact binding. `on_mount` still binds the initial owner once. This preserves
the historyless-observation contract and the Herdr delivery/cutoff seams.

Evidence: `test_mount_registers_one_five_second_timer_and_paints_immediately` PASSED.
CI-default model also yields exactly one 5.0 s timer.

## Failure 2 — `/new` does not discard the old projection (FIXED)

RED: after `/new`, `await old_service.load_session_snapshot()` still returned
rows instead of an empty snapshot.

Root cause: `_transfer_replacement_delivery` set `_workflow_app_service = None`
*before* the old owner's observation was closed, so `_close_workflow_observation`
never saw the service — the old service's caches stayed live and rows crossed
sessions. `_close_workflow_observation` also never cleared `_workflow_app_service`,
leaving a dangling reference that a later close would close twice.

Fix: `_close_workflow_observation` now captures and clears
`_workflow_app_service` itself (self-contained, idempotent). The old owner's
ordered teardown (coordinator → service → sink → panel) is run once, from
`_finish_replacement_commit` after adoption (preserving "prepare candidate
before irreversible old close" — `_transfer_replacement_delivery` keeps only
delivery-boundary release: timers + lease). No rows, caches or timers cross
sessions.

Evidence: `test_new_session_discards_old_projection` PASSED — panel rows `{}`
and old service returns empty snapshot with `_closed is True`.

## Failure 3 — teardown order `[new_session]` (FIXED; prior diagnosis retracted)

**Retraction:** my prior report claimed an "irreducible test-contract conflict"
requiring an assertion relaxation or a per-owner panel, and claimed line 569 ran
at/after unmount. **Both claims were false.** The independent early review
(`ci-repair-early-review.md`, ER-01) traced the actual chain: the assertion at
line 569 runs **inside** `async with app.run_test`, before unmount; the extra
`panel` entry comes from `_bind_workflow_observation`'s leading
`_close_workflow_observation` call during the successor's bind, which reset the
panel again even though the explicit commit close had already retired every
owner slot. The conflict was manufactured by a non-idempotent unbound close,
not by the test contract.

Actual call chain before this correction:

```text
_start_new_session
  → _finish_replacement_commit
    → adopt candidate
    → _close_workflow_observation          # coordinator → service → sink → panel (exact 4)
    → _finish_replacement_ui → _finish_replacement_runtime
      → _ensure_workflow_observation_bound (identity cleared)
        → _bind_workflow_observation
          → _close_workflow_observation    # all slots None, yet panel.reset ran AGAIN
          → construct/start successor observation
  → assertion at line 569 sees [..., 'panel', 'panel']
```

Fix (ER-01): `_close_workflow_observation` is now genuinely inert when unbound —
it captures and clears all three owner slots first and returns without touching
the panel when there is no coordinator, service or sink left to retire. The
explicit commit close is preserved verbatim, so the old owner is still retired
in the exact coordinator → service → sink → panel order even when the
successor's runtime startup is suppressed by shutdown (`_finish_replacement_ui`
returns early on `not _runtime_may_start`; no successor bind, no panel reset).

Evidence: `test_teardown_order_is_coordinator_service_sink_panel[new_session]`
PASSED with its exact assertions unchanged; `[unmount]` PASSED. New regression
`test_unbound_close_is_inert_and_replacement_stays_bound` proves: repeated
unbound close never resets the panel; the shutdown-suppressed replacement still
runs exactly one explicit close; a healthy adopted successor stays bound across
`_ensure_workflow_observation_bound` and is closed exactly once at unmount.

## ER-02 — inbox rollback orphaned the real observation service (FIXED)

Reviewer's mounted diagnostic (reproduced): with `ensure_session_inbox` raising,
rollback cleared `_workflow_app_service` without closing the service or clearing
the coordinator/sink/binding identity; the ensure helper then saw a matching
session ID and returned despite the missing service; unmount closed the
coordinator but never the service (`coordinator_closed=True,
service_closed=False` after unmount).

Fix: rollback now retires the captured observation owner through authoritative
captured-ownership, not slot-clearing. `_rollback_session_delivery` (binding
branch, after the lease release await) delegates to the new
`_close_captured_observation_owner`, which closes the whole captured
coordinator → service → sink trio and resets the panel exactly once **only
while the captured identity is still the published one** (binding session ID,
session identity, coordinator and sink all still present). If any successor
binding (rebind, adoption or an earlier close) displaced the capture, nothing
is closed or cleared — the successor owns its own close, and rollback after the
lease-release await never touches it. `_ensure_workflow_observation_bound` now
requires the whole healthy trio (identity plus coordinator, service and sink),
so a matching session-ID string alone never proves a healthy binding.

The reviewer's optional simplification (remove the initial `on_mount` bind and
the ensure helper) was considered and **not** adopted: removing the mount bind
would leave the window between mount and the mount runtime task with no
observation (the first 5.0 s paint and lifecycle-refresh requests would be
dropped), and per the review the helper is acceptable once ownership and
rollback correctness are proved. All mount/cutoff/retained cleanup boundaries
are preserved.

Evidence: new `test_rollback_closes_captured_observation_owner` (deterministic
RED before the fix — real coordinator `_closed` stayed False, service never
closed) now proves the captured owner's timer/read task joined, service closed,
sink disposed and panel reset exactly once, with the app slots absent; unmount
is inert afterwards. Successor-displacement cases in
`test_herdr_init_ownership.py` (`test_rollback_preserves_successor_after_release`,
`test_captured_absent_store_does_not_release_successor`,
`test_initialization_revalidates_captured_binding`,
`test_rollback_releases_captured_owner`) remain green unchanged.

## Verification summary

- Exact three original failures + both teardown params + both new regression
  tests: **6 passed**.
- Full scoped modules: `tests/tui/test_workflow_session_list.py`,
  `tests/tui/test_herdr_init_rollback.py`, `tests/tui/test_herdr_init_ownership.py`
  → **137 passed**.
- Close/replacement regressions: `test_herdr_init_branches`, `test_herdr_replacement`,
  `test_herdr_all_owner_cutoffs`, `test_herdr_combined_cutoffs`,
  `test_herdr_inbox_cutoffs`, `test_herdr_inbox_disposition`,
  `test_herdr_session_lifecycle`, `test_herdr_prompt_registration`,
  `test_herdr_activation_faults`, `test_herdr_activation_composed`,
  `test_workflow_receive_path`, `test_subagent_event_routing`,
  `test_startup_notice_cutoff` → **239 passed**.
- Wider Herdr TUI sweep: `test_herdr_app_shutdown`, `test_herdr_activation_cutoffs`,
  `test_herdr_activation_notices`, `test_herdr_activation`, `test_herdr_attached_composed`,
  `test_herdr_attached`, `test_herdr_auth_capture`, `test_herdr_initialization`,
  `test_herdr_multiple_viewer_owners`, `test_herdr_platform_commit`,
  `test_herdr_stale_release`, `test_herdr_viewer_registry`,
  `test_herdr_viewer_replacement`, `test_herdr_viewer_retention_composed`,
  `test_herdr_visualizer` → **117 passed**.
- Integration: `tests/integration/test_workflow_progress_tui.py`,
  `tests/integration/test_workflow_child_abort_tui.py` → **22 passed**.
- `mypy src/tui/app.py` and both edited test files: clean. `black --check` on all
  four scoped files: clean. `git diff --check`: clean. `dpkg -V coreutils`: clean.
- No sleeps added, no timeouts raised, no assertions weakened or relaxed, no
  subagents, no commits/pushes, no full suite run, no writes outside the five
  scoped files.

## Out-of-scope observation (worker C's files, flagged for fan-in)

`tests/tui/workflows/test_session_progress_screen.py` (worker C's new
`TestRestoreConvergence` cases) shows ordering-dependent failures when run
together with `test_visualizer_launcher.py` /
`test_headless_workflow_visualizer.py` (3 failed), but **54 passed** when the
module runs standalone and **8 passed** for `TestRestoreConvergence` standalone.
The failures live entirely in C's owned files and reproduce independently of
this change (they involve no app.py observation path); reported for C's
coordinated pass, not edited here.

## Risks / dependencies

- `_rollback_session_delivery` (binding branch) is now async-effective: it awaits
  the captured owner's close. All its callers already await it; no new task or
  ordering hazard introduced (it runs inside the mount/replacement task).
- The helper `_ensure_workflow_observation_bound` and the identity field
  `_workflow_observation_session_id` are retained per the review's allowance;
  both now require the full trio, so the false "intact binding" inference is
  gone.
- Full integrated/static/smoke gates remain scheduled after fan-in per
  `current-ci-repair-plan.md`; this report is scoped author evidence, not final
  Review or Completion.
