# T5 registration handoff 92 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 92, retries 0. Effective turn and dispatch limits unlimited. No agents dispatched. No independent review or full-feature acceptance claimed.

## Owned changes

Only `tests/tui/test_herdr_prompt_registration.py` and lane-specific receipts/report changed in this continuation. No production correction was needed: new behavioral cases passed the existing closing guards. `src/tui/app.py` was Black-checked (formatter left it unchanged). Prior partial work and the separate inbox-disposition lane were preserved. No canonical/global/live/other-worktree edits, commits, push, PR, reset, clean or stash.

Added mounted real config-backed session/Faux coverage:

- `test_prompt_registration_shutdown_submission_gate[busy_closed,lock_wait_idle,lock_wait_busy]`: actual first registered run, unchanged held text and block identity, lock-wait cutoff, unchanged navigation history, shutdown joins outside prompt execution.
- `test_prompt_registration_shutdown_entry_matrix[False/True-manual/inbox/direct]`: literal registration booleans for direct/inbox entry under submission lock; refused calls never construct `_run_prompt` coroutine; manual history versus machine no-history/no-queue policy.
- `test_prompt_registration_shutdown_slash[submitted_slash,direct_slash]`: actual `/help` router after closing, no ordinary run registration. Canonical contract does NOT ban slash dispatch coroutines; no such product restriction was added.
- `test_prompt_registration_shutdown_preexecution[complete/interrupt/slash_abort-manual/inbox]`: actual manual entry or real store enqueue/poll, pause original spinner before session invocation, shutdown preserves exact registered task without cancellation or abort, release permits exactly one invoke after cutoff, held successor never starts. Explicit interrupt and slash-abort delegation remain available. This proves pre-execution abort requests, not an active-stream hard-cancel escalation matrix.
- `test_prompt_registration_open_queue_and_new`: real first/finalizer/successor, latest-wins block identity, input cleared, accepted-only history, busy `/new` refusal and idle replacement. Faux fixture now has two actual responses for the two-run case.
- `test_prompt_registration_shutdown_atomic_commit`: structural complement to mounted tests verifies synchronous final check/create/assign/return, no suspension or extra hook after the final check.

Retained existing canonical local echo / queued removal / queued echo barriers and registered completion test. Existing inbox cutoff and surrounding app/workflow tests run unchanged.

## Evidence

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified approved `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. `check` below means `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`; this supplies the approved safe fallback and adds 62 DAO/projection tests. Read actual root fixtures: pre-import/per-test HERDR stripping, forced disabled, independent registered-file capability guard and terminal spawn guard remain intact. No executable fixture or system symlink added.

- `check tests/tui/test_herdr_prompt_registration.py`: `t5-92-gate.log/.exit`, 71 passed; `t5-92-entry.log/.exit`, 79 passed; `t5-92-policy.log/.exit`, 83 passed. Incremental green receipts, not feature approval.
- Final `check tests/tui/test_herdr_prompt_registration.py tests/tui/test_herdr_inbox_cutoffs.py tests/tui/test_app.py tests/tui/test_workflow_receive_path.py tests/tui/workflows`: **351 passed, 42 warnings in 184.15s**, exit 0, `t5-92-surround-final.log/.exit`. This supersedes earlier 348/351 receipts before final fixture adjustment.
- `PYENV_VERSION=slo-harness poetry run black --check src/tui/app.py tests/tui/test_herdr_prompt_registration.py`: exit 0, `t5-92-black-final.log/.exit`.
- `PYENV_VERSION=slo-harness poetry run mypy src/tui/app.py tests/tui/test_herdr_prompt_registration.py`: exit 1, **9 errors in 6 dependency files; zero diagnostics in either owned file**, `t5-92-mypy-final.log/.exit`. Initial own func-returns-value error was corrected without suppression. Dependency errors: missing yaml stubs; transcript_projector optional tool name; Faux constructor/bind_tools; assistant_chunk_normalizer ToolCall; Anthropic kwargs; OpenAI Codex constructor. This is NOT a green mypy command. Historical full 298-errors/63-files baseline remains unwaived; no full lint rerun here.
- `git diff --check`: silent exit 0, `t5-92-diff.log/.exit`.
- `dpkg -V coreutils`: silent exit 0 after final suite, `t5-92-coreutils.log/.exit` (also silent after intermediate suites).

## Remaining before READY

Do not call this complete solely from the test count:

1. Required actual-file read closure is incomplete. Fully read canonical C 7.9–7.14 and section 8 (605–2175), shared engineering routing/testing/ownership, coding rules/cadence/declarative, Python root/declarative, Textual/workflow guidance, root RESEARCH, routing/scope and KB material. Some earlier combined reads truncated; actual AGENTS/CLAUDE/docs RESEARCH, exact T5 attachments and accepted reviews have NOT all been re-read completely in this continuation. Supplied context/prior handoff is not fresh actual-file read closure.
2. Complete the final finite coverage audit against those attachments/reviews, including precise inbox already-registered ack-boundary/active-abort attribution to the other lane. Current added inbox preexecution case polls real store but does not itself assert done-file bytes or hold ack across cutoff. Do not claim that stronger evidence from it.
3. Review the final owned test diff for all assertions/cleanup and preserve exact canonical IDs mapping. The added syntax assertion is supplemental, not replacement for mounted behavior.
4. Integrated full make test/smoke/lint remain later, as requested, after lane integration. No baseline waiver and no independent acceptance.

No new axes beyond the requested finite family are proposed. This handoff deliberately returns INCOMPLETE rather than claiming read closure or full canonical registration acceptance from surrounding green tests.
