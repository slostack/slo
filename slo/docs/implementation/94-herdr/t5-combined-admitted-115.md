# T5 combined admitted 115 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 115, retries 0. User turn/dispatch budgets unlimited. No agents, production changes, git mutations, external/global/canonical/other-worktree edits. This is a partial continuation, not family acceptance.

## Added executable evidence

Owned change: `tests/tui/test_herdr_all_owner_cutoffs.py`. The unchanged 113/114 real-resource helper remains in `test_herdr_viewer_retention_composed.py`.

The test now runs five named inbox scenarios against both successful and persistent retired-child final drain (10 cases). Each retains the same actual registered fake split CLI child, reporter transport and real sequence lease across replacement, plus an occupied current registry coroutine whose finalizer acquires the submission gate. The current registry coroutine is not a second CLI worker.

| Scenario | Assertions in this composition |
|---|---|
| claim_pending | Exact claimed bytes; no ack or admitted task; workflow still running |
| workflow_advance_pending | Durable completed workflow; exact claimed bytes; no ack/task |
| before_chat_registration | Final registration gateway is called but refuses; no task/ack; durable completed workflow and exact claimed bytes |
| already_registered | Exact pending task identity survives closing with zero cancellation; one registration; captured original store ack despite displaced app store; exact done bytes; no queued next prompt or displaced store creation |
| registered_abort | Same admitted/captured-store assertions, actual Faux delta barrier, operator interrupt while the same task is active, then completion |
| all five / successful final drain | Current session cleanup completes while retired reap held; repeated shutdown cancellation cannot abandon drain; actual same process reaped and sequence lease released |
| all five / persistent final drain | Current cleanup completes independently; repeated cancellation before and after failed final reap leaves graceful teardown pending; identical child and lease retained; cached final drain does not retry |

Inherited helper also asserts repeated-new suppression, retained-owner GC reachability, exact same process three reap attempts, one split and no rename/run commands. Fixture-only final cleanup restores the real reaper and releases only test-owned resources. Persistent teardown's expected cancellation is not successful graceful completion.

## Test-first results and corrections

No production RED was found. Persistent cases passed initially. First admitted increment had a wrong test import (`inbox.service` instead of `inbox.store`): collection exit 2. Correcting it exposed an invalid new spy assertion in the before-registration case: the gateway must be called to refuse, not skipped. Exact output retained: `Expected '_register_prompt_task' to not have been called. Called 1 times.` Existing no-task/no-ack checks were kept; the spy now expects one call only at that final refusal boundary. These are test mistakes, not product defects. Admitted cases and subsequent abort increment passed without production edits.

## Executed commands and receipts

Cwd `/root/Code/slo-94-herdr-integration/slo`. Prefix `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`; helper adds 62 DAO/projection tests. Each stem below has `.log` and `.exit`; overlapping totals are not additive.

- `t5-115-persistent`: both owned files, 71 passed, exit 0.
- `t5-115-admitted`: collection error, exit 2.
- `t5-115-admitted-corrected`: 2 failed / 71 passed, exit 1 (invalid spy expectation above).
- `t5-115-registration`: 73 passed, exit 0.
- `t5-115-abort`: 75 passed, exit 0.
- `t5-115-surrounding`: **774 passed, 91 warnings, 269.39 seconds, exit 0**. Arguments: `tests/tui/test_herdr_*.py tests/tui/test_app.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_visualizer_launcher.py tests/agents/slo_agent/herdr/test_session_lifetime.py tests/agents/slo_agent/herdr/test_session_visualizer_lifetime.py tests/agents/slo_agent/herdr/test_final_lifetime_closure.py tests/cli/test_headless_retained.py`. Tool timeout 1800, production deadlines unchanged.
- `t5-115-format`: Black on changed file before surrounding gate.
- `t5-115-black`: Black check both owned files, exit 0.
- `t5-115-static`: mypy `--follow-imports=silent` both owned files, no issues, exit 0. Not repository lint.
- `t5-115-diff`: tracked diff check, silent exit 0; owned files remain untracked and are separately formatted/tested.
- `t5-115-coreutils`: `dpkg -V coreutils`, silent exit 0, also checked after focused runs.

## Finite family remainder — no READY

| Required branch family | Current status |
|---|---|
| Four cutoff categories, occupied current registry plus actual retired child | Executed in both drain outcomes; admitted has normal and explicit operator-abort variants |
| Original versus displaced ack store | Displaced captured-store case added; original-store variant exists in separate 110 suite, not yet parameterized in this real-resource composition |
| Refusal restart/no automatic replay | Exact original-store no-reclaim asserted here; fresh-mounted restart remains separate 110 evidence |
| All-owner independent timer/subscription/lease/registry/retired/current cleanup with combined throwing diagnostics | NOT closed: current session completion and registry finalizer are asserted, but exhaustive owner call log and throwing-diagnostic combinations absent here |
| Multiple real workers, first join failure and later joins attempted | NOT reconciled or added in this continuation; surrounding tests alone do not close the requested exact composition |
| Replacement CALLER cancellation with actual retained child | NOT added/reconciled; shutdown cancellation is distinct |
| Mandatory read closure: actual AGENTS/CLAUDE/docs RESEARCH, complete scope/routing, C7.9–7.14, exact T5 samples, D lifetime and accepted reviews | NOT complete. 113/114, owned tests, admitted source test, root research, KB Welcome/gotchas and engineering/coding/Python guidance were read. Aggregate scope/routing read truncated. Supplied prompt text is not claimed as fresh file ingestion. Textual/workflow and canonical sections still need complete reads. |
| Full make and fresh exact 295/60 baseline comparison | Not run because finite combined family is not ready; historical baseline unwaived |
| T6 full 64 matrix, live and independent acceptance | Later work; not claimed |

No new runtime design or durable external KB discovery; no KB write under the user's no-global-edits constraint. Remaining work is explicit, not waived or attributed to an artificial case/dispatch limit.
