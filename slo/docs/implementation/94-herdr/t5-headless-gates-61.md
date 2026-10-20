# T5 headless/scheduler continuation 61 — INCOMPLETE

Same unfinished workflow turn 1: started 1/completed 0/historical partial 1/dispatch 61/retries 0. Effective turn and dispatch budgets unlimited; no agents dispatched. Dispatch 61 is not turn 61. No TUI work or whole-feature approval.

## Verified repair

`tests/cli/test_headless_retained.py` now uses a generic, assertion-backed `require_retained` weak-reference dereference. Each expression releases its temporary strong reference; no runner/session/reporter local is retained across the GC/cancellation proof. Nullable close/drain tasks are explicitly asserted, the temporary drain-task local is deleted before the persistent cancellation/GC branch, and cleanup narrows its real reporter type before private transport access. No Any, casts, ignores, production changes or assertion weakening.

Actual RED: fresh `make lint` reproduced all 12 retained-test diagnostics (311/64 total). After repair, actual lint is 299 errors/63 files. Diagnostic multiset comparison against `t5-55-final-lint.log`, normalizing line numbers only: **zero added, zero removed**. Baseline remains unwaived, not green.

## Viewer investigation — unresolved

Read the exact `t5-60-full.log` failure (lines 472–593) and all of `test_visualizer_acceptance.py`. The failure is at lines 46–48, polling `_command_lock._waiters` under a 0.5-second test timeout after starting `_send_report_operation`. The trace does not establish why the waiter was absent. Inspected transport `invoke`, lock/admission/spawn and cleanup ownership: the production configured deadline wraps lock wait as well as execution. No deterministic causal reproduction has yet been executed. A prior isolated pass is not a repair. No viewer/service edits, deadline increases or weakened assertions.

Next investigation must distinguish durable reservation/test admission latency from the real one-second transport deadline, with deterministic barriers and retained actual protocol deadline coverage. Do not infer a production bug merely from this timeout.

## Finite family disposition

| Family | Evidence / disposition |
|---|---|
| Headless adoption/activation and three terminal kinds | Existing test_headless.py; surrounding rerun passes |
| Setup/activation faults, signal/catalog restoration | Existing 55–57 coverage; surrounding rerun passes |
| Optional cleanup, watchdog, original status/notification exception | Existing test_headless_herdr.py including continuation60 combined faults; surrounding passes |
| Retained real child/lease, weakref GC, repeated cancellation, final drain success/persistent quarantine | Two retained59 cases preserved with truthful typing; focused and surrounding pass |
| Exact complete enabled/disabled JSONL, native-restore exclusion | Continuation60 parity tests unchanged; surrounding passes |
| Fleet drain/status withholding and notifier/inbox behavior | Existing test_headless.py coverage; surrounding passes |
| Scheduler fresh/resume HERDR environment filtering | Existing test_runtime_helpers.py; surrounding passes |
| Sub-agent/detached/relaunch exclusion map | Shared spawn-env tests rerun; all-three-call-path source/test audit still outstanding; no claim of closure |
| Viewer queued-report acceptance | Historical full failure unresolved; no causal RED/repair yet |
| Required read closure | Partial, detailed below; outstanding |
| Broad task and final full/smoke gates | Not rerun in continuation61; prior receipts remain historical |
| Static gate | Exactly baseline 299/63; zero new diagnostics; baseline unwaived |

## Actual commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified approved `PYENV_VERSION=slo-harness` resolves `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. `make test-env`: fallback. No venv/package changes.

All receipt stems below are under this directory, with `.log` and `.exit`:

- `t5-61-typing-red`: `PYENV_VERSION=slo-harness make lint`, exit 2, 311 errors/64 files, all 12 requested errors reproduced.
- `t5-61-retained-green`: `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/cli/test_headless_retained.py`, exit 0, 64 passed/4 warnings.
- `t5-61-typing-green`: `PYENV_VERSION=slo-harness make lint`, exit 2, 299 errors/63 files. Filename denotes the bounded typing repair, NOT green global lint. `t5-61-lint-comparison.log` records exact zero-added/zero-removed comparison.
- `t5-61-surrounding`: same safe helper with `tests/cli/test_headless_parity.py tests/cli/test_headless_herdr.py tests/cli/test_headless_retained.py tests/cli/test_headless.py tests/agents/slo_agent/herdr/test_session_lifetime.py tests/scheduling/test_runtime_helpers.py tests/agents/slo_agent/orchestrator/test_spawn_env.py`, exit 0, 220 passed/8 warnings.
- `t5-61-black`: `PYENV_VERSION=slo-harness poetry run black --check tests/cli/test_headless_retained.py`, exit 0.
- `t5-61-diff`: `git diff --check`, exit 0.
- `t5-61-coreutils`: `dpkg -V coreutils`, silent, exit 0. Also silent immediately after focused tests.

## Read closure — partial, not complete

Actual reads in this continuation: final60 receipt, frozen routing and scope-plan in full; t5-code-test lines 1–100; complete retained test and viewer acceptance test; exact full-failure trace; transport service lines 300–599; safe helper; available project instructions/AGENTS/CLAUDE/docs RESEARCH supplied in context. Selected skills actually loaded: engineering routing/testing/ownership, coding rules/cadence/declarative, Python root/named arguments/docstrings/declarative, exact code-test-review workflow. KB Welcome and slo/gotchas fully read.

Still required before READY: actual file reads of AGENTS/CLAUDE/root and docs RESEARCH, remaining workflow SKILL/Faux/build companions and frozen-routing KB companions, canonical read-only C affected sections and complete exact T5 sample attachments, B/D shared-lock contracts and accepted review closure. Earlier receipts are not substituted for these reads. Full launch-path exclusion audit and final gates also remain outstanding.

All existing work preserved. No agents, commits, push/PR, reset/clean/stash, globals/live systems, specifications or other-worktree edits. No real provider/Herdr/windows/system symlinks. This checkpoint closes only the 12 typing diagnostics, not HEADLESS/SCHEDULER readiness. Parent must not treat it as permission to begin dependent TUI integration.
