# T6 harness cleanup 125 — INCOMPLETE; HOLD ACTIVE

Same unfinished turn 1; started 1, completed 0, historical partial 1, supplied dispatch 125, retries 0. User turn/dispatch limits unlimited. No agents dispatched. No independent acceptance claimed.

## Bounded implementation

Changed only `tests/integration/herdr_restore_process_bootstrap.py` and `tests/integration/test_herdr_restore_harness_safety.py`, plus this receipt and `t6-125-*` logs. Existing parent/entry/contained negative target 124 remain unchanged. No positive family, old probe, full make, live provider/Herdr/window, system write, install or Git mutation executed.

- Relative mutating os.open with dir_fd now forwards a validated absolute path, letting the ordinary audit callback validate the same target without an ambient bypass token. A real safe open at an injected audit seam exercises cooperation.
- Added audit admission for chown/utime and setxattr/removexattr. Negatives only invoke policy; they never execute privileged metadata syscalls.
- Added **not yet wired** `OwnedProcessRun`: fresh process session, regular temp-owned stdout/stderr captures (no inherited-pipe deadlock), finite polling timeout using waitid/WNOWAIT, finally cleanup, and direct-child wait. Its unreaped leader is intended to pin the owned process-group identifier until signal; no process-name matching or host-wide scan.
- Recording-only tests cover waitable versus already-reaped signal cutoff and timeout capture retrieval. No real dummy process or descendant was launched. The code is NOT acceptance-ready and must not be adopted merely because these units pass.

## Evidence

Cwd `/root/Code/slo-94-herdr-integration/slo`. Approved `PYENV_VERSION=slo-harness`; `pyenv which python` resolved `/root/.pyenv/versions/slo-harness/bin/python`. Every test command:

```sh
export PYENV_VERSION=slo-harness
bash docs/implementation/94-herdr/t1-dao-check.sh tests/integration/test_herdr_restore_harness_safety.py
```

Reviewed script uses synthetic fallback, disabled Herdr/windows, existing root isolation. No development env sourced.

| Increment | RED | GREEN |
|---|---|---|
| relative audit cooperation + metadata admission | 5 failed / 89 passed | 94 passed |
| retained-child cleanup decision | 2 failed / 94 passed | 96 passed |
| timeout capture retrieval | 1 failed / 96 passed | 97 passed |

Receipts: `t6-125-{red1,green1,red2,green2,red3,green3,final}.{log,exit}`. Each implementation increment stayed below approximately 50 substantive harness lines before the safe unit module was rerun. Final after scoped formatting: **97 passed, 2 warnings, exit 0** (35 safety units + 62 surrounding DAO/projection tests). Scoped Black check exit 0. `dpkg -V coreutils` ran after each test command; final `t6-125-coreutils.log` is empty, exit 0. No mypy/full-suite evidence claimed.

## Precise remaining blockers

1. Parent still uses subprocess.run; the new owner is not wired. Before wiring, restrict/validate launch inputs and prove real contained dummy child/grandchild marker barriers, unrelated owned sentinel survival, timeout/error/cancellation and no surviving descendants. Current mock tests are not this proof.
2. Process-group cleanup kills inherited-group descendants but does not reap grandchildren or contain escaped sessions/groups. Need a deliberate descendant ownership/reaping contract and test before READY. No arbitrary PID kill fallback is allowed. Concurrent external reaping must remain excluded or guarded; WNOWAIT pin assumptions need explicit proof.
3. Timeout output currently snapshots before finally cleanup, so final cleanup-time bytes can be missed. General errors/cancellation lack a structured retrieved-output result. Capture size is not bounded; cleanup failure can mask the original exception. These need correction and failure-path tests.
4. Mutation inventory remains incomplete: duplication/reuse, preopened buffered handles, deleted descriptors/root replacement, additional non-audited native mutation surfaces. Metadata tests prove only policy routing, not installed hooks.
5. Actual installed subprocess/async/exec/spawn refusal dispatch remains unproved. No forbidden-command/system-tool negative execution is authorized. New synthetic regular scripts must install guards before any mutation.
6. Generated fake capture still needs opened-FD identity verification and substitution proof. Existing entry was not imported or executed.
7. Old probe retains unsafe network/missing-command attempts; it was not run and must be replaced before future use. Contained sibling target from 124 is preserved.

This is capability-based accident prevention, **not a malicious-code sandbox** or atomic filesystem confinement. No READY bounded-cleanup claim. **HOLD remains active; parent must explicitly lift it on complete safety proof before any positive family, and no full-make authorization follows automatically.**

## Context consultation limitations

Consulted supplied AGENTS/CLAUDE/docs RESEARCH, root RESEARCH, routing/scope-plan, actual bootstrap/parent/safety module and entry first 150 lines, 124 containment receipt, engineering routing/ownership/testing, cadence, Python root/declarative/Faux and workflow counting. Canonical H B isolation lines 1872–2045 and C 2080–2175 read-only consulted. OS ROLE/README read. Combined skill read truncated the coding-rules header; KB Welcome/slo reads were mistakenly redirected rather than ingested, and workload detail was not read. These are disclosed prerequisite gaps, not claimed complete context review. No KB/shared-status/spec edits made.
