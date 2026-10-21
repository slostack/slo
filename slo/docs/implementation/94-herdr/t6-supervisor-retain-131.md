# T6 supervisor retention 131 — INCOMPLETE; positive HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 131, retries 0. Effective turns and dispatch budgets unlimited. No agents dispatched, independent review or completed workflow turn claimed.

## Substantive bounded changes

Changed only `tests/integration/herdr_restore_process_bootstrap.py` and `tests/integration/test_herdr_restore_harness_safety.py`, plus this receipt and the current section of safety-123. Existing partial work preserved.

- `RetainedResourceError` has declared `first_error`, `owner`, and `resource` fields. It strongly retains the exact resource and cleanup owner; the original exception is also its explicit cause. No arbitrary exception attributes are added. `release(timeout=...)` checks retained-resource identity and delegates the bounded later join.
- Parent stop admission/signal ordinary failures no longer bypass `process.wait`. If joining succeeds, the original failure propagates. If joining fails, the typed capability preserves the original failure and captures. The existing interruption test now asserts typed transfer, capture survival and later explicit release/removal.
- Isolated `OwnedSupervisor` records the first ordinary status/signal/identity failure, independently attempts TERM and KILL with waitability/group/session admission, then attempts reaping regardless of those errors. Failed identity/status admission never grants signal permission.
- Supervisor reaping uses `waitpid(-1, WNOHANG)` with a bounded pending interval instead of unconditional blocking. Partial receipts and the exact Popen remain retained until ECHILD. Later explicit drain writes the receipt and clears ownership only after closure. The supervisor does not own deletion of its enclosing root.
- Three parent fault cases inject killpg/waitid/getpgid failures while a real finite dummy supervisor needs joining. Three isolated adopter cases inject those faults while an actual barrier-held dummy remains alive; they assert real waitpid attempts, exact first-error preservation, typed strong ownership and later release after opening the barrier. RED cleanup independently opens the barrier and reaps children before the wrapper exits; a finite fallback bounds dummy lifetime.

## Test-first evidence

Cwd `/root/Code/slo-94-herdr-integration/slo`. Approved interpreter verified by `pyenv which python`: `/root/.pyenv/versions/slo-harness/bin/python`; `poetry run python --version`: Python 3.11.7.

Every pytest run used this explicit synthetic environment and explicit safety module (no positive family/probe/full make):

```sh
export PYENV_VERSION=slo-harness SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
poetry run pytest -q --tb=short -m 'not e2e' tests/integration/test_herdr_restore_harness_safety.py
```

Preimport state isolation strips inherited case-insensitive HERDR settings; existing terminal/Herdr guards remain unchanged. New wrapper environment is explicit disabled/terminal-off only. Scripts and barrier paths are checked with ProcessSafety before writes; no real executable links or providers/Herdr/windows.

| Increment | RED | GREEN |
|---|---|---|
| Typed parent ownership | 1 failed, 57 passed: missing RetainedResourceError import | 58 passed |
| Parent stop errors still join | 3 failed, 58 passed: typed retention returned without attempting join | 61 passed |
| Isolated adopter faults retain/rejoin | 3 failed, 61 passed: raw OSError escaped before reap | 64 passed |

The third change was approximately 50 substantive implementation lines including bounded drain, after the prior green. Strengthened tests additionally assert waitpid attempts and release through the exception capability. Final post-format/type-fix safety result: **64 passed, 2 warnings in 7.08s**, exit 0. Warnings are pythonjsonlogger module deprecation and LangGraph allowed_objects pending deprecation.

Final chained gates (all exit 0):

```sh
poetry run black --check tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
poetry run mypy --follow-imports=skip tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
poetry run pytest -q --tb=short -m 'not e2e' tests/integration/test_herdr_restore_harness_safety.py
git diff --check
dpkg -V coreutils
```

Black: 2 unchanged. Scoped mypy: no issues in 2 files. Earlier mypy found Popen bytes-vs-str and test alias narrowing errors; both corrected before final gates. Diff check and coreutils verification silent. The Python files were already untracked, so git diff does not review their contents; relevant helper sections were read directly and exact edits reviewed. No standalone logs/spills were intentionally written.

## Exact remaining boundary — not READY

The new typed capability is usable **inside the caller interpreter**, as tested. The generated `run_supervised` wrapper still calls `OwnedSupervisor.invoke` directly under SystemExit without catching retained-resource failures. If the actual child supervisor cannot finish reaping, an uncaught typed error can still terminate that interpreter, losing its in-memory capability. Parent `Popen.wait` alone is not proof that descendant closure occurred. This continuation therefore does NOT establish end-to-end retained ownership for that wrapper or authorize positive execution. A retained-child-side entry lifetime/parent protocol is still required; do not silently promote the primitive proof to composed safety.

Also remaining: repeated interrupts, startup/partial READY races, FD identity/close and capture faults, concurrent owner entry/overwrite, full descendant pending/recovery protocol and positive mutation/exec acceptance. The new ordinary-error catch does not claim repeated BaseException safety. No broad harness redesign attempted. No full non-E2E suite or global static-green claim.

## Reads and limits

Read 129/130 receipts and actual helper/test in chunks <=150 lines; root RESEARCH, routing/scope plan, shared engineering routing/testing/ownership, coding rules/cadence, Python root/style and full declarative/workflow SKILL. AGENTS/CLAUDE/docs RESEARCH were supplied in context, not freshly reread in full from disk. Consulted KB Welcome, slo README/gotchas first 150 lines, os ROLE/README, workload detail first 150 lines and guardian security section; read canonical B isolation prerequisite and C lifetime safety mapping read-only. These are scoped consultations, not a claim to have reread all KB/B/C content. No dedicated Python process recipe was found/claimed. A malformed parallel read omitted paths and produced six validation errors; it read nothing and wrote nothing.

No agents, commit/push/PR/reset/clean/stash, shared workflow-status/KB/spec/global/live/other-worktree edits. No old probe, positive test, full make, host configuration or system executable mutation. Existing historical receipts preserved. **INCOMPLETE for the requested two-fix closure; bounded helper improvements verified, positive HOLD remains.**
