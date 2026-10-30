# T5 continuation 109 — typed migration implemented; closure INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 109, retries 0. Unlimited user turn/dispatch budgets; no agents dispatched. No commit/push/PR/reset/clean/stash, specification, global, live or other-worktree changes.

## Implemented ownership migration

- `workflows/service.py::advance_from_launch_result` returns existing `HandleAdvanceOutcomeDAO`, containing one existing `DetachedWorkflowUiEffectDAO` for valid results, empty effects otherwise. Cache semantics unchanged, no durable advance claimed.
- Removed `LaunchResultOutcome` alias/export/import.
- Removed renderer `handle_launch_result`, `_orchestrator_session_id_from_result`, parser imports, platform launcher import and synchronous boolean `DetachedVisualizerLaunch`.
- `DetachedVisualizerSchedule` registers work only, returning None. Renderer keeps synchronous effect application and per-parent guard, emits no scheduling-success notice.
- App parses once through service and applies returned effects once. Both attached and detached use existing `_schedule_visualizer_launch` and captured-session `_run_visualizer_launch`; no new registry or DAO.
- Removed `_write_attached_visualizer_outcome`. Completed workers delegate to renderer `write_launch_outcome`, the shared five-status notice owner. Failed-outcome guard reset uses finally, surviving notice failure. Existing worker best-effort exception handling and identity-safe registry cleanup remain.
- Ordinary durable lifecycle, status/cache, inbox and catchup code unchanged. Existing explicit destination gateway remains unchanged: unavailable/Herdr refusal cannot fall through to platform.

Flow: raw tool result → service parser/cache → typed effects → renderer guard → app schedule callback → shared registered captured-session worker → launch_async/session gateway → renderer typed notice.

## Test-first and gates

All commands run from repository application root using `PYENV_VERSION=slo-harness`, existing Poetry environment; no environment installation.

Each named log below has matching `.exit` unless explicitly noted.

1. `bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/workflows/test_workflow_app_service.py`: `t5-109-service-red.log`, exit 1, 4 failed / 76 passed (old literal lacks effects).
2. Small service implementation, then helper with `tests/tui/workflows`: `t5-109-service-green.log`, exit 0, 117 passed.
3. Renderer schedule/outcome tests first: helper with `tests/tui/workflows/test_workflow_renderer.py`: `t5-109-renderer-red.log`, exit 1, 14 failed / 62 passed (missing schedule contract).
4. Renderer implementation, helper with whole workflows directory: `t5-109-renderer-green.log`, exit 0, 118 passed.
5. Receive-path asynchronous expectations before caller migration: helper with `tests/tui/test_workflow_receive_path.py`: `t5-109-app-red.log`, exit 1, 20 failed / 67 passed.
6. Caller/alias/formatter coherent migration: helper with workflows, receive-path, herdr_attached, herdr_viewer_replacement: `t5-109-app-green.log`, exit 0, 165 passed.
7. Extended mounted composition matrix in existing `test_herdr_attached_composed.py` to both attached and detached parents, each enabled/auto_off/unavailable: `t5-109-composed.log`, exit 0, 68 passed including helper baseline. Detached persisted parent is distinct from TUI owner. Actual tool-result → service → renderer → registry → session gateway → registered regular fake CLI asserts exact split/rename/run parent, repeat deduplication, no OS fallback or focus/get/close. Synthetic/Faux only; not live pane paint.
8. Initial surrounding command contained nonexistent `test_sub_agent_routing.py`: `t5-109-surrounds.log`, exit 4, no tests run. Corrected to `test_subagent_event_routing.py` and added shutdown.
9. Corrected helper arguments: workflows, test_workflow_receive_path.py, test_visualizer_launcher.py, test_subagent_event_routing.py, test_herdr_attached.py, test_herdr_attached_composed.py, test_herdr_viewer_replacement.py, test_herdr_visualizer.py, test_herdr_inbox_cutoffs.py, test_herdr_app_shutdown.py. `t5-109-surrounds-corrected.log`, exit 0, 252 passed.
10. `make test`: `t5-109-full.log`, exit 0, **8152 passed, 19 deselected, 600 warnings**, 703.96 seconds. Afterwards Black only reformatted one test signature; no behavior changes.
11. Black scoped files: `t5-109-black.log` / `t5-109-black-final.log`, exit 0.
12. Scoped mypy first found one new test Literal annotation error; corrected it. `make lint`: `t5-109-lint.log`, exit 2, **295 errors / 60 files**, unwaived. `t5-109-lint-comparison.log` normalizes line/column numbers with Counter against 107: no added or removed diagnostic rows. This is not global static green.
13. `git diff --check`, `dpkg -V coreutils`: `t5-109-diff.log` / `t5-109-coreutils.log`, both exit 0 and silent.

## Remaining closure and truthful verdict

**INCOMPLETE for requested overall closure**, not another read-only continuation: the cohesive typed migration and mounted fake-gateway proof are implemented and full tests pass. No known new runtime defect was demonstrated. However the complete requested on-disk prerequisite audit (exact T5 sample inventory, accepted reviews, C lifetime and all requested Textual/Faux guidance) was not completed. One combined KB/spec read was truncated; do not count it as full ingestion. Canonical D 7.1–7.5 and A2 contract were visible and used. Project instructions and docs/RESEARCH were provided in session context, not all freshly verified on disk. Do not mark this a fully closed READY handoff until those reads and final convention audit are complete.

Attached read closure, full T5/T6 and independent review remain later. No live Herdr compatibility, OS window, provider access or viewer-paint claim. No KB edits because user prohibits global edits. Historical receipts remain intact.
