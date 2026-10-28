# T5 author audit 110 — REVISE

Date: 2026-10-19. **Author Code/Test audit, not independent Review or workflow acceptance.** Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 110, retries 0. Effective turn/dispatch budgets unlimited; no agents launched.

Only this report and `t5-110-*` receipts were written. No production/test changes, shared status, combined-cutoff lane edits, specification/KB/global/live/other-worktree edits, commit, push, PR, reset, clean or stash. Findings below—not an arbitrary capacity limit or red baseline alone—prevent READY.

## Verdict and precise corrections

### F1 — viewer drain failure can skip mandatory later cleanup (high)

Owner: `src/tui/app.py::_finish_app_shutdown` (974–988), `_commit_replacement_session` (2451–2463), `_cancel_visualizer_launches` (2843–2856).

Both shutdown and irreversible replacement await `_cancel_visualizer_launches()` **outside any ordinary-exception containment**. That helper calls `_on_visualizer_launch_done`, whose `task.exception()` retrieves rather than raises a worker exception, but the cleanup helper itself can still fail. C7.9 explicitly requires containing a programmer/cleanup-helper failure, preserving ownership and proceeding with reporter close/adoption; C7.11's final additions require viewer-drain-error and C7.14 F4 requires a throwing notice alongside the original viewer cleanup fault. Current callers instead exit before reporter close, delivery cleanup and final selected/retired drains; replacement can remain transitioning with old reporting revoked and candidate not adopted.

Existing `test_shutdown_attempts_each_owner` in `tests/tui/test_herdr_app_shutdown.py` parameterizes preparation/unsubscribe/close/release, **not viewer**. `test_shutdown_joins_viewer_before_reporter_close` and `test_replacement_drains_gate_using_viewer` establish successful/cancelled joining and lock order, not this failure cutoff. Session-level `test_failed_viewer_close_retains_owner` tests a different owner and cannot cover the app failure.

Required correction in the source-owning lane: preserve out-of-submission-lock viewer joining, contain ordinary helper failure, conservatively retain unresolved work/disable unsafe successor behavior, and still attempt independent cleanup/adoption as specified. Do not simply discard registry handles. Add mounted `viewer_error` cases for shutdown and replacement with a throwing diagnostic sink; assert later-owner call order, selected identity, retained handles and no reopened admission. This is distinct from the other lane's occupied-viewer/retired-owner inbox cutoff matrix.

Evidence classification: direct control-flow finding, **not** a claimed executed failing regression.

### F2 — scheduler filter broadens the approved environment removal (medium)

Owner: `src/scheduling/runtime/subprocess_runner.py:133–139`, `_build_child_environment`.

C7.2 explicitly requires removing keys whose uppercase name starts **`HERDR_`**, preserving ALL other inherited values. Implementation tests `startswith("HERDR")`. Consequently `HERDR` and `herdrFuture` are dropped too. `tests/scheduling/test_runtime_helpers.py:275–321::test_scheduler_child_drops_inherited_herdr_environment[False/True]` explicitly places those two non-prefix names in `removed`, so its passing result locks in the broader behavior rather than verifies the canonical requirement.

Required correction: use the exact approved prefix and move non-underscore lookalikes to preservation assertions, including fresh/resume actual-child cases, case-insensitive true-prefix removal and unchanged parent environment. No narrower orchestrator allowlist should replace inherited environment. If broader removal is desired, it needs explicit contract authorization, not a silent test change. No such authorization appears in current C or T5 tasks.

Evidence: source plus freshly passing existing test demonstrates the erroneous expected boundary; no production change made.

### F3 — reused-pane notice omits the agreed uncertainty/recovery contract (medium)

Owner: `src/tui/workflows/renderer.py:123–142::_write_launch_notice`.

D6/7.2 requires a previous-attempt notice qualified **“if still present”** and otherwise the exact manual `slo visualize --session ID --follow` command. Current reused output is only `Select the retained Herdr workflow viewer pane manually (pane-id).`; the command is appended only for failed/skipped. A retained adapter mapping is not proof that a user has not closed/moved/repurposed the pane. This is the conservative product behavior chosen instead of discovery or automatic replacement, not optional wording polish.

`TestLaunchOutcomes.test_typed_outcomes[reused]` checks only `retained`; `test_worker_renders_typed_outcome_once[reused]` checks only `Select` and absence of `Opened`/`running`. Neither asserts conditional existence or manual recovery. Required correction: shared renderer copy must describe previous attempt, conditional presence and exact captured-parent recovery command; strengthen both renderer and app completion assertions. Preserve zero query/focus/split/run on reuse. No duplicate app formatter should be introduced.

## Ownership migration that is actually complete

The historical defects in 108 are removed:

- `DetachedWorkflowAppService.advance_from_launch_result` returns existing `HandleAdvanceOutcomeDAO`; malformed/error/missing-parent parsing gives empty effects, valid input seeds the same cache and gives one launch effect without durable-advance claims.
- `SloTUI._maybe_launch_workflow_visualizer` delegates raw text once and applies returned effects once.
- `DetachedVisualizerSchedule.__call__` returns None; renderer `_launch_once` only guards and schedules, with no scheduling-success notice.
- Attached `_maybe_launch_visualizer` and detached effects converge on `_schedule_visualizer_launch` → captured-session `_run_visualizer_launch` → `VisualizerLauncher.launch_async`.
- Shared renderer `write_launch_outcome` owns all five statuses; failed guard reset is in finally and survives notice failure. App handles late-result suppression and its own attached run guard, not formatting.
- Registry callback removes only the identical task and retrieves non-cancelled exceptions. Platform work is retained locally per parent and joined before cancellation propagates.
- Recursive search of `src` and `tests` found no `LaunchResultOutcome`, `DetachedVisualizerLaunch`, `handle_launch_result`, `_orchestrator_session_id_from_result`, or `_write_attached_visualizer_outcome` usage. Historical docs are not dangling runtime references.

Thus **typed migration/deletion ownership is READY as a bounded subfamily**, but complete D presentation/lifetime acceptance is REVISE due to F1/F3.

## Actual T5 graph

```text
bootstrap pristine permission → actual tool attachment → exact provenance
                                   ↓
TUI mount / adopted HeadlessRunner → session activation
  → captured environment/private path facts → reporter + shared transport + viewer
session policy/history commits → immutable capture/generation
session usage/run/attention commits → safe publication → reporter worker/save/CLI

attached parent event ───────────────┐
detached raw result → service parse → typed effects → renderer guard
                                    ↓
app registered captured-session worker → async destination selector
  platform → retained joined thread → platform launch
  herdr → session persisted-parent eligibility → one-shot adapter/shared transport
  unavailable → failed (never platform fallback)
                                    ↓
shared renderer outcome notice (F3)

/new candidate prepare → revoke predecessor → viewer join outside gate (F1)
 → gate → old delivery/reporting close → synchronous adoption → successor runtime
unmount monotonic prefix → join mount/replacement → viewer join (F1)
 → gate → preparation/reporting/delivery cleanup → selected + retired final drains

inbox claim → post-await authority → durable advance → post-await authority
 → delivery or final synchronous prompt registration → captured-store ack
scheduler actual spawn → copied environment minus prefix (F2)
```

No second raw parser, accounting source, context reader, transport process slot or notice formatter was found in the traced paths. `OrchestratorContextReader` remains below TUI. Session owns eligibility/capture/attention; reporter owns saves/revisions/remote evidence; app owns selected-session/task registration; renderer owns presentation. Different request guards and lifetime attempt ledger are intentionally different concerns.

## Canonical-to-current evidence map

Paths below are actual test modules; function names are exact. This map distinguishes source tracing, existing test coverage and proof still required. It is not a claim that every listed module was rerun or exhaustively assertion-audited in this continuation. The exact discovered function inventory is `t5-110-test-inventory.log`.

| Canonical contract / methods | Current test mapping and qualification |
|---|---|
| C7.9 activation inputs; `_prepare_herdr_capture_inputs`, `_resolve_herdr_capture_paths` | `herdr/test_session_capture.py::test_activation_reads_existing_metadata_without_creating_history`, `test_activation_eligibility_branches`, `test_activation_path_sources_are_guarded`; `test_session_publication.py::test_activation_does_not_skip_explicit_workspace_persistence` |
| C7.9 provenance begin/finish/reproducibility/tool identity | `test_session_publication.py::test_standard_bootstrap_records_only_pristine_policy`, `test_bootstrap_preserves_exact_restore_identity`, `test_general_attach_immediately_withdraws_capture`; `test_session_publication_compositions.py::test_bootstrap_failure_never_mints_provenance`, `test_bootstrap_early_return_never_mints_provenance`, `test_standard_provenance_rejects_later_mutation`; `test_session_mutation.py::test_bootstrap_final_attachment_refuses_unexpected_additions` |
| C7.9 capture gate/pool/generation/publication | `test_session_capture.py::test_pool_capture_copies_order_and_all_scalars_without_aliases`, `test_capture_uses_established_facts_and_effective_policy`, `test_real_persistence_and_reasoning_commits_refresh_generation`, `test_model_commit_clears_pool_and_refreshes_capture`; `test_session_publication.py::test_usage_commit_publishes_latest_without_capture_or_io`; compositions `test_catalog_only_adoption_does_not_save_or_release`, `test_real_routed_fallback_keeps_configured_capture`, `test_publication_has_no_io_credentials_or_model_build`; isolation `test_caller_pool_mutation_preserves_actual_saved_bytes` |
| C7.9 candidate preparation/disposal | `test_herdr_session_lifecycle.py::test_new_prepare_retains_mounted_owner`, `test_new_prepared_policy_is_independent`, `test_candidate_cleanup_joins_repeated_cancellation`, `test_new_rejects_candidate_history_root_change`; session lifetime `test_candidate_disposal_only_drains_candidate`, `test_candidate_pool_cancel_and_failure`, `test_candidate_pool_disposal_with_reporting_fault` |
| C7.9 irreversible commit/adoption | `test_herdr_replacement.py::test_new_commit_joins_old_close`, `test_new_committed_fault_never_restores_old`, `test_new_uncertainty_is_sticky`; viewer replacement `test_replacement_drains_gate_using_viewer`; app shutdown `test_unmount_joins_replacement_outside_gate`; **viewer-helper ordinary failure missing, F1** |
| C7.9 delivery transfer/renew/timers/captured release | `test_herdr_replacement.py::test_new_failed_release_disables_successor_delivery`; init ownership `test_rollback_releases_captured_owner`, `test_initialization_rollback_uses_acquired_store`; init rollback `test_failed_stops_retain_handles_until_later_cleanup`, `test_timer_stop_preserves_successor_slot` |
| C7.9 postcommit UI/runtime/usage failure | `test_herdr_activation_notices.py::test_open_runtime_notice_failure_preserves_preparation`; `test_herdr_replacement.py::test_new_committed_fault_never_restores_old`, `test_new_candidate_lease_rollback_failure_keeps_ui_progress` |
| C7.9 inbox disposition/handler/nonchat/final registration | Fully read `test_herdr_inbox_disposition.py::test_inbox_delivery_disposition`, `test_context_pending_at_close`, `test_durable_advance_then_shutdown`, `test_already_registered_ack_pending_at_close`, `test_displaced_session_retains_claim`; actual store bytes, committed handle, captured ack, no machine queue/navigation, restart non-replay and streamed abort assertions exist. Occupied viewer/retired cutoff composition remains **other lane**, not this audit's missing implementation demand. |
| C7.9 local/queued registration and preserved execution | Fully read `test_herdr_prompt_registration.py::test_prompt_registration_shutdown`, `test_prompt_registration_shutdown_submission_gate`, `test_prompt_registration_shutdown_entry_matrix`, `test_prompt_registration_shutdown_slash`, `test_prompt_registration_shutdown_preexecution`, `test_prompt_registration_open_queue_and_new`, `test_prompt_registration_shutdown_registered_completion`; atomic AST assertion is supplemental. This bounded registration family is READY on retained 92/109 evidence. |
| C7.10 attention and operation tokens, scope/final usage | `test_session_attention.py::test_attention_tokens_and_operation_precedence`, `test_attention_publication_and_closing`, `test_actual_run_scope_brackets_preparation_and_final_usage`, `test_manual_compaction_keeps_working_through_final_refresh`, `test_startup_operation_owns_matching_attention`, `test_readiness_rejection_never_accepts_work`, `test_real_faux_tool_submission_keeps_working_and_commits_totals`; auth capture `test_auth_attention_clears_only_matching_request`, `test_captured_auth_callback_refuses_displaced_owner` |
| C7.11 activation/start/close/suppression | `test_session_lifetime.py::test_prepare_disabled_does_not_prepare_capture`, `test_disabled_activation_allocates_no_task`, `test_activation_is_once_and_retains_attempted_owner`, `test_close_during_activation`, `test_cleanup_fault_keeps_later_owners`, `test_suppression_is_permanent`, `test_suppression_rejects_attempted_activation`, `test_public_gateway_repeated_cancel_joins_owner` |
| C7.13 retired drain/current owner evidence | `test_session_lifetime.py::test_retired_local_drain_cached`, `test_final_drain_fault_is_retained`, `test_final_outcome_cannot_disagree_with_drained_getter`, `test_retired_drain_requires_completed_close`, `test_finish_retired_cleanup_single_local_attempt`; app shutdown `test_persistent_real_lease_keeps_app_shutdown_pending`, `test_pending_retired_drain_does_not_starve_selected`; activation composition `test_mounted_uncertain_unlock_retains_one_owner_and_suppresses_successors`, `test_mounted_drained_uncertainty_suppresses_successors_and_allows_gc` |
| C7.13 initialization/captured identity/timer publication/rollback | `test_herdr_init_ownership.py::test_initialization_revalidates_captured_binding`, `test_repeated_unmount_cancel_joins_actual_acquire_thread`, `test_initialization_fault_is_contained`, `test_mount_rejects_mismatched_acquisition`; rollback `test_mount_setup_failure_rolls_back`, `test_init_rollback_never_stops_successor_timers`; branches `test_historyless_initialization_has_no_delivery_effects`, `test_mount_phase_order_and_preparation_branch` |
| C7.14 F3/F4 lifetime/diagnostics | `test_herdr_activation_cutoffs.py::test_shared_runtime_await_cutoff`, `test_preparation_completion_cutoff`, `test_mount_public_unmount_blocks_focus_and_auth`; shutdown `test_late_runtime_continuation_is_silent`, `test_shutdown_attempts_each_owner`; init ownership `test_preparation_notice_failure_still_registers_task`; **app viewer fault absent, F1** |
| C7.14 T3-F1 | The four named positions are split between `test_durable_advance_then_shutdown` (three refusal positions × healthy/throwing notice) and `test_already_registered_ack_pending_at_close` (normal/actual-stream abort × original/displaced store). Registration family supplies pre-coroutine versus admitted-task distinction. Other-lane composition qualification remains. |
| C7.14 64-case cross-product | Explicit **T6**, not a T5 audit gap; not run or claimed here. |
| D service/parser migration | `tests/tui/workflows/test_workflow_app_service.py::TestAdvanceFromLaunchResult`; current service returns typed effects. Renderer/parser alias deletion confirmed by search. |
| D caller actual wire | Fully read `test_herdr_attached_composed.py::test_attached_spawn_submits_real_parent_once[enabled/auto_off/unavailable × attached/detached]`: actual bootstrap/Faux session, real gateway/shared transport, registered regular fake CLI; detached persisted parent differs from TUI owner; exact split/rename/run and no fallback/focus/get/close. Not actual viewer paint. |
| D gateway policy and awaited reads | Fully read `test_session_visualizer.py::test_saved_parent_submits_owned_viewer`; `test_session_visualizer_policy.py::test_unsupported_owner_never_reads_parent_or_falls_back`, `test_parent_evidence_and_private_diagnostics`; `test_session_visualizer_lifetime.py::test_gateway_read_lifetime` across metadata/events/context/PATH and cancellation/revocation/identity/default changes. |
| D registry/late notices | Fully read `test_registry_captures_owner_and_deduplicates`, `test_registry_auto_off_refuses_before_task_registration`, `test_shutdown_joins_viewer_before_reporter_close`; attached `test_attached_event_schedules_captured_parent`, `test_completion_lifetime_and_failure_isolation`; replacement `test_transition_refuses_admission`. |
| D five outcomes/reset | `TestLaunchOutcomes.test_typed_outcomes`, `test_failed_notice_still_releases_guard`; `test_worker_renders_typed_outcome_once`. **Reused copy incomplete, F3**. |
| D A2 platform | Fully read `test_destination_selector`, `test_async_platform_keeps_root_spawn_guard`, `test_platform_join_reports_terminal_result`, `test_platform_join_retrieves_error`, `test_platform_join_retains_thread_through_repeated_cancel`, `test_replacement_joins_actual_platform_thread`. Current barrier substitutes whole sync launch, not distinct discovery and spawn seams. Canonical separate discovery-blocked/spawn-blocked coverage is not established by that test alone; source-owner should retain those exact boundary assertions before claiming full A2 matrix. |
| C7.2 headless/child/scheduler | Traced outer `HeadlessRunner.invoke` finally → close/final drain → credential release and adoption-before-start. Actual test inventory: `test_reporting_cleanup_preserves_original_outcome`, `test_process_cleanup_preserves_original_outcome`, `test_config_backed_faux_headless_never_advertises_restore`, `test_enabled_disabled_whole_jsonl_parity`, `test_runner_retains_child_and_lease_until_final_drain`, subagent/detached/relaunch exclusion tests. Scheduler actual child test freshly passes but enforces wrong prefix, **F2**. |

## Read and convention reconciliation

Canonical H is `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`, read-only.

Completed current C **1–2175** in bounded 1–600/601–1200/1201–1750/1751–2175 reads, current D **1–711** in 1–400/401–711 reads, exact tasks **2401–3720** in 2401–2850/2851–3300/3301–3720 reads, plus task requirements/dependency/allocation preamble. Read accepted turn-4 review (initial truncated prefix separately recovered) and finalization receipt: specification acceptance is not implementation acceptance. Read B7.1–7.8 session/protocol/private-publication/transport contracts, not a fresh exhaustive re-audit of all B reporter algorithms. C later corrective prose governs attached before-code.

Read actual AGENTS 1–500/501–1013, CLAUDE, root RESEARCH and docs/RESEARCH 1–310/311–633; frozen routing and scope-plan, 107/108/109 and both 92 handoffs. KB Welcome → actual `slo/README.md` → gotchas consulted read-only. Read vendored engineering routing/ownership/testing, coding-rules, code-test-loop, shared/Python declarative, Python root, named arguments/types, method docstrings, DAO/domain and application-service guidance, full Textual/Faux guidance, workflow SKILL and exact Code-Test-Review workflow. Truncated combined skill prefixes were recovered separately. The broader frozen routing lists additional recipes; this report does not claim fresh full ingestion of every one of those or every test body in the inventory. Consequently it does not certify exhaustive all-family read closure merely from grep results.

Applicable specialization: existing instance-owned session/app lifetime and typed support adapters, not a new SQL service, database, HTTP router or Command class. Generic invoke/classmethod examples do not justify replacing the specified owners. No-await registration/admission sections must stay atomic; Python decomposition is a cohesion check, not mechanical line splitting. Framework positional callbacks/gather/zip remain legitimate exceptions. Private capture is not a public event/diagnostic. Test-first receipts in 109 are retained rather than relabeled as new audit executions.

Additional concrete documentation drift in touched code: `_prepare_session_delivery` documents removed `session`/`owner_id` parameters instead of `binding`; `_publish_delivery_timers` likewise documents `session` instead of `binding`/`timers`. `VisualizerLauncher` class docstring still calls `launch` the single public entry point and other methods pure, despite async gateway/thread ownership. Source owner should correct these mandatory contract-doc mismatches; this lane cannot edit production. T6 AGENTS/README/INSTALL updates remain future by allocation.

## Execution evidence

Fresh focused command (cwd application root):

```bash
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/workflows/test_workflow_renderer.py tests/scheduling/test_runtime_helpers.py::test_scheduler_child_drops_inherited_herdr_environment
```

Approved interpreter verified `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. Reviewed helper exports safe fallback/auto-off/Herdr-disabled and adds 62 DAO/projection cases. Root isolation strips inherited Herdr before imports/per test; real-terminal leaf blocked; independent registered-file capability wraps transport spawn. Result: **78 passed, 2 warnings, 1.22s, exit 0** (`t5-110-focused.log/.exit`). These existing tests pass despite F2/F3 because their expectations are incomplete/wrong; no failing test was hidden or weakened.

`dpkg -V coreutils`: silent exit 0 (`t5-110-coreutils.log/.exit`). No full suite, live Herdr, provider or real window run.

Retained 109 full receipt inspected: **8152 passed, 19 deselected, 600 warnings, 703.96s, exit 0**. Retained normalized comparison: previous/current **295/295**, no added/removed diagnostic rows; **295 errors/60 files remain unwaived**, not static green. 108's comparison against 100 removes one optional-timer diagnostic. These are prior executions, not fresh whole-worktree certification, particularly while the separate lane is active.

## Handoff

- READY bounded: typed migration/deletions and shared ownership; registration behavior as qualified above; real attached/detached gateway-to-registered-fake composition exists.
- REVISE: app viewer-failure cleanup containment (F1), exact scheduler prefix (F2), truthful reused recovery notice (F3); exact A2 discovery/spawn boundary proof and touched docstrings need reconciliation.
- Other lane: occupied viewer plus retired-owner inbox cutoff composition. Its files were not edited or run; inventory discovery is not acceptance of its current work.
- T6: full 64-case composition, two-process native restore, live supported-version/pane paint and release docs remain future, not excuses to block the bounded author audit.
- No independent implementation Review or completion assessment has occurred. Do not advance workflow acceptance from the retained green count or this author report.
