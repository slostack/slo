# T5 inbox disposition continuation 90 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 90, retries 0. Turn/dispatch budgets unlimited. No agents launched. No completion, independent approval, or live acceptance claim.

## Implemented bounded increments

1. `_handle_inbox_message` returns an explicit bool for all four modes. It checks app delivery authority before advancement and after its await, including captured-session identity. `_start_inbox_chat_turn` returns the final `_register_prompt_task` result instead of discarding it.
2. Claim owner captures session/store before awaiting claim, checks closing/authority/session identity after claim, and acknowledges only admitted delivery using captured identities. Refusal leaves claimed bytes unchanged and emits the existing best-effort fixed lifecycle notice. No store/schema/coordinator/lease policy changes.
3. Existing direct handler tests now hold the submission gate and assert `is True`; chat mocks explicitly return True.

## Finite evidence map / outstanding branches

| Branch | Evidence |
|---|---|
| Four delivery modes, open and closing entry | Eight mounted real-session/Faux cases `test_inbox_handler_explicit_admission`; explicit bool assertions |
| Shutdown during claim | Real mounted temp store barrier; public shutdown prefix; exact bytes only in claimed; no invoke; pending-only next claim returns None |
| Shutdown after advance return | Same real path barrier; ordinary system notice only: NOT proof of durable workflow transition |
| Final registration refusal | Synchronous notice seam closes app before registration; bool propagates to no-ack |
| Local echo pending | Prior 89 mounted regression retained and passes |
| Direct receive handler contracts | Existing tests migrated to gate + literal booleans; 25 existing cases pass |
| Captured-session displacement checks | Implemented after claim/advance; dedicated displacement tests still required |
| Already registered / ack pending / abort policy / task identity | Still required; four-case T3F1 matrix NOT complete |
| Durable workflow advance at shutdown | Still required with actual lifecycle payload and retained handle assertion |
| Context persistence pending at close / idempotency | Existing behavior retained; new cutoff proof still required |
| Claim/advance errors, handler cancellation, ack false/error, empty/closed poll | Full named disposition matrix still required |
| Throwing diagnostic sink / shutdown owners | Existing best-effort seam reused; new inbox fault matrix still required |
| Ordinary closing entry and queued successor guards/matrices | Still required; current final gate alone does not close all queue semantics |

## Exact execution receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. `check` means `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`. Script adds 62 DAO/projection cases, disables Herdr and uses test environment. New tests patch factory to Faux; mounted store files are under pytest tmp_path. No executable/link creation.

- `check tests/tui/test_herdr_inbox_cutoffs.py`: `t5-90-bool-red.log/.exit`, **8 failed, 63 passed**, exit 1. Literal None return failures.
- `check tests/tui/test_herdr_inbox_cutoffs.py tests/tui/test_app.py tests/tui/test_workflow_receive_path.py tests/tui/workflows tests/scheduling`: `t5-90-bool-green.log/.exit`, **385 passed**, exit 0.
- Claim test first execution: `t5-90-claim-red.log/.exit`, **3 failed, 71 passed**, exit 1. Test glob incorrectly omitted store timestamp filename prefix; this is fixture failure, NOT behavioral RED.
- Corrected filename glob: same focused command, `t5-90-claim-red2.log/.exit`, **3 failed, 71 passed**, exit 1. Behavioral RED: files wrongly moved to done after refused delivery.
- Same surrounding command: `t5-90-claim-green.log/.exit`, **388 passed**, exit 0.
- `check tests/tui/test_workflow_receive_path.py`: `t5-90-direct.log/.exit`, **87 passed**, exit 0 (includes 62 added guard cases).
- `PYENV_VERSION=slo-harness poetry run black src/tui/app.py tests/tui/test_herdr_inbox_cutoffs.py tests/tui/test_workflow_receive_path.py`: `t5-90-black.log/.exit`, exit 0.
- Post-format same surrounding command: `t5-90-final-surround.log/.exit`, **388 passed, 26 warnings**, exit 0, 172.66s.
- `git diff --check`: `t5-90-diff.log/.exit`, silent exit 0.
- `dpkg -V coreutils`: `t5-90-coreutils.log/.exit`, silent exit 0.

Full make/test/smoke/lint NOT run: family not ready. Prior lint 298 errors / 63 files remains unwaived; no ignore/skip/xfail added.

## Read closure and scope

Read 89 receipt, actual claim/handlers/final registration callers, inbox store/DAO and affected direct tests, C lines 1100–1579 including normative inbox contract, existing plan/root research and KB welcome/gotchas. Shared engineering routing/testing/ownership, coding-rules/code-test-loop, Python/declarative/Faux and workflow SKILL read. Textual/shared declarative reads were partial. Combined plan/KB read truncated. Full actual disk AGENTS/CLAUDE/docs RESEARCH, exact C25/C26/C30/task samples/section8/accepted reviews and remaining skill closure have NOT been completed in this continuation. Do not infer full read closure from supplied project context.

Only app.py, inbox cutoff tests, existing direct handler tests and this continuation's documentation/logs edited. Other pre-existing changes preserved. No canonical/global/live/other-worktree edits, agents, commits, pushes, PRs, resets, clean or stash. Viewer/T6 work untouched. Continue this family, not a new workflow turn.
