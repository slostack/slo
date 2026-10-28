# T5 inbox matrix 91 — INCOMPLETE (bounded tests green)

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 91, retries 0. User turn/dispatch limits unlimited. No agents launched. No full-scope readiness or independent approval claim.

## Write scope

Added only `tests/tui/test_herdr_inbox_disposition.py` plus this report and `t5-91-*` receipts. No app, existing tests, shared status, canonical specs, KB, global settings or other worktree edits. No commit/push/PR/reset/clean/stash. Existing parallel changes preserved. One temporary context concatenation was written to `/tmp/slo91-context-read.txt`; it is not a repository deliverable or a read-completion claim.

## Finite branch evidence

20 new mounted cases use config-backed real SloAgentSession, a patched LLM factory returning Faux, real temp-root SessionInboxStore and the original app poll/handler/registration path. Test suite isolation supplies disabled Herdr and terminal guards. No executable or symlink created. Message files are checked regular, resolved-contained, unique, byte-identical across lanes.

| Contract | Evidence / limitation |
|---|---|
| empty, closed_entry, claim_error | No ack/invoke; no file for empty, unchanged pending file otherwise |
| advance_error, handler_cancel | Exception/cancellation propagated; unchanged claimed bytes; no ack/invoke |
| chat_open, notice_open, note_open, context_open | Original real handlers; exact invoke/ack counts, output prefix/text, no echo/queue; successful real ack moves unchanged bytes to done |
| ack_false, ack_error | One admitted execution, claimed retention, pending-only fresh store cannot reclaim; errors not hidden |
| context_pending_at_close | Real history writer held before persistence, public unmount prefix, successful captured-store ack and duplicate message ID refused by real persistence |
| durable workflow advancement then close | Real `running → completed` WorkflowHandleStore write through app service; barrier after advance; no invoke/ack, claimed bytes retained, fresh store no reclaim, completed handle unchanged |
| throwing refusal notice | Same durable case, adapter diagnostic sink raises; poll/shutdown complete and durable disposition unchanged |
| already_registered / ack_pending_at_close | Four cases: normal/operator interrupt × unchanged/replaced app store reference. Exact registered task survives closing prefix, zero shutdown abort/cancel, original ack gets captured ID, real Faux execution once, done bytes unchanged, no queue/reclaim, replacement store never created |
| displaced captured session | Displacement after real claim or real advance; neither old nor new session invoked, no ack, original claimed bytes retained |
| earlier cutoffs | Existing `test_herdr_inbox_cutoffs.py` claim/advance/registration and local-echo cases reused unchanged in surrounding gate; its advance case is supplemented by actual durable test above |

Abort qualification: the new operator-interrupt variant requests abort while the already-registered coroutine is held before `_run_prompt`; it proves existing interrupt invocation and no shutdown-issued abort, not all mid-stream abort/escalation branches.

## Initial failure classification

`t5-91-cutoffs.log`: **2 failed, 75 passed**. Both were fixture errors: initial handle was `launching`, for which ordinary `completed` transition is illegal. The real service correctly retained launching. Changed only fixture initial state to running; retained exact completed-state assertion. Corrected receipt: **77 passed**. This is NOT behavioral RED, and no production defect was demonstrated. No assertion relaxed, skip or xfail added.

## Exact commands and receipts

Working directory `/root/Code/slo-94-herdr-integration/slo`. `check` below expands to `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`; it includes 62 DAO/projection safety tests and selects non-e2e.

- `check tests/tui/test_herdr_inbox_disposition.py`: `t5-91-focus.log/.exit`: **73 passed**, exit 0 (11 new).
- Same command after next increment: `t5-91-cutoffs.log/.exit`: **2 failed, 75 passed**, exit 1; fixture failure above.
- Same command corrected: `t5-91-cutoffs-corrected.log/.exit`: **77 passed**, exit 0.
- Same command after displacement/context increment: `t5-91-displacement.log/.exit`: **80 passed**, exit 0.
- Final `check tests/tui/test_herdr_inbox_disposition.py tests/tui/test_herdr_inbox_cutoffs.py tests/tui/test_app.py tests/tui/test_workflow_receive_path.py tests/tui/workflows tests/scheduling`: `t5-91-surrounding.log/.exit`: **408 passed, 33 warnings, 176.40s**, exit 0.
- `PYENV_VERSION=slo-harness poetry run black --check tests/tui/test_herdr_inbox_disposition.py`: `t5-91-black-check.log/.exit`, exit 0. Formatting receipts also retained.
- `PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent tests/tui/test_herdr_inbox_disposition.py`: `t5-91-mypy-final.log/.exit`: **Success: no issues found in 1 source file**, exit 0. This is scoped checking, not full-project mypy approval.
- `git diff --check`: `t5-91-diff.log/.exit`, silent exit 0. New untracked test was separately read/formatted; git diff does not include it.
- `dpkg -V coreutils`: `t5-91-coreutils.log/.exit`, silent exit 0.

Full make/test/smoke/lint deferred to integration; baseline 298 errors / 63 files remains unwaived, not reverified here. Offline tests are not live provider/Herdr acceptance.

## Precise remaining closure

Do not mark bounded requested matrix READY yet:

1. Assert each required shutdown cleanup owner is attempted in every cutoff, not merely successful completion of public unmount. Current tests prove no deadlock but not independent owner call coverage.
2. Extend throwing diagnostic sink to claim/before-registration refusal variants; only durable-advance refusal has that fault here.
3. Add mounted restart/fresh-poll evidence beyond fresh-store pending-only claim checks, and explicit user-history non-entry assertions in every refused path. Existing echo/queue spies cover disposition cases, not all new cutoff cases.
4. Abort proof should additionally pause inside actual invocation/stream and verify normal abort semantics; pre-run interrupt evidence above must not be overstated.
5. Finish required read audit: actual root research, scope/routing, KB welcome/gotchas, inbox/store/app boundaries, C7.9 and workflow fixtures were read. Actual AGENTS/CLAUDE/docs RESEARCH were concatenated but not fully reviewed through tool output (supplied context is not disk read closure). Combined skill output was truncated; selected Python/Textual/Faux/workflow sections were visible, but full engineering/coding prerequisite closure is not established. C7.10–7.14, exact C25/C26/C30 task attachments and accepted review documents were not fully read in this continuation. No claim of full prerequisite compliance.

No new behavioral RED remains in the executed test set. INCOMPLETE is a coverage/read-closure assessment, not a fabricated production failure or an arbitrary workflow budget stop.
