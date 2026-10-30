# T5 continuation 82 — READY: finite INIT ownership technical evidence

**READY for the finite INIT map from continuation 79.** This is a Code/Test
**author audit**, not independent review, whole T5 acceptance, enabled activation
acceptance, or release approval. No production or existing test was edited.

Accounting preserved: same unfinished turn 1; started 1, completed 0, historical
partial 1, supplied dispatch 82, retries 0. Unlimited turns AND dispatches override
old limits. No agents dispatched; no commit/push/PR, cleanup/reset/stash, global,
live, specification or other-worktree edits.

## Finite map — all rows from 79

Paths below are under `tests/tui/`; names are exact pytest function names.
O = `test_herdr_init_ownership.py`; R = `test_herdr_init_rollback.py`;
S = `test_herdr_app_shutdown.py`; N = new `test_herdr_init_branches.py`.
All cited Herdr files and OpenRouter startup tests ran in the affected gate.

| 79 branch / boundary | Concrete evidence |
|---|---|
| Existing timer slots | O::test_duplicate_initialization_preserves_timer_identity; R::test_init_rollback_never_stops_successor_timers also repeats initialization after refusal |
| Unsafe delivery | test_herdr_replacement.py::test_new_failed_release_disables_successor_delivery[absent,mismatch,error]; R::test_init_rollback_never_stops_successor_timers repeats init without construction |
| Absent history / inert construction | N::test_delivery_construction_is_inert_and_reuses_stores proves real constructors reuse identical stores/service without history creation, timer registration, mount task or reporting start; N::test_historyless_initialization_has_no_delivery_effects[False,True] independently covers disabled history and enabled history with absent root |
| Construction failure | O::test_initialization_fault_is_contained[build] |
| Reconcile/acquire failures | O::test_initialization_fault_is_contained[reconcile,acquire] |
| Missing acquisition store | O::test_missing_lease_store_refuses_acquisition |
| Returned lease session/owner mismatch | O::test_mount_rejects_mismatched_acquisition[session_id,owner_id], real persisted foreign result retained |
| Reconcile/acquire/inbox continuation identity | O::test_initialization_revalidates_captured_binding: 3 phases × owner/session_id/store/inbox/service/renderer/session = 21 cases |
| Captured absent/existing lease store | O::test_captured_absent_store_does_not_release_successor; O::test_initialization_rollback_uses_acquired_store |
| Inbox exception | R::test_mount_setup_failure_rolls_back[inbox] |
| First/second timer registration exception or closing | R::test_mount_setup_failure_rolls_back[timer1,timer2,cutoff1,cutoff2] |
| Timer slot-only displacement | R::test_init_rollback_never_stops_successor_timers, change_owner=False across inbox/timer1/timer2 (both stop outcomes) |
| Failed init stop + displaced successor pair | Same R matrix with stop_fails=True: exact retained tuple, bounded count, exact successful retry union, empty final slots |
| Unrelated retained handle | R::test_init_subset_preserves_old_retained_timer[False,True]; R::test_displaced_failed_timer_remains_owned[False,True]; R::test_timer_stop_preserves_successor_slot |
| Stop/lease/notice combinations | R::test_failed_stops_retain_handles_until_later_cleanup: lease/inbox/both × none/false/error, throwing notice, exact stop-stop-release order |
| Post-release collaborator displacement | O::test_rollback_preserves_successor_after_release |
| Repeated cancellation during real acquire/release thread | O::test_repeated_unmount_cancel_joins_actual_acquire_thread; O::test_rollback_release_joins_thread_before_original_cancel[False,True] |
| Direct catalog preparation cancellation | O::test_direct_preparation_cancellation_preserves_delivery: original cancel, no paints, same timer identities and lease |
| Optional initial preparing notice failure | O::test_preparation_notice_failure_still_registers_task; retained 79 RED/GREEN remains evidence of the actual earlier fix |
| Mount startup notice/usage fault | O::test_mount_optional_fault_does_not_skip_runtime[notice,usage] |
| Late hydration/usage/preparation completion | S::test_late_runtime_continuation_is_silent[mount_hydration,replacement_usage,preparation] |
| Replacement ordering | O::test_replacement_phase_order: release → close → clear → initialize; test_herdr_replacement.py::test_new_commit_joins_old_close[False,True] additionally asserts old lease absent/new lease present and exact subscription |
| Public unmount/replacement gate order | test_herdr_initialization.py::test_mount_initialization_is_joined_before_shutdown; S::test_unmount_joins_replacement_outside_gate; O repeated public cancellation test above; test_herdr_session_lifecycle.py::test_candidate_cleanup_joins_repeated_cancellation |
| Exact mount phase order / ready-pending / no-history | N::test_mount_phase_order_and_preparation_branch: history False/True × pending False/True. Exact hydration → notice → subscribe → delivery → reporting(interactive=True) → context → title → usage → optional preparation → focus/auth; actual retained mount task and submission lock asserted inside delivery |

The phase test's preparation call is deliberately a recording boundary. Actual
pending worker registration, single-flight, success/failure/retry and unmount
cancellation are separately exercised by `test_openrouter_startup.py`:
`test_unmount_cancels_pending_worker`,
`test_new_openrouter_session_is_pending_and_starts_its_own_worker`,
`test_new_cancels_old_preparation_worker_before_replacement`, and
`test_mounted_startup_shared_worker_gates_and_recovers[False,True]`.
Those use the real session gateway with a controlled catalog boundary, not a
provider request. Ready skips preparation in N's two ready cases. No-history
mount still reaches reporting delegation/context/focus but has no delivery timers.

## Canonical reconciliation

Read-only canonical root:
`/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`.
C = `94.b.2-session-publication-and-native-restore.md`.

- C7.9–7.14 read at 605–2120, including capture, attention, activation/close,
  claimed-message disposition, monotonic shutdown and deterministic lifetime map.
- Exact task samples read: C13 `tasks.md:2704–2835`; C14 `2837–2884`;
  C25 `3410–3479`; C26 `3481–3552`. Accepted turn-4 review read in full,
  including the tail previously read in 80. That review accepts the specification,
  not this implementation.
- Actual `src/tui/app.py:606–699` owns mount/preparation; `947–1279`
  owns shutdown/build/initialize/rollback/acquire; `2330–2625` owns replacement,
  timer retention/release and shared runtime. C14 order at C:925–948 is now
  implemented by `_finish_replacement_runtime` (2518 onward), as wired in 81.
  Existing `test_herdr_activation.py::test_shared_runtime_activates_before_context_and_title`
  and new mounted N matrix both pass. The stale title-before-context finding
  in 79/80 is closed for **ordering**, not promoted into full activation proof.
- C25's inert construction means no acquired lease/timers/tasks or persisted
  delivery state; constructors may resolve paths. The new test does not claim
  zero filesystem reads. Exact pre-await identity capture and owned-handle rollback
  are stronger current implementation details, not a second delivery owner.
- C26's join-before-gate principle is covered by actual mounted tests. Existing
  candidate preparation runs under the gate, so shutdown waits for its disposal
  without acquiring a second cancellation owner.

Enabled mounted reporter/native-capture/release-before-claim acceptance remains
with the **separate activation lane** described in 81. Inbox claim/ack/final prompt
registration and viewer registry/drain are future T5 families, not missing INIT
rows. No claim that all C7.9–7.14 acceptance matrices are implemented.

## Reads, scope and author checks

Consumed actual 79, 80, 81 reports and frozen `routing.md` / `scope-plan.md` unchanged.
AGENTS, CLAUDE and docs/RESEARCH were supplied in full context; additionally inspected
actual disk AGENTS opening, full CLAUDE, root RESEARCH and docs/RESEARCH opening.
No claim of a fresh full disk re-read of context-provided files. Read actual affected
app methods and complete initialization, ownership, rollback, shutdown, replacement,
session-lifecycle and activation test files; complete OpenRouter startup tests;
relevant existing app/replay fixtures. Reviewed new test file and actual isolation
fixture/guard code before execution.

Loaded frozen selected checkout skills: engineering routing/ownership/testing;
coding rules/code-test-loop/shared declarative; Python root/declarative/named
arguments/type hints/docstrings/Faux recipe; full Textual build rules; workflow
SKILL and exact code-test-review workflow. No fresh all-family routing exercise.
KB Welcome and slo README/conventions/gotchas read; obsolete platform/path and
publishing guidance not adopted. No KB/shared-status edit authorized or made.

Two actual evidence gaps warranted the new file: direct inert/no-history assertions
and full mounted phase/branch order (the prior shared-runtime test alone was not
full mount proof). Seven new cases pass without production changes. Initial run
was 4 failed/65 passed because the test incorrectly expected Textual focus paint
to settle synchronously inside on_mount. Retained `t5-82-branches.log` shows:
`TranscriptScroll(id='transcript-scroll') is PromptInput()` was false. Corrected
only this new test to record the synchronous `PromptInput.focus` request before
auth, which is the canonical phase contract; no timing sleep or production change.
This is a test assumption correction, **not a product RED-to-GREEN fix**. No genuine
production contract gap was found in this finite INIT audit; none is hidden by a
skip, xfail or weakened ownership assertion.

## Exact execution receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Every Python command below uses
`PYENV_VERSION=slo-harness`; verified interpreter
`/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. No venv created.
`check` below expands to `bash docs/implementation/94-herdr/t1-dao-check.sh`, which
sets isolated test fallback variables, force-disables Herdr and adds the 62
DAO/projection tests. Suite guards strip inherited HERDR state, reject unregistered
executables, isolate HOME/state and prevent real terminals. Existing persistent
lease test uses registered temp-owned fake capability; no real provider/Herdr/window.

Receipts are sibling `t5-82-<name>.log` and `.exit` (format has log only).

| Receipt | Exact command after PYENV_VERSION prefix | Result |
|---|---|---|
| branches | check tests/tui/test_herdr_init_branches.py | 4 failed, 65 passed, 2 warnings; exit 1; test assumption above |
| format | poetry run black tests/tui/test_herdr_init_branches.py | formatted new file only |
| affected | check tests/tui/test_herdr_init_branches.py tests/tui/test_herdr_initialization.py tests/tui/test_herdr_init_ownership.py tests/tui/test_herdr_init_rollback.py tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_replacement.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_herdr_activation.py tests/tui/test_openrouter_startup.py | 189 passed, 8 warnings, 26.00s; exit 0 |
| surrounding | check tests/tui/test_app.py tests/tui/test_replay_resume.py | 244 passed, 27 warnings, 171.15s; exit 0 |
| black | poetry run black --check tests/tui/test_herdr_init_branches.py | exit 0 |
| static | poetry run mypy --follow-imports=silent tests/tui/test_herdr_init_branches.py | Success: no issues found in 1 source file; exit 0 |
| diff | git diff --check | silent; exit 0 |
| coreutils | dpkg -V coreutils (repeated after surroundings) | silent; exit 0 |

Scoped static evidence covers only the owned new test; it does not clear imported
production or repository diagnostics. Full `make test`/smoke/lint integration is
later as requested. Historical **299 errors / 63 files remains UNWAIVED**; no fresh
full-green claim. Continuation 79's intermittent selection failure remains retained
without a causal repair claim. Neither focused gate replaces independent review.

Owned outputs: this report, t5-82 receipts, and
`tests/tui/test_herdr_init_branches.py` only. All pre-existing dirt preserved.
