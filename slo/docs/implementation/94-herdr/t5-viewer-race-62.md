# T5 viewer race owner — continuation 62 — INCOMPLETE

Same unfinished workflow turn 1: started 1/completed 0/historical partial 1/dispatch 62/retries 0. Effective turn and dispatch budgets unlimited. No agents dispatched. This is bounded author evidence, not independent approval or full T5 readiness.

## Scope and actual change

Only `tests/agents/slo_agent/herdr/test_visualizer_acceptance.py` changed, plus this report and `t5-62-*` receipts. No production, headless, shared status, specification, KB, other-worktree or global edits. No commits/push/PR/reset/clean/stash, real providers, real Herdr or terminal windows. Existing partial work preserved.

The first parametrized acceptance test now completes A's real durable reservation before beginning the viewer's timed transport operation. A test-local wrapper holds the prepared report immediately outside the real transport `invoke`. Once the actual fake executable records split, the test releases A into the real one-second transport scope and held lock. An event at `_invoke_locked` signals queue entry, immediately delegating to the original implementation without an intervening await. Assertions still verify actual `_waiters`, both tasks pending, no admitted report ticket, durable sequence, and exactly 1.0-second configured deadline. B supersedes A before viewer release/close/cancel/timeout. All original executable command-order, unused sequence, retained attempt, duplicate refusal and newer B assertions remain.

A controlled thread reservation barrier is exercised on every repetition. It uses the real sequence store after release, not a fake counter. No clock changes, deadline changes, positive sleep masks or assertion relaxation were introduced. Existing child file-barrier polling remains unchanged. The wrapper delegates every command to the real transport; production admission, subprocess, timeout, cleanup and accounting paths remain intact.

## RED and causal boundary

`t5-62-red.log`: the original ordering with a deterministic blocked `reserve` reproduced the exact 0.5-second `_waiters` polling TimeoutError: **1 failed, 62 passed**, exit 1. Diagnostic state at failure:

```
reservation_pending=True; old_done=False; launch_done=False; lock_held=True
```

Thus a report that is still awaiting its off-thread reservation has not entered the transport lock queue. Polling lock internals does not distinguish that setup delay from a dead/failed report. The test's 0.5-second expectation incorrectly includes disk/executor progress while the viewer's independently running one-second deadline is already being consumed. The injected barrier is released in finally and all owned tasks/processes are joined. No production failure was reproduced.

This establishes a deterministic sufficient cause for the observed signature, **not retrospective proof of the exact host scheduling state in t5-60-full.log**. That historical trace has no reservation/task-state observations. It cannot establish that the production one-second deadline expired, that the report was done, or that private polling itself lost an existing waiter. The RED here specifically proves a pending reservation with both tasks alive, before viewer expiry.

## Why INCOMPLETE rather than READY

1. The new ordering proves durable A, actual viewer-held lock, true queued transport admission, then B and zero stale executable entry. However, it moves A's durable reservation before viewer launch. B's mandatory G2 text explicitly describes viewer entry followed by publication/reservation of A while the viewer holds the lock. This narrower scheduling proof is not silently promoted to exact compliance with that ordering. A further refinement should preserve viewer-first reservation ownership while deterministically separating unrelated setup latency, or explicitly justify this test factoring alongside unchanged real viewer-first G2 coverage.
2. Full `make test` was intentionally not run in this lane: the user assigns the final integrated full gate to the parent after lanes finish. The historical full failure is not superseded by an isolated/package pass. Parent integration must run the fresh full gate on final bytes.
3. Requested read closure is partial, not complete. Do not treat inherited routing declarations as newly executed reads. Remaining full prerequisite reading is listed below.

No production change is justified. No deadline increase is proposed.

## Executed evidence

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved `PYENV_VERSION=slo-harness`: `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. `make test-env`: fallback. No installation or venv creation.

P = `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`; it adds DAO/projection tests. All stems below are under this report's directory; `.exit` retains actual exit status, `.log` full output.

| Receipt stem | Command / actual result |
|---|---|
| `t5-62-red` | P `tests/agents/slo_agent/herdr/test_visualizer_acceptance.py::test_operational_viewer_supersedes_queued_report[False-release]`; 1 failed, 62 passed, 2 warnings; exit 1 |
| `t5-62-green` | P `tests/agents/slo_agent/herdr/test_visualizer_acceptance.py`; 81 passed, 2 warnings; exit 0 |
| `t5-62-format` | `PYENV_VERSION=slo-harness poetry run black tests/agents/slo_agent/herdr/test_visualizer_acceptance.py`; exit 0 |
| `t5-62-repeat-1` through `t5-62-repeat-20` | Twenty actually executed post-format P runs of the complete viewer acceptance file; each 81 passed, 2 warnings, exit 0. Eight controlled-reservation supersession variants per run, 160 total, plus unchanged adjacent tests. No pytest-repeat dependency. |
| `t5-62-package` | P `tests/agents/slo_agent/herdr tests/agents/slo_agent/orchestrator/test_context_reader.py tests/tui/test_workflow_visualizer_loader.py`; 1344 passed, 125 warnings; exit 0 |
| `t5-62-lint` | `PYENV_VERSION=slo-harness make lint`; 299 errors/63 files; make exit 2. Baseline remains unwaived. |
| `t5-62-lint-comparison.log` | Diagnostic multiset versus `t5-55-final-lint.log`, line numbers normalized only: zero added, zero removed. |
| `t5-62-black` | `PYENV_VERSION=slo-harness poetry run black --check tests/agents/slo_agent/herdr/test_visualizer_acceptance.py`; exit 0 |
| `t5-62-diff` | `git diff --check`; exit 0 (target file is pre-existing untracked feature work, so this is not a target-file content diff). |
| `t5-62-coreutils` | `dpkg -V coreutils` after final package/static checks; zero-byte stdout/stderr, exit 0. Also silent immediately after RED/initial green. |

No full-suite, live compatibility or independent review claim. The 20 repetitions are not 20 workflow turns.

## Reads and safety

Read actual final60/gates61 reports, historical failure trace, complete viewer acceptance test, real transport/visualizer, reporter reservation/admission/send paths, sequence store opening, fixture registration/containment code, conftest isolation opening and fixture locations, Makefile and safe helper; root RESEARCH and supplied AGENTS/CLAUDE/docs RESEARCH. Read frozen routing in full. Combined scope-plan and other large outputs were truncated and are not claimed fully consumed.

Loaded committed engineering routing/testing/ownership, coding rules/cadence/declarative, Python root/declarative/named-arguments/docstrings, exact workflow SKILL/code-test-review; Faux recipe opening only. Read KB Welcome/gotchas. Actual full-file AGENTS/CLAUDE/docs RESEARCH rereads, full Faux/build-rule and KB companion closure remain outstanding.

Read canonical read-only B shared timeout/admission/G2 excerpts, D eligibility/lifetime/one-shot/test excerpts, exact T4/T5 task allocation, and accepted review evidence visible in bounded output. One combined canonical read was truncated; missing opening portions and full relevant task attachments are not claimed read. Specifications untouched.

Fixture-owned regular executable is revalidated through the existing capability guard before append/barrier writes and every actual spawn. HERDR stripping/disabled environment and real-terminal guard remain enabled. No system symlinks or system writes. Thread/event barriers are test-local and released during cleanup.

## Handoff

Retain the causal RED and finite repeat/package receipts. Resolve the viewer-first G2 ordering qualification and remaining reads before READY race-owner status; then parent runs the integrated full gate. Do not call an isolated pass a causal repair or use this report to advance dependent TUI work automatically.
