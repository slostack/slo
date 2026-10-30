# T5 replacement viewer 105 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 105, retries 0. User turn and dispatch budgets unlimited. No agents launched. No commit/push/PR/reset/clean/stash/specification/global/live/other-worktree changes.

## Implemented finite change

`src/tui/app.py` now prepares candidates under the submission gate, synchronously captures/revokes the predecessor and registers the retained commit, then releases the gate before joining it. The commit drains the viewer registry outside the gate before reacquiring it for preparation cleanup, captured old lease release, reporter close, adoption and runtime/UI refresh. Public caller cancellation joins the commit before propagation. Existing unmount joins replacement outside the gate and keeps its two cleanup owners.

`_session_transitioning` closes admission from commit registration through completion. Local submit/accepted/final registration, queue mutation/handoff, inbox eligibility and viewer schedule/worker/late outcome all refuse it. Runtime initialization deliberately remains allowed. Existing precommit candidate disposal, pool-copy policy, registered prompt execution policy and captured lease release remain unchanged. The guard clears only after completed adoption/runtime work; closing remains independently monotonic.

Tests added in `tests/tui/test_herdr_viewer_replacement.py`. One exact-AST expectation in `test_herdr_prompt_registration.py` now requires both flags while retaining the original no-await/no-hook assertion. Black also formatted that owned surrounding file.

## Branch map / exact verification

CWD: `/root/Code/slo-94-herdr-integration/slo`. All pytest commands below use `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` (approved Python 3.11.7 fallback, plus DAO/projection tests). Receipts are `t5-105-<name>.log` and `.exit` in this directory.

| Receipt | Arguments / behavior | Result |
| --- | --- | --- |
| drain-red | `tests/tui/test_herdr_viewer_replacement.py`; mounted viewer finalizer acquires submission gate, normal/repeated-cancel replacement | 2 failed (finalizer timeout), 62 passed; exit 1 |
| drain-green | new file + `test_herdr_replacement.py test_herdr_viewer_registry.py test_herdr_app_shutdown.py` under tests/tui | 90 passed; exit 0 |
| admission-red | new file; submit/accepted/register/queue/handoff/inbox/viewer with transition true and delivery quiescence false | 7 failed, 64 passed; exit 1 |
| admission-green | drain partition + prompt-registration/inbox-cutoffs/inbox-disposition/app | 1 failed (obsolete exact AST guard text), 329 passed; exit 1 |
| admission-green2 | same without test_app after updating required AST expression | 158 passed; exit 0 |
| platform | new file + test_herdr_visualizer.py + test_herdr_attached.py | 95 passed; exit 0 |
| surrounding | `tests/tui/test_herdr*.py tests/tui/test_app.py tests/tui/test_visualizer_launcher.py tests/tui/workflows tests/tui/test_workflow_receive_path.py` | 621 passed, 75 warnings; exit 0 |
| full | `PYENV_VERSION=slo-harness make test` | 5 failed, 8140 passed, 19 deselected, 600 warnings; make exit 2 |
| black | `PYENV_VERSION=slo-harness poetry run black src/tui/app.py tests/tui/test_herdr_viewer_replacement.py tests/tui/test_herdr_prompt_registration.py` | exit 0 |
| mypy | `PYENV_VERSION=slo-harness poetry run mypy` on those three files | 9 errors in 6 imported files; zero diagnostics on those three files; exit 1, not green |
| diff | `git diff --check` | silent exit 0 |
| coreutils | `dpkg -V coreutils` | silent exit 0 |

Platform coverage uses actual `launch_async` and retained `to_thread` joining with `VisualizerLauncher.launch` replaced by a thread-barrier fake. No real windows. It proves replacement and concurrent public unmount wait for the committed thread and suppress its notice. It is not OS spawn/Herdr wire acceptance. Mounted registry coverage asserts old session is revoked before finalizer await, still selected while worker retained, and old close occurs only after registry termination. The isolated admission matrix proves each entry refuses the transition flag even after delivery becomes available; it is not a full concurrent delivery-lane matrix. Existing surrounding tests retain candidate failure/queue/lease and shutdown evidence.

## Full-gate failures (unwaived)

All five are in `tests/tui/test_subagent_event_routing.py::TestVisualizerAutoLaunch`:

- test_first_spawn_launches_visualizer_once
- test_launch_passes_parent_session_id
- test_success_writes_open_notice
- test_failure_writes_manual_hint
- test_cleanup_resets_launch_guard

These tests still expect synchronous launch behavior following the preceding 104 attached-route migration. This is a concrete compatibility-test gap, not a passing baseline or waiver. Do not call the family READY. Update them to await registered worker terminal outcomes and assert the captured parent, typed notice and retry guard; do not weaken assertions to skip asynchronous effects. No changes made to that out-of-owned test file here. Full make must be rerun after correction.

## Precise remaining work

1. Repair the five attached-route surrounding tests with asynchronous registry evidence, then rerun full make and required static gates. Imported mypy failures remain unwaived; no fresh baseline comparison claimed.
2. Add the requested actual attached positive: config-backed Faux factory, temp default history and persisted parent context, registered fake Herdr executable capability; drive real sub_agent_spawned → scheduler → launch_async → session gateway → split/rename/run. Assert exact captured-parent argv, one attempt, truthful submitted notice, no platform fallback and terminal registry. Reuse gateway fixtures in `test_herdr_visualizer.py` and T4 fake capability; do not mock launch_async/session gateway for this acceptance.
3. Expand actual in-transition concurrent admission and late successful worker-return coverage (current platform cancellation suppresses completion and existing 104 tests cover late outcomes). Include runtime-refresh barrier after delivery initialization and public unmount cleanup-owner assertions.
4. Finish complete prerequisite reading: shared routing/ownership/testing/coding/cadence/Python/Textual/Faux/workflow skills and C7.9/C7.13–14 were read, as were current caller/registry and D platform contract. Bulk scope-plan/KB output was truncated; complete C7.10–12, accepted-review/sample and Python sibling style closure is not claimed. Provided AGENTS/CLAUDE/docs RESEARCH were consulted; no global KB edits authorized.
5. Detached parser/renderer migration is explicitly deferred. No all-T5 or independent review/completion claim.

**Verdict: INCOMPLETE.** Core replacement lock inversion is corrected with test-first evidence; full gate and remaining acceptance prevent READY.
