# T5 viewer start 93 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 93, retries 0. Unlimited turn/dispatch budgets; no agents dispatched. No canonical/global/live/other-worktree changes or git mutation commands.

## Concrete viewer unit implemented

`src/tui/visualizer_launcher.py::_launch_platform_joined` now retains one local task wrapping the existing synchronous platform launcher. `HerdrTaskJoin.wait` shields and joins that work through repeated caller cancellation, retrieves terminal errors, and only then re-raises cancellation. Normal bool results map to opened/failed; exceptions map to fixed failed. Existing synchronous launch behavior is unchanged. This helper is not yet wired into a destination selector or either app caller.

New `tests/tui/test_herdr_visualizer.py` covers true/false, exception privacy, and a thread barrier with repeated cancellation and terminal-work assertion. It patches the launch boundary: no executable, provider, Herdr process or terminal window is opened. Existing suite-wide default-spawn guard remains intact. No stronger async-default guard is claimed yet.

## Executed evidence

CWD is the feature checkout. Commands use `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` (reviewed safe fallback, includes 62 DAO/projection cases).

- `tests/tui/test_herdr_visualizer.py`: `t5-93-platform-red.log/.exit`, exit 1, 4 failed/62 passed. All four failures are missing `_launch_platform_joined`, before implementation.
- Above plus `tests/tui/test_visualizer_launcher.py`: `t5-93-platform-green.log/.exit`, exit 0, 86 passed.
- Above plus `tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_app.py tests/tui/test_herdr_session_lifecycle.py`: `t5-93-platform-surround.log/.exit`, exit 0, 353 passed, 31 warnings, 172.84s.
- `PYENV_VERSION=slo-harness poetry run black --check src/tui/visualizer_launcher.py tests/tui/test_herdr_visualizer.py`: `t5-93-black.log/.exit`, exit 0.
- `git diff --check`: `t5-93-diff.log/.exit`, silent exit 0.
- `dpkg -V coreutils`: `t5-93-coreutils.log/.exit`, silent exit 0.

Full make/test/smoke/lint not rerun: no cohesive viewer integration family is finished. Historical 298 errors/63 files remains unwaived. No new ignore added.

## Inbox/registration handoff kept separate

Read both actual `t5-registration-handoff-92.md` and `t5-inbox-handoff-92.md`. Their 351/412 surrounding receipts remain historical evidence, not this continuation's execution. Their explicit 13-disposition/four-T3-F1 map and registration matrix are preserved without downgrading viewer debt into an inbox behavior defect. However, actual-test reinspection and the requested complete canonical/read reconciliation were NOT completed here, so no new bounded-family READY verdict is issued.

Integration debt is specifically occupied-retired-owner plus tracked-viewer cleanup at the named cutoffs. Retest those combined owners AFTER wiring. Disabled/no-viewer cleanup is not evidence for the missing registry.

## Read closure (not complete)

Read full canonical D (711 lines), actual frozen routing/scope plan, both handoffs, root RESEARCH, launcher, task-join owner and root fixture guards. Read shared engineering routing/testing/ownership, coding rules/cadence/declarative, Python root/declarative/Faux/named-arguments/docstrings and workflow SKILL. One combined skill read truncated; its missing first 420 lines were then read from the full captured output. KB Welcome/index/gotchas combined read truncated at the beginning; no full fresh closure claim. Supplied AGENTS/CLAUDE/docs RESEARCH context is not a fresh actual-file reread. C inbox/session/viewer sections, exact tasks 2401–3720, accepted reviews, actual inbox/registration tests, Textual skill and build-rule closure still require explicit reading.

## Next finite units

1. Finish actual read/test reconciliation and issue bounded inbox/registration technical verdict only for proved rows.
2. Session `open_workflow_visualizer`: canonical parent, enabled/default history, same workdir/plain PATH and persisted metadata plus attached event/context eligibility; use existing T4 reader/adapter, no second parser.
3. Async selector with auto gate and distinct platform/herdr/unavailable destinations; no fallback for enabled failure or skipped Herdr eligibility. Strengthen default-terminal safety for async execution.
4. Shared app registry, identity-safe done cleanup, captured-session and closing/transition refusal, cancellation drain before replacement/unmount and no late notices.
5. Cohesive detached typed-effect/parser/callable migration, then both callers and occupied retired/viewer cutoff composition.

Whole T5, T6 and independent review remain pending. This checkpoint provides concrete tested launcher functionality, NOT completed destination or scheduling foundations.
