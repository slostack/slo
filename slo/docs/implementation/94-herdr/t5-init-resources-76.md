# T5 continuation 76 — INITOWNERSHIP INCOMPLETE

Same unfinished turn 1; started 1, completed 0, historical partial 1,
dispatch 76 (supplied), retries 0. Unlimited turn/dispatch budgets; no agents.
No canonical/global/live/other-worktree edits, git publication or destructive git operations.

## Delivered test-first increments

1. Immutable local `_DeliveryInitialization` captures session object, scalar ID,
   owner, lease/inbox/service/renderer references before the initial await.
   Fifteen mounted real-store barriers mutate owner/ID/store/inbox/service after
   reconcile/acquire/inbox. Every case now refuses continuation and removes the
   original lease, not a successor-store record.
2. Timer teardown snapshots handles and retains displaced failed handles in an
   app-owned tuple for later stop. The permanent unsafe flag prevents normal
   subsequent initialization from growing this retention.
3. Lease release retains a task and joins the actual filesystem thread under
   repeated cancellation. The first cancellation object/message is re-raised
   after thread terminal, including release failure.
4. Initialization records its own timers before publication checks. Rollback
   receives that exact tuple, preserving successor slots. Real mounted timer1,
   timer2 and inbox displacement tests prove exact stop identities.
5. Construction faults are contained again; missing-store acquisition refusal
   has a dedicated test. Reconcile/acquire faults retain fixed local failure.
6. Existing replacement delivery retirement now precedes reporter close and
   adoption; successor delivery follows UI reset. Exact ordered recording test.
7. Mount and replacement share `_finish_replacement_runtime` for delivery,
   usage and preparation. Optional mount notice/usage faults no longer skip
   retained runtime initialization.

## Finite remaining audit — readiness withheld

| Branch/obligation | Evidence/status |
|---|---|
| Owner/ID/store/inbox/service after three awaits | 15-case RED/GREEN |
| Returned lease mismatch, duplicate init, nine stop/release/notice combinations | Prior tests preserved and rerun |
| Displaced stop success/failure and later cleanup | RED/GREEN |
| Init-owned timer subset, successor slots at inbox/timer1/timer2 | RED/GREEN |
| Release-thread repeated cancellation, success/error, original cancel | RED/GREEN |
| Missing store; build/reconcile/acquire failures | Dedicated tests; build RED/GREEN |
| Mount optional notice/usage and replacement phase order | RED/GREEN |
| Captured renderer mutation and actual session-object replacement at every await | Not yet added to finite matrix |
| Successful publication displaced by timer slot mutation without owner change | Not comprehensively proved |
| Rollback service/renderer clearing after release continuation | Identity checks exist; dedicated post-release displacement barrier still needed |
| Captured None store semantics | Optional parameter still uses None as current-store fallback; explicit capture distinction needs resolution |
| Acquisition complete explicit capture | Gateway still reads current store/ID synchronously after binding validation; explicit binding delegation not finished |
| Init cancellation from preparation itself | Public retained mount protects normal callers; direct preparation CancelledError rollback not proved |
| Strict cleanup only init timers | Helper also retries previously retained failed timers; review against requested strict subset still outstanding |
| Bounded retained timer proof with displaced failed init + successor pair | Normal unsafe guard exists; full combined failure/strong-reference test still missing |
| Canonical full phase closure | Shared seam exists; activation is absent (next family), viewer drain absent (later family); complete ordering precondition audit still outstanding |
| Full affected required-read closure | See below; incomplete |

No READYINITOWNERSHIP or overall T5 claim. Actual mounted activation remains the
explicit next family after INITOWNERSHIP, then inbox and viewers. No full make
test/smoke was run because this family is not ready.

## Execution receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. All pytest invocations use
`PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`;
the unchanged helper adds 62 foundation cases, no environment created.
Logs and numeric exits are `t5-76-<name>.log` / `.exit` in this directory.

| Name | Target / result |
|---|---|
| red1 | ownership: 15 failed, 69 passed, exit 1 |
| green1 | surrounding: 362 passed, 1 deselected, exit 0 |
| red2 | rollback: 1 failed, 78 passed, exit 1 |
| green2 | surrounding: 364 passed, 1 deselected, exit 0 |
| red3 | ownership: 2 failed, 84 passed, exit 1 |
| green3 | surrounding: 366 passed, 1 deselected, exit 0 |
| red4 | rollback: 3 failed, 79 passed, exit 1 |
| green4 | surrounding: 369 passed, 1 deselected, exit 0 |
| red5 | ownership: 1 failed, 89 passed, exit 1 |
| green5 | surrounding: 373 passed, 1 deselected, exit 0 |
| red6 | ownership: 1 failed, 90 passed, exit 1 |
| green6 | surrounding: 374 passed, 1 deselected, exit 0 |
| red7 | ownership: 2 failed, 91 passed, exit 1 |
| green7 | surrounding: 376 passed, 1 deselected, exit 0, 201.70s |
| final-focus | both ownership/rollback after formatting/type narrowing: 113 passed, exit 0 |

Surrounding suffix reused from 75 (not a restarted audit):

```text
tests/tui/test_herdr_init_ownership.py tests/tui/test_herdr_init_rollback.py tests/tui/test_herdr_initialization.py tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_replacement.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_app.py tests/tui/authentication
```

Black/check scoped to `src/tui/app.py` and the two edited init tests: exit 0.
`git diff --check`: exit 0, silent. `dpkg -V coreutils`: exit 0, silent,
also checked after each surrounding suite. `PYENV_VERSION=slo-harness make lint`
initially found 302 errors/64 files (three new test Optional narrowing errors);
corrected with explicit assertions, final **299 errors/63 files**, exit 2.
Baseline remains UNWAIVED. Matching counts alone are not a normalized diagnostic
identity comparison; no new init-test errors remain in final output.

## Required reads performed / limitations

Fresh full reads: actual AGENTS (initial truncation recovered 1–150), CLAUDE,
root RESEARCH and docs/RESEARCH; frozen routing and scope-plan; engineering
routing/testing/ownership; coding-rules/code-test-loop/shared declarative; Python
root/declarative/named arguments/docstrings; complete Textual and Faux skills;
workflow SKILL; KB Welcome/slo README/gotchas; canonical C7.9–end and exact T5
sample attachment 2401–3720; accepted independent turn4 review (truncated opening
recovered separately) and finalization receipt; Makefile and approved helper;
lease store; init ownership/rollback/initialization/replacement/shutdown tests;
app constructor/mount/preparation and init/rollback/timer/release/replacement seams;
root conftest safety guards.

Not complete: full affected surrounding app/test source closure, remaining KB build
rules, full state-isolation source, and normalized static diagnostic comparison.
The final diff was whitespace checked; full convention review remains open,
including new test helper annotations and outdated helper docstrings. No external
KB write under user restrictions. Prior receipts remain historical, unchanged.
