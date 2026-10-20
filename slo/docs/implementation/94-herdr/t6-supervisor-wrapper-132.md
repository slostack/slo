# T6 generated supervisor wrapper 132 — bounded wrapper READY; overall HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 132, retries 0. Effective turns and dispatch budgets unlimited; no agents dispatched or workflow acceptance claimed.

## Scope and design

Only bootstrap/safety tests and this receipt plus safety-123's current section changed. Existing partial work preserved. Plan: reproduce generated-entry capability loss with independently safe cleanup; retain the exact child-side capability through local drain; prove parent capture retention and explicit later join; run only the explicit safety module and scoped static/integrity checks. Positive families, full make and the old probe remain prohibited.

`OwnedSupervisor.run_entry` is the generated wrapper's lifetime boundary. It invokes once, catches `RetainedResourceError`, retains that exact exception/owner/resource on its stack, emits only fixed `SUPERVISOR_RETAINED`, and retries bounded 0.25-second local drains with a 0.1-second sleep. No respawn, repeat TERM/KILL or remote commands occur in this loop. Persistent ordinary drain errors leave the interpreter pending. Failed status output cannot terminate ownership. Closure returns failure status 125, never success. Existing SIGTERM handler installation still precedes READY; parent still owns capture lifetime and transfers its typed retained capability if its bounded join expires.

## Actual generated-wrapper proof

The regression instruments the actual generated `supervisor.py` bytes at their contained write boundary, not a replacement entry implementation. An actual isolated leader launches an actual same-group grandchild then exits without reaping it. The isolated supervisor adopts the grandchild. Persistent injected killpg/waitid/getpgid errors deny initial cleanup; a separate case fails stderr status output. Drain is barrier-blocked, records exact supervisor/resource identity, and bounds attempted drain count. A separately launched sentinel group remains alive throughout retention.

Parent invocation fails with `RetainedResourceError`, not success or temp-directory deletion. Its exact Popen is still alive and captured stderr is either the fixed status or empty when status writing fails; no private exception payload. Another explicit bounded release fails while the barrier remains closed and preserves the captures. Opening the barrier permits local ECHILD proof, two actual waitpid receipts, wrapper status 125, explicit parent join and capture removal. The sentinel exits only when its independent process observes the test-owned stop barrier and is explicitly joined; ECHILD is checked afterward.

RED safety: test-only atexit cleanup opens the barrier and drains the actual children even if the old generated wrapper lets the error escape. The grandchild also has a finite 20-second fallback. Tests write contained regular scripts/barriers only; no system links. No test uses saved descendant PIDs to signal. Existing supervisor signaling requires its waitable unreaped anchor and matching group/session; injected faults never grant permission.

## Test-first results and exact commands

Cwd `/root/Code/slo-94-herdr-integration/slo`; `pyenv which python` reported `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. All pytest runs used:

```sh
export PYENV_VERSION=slo-harness SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
poetry run pytest -q --tb=short -m 'not e2e' tests/integration/test_herdr_restore_harness_safety.py
poetry run black --check tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
poetry run mypy --follow-imports=skip tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
git diff --check
dpkg -V coreutils
```

Existing preimport HERDR stripping and terminal/Herdr guards unchanged. Child environments explicit, disabled and terminal-off; no providers/Herdr/windows.

- Initial RED: **1 failed, 64 passed**, 7.59s; expected retained capability absent, actual `subprocess.TimeoutExpired` escaped after the wrapper exited.
- Implementation: 26-line cohesive entry method plus generated call-site switch, below the approximately 50-line implementation increment.
- First rerun: **1 failed, 64 passed**, 17.54s. Test leader incorrectly waited/reaped its own grandchild, so supervisor receipt correctly had only one PID. Corrected fixture to exit without reaping, testing actual adoption instead of weakening the two-receipt assertion.
- GREEN: **65 passed**, 17.45s. Only then expanded four fault cases and sentinel/identity evidence.
- Expanded: **68 passed**, 48.59s. Black initially reported safety file formatting; scoped mypy already clean. Applied Black only to that authorized file.
- Final chained post-format gates: **68 passed, 2 warnings in 48.62s**, exit 0; Black **2 unchanged**; scoped mypy **no issues in 2 source files**; diff check and `dpkg -V coreutils` silent. All chained commands exit 0. Warnings: pythonjsonlogger module deprecation and LangGraph allowed_objects pending deprecation.

Tool transcripts retain command output; no separate log files intentionally created. Two overlarge read commands produced tool-managed spill files; they were not edited/deleted. The Python files are pre-existing untracked work, so git diff alone cannot review them: actual wrapper, entry and changed tests were inspected directly.

## Read scope and remaining limitations

Consulted supplied AGENTS/CLAUDE/docs RESEARCH, root RESEARCH and routing/scope artifacts, 131 receipt and actual bootstrap; shared engineering routing/testing/ownership, coding rules/cadence, Python root/style/declarative and workflow SKILL. Consulted KB entry, slo README/gotchas, os ROLE/README and workload detail. Some combined reads truncated; this is not a full fresh reread claim. No dedicated Python process recipe found. Canonical B default-suite isolation and C lifetime safety mapping read-only via discovered canonical specification directory (local specifications symlink absent). No spec modifications.

**READY is limited to ordinary-error retention in the generated wrapper family**, with actual leader/grandchild/parent proof. It is NOT general supervisor safety or permission to run the positive families. Startup/partial READY races, startup descriptor ownership/close faults, capture faults, repeated BaseException interruptions and concurrent owner entry/overwrite still need their own test-first guard proofs. SIGKILL/crash resilience is not provided by a Python strong reference. Current run_entry catches ordinary retry errors, not arbitrary repeated BaseException. No full-suite/static-baseline clearance or independent review claimed.

No production/global/KB/shared-workflow-status/other-worktree edits, live Herdr operations, agents, commits, pushes, PRs, resets, cleans or stashes. Overall safety HOLD remains.
