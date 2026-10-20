# T6 mounted journey and cutoff matrix — INCOMPLETE

## Scope and accounting

Bounded lane: new `tests/integration/test_herdr_full_flow.py` and optional
`tests/integration/herdr_*` helpers, plus this receipt and its verification
receipts. No production edits, shared-status edits, two-process worker edits,
canonical-specification edits, agents, commits or external delivery performed.

User-supplied accounting retained: unfinished turn 1; started 1; completed 0;
historical partial 1; dispatch 121; retries 0. Unlimited turns and dispatches.
This session has not completed a workflow turn or independent review.

## Work actually performed

Read-only inventory confirmed substantial pre-existing T1–T5 changes. Those
changes were not altered. Read `scope-plan.md` (opening through T6 allocation),
full `routing.md`, and full `t5-final-handoff-120.md`. Read the canonical tasks
attachment lines 3721–3816 and C lines 2100–2175, including the exact lifetime
matrix semantics and sections 8–10. Inspected the existing mounted activation
and attached-viewer composed tests as potential boundary references. Read shared
engineering routing/ownership/testing, Python gateway, coding rules and test-loop
skills, and the KB Welcome opening. This is **not** full prerequisite ingestion:
remaining requested specification/review, skill and KB reads are outstanding.

The supplied T5 handoff reports 8213 passed and the unwaived 295-error/60-file
static baseline. These were read as prior receipts, **not rerun or independently
verified here**.

## Canonical matrix boundary identified

C requires `test_lifetime_cutoff_matrix`, 64 meaningful cases:

- Stops: runtime disable, session close, new, unmount.
- Phases: queued report, admitted report, queued viewer, admitted viewer,
  precommit platform, committed platform, queued capture, running save.
- Diagnostics: healthy, raising.

Runtime disable must arise after activation from sequence/authority failure;
it is not an environment toggle. Queued work must not spawn after revocation;
admitted work joins and accounts old effects without follow-up. Platform
precommit/committed behavior must distinguish app lifetime from reporter
lifetime. Running save joins without adoption, leaving only an immutable orphan.
G1/G2 and all-owner quarantine proofs remain separate obligations. No reduced
matrix or repeated predicate loop was written or counted as acceptance.

## Missing deliverables and verification

No integration test or helper was created in this session. No new test was
collected or run. No production defect was reproduced; no RED production report
is available. Tool-schema failures during attempted parallel reads were read-call
errors, not product/test failures.

Still outstanding in this lane:

1. Complete mandatory context ingestion and inspect current production owners.
2. Actual PromptInput/Faux/tool/retry/pool journey through idle, rename, model,
   new and both typed viewer entry paths with exact real fake-CLI argv.
3. Disabled/outside event/history parity with timestamp-only normalization and
   zero integration writes/spawns.
4. Four-provider synthetic-secret/private-path public-channel scanning, private
   store-only capture assertions, context/cooldown clearing and stale handling.
5. All 64 canonical composed lifetime cases, with meaningful owner barriers and
   independent G1/G2/quarantine retention evidence.
6. Incremental targeted/surrounding runs, owned Black/mypy checks, diff and silent
   coreutils verification; final shared full gate only after all lanes finish.

The separate two-OS-process restore lane was not touched. Live Herdr 0.9.2,
server restart and pane paint were neither authorized nor exercised. No live or
mock compatibility claim is made.

**Verdict: INCOMPLETE — prerequisite inspection only; zero new executable T6
acceptance evidence.** This receipt is not T6 READY, review approval or completion.
