# T5 continuation 78 — INITOWNERSHIP INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 78 (user-supplied), retries 0. Unlimited turns and dispatches.
77 was read-only, normally completed after API interruption, not aborted.
No agents, commits, pushes, external/global/live/specification or other-worktree edits.

## Implemented, with RED before production

Two confirmed defects reproduced together in `t5-78-red.log`: **3 failed,
113 passed**, exit 1.

1. A mounted initializer captured `lease_store=None`; reconcile installed a real
   successor store with an existing same-owner lease. Old rollback incorrectly
   deleted that successor lease. `_release_captured_session_lease` now requires
   explicit typed store/ID/owner arguments: None means no store, never fallback.
   `_release_replaced_session_lease` separately captures current ownership for
   replacement/global teardown. Initialization rollback chooses its immutable
   binding when present. No Any or unchecked sentinel added.
2. Init-only timer cleanup retried a prior retained handle. Explicit timer input
   now stops only that subset and carries unrelated retained failures forward.
   Omitted input still retries all retained failures plus current slots. Tests
   cover new stop success and failure, retained identities and later global retry.

Production increment stayed below approximately 50 added lines before green.
First surrounding gate: **379 passed, 1 deselected**, exit 0.

## Remaining barrier evidence added

The existing real-operation continuation matrix now includes renderer displacement
and actual session-object replacement at reconcile/acquire/inbox: six additional
cases. A seventh test blocks after real lease release, publishes successor service
and renderer, then proves rollback preserves both references. These tests exercise
existing guards, so no additional production correction was needed.

First barrier invocation exceeded its 180-second tool timeout. It stalled because
the test assumed a lazily constructed renderer already existed; an observer assertion
prevented barrier release. This was a test-fixture error, not evidence of a production
deadlock. Both relevant fixtures now explicitly construct the existing renderer
before capture. Original partial log is retained as `t5-78-barriers.log` (no shell
exit receipt was produced because the tool timed out). Corrected run:
**123 passed**, exit 0, `t5-78-barriers-fixed.log`.

## Finite branch map

| Obligation | Evidence/status |
|---|---|
| Explicit captured absent store versus current store | New mounted RED/GREEN |
| Explicit captured existing store versus successor | Existing regression retained |
| Init subset excludes old retained handles, retains failure references | Two new RED/GREEN cases |
| Global teardown retries retained/current handles | New assertions plus existing rollback suite |
| Owner/scalar ID/store/inbox/service/renderer/session across three awaits | 21-case mounted matrix passes |
| Returned lease mismatch, duplicate init, construction faults | Existing cases preserved |
| Repeated cancellation joins actual release/acquire threads | Existing cases preserved |
| Post-release successor service/renderer preservation | New real-store barrier passes |
| Stop/lease/notice failure combinations | Existing nine-case matrix preserved |
| Replacement phase ordering and shared mount/runtime seam | Existing tests preserved |
| Timer-slot-only displacement at publication with unchanged owner | Full explicit matrix still not established |
| Direct preparation cancellation versus public retained mount cancellation | Direct case still unproved; public cases preserved |
| Combined displaced failed init handles plus successor pair, strong retention bound | Existing partial evidence; complete combined case still unproved |
| Canonical phase/read closure | Incomplete; see below |

No activation, inbox-next-family or viewer requirement is added to INITOWNERSHIP.
Those remain later T5 families. No READYINITOWNERSHIP claim.

## Commands and final receipts

CWD `/root/Code/slo-94-herdr-integration/slo`.
Pytest commands used `PYENV_VERSION=slo-harness bash
docs/implementation/94-herdr/t1-dao-check.sh <suffix>` (approved existing 3.11.7
fallback, no environment created). Helper adds 62 foundation cases.

Focus suffix: `tests/tui/test_herdr_init_ownership.py tests/tui/test_herdr_init_rollback.py`.
Surrounding suffix adds `tests/tui/test_herdr_initialization.py
 tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_replacement.py
 tests/tui/test_herdr_session_lifecycle.py tests/tui/test_app.py tests/tui/authentication`.

| Receipt prefix `t5-78-` | Result |
|---|---|
| red | 3 failed, 113 passed; exit 1 |
| green | 379 passed, 1 deselected; exit 0 |
| barriers-fixed | 123 passed; exit 0 |
| final-surrounding | 386 passed, 1 deselected, 31 warnings, 197.40s; exit 0 |
| black / black-check | Three edited Python files; exits 0 |
| diff | `git diff --check`; silent, exit 0 |
| coreutils | `dpkg -V coreutils`; silent, exit 0 |
| lint | `PYENV_VERSION=slo-harness make lint`; 299 errors/63 files, exit 2 |
| lint-normalized | Sorted file/message diagnostics with line numbers removed match 76 exactly; empty diff, exit 0 |

Lint remains UNWAIVED. No ignore or suppression added. Full make test/smoke not
run: finite family/read closure is not yet complete. Final surrounding includes
all prior 376 cases plus ten new cases. Existing historical receipts unchanged.

## Read closure limitations

Read actual initialization, rollback, timer and release helpers and both ownership
and rollback test portions; current routing/scope plan; shared engineering routing,
testing and ownership; coding rules/cadence; Python root/declarative; KB entry,
slo README/gotchas/conventions; portions of Textual/Faux/workflow guidance; canonical
C7.13 initialization and C7.14 mapping. Supplied AGENTS/CLAUDE/docs RESEARCH context
was available, but a complete fresh on-disk read of those files and root RESEARCH
was not finished. Two oversized combined reads truncated; their missing beginnings
were not completely recovered. Complete Textual/Faux guidance, exact T5 attachment,
accepted review, KB build rules, affected source/test closure and complete canonical
C7.9–7.14 phase audit remain unfinished. This receipt does not represent those as
completed or silently inherit 76's read claims as new evidence.
