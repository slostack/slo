# T2 dispatch 19 handoff — INCOMPLETE

This is an implementation-worker receipt, not independent Review or Completion.
T2 dependency handoff is **not READY**. No production files were changed by this
worker. Twenty additional behavioral cases pass; they close bounded gaps rather
than the complete requested ledger. Handoff is due to this execution context's
remaining capacity, **not** a dispatch/turn budget, static-debt prohibition, or
technical host blocker. Continue substantive T2 work; do not start T3/T4 on this
receipt alone.

## Authority and preservation

User override: unlimited workflow turns AND unlimited per-turn dispatch calls.
Parent-owned counts: turn 1, started 1/completed 0/historical partial 1,
dispatch 19 (18 previously consumed), retries 0. No nested agent calls.
Older capacity-stop paragraphs are historical, not active instructions.
Branch feature-94-herdr-integration; HEAD d0e3a756689f2675e5507034d43cd8b272d3c6b8.
All prior tracked/untracked work retained; no reset/clean/stash/worktree/commit,
global, canonical-specification, other-worktree, provider, live Herdr or terminal
operations. Live compatibility remains unverified and separately authorized.

Effective SLO_SKILLS_DIR remains the installed pipx skills directory. Frozen
routing and scope-plan hashes still match ca705057a4b22709de4873be158b3c7117be0c84cf51770969c78022d9cc0bb7
and c0c3e1ec1708bc7aefe93881389c8e8921f26b334103aac9730ed4585dd562c5.
No source-tier/environment override was made. This continuation consulted the
committed shared engineering/coding/Python style/DAO/service/testing guidance,
workflow definitions, KB entry/Slo README/gotchas, root memory, supplied project
context and actual reporter/transport/test owners. It read overview and exact T2
attachments 446–1905 and B's final ledger/corrections. **It did not complete the
requested fresh full ingestion of every B/C/D/source/evidence document, every
routed skill or current docs/RESEARCH.md from disk.** Prior ingestion receipts
are not represented as fresh reads here. Finish that prerequisite before claiming
full-scope closure; this is an explicit cadence/context limitation.

## Requirement → new evidence

All paths below are under tests/agents/slo_agent/herdr/.

| Requirement | Test / bounded proof |
|---|---|
| Explicit C argv boundaries | test_resume_bounds.py: 64/65 arguments and 8192/8193 UTF-8 bytes, ASCII/multibyte, separators counted. Six added cases; helper validation, not T3 loader proof |
| B7.11 worker wake | test_worker_wake.py: empty/new/busy_replaced/adoption_wake/close. Actual worker with recording consume boundary; newest slot, no duplicate batch, empty-worker revocation wake. Not complete save/rename integration |
| Activation lifetime | test_activation_lifetime.py: repeat/contention/reject/timeout/cancel, real sequence lease and guarded executable. One release at most; no claims; local failures drain; repeated start retains task |
| Close-during-start | same file: held real off-loop acquire + repeated close cancellation; close stays pending, no executable entry after revocation, task joined, lease released only through sealed transport |
| Independent holder timeout | test_independent_lock_holder.py: actual guarded split child holds shared transport primitive without reporter deadline; queued reporter times out while holder remains alive/locked/owned; no claim entry, holder then completes and fresh claim succeeds. Deliberately not actual T4 viewer adapter |
| B7.13/C retained cleanup | test_retained_transport_composition.py: actual child/transport/lease with two injected reap failures; real competing lease remains refused; final local drain ordinary/repeated caller cancellation joins and releases lease, sticky uncertainty, exactly one callback and no remote retry. Not persistent kernel-reap certification |

No production unit changed, so no behavioral RED was manufactured. Each bounded
test addition was run before the next test family. All initially passed; Black
formatting preceded package/full/static gates. One failed exact-text edit attempt
made no change. No assertions were weakened or tests skipped.

## Fresh verification

CWD is the assigned checkout. pyenv which python:
/root/.pyenv/versions/slo-harness/bin/python; Python 3.11.7. make test-env:
fallback. Targeted prefix unchanged:
`bash docs/implementation/94-herdr/t1-dao-check.sh` (reviewed exact safe exports;
includes 62 DAO/projection tests, so focused totals are not new-test counts).

| Suffix / command | Receipt prefix | Result |
|---|---|---|
| tests/agents/slo_agent/herdr/test_resume_bounds.py | t2-32-bounds | 72 passed; exit 0 |
| tests/agents/slo_agent/herdr/test_independent_lock_holder.py | t2-32-lock | 63 passed; exit 0 |
| tests/agents/slo_agent/herdr/test_worker_wake.py | t2-32-worker | 67 passed; exit 0 |
| tests/agents/slo_agent/herdr/test_activation_lifetime.py (first five) | t2-32-activation | 67 passed; exit 0 |
| same, plus acquire/close | t2-32-acquire | 68 passed; exit 0 |
| tests/agents/slo_agent/herdr/test_retained_transport_composition.py | t2-32-retained | 64 passed; exit 0 |
| tests/agents/slo_agent/herdr | t2-32-herdr | 519 passed, 4 warnings, 24.83s; exit 0 |
| make test | t2-32-full | 6847 passed, 19 deselected, 407 warnings, 515.59s; exit 0 |
| make smoke | t2-32-smoke | 285 passed, 2 warnings, 2.85s; exit 0 |
| make lint | t2-32-lint | 301 errors/64 files, 718 checked; exit 2 |
| exact error-line diff vs t2-31-lint-final.log | t2-32-lint-baseline.diff | empty; baseline UNWAIVED |
| Black changed Python scope | t2-32-black | 41 unchanged; exit 0 |
| dpkg -V coreutils | t2-32-coreutils | silent; exit 0 |
| git diff --check | t2-32-diff-check | silent; exit 0 |

Matching .log/.exit files retain output/results. Black exact scope:
`poetry run black --check src/agents/slo_agent/herdr src/agents/slo_agent/sessions/{dao,identity,token_format}.py src/cli/headless_request.py src/tui/widgets/usage_status_bar.py tests/conftest.py tests/state_isolation.py tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session_identity.py tests/agents/slo_agent/test_token_format.py`.
Formatting command used only the five newly changed test files. No source edits
followed final gates. Full chapter regression lists and chapter Black fences were
not separately rerun; make test covers existing non-E2E tests but does not prove
absent T3/T4/T5/T6 tests or replace those future gates.

## Exact remaining ledger

Retain all earlier Partial qualifications except the bounded additions above:

1. Actual rename continuation, full changed-capture save/batch flow and worker
   adoption integration (recording worker proof is not those compositions).
2. Unsafe/corrupt-counter activation; close with pending save/worker and full
   repeated-cancel/ordinary-error combinations; reservation expiry composition.
3. Complete binding/confirmed-policy matrices, nonmatching/stale release,
   partial/final display acknowledgements, definitive spawn failure with and
   without prior binding, including claim-after-uncertain-install.
4. Shutdown budget expiry during durable reservation, release timeout and first
   clear failure, stale-between-patches actual executable evidence; timer's real
   two-second wake (existing batch-refresh proof does not establish timer).
5. Persistent final real transport/lease cleanup failure variants and lease-close
   faults; new successful late-drain composition is not the complete matrix.
6. Diagnostic cross-build policy/recovery/sink/suppression/cancellation matrix.
   Source currently logs gate configuration failures each build; compare this
   against B's 60-second category policy before declaring it closed.
7. Complete section-8 privacy/projection audit and named helper coverage ledger.
   Exact argv boundary and independent holder deadline gaps are now proved as
   described, not live compatibility or actual viewer routing.
8. Complete required fresh source/routing ingestion, task/chapter regressions,
   chapter Black fences, final scope review and updated requirements map.

T3/T4/T5/T6 remain unstarted here. Whole-feature lint remains failing/unwaived;
it does not prohibit finishing T2 safely. Independent full-scope Review and fresh
Completion remain parent-owned later phases, not performed by this worker.
