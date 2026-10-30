# T6 guard sensitivity 140 — READY for two finite proofs only

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 140, retries 0. Turn and dispatch budgets unlimited; no agents dispatched. This is bounded author evidence, not independent approval, overall guard completion or release readiness.

## Actual changes

Only `tests/integration/test_herdr_restore_harness_safety.py` changed as code: two parameterized tests, eight cases. No bootstrap/entry/product change was needed. Existing 138 denial tests remain unchanged and ran in the final safety module. Documentation writes are limited to this receipt and the new current section in safety123; all older sections remain historical.

### 1. Generated capture substitution and old-behavior sensitivity — READY

`test_generated_capture_substitution_supervised[old-behavior-red,current-green]` executes the actual `ProcessSafety.capture_script` body inside the existing `OwnedProcessRun.run_supervised` / READY-handshake supervisor. Instrumentation wraps the original `os.open` before `safety.install()`, placing the barrier below the installed open wrapper's validation. Only the capture pathname pauses. The parent waits for `VALIDATED`, moves the original capture to `saved`, moves a fresh regular sibling victim into the capture pathname, then releases `SWAPPED` in finally. The victim begins outside the child allowed subtree but inside the parent test root. All creates and parent mutations have containment checks; no host victim, system link, PATH lookup or shell is involved.

The controlled old-body variant replaces only `append_capture` in this disposable generated dummy with check-pathname-identity → open-append → write → close. Audit and descriptor wrappers remain installed. It intentionally lacks the opened-FD identity check. This is an old-behavior reconstruction, not byte-for-byte execution of an archived script. It really writes `[]\n` into the substituted victim. The common child preservation oracle emits `PRESERVATION_ORACLE_RED` and exits **41**. The outer regression asserts that exact nonzero exit, exact stdout, empty stderr, original capture bytes and altered victim bytes. This is an executed old-behavior RED, not a missing-API failure or xfail.

The current-body variant retains the actual writer. It catches exactly `PermissionError('substituted capture descriptor')`, emits `REFUSED_BEFORE_WRITE`, exits **0**, and preserves `saved == b'capture'` and substituted capture `== b'VICTIM'`. Both variants assert supervisor READY, exact workload status in `reaped.json`, and ECHILD for the joined supervisor. The race is deterministic via bounded file barriers, not timing sleeps as race selection (short polling only).

### 2. Registered executable matching/substituted identity — READY

`test_registered_execution_identity_supervised` covers actual `subprocess.Popen`, `subprocess.run`, and `asyncio.create_subprocess_exec`, each with matching identity and actual replacement inode. The new regular executable is the actual generated capture script with the approved current Python shebang. An independently created replacement has identical harmless content but a distinct inode. Child setup registers the original exact `(st_dev, st_ino)`, installs ProcessSafety, and only the negative variant replaces that path before the actual API call.

Matching cases emit exactly `EXECUTED\n`, capture exactly `["registered"]\n`, and wait their fake child. Replacement cases catch exactly `substituted child`, emit `REFUSED\n`, and leave capture empty. All six supervisor workloads return zero with empty stderr, exact single-entry zero reap receipts, READY evidence and supervisor ECHILD. Approved Python `-I -B <contained regular script>` wrapper paths are exercised by every supervised case. This does not broaden ProcessSafety to authorize arbitrary Python subprocess commands. Existing actual Popen/run/asyncio/exec/spawn denial tests from 138 are reused rather than replaced.

## Verification actually executed

Cwd: `/root/Code/slo-94-herdr-integration/slo`.

Synthetic environment for all pytest invocations:

```sh
export PYENV_VERSION=slo-harness SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
```

Root collection/per-test isolation strips inherited HERDR settings and preserves terminal guards. Supervised children receive `env={}` plus supervisor-forced disablement/window settings, not inherited credentials. No product entry is imported by either new test.

Intermediate commands used `poetry run pytest -q --tb=short tests/integration/test_herdr_restore_harness_safety.py` with these selectors:

| Invocation | Actual outcome |
|---|---|
| `-k generated_capture_substitution` | 2 passed, 119 deselected, 2 warnings, 1.94s; exit 0 |
| Whole safety module before second increment | 121 passed, 2 warnings, 55.97s; exit 0 |
| `-k registered_execution_identity` | 6 passed, 121 deselected, 2 warnings, 3.37s; exit 0 |

Poetry resolved the installed Python 3.11.7 base spelling; the final gate explicitly used the approved alias below. No interpreter or package was installed or modified.

```sh
P=/root/.pyenv/versions/slo-harness/bin/python
"$P" --version
"$P" -m black tests/integration/test_herdr_restore_harness_safety.py
"$P" -m pytest -q --tb=short tests/integration/test_herdr_restore_harness_safety.py
dpkg -V coreutils
"$P" -m black --check tests/integration/test_herdr_restore_harness_safety.py tests/integration/herdr_restore_process_bootstrap.py tests/integration/herdr_restore_process_entry.py
"$P" -m mypy --follow-imports=skip tests/integration/test_herdr_restore_harness_safety.py tests/integration/herdr_restore_process_bootstrap.py tests/integration/herdr_restore_process_entry.py
git diff --check
```

Final actual output: Python **3.11.7**; **127 passed, 2 warnings in 58.12s**; Black **3 files unchanged**; mypy **Success: no issues found in 3 source files**. Recorded statuses `pytest=0 coreutils=0 black=0 mypy=0 diff=0`. Coreutils and diff checks were silent. Warnings are pythonjsonlogger relocation and LangGraph pending allowed_objects default. Coreutils also ran silently after every intermediate pytest command. Scoped source was reviewed through edits/read output; the safety module is already untracked, so HEAD diff cannot represent its additions alone.

## Context, boundaries and remaining HOLD

Consulted supplied AGENTS/CLAUDE/docs RESEARCH, root RESEARCH, routing/scope-plan, 138/139 receipts, safety123 current/history, actual bootstrap supervisor/writer/audit implementation, entry publish wiring and root isolation. Consulted KB Welcome, Slo README/gotchas and os ROLE/README/workloads; canonical B fixture/identity requirements at lines 1880–2070 were read only. Selected shared engineering routing/testing/ownership, coding rules/cadence/declarative, Python root/declarative/naming-argument/docstrings and workflow counting guidance. Some oversized context reads were truncated; this is not a claim of a complete remaining context/mutation-map audit. No dedicated Python process skill is present in the supplied manifest; existing PROCESS supervisor contract governs this adapter test scope.

**Both requested finite proofs are READY.** Remaining opened-FD matrix, broad mutation reconciliation and remaining read audit are separate unfinished work. Parent-positive wiring, positive Herdr-family runs and full `make` remain **HOLD** and were not run. No old unsafe probe, real provider, Herdr, window, live/global/system/spec/other-worktree changes; no agents, commit, push, PR, reset, clean or stash. This is not atomic filesystem confinement or malicious-Python sandbox proof. No shared workflow status was changed.
