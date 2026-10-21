# T6 process 126 — INCOMPLETE; HOLD ACTIVE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 126, retries 0. User turn/dispatch limits unlimited; no agents dispatched. No independent acceptance.

## Scope and actual changes

Changed only `tests/integration/herdr_restore_process_bootstrap.py` and `tests/integration/test_herdr_restore_harness_safety.py`, plus this document and `t6-126-*` receipts. Parent, entry and parity harness unchanged. No old probe, positive family, full make, live provider/Herdr/window, installs, global settings or Git mutations.

OwnedProcessRun now refuses cleanup of an object not captured at its own spawn boundary; before signaling it checks waitable-child capability and actual PGID/SID equal to leader PID. This relies on exclusive reaping ownership and does not protect against another thread externally reaping the child between checks. Launch admits current sys.executable with `-I -B` and a contained regular script, rejects unknown environment names, validates state paths, and adds disabled Herdr/windows without inheriting environment. This is not yet a registered script-identity capability across launch races. Timeout captures are retrieved after cleanup rather than before it.

Two actual finite dummy Python child cases now run: normal exit and timeout. Their regular temp-owned scripts install ProcessSafety before their assertions/output, use no providers or Herdr, print separate flushed stdout/stderr markers, and the timeout dummy sleeps at most two seconds even if cleanup regresses. Actual waitpid raises ChildProcessError after completion, proving direct-child reaping. **No grandchild has been launched or reaped in this increment.** No unsupported zombie-free family claim.

## Required remaining cleanup work — blocks wiring

| Family | Status |
|---|---|
| Unowned object / SID / PGID refusal | Recording seam proof, no live negative signals |
| Actual direct child normal/timeout, partial output, reap | Passed |
| Grandchild alive after leader exits; actual group termination | NOT PROVED |
| Descendant reaping by correct Python parent or dedicated disposable subreaper | NOT IMPLEMENTED; direct Popen.wait cannot reap grandchildren |
| Unrelated owned sentinel survives | NOT PROVED |
| TERM grace then bounded KILL escalation | NOT IMPLEMENTED; current helper uses immediate SIGKILL |
| Spawn failure / wait or capture error | NOT PROVED |
| Synchronous KeyboardInterrupt cancellation | NOT PROVED; no asyncio cancellation contract or signal handler installed |
| Cleanup error preserving original failure and output | NOT IMPLEMENTED; cleanup can mask primary exception |
| Bounded capture bytes / post-open capture FD identity | NOT IMPLEMENTED |
| Launch script registration/identity and concurrent reuse exclusion | NOT COMPLETE |
| Parent wiring | DELIBERATELY NOT DONE; dummy family proof prerequisite unsatisfied |

No communicate() is used: captures are regular files. Its corresponding failure surface is polling/wait/read failure, which still needs tests. A deliberate descendant contract is required before launching long-lived grandchildren: group kill is not reaping, and escaped groups/sessions are outside this helper. Do not claim orphan adoption without an actual process-local adopter and wait proof. No broad PID scans or arbitrary PID fallback.

## Other HOLD rows retained from 125

Descriptor duplication/reuse and preopened buffered handles; deleted descriptors/root replacement; non-audited mutation inventory; actual installed subprocess/async/exec/spawn refusal; fake capture opened-FD identity/substitution; replacement of legacy unsafe probe. Current parent still uses subprocess.run and must not be executed. Positive family remains forbidden until ALL guards pass and HOLD is explicitly lifted; no full-make authorization follows.

## Exact safe-unit receipts

Cwd `/root/Code/slo-94-herdr-integration/slo`; `PYENV_VERSION=slo-harness`, `pyenv which python` → `/root/.pyenv/versions/slo-harness/bin/python`. Each test shell exported the tracked synthetic fallback explicitly:

```sh
export PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
poetry run pytest -q -m 'not e2e' tests/integration/test_herdr_restore_harness_safety.py
```

No surrounding DAO tests or old probe were selected. All implementation increments below 50 substantive harness lines, each followed by whole safe-module green.

| Receipt | Result |
|---|---|
| red1 / green1 | 3 failed,35 passed → 38 passed |
| red2 / green2 | 6 failed,37 passed → 43 passed |
| red3 / green3 | 1 failed,42 passed → 43 passed |
| red4 / green4 | 2 failed,43 passed → 45 passed |
| final after scoped Black | 45 passed,2 warnings,2.32s; exit 0 |

`t6-126-{red1,green1,red2,green2,red3,green3,red4,green4,final}.{log,exit}` retain output/status. RED exits 1; GREEN exits 0. The red2 timeout recording test failed because newly expected validate_launch did not exist; the five launch refusals reached mocked Popen then real waitid on a Mock, not real subprocess execution.

Static commands (same interpreter):

```sh
poetry run black --check tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
poetry run mypy --follow-imports=skip tests/integration/herdr_restore_process_bootstrap.py tests/integration/test_herdr_restore_harness_safety.py
git diff --check
dpkg -V coreutils
```

Black exit 0; own-file mypy **exit 1: 7 errors in 2 files**, unwaived (TimeoutExpired.output bytes annotation; three patch.multiple overloads; audited_open object argument; two recording stream.write object types). See full t6-126-mypy.log. git diff --check exit 0, but untracked files are not covered by that Git check. Coreutils ran after every safe test command; final log empty, exit 0. No full-gate evidence.

## Context and limitations

Consulted supplied AGENTS/CLAUDE/docs RESEARCH, root RESEARCH, routing/scope plan, current helper/safety/parent and entry first 150 lines; canonical B default guards 1872–2045 and C 2080–2175 read-only. Loaded checkout engineering routing/testing/ownership, coding rules/cadence, Python root/declarative/Faux, shared declarative and workflow SKILL. KB ROLE/README, access guardian rules, Welcome, actual slo/README (index absent), gotchas consulted. Oversized combined workload read truncated its beginning; no claim of full prerequisite ingestion or independent review. No KB/shared-status/spec edits.

Result is a partial direct-child safety improvement, **not the requested finite child/grandchild cleanup family**. HOLD ACTIVE; parent remains unwired.
