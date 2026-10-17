# Feature 95 — P1/P2 Code+Test handoff

**Verdict: REVISE.** Runtime P1/P2 implementation and affected tests pass, but the scoped static check remains nonzero; no silent waiver and no whole Step 1 READY claim. P3–P5 remain pending. Turn 1 started/current dispatch 2/20; unlimited legitimate revision turns, retries consumed 0, nested dispatches 0. No completed workflow turn or independent review.

## Scope and authority

Work remained in `/root/Code/slo-managed-launch-reasoning-20261017`, application cwd `slo`, branch `feature-95-managed-launch-reasoning-20261017`, base `d0e3a756689f2675e5507034d43cd8b272d3c6b8`. Consumed routing-and-plan.md completely, full overview/engineering/tasks/task-breakdown-report, round2 verification, prerequisite/context/revision reports, supplied AGENTS/CLAUDE/docs RESEARCH and root RESEARCH. Read checkout shared engineering, generic coding/declarative/coverage/cadence, exact Code-Test-Review workflow/accounting, Python root/types/declarative/docstrings/tool/graph-test and complete CLI module guidance. KB Welcome, slo README/gotchas/headless consulted read-only. Project-specific JSON-string factory, same-owner extraction and existing CLI/linear graph contracts specialize unrelated generic examples. No runtime owner expansion.

Accounting file moved from application `todo/accounting.md` to `docs/implementation/95-managed-launch-reasoning/todo/accounting.md`; historical counters retained and current dispatch addendum appended. Routing references corrected. No unrelated todo files touched.

## Implementation / requirement map

| Requirements | Implemented evidence |
|---|---|
| R1/R5, AC1 | Canonical nullable ReasoningLevel schema; runtime extra forbid; fixed no-input-echo JSON validation handler. Separate real provider conversion test, invalid token/type/unknown-key matrix, ToolCall id/error status tests. |
| R2/R4, AC2 | Factory TypeAdapter validates before root/store dependencies; immutable fallback; explicit seven values/off, omitted/null medium, both absent/None legacy factory forms, high then omitted medium; exact one unchanged argv pair and identities. |
| R3, AC3 | Sole bootstrap keyword; three bound inputs and shared status/launch store identity; real config-backed setting switches, real lazy factory rebuild, actual replacement-config method/fresh owner/tool, offline pending-startup adoption retains provisional snapshot. |
| R5 graph boundary | Real executor and next Faux model input receive fixed validation JSON, no handle/spawn. Existing routing fixture explicitly forwards typed default_reasoning_level and handle_store, no swallowed kwargs. |
| R6 bounded adapter | Captured managed argv enters real CliRunner/dispatcher; explicit high overrides saved low, explicit model clears configured pool. This captures child config, NOT composed child inference acceptance (P3). |
| R8/R9, AC6 | Initial high handle has no reasoning field; real resume argv omits flag and different preference remains eligible. Real high parent plus phase medium/None produce independent argv. |
| R7 bounded retained regression | Same-class `_launch` move preserves guard/registration/spawn/resource bodies; capture failure/close/PID conflict/abort race tests now carry non-null high. Full orchestrator partition passes. Full registered child journey is P3, not claimed. |
| R10/R11 | Only corresponding launcher/bootstrap/dispatcher docstrings changed. P4 guidance/index and P5 complete static/full gates remain pending. |

Production behavior changes only launch_tool.py and bootstrap.py; dispatcher docstring only. No session/provider/catalog/CLI parser/lifecycle/persistence changes.

## Exact command receipts and cadence

Every gate has `<name>.command`, `.log`, `.exit` alongside this report. All were invoked with `bash docs/implementation/95-managed-launch-reasoning/run-gate.sh <name> <command...>` from the application cwd. The retained script records command-local approved VIRTUAL_ENV/PATH, PYTHONDONTWRITEBYTECODE, PYTHONPATH and exact Makefile test fallback (tests.env absent). Poetry pytest reports Python 3.11.7 and approved slo-harness executable in argv assertions. No install/global environment edits.

| Receipt prefix | Command scope | Actual result |
|---|---|---|
| p1-schema-red | pytest launch TestReasoningSchema | 16 failed; missing schema field and ignored invalid args |
| p1-schema-green | pytest whole launch module | 49 passed |
| p1-default-red | pytest TestReasoningDefaults | 16 failed; absent factory keyword |
| p1-default-green | pytest whole launch module | 65 passed |
| p1-transport-red | pytest TestReasoningTransport | 10 failed, 4 passed; missing flag; legacy omission initially green |
| p1-transport-green | pytest whole launch module | 79 passed |
| p1-extraction-green | pytest whole launch module immediately after coherent same-owner body move | 79 passed; refactor characterization, not manufactured RED |
| p2-binding-red | pytest whole bootstrap module | 1 failed, 13 passed; missing default binding |
| p2-binding-green | pytest whole bootstrap module | 14 passed |
| p2-routing-characterization | pytest whole routing module | 6 passed initially |
| p2-graph-characterization | pytest whole routing module | 7 passed initially |
| p2-switch-characterization | pytest whole bootstrap module | 1 failed, 15 passed; fixture used env values cached by config |
| p2-switch-green | same, synthetic isolated CredentialStore rows | 16 passed; no production change |
| p2-pending-characterization | whole bootstrap | 17 passed initially |
| p2-cli-characterization | whole dispatcher | 37 passed; retained coroutine warnings |
| p2-phase-characterization | whole process | 2 failed, 75 passed; new fixture omitted required workdir |
| p2-phase-green | same, tmp workdir added | 77 passed; no production change |
| p2-resume-characterization | whole relaunch | 15 passed initially |
| p1-p2-affected | six affected modules after docstrings/high regressions/format | 232 passed |
| p1-p2-orchestrator | full orchestrator partition | 720 passed |
| p1-p2-mypy | scoped eight-file mypy | 36 errors; new narrowing/type defects corrected |
| p1-p2-mypy-followup | same | 1 error remains in unchanged late-opener test |
| p1-p2-retest | six modules after type corrections | 232 passed |
| p1-p2-final-tests | full orchestrator + dispatcher after final edits | **757 passed, 19 warnings, 44.77s; exit 0** |
| p1-p2-final-mypy | same scoped eight-file mypy | **1 error; exit 1**, below |
| p1-p2-black-check | eight touched implementation/test files | 8 unchanged; exit 0 |

Production increments were small schema/handler, factory validation, transport/helper, then the separately tested coherent move of the existing ~44-line launch body plus signature/docs/bridge (not disguised as net-new lines). Bootstrap adds one behavioral line. Tests preceded production behavior. Later characterization tests did not require production changes. Each increment ran its full affected module before subsequent work. Formatter limited to touched files; no bulk repository formatting.

## Outstanding static finding (not waived)

`p1-p2-final-mypy.log`:

```text
tests/agents/slo_agent/orchestrator/test_relaunch.py:274: error: Argument "opener" to "_close_late_capture_result" of "WorkflowRelauncher" has incompatible type "Task[Endpoint]"; expected "Task[IO[bytes]]"  [arg-type]
Found 1 error in 1 file (checked 8 source files)
```

This expression/test body is unchanged in the diff. It is a source-local pre-existing defect, **not independently reproduced on a clean base**, and is not a green/waived gate. Next author should reconcile the test endpoint type at its existing seam without weakening cleanup assertions, then rerun scoped static/affected gates; full `make lint` remains P5. Existing dispatcher coroutine warnings are retained verbatim in logs, not summarized away.

## Safety / preservation

Read complete capture_test_safety.py and canonical state isolation before lifecycle runs; inspected real finite writer/FD/relaunch helper boundaries. Existing suites use temp-owned finite Python helper processes, not actual model/workflow workloads; workload creation/signals are stubbed in changed tests. No provider network calls, real terminal windows, installed files or source specs modified. Real finite helper subprocess testing is not native orchestrator/provider acceptance. No irreversible parent audit hook added. `dpkg -V coreutils` printed nothing after lifecycle partition and final verification. `git diff --check` exit 0. Read-only hash verification passed all 19 protected spec/policy artifacts from routing plan. No skipped/disabled tests or weakened retained assertions.

## Pending handoff

- P1/P2 runtime tests green; scoped static finding above keeps this handoff REVISE rather than unqualified COMPLETE.
- P3: new composed fixture/module, real child CLI/session/factory clamp matrix, legacy preference/seed, deferred real local HTTP OpenRouter admission, complete correlated lifecycle success, all exact C2 failure rows and supported abort. Existing mocked-agent routing fixture is NOT a substitute.
- P4: narrow guidance/skill/schema examples, accounting-source check, docs and generated index. None performed beyond corresponding docstrings.
- P5: full focused surrounding gates, full Black/mypy/skills/index/full non-E2E gate and manifest. No full-suite claim here.
- Independent Step2 review and fresh Step3 completion remain required. No commit/push/PR/publish or nested/detached agent launched.
