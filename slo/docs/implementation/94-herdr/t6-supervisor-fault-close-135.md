# T6 supervisor fault closure 135 — INCOMPLETE / HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 135, retries 0. Effective turns and dispatches unlimited; no agents dispatched. No independent review or completed workflow claim.

## Scope and changes

Only bootstrap and its explicit safety module changed as code:
`tests/integration/herdr_restore_process_bootstrap.py` and
`tests/integration/test_herdr_restore_harness_safety.py`.

- Parent registers both raw pipe ends before either fstat; capture FD registration likewise precedes fstat. Nullable identity means exclusively owned partial acquisition, never permission to adopt an externally mutated slot. Failed identity inspection now unwinds or retains the raw FD through the existing resource.
- Combined unjoined actual child and capture-close failure preserve the existing typed capability, exact resource and ultimate first exception instead of nesting RetainedResourceError. GC exercise keeps actual child and FD reachable.
- Child startup owns READY FD before validation/handler/write, attempts disposal after failures, retains ambiguous close, disposes on spawn failure, and refuses workload creation when stop is already requested before spawn.
- Capture reads use the existing owned raw FD; Path read helpers and their additional file-handle/finalizer close boundary are removed from this path. Read failure remains tested at the new boundary.
- Removed unused test-only `OwnedProcessRun.run` and its `cleanup` alternative. Repository search found their callers only in this safety module; canonical parent is not wired to this helper. Six legacy-only recording cases removed; launch refusals and real direct-child output/timeout cases migrated to `run_supervised`. Earlier reports remain historical, not instructions to retain an unsafe alternative.
- Explicit parent drain now shares the active-run admission lock. An actual-run read barrier proves concurrent drain cannot delete/close active captures.
- Failed/interrupted parent join still attempts descriptor disposal. Child wait/signal/drain BaseException boundaries now attempt cleanup and either propagate after closure or transfer typed retention.
- Composed capture close-after-error with actual slot reuse preserves a different temp-owned regular file through explicit release.

No new generic framework or product API was added. Each implementation increment was below approximately 50 substantive harness lines; full safety module went green before the next increment.

## Test-first receipts

| Increment | RED | Entire safety module GREEN |
|---|---|---|
| Allocation/fstat pipe ends and captures | 4 failed, 81 deselected; actual leaked FD assertions | 85 passed |
| Combined child/close primary | 1 failed, 85 deselected; nested primary observed | 86 passed |
| Child startup/stop | 3 failed, 2 passed, 86 deselected; handler/write leak and spawn after stop | 91 passed |
| Remove transient read handle | 1 failed, 91 deselected; Path.read_text reached | 92 passed |
| Remove legacy alternative | 1 failed, 92 deselected; run still present | 87 passed (six legacy cases removed) |
| Full-run versus drain | 1 failed, 87 deselected; drain incorrectly succeeded | 88 passed |
| Interrupted drain still disposes FDs | 1 failed, 88 deselected; FD left open | 89 passed |
| Child BaseException boundaries | 3 failed, 89 deselected; cleanup bypassed | 92 passed |
| Composed capture reuse regression | Already green; no new defect claimed | 93 passed |

RED tests use actual newly created dummy children/private FDs, bounded lifetimes and independent finally cleanup. No real provider/Herdr/window/system-file probe. Child startup and interruption rows execute disposable wrapper scripts, not the product entry shim. Stop/write/spawn faults do not launch a workload. Parent combined join test injects repeated KeyboardInterrupt only at its actual registered child's wait method.

Final post-format chain: **93 passed, 2 warnings in 52.17s**, Black two files unchanged, scoped mypy clean in two files, `git diff --check` silent, `dpkg -V coreutils` silent; chained exit **0**. Warnings are pythonjsonlogger deprecation and LangGraph pending deprecation. Intermediate mypy found one nullable-process assertion at safety-test line 1083; explicit non-null assertion fixed it, then fresh gates passed. Coreutils separately verified immediately after that interrupted static chain.

Cwd `/root/Code/slo-94-herdr-integration/slo`. Verified `PYENV_VERSION=slo-harness pyenv which python` = `/root/.pyenv/versions/slo-harness/bin/python`, Poetry Python 3.11.7. Commands:

```sh
export PYENV_VERSION=slo-harness SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
poetry run pytest -q --tb=short -m 'not e2e' tests/integration/test_herdr_restore_harness_safety.py
poetry run black --check tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
poetry run mypy --follow-imports=skip tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
git diff --check
dpkg -V coreutils
```

Final commands chained with `&&`. RED commands used `-k` for the named increment; pytest failures are explicit above (shell command ended with coreutils and thus returned zero). No logs written separately; output is in tool transcript. Both code files were already untracked, so git diff does not expose their content; changed boundaries were directly inspected.

## Exact remaining HOLD

This is meaningful finite-family progress, **not READY for all known PROCESS faults**:

1. `OwnedSupervisor.run_entry` still catches only Exception around retained.release, and sleeps outside that handler. A repeated KeyboardInterrupt at retained-entry sleep/release can unwind the wrapper with pending ownership. Newly proved invoke boundaries do not close this outermost row.
2. Child READY close-before-error plus persistent fstat failure/combined handler failure needs composed retention/drain proof. The new child close row is close-after-error; shared parent descriptor units are not a substitute for all child combinations.
3. Parent stop-request handling still catches Exception rather than BaseException inside its cleanup join block. A second interruption there transfers ownership but skips that immediate join attempt; explicit later release is possible, not proof that every cleanup action was attempted.
4. Concurrent run-versus-drain is now proved; concurrent drain-versus-drain refusal and repeated retained-wrapper interruption need explicit tests before the broader concurrency/interruption family is declared closed.
5. Device/inode checks are accident guards, not atomic FD generations: same-inode reopen/external concurrent descriptor mutation remains outside the stated exclusive-ownership contract.

Positive parent/entry wiring, old probe, full make, live acceptance remain HOLD. No arbitrary unit-count stopping rule or exhausted workflow budget is claimed. Full finite-family closure and independent review remain unfinished.

## Read/safety honesty

AGENTS/CLAUDE/docs RESEARCH supplied in context; root RESEARCH read directly. Read routing/scope-plan, 134 exact rows/current safety123, affected bootstrap/test portions, isolation guard locations, engineering routing/ownership/testing, coding rules/cadence, Python root/named arguments/docstrings/shared and Python declarative, canonical workflow SKILL; KB ROLE first then README/workload, Welcome/Slo README/gotchas. Canonical Herdr B 1872–1925 and C 2060–2105 read-only via absolute canonical path (initial repo-local path attempts failed). No claim of fresh full-file ingestion of every existing test or prerequisite document.

Two oversized orientation commands auto-spilled tool output to `/tmp/slo-bash-9mm1w_r2.txt` and `/tmp/slo-bash-msjxcc9p.txt`; no scratch copies were authored. Missing initial coding/workload text was reread boundedly. These are disclosed tool spills, not a claimed host-policy breach. Pytest's ordinary temp-owned roots remain authorized test output.

No agents, commit/push/PR/reset/clean/stash, globals/live/KB/spec/other-worktree/shared-status changes. Only this receipt and the current safety123 section are documentation writes. Existing unrelated partial work preserved.
