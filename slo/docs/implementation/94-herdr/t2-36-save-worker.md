# T2-36 — READY, save/worker/close family only

This is Code+Test evidence for the finite requested family, not T2 dependency
approval or whole-feature completion. Independent whole-feature Review and
Completion remain required. No production change was necessary. Only the new
`tests/agents/slo_agent/herdr/test_save_worker_closure.py` and this receipt plus
`t2-36-*` command/output/exit receipts were written by this lane. Other partial
work was preserved. No agents, commits, external delivery, globals, live Herdr,
canonical specifications or other worktrees were modified.

Accounting unchanged: turn 1, started 1, completed 0, historical partial 1,
dispatch 23, retries 0; turns/dispatches unlimited. No historical numeric stop
was applied.

## New executable proof (10 cases)

- `test_save_worker_continues_latest[rename]`: real `start`/activation, actual
  worker and off-loop barrier store, real `SloAgentSession.rename_session`,
  temp history metadata, manual latest publication. One record is reused;
  newest turn=9 is sent exactly once; one exact reference install; no name leak,
  no duplicate pending/adoption wake, all background owners joined.
- `test_save_worker_continues_latest[capture]`: change effective reasoning and
  generation while first save is pending. First immutable file remains an orphan;
  the same real worker saves the next capture and successfully installs only its
  second reference, acknowledges newest display and exact capture. No old claim
  or install occurs before the barrier. This closes the prior discard-only proof.
- `test_close_joins_pending_save_and_worker[none/save/worker × ordinary/repeated_cancel]`:
  close while actual worker awaits its off-loop save. Cancellation does not cancel
  the save; close cannot finish early. Success leaves an unadvertised record;
  store error is retrieved; injected worker teardown error becomes sticky
  uncertainty without preventing remaining cleanup. All tasks terminal and
  exceptions retrieved, save slot cleared, no adoption or stale spawn, lease
  retained until sealed transport drain, repeated close shares its task.
- `test_close_joins_worker_admitted_child[ordinary/repeated_cancel]`: registered
  fake child holds a real claim; close cancels/joins worker, reaps that process,
  performs exactly one shutdown release and two authorized clear patches. No
  obsolete display/install follows the claim. Repeated close/post-close publish
  produces no command; final local ownership drained.

All new behavior assertions passed initially. No behavioral RED or production
fix is claimed. Tests were added in three increments and run after each; a
package run followed the first increment and the final formatted increment.

## Source and reused branch map

Canonical read-only H is
`/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`.
B = `94.b.1-herdr-reporting-adapter.md`; C =
`94.b.2-session-publication-and-native-restore.md`.

| Contract / owner | Evidence retained, not duplicated |
|---|---|
| B 7.3, 7.8, 7.10; reporter `_consume_pending`, `_consume_publication`, `_same_configuration` | New continuation cases; `test_worker_wake.py::test_worker_wake` empty/new/busy replacement/adoption/close; `test_reporter.py::test_usage_update_during_identical_config_save_reuses_reference` |
| B 7.8/7.11 exact save selection/adoption | `test_reporter.py::test_save_exact_association`, `test_save_selection`, `test_failed_save_does_not_requeue`; `test_t2_remaining.py::test_save_adoption_remaining`, `test_changed_capture_save_barrier` pool/session/eligibility/generation/closed/disabled; new successful next-generation worker continuation |
| B 7.10/7.11 save join absent/success/error/cancel/repeated/error during cancel | `test_t2_remaining.py::test_save_join_remaining`; `test_reporter_compositions.py::test_save_join_repeated_cancel_drains_and_retrieves`; new real worker/thread close cases |
| B activation/close lifetime, samples B19/B22 | `test_activation_lifetime.py::test_activation_lifetime`, `test_close_during_acquire_joins_before_unlock`; `test_reporter_shutdown_closure.py::test_counter_activation_refuses_without_send`; new worker close cases |
| B close pending reservation | `test_reservation_composition.py::test_reservation_thread_is_drained_before_cutoff` close/repeated cancellation/error cancellation |
| B 7.13 / C final local ownership (C28/C29) | `test_reporter.py::test_close_unstarted`, `test_local_drain_before_lease_release`, `test_close_transport_cancel_still_unlocks`, `test_lease_close_order`; `test_reporter_final_drain.py::test_final_reporter_drain_is_retained_once`; `test_retained_transport_composition.py::test_retained_real_transport_drains_before_lease_release` |
| Failed save with reference/uncertain withdrawal | `test_reporter_compositions.py::test_failed_save_uncertain_release_blocks_replacement` |

Read T2 task sample allocation 446–1905, B save/worker/close and final authority
contracts, C lifetime/final-drain contracts, routing unchanged, scope plan and
T2-35/current ledger. Applied shared engineering routing/testing/ownership,
generic coding/cadence and Python declarative/style/service rules; consulted KB
Welcome and Slo README/gotchas and repository instructions/research.

C lines 174–190 and 281–287 assign automatic history eligibility and rename
publication to the **session**; tasks T5 owns those session edits. This test
intentionally supplies immutable publications manually after the actual rename.
It proves reporter same-capture continuation, not automatic T5 hooks, full
session eligibility, concrete T3 restore durability, or native restart.
The barrier store is a protocol fake writing distinct temp files, not a claimed
implementation of T3's fsync/quota/security contract.

## Exact verification receipts

CWD `/root/Code/slo-94-herdr-integration/slo`; verified
`pyenv which python` = `/root/.pyenv/versions/slo-harness/bin/python`, Python
3.11.7; `make test-env` = `fallback`. Inspected unchanged `t1-dao-check.sh`;
its safe test exports/default disable and root guards were used. Fake fixture
registration is the only executable capability; real terminals remain blocked.
No provider/model invocation was needed for metadata-only rename.

Every prefix below has `.command`, full `.log`, `.exit` siblings here:

| Prefix | Result |
|---|---|
| `t2-36-continuation` | 64 passed, 2 warnings, exit 0 (2 new + 62 DAO/projection) |
| `t2-36-surrounding1` | 6 failed, 673 passed, 4 warnings, exit 1 |
| `t2-36-close` | 70 passed, 2 warnings, exit 0 (8 new + 62) |
| `t2-36-child` | 72 passed, 2 warnings, exit 0 (10 new + 62) |
| `t2-36-final` | Full Herdr package: **729 passed, 4 warnings**, 46.74s, exit 0 |
| `t2-36-black` | New Python file unchanged, exit 0 |
| `t2-36-coreutils` | **silent**, exit 0 |
| `t2-36-diff` | `git diff --check` silent, exit 0 |

The intermediate six failures were in another lane's
`test_policy_accounting_closure.py::test_binding_conflict_policy[missing_publication-*]`:
`ValidationError: Invalid ticket publication` at line 60 during construction.
That file appeared during this lane and was not edited here. Full failure output
is preserved; the final package run subsequently passed the then-current shared
worktree. This lane does not claim to have repaired those tests or freeze other
writers' work. No tests were excluded to obtain the final package pass.

Black formatted only the new file before the final run. Reviewed the new test
content for containment, barrier release in finally, owner joins, real transport
use and forbidden sends. No production diff was introduced by this lane.
No full make test/smoke/lint gate was run, as explicitly scoped; historical static
failures are neither waived nor certified green. T2 integration and whole-feature
review/completion remain separate obligations.
