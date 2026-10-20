# T4 continuation 29 — INCOMPLETE

Entire-T4 technical READY is **withheld**. This continuation closes a cohesive
viewer lifetime test family, not all T4 acceptance. T5 assembly remains untouched.
Same unfinished turn 1: started 1, completed 0, historical partial 1, dispatch 29,
retries 0. Unlimited workflow turns AND dispatches supersede old numeric limits.
No agents dispatched, commits, external/spec/global/other-worktree changes.

## Changes

- `src/agents/slo_agent/herdr/visualizer.py`: construct the typed outcome directly
  from the conditional literal rather than widening through a `str` local.
  No runtime behavior change, no ignore/Any/cast.
- `tests/agents/slo_agent/herdr/test_visualizer.py`: type the command expectation
  map with `HerdrViewerOperation` and failure input with `HerdrCommandStatus`.
- New `tests/agents/slo_agent/herdr/test_visualizer_lifetime_acceptance.py`:
  39 parameterized cases, actual registered regular executable, real transport,
  deterministic barriers, temp-owned sequence store and real atomic writer.
  Ordinary-exception cases inject only the escaping exception at invoke; earlier
  operations still use the real executable. Authority facts use the existing
  independent predicate fixture, not a claim of real activation/lease acquisition.

The three typing errors identified in t3-cli-28 are absent in fresh lint. Reader
and loader have no diagnostics in that receipt. Whole-project lint remains
**unwaived failure: 300 errors / 64 files**, not green. Concurrent disjoint work
means the global count delta is not attributable solely to these three fixes.

## Finite branch/requirement map

| Row | Evidence and exact remaining boundary |
|---|---|
| Split JSON envelope/type/controls/byte bounds/failure | Existing `test_visualizer.py` parser matrix, fresh package PASS |
| Exact split/rename/run argv | Existing `test_viewer_commands`, fresh package PASS |
| Invalid builder identity / missing pane | NOT directly tested; add negative builder tests |
| Public valid/nonzero/oversized retained outcomes | Existing 28 `test_public_retained_outcome`, retained unchanged, package PASS |
| Public malformed split | Existing lifecycle simultaneous empty-output path PASS; exhaustive malformed envelope remains pure parser coverage, not every variant public |
| Split/rename/run timeout | NEW `test_public_timeout_retains_effect`, 3 PASS; real deadline/reap, rename timeout continues run, split/run fail, repeat adds no commands |
| Ordinary exception split/rename/run | NEW `test_ordinary_exception_retains_manual_recovery`, 3 PASS; later commands absent, known ID preserved, public result excludes injected sentinel |
| Shared waiters / identity callback / error retrieval | Existing 28 tests preserved, package PASS |
| Queued live revocation | Existing lifecycle 7 authority facts × split/rename/run = 21 PASS |
| Already admitted versus new request | NEW `test_admitted_effect_survives_but_new_request_is_refused`, 7 facts × 3 operations = 21 PASS; original task survives, new invoke refused, later operations suppressed, consumed ledger retained, executable prefix exact |
| Real unsafe sequence revokes queued viewer | NEW `test_real_sequence_failure_revokes_queued_viewer`, 3 failures × 3 operations = 9 PASS; actual file-fsync precommit failure, directory-fsync warning, overflow; reporter reservation disables authority, transport remains open, zero executable entry |
| Actual write syscall failure | NOT covered separately: the case named `write` injects file fsync before replacement, not `tmp.write` failure. Do not claim a literal write syscall failure |
| Close repeated cancellation / multiple parents / known-pane cancel | NEW `test_repeated_close_cancellation_joins_all_parents`, split/rename/run = 3 PASS; real child plus queued second parent, delayed real reap, three outer cancellations, shared close task retained, all registry work drained, transport left open, panes never closed |
| Admission complete guards | Successful completion exercised through transport; explicit never-admitted and repeated complete callback branch assertions still missing |
| Public actual viewer G2 A/B same/changed generation | Existing 28 test preserved, package PASS; not rewritten |
| G2 public viewer close/cancel/timeout variants | Still missing; do not substitute the new close/timeout tests (they contain no queued reporter A/B) |
| Already-admitted reporter A accounting with public viewer | Existing reporter composition proof is not newly composed with public viewer; still missing that exact composition |
| Reader missing/invalid/OS/slug/UUID/privacy and loader delegation | Existing tests unchanged, fresh package PASS |
| Complete prerequisite ingestion | Still incomplete; exact read audit below |

No focus, query, pane-close, retry, source fallback, or caller assembly was added.
Submitted remains queue admission, never paint/process-start evidence.

## Exact verification receipts

CWD `/root/Code/slo-94-herdr-integration/slo`.
`pyenv which python` = `/root/.pyenv/versions/slo-harness/bin/python`,
Python 3.11.7, `make test-env` = fallback. No environment creation/install.
P = `bash docs/implementation/94-herdr/t1-dao-check.sh`; its existing safe fallback
and suite guards strip HERDR, disable integration and terminals, isolate state.
Each prefix below has full `.log` and `.exit` in this directory.

| Prefix | Command after P | Result |
|---|---|---|
| t4-29-types | tests/agents/slo_agent/herdr/test_visualizer.py tests/agents/slo_agent/herdr/test_visualizer_lifecycle.py tests/agents/slo_agent/herdr/test_visualizer_acceptance.py | 130 passed, 2 warnings, exit 0 |
| t4-29-timeout | tests/agents/slo_agent/herdr/test_visualizer_lifetime_acceptance.py tests/agents/slo_agent/herdr/test_visualizer_lifecycle.py | 98 passed, 2 warnings, exit 0 |
| t4-29-authority | same two files | 119 passed, 2 warnings, exit 0 |
| t4-29-sequence | same two files | 128 passed, 2 warnings, exit 0 |
| t4-29-close | same two files | 2 failed, 129 passed, exit 1: test barrier incorrectly delayed successful earlier commands |
| t4-29-close-corrected | same two files | 131 passed, 2 warnings, exit 0 |
| t4-29-exception | same two files | 134 passed, 2 warnings, exit 0 |
| t4-29-package | tests/agents/slo_agent/herdr tests/agents/slo_agent/orchestrator/test_context_reader.py tests/tui/test_workflow_visualizer_loader.py | 972 passed, 4 warnings, exit 0, 59.66s |

These are initial passes for existing correct behavior, **not production RED/GREEN**.
The close failure was a test defect, fixed by delaying only a child whose returncode
is None; original failing receipt preserved. Type-only fixes used the reported
static failures as their initial evidence. No assertion weakened or test skipped.
Package count includes concurrent disjoint lane additions.

`poetry run black` formatted only visualizer.py, test_visualizer.py and the new
lifetime file (`t4-29-format.log`). `t4-29-black` runs `poetry run black --check`
on visualizer.py, context_reader.py, workflow_visualizer_loader.py, all
`tests/agents/slo_agent/herdr/test_visualizer*.py`, test_context_reader.py and
 test_workflow_visualizer_loader.py; exit 0.
`t4-29-lint`: `poetry run mypy src/ tests/`, exit 1, 300 errors/64 files,
743 source files checked. No viewer/context-reader/loader diagnostic.
`t4-29-diff`: `git diff --check`, exit 0.
`t4-29-coreutils`: `dpkg -V coreutils`, empty output, exit 0.
Full integrated make is NOT run; user places it after T3 and T4 READY.

## Read audit and remaining work

Read actual AGENTS.md completely in two chunks, CLAUDE.md, root RESEARCH,
docs/RESEARCH.md completely, Makefile, pyproject test/static declarations,
routing.md, scope-plan.md (recovered truncated beginning), prior T4 receipts,
KB Welcome/slo README/gotchas; full current D and tasks 2109–2400.
Loaded shared engineering routing/testing/ownership, coding-rules/code-test-loop,
Python root/declarative/style, full application-service recipe, exact workflow
and shared workflow SKILL. Inspected actual viewer/tests, reader/tests,
transport admission/cleanup, sequence reserve and reporter reservation seam,
fake capability identity guard. One malformed parallel read call read nothing.

Still NOT reread this continuation: full generic declarative, DAO recipe,
Textual recipe, relevant complete B/C authority/retained-drain sections, accepted
review, overview and legacy publication contracts. Historical reads are recorded
in earlier receipts but are not a complete-ingestion claim here. Those reads and
the explicitly missing rows above remain required before entire-T4 READY.
No independent review/completion, supported-release Herdr or live paint claim.
