# T6 supervisor handoff 129 — INCOMPLETE; positive family HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 129, retries 0. Effective turn and dispatch budgets unlimited. No agents dispatched, no independent review or completed turn claimed.

## Scope and changes

Only bootstrap helper and safety test source changed, plus this receipt and the current section of safety-123. Positive parent and entry remain unwired. Existing unrelated work preserved. No full make, positive family, old probe, real Herdr/provider/window, global configuration, system executable, spec, other-worktree or Git mutation performed.

`OwnedSupervisor` publishes READY with its PID through a private inherited pipe after installing its TERM handler. Parent stop refuses before this evidence, before even querying process status. EOF, wrong PID and extra bytes fail startup admission. The existing real descendant timeout test now crosses this handshake.

`RetainedSupervisor` holds the exact Popen object, directory and handshake descriptors. The context no longer automatically removes captures while the process returncode is unknown. `drain_supervisor` permits a later bounded join and directory removal. An injected KeyboardInterrupt followed by failed wait preserves the original exception object and retained directory; the test subsequently performs a real join. Directory cleanup failure also preserves the original exception and retains the resource. Failed spawn closes the allocated handshake pipe.

## Actual test-first evidence

Cwd: `/root/Code/slo-94-herdr-integration/slo`. Verified approved `PYENV_VERSION=slo-harness`, Python 3.11.7. All pytest commands used explicit synthetic fallback:

```sh
export PYENV_VERSION=slo-harness SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
poetry run pytest -q -m 'not e2e' tests/integration/test_herdr_restore_harness_safety.py
```

- READY refusal RED: 1 failed, 51 passed; GREEN: 52 passed.
- Retained join/original exception RED: 1 failed, 52 passed; GREEN: 53 passed.
- Invalid handshake and cleanup exception increment: 1 failed, 56 passed; GREEN: 57 passed. Invalid handshake rows were already green; no red-first claim for those rows.
- Spawn pipe cleanup RED: 1 failed, 57 passed; final GREEN: **58 passed, 2 warnings, 4.47s**.
- Final `poetry run black --check` on the two owned Python files: 2 unchanged, exit 0.
- Final `poetry run mypy --follow-imports=skip` on those files: no issues, exit 0.
- `git diff --check`: silent. Both source files remain pre-existing untracked files, so this does not cover their content; source changes inspected directly.
- `dpkg -V coreutils`: silent after tests, including final run, exit 0.

No separate log files written; tool outputs hold the exact failures and summaries. First implementation increment was below approximately 50 substantive lines and all 51 existing units remained green before the next increment.

## Remaining lifetime blockers — NOT READY

1. Supervisor-side status/identity/signal faults still escape its cleanup finally before reaping. A failed TERM must not skip KILL/reap; a failed identity check needs retained child-side ownership, not interpreter exit. These boundaries need safe actual-resource injection and recovery.
2. A parent can retain the object, but the exception carries only a note, not a typed retained-owner reference. Caller-held owner is necessary; ephemeral-call ownership handoff is not proved. Repeated interruption and concurrent run/resource-context entry are not protected.
3. Pipe close faults may replace the primary failure; descriptors are numeric, not identity-checked on retry. Capture open/write/read/close failures and status/signal failures lack the complete requested matrix. The initial retained-join RED exposed the old unsafe automatic temp removal; that failing version did not have a working recovery method, so it is not a cleanup-proof receipt.
4. READY is one-way. Parent timeout before READY waits for the supervisor's internal deadline without signaling, but child startup failure and interrupted/partial handshake need explicit composed tests. A TERM received between READY and workload spawn sets stop but does not prevent spawn. No exact startup-failure contract is certified.
5. Child waitpid remains blocking; escaped groups remain outside fixture contract. No bounded retained child-side join protocol exists. Capture bounds, root/script substitution and receipt namespace issues from 128 remain.
6. Mutation/real-exec capability proof is still open independently of supervisor lifetime. Positive Herdr family, parent/entry wiring and full make stay HOLD.

The requested cohesive finite-boundary closure was not achieved. The green safety module is bounded incremental evidence, not supervisor-family approval.

## Context and read limitations

AGENTS/CLAUDE/docs RESEARCH supplied in context; root RESEARCH, routing/scope plan, 128 and current safety-123 read. Consulted checkout engineering routing/ownership/testing, coding rules/cadence, Python/declarative and canonical workflow SKILL; some combined reads were truncated, and not every mandated style companion was reread. KB ROLE and README/workloads, Welcome/slo README/gotchas consulted; canonical B/C safety matches searched read-only, not fully ingested. An early read command unnecessarily redirected KB text to `/tmp/unused-read-output`; this was outside the requested document write set and is disclosed, not claimed compliant. No KB/shared workflow status edits.
