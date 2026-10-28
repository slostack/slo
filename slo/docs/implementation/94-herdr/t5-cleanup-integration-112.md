# T5 cleanup integration 112 — INCOMPLETE

Author diagnostic continuation only. Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 112, retries 0; turn/dispatch budgets unlimited. No agents launched. No production or test changes, no fixture weakening, no acceptance claim.

## Diagnosis evidence

Read `t5-audit-fixes-111.md`, the actual 111 surrounding log, current app shutdown/replacement/registry paths and candidate cancellation fixture. The 111 log has progress dots only (through 71% plus ten dots), no node ID, terminal summary or exit receipt. It cannot identify a hanging test. Its 240-second invocation timeout is not itself proof of a deadlock.

Two verbose 90-second localization invocations stopped at different positions:

- `t5-112-locate.log`: last running node `TestSloTUISessionInbox::test_new_session_rejection_when_app_task_is_tracked` after the Herdr modules passed.
- `t5-112-app-locate.log`: last running node `TestThinkingBlockLiveness::test_window_never_evicts_an_unsealed_thinking_block`.

Neither probe produced a pytest terminal summary or `.exit`; both tool invocations timed out. Neither emitted the configured per-test faulthandler dump. These are incomplete probes, not failed assertions or confirmed hanging tests. The subsequent complete app partition passed both nodes. Do not label either as the 111 hanging test.

The complete TUI-Herdr partition takes 84.75s; the complete app partition takes 155.09s. Their sum is 239.84s, before additional workflows/session/headless tests. This provides a concrete aggregate-duration explanation consistent with 111's 240-second timeout. It does not prove that the exact original expanded command has no other hanging fixture.

## Completed bounded partitions

All commands used the approved `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` helper, preserving its disabled Herdr/default terminal guards and DAO/projection additions. Arguments and receipts:

| Arguments | Receipt stem | Result |
|---|---|---|
| `--collect-only tests/tui/test_herdr_*.py tests/tui/test_app.py tests/tui/workflows tests/tui/test_workflow_receive_path.py` | `t5-112-collect` | 622 collected, exit 0 |
| `tests/tui/test_app.py -vv -o faulthandler_timeout=8` | `t5-112-app` | 234 passed, 25 warnings, 155.09s, exit 0 |
| `tests/tui/test_herdr_*.py -vv -o faulthandler_timeout=8` | `t5-112-tui-herdr` | 369 passed, 62 warnings, 84.75s, exit 0 |
| `tests/tui/workflows tests/tui/test_workflow_receive_path.py -vv -o faulthandler_timeout=5` | `t5-112-workflows` | 143 passed, 2 warnings, 6.56s, exit 0 |
| `tests/agents/slo_agent/herdr/test_session_lifetime.py tests/agents/slo_agent/herdr/test_session_visualizer_lifetime.py tests/agents/slo_agent/herdr/test_final_lifetime_closure.py -vv -o faulthandler_timeout=5` | `t5-112-lifetime` | 179 passed, 2 warnings, 10.05s, exit 0 |

Each completed receipt has `.log` and `.exit`. Counts overlap because the helper adds DAO/projection tests; do not add them as unique coverage. `t5-112-app-tail` is an additional passing ThinkingBlockLiveness/Visualizer filtered probe, not a separate acceptance family.

## Causal paths inspected; not altered

- `_finish_app_shutdown` attempts viewer cleanup, independently closes selected reporting/delivery, drains selected and retired reporting owners, then joins retained registry tasks.
- `_finish_shutdown_owner` intentionally waits on an unresolved Future after final retained/failed evidence. Returning success there would erase ownership safety.
- `_commit_replacement_session` contains an ordinary viewer helper error, marks delivery unsafe, then closes the old reporter and adopts under the submission gate. This inspection alone does not prove shared-lease successor exclusion for a real retained viewer child.
- The existing candidate cancellation fixture raises from its synthetic pool drain, but the actual tested module passes in the complete TUI-Herdr partition. No causal justification was found for changing this fixture.

No task-stack/barrier proof of a persistent-fake hang was obtained. No production defect was established and therefore no speculative source fix or artificial RED was made.

## Remaining work and limits

INCOMPLETE: the requested real registered fake Herdr child + real sequence lease + mounted `/new` + registry fault-boundary composition is not added. Enabled successor suppression while old viewer ownership remains retained still needs its requested executable proof. Combined retired predecessor + occupied viewer/inbox four-cutoff family remains unimplemented; no T6/full-64 claim.

The requested exhaustive prerequisite read closure (actual full AGENTS/CLAUDE/docs RESEARCH, frozen plan/routing, canonical C7.9–7.14 and D registry/T5 samples/reviews, all named skills/build rules) was not completed in this continuation. Consult 111's prior limitations; do not infer closure from supplied context. No new architecture decisions or KB edits.

The completed partitions establish passing app/queue, all `test_herdr_*.py`, workflows/receive path and three session-lifetime modules separately. They do not establish a single combined broad gate, all Herdr adapter modules/headless surroundings, or cross-partition ordering freedom. No fresh full suite ran. Lint's historical 295 errors / 60 files remains unwaived; lint and Black were not rerun because no Python source/test changed. Final `git diff --check` and `dpkg -V coreutils` were silent, exit 0 (`t5-112-diff`, `t5-112-coreutils-final`). All existing worktree changes preserved. No commit/push/PR/reset/clean/stash/global/live/spec/other-worktree edits.
