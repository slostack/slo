# T5 headless/scheduler continuation 60 — INCOMPLETE

Same unfinished workflow turn 1: started 1/completed 0/historical partial 1/dispatch 60/retries 0. Effective turns and dispatch budgets unlimited; no agents dispatched. This is author verification, not independent review or full T5 approval. No TUI work started.

## Changes

- New `tests/cli/test_headless_parity.py`: two actual config-backed HeadlessRunner/session/Faux runs, enabled versus disabled against the fixture-registered fake executable. Every stdout line parses as JSON; entire ordered event objects compare equal. **No normalization at all was necessary** (no fields or lines discarded). Same question and answer, real session construction/activation/close; only model factory and synthetic credential resolution replaced. Disabled capture remains byte-identical; enabled capture changes. Neither session is injected/interactive or carries a restore capture; no restore argv or synthetic secret appears in captured output.
- Added four `test_terminal_error_survives_combined_cleanup_faults` cases to `tests/cli/test_headless_herdr.py`: status versus notification exception, ordinary versus CancelledError, each combined with watchdog stop, signal restoration, catalog shutdown, reporting close and final-drain ordinary faults. Exact original exception identity survives; all later cleanup owners are attempted; private fault text absent; original completed JSONL terminal remains unchanged.
- No production change. Both initial coverage passes were green; **no production RED claimed**. The actual existing contract (also asserted by test_headless.py) propagates terminal status/notification defects. Optional reporting cleanup must not replace that original error. These tests do not invent successful status persistence after a failed owner or prove disposal merely from an attempted cleanup.

## Finite headless/scheduler evidence map

| Obligation | Evidence / remaining qualification |
|---|---|
| Adopt before activation, default noninteractive start, all three terminal kinds | test_headless.py::test_reporting_lifetime_surrounds_headless_run |
| Activation ordinary error/cancellation preserves signal/catalog/reporting ownership | test_activation_exit_restores_signal_owner; retained 54/55 tests |
| Setup/status/notification original exception | test_adopted_setup_and_terminal_fault_restore_signal; new combined-fault cases |
| Optional reporting ordinary faults with throwing diagnostic sink | test_reporting_cleanup_preserves_original_outcome (8 cases) |
| Signal/catalog individually and together, original result/error | test_process_cleanup_preserves_original_outcome (6 cases) |
| Watchdog stop preserves terminal status/notification attempts | test_watchdog_stop_fault_preserves_terminal_status (3 kinds) |
| Exact enabled/disabled complete stdout JSONL | new test_enabled_disabled_whole_jsonl_parity; no normalization or filtering |
| No native restore for actual headless session | parity and test_config_backed_faux_headless_never_advertises_restore |
| Real retained child/lease, GC reachability, repeated cancellation, successful/persistent final drain | retained-59 test_headless_retained.py, rerun in 220/1463 partitions; its static errors remain outstanding |
| Existing fleet safety and status withholding | TestHeadlessRunnerDrainGate: drained/unresolved/no-store, recycled/unreadable PID refusal; no real fleet processes signalled |
| Existing notifier success/failure/no flag and real inbox failure | TestHeadlessRunnerWorkflowNotifications, TestHeadlessNotifyEndToEnd |
| Scheduler actual fresh/resume child environment | test_scheduler_child_drops_inherited_herdr_environment; surrounding and broad task gate pass; no scheduler edit |
| Sub-agent/detached/relaunch exclusion | Existing shared spawn-env tests pass; explicit all-three-path HERDR exclusion evidence map still not completed here |
| Complete required-read closure | Affected direct reads below completed, but full requested canonical/read closure NOT complete |
| Final full/static acceptance | BLOCKED by full-suite failure and 12 added retained-test typing diagnostics |

This is finite existing-proof mapping, not an unbounded fault Cartesian matrix. TUI lifetime/inbox/viewer and T6 composed/live acceptance remain separate future tasks.

## Actual gates

CWD `/root/Code/slo-94-herdr-integration/slo`; approved `PYENV_VERSION=slo-harness`, interpreter `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. `make test-env` returned fallback. No installation or venv creation. Prefix **P** = `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh` (always adds DAO/projection tests).

All receipt stems below are in this directory, with `.log` and `.exit` unless stated otherwise.

| Stem | Command/result |
|---|---|
| t5-60-parity-initial | P tests/cli/test_headless_parity.py: 63 passed, 4 warnings, exit 0 |
| t5-60-parity-surrounding | P + surrounding list below: 216 passed, 8 warnings, exit 0 |
| t5-60-terminal-initial | P tests/cli/test_headless_herdr.py: 85 passed, 4 warnings, exit 0 |
| t5-60-terminal-surrounding | P + surrounding: 220 passed, 8 warnings, exit 0 |
| t5-60-format | PYENV_VERSION=slo-harness poetry run black tests/cli/test_headless_parity.py tests/cli/test_headless_herdr.py: exit 0 |
| t5-60-full | PYENV_VERSION=slo-harness make test: **1 failed, 7766 passed, 19 deselected, 550 warnings**, make exit 2 |
| t5-60-smoke | PYENV_VERSION=slo-harness make smoke: 288 passed, 2 warnings, exit 0 |
| t5-60-lint | PYENV_VERSION=slo-harness make lint: **311 errors/64 files**, make exit 2 |
| t5-60-full-failure-isolated | P 'tests/agents/slo_agent/herdr/test_visualizer_acceptance.py::test_operational_viewer_supersedes_queued_report[False-release]': 63 passed, 2 warnings, exit 0; NOT resolution of full failure |
| t5-60-black | PYENV_VERSION=slo-harness poetry run black --check src/cli/headless.py tests/cli/test_headless_herdr.py tests/cli/test_headless_parity.py tests/cli/test_headless_retained.py: exit 0 |
| t5-60-task | P + broad list below: 1463 passed, 131 warnings, exit 0 (post-format) |
| t5-60-coreutils | dpkg -V coreutils after broad suite: silent, exit 0 |
| t5-60-diff | git diff --check: see receipt |

Surrounding arguments:
```
tests/cli/test_headless_parity.py tests/cli/test_headless_herdr.py tests/cli/test_headless_retained.py tests/cli/test_headless.py tests/agents/slo_agent/herdr/test_session_lifetime.py tests/scheduling/test_runtime_helpers.py tests/agents/slo_agent/orchestrator/test_spawn_env.py
```
Broad task arguments:
```
tests/cli/test_headless_parity.py tests/cli/test_headless_herdr.py tests/cli/test_headless_retained.py tests/cli/test_headless.py tests/agents/slo_agent/herdr tests/agents/slo_agent/orchestrator/test_bootstrap.py tests/agents/slo_agent/orchestrator/test_spawn_env.py tests/cli/test_headless_request.py tests/scheduling/test_runtime_helpers.py
```

### Exact blockers

Full failure: `test_operational_viewer_supersedes_queued_report[False-release]`, `tests/agents/slo_agent/herdr/test_visualizer_acceptance.py:46–48`: 0.5-second timeout while waiting for `_command_lock._waiters`. Actual TimeoutError trace is retained in full log. Isolated and later broad run pass. No causal explanation or repair established; do not call it fixed or waive it as flaky. That file is outside this request's named write scope.

`t5-60-lint-comparison.log` compares diagnostic multisets against `t5-55-final-lint.log`, normalizing line numbers only. Exactly **12 added, zero removed**; all additions are in `tests/cli/test_headless_retained.py`: nullable weakref dereferences, nullable cleanup task/shield, and protocol/private-transport access (lines 81,95,96,97,107,109 twice,118,128,141,155,156). Existing **299/63 remains unwaived**. No diagnostic in the newly added parity/test changes. Retained test is outside the named write scope; not edited. Repair must preserve weakref-only GC proof rather than retaining local strong references across collection/cancellation. No ignores/casts added to hide errors.

## Reads and limitations

Before new tests, actual tool reads covered AGENTS.md 1–1013, CLAUDE.md, root RESEARCH and docs/RESEARCH 1–633; routing.md/scope-plan.md; current t5-code-test (current and supplied historical receipts); retained59/handoff57; Makefile, safe helper and pyproject; full headless.py (1–945), full test_headless.py (1–1024), test_headless_herdr/retained; scheduler source, shared spawn-env tests; actual Faux, status store, test isolation/conftest. KB Welcome, slo README/gotchas read. Shared engineering routing/testing/ownership; coding rules/cadence/declarative; Python root/service/Faux/declarative/named-args/docstrings; exact workflow SKILL/code-test-review; product Typer skill read. Truncated Python combined read was completed by separately reading Python root and service opening.

Canonical read-only affected sections read: C7.1–7.2, C7.11 and final author additions (1476–1666), final ownership/drain/C7.14/tests/acceptance (1939–2175); exact tasks T5 allocation 195–241 and C23 3248–3371; B7.2–7.4, default-suite isolation and final helper additions 1872–2076; accepted independent-review-turn4.md. No spec writes.

**Not complete full requested read closure:** remaining canonical C middle sections/T5 sample attachments, further frozen-routing KB/build-rule companions and explicit three launch-path exclusion audit were not fully completed. Initial combined routing/KB read truncated and was not treated as proof; separate routing/scope and visible KB portions were consumed. No claim of full prerequisite closure or whole-family readiness.

No agents, commits, pushes, PRs, reset/clean/stash, globals, live systems, specifications or other-worktree edits. No real providers/Herdr/windows or system symlinks. Existing work preserved. Next authorized work needs read closure, the two out-of-scope blocker repairs with proper evidence, explicit launch-path map, and fresh final gates before READY HEADLESS/SCHEDULER. No full-T5 claim.
