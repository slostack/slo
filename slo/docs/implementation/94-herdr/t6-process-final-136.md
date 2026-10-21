# T6 PROCESS final 136 — READYPROCESS; parent-entry HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 136, retries 0. Effective workflow-turn and dispatch budgets unlimited; no agents dispatched. This is bounded author PROCESS closure, not independent review, overall harness approval or feature completion.

## Four-row disposition

| Receipt 135 row | Change and executed evidence | Verdict |
|---|---|---|
| Retained wrapper repeated interruption | `OwnedSupervisor.run_entry` installs a stop-only SIGINT handler before invocation and restores the previous handler only on exit. Sleep and release share a BaseException boundary. Disposable wrapper with a real finite child injects two sleep KeyboardInterrupts, two release KeyboardInterrupts and actual self-SIGINT at traced loop lines (including gaps). Exact capability, resource and primary survive; exit 125 only after drain, child returncode 0 and ECHILD. | Closed |
| Child READY close/fstat combinations | Four composed cases: close-before-error/close-after-error × handler success/failure. Two persistent EIO inspection failures retain the same resource/FD and original handler-or-close primary; before-close ambiguity never retries close. Independent known-owner disposal then actual FD-slot reuse with another temp regular file proves release does not close unrelated identity. No workload spawned on startup failure. Existing child interrupt cases separately prove actual workload reap. | Closed |
| Second interruption during parent stop | Catch BaseException at stop request so cleanup wait still runs. Two actual-child cases prove exactly two wait attempts: successful cleanup propagates original primary after reap; interrupted cleanup transfers typed retention with exact resource/process/primary and disposed descriptors. Independent final join/drain proves ECHILD. | Closed |
| Drain-versus-drain concurrency | Real child wait barrier holds first drain under existing admission lock. Second drain refuses busy, leaving resource/directory/FD unchanged; releasing barrier completes one join/removal and proves ECHILD. Existing run-versus-drain coverage retained. | Closed |

Finite PROCESS scope is the identified owner/syscall contract, not arbitrary errno combinations, an OS sandbox, atomic FD generations or protection against external concurrent same-inode descriptor substitution. Ownership is exclusive; ambiguous close is not retried. Signals target only created anchored groups or the disposable wrapper itself. MUTATION/EXEC guard-family and positive parent-entry remain **HOLD** and were not exercised or edited.

## Test-first sequence and exact outputs

Only `tests/integration/herdr_restore_process_bootstrap.py` and `tests/integration/test_herdr_restore_harness_safety.py` changed as code. Both were already untracked; git diff cannot display their content. Changed owner boundaries and added tests were inspected directly. No legacy unsafe helper restored.

1. Wrapper RED: `-k retained_entry`: **1 failed, 93 deselected**, 1.58s; wrapper escaped with `KeyboardInterrupt: sleep`, returncode -2. Its independent finally joined the real dummy. Implementation increment below 50 substantive lines. Entire module GREEN: **94 passed**, 52.49s.
2. Parent RED: `-k parent_stop_interrupt`: **2 failed, 94 deselected**, 2.25s; `assert calls == 2`, actual 1 in both cases. One catch changed. Entire module GREEN: **96 passed**, 53.62s.
3. Drain concurrency added as regression proof, already green; no invented RED/code defect: entire module **97 passed**, 53.39s.
4. Four child combinations added as regression proof, already green: entire module **101 passed**, 53.62s.
5. Black formatted only the safety module; bootstrap unchanged. Scoped mypy clean. Fresh final post-format chain below: **101 passed, 2 warnings in 53.62s**, Black two files unchanged, mypy no issues in two files, diff/coreutils silent, chained exit **0**.

All pytest runs emitted only the existing pythonjsonlogger deprecation and LangGraph pending-deprecation warnings. Each incremental test command captured pytest status separately and then ran `dpkg -V coreutils` (silent); shell exit 0 on RED is not represented as pytest success. Exact pytest statuses: 1, 0, 1, 0, 0, 0, then final chain 0. Output retained in tool transcript, not separate log files, respecting the two-document write restriction.

Cwd `/root/Code/slo-94-herdr-integration/slo`. `PYENV_VERSION=slo-harness pyenv which python` returned `/root/.pyenv/versions/slo-harness/bin/python`; Poetry verified Python 3.11.7. Environment/commands:

```sh
export PYENV_VERSION=slo-harness SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
poetry run python --version &&
poetry run pytest -q --tb=short -m 'not e2e' tests/integration/test_herdr_restore_harness_safety.py &&
poetry run black --check tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py &&
poetry run mypy --follow-imports=skip tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py &&
git diff --check && dpkg -V coreutils
```

Incremental pytest commands used the identical explicit module with `-q --tb=short` and the above `-k` only for RED. Root pre-import/per-test HERDR stripping, disabled integration, fake-only transport and terminal guard remain intact. New scripts/files are contained regular temp files; no system symlinks/providers/Herdr/windows.

## Read and scope honesty

AGENTS/CLAUDE/docs RESEARCH supplied in context; root RESEARCH, routing/scope-plan, receipt135/current safety123, affected owner/test boundaries, state isolation and root guard locations inspected. Read vendored engineering routing/testing/ownership, coding rules/cadence, Python root/shared+Python declarative/named-arguments and canonical workflow SKILL counting section. No dedicated Python process skill exists in the supplied manifest; exact bootstrap ownership contracts govern this adapter test slice. KB ROLE read first, then README/Welcome/Slo README/gotchas/workload detail. Canonical Herdr B1872–1925/C2060–2105 read-only. No claim of fresh full-file ingestion of all project instructions, every historical test or the full workflow document. Two malformed parallel read batches returned validation errors and read nothing. An oversized KB read spilled to `/tmp/slo-bash-poijc0ln.txt`; its initial README lines were truncated, not claimed ingested from that call.

No agents, commit/push/PR/reset/clean/stash, global/live/KB/spec/other-worktree/shared-status edits. Documentation writes only this receipt and safety123 current section; historical evidence preserved. No old probe, positive parent-entry, full make, product E2E or live acceptance. **READYPROCESS does not lift MUTATION/EXEC or parent-entry HOLD.**
