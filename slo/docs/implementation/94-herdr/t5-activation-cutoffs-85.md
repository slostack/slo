# T5 activation cutoffs 85 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 85, retries 0. Effective turn and dispatch budgets unlimited. No agents launched. This is bounded author evidence, not independent review or shared-status advancement.

## Owned change

Added only `tests/tui/test_herdr_activation_cutoffs.py` and this report. No production edits, including app.py; no session/reporter overlap. All pre-existing partial work preserved. No specification, global, live, other-worktree, commit or external-system edits.

Sixteen new mounted orchestration cases pass against existing production behavior. No product RED or repair is claimed:

- `test_shared_runtime_await_cutoff`: delivery/activation/context × closing/identity × normal/exception completion (12). Event barriers stop the actual shared runtime continuation after each await. The captured session cannot admit a later phase, repaint title/usage or schedule preparation. A throwing diagnostic sink cannot interrupt return or delivery rollback invocation.
- `test_preparation_completion_cutoff`: closing/identity × success/error (4). Real mounted app, controlled catalog gateway, no late diagnostic/title/usage after completion.

These are boundary orchestration proofs. Closing is set directly to isolate its predicate; they do **not** claim every case calls public unmount during the barrier. Identity displacement is restored only for real original-owner teardown. Delivery rollback is a recording boundary here, not a second proof of actual lease cleanup. Activation is mocked at the session boundary, not native CLI claim evidence. Preparation cases do not exercise a model request. First matrix installs Faux before session construction; all cases keep default disabled Herdr isolation.

## Exact retained coverage reused, not duplicated

Paths relative to `tests/tui/`:

| Obligation | Existing exact evidence |
|---|---|
| Preparation notice cannot prevent task registration | `test_herdr_init_ownership.py::test_preparation_notice_failure_still_registers_task` |
| Original preparation cancellation preserves delivery | same file `test_direct_preparation_cancellation_preserves_delivery` |
| Optional mount notice/usage failure does not skip runtime | same file `test_mount_optional_fault_does_not_skip_runtime` |
| Independent cleanup attempts despite throwing notice | `test_herdr_app_shutdown.py::test_shutdown_attempts_each_owner` |
| Public shutdown joining replacement outside gate | same file `test_unmount_joins_replacement_outside_gate` |
| Late mount hydration/replacement usage/preparation | same file `test_late_runtime_continuation_is_silent` |
| Native mount/display and release-before-successor claim | `test_herdr_activation_composed.py::test_mount_native_save_display_and_new_lease_order` |
| Disabled/outside Faux parity | same file `test_mount_inactive_has_zero_integration_io_and_faux_parity` |
| Full delivery initialization ownership matrix | retained `t5-init-audit-82.md`; not rewritten or promoted to activation acceptance |

All tests in these named files ran in the surrounding gate. This table is not the requested complete canonical B/C/accepted-review map.

## Executed verification

CWD `/root/Code/slo-94-herdr-integration/slo`. Test prefix:
`PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`.
The wrapper adds 62 DAO/projection cases, strips/guards external integration through existing suite fixtures and disables real terminal launch. No venv created. Results were captured in tool output, not invented sibling log receipts.

1. New file first matrix: **74 passed, 2 warnings**, exit 0, 3.62s.
2. Surrounding files: activation, activation_composed, app_shutdown, init_ownership, openrouter_startup: **131 passed, 4 warnings**, exit 0, 15.45s.
3. New complete file plus those surrounding files: **147 passed, 4 warnings**, 19.04s. Pytest printed complete success; the compound shell also ran later checks, so its final exit is not a separately saved pytest exit receipt.
4. Initial Black check failed formatting only. Black formatted only the new file; final Black check passed.
5. `PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent tests/tui/test_herdr_activation_cutoffs.py`: **Success: no issues found in 1 source file** (before formatting).
6. Final post-format targeted run: **78 passed, 2 warnings**, exit 0, 4.44s.
7. `git diff --check`: silent. `dpkg -V coreutils`: silent after suites, including final chained command, exit 0.

Full make/integration gate deferred as requested. Historical 299 errors/63 files remains unwaived, not freshly assessed. No ignores, skips, xfails or assertion weakening added.

## Precise remaining closure gaps

**INCOMPLETE**, not READY for the requested finite cutoff/audit family:

1. Full actual disk instruction/skill and canonical affected read closure was not achieved. Read actual 82/84 receipts and INIT82 map, routing/scope-plan, current app shared runtime/mount/preparation, relevant tests, KB Welcome/gotchas, engineering routing/testing/ownership and selected Python/cadence/build guidance. Large combined reads truncated; redirection of actual AGENTS/CLAUDE/research to a temporary file is not semantic ingestion. Only C runtime excerpt and exact C14 attachment excerpt were freshly read; complete C7.9–7.14, B privacy/close and accepted reviews were not freshly consumed. No false full-read claim.
2. Missing finite evidence remains for successful-open runtime failures with a throwing notice allowing the next phase/preparation registration (as distinct from closing/identity early returns).
3. The new matrix does not directly assert focus/auth suppression from `on_mount` after each barrier, or actual public-unmount barriers for every newly covered phase. Retained tests cover parts, but a complete exact C14/F4 map has not been established.
4. No complete affected canonical B/C and accepted-review requirement-to-existing-test ledger was produced. The exact retained table above is partial, not an acceptance closure.

No session defect discovered by these sixteen cases. No session/reporter fix attempted. No whole T5/T6, live compatibility, complete activation or independent approval claim.
