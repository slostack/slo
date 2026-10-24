# T2-34 diagnostic lane — INCOMPLETE

Code/test lane only; no independent review or whole-feature approval. No production
file was changed. `reporter.py` remains exclusively owned by the other worker.
No agents, delivery operations, shared status/counter edits, live Herdr, global,
specification or other-worktree changes. Unlimited workflow turns/dispatches remain
effective; supplied accounting is unchanged (turn 1 started 1/completed 0/historical
partial 1, dispatch 21 parallel, retries 0).

## Confirmed correction required in reporter.py

`HerdrReporter._record_result_diagnostic` (currently lines 412–428) excludes only
`suppressed` from failures. An admitted `cancelled` completion therefore logs
`herdr_publication_failed` and inserts that failure episode. B's final diagnostic
contract explicitly says cancellation/BaseException is not translated into ordinary
diagnostic failure. Transport's cancellation finalizer supplies exactly this
cancelled result to reporter accounting.

New `test_diagnostic_closure.py::test_reporter_cancelled_accounting_does_not_change_episode`
fails in both variants (no prior episode; unrelated restore episode). It calls the
actual `_record_command_result` owner, asserts admitted ticket consumed, then requires
unchanged logs/episode set. Actual extra message is `herdr_publication_failed`.
Correction: skip diagnostic failure/recovery for `cancelled` as well as `suppressed`,
while preserving binding uncertainty, acknowledgement invalidation and terminal
accounting. Do not suppress the actual timeout diagnostic in transport's invoke
boundary. Reporter owner must implement/test the correction; tests remain enabled,
not xfailed. This was communicated in-session; no cross-worker file was edited.

## Requirement → evidence added

| Contract | Tests / result |
|---|---|
| Independent configuration/profile categories; disabled/outside do not recover; invalid profile compact fallback; valid detail/compact | `test_gate_categories_and_inactive_builds_are_independent`, two variants, pass |
| Sink exceptions isolated for failure and recovery; recovery consumed once, no fallback logger | `test_gate_sink_recovery_is_not_retried`, pass |
| Actual invoke: definitive spawn error / lock-inclusive timeout → suppression → success → repeated success | `test_invoke_failure_suppression_and_recovery`, two variants, pass; exact safe messages, completion counts and drained lock/resources |
| Queued cancellation neither fails nor recovers, with/without episode | `test_cancelled_waiter_preserves_episode`, two variants, pass |
| Actual invoke sink exceptions; independent accounting/cleanup/termination categories and bounded retained timestamps | `test_transport_sink_failure_and_category_bounds`, pass; four fixed keys after 100 repeats |
| Reporter cancelled completion | New two-case regression above, FAIL; correction belongs to reporter owner |

Existing cross-build 0/59.999/60-second gate tests, ordinary real rejected command
recovery, actual spawn guard, accounting sink cleanup and retained-resource tests
were included in the package run. New tests retain the root fake-only spawn guard;
real successful children use the registered fixture executable. New tests do not
write executables, captures or barriers themselves. Spawn-error injection is below
the actual guard at asyncio.create_subprocess_exec; timeout uses the real lock and
configured deadline. No private exception text or temporary path enters captured
new diagnostic messages. No provider or terminal is started.

## Exact cadence and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Interpreter verified by
`pyenv which python` → `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7;
`make test-env` → fallback. Read the unchanged t1-dao-check.sh exports: test mode,
synthetic key, disabled Herdr, terminal blocker, project PYTHONPATH; no dev env.
All pytest commands below use `bash docs/implementation/94-herdr/t1-dao-check.sh`
and thus also include 62 DAO/projection cases. Receipts are sibling `.log`/`.exit`.

| Receipt prefix | Suffix / command | Result |
|---|---|---|
| t2-34-gate | test_gate_diagnostics.py | 74 passed, exit 0 |
| t2-34-invoke | test_diagnostic_closure.py (first increment) | 64 passed, exit 0 |
| t2-34-cancel-sink | same (next increment) | 67 passed, exit 0 |
| t2-34-reporter-red | same with reporter regression | 2 failed, 67 passed, exit 1 |
| t2-34-package | tests/agents/slo_agent/herdr | 2 failed, 598 passed, 4 warnings, 39.31s; exit 1 |
| t2-34-format | poetry run black on both changed test files | exit 0 |
| t2-34-black | poetry run black --check service.py and three lane test files | exit 0 |
| t2-34-diff-check | git diff --check | silent, exit 0 |
| t2-34-coreutils | dpkg -V coreutils | silent, exit 0 |

All test paths above are under tests/agents/slo_agent/herdr; service.py is under
src/agents/slo_agent/herdr. Existing-correct coverage passed initially, not invented
RED. Reporter regression is a real behavioral RED; no production changes were made.
Package count includes concurrently added tests and is not an isolated attribution
of all additional cases to this lane. No full make test/smoke/lint ran, per request;
301 errors/64 files remains the prior unwaived static baseline, not a current green.

## Remaining work and read limitations

Diagnostic closure is not complete: reporter cancellation correction and green
rerun are required. Stronger actual admitted-cancellation / timeout diagnostic
compositions and retained cleanup/recovery diagnostic assertions remain to be
completed; helper category coverage is not a substitute for those flows. Complete
B/C/D relevant contract and exact T2 attachment ingestion is also outstanding:
routing/scope-plan/t2-33/t2-code-test, current service, diagnostic tests, selected
B diagnostic/service/final-correction excerpts and tasks 446–1415 were inspected;
1416–1905 and relevant C/D accepted-decision reads were not finished. Some combined
skill/context reads truncated; no complete frozen routing ingestion is claimed.
Shared engineering routing/testing/ownership, coding-rules/cadence, Python root/
declarative/type/docstring/service guidance and canonical workflow were consulted;
KB Welcome/Slo README/gotchas and root RESEARCH were consulted. Initial actual
AGENTS/CLAUDE command redirected rather than exposing contents; supplied context
was used, not a claim of a complete fresh actual-file read.

Do not mark this lane READY on the passing subsets. The concrete next action is
reporter-owner correction using the retained RED tests, then finish the remaining
diagnostic compositions/reads and rerun focused/package/Black/safety gates.
