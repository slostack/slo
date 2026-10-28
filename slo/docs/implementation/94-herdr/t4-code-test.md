# T4 Code/Test — technical READY

## Current continuation 31

**Entire T4 adapter/reader scope technical READY.** See `t4-handoff-31.md`
for the finite whole-requirement map, completed read audit, exact task/regression
reconciliation and receipts. Closed literal AtomicFileWriter tmp.write failure
for queued split/rename/run and already-admitted A accounting composed with the
PUBLIC viewer for same/changed generation. Five cases added, initial green
against existing production behavior; no production/T3/T5/shared-DAO edits.
A test-only wrapper annotation defect was corrected; failed receipt preserved.
Final package/reader/loader: **1027 passed**; surrounding regressions **214 passed**;
exact tasks.md T4 list **138 passed**. Nine-file Black/diff pass; coreutils silent.
Latest verified lint remains **300 errors/64 files, unwaived**, no T4 diagnostic
or new ignore. Full make remains after T3 and T4 closure as instructed; latest
inspected T3 receipt remains incomplete. This is not integrated Step-1 acceptance,
independent review, full chapter D, live compatibility or viewer-paint acceptance.
Counters: same turn 1 started 1/completed 0/historical partial 1, dispatch 31,
retries 0; unlimited turns AND dispatches. No agents dispatched here.

## Historical continuation 30 (preserved)

**REVISE — entire T4 technical READY withheld.** See `t4-g2-30.md` for
finite requirement mapping and exact receipts. Closed public-viewer G2
close/cancel/timeout with same/changed generation using real registered CLI,
shared reporter transport and durable reservation. Added builder rejection and
completion guard assertions: 13 additional cases, all initial green against
existing correct production behavior. Post-format package/reader/loader:
**998 passed, 4 warnings, exit 0**, including concurrent disjoint additions.
Scoped Black/diff/coreutils receipts saved. No production edits, T3/T5 edits,
agents or full make. Latest lint 300/64 remains unwaived, not rerun.
Remaining: literal tmp.write failure (distinct from fsync), already-admitted
report A accounting composed with public viewer, complete required ingestion
and final task-regression reconciliation. No independent review/live claim.
Counters preserved: turn 1 started 1/completed 0, historical partial 1,
dispatch 30, retries 0; unlimited turns and dispatches.

## Historical continuation 29 (preserved)

**INCOMPLETE — entire T4 technical READY withheld.** See `t4-final-29.md`
for the finite branch map and exact remaining rows. Added 39 lifetime acceptance
cases: real timeouts, admitted/new authority split across all seven facts and
three operations, real reservation durability/overflow revocation, repeated
close cancellation with two parents and delayed real reap, ordinary exceptions.
All initial passes after correcting one test-barrier defect; no production
behavior fix claimed. Fixed three viewer/test typing errors without ignore/Any.
Fresh package: **972 passed, 4 warnings, exit 0**; scoped Black/diff pass;
coreutils silent. Fresh lint: **300 errors/64 files, unwaived**, no T4 diagnostics.
Remaining public-viewer G2 lifecycle/admitted-A compositions, exact write failure,
callback/builder negative branches and prerequisite reads are enumerated in the
receipt. Full make waits for T3/T4 READY. No agents or T5 assembly.
Counters preserved: turn 1, started 1/completed 0, historical partial 1,
dispatch 29, retries 0, unlimited turns AND dispatches.

## Historical continuation 28 (preserved)

**INCOMPLETE — T5 still waits.** Added 11 acceptance cases in
`tests/agents/slo_agent/herdr/test_visualizer_acceptance.py`, all initial passes:
operational public viewer/shared-lock G2 supersession (same/changed generation),
public retained outcomes, shared-waiter cancellation and callback identity/error
retrieval. No production edits or artificial RED cycle. Fresh post-format
package/reader/loader gate: **928 passed, 4 warnings, exit 0**; count includes
other lanes. Scoped Black/diff checks and silent coreutils verification recorded.
See `t4-acceptance-28.md` for the current finite requirement map, exact receipts,
remaining real-sequence/lifecycle/authority cases and incomplete read audit.
No fresh lint/full make, independent review or live paint claim. Supplied counters
preserved: turn 1 started 1/completed 0, historical partial 1, dispatch 28,
retries 0; unlimited turns/dispatches; no agents dispatched here.

## Historical continuation 27 (preserved)

Operational viewer lifecycle now exists in `herdr/visualizer.py`: invoke/shared
pending task, immutable operation admission, split/rename/run, retained outcomes,
and cancellation-resistant close. New `test_visualizer_lifecycle.py` includes real
guarded transport execution and 21 queued live-authority revocation cases.
Post-format package/reader/loader gate: **847 passed, 4 warnings, exit 0**.
Changed-file Black and diff checks pass; coreutils verification silent.
See `t4-lifecycle-27.md` and `t4-27-*.log/.exit` for exact RED/GREEN receipts and
remaining executable gaps. **T4 remains INCOMPLETE; T5 waits.** No independent
review, live certification, fresh lint or full integrated make test is claimed.
Counters: turn 1 started 1/completed 0, historical partial 1, dispatch 27,
retries 0; unlimited turn/dispatch budgets. No agents dispatched here.

## Historical continuation 26 (preserved)

This receipt is partial implementation, NOT T4 technical READY or feature completion.
Parent counters/status untouched: supplied turn 1, started 1/completed 0,
historical partial 1, dispatch 26, retries 0; unlimited turns/dispatches.
No agents, live Herdr/providers/windows, system changes, commits or external writes.

## Implemented

- `orchestrator/context_reader.py`: single tolerant existing-schema reader using
  shared ordinary session-ID validation and OrchestrationLayout; missing/invalid/OS
  failures return None without diagnostics. Ordinary slug support preserved.
- `tui/workflow_visualizer_loader.py`: delegates context loading to that reader;
  duplicate parser removed. Other discovery unchanged.
- `herdr/visualizer.py`: ONLY constructor, strict bounded split-envelope parser,
  fixed split/rename/run command builder with T1 canonical UUID validation.
  This is NOT a functioning launcher yet: invoke/admission/lifetime remain absent.

## Test-first cadence and exact commands

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified pyenv interpreter
`/root/.pyenv/versions/slo-harness/bin/python`, Poetry Python 3.11.7,
`make test-env` = fallback. P below is exactly
`bash docs/implementation/94-herdr/t1-dao-check.sh` (adds 62 existing tests).
Each prefix has `.log` and `.exit` under this directory.

| Receipt | Command after P | Result |
|---|---|---|
| t4-01-red | tests/agents/slo_agent/orchestrator/test_context_reader.py | Missing module collection error, exit 2 |
| t4-01-green | tests/agents/slo_agent/orchestrator/test_context_reader.py tests/tui/test_workflow_visualizer_loader.py | 81 passed, exit 0 |
| t4-02-red | tests/tui/test_workflow_visualizer_loader.py | delegation assertion: 1 failed, 68 passed, exit 1 |
| t4-02-green | tests/agents/slo_agent/orchestrator/test_context_reader.py tests/tui/test_workflow_visualizer_loader.py | 82 passed, exit 0 |
| t4-03-red | tests/agents/slo_agent/herdr/test_visualizer.py | Missing module collection error, exit 2 |
| t4-03-green | tests/agents/slo_agent/herdr/test_visualizer.py tests/agents/slo_agent/orchestrator/test_context_reader.py tests/tui/test_workflow_visualizer_loader.py | 105 passed, exit 0 |
| t4-04-red | tests/agents/slo_agent/herdr/test_visualizer.py | Missing constructor/command behavior, exit 1 |
| t4-04-green | tests/agents/slo_agent/herdr/test_visualizer.py tests/agents/slo_agent/herdr/test_viewer_authority_closure.py | 109 passed, exit 0 |

Increments were reader (~32 lines), loader delegate, parser (~45 lines),
constructor/builder (~50 lines), each tested before the next. Final Black formatting
command lists exactly the six changed source/test files in t4-format.log; no
post-format test or Black-check gate is claimed. `dpkg -V coreutils` silent,
exit 0 (`t4-coreutils`). Full suite/lint/package were NOT run in this partial lane.
Prior 301 errors/64 files baseline remains unwaived and is not a fresh result.

## Remaining mandatory T4 work

1. Pending shared shielded task registry, identity-only done cleanup and exception
   retrieval; immutable reservation/reuse outcomes; invoke and cancellation-resistant
   close joining only owned viewer work, never closing shared transport or panes.
2. HerdrViewerAdmission and split/rename/run core, current object/op ledger and live
   bound reporter authority under actual shared transport lock; retain unknown/known
   effects across errors, timeouts, suppression and cancellation.
3. Full matrices including simultaneous waiters, repeated cancellation, malformed/
   oversized output, exact argv bounds, new versus admitted revocation, real sequence
   failure/fsync/overflow, queued split/rename/run and actual G2 opposite contention.
4. Real registered fake executable composition, surrounding/package gates, changed
   Black check, lint delta and full integration gates after both T3/T4 lanes.
5. Complete remaining prerequisite reads: entire B/C relevant lifetime sections,
   overview/legacy integration/publication contracts and accepted review decisions;
   recover truncated skill reads and full Textual recipe before broader claims.

Read D in full, exact D04–D07 task attachment (2109–2400), T4 requirements,
T2-38/T2-37 handoffs, routing and scope-plan excerpts, root RESEARCH, supplied
AGENTS/CLAUDE/docs RESEARCH, actual identity/DAO/layout/loader/transport join and
reporter authority tests, KB Welcome/README/gotchas. Shared engineering/coding,
Python root/style/declarative, exact workflow/shared SKILL loaded; combined
DAO/service read truncated and Textual read partial. No claim of complete required
context ingestion. No new shared-change need established; session eligibility and
app integration remain exclusively T5. T5 must wait: this lane is INCOMPLETE.
