# T6 descendants 127 — INCOMPLETE; HOLD ACTIVE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 127, retries 0. Turn and dispatch budgets unlimited. No agents dispatched. This is not a completed descendant-cleanup family or independent acceptance.

## Actual delivered change

Only bootstrap and safety-test code changed, plus this receipt. Parent/entry/positive harness remains unchanged and unwired. Preserved all pre-existing partial work.

The exact seven mypy errors from `t6-harness-process-126.md` were reproduced and repaired without Any, ignores or casts:

- TimeoutExpired output/stderr are read as bytes after cleanup, matching the subprocess exception contract. CompletedProcess normal captures remain strings.
- Three ambiguous `patch.multiple(**wrappers)` sites now use a contextmanager with ExitStack and individually named patch.object operations; all patches restore at scope exit.
- audited_open accepts the real supported path union instead of object.
- Recording spawn narrows both owner-opened streams with TextIOBase assertions before writing.

This is a bounded typing/capture correction, **not implementation of the requested real grandchild/leader-exited cleanup**. No grandchild or sentinel process was launched. No zombie-free claim is made.

## Remaining finite-family blockers

| Required evidence | Status |
|---|---|
| Contained regular grandchild, ready barrier, actual timeout termination | NOT IMPLEMENTED/PROVED |
| TERM-ignoring grandchild followed by bounded own-group KILL | NOT IMPLEMENTED/PROVED |
| Actual descendant reaping by cooperating parent or isolated adopter | NOT IMPLEMENTED/PROVED |
| Leader exits while descendant survives | NOT IMPLEMENTED/PROVED |
| Durable group anchor until all descendants finish; no stale PID signaling | NOT IMPLEMENTED/PROVED |
| Separate-group same-parent owned sentinel survives, then is joined | NOT IMPLEMENTED/PROVED |
| Direct child normal and timeout capture/reaping | Existing tests remain green |
| Parent positive harness | UNWIRED; HOLD |

Design constraint, not implemented architecture: killing an entire group also kills an in-group supervisor, so it cannot itself furnish post-KILL descendant wait results. A dedicated disposable supervisor outside the workload group could own adoption and waits, while a retained child anchor pins the workload group until cleanup finishes. Any subreaper setting must be confined to that disposable interpreter, never pytest or a global host setting. It must prove wait results, not infer reaping from killpg success or process absence. The current helper still uses immediate group SIGKILL and only waits its direct child; it must not be used as descendant acceptance evidence.

Other HOLD rows from 126 remain: spawn/wait/capture failures, KeyboardInterrupt, primary-failure preservation on cleanup error, bounded capture and FD identity, script registration/identity races and concurrent owner reuse; descriptor duplication/reuse, buffered handles, deleted descriptors/root replacement, mutation inventory, real installed exec/spawn refusals and replacement of the legacy unsafe probe. No full-suite or positive-family authorization follows.

## Verification receipts

Cwd: `/root/Code/slo-94-herdr-integration/slo`. Approved `PYENV_VERSION=slo-harness`; `pyenv which python` resolved `/root/.pyenv/versions/slo-harness/bin/python`. No package installation or alias changes.

Commands used the explicit synthetic fallback:

```sh
export PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
poetry run pytest -q -m 'not e2e' tests/integration/test_herdr_restore_harness_safety.py
poetry run black --check tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
poetry run mypy --follow-imports=skip tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
git diff --check
dpkg -V coreutils
```

- Fresh mypy RED: `Found 7 errors in 2 files (checked 2 source files)`.
- Capture-contract RED: **3 failed, 42 passed**, exit 1. Two failures were intended timeout string-versus-bytes checks. The third was an accidental broad test edit changing a normal-result expectation to bytes; corrected it back to strings, not a product failure.
- GREEN after the small correction: **45 passed, 2 warnings**, 2.33s, exit 0; mypy `Success: no issues found in 2 source files`, exit 0.
- Scoped Black applied to those two files only, then check: **2 files would be left unchanged**, exit 0.
- Final post-format safety module: **45 passed, 2 warnings**, 2.29s, exit 0.
- Final scoped mypy: **no issues found in 2 source files**, exit 0. Follow-imports=skip is scoped evidence, not full-project lint.
- `git diff --check`: exit 0; both helper files are pre-existing untracked files, so this does not check their content. Reviewed changed sites directly and Black checked both.
- `dpkg -V coreutils`: silent, exit 0 after test runs and final checks.

Tool outputs in this session are the execution receipts; no extra log/exit files were written. No old probe, positive family, full make, real Herdr/provider/terminal, host process termination, prctl, commit/push/PR, reset/clean/stash, global or other-worktree edits occurred.

## Context/routing

Read supplied AGENTS/CLAUDE/docs RESEARCH and root RESEARCH, actual bootstrap/safety/parent code, 126 receipt and seven-error log. Consulted checkout engineering routing/testing/ownership, coding rules/cadence, Python root/shared and Python declarative guidance, named arguments/types/docstrings, and workflow SKILL. Test category is isolated guard units plus existing actual finite direct-child process tests; no database, provider or UI recipe is substituted for process evidence.

Consulted KB Welcome, slo README/gotchas and OS ROLE/README/guardian rules/workloads detail. Repository specifications link is absent; discovered and read canonical Herdr B default guards and B.2 two-process acceptance plus C test requirements read-only under `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr/`. No shared-status, KB or spec edits. Unlimited budget was not exhausted; this result is explicitly incomplete rather than an invented budget stop or READY claim.
