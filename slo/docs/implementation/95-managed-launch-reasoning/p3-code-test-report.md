# Feature 95 — dispatch 3 partial P3 evidence

**Verdict: REVISE — P3 incomplete.** This is turn 1, dispatch 3/20, same Code+Test phase; retries 0, nested dispatches 0, completed workflow turns 0. No P4/P5 or independent review/completion acceptance is claimed.

## Delivered

1. Reproduced the requested static defect before editing (`p3-static-before`: exit 1, Task[Endpoint] incompatible with Task[IO[bytes]]).
2. Corrected only the typed fixture seam in `test_relaunch.py`: the local endpoint now subclasses `BytesIO`, its close delegates to the binary stream before setting the existing threading event, and `late_opener` returns `IO[bytes]`. All prior wait/release/cleanup/no-spawn assertions remain intact. No production changes.
3. Created `test_managed_launch_reasoning.py` with a small, immediately tested foundation: canonical imported history-root agreement; local SLO_PARENT_PID removal; plugins disabled; inherited provider keys removed; clean rooted cwd; catalog shutdown/reset; and a separate finite real capture-writer ownership/EOF/drain characterization using CaptureLaunchContainment. No owner/child composed journey exists yet.

The two foundation tests initially passed. They characterize existing behavior; no artificial production RED or production change was introduced. The capture test uses only registered finite writer helpers, retains their Popen objects, checks exact writer PID ownership, closes endpoints in finally and performs bounded wait(timeout=25). It never invokes CleanDrainScenario, installs parent audit hooks, duplicates FDs or launches an agent workload.

## Receipts

All commands ran from the requested application cwd through unchanged `run-gate.sh`, with scoped approved slo-harness Python 3.11.7 VIRTUAL_ENV/PATH. Each prefix below has exact `.command`, `.log`, `.exit` files in this directory.

| Prefix | Result |
|---|---|
| p3-static-before | 1 mypy error in test_relaunch.py; exit 1 |
| p3-static-correction | scoped eight-file mypy, no issues; exit 0 |
| p3-relaunch-correction | 15 passed, 2 warnings; exit 0 |
| p3-root-first | 1 passed, 2 warnings; exit 0 |
| p3-capture-foundation | 2 passed, 2 warnings; exit 0 |
| p3-foundation-static | both changed test modules mypy clean; exit 0 |
| p3-partial-surrounding | entire orchestrator partition + dispatcher/headless/reasoning/executors: 873 passed, 16 warnings, 45.64s; exit 0 |
| p3-partial-black | 2 files unchanged; exit 0 |
| p3-partial-diff | git diff --check, empty output; exit 0 |
| p3-partial-binary-integrity | dpkg -V coreutils, empty output; exit 0 |

Surrounding log retains RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited, including post-suite output, plus dependency deprecations. No warnings were suppressed. This is not the P5 full non-E2E/static gate.

## Requirement mapping / remaining implementation

| Obligation | Current evidence |
|---|---|
| P1/P2 scoped static defect | Reproduced and corrected; eight-file static and relaunch suite green |
| §7.7 canonical roots/N1/isolation | Foundation root test only |
| §7.7 finite capture ownership | Separate real writer foundation only, not managed-launch endpoint observation |
| R3/R4/R6: real owner/bootstrap/lazy graph → captured argv → serial real child CLI/session/factory | NOT IMPLEMENTED |
| R7/C1: actual PID/store injection, real status/inbox/phase/reconciliation correlation | NOT IMPLEMENTED |
| R6: three clamp cases, preference/seed, real HTTP-backed OpenRouter admission | NOT IMPLEMENTED |
| R5/R7/C2: invalid-before-registration, unknown constructor, preparation failure, lazy credential failure | NOT IMPLEMENTED |
| R7 supported abort with injected killer/probe/scheduler | NOT IMPLEMENTED in composed module; retained surrounding regressions pass |
| R9 actual phase task/argv medium versus high parent | NOT IMPLEMENTED in composed module; P2 surrounding coverage retained |

Continue at the owner fixture increment: exact typed graph factory recorder returning LLMBuildResult, synthetic stored OpenAI credential, class-preserving store constructor/probe injection, recording spawn and delegated launch factory, real bootstrap and owner invocation. Add real endpoint observation/final cleanup around that launch before composing the child. Then add serial worker-thread CliRunner with exact argv[3:] and recorded-env replacement, typed delegating runner initializer, real child configuration/readiness, phase transport-only stub and all exact §8 positive/negative observations. Each listed case remains mandatory; do not substitute the foundation tests for C1/C2.

## Scope, reads, limitations

Branch verified `feature-95-managed-launch-reasoning-20261017`. Existing P1/P2 changes untouched except the requested test_relaunch seam. No source specs, past reports, other worktrees, production lifecycle, global environment, installed files, commits/push/PR/publish or nested agents changed.

Read complete routing plan, P1/P2 report, accounting, engineering spec (including truncated tail separately), overview and tasks. Read the entire 779-line capture safety helper before execution, canonical state isolation and root conftest, named workflow/cadence/coding rules, shared engineering policies, Python root/types/docs/agent-testing, root research and supplied project context. KB and round2/context combined reads had truncated openings; their visible substantive contracts were consulted, but this dispatch does not claim every selected-route skill or supporting context file was fully reloaded. Complete those bounded reads before expanding composition.

Deviation: this dispatch delivers the static correction and tested P3 foundations, not the requested full P3. The large context/read output leaves the remaining composition for continuation; no policy dispatch cap or unsupported budget stop is asserted. No substantive contract conflict has been identified. Preserve this exact partial evidence and continue the same phase; do not mark P3 COMPLETE or advance to P4 based on the green surrounding suite.
