# T5 continuation 79 — INIT ownership proofs closed; finite audit INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 79 (user supplied), retries 0. Unlimited turns and dispatches;
no agents dispatched. No commits, pushes, external/global/live/spec edits.

## Changes and proof results

Only `src/tui/app.py`, `tests/tui/test_herdr_init_ownership.py` and
`tests/tui/test_herdr_init_rollback.py` changed, plus local receipts.

1. Timer-slot-only displacement: expanded the actual mounted registration test
   across inbox return, first registration and second registration, with unchanged
   owner as well as changed owner. No artificial inbox exception in these cases.
   Successor pair identity, exact stopped handles, disabled delivery and actual
   captured lease removal are asserted. Existing production guards pass.
2. Direct preparation cancellation: mounted app, explicit catalog boundary Event,
   cancellation of `_prepare_mounted_session` propagates the original cancellation;
   no notice/title/usage paint, same live delivery timers and actual lease.
   This is catalog preparation, NOT direct cancellation of the private delivery
   initializer. C7.13 explicitly forbids direct cancellation of delivery init;
   public mount cancellation joins its retained owner (existing threaded proof).
3. Combined displaced failed handles and successor pair: same matrix injects failed
   stops of init-created handles, asserts exact strong tuple retention (<=2),
   no additional construction on repeat init, preserved successor slots, then
   exact union of retained+successor handles on successful global retry and empty
   final slots. Existing production behavior passes; no fabricated RED claimed.

Canonical C7.14 additionally exposed a concrete unmet F4 row: preparing notice
failure prevented task registration. New test failed before production change
(`t5-79-notice-red`: 1 failed, 102 passed, exit 1). Three call-site changes use
existing best-effort lifecycle notices for preparing/failure/ready. No new owner,
catch-BaseException, ignore or suppression. Surrounding GREEN: 397 passed.

## Finite whole INIT map (not whole T5)

| Branch / boundary | Evidence / disposition |
|---|---|
| Existing timer slots | duplicate initialization identity test; new repeated-displacement assertion |
| Unsafe delivery | sticky false path exercised through setup/stop/release failures and subsequent init |
| Absent history / inert construction | existing app suite; needs explicit row-to-test citation before audit closure |
| Construction failure | ownership `test_initialization_fault_is_contained[build]` |
| Reconcile/acquire failures | same test `[reconcile,acquire]` |
| Missing acquisition store | `test_missing_lease_store_refuses_acquisition` |
| Returned lease session/owner mismatch | actual persisted foreign-result matrix |
| Reconcile/acquire/inbox continuation identity | 21 cases: owner, scalar session ID, store, inbox, service, renderer, session object |
| Captured absent/existing lease store | successor-store preservation tests |
| Inbox exception | rollback mounted setup failure |
| First/second timer registration exception or closing | rollback five-case matrix |
| Timer slot-only displacement | new unchanged-owner three-phase cases |
| Failed init stop + displaced successor pair | new combined matrix, exact tuple and later retry |
| Unrelated retained handle | existing subset success/failure tests |
| Stop/lease/notice combinations | existing 3x3 rollback cases |
| Post-release collaborator displacement | actual release barrier preserves successor service/renderer |
| Repeated cancellation during real acquire/release thread | existing ownership tests join actual operation and preserve first release cancellation |
| Direct catalog preparation cancellation | new Event test, no paints or delivery teardown |
| Optional initial preparing notice failure | new RED/GREEN; existing lifecycle notice seam |
| Mount startup notice/usage fault | existing optional-fault cases |
| Late hydration/usage/preparation completion | shutdown continuation tests |
| Replacement ordering | release → close → clear → initialize test |
| Public unmount/replacement gate order | shutdown and initialization suites |
| Exact mount phase order and every ready/pending/no-history branch citation | remaining finite audit item, not activation implementation |

## Canonical phase order and next family

C7.9/C7.13 and task samples C13/C14/C25/C26:
- Mount: hydrate → optional startup notice → subscribe → register retained mount
  runtime under submission gate → delivery setup → reporting activation → usage
  refresh → pending catalog preparation → focus/auth, with captured identity and
  monotonic-closing checks around continuations.
- Replacement: prepare candidate without mutation → revoke old reporting → cancel
  old preparation/viewers → stop old timers/release captured old lease → close old
  reporting → retain/suppress/adopt synchronously → reset UI → same runtime chain.
- Delivery: inert construction/capture → reconcile/check → acquire/check/result
  identity → inbox/check → first timer/check → second timer/check → reopen.
  Failure stops only owned handles, releases captured lease and clears only captured
  collaborators; shutdown never reopens. Retained mount/commit owns cancellation.

Current `_finish_replacement_runtime` has delivery → title/usage → preparation;
**actual `start_external_reporting(interactive=True)` is NEXT activation family**,
not a hidden requirement to implement all T5 before INIT can be ready. Viewer
registry/drain and inbox claim/ack/final-registration matrices likewise remain
separate T5 families. This receipt does not assert their implementation.
The current title refresh precedes context refresh, unlike canonical C14; exact
phase reconciliation remains an explicit audit item rather than a claimed match.

## Actual read audit this continuation

Frozen `routing.md` and `scope-plan.md` reused unchanged; no fresh routing exercise.
Read actual AGENTS 1–1013 (three bounded reads), CLAUDE 1–65, root RESEARCH 1–41,
docs/RESEARCH 1–633 (two bounded reads), complete engineering routing/testing/
ownership, coding rules/cadence, shared declarative (two chunks), Python root and
declarative, full Textual (three chunks), full Faux recipe (two chunks), workflow
SKILL, KB Welcome and slo README/conventions/gotchas. One combined read truncated;
its omitted beginning was recovered from the tool spill, not counted unseen.
Read canonical C7.9–7.14 through the lifetime mapping (605–2113), exact T5 samples
2401–3720 in four bounded reads, and accepted turn-4 review through line 180.
Read actual delivery construction/preparation/publication/rollback/stop/release,
mount/preparation/shutdown/replacement runtime methods, ownership and rollback tests,
initialization test, shutdown continuation test and Makefile/isolation fixture prefix.

Finite remaining read/audit rows: accepted review tail after line 180; workflow
code-test-review file; Python named-argument/docstring recipe; complete affected
shutdown/replacement/session-lifecycle tests and their final canonical phase/branch
citation map. These are explicit missing rows, not an indefinite whole-family audit.
No claim all required reads were completed before editing: they were not.

## Commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Every Python command used
`PYENV_VERSION=slo-harness`; no venv created. Focus/surrounding use
`bash docs/implementation/94-herdr/t1-dao-check.sh <tests>` (adds 62 foundation tests).
Focus: both init ownership and rollback files. Surrounding adds initialization,
app_shutdown, replacement, session_lifecycle, test_app and authentication directory.
All logs and `.exit` files are `t5-79-<name>` alongside this report.

| Name | Result |
|---|---|
| slots | 87 passed, exit 0 |
| retention | 93 passed, exit 0 |
| focus | 133 passed, exit 0 |
| surrounding (before notice fix) | 396 passed, 1 deselected, exit 0 |
| notice-red | 1 failed, 102 passed, exit 1 |
| notice-green (full surrounding) | 397 passed, 1 deselected, 31 warnings, exit 0 |
| test (before notice fix) | 7882 passed, 19 deselected, exit 0 |
| test-final | 1 failed, 7882 passed, 19 deselected, exit 2 |
| selection-isolated | failing case + 62 foundation tests: 63 passed, exit 0 |
| test-confirm (same final code) | 7883 passed, 19 deselected, 556 warnings, 660.56s, exit 0 |
| smoke-final | 288 passed, 2 warnings, exit 0 |
| lint-final | 299 errors/63 files, exit 2, UNWAIVED |
| lint-normalized | file/message diagnostics normalized only for line numbers equal 78, empty diff, exit 0 |
| black-final | app and two edited tests, exit 0 |
| diff-final | git diff --check, silent, exit 0 |
| coreutils-confirm | dpkg -V coreutils, silent, exit 0 |

Retained full-gate failure: `test_selection_scroll_highlight... [slo-default-thinking]`
raised `AssertionError: offset Offset(x=6, y=0) was not visible` at line 54, called
from line 159. It passed isolated and on fresh full rerun. No causal fix or waiver
claimed, no assertion weakened, no out-of-scope selection edit. Earlier pass does
not erase this receipt. Full outputs retain all warnings.

Verdict: three requested proof additions PASS; INITOWNERSHIP READY withheld only
for the finite audit/phase rows explicitly above. No full T5 completion claim.
