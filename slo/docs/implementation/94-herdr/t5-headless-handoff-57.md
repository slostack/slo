# T5 headless continuation 57 — INCOMPLETE

Same unfinished turn 1: started 1/completed 0/historical partial 1/dispatch 57/retries 0. User turn and dispatch budgets unlimited; no agents dispatched. This is not the requested cohesive-family completion, independent review, or READY.

## Changes and evidence

Only `src/cli/headless.py` and `tests/cli/test_headless_herdr.py` changed in production/test scope during this continuation. Existing partial work preserved. No session-service, scheduler or TUI edits.

Six test-first process-cleanup cases reproduced signal restoration/catalog shutdown exceptions replacing success or the exact original setup exception. Ordinary errors are now isolated independently; catalog shutdown is still attempted after restoration failure, and reporting cleanup remains reached. Three watchdog-stop regressions reproduced terminal status/notification being skipped for completed/failed/aborted runs. Ordinary stop errors now permit those terminal operations and remaining cleanup. These catches do not catch CancelledError. They prove attempted cleanup, NOT successful disposal of an owner whose cleanup throws.

Commands ran in `/root/Code/slo-94-herdr-integration/slo`, with `PYENV_VERSION=slo-harness`; verified `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. No environment installation or mutation. Test command prefix: `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` (includes DAO/projection tests).

| Receipt stem (all under this directory, .log and .exit) | Test arguments / command | Actual result |
|---|---|---|
| t5-57-process-red | tests/cli/test_headless_herdr.py | 6 failed, 72 passed, 4 warnings; exit 1 |
| t5-57-process-green | target + surrounding below | 210 passed, 4 warnings; exit 0 |
| t5-57-watchdog-red | tests/cli/test_headless_herdr.py | 3 failed, 78 passed, 4 warnings; exit 1 |
| t5-57-watchdog-green | target + surrounding below | 213 passed, 4 warnings; exit 0 |
| t5-57-final-surrounding | target + surrounding below, after formatting | 213 passed, 4 warnings; exit 0 |
| t5-57-black | poetry run black src/cli/headless.py tests/cli/test_headless_herdr.py | exit 0 |
| t5-57-black-check | poetry run black --check src/cli/headless.py tests/cli/test_headless_herdr.py | exit 0 |
| t5-57-diff | git diff --check | silent, exit 0 |
| t5-57-coreutils | dpkg -V coreutils, after final suite | silent, exit 0 |

Target + surrounding arguments: `tests/cli/test_headless_herdr.py tests/cli/test_headless.py tests/agents/slo_agent/herdr/test_session_lifetime.py tests/scheduling/test_runtime_helpers.py tests/agents/slo_agent/orchestrator/test_spawn_env.py`.

Reviewed headless diff against HEAD, distinguishing previous changes from this continuation. No fresh full make test/smoke/lint: family not ready. Historical 299 errors/63 files remains unwaived; no new diagnostic-comparison claim.

## Finite whole-family disposition (not an exhaustive completed canonical audit)

| Obligation | Retained proof / current disposition |
|---|---|
| C7.2 adoption-before-reporting, outer finally on preparation failure/activation error/cancellation | Retain 54/55 orchestration tests in test_headless.py; surrounding passes |
| C7.2 real non-injected session/Faux/registered CLI enabled and disabled; no native restore | Retain 56 two actual cases; rerun passing |
| C8 exact normalized whole JSONL parity, terminal error/abort composition and privacy | Still outstanding; final-kind/answer assertions are NOT whole-stream equality |
| C lifetime actual retained child and lease through runner close/final drain, repeated cancellation, persistent pending/strong reachability | Still outstanding at runner boundary. Session lifetime40 proofs retained but do not replace this composition |
| Optional reporting close/final-drain ordinary faults and failing diagnostic sink preserve original result/error | Retain 56 eight orchestration cases; passing |
| Signal/catalog ordinary faults, simultaneous signal+catalog faults, original setup exception | Six new passing orchestration cases; cancellation and retained resources not proved by these |
| Watchdog stop ordinary fault across three terminal kinds, status and notification still attempted | Three new passing orchestration cases |
| Status/notification faults and combined watchdog/catalog/signal/reporting failures, cancellation precedence | Still outstanding. No every-errno expansion is required; meaningful owner combinations need coverage |
| Scheduler actual fresh/resume HERDR stripping | Retain scheduler54 proof unchanged; surrounding rerun passes |
| All unrelated scheduler environment values and sub-agent/detached/relaunch exclusion audit | Still needs complete finite map to existing tests; no new scheduler change warranted by this continuation |
| Required read closure | Partial, detailed below |
| Final full/smoke/lint with exact diagnostic baseline comparison | Outstanding until family ready |

## Reads and next work

Read routing.md, scope-plan.md, current t5-code-test and isolation56; root RESEARCH, KB slo README/gotchas, selected engineering routing/testing/ownership, coding rules/cadence/declarative, Python conventions/service/Faux/declarative/named-args/docstrings, Typer, workflow SKILL and exact code-test-review workflow; Makefile and safe test helper. AGENTS/CLAUDE/docs RESEARCH supplied context consumed, not fresh complete tool-output closure. Combined KB read truncated the beginning of Welcome; no complete fresh Welcome claim. C searched for headless/lifetime obligations with context, not fully reread. Source runner first 280 lines and session final-drain gateway/join owner inspected; full source/tests and canonical middle/sample/B/review reads still outstanding.

Next: complete affected canonical/read closure; exercise actual retained child/lease with deterministic admitted-command barriers through the runner, repeated cancellation and persistent pending owner. Preserve session strong ownership and propagate cancellation only after joining; no catch-and-release workaround. Add exact normalized JSONL comparison and meaningful cleanup/status/notification fault combinations. Run fresh required family/full/static gates, compare diagnostics without waivers. Entire T5 app/inbox/viewer and T6/review remain future work.

No commits/push/PR/reset/clean/stash, global/live/specification/other-worktree edits, real providers, Herdr or terminal windows. No family completion claim.
