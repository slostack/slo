# T5 continuation 71 — READY: finite shutdown-hang repair only

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 71, retries 0; user turn and dispatch budgets unlimited. No agents.
This is NOT mount initialization completion or whole-T5 acceptance.

## Causal diagnosis

Continuation 70 completed normally; its commands timed out, not the agent.
Read its receipt and actual green1/app-surround/surround-isolation logs. The latter
stops entering `test_retired_owner_final_drain_is_joined`; app-surround stops after
65 dots (62 foundations and three diff cases).

1. Isolated retired-owner case: diagnostic at 3 seconds shows selected=True in
   app `_finish_shutdown_owner`, selected session's completed close result retained,
   and session `_finish_herdr_cleanup_once` at service.py:2532 (`await Future()`).
   Retired drain had already finished. The test's class-wide PropertyMock made
   **every NullHerdrReporter**, including the successor, retain resources while
   the predecessor barrier was held. Successor cached retained final evidence
   before that barrier released. This is intentional fail-closed waiting, NOT a
   submission-lock/mount-task cycle. Fix: identity-scoped property, plus explicit
   assertion that the successor has no retained resources. Existing old-owner,
   repeated cancellation and exact close/drain call assertions remain.
2. Presentation fixtures: isolated title test reaches app.py:988 (`await Future()`)
   after `finish_retired_reporting_cleanup` returns an unconfigured AsyncMock.
   Whole-TUI run found the same defect in replay; its isolated diagnostic prints
   `selected=True outcome=<AsyncMock ...finish_retired_reporting_cleanup()>`.
   Fix: presentation-only mock constructors return typed safe/drained evidence.
   Updated test_app, replay and workflow-receive fixtures; no production type
   bypass, special-case mock handling or weakened retention assertion.

**No production code changed in 71.** App 69 independent final tasks and 70 retained
mount initialization remain exactly as received. No runtime timeout increased.

## Persistent failure proof retained separately

New mounted `test_persistent_real_lease_keeps_app_shutdown_pending` uses a real
HerdrReporter and acquired temporary sequence lease, under registered fake capability.
It fails both actual lease close calls, commits replacement, proves successor
suppression, exact retired identity/lease identity, contender exclusion, zero CLI
wire commands, and pending shutdown through three public cancellations.
Only fixture cleanup releases its actual lease, then cancels the private session
pending sentinel. Textual's repeated unmount truthfully propagates that cancellation;
the test expects it, never substitutes successful production cleanup. Existing
session child/lease/persistent tests and independent two-owner barrier test pass.
This is real lease-retention proof, not mounted live-child or full F2 acceptance.

## Commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. All pytest commands use:

```bash
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <arguments>
```

Helper supplies isolated fallback environment and 62 foundation tests. Default
suite strips HERDR variables, disables activation, guards registered executable
identity/containment and real terminal launch. No providers/windows/live Herdr.
Each prefix below is under this directory; `.log` is full output and `.exit` is
actual command status except the explicitly noted outer tool timeout.

| Prefix | Exact arguments | Result |
|---|---|---|
| t5-71-diagnostic | `tests/tui/test_herdr_replacement.py::test_retired_owner_final_drain_is_joined -p docs.implementation.94-herdr.hang71_probe -o faulthandler_timeout=8 -o faulthandler_exit_on_timeout=true -s` | exit 1, bounded task-chain + fatal timeout receipt |
| t5-71-focus | `tests/tui/test_herdr_replacement.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_initialization.py -o faulthandler_timeout=15 -o faulthandler_exit_on_timeout=true` | exit 0, 100 passed |
| t5-71-app-diagnostic | `tests/tui/test_app.py tests/tui/authentication -vv -o faulthandler_timeout=15 -o faulthandler_exit_on_timeout=true` | exit 1, localized title fixture |
| t5-71-mock-diagnostic | `tests/tui/test_app.py::TestSloTUIActiveModelState::test_title_uses_session_active_model_and_reasoning_state -p docs.implementation.94-herdr.hang71_probe -s -o faulthandler_timeout=8 -o faulthandler_exit_on_timeout=true` | exit 1; chain at app:988; diagnostic's extra private-field lookup raised on mock (subsequently corrected) |
| t5-71-app-green | same as app-diagnostic | exit 2, test-edit indentation error; corrected, not production RED |
| t5-71-app-green2 | same as app-diagnostic | outer 180s command timeout at 96%, no exit receipt; progressing, not same hang; split partitions below |
| t5-71-app-final | `tests/tui/test_app.py -o faulthandler_timeout=15 -o faulthandler_exit_on_timeout=true` | exit 0, 234 passed, 163.99s |
| t5-71-auth | `tests/tui/authentication -o faulthandler_timeout=15 -o faulthandler_exit_on_timeout=true` | exit 0, 114 passed/1 deselected, 16.69s |
| t5-71-persistent | `tests/tui/test_herdr_app_shutdown.py::test_persistent_real_lease_keeps_app_shutdown_pending -o faulthandler_timeout=12 -o faulthandler_exit_on_timeout=true` | exit 1, 1 failed/62 passed; fixture cleanup cancellation propagated from Textual |
| t5-71-persistent-green | `tests/tui/test_herdr_app_shutdown.py -o faulthandler_timeout=15 -o faulthandler_exit_on_timeout=true` | exit 0, 72 passed |
| t5-71-herdr-final | `tests/tui/test_herdr* tests/agents/slo_agent/herdr -o faulthandler_timeout=20 -o faulthandler_exit_on_timeout=true` | exit 0, 1364 passed, 126.05s |
| t5-71-tui-all | `tests/tui -vv -o faulthandler_timeout=20 -o faulthandler_exit_on_timeout=true` | exit 1, localized replay mock |
| t5-71-replay-diagnostic | `tests/tui/test_replay_resume.py::TestReplayThinkingParity::test_hydration_mounts_a_sealed_thinking_block_immediately_before_the_answer -p docs.implementation.94-herdr.hang71_probe -s -o faulthandler_timeout=8 -o faulthandler_exit_on_timeout=true` | exit 1, actual untyped outcome captured |
| t5-71-replay-green | `tests/tui/test_replay_resume.py tests/tui/test_workflow_receive_path.py -o faulthandler_timeout=20 -o faulthandler_exit_on_timeout=true` | exit 0, 97 passed |
| t5-71-tui-final | `tests/tui -o faulthandler_timeout=20 -o faulthandler_exit_on_timeout=true` | exit 0, 1350 passed/1 deselected, 273.47s |

No full repository suite run. Whole TUI and whole Herdr partition are green;
counts overlap foundation cases and must not be summed as unique tests.

Other commands:
- `PYENV_VERSION=slo-harness poetry run black --check src/tui/app.py tests/tui/test_app.py tests/tui/test_herdr* tests/tui/test_replay_resume.py tests/tui/test_workflow_receive_path.py`: t5-71-black, exit 0, eight unchanged files.
- `PYENV_VERSION=slo-harness make lint`: t5-71-lint, exit 2: **299 errors/63 files**, unwaived. Comparison to t5-usage-integration-53-lint-final.log normalizes line numbers only: ADDED [] / REMOVED [] (t5-71-lint-comparison.log). No ignores added.
- `git diff --check`: t5-71-diff, exit 0, silent.
- `dpkg -V coreutils`: t5-71-coreutils, exit 0, zero bytes.

## Read and scope boundary

Consulted supplied AGENTS/CLAUDE/docs RESEARCH and actual root RESEARCH, frozen
routing/scope plan, actual test helper/Makefile/Python/pytest declarations,
conftest isolation and registered-fake guards, app shutdown/mount/replacement
paths, session close/final-drain paths, existing lifetime/headless retained tests,
shared routing/testing/ownership, coding rules/cadence/declarative, Python gateway,
style/Faux and Textual/workflow guidance, KB Welcome/slo README/gotchas.
Canonical C 7.13 and exact T5 samples (tasks.md 2401–3720), B final ownership and
D platform lifetime read read-only. This does not claim fresh full ingestion of
all canonical chapters or every broad architecture companion. No new mount
implementation undertaken; continuation70's full transactional initializer and
other pending feature rows remain open.

Durable lesson: a class-wide retention descriptor can contaminate a different
owner before its cached final attempt. A resource-free UI mock must explicitly
return typed drained evidence. Neither is grounds to relax fail-closed production
cleanup. Kept here rather than modifying external KB under the no-global-write
scope. No commits/push/PR/reset/clean/stash/spec/global/other-worktree edits.
