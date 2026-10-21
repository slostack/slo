# T5 multiworker 116 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 116, retries 0. User turn/dispatch budgets unlimited; no agents launched. No production edits, commits, global/live/spec/other-worktree mutations. Shared status and the parallel all-owner test lane were not edited.

## Delivered evidence

Owned files:
- `tests/tui/test_herdr_viewer_retention_composed.py`
- `tests/tui/test_herdr_multiple_viewer_owners.py`

The new matrix has eight cases: registry join healthy/failing × replacement caller normal/repeatedly cancelled × final drain successful/persistent. This is coverage of existing correct production behavior, not a production RED/GREEN claim.

Both workers are registered through actual `SloTUI._schedule_visualizer_launch`, with distinct persisted canonical workflow parents, the real async launcher/session eligibility/Herdr viewer, and one reporter-owned transport. The first registered fake split process is live before the second viewer reserves its operation. The second has an empty admitted-operation set and both registry tasks are pending. Capture contains exactly one split and no rename/run. The queued reservation remains unadmitted after close. No worker-only stand-in substitutes for the real gateway.

A join fault on the first registry task does not skip the second join. Both workers terminate before adoption checks. Repeated cancellation is directed to the public `/new` dispatch caller after irreversible commit. Instrumented workers delegate to the real original worker and then enter finalizers that acquire the submission lock. While finalizers are barrier-held, the caller and commit remain pending, the old session remains selected and revoked, and session close has not begun. After release both finalizers finish, adoption completes, the commit is terminal and cancellation propagates. No production deadline was increased.

The retained-resource helper proves the same real child and real sequence lease remain quarantined; repeated `/new` keeps one strong old-owner slot and suppresses successor activation. GC reachability, contender refusal, selected-owner independent cleanup, one final local drain, cached outcome, no wire retry, and repeated shutdown cancellation remain asserted for both successful and persistent drain. Persistent graceful shutdown remains pending; fixture-only cleanup restores the original reaper and releases only owned resources.

## Test-first history and harness failure

Initial run exceeded the 1800-second tool timeout after the helper's 62 DAO/projection tests; it produced no pytest terminal verdict and no `.exit` receipt. Do not describe it as a product RED. A bounded fixture rescue exposed the actual setup defect: creating the second parent reused the first parent's unique session name (`ValueError: session name already in use: retained viewer`). The setup exception occurred before the helper's existing resource-finally region, so intentional retained cleanup waited indefinitely. Session names now include their canonical ID, and the second persisted parent is prepared before starting the first child.

A test-only 20-second rescue releases barriers and restores the original reaper if a test assertion fails before ordinary cleanup. Successful cases finish far earlier; rescue is cancelled and retrieved. This changes no production lifecycle timeout. The initial timed-out run does not establish successful resource cleanup; the subsequent coreutils check was silent, but no process-inventory claim is made.

## Executed receipts

Cwd `/root/Code/slo-94-herdr-integration/slo`. Pytest prefix:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh
```

The helper adds 62 DAO/projection tests. Counts below overlap and are not additive.

| Stem under this directory | Result |
|---|---|
| t5-116-multiple | Tool timeout at 1800s, no terminal pytest result/exit file |
| t5-116-isolated | 1 failed / 62 passed, exit 1; duplicate-name fixture defect |
| t5-116-multiple-green | 67 passed, exit 0; two-worker join-fault cases plus existing helper tests |
| t5-116-caller | 85 passed, exit 0; caller cancellation plus replacement/registry surrounding |
| t5-116-surrounding | 786 passed, 95 warnings, 276.90s, exit 0 |
| t5-116-format | Black applied to both owned files before final surrounding |
| t5-116-black | Black check both files, exit 0 |
| t5-116-static | mypy --follow-imports=silent both files, no issues, exit 0 |
| t5-116-diff | git diff --check, silent exit 0 |
| t5-116-coreutils | dpkg -V coreutils, silent exit 0 |

Surrounding arguments:

```text
tests/tui/test_herdr_*.py tests/tui/test_app.py tests/tui/workflows
tests/tui/test_workflow_receive_path.py tests/tui/test_visualizer_launcher.py
tests/agents/slo_agent/herdr/test_session_lifetime.py
tests/agents/slo_agent/herdr/test_session_visualizer_lifetime.py
tests/agents/slo_agent/herdr/test_final_lifetime_closure.py
tests/cli/test_headless_retained.py
```

Tool timeout was 1800 seconds. Existing fake capability, Faux factory, environment isolation and terminal guards were retained. No real provider or Herdr executable was selected. Owned files remain untracked; tracked diff check is not a review of their contents. Their contents were inspected, formatted, type-checked and executed separately.

## Finite audit and remaining blockers

| Obligation | State |
|---|---|
| Two actual app workers, shared transport, admitted versus queued | Eight new composed cases pass |
| First registry join fault cannot skip later join | Exact join-list assertion passes |
| Replacement caller repeated cancellation after commit | Actual public dispatch + real workers + gate-dependent finalizers pass |
| Retained child/lease, strong quarantine, sticky suppression, final drain | Existing helper assertions executed across all eight cases |
| Healthy versus throwing diagnostics composed with these workers | Not added; existing separate diagnostic coverage is not claimed as this composition |
| T2/T4 multiple-parent cancellation proof reconciliation | Production viewer/service paths read; complete existing test-to-canonical audit not completed |
| Canonical C7.9–7.14 | Completely read in two bounded reads (605–1364 and 1364–end) |
| Canonical D shared transport/registry and exact T5 samples/accepted reviews | Targeted D search only; full D, exact attachments and accepted-review read closure not completed |
| AGENTS/CLAUDE/docs RESEARCH | Supplied full context consulted; no claim of fresh complete file ingestion |
| Routing/scope/KB | Complete routing read; scope aggregate truncated; KB Welcome/gotchas read, actual README not completed |
| Skills | Engineering routing/testing/ownership, coding rules/cadence, Python root/specialized declarative, Textual, Faux, workflow overview read in full. Shared declarative and Python named-argument/docstring sibling reads not completed |
| Build/isolation affected-read closure | Existing helper and Faux fixture read; complete Makefile/state-isolation/conftest and affected owner/test reads not completed |
| Static baseline/full integration | Scoped mypy green only; historical 295 errors/60 files remains unwaived and was not freshly rerun. Full make integration remains later, not claimed green |

**Verdict: INCOMPLETE.** The requested real multiworker and replacement-caller composition is now executable and passing. Finite family acceptance still requires the concrete diagnostic variant and the specified read/audit closure above; no artificial case, turn or dispatch budget is used as a stopping rule. No full-feature, independent review, T6, live or release acceptance claim.
