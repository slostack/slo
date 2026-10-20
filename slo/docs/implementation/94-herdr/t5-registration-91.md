# T5 registration continuation 91 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 91, retries 0. User turn/dispatch limits unlimited. No agents dispatched. No independent review or completion claim.

## Changes owned by this lane

Only `src/tui/app.py` and NEW `tests/tui/test_herdr_prompt_registration.py`, plus these lane-specific receipts/report, were edited. Other existing work preserved.

- Ordinary submission returns on closing before preparation feedback and rechecks after acquiring the submission gate, before queue mutation.
- Accepted ordinary entry returns before navigation-history recording/echo when already closing.
- Queued handoff checks closing immediately after task identity, releases the finished task slot and leaves the held prompt unconsumed.
- Existing synchronous `_register_prompt_task` final check/create/assign remains unchanged, with no await or callback. No shutdown check inside `_run_prompt`, new abort policy, prompt join under the gate, or TCSS edit.

## Evidence and remaining coverage

Mounted tests use real config-backed sessions, patched LLM factory returning Faux, actual Textual echo/removal, public shutdown and deterministic Event barriers. The final queue barrier tests use an actual first registered run and its real finalizer, NOT a fabricated registered task. An earlier green matrix used a fabricated completion owner; the strengthened final receipt supersedes that limited proof.

Covered: closed manual and direct accepted entry (no echo/navigation record/task); local echo pending; queued removal pending; queued echo pending; real pre-cutoff registered completion with held successor retained and no successor echo. Pre-cutoff task identity is asserted through shutdown; its actual Faux execution and finalizer complete outside the gate.

Still required before READY finite family:
- Dedicated busy ordinary closing entry and waiting-on-submission-lock cutoff proofs, including unchanged existing held text.
- Complete manual/inbox/queued/slash registration matrix and explicit direct registration bool cases under the gate.
- Separate pre-cutoff execution-entry barrier and existing abort-policy variant; current completion test holds cleanup after actual execution, not before session entry.
- Explicit open-path latest-wins/history/input/slash/new assertions in this new matrix (existing surrounding tests pass, but are not the complete requested matrix).
- Full actual-file read closure for AGENTS/CLAUDE/docs RESEARCH, complete C7.9–7.14/section8, exact T5 attachments and accepted reviews, shared declarative/workflow guidance. Read source registration/submit/queue/finalizer/shutdown, 89/90 receipts, routing/scope/root research and KB welcome/README/gotchas; some combined output truncated. Do not infer complete ingestion from supplied context.
- Own static checking and final integrated make gates after both lanes finish. Prior 298 errors / 63 files baseline remains unwaived. No full gate run here.

## Receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. `check` = `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`; script supplies safe disabled Herdr test environment and adds 62 DAO/projection tests. Existing HERDR stripping/fake-capability/terminal guards retained. No test executable/system symlinks or live provider/Herdr/windows.

- `check tests/tui/test_herdr_prompt_registration.py`: `t5-91-entry-red.log/.exit`: **2 failed, 62 passed**, exit 1 (closed entries echoed).
- Same target plus `tests/tui/test_app.py tests/tui/test_workflow_receive_path.py tests/tui/workflows`: `t5-91-entry-green.log/.exit`: **316 passed**, exit 0.
- Focused target: `t5-91-successor-red.log/.exit`: **1 failed, 64 passed**, exit 1 (held successor consumed).
- Same surrounding set: `t5-91-successor-green.log/.exit`: **317 passed**, exit 0.
- Target plus `tests/tui/test_herdr_inbox_cutoffs.py` and above surroundings: `t5-91-matrix.log/.exit`: **332 passed**, exit 0; limited fabricated completion owner subsequently replaced.
- Strengthened real finalizer focused target: `t5-91-real-finalizer.log/.exit`: **68 passed**, exit 0.
- `PYENV_VERSION=slo-harness poetry run black src/tui/app.py tests/tui/test_herdr_prompt_registration.py`: `t5-91-black.log/.exit`, exit 0.
- Final strengthened target + inbox cutoff + app + receive + workflows: `t5-91-final-surround.log/.exit`: **332 passed, 29 warnings**, exit 0, 171.29s.
- `git diff --check`: `t5-91-diff.log/.exit`, silent exit 0.
- `dpkg -V coreutils`: `t5-91-coreutils.log/.exit`, silent exit 0 (also silent after earlier surrounding runs).

No canonical/global/live/other-worktree edits, commits, push, PR, reset, clean or stash. No shared status edited. This report deliberately withholds READY: the finite family and required read/static/full verification are not complete.
