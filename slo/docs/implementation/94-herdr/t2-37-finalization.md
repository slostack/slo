# T2-37 integration finalization — INCOMPLETE, narrowed handoff

Code+Test only. The retained cleanup RED is corrected and every currently collected
non-E2E test passes. This is not whole-feature approval or an independent review.
T2 technical READY is withheld for the specific authority-boundary assertions below,
not because the old save/worker/policy/privacy families are still pending. T3/T4
have not been started. Parent accounting unchanged: turn1 started1/completed0,
historicalpartial1, dispatch24, retries0. Both budgets unlimited; no numeric stop.

## Changes and cadence

- `src/agents/slo_agent/herdr/service.py`: added one transport-owned cleanup
  diagnostic episode boolean, set before failure throttling. Successful retained
  local drain consumes the episode before calling the sink and emits fixed
  `herdr_cleanup_unavailable_recovered`. Sticky `_cleanup_failed`, sealed admission,
  cached drain tasks, accounting and remote retry policy are unchanged. Production
  increment: 14 added lines. The requested behavioral RED was reproduced first;
  immediate whole Herdr package then passed 730 cases before further work.
- `test_final_lifetime_closure.py`: recovery sink healthy/raising variants, exact
  once, sticky/sealed state; persistent failed drain with/without cancellation
  asserts no recovery and retained episode. Ordinary admitted cancellation cases
  remain unchanged. A cancellation request is not drain evidence: shielded actual
  successful drain may subsequently recover, but failed drain never does.
- The first added sink test patched an individual logger method; monkeypatch
  restored a bound instance attribute that shadowed subsequent class patches.
  Two surrounding sink tests caught this. Corrected the test to patch the class;
  no production workaround or weakened assertion. The failed receipt is preserved.
- `test_privacy_closure.py`: explicit `dict[str, str]` annotation fixes the new
  mypy index error found in the prior lane's test. No behavior/assertion changed.
- `test_restore_batch_closure.py`: five new coverage-only real executable cases
  (rejected, timeout, current_ok, stale_ok, stale_timeout). Complete batch crosses
  actual reservation/admission/accounting: one install attempt per batch,
  confirmed identity retained, truthful settled lifecycle after failed install,
  no stale follow-up, later retry only on another batch, and release before a
  changed generation. All passed initially; no fabricated production RED.

## Reconciled finite B7.11/B7.13/section-8 map

Paths are relative to `tests/agents/slo_agent/herdr/`. Covered means the named
bounded adapter behavior, not future automatic T5 hooks or live protocol acceptance.
The detailed tables in t2-34-privacy and t2-36-policy/save-worker/lifetime remain
part of this handoff. Historical 'all pending' paragraphs are superseded here.

| Obligation | Current executable evidence | Status |
|---|---|---|
| Task join complete/pending/error/single/repeated/owned cancellation | `test_cli_transport.py::test_join_drains_before_return` | Covered |
| Publication memory-only, identical/lower/reused generation/session mismatch | `test_reporter.py::test_publication_admission`; `test_t2_remaining.py::test_session_mismatch_publication_has_fixed_failure` | Covered |
| Empty/new/busy/adoption/close worker wake | `test_worker_wake.py::test_worker_wake` | Covered |
| Same-save newest usage/actual rename; next-generation successful continuation | `test_save_worker_closure.py::test_save_worker_continues_latest[rename,capture]`; `test_reporter.py::test_usage_update_during_identical_config_save_reuses_reference` | Covered; manual publication after real rename is the T2 seam |
| Pool/eligibility/session/generation supersession; adoption closed/disabled/current | `test_t2_remaining.py::test_changed_capture_save_barrier`, `test_save_adoption_remaining` | Covered |
| Save selection, exact association, failed reference withdrawal/no requeue | `test_reporter.py::test_save_selection`, `test_save_exact_association`, `test_failed_save_does_not_requeue`; `test_reporter_compositions.py::test_failed_save_uncertain_release_blocks_replacement` | Covered |
| Save absent/success/error/cancel/repeated/error during cancel | `test_t2_remaining.py::test_save_join_remaining`; `test_reporter_compositions.py::test_save_join_repeated_cancel_drains_and_retrieves` | Covered |
| Durable reservation sources, stale/close/cancel/error-cancel; expired shutdown deadline | `test_reservation_composition.py::test_reservation_thread_is_drained_before_cutoff`; `test_final_lifetime_closure.py::test_shutdown_deadline_joins_durable_reservation`; sequence store tests | Covered |
| Exact ticket/lease/safe admission; six ordinary operations × seven currentness states | `test_reporter.py::test_lock_admission`; `test_t2_remaining.py::test_ordinary_operation_currentness` | Covered |
| Binding conflicts, none/same, confirmed policy, exact saved association | `test_policy_accounting_closure.py::test_binding_conflict_policy`, `test_nonconflicting_claim_release_policy`, `test_confirmed_policy`, `test_restore_association_policy` | Covered; invalid missing-publication helper input is explicitly defensive |
| Every terminal operation/status/currentness, one-shot/unowned completion | `test_operation_results.py::test_terminal_operation_matrix`; policy `test_unowned_result_cannot_account`; reporter `test_terminal_accounting`, `test_admission_bridge_refuses_reuse` | Covered |
| Nonmatching/stale release, partial/final display, spawn-failure rollback prior/no-prior | policy `test_release_accounting`, `test_display_acknowledgement`, `test_definitive_spawn_failure` | Covered |
| Same-capture uncertain install/claim retains reference and confirmed identity | policy `test_claim_after_uncertain_install`; `test_restore_batch_closure.py::test_restore_uncertainty_batch` | Covered; no remote installation acknowledgement invented |
| Activation repeat/contention/reject/timeout/cancel/close-pending/unsafe counter | `test_activation_lifetime.py`; `test_reporter_shutdown_closure.py::test_counter_activation_refuses_without_send` | Covered |
| Shutdown admission token/budget/release/clear constraints | `test_reporter.py::test_shutdown_admission`, `test_shutdown_release`; shutdown closure `test_shutdown_and_patch_cutoffs` | Covered |
| Pending worker/save/admitted child close with repeated cancellation/errors | `test_save_worker_closure.py::test_close_joins_pending_save_and_worker`, `test_close_joins_worker_admitted_child`; reservation/activation tests above | Covered |
| Transport lock-inclusive waiter, late spawn, bounded readers, signals and reap faults | `test_transport_lifetime.py`, `test_transport_read_failures.py`, `test_transport_signals.py`, `test_cli_transport.py` | Covered bounded platform seam; not native Windows certification |
| Real G2 viewer/A/B plus admitted old effect; independent holder survives waiter timeout | `test_reporter.py::test_viewer_lock_waiter_superseded_report_never_spawns`; `test_reporter_compositions.py::test_already_admitted_a_accounts_without_followup`; `test_independent_lock_holder.py::test_reporter_timeout_does_not_drain_independent_viewer` | Covered transport/reporter seam, not actual future T4 launcher |
| Retained child/lease, final success/persistent failure/cache/cancel, exact-fd close faults | `test_final_lifetime_closure.py`; `test_retained_transport_composition.py`; `test_reporter_final_drain.py` | Covered; failed OS calls injected around real owned resources |
| Batch bootstrap/working/settled/failure/stale patches and TTL | `test_reporter.py::test_bootstrap_batch`, `test_report_steps`; `test_batch_failures.py`; shutdown closure; new restore batch test | Covered |
| Actual two-second timer without revision increments | `test_refresh_timer.py::test_refresh_timer_preserves_revision` | Covered, not merely repeated batch |
| Fixed category throttle/recovery/sink/suppression/cancellation | `test_gate_diagnostics.py`, `test_diagnostic_closure.py`, `test_transport_diagnostics.py`, `test_reporter_diagnostics.py`, lifetime recovery above, `test_path_recovery.py` | Covered listed recoverable episodes; terminal defects retain uncertainty |
| Explicit native argv argument/byte/control bounds | `test_resume_bounds.py`; reporter lifecycle commands | Covered helper/wire boundary, not future T3 CLI parser |
| Pure numeric/token/identity/privacy helpers, four-provider actual wire | full helper table in `t2-34-privacy.md`; `test_privacy_closure.py`, `test_projection.py`, `../test_token_format.py` | Covered bounded adapter map |
| Sequence corruption/overflow/fsync/write/refusal/restart/concurrent processes | `test_sequence_store.py`, activation refusal, reservation composition | Covered |
| Default safety before import/per test, real spawn capability substitution and runtime guard | `test_test_isolation.py`, `test_spawn_guard.py`, `test_fake_fixture.py`, `test_t2_remaining.py::test_actual_spawn_substitution_refused` | Covered; no live activation |
| Live reporter authority predicate and viewer-construction contract | Existing activation, inactive visualizer refusal and ordinary revocation tests cover subsets | **Partial: exact gaps below** |

## Exact remaining T2 executable assertions

1. B7.13 reporter authority: explicitly exercise `allows_viewer_admission` and
   destination for each independent revocation predicate (viewer revoked,
   closing, disabled, activation not released, lease lost, unsafe sequence,
   sealed transport), then queue a command using that live bound predicate at
   the actual shared lock and prove refusal after authority changes. Existing
   ordinary-operation currentness tests are not this viewer authority boundary.
   The actual T4 one-shot split/rename/run ledger remains T4, not a T2 omission.
2. B final helper additions: `build_visualizer` currently has only inactive
   refusal coverage. Prove closed/unsafe refusal before construction and the
   positive assembly seam passes the identical transport and bound live
   predicate to an injected constructor. Concrete `.visualizer` is correctly
   deferred to T4; testing the existing T2 assembly seam does not require
   implementing that adapter or starting T5.

No further production defect is established by these missing assertions. Do not
re-open completed save/policy/privacy families wholesale. Add these bounded tests,
fix only a reproduced defect if any, rerun affected/package/full gates, then decide
T2 technical READY. This is a concrete evidence gap, not an invented stronger
product contract or a baseline-lint prohibition on dependency work.

## Exact execution receipts

CWD `/root/Code/slo-94-herdr-integration/slo`, branch `feature-94-herdr-integration`.
Approved `pyenv which python` = `/root/.pyenv/versions/slo-harness/bin/python`,
Python 3.11.7; `make test-env` = fallback. `t1-dao-check.sh` inspected before runs:
safe exports, default-disabled Herdr, project PYTHONPATH, synthetic credential,
root capability/terminal guards. It adds 62 DAO/projection tests.
All prefixes below are sibling `.log`/`.exit` receipts; actual exits retained.

| Prefix / command | Result |
|---|---|
| t2-37-red: helper + exact requested recovery test | 1 failed, 62 passed; exit 1 |
| t2-37-green: helper + Herdr package | 730 passed; exit 0 |
| t2-37-package: helper + package/token/footer | 2 failed, 770 passed; exit 1, test logger isolation fault described above |
| t2-37-package-final: same after test correction | 772 passed; exit 0 |
| t2-37-full: make test before annotation/new restore cases | 7059 passed, 19 deselected, 408 warnings; exit 0 |
| t2-37-lint: make lint before annotation correction | 302 errors/65 files; exit 2 |
| t2-37-restore: helper + test_restore_batch_closure.py | 67 passed; exit 0; coverage-only |
| t2-37-final-package: helper + Herdr, token format, footer, visualizer launcher, tui/workflows, workflow receive path | 877 passed, 5 warnings; exit 0 |
| t2-37-surrounding: exact additional surrounding list in routing.md | 518 passed, 31 warnings; exit 0 |
| t2-37-full-final: make test | **7064 passed, 19 deselected, 408 warnings; exit 0**, 586.10s |
| t2-37-smoke-final: make smoke | **285 passed**, exit 0 |
| t2-37-lint-final2: make lint | **301 errors/64 files, 726 checked; exit 2** |
| t2-37-lint-final-baseline.diff | Exact `: error:` lines versus t2-33-lint.log: empty; baseline **unwaived** |
| t2-37-black-final | All changed Python scope (same explicit list as t2-32 plus new package files): **49 unchanged**, exit 0 |
| t2-37-chapter-black | All existing B/C/D chapter source paths: **12 unchanged**, exit 0 |
| t2-37-coreutils-final | `dpkg -V coreutils`: silent, exit 0 |
| t2-37-diff-final | `git diff --check`: silent, exit 0 |

Available chapter lists ran without claiming absent paths passed. Planned files
`tests/cli/test_herdr_restore.py`, `tests/tui/test_herdr_session_lifecycle.py`,
`tests/tui/test_herdr_visualizer.py`, `tests/integration/test_herdr_full_flow.py`
remain future T3/T5/T6 acceptance. Their full chapter commands are not green gates.
No skipped assertions or exclusions were added. Full suite's 19 deselections are
its existing non-E2E policy, not executed live evidence.

## Reading and handoff boundary

Read supplied AGENTS in project context, actual CLAUDE/root RESEARCH/full maintained
`docs/RESEARCH.md`, Makefile, Python/test/static declarations, safe helper; full
routing/scope plan and requested t2-34..36 receipts (initial combined output
truncated; individual relevant maps subsequently recovered). Read B completely
in 1–655/656–1250/1251–1838/1839–2221 ranges; exact T2 tasks 446–1905 in three
bounded ranges; C 169–368, 1476–1740, 1985–2175 for capture/argv/lifetime/final-drain
contracts; full D 1–711; accepted turn-4 independent review and finalization.
This is relevant T2 ingestion, not full unrelated C app/inbox implementation review.

Loaded checkout shared engineering routing/testing/ownership; coding rules/cadence/
declarative; Python root/declarative/DAO/service/type/docstring; exact workflow and
workflow SKILL. First combined Python read truncated; recovered Python root,
declarative and DAO opening separately. KB Welcome/Slo README/gotchas consulted
read-only. Not claiming every deferred CLI/Textual or unrelated routed recipe was
freshly read; none of those layers was changed. The existing frozen routing remains
unchanged. No full-family independent review/completion has occurred.

Preserve immutable capture, no-await lock-held admission→tracked spawn, one shared
transport, joined resources and sticky uncertainty. T3 supplies secure immutable
store/CLI; T4 supplies viewer/context reader; T5 later owns automatic session rename,
capture/privacy event exclusion and lifecycle wiring; T6 owns composed and live
acceptance. No 0.9.2, restart, native restore or pane-paint certification. No agents,
commit/push/PR/reset/clean/stash, global/KB/specification/other-worktree edits or live
operations. Durable lesson: end a diagnostic episode only after actual local drain;
consuming it before a best-effort sink prevents duplicate recovery on sink failure.
