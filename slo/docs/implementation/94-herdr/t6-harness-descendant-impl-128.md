# T6 descendant implementation 128 — INCOMPLETE; positive family HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 128, retries 0. User turn/dispatch limits unlimited; no agents dispatched. No completed review or workflow acceptance is claimed.

## Scope and implemented behavior

Changed only `tests/integration/herdr_restore_process_bootstrap.py`, `tests/integration/test_herdr_restore_harness_safety.py` and these local receipts. Positive parent and application entry remain unchanged. All prior work preserved.

`OwnedSupervisor` now actually runs in a disposable isolated Python interpreter. Linux PR_SET_CHILD_SUBREAPER is set only there, after platform/session and contained-launch checks; never in pytest or the running agent. Unsupported platforms refuse before spawn. Workload starts a separate session. The supervisor retains its unreaped workload leader through TERM and KILL, so even early application exit cannot permit PID/group reuse before the final signal. It then calls waitpid until ECHILD, recording the actual PID/exit statuses in the contained `reaped.json` receipt. This is observed reaping, not an inference from kill success or /proc absence. Escaped groups are outside this bounded fixture contract.

`OwnedProcessRun.run_supervised` creates a contained regular wrapper, uses the current isolated Python, explicit environment with Herdr/windows disabled and regular capture files. Parent timeout requests TERM only against its exact tracked, waitable, session/group-checked supervisor, then waits for the supervisor. The supervisor converts TERM to orderly workload teardown rather than dying with the workload. Timeout output is collected after joining. The old direct-child helper is not replaced or represented as descendant-safe.

Real tests use newly written temp-owned Python leader/grandchild files, a grandchild ready marker, and explicit recorded PID. Three cases observe early leader exit with surviving grandchild, timeout, and TERM-ignoring descendant killed with status -9. Normal descendant termination is observed as -15. A separate-session, same-test-parent sentinel remains alive through each cleanup, is stopped using its own contained marker, and is explicitly waited; subsequent waitpid raises ChildProcessError. Parent-timeout integration observes grandchild -9 and supervisor already reaped. No provider/network/Herdr/terminal commands are used.

## Genuine remaining safety blockers

Do NOT wire the positive parent yet. Inspection after green tests found these unclosed cases:

1. Parent deadline can expire before the wrapper has installed its TERM handler. A startup-ready handshake is required before parent TERM admission; current .5-second test proves the exercised ready path, not arbitrary scheduling safety.
2. Supervisor waitpid draining is blocking. A descendant escaping its group or an unexpected uninterruptible wait can exceed the parent join bound. If that happens, run_supervised currently propagates the join exception and removes its temporary wrapper/capture directory without retaining an explicit recoverable owner. No failure-injection proof closes this path.
3. Cleanup exceptions can replace an original timeout/KeyboardInterrupt. Startup/spawn failure, repeated interruption, receipt-write failure, concurrent reuse, and process identity refusal branches need explicit safe-unit proofs. Current single-use check is not a concurrency primitive.
4. Fixed `reaped.json` is evidence for these serial temp-root fixtures, not a general concurrent/repeated-run receipt namespace. Capture bounds and opened-FD/root/script substitution races remain outstanding from 127.
5. Guard mutation/real exec capability proof and legacy unsafe-probe replacement remain HOLD. No positive Herdr family or full make was run.

These are concrete lifecycle gaps, not a turn/dispatch/unit cap. The new implementation materially closes exercised descendant termination/reaping paths but is NOT cleanup-family READY or feature acceptance. No zombie-free claim is made beyond the observed wait receipts for these controlled children.

## Test-first cadence and actual receipts

Cwd `/root/Code/slo-94-herdr-integration/slo`; `PYENV_VERSION=slo-harness`; `pyenv which python` returned `/root/.pyenv/versions/slo-harness/bin/python`. Every pytest invocation used the explicit synthetic fallback before imports:

```sh
export PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
poetry run pytest -q -m 'not e2e' tests/integration/test_herdr_restore_harness_safety.py
```

- First RED: 3 failed, 45 passed, 2 warnings, 2.43s; missing OwnedSupervisor, before any new descendant spawn.
- First implementation GREEN: 48 passed, 2 warnings, 3.70s.
- Sentinel/platform/session refusal increment: 50 passed, 2 warnings, 3.75s. These additive tests were not separately observed RED.
- Parent integration RED: 1 failed, 50 passed, 2 warnings, 3.86s; missing run_supervised.
- Parent implementation GREEN: 51 passed, 2 warnings, 4.41s.
- Parent TERM request/handler refinement final GREEN: 51 passed, 2 warnings, 4.42s. This refinement was not separately observed RED; do not describe every increment as strict red-first.

Final checks:

```sh
poetry run black --check tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
# 2 files would be left unchanged; exit 0
poetry run mypy --follow-imports=skip tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
# Success: no issues found in 2 source files; exit 0
git diff --check
# silent; exit 0 (these two pre-existing untracked files are not covered)
dpkg -V coreutils
# silent; exit 0
```

Black was applied only to the two changed files before the final check. Source edits were inspected directly; no full-project lint or untracked-file Git diff coverage is claimed. Tool outputs are the execution receipts, not separately persisted log files.

## Context and boundaries

AGENTS/CLAUDE/docs RESEARCH supplied in context; root RESEARCH and the three process files, current safety units and 127 receipt read. Consulted checkout engineering routing/testing/ownership, coding rules/cadence, Python/declarative/type/docstring and canonical workflow SKILL guidance. Test category: real disposable process adapter/lifecycle proof plus isolated refusal units; no database/provider recipe. Consulted KB OS ROLE, README/security guardian material, Welcome and slo README/gotchas. Canonical Herdr B.2 functional restore and C acceptance excerpts consulted read-only; no claim of exhaustive spec reread. Some combined reads were output-truncated.

No host/global configuration, system executable, spec, other-worktree, production, shared parent state, commit/push/PR/reset/clean/stash change. Test subprocess lifecycle only; no host process search/termination. No live certification or independent review. Parent/entry remain unwired pending the blockers above.
