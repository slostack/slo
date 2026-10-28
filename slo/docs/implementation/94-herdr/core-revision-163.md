# Core revision163 — partial implementation, NOT READY

Accounting supplied by parent: turn4/global163/current dispatch2; started4/completed0/historical stopped partial1/retries0; effective budgets UNLIMITED. Prior162 completed exit0 was a domain pause, not failure/abort. No subagents, Git mutation, packages, global state, specifications or live integration changed. Independent re-review remains required. Live DEFERRED; compatibility UNVERIFIED.

## Starting state and chronology

Verified branch `feature-94-herdr-integration`, origin `https://gitlab.com/core-27/slo.git`, HEAD/base `d0e3a756689f2675e5507034d43cd8b272d3c6b8`.
Before source edits preserved exact sequence-store bytes at `core-revision-163/sequence_store.start.py`, SHA256 `6b76f8a2020d9bd46d6576924deaf500f46df72494d202327ab6a021c3d86406`. Tool UTC capture was `2026-10-19T20:13:59Z`; no claim that this agrees with parent's wall-clock labels. The existing `_close_ambiguous`/`_identity`/`_reconcile_close` implementation is unattributed and UNVERIFIED starting work, not authored here. No RED-before-that-edit claim. No concurrent conflicting writer established; no process inspection or private transcripts used.

## Actual bounded work

Added `test_lease_ambiguity.py`: close-before-error, close-after-release, different-file FD reuse and inspection failure. With the inherited implementation, four new cases plus whole sequence module passed: **45 passed,2 warnings**, exit0 (`lease-start.log/.exit`). These prove no second close of the ambiguous slot and continued replacement descriptor usability in the tested cases only. They do NOT finish restore retained-owner or pane final-drain acceptance, same-inode generation cases or all EBADF variants.

Added `test_sequence_short_reads.py`: valid prefix/EOF, corrupt suffix, exactly4096 vs4097 bytes, and error after prefix; refused acquisition cannot reserve and original bytes remain unchanged. Current-state RED: **5 failed**, exit1 (`short-red.log/.exit`). Then changed only sequence `_read_state` to accumulate through EOF or4097 bytes and return bytes. Focused plus whole sequence and ambiguity modules: **50 passed,2 warnings**, exit0 (`short-green.log/.exit`). This is new RED-first behavior evidence; historical161 probes are not represented as its RED run. Post-edit sequence SHA256 `721c64463051ae69544458ebb1d534ac465ce095a94b3d93f2206803573cf9f8`.

All executions used explicit `/root/.pyenv/versions/slo-harness`, VIRTUAL_ENV/PATH/PYENV_VERSION; verified Python3.11.7 and make test-env=fallback. Targeted invocation was `python -m pytest -q` with the named modules, tracked Makefile synthetic fallback environment and PYTHONPATH=$PWD. Root isolation/terminal/fake-Herdr guards read and retained. All writes in new tests check temp-root containment. Post-suite `dpkg -V coreutils` was silent. Black formatted the ambiguity test after green (no subsequent test rerun yet); short-read test unchanged. `git diff --check` silent. No full1070 selection, surrounding session/app suite, lint or full gates run here.

## Prerequisite qualification

AGENTS/CLAUDE/docs RESEARCH supplied full context; root RESEARCH, Makefile, routing, independent161 report/read ledger/probes and160 receipt read. KB Welcome/slo README/gotchas consulted. Worktree workflow/code-test-loop, routing/ownership/testing/coding rules, Python root/types/docstrings/shared+Python declarative loaded. Canonical B7.5/B7.9 and samples B19/B20/C23 read. Sequence/restore full bodies and reporter close/session aggregation inspected. Broad aggregate prerequisite output truncated: scope-plan and some additional component prerequisites are NOT claimed fully reread. Remaining prerequisite reads must precede further changes in those layers.

## Remaining required work

- R161-1: retain unresolved restore operation-local owner; verify pane and restore cleanup matrices, identity unavailable/same inode/EBADF, conservative final resources. Never retry an ambiguous FD. Existing close-before-error test expects eventual retry and needs safety-grounded revision, not arbitrary weakening.
- R161-2: add composed reporter/viewer no-admission proof and reservation-time short-read/refusal coverage. Existing five new cases cover acquire only plus forbidden subsequent reserve.
- R161-3: RED-first canonical intermediate close semantics, retained physical lease, sticky remote/cleanup failures, final resource evidence; align session aggregation and normal replacement/suppression tests.
- R161-4: truthful Google Args/Returns/Raises/cancellation/ownership docs after semantics settle; audit all core complex APIs.
- Run full owned1070 selection plus new tests, affected session/app surrounds, lint/Black/diff; separate dispatch for exact full gates per parent request. Preserve159usage/156profile/151terminal/146guards.

No finding is declared fully closed. This receipt is a partial handoff, not a new approval request, numeric stop, independent review or workflow completion.
