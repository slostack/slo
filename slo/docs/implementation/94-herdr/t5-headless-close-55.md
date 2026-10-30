# T5 headless/scheduler continuation 55 — INCOMPLETE

Same unfinished turn 1: started 1/completed 0/historical partial 1/dispatch 55/retries 0. Unlimited user turns and dispatches; no agents dispatched, no completed workflow pass. No TUI or whole-feature readiness claim.

## Changes and causal evidence

Owned edits: `src/cli/headless.py`, `tests/cli/test_headless.py` only, plus these local evidence files. No session service change needed for the reproduced defect. Existing unrelated work preserved.

`HeadlessRunner._invoke` now owns signal installation/restoration and catalog shutdown around the complete preparation/adoption/activation/run/terminal path. The prior implementation restored only when preparation had not adopted a session or when execution reached the watchdog finally. Activation cancellation after adoption bypassed both. The new outer finally attempts catalog shutdown even if signal restoration raises. Watchdog stop remains its existing run-scoped owner; reporting close/final drain and credential clearing remain in public invoke.

Two new tests reproduce activation exception and cancellation, requiring exact signal restoration and catalog shutdown once, reporting close/final drain, original exception identity or existing abort exit 2, and credential clearing. Five further cases cover notifier/status construction, started notification, terminal status and terminal notification exceptions with exact original exception identity and cleanup assertions. These are orchestration-fake tests, NOT actual Faux/registered-Herdr composition.

A pre-existing continuation-54 terminal-kind test annotation introduced one additional mypy error. Changed its parameter to the canonical `StreamEventKind`; no ignore or runtime behavior change.

## Commands and results

CWD `/root/Code/slo-94-herdr-integration/slo`. Every command exported `PYENV_VERSION=slo-harness`; approved Python 3.11.7 fallback, no environment installation. All targeted pytest commands used `bash docs/implementation/94-herdr/t1-dao-check.sh` (adds DAO/projection tests and test/disabled/terminal-safe environment). Each stem below has `.log` and `.exit` files in this directory.

| Stem | Command / arguments | Actual result |
|---|---|---|
| t5-55-signal-red | helper + tests/cli/test_headless.py | 2 failed, 106 passed; exit 1; both new signal restoration assertions failed |
| t5-55-signal-green | helper + tests/cli/test_headless.py tests/agents/slo_agent/herdr/test_session_lifetime.py | 167 passed; exit 0 |
| t5-55-surrounding | helper + tests/cli/test_headless.py tests/scheduling/test_runtime_helpers.py tests/agents/slo_agent/orchestrator/test_bootstrap.py tests/agents/slo_agent/orchestrator/test_spawn_env.py tests/agents/slo_agent/herdr/test_session_lifetime.py | 208 passed; exit 0 |
| t5-55-test | make test, before annotation correction | 7741 passed, 19 deselected, 545 warnings; exit 0 |
| t5-55-smoke | make smoke, before annotation correction | 288 passed; exit 0 |
| t5-55-lint | make lint, before annotation correction | 300 errors/63 files; exit 2 |
| t5-55-final-test | make test, after all source/test changes | 7741 passed, 19 deselected, 545 warnings in 623.03s; exit 0 |
| t5-55-final-smoke | make smoke, same final snapshot | 288 passed, 2 warnings; exit 0 |
| t5-55-final-lint | make lint, same final snapshot | 299 errors/63 files; exit 2, unwaived |
| t5-55-black | poetry run black --check src/cli/headless.py tests/cli/test_headless.py | exit 0 |
| t5-55-diff | git diff --check | silent, exit 0 |
| t5-55-coreutils | dpkg -V coreutils after suites | silent, exit 0 |

`t5-55-lint-comparison.log` compares exact diagnostic multisets after removing only line/column positions against `t5-usage-integration-53-lint-final.log`: ADDED [], REMOVED []. Baseline is not green. Final gates were run after the annotation correction; only documentation/evidence changed afterward.

## Remaining finite acceptance map

This is INCOMPLETE, not finite-family READY:

- Actual config-backed Faux plus registered temp-owned fake Herdr HeadlessRunner composition remains unproved here: no native restore advertisement, disabled parity/spawn-zero, original JSONL/result and credential safety.
- Actual retained child-resource cancellation during activation/close/final drain, held-owner pending evidence and repeated cancellation remain unproved at the runner boundary.
- Cleanup fault matrix is incomplete. Current nested finally blocks can still replace an original exception/result if cleanup itself raises. Watchdog stop failure, catalog shutdown failure, reporting close/final-drain errors and cancellation combinations need explicit policy-preserving tests/fixes; the new signal owner does not resolve these.
- Scheduler actual fresh/resume filtering from 54 reran successfully in the surrounding and full suites, but this continuation did not independently complete the canonical-prefix/preserve-all-unrelated environment audit or every child launch/relaunch exclusion proof.
- Full instruction/specification read closure remains incomplete. Routing/scope/checkpoints and KB were consulted; some large combined skill/context reads truncated. Canonical C path is `herdr/94.b.2-session-publication-and-native-restore.md` (the request's C is its chapter label, not filename). Headless/scheduler/lifetime references inspected, but all exact T5 samples, optional-error-safety accepted reviews and full on-disk context were not completely consumed. No complete-read claim.
- Usage53 stale-snapshot qualification, later TUI family, T6 and independent review remain separate and unresolved.

No arbitrary workflow/unit limit is asserted. This receipt records the implemented narrow correction and honest remaining acceptance, not authorization to waive it. No commits, pushes, PRs, reset/clean/stash, global/live/specification/other-worktree changes, real providers, Herdr or terminal windows.
