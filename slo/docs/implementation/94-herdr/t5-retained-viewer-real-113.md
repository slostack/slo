# T5 actual retained viewer 113 — bounded proof delivered; overall INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 113, retries 0. Turn/dispatch budgets unlimited. No agents launched. No production changes, commits or external operations.

## Delivered

New owned file: `tests/tui/test_herdr_viewer_retention_composed.py`.

This is enabled, mounted, config-backed session composition, using the existing Faux factory fixture, real history/context, actual app scheduling registry, real Herdr viewer, shared reporter transport, registered regular fake CLI executable and real sequence lease. It does not replace the reporter or viewer with placeholders.

| Test / boundary | Evidence |
|---|---|
| `test_registered_viewer_uses_enabled_transport` | Mounted activation reaches confirmed display, holds sequence lease, and shares the identical transport with its viewer. |
| `test_new_registry_fault_retains_real_viewer[False]` | Actual registered split child acquired before `/new`; only that app registry join raises. Captured predecessor is already closing and admission revoked at join entry. Session viewer/reporter/transport cleanup proceeds. Two failed reap attempts retain the child and lease. |
| same, repeated replacement | Real old inbox lease removed, replacement slot cleared, successor reporting never starts. Another `/new` retains the same old session through the explicit quarantine slot and GC; no new wire commands. Competing real sequence-store acquisition fails. |
| same, final drain | Selected owner's actual final cleanup completes independently while old final reap is barrier-held. Repeated operator shutdown cancellation remains pending. Final success reaps/unlocks, clears the retired slot and then surfaces cancellation. |
| `...[True]` | Final reap fails persistently; public teardown remains pending despite repeated cancellation. Same live process and held lease survive, selected cleanup has already completed. Cached final drain does not repeat cleanup or wire submission. |
| fixture-only teardown | After assertions, restore original reap boundary, drain only registered test child, release owned lease, cancel private pending sentinel. Persistent Textual teardown cancellation is expected, not reported as graceful success. |

Exactly one split is captured; no rename/run is sent. Attempts are exactly the same process three times (initial cleanup, transport close, single final drain). Production one-second CLI deadline remains unchanged. All three new cases passed initially at their completed increments: **coverage of existing correct behavior**, not a production RED/GREEN claim.

## Commands and receipts

Cwd: `/root/Code/slo-94-herdr-integration/slo`. Pytest prefix for every run:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh
```

Existing helper preserves isolated fallback environment, default Herdr disable, independent registered-fake capability and real-terminal guard. Test enables only its registered fake. Each stem has `.log` and `.exit`:

- `t5-113-initial`: new module activation scaffold, 63 passed, exit 0.
- `t5-113-child`: real split/retention increment, 65 passed, exit 0.
- `t5-113-registry`: registry fault and repeat-new/GC assertions, 65 passed, exit 0.
- `t5-113-final-drain`: final-success/persistent/cancellation assertions, 65 passed, exit 0.

The helper adds 62 DAO/projection cases; these counts are not unique new tests.

Final surrounding arguments (tool command timeout **1800 seconds**, not production timeout):

```text
tests/tui/test_herdr_*.py tests/tui/test_app.py tests/tui/workflows
tests/tui/test_workflow_receive_path.py tests/tui/test_visualizer_launcher.py
tests/agents/slo_agent/herdr/test_session_lifetime.py
tests/agents/slo_agent/herdr/test_session_visualizer_lifetime.py
tests/agents/slo_agent/herdr/test_final_lifetime_closure.py
tests/cli/test_headless_retained.py
```

`t5-113-surrounding`: **764 passed, 87 warnings, 259.12s, exit 0**. This completes a combined surrounding gate rather than adding overlapping partition totals. It is not the whole non-E2E suite.

- `PYENV_VERSION=slo-harness make lint`: `t5-113-lint`, **295 errors / 60 files, 790 checked, exit 2**. No diagnostic names the owned new test. Baseline remains unwaived, not green.
- `PYENV_VERSION=slo-harness poetry run black --check tests/tui/test_herdr_viewer_retention_composed.py`: `t5-113-black`, exit 0. Formatter receipt `t5-113-format` precedes surrounding gate.
- `git diff --check`: `t5-113-diff`, silent exit 0. New file is untracked; Black and executed tests cover it, not this tracked diff check.
- `dpkg -V coreutils`: `t5-113-coreutils`, silent exit 0 after subprocess tests.

## Limits / precise remaining work

The requested retained real-child replacement composition is now executable, including successful and persistent final drains. However **overall request remains INCOMPLETE**:

1. Exhaustive prerequisite read closure was not achieved. Supplied AGENTS/CLAUDE/docs RESEARCH were available; actual routing/scope and 111/112 receipts plus scoped source/spec/KB/skill reads were made, but several aggregate reads truncated. Do not infer full C7.9–7.14, exact T5 attachments, accepted-review or full build-rule ingestion from these targeted reads.
2. The new test injects one actual app registry worker's join failure. It does not newly combine multiple actual registered workers and prove every later registry join after the first fails; existing 111 registry tests cover that separately.
3. Repeated operator cancellation is proved at shutdown/final-drain, not newly at the replacement caller while this same real split child is held. Existing replacement cancellation tests remain surrounding coverage, not this exact composition.
4. Combined retired-child/occupied-viewer/inbox four-cutoff family was not added. No full-64, T6, independent review, full-suite or overall acceptance claim.

No new production design or non-obvious runtime defect was discovered. No global/KB/spec/other-worktree writes. Existing changes and historical receipts preserved. This is implemented test evidence, not the read-only diagnostic checkpoint from 112.
