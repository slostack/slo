# CI repair — headless child control (scope A)

Baseline: commit `4ab10b0`, MR pipeline2970613678/job17338411077, trace
`/tmp/herdr-ci-4ab10b0.log` (11 failed / 10490 passed). This repair covers only
the seven `tests/cli/test_headless_child_abort.py::TestHeadlessRunnerChildControl`
failures owned by scope A, plus the ER-04 contract correction from
`ci-repair-early-review.md`. No commit/push; full gates deferred to fan-in per
`current-ci-repair-plan.md`.

## One root cause, one fix

The seven failures are one causal chain, not seven defects:

1. `HeadlessRunner.invoke()` owns the adopted-session reporting lifetime: it
   awaits `session.start_external_reporting()` after preparation and joins
   `session.close_external_reporting()` +
   `session.finish_retired_reporting_cleanup()` in its outer `finally`
   (`src/cli/headless.py` — unchanged production behavior, also asserted by
   `tests/cli/test_headless.py::test_reporting_lifetime_surrounds_headless_run`).
2. The test double `_DispatchingSession` in
   `tests/cli/test_headless_child_abort.py` predates that protocol and lacked
   all three methods. The runner task therefore died with
   `AttributeError: '_DispatchingSession' object has no attribute
   'start_external_reporting'` before starting child control.
3. With the runner task finished, every test-side `_until`/`_bounded`
   predicate (`accepting_capability`, children running) timed out → the four
   `TimeoutError` failures; the abandoned blocked stream task plus the
   unretrieved runner exception tripped the
   `_every_task_exception_retrieved` fixture on top.

Production is not at fault: the sibling headless doubles
(`tests/cli/test_headless.py::_BlockedSession`,
`test_reporting_lifetime_surrounds_headless_run`) already implement the same
three-method protocol. **Fix (test-side only):** add the three reporting seams
to `_DispatchingSession`. No production edit to `src/cli/headless.py` was
required — the demonstrated defect is the test double's missing protocol, not
the runner. No waits increased, no observer suppressed; the fix removes the
abandoned task rather than tolerating it.

## ER-04 correction — explicit typed reporting contracts (not "fail closed")

**Retraction:** the first revision of this report claimed the bare `AsyncMock()`
seams "fail closed." That claim was wrong and is corrected here. A bare
`AsyncMock()` returns another auto-mock when awaited — neither the documented
`None` activation result nor a real `HerdrReporterCloseOutcomeDAO` — and such
an object fabricates arbitrary attributes and truthiness. Recording calls is
not failing closed. The early review's qualification is also accepted: the
runner currently ignores both close return values and unconditionally awaits
final cleanup, so the previous mocks were never driving a truthy `resources`
branch or masking a real drain violation; the 25 child tests are child-control
evidence, not reporting-resource drain evidence.

**Correction (test-side only, no production change):**

- `_DispatchingSession.start_external_reporting` → `AsyncMock(return_value=None)`
  — the explicit documented activation result.
- `_DispatchingSession.close_external_reporting` and
  `finish_retired_reporting_cleanup` → `AsyncMock(return_value=...)` returning
  real `HerdrReporterCloseOutcomeDAO(replacement="safe", resources="drained")`
  instances — the truthful contract for this resource-free fixture (the DAO's
  own validator forbids `retained` without `uncertain`, so the returned values
  are genuine domain objects, not permissive fabrications).
- Meaningful await assertions at both relevant runner boundaries:
  `assert_awaited_once_with()` on all three seams in
  `test_consumer_runs_during_dispatch` (normal exit boundary) and
  `test_runner_cancellation_still_joins_close` (cancellation boundary). These
  fail if the runner ever stops awaiting any gateway, so they are non-vacuous.
- No new mock-special handling in production, no permissive widening of the
  runner, no Herdr test-matrix expansion of the child-abort suite.

## Per-failure RED → GREEN

| Failure | CI error | RED reproduced | GREEN |
|---|---|---|---|
| consumer_runs_during_dispatch | TimeoutError (cascade of AttributeError) | yes | yes |
| run_without_owner_context_publishes_no_capability | AttributeError | yes (shared cause) | yes |
| plain_headless_run_publishes_no_capability | AttributeError | yes (shared cause) | yes |
| start_failure_leaves_execution_usable | TimeoutError (cascade) | yes (shared cause) | yes |
| composition_failure_leaves_execution_usable | TimeoutError (cascade) | yes (shared cause) | yes |
| runner_cancellation_still_joins_close | TimeoutError (cascade) | yes (shared cause) | yes |
| restarted_runner_refuses_old_run_request | AttributeError | yes (shared cause) | yes |

RED command (pre-fix, exact): pytest of the class failed the first test in
4.08s with the AttributeError "Task exception was never retrieved" report —
byte-identical signature to the CI trace (`headless.py:137` runner task).

## Verification evidence

All commands from `/root/Code/slo-94-herdr-integration/slo` with
`set -a; source environments/tests.env; set +a` plus
`SLO_HERDR_DISABLED=1 SLO_AUTO_VISUALIZE=0 PYTHONPATH=$PWD`
(pyenv `slo-harness`, Python 3.11.7):

1. `python -m pytest tests/cli/test_headless_child_abort.py::TestHeadlessRunnerChildControl::test_consumer_runs_during_dispatch -q`
   → **1 passed** in 2.21s (was: 1 failed).
2. `python -m pytest tests/cli/test_headless_child_abort.py -q` (entire
   affected module, rerun after the ER-04 correction) → **25 passed** in
   5.95s. All assertions/invariants preserved; six new typed-contract await
   assertions added, none relaxed.
3. Nearest headless regression modules (rerun after the ER-04 correction):
   `python -m pytest tests/cli/test_headless_child_abort.py tests/cli/test_headless.py tests/cli/test_headless_parity.py tests/cli/test_headless_events.py tests/cli/test_headless_exclusions.py tests/cli/test_headless_logging.py tests/cli/test_headless_request.py tests/cli/test_headless_retained.py tests/cli/test_headless_watchdog.py tests/cli/test_headless_herdr.py -q`
   → **162 passed** in 10.18s. No pending/unretrieved task exceptions (the
   autouse `_every_task_exception_retrieved` fixture stayed green).
4. `poetry run black --check tests/cli/test_headless_child_abort.py` → clean.
5. `git diff --check` → clean. `dpkg -V coreutils` → no output (exit 0).

## Scope discipline

- Files changed: `tests/cli/test_headless_child_abort.py` only (typed
  reporting seam configuration in `_DispatchingSession.__init__` plus six
  boundary await assertions in two existing tests) and this report.
- `src/cli/headless.py` not edited: no production defect demonstrated, and
  ER-04 explicitly forbids inventing permissive production behavior — the
  production close gateways still execute exactly as released.
- Worktree contains foreign uncommitted edits (e.g. `src/tui/app.py`, scope
  B/C workers); preserved untouched. No commits, pushes, full suites, or
  subagents.
- Full gates (`make test`, `make smoke`, `make lint`) intentionally deferred
  to the coordinated fan-in per the plan's no-concurrent-full-suites rule.

## Next risks

- Full-suite gate at fan-in may surface cross-scope interactions (e.g. scope
  B/C edits against `src/tui/app.py`); rerun this module after fan-in edits.
- `_DispatchingSession` now tracks the session reporting protocol by hand; a
  future fourth reporting method added to `HeadlessRunner`'s adoption path
  will need the same seam in this double (same failure signature: AttributeError
  → TimeoutError cascade).
- The typed seam outcomes (`safe`/`drained`) describe only this resource-free
  fixture; they assert nothing about real reporting-resource drains, which
  remain covered by session/herdr-owned tests elsewhere.
- Live Herdr acceptance remains user-deferred/unverified, unchanged by this
  repair.

Verdict: **READY** (scope A focused evidence complete, ER-04 fully resolved
with explicit typed contracts and the false "fail closed" claim retracted;
full gates pending fan-in).
