# T5 continuation 66 — APP adoption INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, dispatch 66,
retries 0. Effective turn/dispatch budgets unlimited. No agents dispatched or new
workflow turn claimed. This is author implementation evidence, not independent acceptance.

## Implemented bounded increments

Only `src/tui/app.py`, new `tests/tui/test_herdr_replacement.py`, and local evidence/status
files changed in this continuation. Candidate65 and all unrelated partial work retained.
No session-service change or demonstrated shared-seam defect. No TCSS, specs, KB,
global state, other worktrees, commits or external actions.

- Candidate preparation remains first and unchanged. One retained
  `_session_replacement_task` shields commit and joins repeated caller cancellation.
- Commit synchronously calls actual `begin_external_reporting_close()` before its
  first await, joins old preparation, closes through actual session lifetime, then
  unsubscribes/assigns/subscribes without yielding. Ordinary preparation/close and
  unsubscribe faults have conservative containment.
- Current phase order is **prepare → revoke → preparation join → reporter close →
  synchronous adopt → stop timers → captured OLD-ID release → NEW-ID initialization
  → UI/usage refresh**. This follows the requested close/adopt-before-transfer order;
  C's example quiesces timers/releases before reporter close. Exact ordering versus
  final canonical requirement still needs explicit reconciliation/evidence; do not
  call this a complete C phase-order proof.
- Heartbeats resolve identity under the existing submission gate. Claim entry refuses
  while delivery quiesces or becomes unsafe. Failed old release (False or exception)
  sticks across successors; no new lease is acquired. Candidate initialization error
  stops timers and attempts captured candidate release without skipping UI cleanup.
- Uncertain remote close permanently suppresses successors. Only retained local
  resources cause an explicit strong `_retired_herdr_session`; repeated replacement
  preserves that exact slot. Fully drained remote uncertainty remains sticky but does
  not retain the old session.
- Unmount has a narrow final retained-owner drain hook using the existing session
  `finish_retired_reporting_cleanup()` gateway. Its app task joins repeated waiter
  cancellation. This is NOT the complete monotonic unmount implementation.
- UI/usage faults cannot restore a closed predecessor. Existing workspace/plugin/new
  queue policy remains unchanged.

**No successor reporting activation was added.** Mount/unmount is still the legacy
lifecycle and lacks the required monotonic startup/shutdown ownership. Starting a
new real reporter here would be unsafe. Enabled successor activation remains pending,
not silently replaced with a claim that disabled tests prove it.

## Finite branch map and actual evidence

All 13 new cases mount real Textual with config-backed actual sessions and actual
temp-only inbox lease stores. They invoke `_start_new_session`, not a copied sample.
Reporter barriers instrument the null reporter through actual session close; they
are orchestration evidence, NOT enabled fake-executable/OS-resource proof. Existing
candidate65 tests invoke Faux for preserved usability; new tests do not invoke models.
Default HERDR stripping/disable, fake-only capability guard and terminal guard remain.

| Branch | Evidence |
|---|---|
| Safe close, cancellation, repeated cancellation | `test_new_commit_joins_old_close[False,True]`; retained task, old subscription while blocked, candidate subscription exactly once, actual old lease absent/new lease owned |
| Ordinary preparation/unsubscribe/transcript/inbox faults + throwing diagnostic | `test_new_committed_fault_never_restores_old`, four cases; selected candidate and retrieved task |
| Remote-only versus local-retained uncertainty | `test_new_uncertainty_is_sticky[False,True]`; real session close, GC weakref, explicit slot, repeat new suppression |
| Old lease absent/mismatched/error | `test_new_failed_release_disables_successor_delivery`, three cases; actual owner mismatch preserved, renew/poll refused, second new still disabled |
| Final local drain, repeated public cancellation | `test_retired_owner_final_drain_is_joined`; one close/one drain, strong slot until drain completes |
| Partial initialization plus candidate release error | `test_new_candidate_lease_rollback_failure_keeps_ui_progress`; real acquired lease/timers, both stopped, workflow state reset, queue cleared |

## Executed commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved
`PYENV_VERSION=slo-harness pyenv which python` returned
`/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7. No new venv/install.

F = `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/test_herdr_replacement.py`

S = `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/test_herdr_replacement.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_app.py tests/tui/authentication tests/agents/slo_agent/test_session.py tests/agents/slo_agent/herdr/test_session_lifetime.py`

Every stem below has `.log` and `.exit` in this directory unless noted.

| Stem | Command | Result |
|---|---|---|
| t5-66-red1 | F | 2 failed/62 passed, exit 1; reporter close never entered |
| t5-66-surround1 | S | 445 passed/1 deselected, exit 0 |
| t5-66-red2 | F | 2 failed/62 passed, exit 1; old lease remains |
| t5-66-surround2 | S | 445 passed/1 deselected, exit 0 |
| t5-66-red3 | F | 4 failed/64 passed, exit 1; committed cleanup/render errors escape |
| t5-66-surround3 | S | 449 passed/1 deselected, exit 0 |
| t5-66-focus4 | F | 73 passed, exit 0; added sticky/GC/lease cases, no production RED claimed |
| t5-66-red5 | F | 1 failed/73 passed, exit 1; final drain absent |
| t5-66-surround5 | S | 455 passed/1 deselected, exit 0 |
| t5-66-red6 | F | 1 failed/74 passed, exit 1; rollback release skips UI |
| t5-66-surround6 | S | 456 passed/1 deselected, exit 0 |
| t5-66-full | `PYENV_VERSION=slo-harness make test` | 7800 passed/19 deselected/556 warnings, exit 0, 638.10s |
| t5-66-lint | `PYENV_VERSION=slo-harness make lint` | 299 errors/63 files, exit 2; baseline remains unwaived |
| t5-66-black | `PYENV_VERSION=slo-harness poetry run black --check src/tui/app.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_herdr_replacement.py` | 3 unchanged, exit 0 |
| t5-66-diff | `git diff --check` | silent, exit 0 |
| t5-66-coreutils | `dpkg -V coreutils` | silent, exit 0 |

`t5-66-format.log` records scoped Black before full gate. Lint comparison log is
silent: sorted `error:` lines versus `t5-65-lint-final.log`, normalizing only line
numbers with `sed -E 's/:[0-9]+: error:/:LINE: error:/'`; zero new/removed diagnostics.
No ignores, disabled assertions or new skips. Focus helper includes 62 foundation
cases; overlapping counts are not additive. Smoke not rerun. Full gate is regression
evidence for this partial snapshot, NOT finite-family acceptance.

## Outstanding obligations — do not advance as READY

1. Full captured-ID initializer: actual lease DAO identity validation, all setup
   failures, both timer failures/retained handles, queued heartbeat/inbox proof and
   final identity checks. Current initializer remains legacy; narrow replacement
   rollback is not the canonical complete initializer.
2. Enabled fake-Herdr mounted close→new-claim order and revoked viewer admission at
   real transport barriers; no old release after new claim. Activation deliberately
   withheld until monotonic mount/unmount is safe. Viewer caller registry still later.
3. Quarantine real child/lease retention, persistent final-drain failure and late reap
   with registered fake executable, containment checks, GC and exact owner identities.
   Null-reporter recording outcomes do not establish those resource guarantees.
4. Unmount must join replacement **outside** submission gate before closing actually
   selected owner. Current unmount does not do this, nor attempt every owner after
   preparation/unsubscribe defects. Narrow drain hook cannot be treated as full safety.
5. Remaining committed fault/cancellation matrix: old-preparation barrier, throwing
   close seam, timer faults, usage/startup notices and pending preparation. UI clear
   failure can still preserve queued state; complete independent queue cleanup needed.
6. Canonical phase-order reconciliation noted above, comprehensive author diff review,
   remaining B/D reads, complete read closure and finite-family branch coverage.
7. Inbox shutdown continuations, auth/viewer captured callbacks and T6 remain later.

Read this continuation: current candidate65/status, frozen routing/scope plan, supplied
AGENTS/CLAUDE/docs RESEARCH plus root RESEARCH; entire canonical C in three bounded
ranges, exact tasks 2401–3720, accepted turn4 review/finalization, B final lease/revocation
section and D viewer admission/platform section; actual app preparation/replacement/
delivery, session lifetime, lease store, existing candidate/lifetime tests, Makefile,
test helper/isolation. Shared engineering/coding/Python service/Faux/declarative/Textual
and workflow guidance loaded. KB Welcome/README/gotchas/tui-cli-session consulted;
one combined read truncated its leading skill content, then Python style files were
read separately. This is not a claim of full fresh B/D or all adjacent source reads.

Verdict: **INCOMPLETE finite adoption family**. No invented budget limit, no independent
review or completed workflow turn, no whole-T5 readiness. Preserve these partial edits
and receipts; finish the named obligations rather than restarting candidate work.
