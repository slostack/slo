# T4 lifecycle continuation 27 — INCOMPLETE

Turn 1 remains active: started 1, completed 0, historical partial 1, dispatch 27,
retries 0. Unlimited turns and dispatch calls; no agents dispatched here.
No independent review or live certification. T5 still waits.

## Implemented in this continuation

Only `src/agents/slo_agent/herdr/visualizer.py` and new
`tests/agents/slo_agent/herdr/test_visualizer_lifecycle.py` changed, plus these T4 receipts.
Existing partial reader/loader and other lanes were preserved.

The adapter now has an operational invoke → split → rename → run path:
immutable attempt/operation ledger, typed admission bridge using current reporter
predicate through the actual transport lock, synchronous pending-task registration,
shielded waiters, identity-only done removal and exception retrieval, retained
uncertain/known outcomes, and a retained cancellation-resistant close task.
Close cancels and joins viewer tasks, not transport, panes or viewer processes.
No focus/query/replacement or retry command was added. Submitted means queue
acknowledgement, not paint or process-start evidence.

## Exact executed evidence

CWD `/root/Code/slo-94-herdr-integration/slo`; `pyenv which python` returned
`/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7; `make test-env`
returned `fallback`. P = `bash docs/implementation/94-herdr/t1-dao-check.sh`.
All named prefixes below have full `.log` and `.exit` receipts in this directory.
The script adds its existing DAO/projection gates and sets the approved isolated
fallback, disabled default and PYTHONPATH. Actual fake execution passes the
existing fixture registration, containment/device/inode and transport spawn guard.

| Prefix | Arguments after P | Actual result |
|---|---|---|
| t4-27-01-red | tests/agents/slo_agent/herdr/test_visualizer_lifecycle.py | missing admission import, collection exit 2 |
| t4-27-01-green | lifecycle file + test_visualizer.py + test_viewer_authority_closure.py (same directory) | 116 passed, exit 0 |
| t4-27-02-red | lifecycle file | 1 failed, 69 passed, exit 1; missing send gateway |
| t4-27-02-green | same three files | 117 passed, exit 0 |
| t4-27-03-red | lifecycle file | 2 failed, 70 passed, exit 1; missing split core |
| t4-27-03-green | same three files | 119 passed, exit 0 |
| t4-27-04-red | lifecycle file | 1 failed, 72 passed, exit 1; missing invoke |
| t4-27-04-green | same three files | 120 passed, exit 0 |
| t4-27-05-red | lifecycle file | 1 failed, 73 passed, exit 1; missing close |
| t4-27-05-green | same three files | 121 passed, exit 0 |
| t4-27-package | tests/agents/slo_agent/herdr tests/agents/slo_agent/orchestrator/test_context_reader.py tests/tui/test_workflow_visualizer_loader.py | 847 passed, 4 warnings, exit 0, 49.76s |

Each production increment was approximately 50 lines or fewer, after RED and
before its GREEN plus surrounding files. The final package run includes the
21-case split/rename/run queued-revocation matrix with real transport and live
bound reporter predicate. It changes independent reporter facts; it does NOT
prove real sequence-write/fsync/overflow failure composition.

`poetry run black --check src/agents/slo_agent/herdr/visualizer.py tests/agents/slo_agent/herdr/test_visualizer_lifecycle.py`
passed after scoped formatting (`t4-27-black`, exit 0).
`git diff --check` passed (`t4-27-diff`, exit 0).
`dpkg -V coreutils` was silent (`t4-27-coreutils`, exit 0).
No fresh mypy or full make test run; baseline 301 errors/64 files remains unwaived.
Full integration gates remain after T3/T4 integration, not inferred from package tests.

## Remaining executable gaps — not READY

- Operational viewer owns lock → actual reporter A reserves/queues → B publishes →
  unlock G2 proof, plus already-admitted stale A accounting.
- Real sequence write/fsync/overflow revocation while each viewer operation queues;
  current matrix uses independent authority-state changes, not those failure paths.
- Shared-waiter cancellation; callback identity replacement/error retrieval;
  repeated close cancellation with delayed real subprocess cleanup; multiple parents.
- Full split timeout/nonzero/oversize/cancellation composition; rename rejection versus
  ordinary exception; run failure/timeout and known-pane cancellation; retained reuse
  after successful completion through public invoke (current direct core happy path
  and public uncertain reuse are narrower proofs).
- Complete prerequisite ingestion audit: full D and exact task attachment read;
  B 7.13 and C retained-drain contracts/current accepted turn-4 review read. Combined
  skill reads were truncated and not fully recovered, notably generic declarative
  and early domain examples. Supplied AGENTS/CLAUDE/docs RESEARCH were available;
  frozen routing/scope and root RESEARCH plus KB entry/README/gotchas consulted.
  Do not claim complete mandated ingestion or whole T4 branch coverage.

Session eligibility, destination selection and app integration remain T5-owned.
No shared DAO, session, app, T3, global state, spec or other-worktree changes made.
