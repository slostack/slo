# T5 attached acceptance 106 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 106, retries 0. User turn/dispatch budgets unlimited; no agents launched. No commit/push/PR/reset/clean/stash/global/live/specification/other-worktree changes. Selection files untouched.

## Verified old-test migration and runtime defect

Read the complete 105 full failure log (including its truncated tail separately) and 104/105 receipts. The exact five failures are methods in ONE file, `tests/tui/test_subagent_event_routing.py::TestVisualizerAutoLaunch`, not five files:

- `test_first_spawn_launches_visualizer_once`
- `test_launch_passes_parent_session_id`
- `test_success_writes_open_notice`
- `test_failure_writes_manual_hint`
- `test_cleanup_resets_launch_guard`

Migrated only that class plus its asyncio import: explicitly opt into the production auto-launch gate; capture and await the actual registered task with a bounded wait rather than using pilot pauses as completion evidence; assert terminal task and empty registry. Existing once-per-run, original parent, opened notice, manual hint and cleanup/relaunch assertions remain intact. The synchronous platform leaf is still mocked; this is not Herdr wire acceptance.

Source evidence: `VisualizerLauncher.launch_async` checks `_auto_visualize_enabled` before dispatching; `SloTUI._schedule_visualizer_launch` registers the task synchronously and `_on_visualizer_launch_done` removes it by identity. The migrated tests initially failed with KeyError: no registered task. Their original injected sessions have history disabled. `_initialize_session_delivery` intentionally leaves `_delivery_quiescing=True` for unsupported inbox delivery (explicitly asserted by `test_herdr_init_branches.py`). Applying that inbox-only state unconditionally to viewer scheduling broke previously supported historyless platform launch.

Bounded production correction in `src/tui/app.py`: viewer scheduling and both worker cutoffs apply delivery quiescence only when inbox delivery is supported. Closing, replacement transition, captured session identity, master auto flag and registry deduplication remain enforced. No history requirement was added to the original tests; no initialization/inbox semantics changed. New production changes are below 50 lines and followed the failing migrated tests before implementation.

## Exact commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Every focused test uses `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`, which also adds DAO/projection tests. Full logs and numeric exits are adjacent `t5-106-<receipt>.log` and `.exit`.

| Receipt | Arguments / command | Result |
| --- | --- | --- |
| old-red | `tests/tui/test_subagent_event_routing.py::TestVisualizerAutoLaunch` before edits | 5 failed, 62 passed; exit 1 |
| old-green | subagent event routing + attached + platform launcher after test migration only | 5 failed, 116 passed; exit 1; absent registry tasks, not green |
| old-green2 | previous partition + viewer registry + viewer replacement + initialization branches | 142 passed, 2 warnings; exit 0 |
| black | `PYENV_VERSION=slo-harness poetry run black --check src/tui/app.py tests/tui/test_subagent_event_routing.py` | two files unchanged; exit 0 |
| diff | `git diff --check` | silent exit 0 |
| coreutils | `dpkg -V coreutils` | silent exit 0 |

## Finite attached evidence map and remaining obligations

| Contract | Evidence / limitation |
| --- | --- |
| Original platform first/repeat/parent/outcome/reset | Five migrated tests pass, actual async worker and platform joining; platform spawn leaf mocked |
| Historyless platform compatibility | Previously failed migrated tests now pass without modifying session history; initialization surrounding retains unsupported inbox quiescence |
| Auto-off, platform/Herdr/unavailable selector | Existing `test_herdr_visualizer.py`; not freshly included in 106 partition |
| Five typed outcomes, late replaced/closing/quiescing, notice/gateway error | Existing `test_herdr_attached.py` included; gateway mocked |
| Registry/replacement/drain/admission | Existing registry/replacement tests included; 105 broader 621-pass evidence historical |
| Actual mounted config/Faux/bootstrap/persisted requested parent → real gateway → registered fake Herdr split/rename/run | **NOT ADDED / NOT PROVED** |
| Actual fake-wire pending/repeat/failed/revoked/auto-off mapping | **Not completed in this continuation** |
| Public unmount late outcomes plus no new admission combined with 105 drain evidence | Existing coverage not yet completely mapped/reverified |
| Complete affected prerequisite read closure | **Incomplete**; 106 read shared routing/testing/ownership, Python root/style, generic coding/cadence/declarative, Textual, KB Welcome/slo README/gotchas, routing record, D7.1–7.5; remaining scope/C/accepted reviews/workflow/Faux/build/current-doc closure not claimed |
| Final full make test/smoke/lint and all-changed Black/static baseline comparison | **Not run in 106**; prior failures remain unwaived, no full-suite pass claim |

Attached-only outcome formatting remains explicitly interim. Shared renderer consolidation belongs with the next detached migration; neither was changed here. No live Herdr, provider, terminal-window, process-running or viewer-paint claim.

**Verdict: INCOMPLETE, not READY attached and not all-T5.** The exact five legacy failures have bounded passing evidence, including a genuine historyless runtime compatibility correction; mounted real-gateway acceptance, read closure and final gates remain required.
