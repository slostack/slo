# T6 mounted outcomes 127 — INCOMPLETE (new bounded evidence)

## Scope and accounting

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 127, retries 0. Unlimited user turn/dispatch budgets retained. No agents dispatched. Changed only `tests/integration/test_herdr_full_flow.py`, this receipt and `t6-mounted-outcomes-127/` receipts. Parity helper unchanged. No production changes, shared-status writes, spec edits, Git mutations, other-worktree edits or live operations. Two-process HOLD retained: only explicit safe files collected, no full make/integration-directory gate.

## Implemented evidence

### Inactive attempts

Removed the old `_prepare_herdr_reporter` raising mock: that replaced the production gate itself and could be swallowed by optional integration failure isolation. New disabled/outside mounted tests run the real gate, PromptInput Enter, Faux graph, actual bound tool executor, usage accumulation and durable history assertions.

Fourteen integration-specific boundaries record calls and raise if reached: parent preparation, capture-input preparation/path probing, restore construction/save/directory preparation, sequence construction/acquire/reserve, file-lease validation/acquire, transport construction/invoke/spawn. Assertions run outside the mounted journey and isolated callbacks, after teardown. Both modes require zero calls; normal Slo history I/O remains allowed. This is explicit owner-boundary attempt evidence, not blanket filesystem syscall tracing. Direct low-level filesystem operations that bypass these named owners are not independently intercepted.

### Real transport and viewer results

Every actual transport invoke return is captured with a spy that awaits and returns the original production method. All eight existing synthetic reporting privacy journeys now scan every complete result DAO and require rejected results in the failing-child variants; reporting results must have no parser bytes. Existing publication, argv, diagnostics, events, private-path and close assertions remain.

Attached/detached mounted viewer journeys now cover success, rejected run, oversized split stdout and private non-JSON split stdout (eight scenarios). Fake executables remain identity-registered temp-owned regular files. Transport and viewer invoke spies delegate to production. An explicit second public `session.open_workflow_visualizer` request reaches the real ledger rather than only the TUI dedup guard. Success returns submitted/reused; rejected run preserves known pane and returns failed/reused; oversized and private malformed split return failed/failed without another split. Exact command ordering remains asserted.

Scans include every transport result's public fields and every adapter viewer outcome, through successor replacement and teardown. `HerdrCommandResultDAO.json_bytes` is private parser input by actual DAO contract, not a public outcome; successful malformed stdout is explicitly asserted present there. Failed transport results must have no parser bytes. Private bytes are never asserted absent from their intentional private carrier. Configured synthetic credentials, private child output, temp workdir and private session labels are excluded from scanned public outcomes. Literal intentional conversation is not incorrectly forbidden in Slo transcript.

## Actual verification

Approved existing `PYENV_VERSION=slo-harness` resolves `/root/.pyenv/versions/slo-harness/bin/python`. Safe fallback command used throughout:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <explicit paths>
```

Helper adds 62 foundation cases; overlapping counts must not be summed.

| Receipt | Selection | Actual result |
|---|---|---|
| inactive | new inactive test + activation composed file | 73 passed |
| viewer | expanded viewer test | 8 failed, 62 passed: test called nonexistent launch_workflow_visualizer |
| viewer-green | viewer test + attached composed file | 2 failed, 74 passed: test expected unavailable instead of production's documented malformed oversize result |
| viewer-final | same selection after test corrections | 76 passed |
| channels | reporting privacy + viewer tests + attached composed file | 84 passed |
| final | full owned test file + activation composed + attached composed | **149 passed, 84 warnings, 127.83s, exit 0** |

These RED results were test-author defects, not production failures or mutation sensitivity evidence. No production RED was found or repaired. Black and own-file mypy (`--follow-imports=silent`, both owned files) pass. `git diff --check` silent; it does not include the pre-existing untracked full-flow file. Coreutils verification was silent after each test command; final silent exit-0 receipt retained. Global baseline **281 errors / 58 files remains UNWAIVED**, not rerun. No full suite under HOLD.

## Remaining qualifications — no READY claim

The two requested proofs gained executable evidence, but strict closure is withheld:

- Disabled instrumentation covers integration-owned preparation/probe/store/sequence/transport boundaries, not independent path-filtered low-level filesystem write-attempt interception. No deliberate caught-failure mutation was executed to prove the outer assertion catches an attempted write.
- Viewer capture is at the actual Herdr adapter invoke boundary; not every higher-level platform/skipped/failed bridge outcome category is exercised. The supplied success/reject/oversize/private-output/known-pane matrix is covered, not the full lifecycle family.
- Complete requested prerequisite reading was not achieved. Consulted actual relevant source methods, DAO private/public distinction, predecessor 125/126 receipts, scope plan, root research, KB Welcome/slo README/gotchas, engineering routing/testing/ownership, Python/Faux/cadence/workflow guidance. Some bulk guidance output truncated; full canonical B/C/D privacy/disabled sections, accepted-review companions, actual full project-instruction rereads and Textual/integration guidance were not all completed. Prior context is not substituted for read closure.
- Sentinel-bearing session/tool exceptions, configured model/provider/effort rotation, independent publication credential lookup, remaining parity oracle sensitivity and full lifetime/viewer unification remain next-family work, unchanged.

This is a test-only implementation increment with passing explicit safe regression selection, not T6 completion, independent review or live Herdr acceptance.
