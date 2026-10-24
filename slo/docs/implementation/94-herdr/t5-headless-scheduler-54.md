# T5 headless/scheduler 54 — INCOMPLETE

Same unfinished turn 1: started 1/completed 0/historical partial 1/dispatch 54/retries 0. User turn and dispatch budgets unlimited. No agents dispatched; no workflow pass completed.

## Changes in this continuation

- `src/scheduling/runtime/subprocess_runner.py`: actual subprocess spawn receives a fresh inherited environment copy excluding keys whose uppercase spelling starts `HERDR`. This follows the user's explicit all-HERDR-prefix contract (broader than C's historical `HERDR_` spelling). No orchestrator allowlist changes; all unrelated values retained.
- `tests/scheduling/test_runtime_helpers.py`: real temp-owned regular executable for fresh and resume paths reports only synthetic-key presence booleans. Tests include lowercase/future/no-underscore prefixes, unrelated provider/settings values, and exact unchanged parent environment. No system symlinks.
- `src/cli/headless.py`: adopted session starts reporting with default interactive=False; outer invoke finally calls close followed by final local drain, with credential clearing in a further finally.
- `tests/cli/test_headless.py`: three terminal-kind ordering tests and existing blocked-session fake updated with lifecycle methods.
- No session service change, TUI changes, agents, git lifecycle, installation, global/live/specification or other-worktree changes.

## Actual RED/GREEN evidence

CWD `/root/Code/slo-94-herdr-integration/slo`; approved interpreter `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. All pytest commands used `bash docs/implementation/94-herdr/t1-dao-check.sh` (includes DAO/projection and safe fallback env). Logs and exits are adjacent.

| Receipt stem | Arguments after helper | Result |
|---|---|---|
| t5-54-scheduler-red | tests/scheduling/test_runtime_helpers.py | 2 failed, 70 passed; exit 1; inherited HERDR keys reached real child |
| t5-54-scheduler-green | tests/scheduling/test_runtime_helpers.py tests/agents/slo_agent/orchestrator/test_spawn_env.py | 84 passed; exit 0 |
| t5-54-headless-red | tests/cli/test_headless.py | 3 failed, 103 passed; exit 1; lifecycle calls absent |
| t5-54-headless-green | tests/cli/test_headless.py tests/agents/slo_agent/herdr/test_session_lifetime.py | 1 failed, 164 passed; exit 1; old blocked-session double lacked new lifecycle interface |
| t5-54-headless-green-corrected | same | 165 passed; exit 0 |

Black formatted the four changed Python files (only scheduler test changed formatting). `git diff --check` and `dpkg -V coreutils` were silent, exit 0, after tests. No final post-format regression, full make test/smoke/lint or diagnostic-baseline comparison executed. Prior 7729 full pass remains historical; usage53 stale-snapshot qualification is NOT resolved.

## Precise remaining work / known risk

This is not finite-family READY. Current headless wiring is only a first increment:

1. Activation currently sits inside preparation cancellation handling after `_session` adoption. A cancellation/error there can bypass existing signal restoration because that preparation finally restores only when `_session is None`. Move/extend actual cleanup ownership test-first; verify signal handler, model catalog, status and watchdog cleanup across all adopted-session setup failures, not only normal stream finally.
2. Prove activation faults and credential errors preserve original result/error/JSONL. Session methods contain optional faults, but current runner orchestration tests do not prove that composition. Do not claim exception preservation from nested finally alone.
3. Add actual config-backed factory/Faux and registered fake-Herdr headless composition, disabled parity, no native restore advertisement, preparation failure, status/notification failure, cancellation during activation/close/final drain, and retained-resources pending-owner evidence.
4. Re-run scheduler post-format, headless/bootstrap/spawn-env/scheduler/session regressions and unchanged subagent/detached/relaunch exclusions.
5. Fresh unchanged-snapshot make test/smoke/lint, changed-file Black check, diff/coreutils and exact 299/63 baseline diagnostic multiset attribution remain required.
6. Required read closure remains partial: frozen routing/scope and handoffs40/47/53, actual headless adoption/outer-finally, scheduler spawn and session lifecycle methods were inspected. Shared engineering/coding/Python service/declarative/Faux and exact workflow skills read (large skill output prefix recovered). KB Welcome/slo README/gotchas consulted. Canonical headless/scheduler/lifetime references and tasks2401–2720 inspected; remaining exact T5 attachments, accepted review, full safety/build companions and actual full AGENTS/CLAUDE/docs RESEARCH on-disk read remain to finish; supplied project context was available. No complete-read claim.

App replacement/inbox/viewer callers, T6 and independent Review remain future work, not covered or waived by these tests. Preserve all existing partial work and historical receipts.
