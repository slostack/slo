# T5 activation cutoff handoff 86 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 86, retries 0. Effective turns AND dispatches unlimited; no budget stop and no agents launched. Author evidence only, not independent review or whole T5/T6 acceptance.

## Changes and outcome

Owned edits only:
- `src/tui/app.py`: four executable lines guard `_push_auth_modal` and `_on_auth_dismissed` after closing; one docstring updated. No session/reporter lifetime edits.
- `tests/tui/test_herdr_activation_cutoffs.py`: preserved all sixteen existing cases; added nine actual mount/public-unmount barrier cases.
- `tests/tui/test_herdr_activation_notices.py`: six open-runtime throwing-notice cases and two public-unmount late-auth cases.
- This handoff and sibling `t5-86-*` receipts. No shared status, specifications, KB/global/live/other-worktree edits, commit/push/PR, reset/clean/stash.

Open runtime faults at transcript, delivery, activation, context, title and usage cannot prevent actual preparation task registration. Public unmount cancels/retrieves that worker, stops timers and releases the real inbox lease despite the throwing sink. Exact phase order and fixed-only notice arguments asserted. This is mounted orchestration evidence, not native reporting wire proof.

Nine new cutoff cases run original `on_mount`, real replay/delivery/context and disabled session reporting gateways. Barriers pause hydration (normal completion), startup notice, delivery, activation and context (the latter four normal/error). An independent driver calls public `on_unmount`; the original session close prefix signals sealing before release. No direct `_app_closing` assignment. No later phase, focus request, credential check, auth push or preparation scheduling occurs. Shutdown reaches a completed retained task and clears timers. The prior sixteen synthetic closing/identity cases remain unchanged.

Actual RED: both new late-auth cases called `ModelSuggestionProjection.refresh_authentication` after completed public unmount. The same test invokes `_push_auth_modal` and forbids screen creation. Four production guard lines fix this. `getattr(self, "_app_closing", False)` preserves an existing direct-handler `Mock(spec=SloTUI)` test lacking constructor fields; real constructed apps always own the bool. No old assertion changed.

## Honest first runs

- Notice first run: 1 failed/67 passed. New test incorrectly expected a delivery-boundary diagnostic; that catch rolls back without emitting its own notice. Corrected the new assertion to exact count one for delivery, two otherwise. Not product RED.
- Cutoff first run: 8 failed/80 passed. Throwing sink made original startup notice raise before the new wrapper reached its barrier. Moved only the wrapper barrier to `finally`; removed duplicate hydration error parameter that did not inject an error. No production repair or weakened existing assertion claimed.
- Auth RED: 2 failed/68 passed, real post-close UI work.
- First auth surrounding: 1 failed/154 passed/1 deselected; direct-handler mock lacked `_app_closing`. Compatibility correction above, then green. No ignore/skip/xfail added.

## Bounded read closure

Canonical root (read-only): `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`.

Fresh explicit reads:
- Actual AGENTS 1–510 and 511–1013; full CLAUDE, root RESEARCH; docs/RESEARCH 1–320 and 321–end.
- Frozen `routing.md`, `scope-plan.md`, cutoff85, INIT82 and activation-proof82. Existing routing remains applicable: Python/asyncio/Textual, orchestration plus composed offline tests; no database, provider, CLI-command, styling or platform-launch redesign.
- C 7.9–7.14 completely: 605–982, 983–1363, 1364–1673, 1674–end (including acceptance tail). Exact tasks B02/B05 2401–2434 and C14 2837–2886. C runtime samples and corrective prose govern over excerpt-only readings.
- B optional isolation/privacy 1–180 and 220–315; headings/diagnostic references scanned to bound relevance. This is not a fresh complete B transport implementation audit.
- Accepted `review-evidence/independent-review-turn4.md` complete: T2-F3 monotonic initialization, T2-F4 no-throw diagnostics, T3-F1 admission versus claim and all-owner shutdown are specification acceptance, not implementation approval.
- Engineering routing/ownership/testing; coding rules, code-test-loop, shared declarative; Python root/declarative/Faux/named arguments/docstrings; full Textual build skill (1–240, 241–600, 601–918); workflow SKILL and exact code-test-review workflow. Combined initial reads truncated; omitted engineering beginnings were reread explicitly. Skill sources are checkout `skills/` per frozen routing; no skills changed.
- KB Welcome, actual slo README index and gotchas (current source wins over historical paths and publishing advice). Root test fixtures/state isolation, actual affected mount/preparation/shutdown/runtime/auth methods and surrounding tests inspected.

This closes the fresh C-runtime/instruction read gap in 85. It does not falsely claim reading all 9,859 family lines again or independent full-family review. Additional affected contracts discovered by that read are listed below rather than silently excluded.

## Finite affected contract map

Paths below are relative to `tests/tui/`.

| Contract | Evidence / disposition |
|---|---|
| C14 delivery → activation → context → title/usage → pending preparation | `test_herdr_activation.py::test_shared_runtime_activates_before_context_and_title`; INIT82 `test_herdr_init_branches.py::test_mount_phase_order_and_preparation_branch` covers actual mount/history/ready branches; new notice matrix covers fault continuation |
| C14 transcript/startup failure still reaches runtime | `test_herdr_init_ownership.py::test_mount_optional_fault_does_not_skip_runtime`; new `test_open_runtime_notice_failure_preserves_preparation[transcript]` |
| C13/C25 delivery rollback, timer ownership, captured leases | Reuse complete finite `t5-init-audit-82.md` map unchanged; all four init test files rerun in final gate |
| C13/C14 reporting/context/presentation failure + raising sink | New six-case notice matrix; later phase order, real preparation registration and public cleanup asserted |
| C7.13 mount await cutoffs, no late focus/auth | New nine-case `test_mount_public_unmount_blocks_focus_and_auth`; retained 16 cutoff85 cases supplement identity and preparation branches |
| C7.13 preparation notice and completion | New matrix plus `test_preparation_notice_failure_still_registers_task`, `test_direct_preparation_cancellation_preserves_delivery`; cutoff85 success/error × closing/identity |
| C7.13 public close forbids auth open/dismissal work | New two-case `test_public_unmount_refuses_late_auth`, RED→four-line repair→GREEN |
| C7.13 captured-session auth callback after replacement | **Not closed.** `_push_auth_modal` still binds bare `_on_auth_dismissed`; no captured-session callback or attention token. Closing guards do not solve identity displacement while open. Requires separate test-first captured-session wiring, preserving existing auth behavior; session attention is another lane. |
| F4 cleanup owner isolation | Reused `test_herdr_app_shutdown.py::test_shutdown_attempts_each_owner[preparation,unsubscribe,close,release]`, INIT82 timer/release fault matrices; final gate green |
| F4 viewer registry cleanup | **Not closed.** No `_visualizer_launch_tasks`, `_cancel_visualizer_launches` or scheduling registry wiring exists in current app. `_finish_app_shutdown` attempts preparation, session close, selected delivery then final owner drains; `_commit_replacement_session` likewise has no viewer drain. Cannot prove notice-independent cleanup of an absent registry. This is the D/T5 viewer caller lane, not permission to fabricate a mock-only registry or change session/reporter lifetime here. |
| C7.13 replacement/mount join-before-gate | Existing initialization, repeated-cancellation and shutdown tests rerun; new public-unmount barriers demonstrate no deadlock |
| B optional/disabled behavior | Default stripped/disabled suite; composed disabled/outside PromptInput/Faux parity rerun; fixed-only new notice assertions. No live provider/Herdr claim |
| Actual mounted native activation | `test_herdr_activation_composed.py::test_mount_native_save_display_and_new_lease_order` rerun and passes now. INIT82 is initialization evidence, not this proof. Activation-proof82 DID test actual mounted enabled activation successfully before failing successor authority; later fixes belong to the other lane. Do not describe 82 as never having tested mounted activation. |
| Accepted review T3-F1 inbox/prompt registration; F2 quarantine; D viewer/platform; 64-case lifetime matrix | Read and kept distinct. Not acceptance claimed by this finite cutoff patch. No other-lane changes. |

## Verification receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved `PYENV_VERSION=slo-harness`; verified `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. No venv created. Tests use `bash docs/implementation/94-herdr/t1-dao-check.sh <files>`; wrapper adds 62 DAO/projection cases. Suite strips HERDR, disables by default, guards real terminal and Herdr spawn, isolates state in temp roots. Composed tests use existing registered regular-file fake capability; no system symlinks or real provider/window.

Sibling `.log`/`.exit` pairs:
- `t5-86-notices-first`: 1 failed, 67 passed.
- `t5-86-notices-surrounding`: 135 passed; notices, cutoffs, init_ownership, app_shutdown.
- `t5-86-cutoffs-first`: 8 failed, 80 passed.
- `t5-86-cutoffs-surrounding`: 162 passed; cutoffs, notices, activation, activation_composed, app_shutdown, init_ownership, openrouter_startup.
- `t5-86-auth-red`: 2 failed, 68 passed; notices file.
- `t5-86-auth-surrounding`: 1 failed, 154 passed, 1 deselected; notices, cutoffs, openrouter_startup, authentication directory.
- `t5-86-auth-green`: 155 passed, 1 deselected; identical file set.
- `t5-86-final`: **485 passed, 1 deselected, 47 warnings**, exit 0, 251.68s, post-format. Exact arguments: `tests/tui/test_herdr_activation_cutoffs.py tests/tui/test_herdr_activation_notices.py tests/tui/test_herdr_activation.py tests/tui/test_herdr_activation_composed.py tests/tui/test_herdr_activation_faults.py tests/tui/test_herdr_initialization.py tests/tui/test_herdr_init_ownership.py tests/tui/test_herdr_init_rollback.py tests/tui/test_herdr_init_branches.py tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_replacement.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_openrouter_startup.py tests/tui/test_app.py tests/tui/test_replay_resume.py tests/tui/authentication`.
- `t5-86-black`: `poetry run black --check src/tui/app.py tests/tui/test_herdr_activation_cutoffs.py tests/tui/test_herdr_activation_notices.py`, exit 0. Format log covers only owned test files.
- `t5-86-static`: `poetry run mypy --follow-imports=silent` both owned tests, exit 0.
- `t5-86-app-static`: same scoped mypy plus `src/tui/app.py`, success in 3 files, exit 0. This does not clear repository/imported-file diagnostics.
- `t5-86-diff`: `git diff --check`, silent exit 0; repeated after final suite.
- `t5-86-coreutils`: `dpkg -V coreutils`, silent zero-byte output, exit 0 after final suite; also silent after increment gates.

Full make/integration gate remains later as requested. Historical 299 errors/63 files remains **UNWAIVED**, not a fresh full-static result. Existing E2E deselection is not an added exclusion.

## Verdict and next bounded work

**INCOMPLETE for complete affected C14/F4 family**, despite green cutoff/notice evidence. Remaining concrete gaps: captured-session auth completion and viewer registry/drain integration. The latter cannot be closed by this runtime-continuation test slice; do not claim a nonexistent cleanup owner was tested. No arbitrary unit/turn cap caused this result. Preserve the new tests and four-line cutoff repair, hand the exact missing owner contracts to their integration lane, and rerun this affected gate after integration. Independent review and full make gates remain outstanding.
