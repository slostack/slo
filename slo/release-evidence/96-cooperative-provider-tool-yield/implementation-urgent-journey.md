# 96.A.2 urgent journey — dispatch 11

## Verdict: INCOMPLETE — runnable delivery, failed lifecycle acceptance

The real local-client journey now reaches urgent application and a second provider request without releasing the held first/next token, on flat and tree history. **Do not accept this milestone:** the final explicit no-orphan assertion detects an intermittently stranded LangGraph `AsyncQueue.wait()` task after session close. Final feature command: **2 failed, 606 passed**, exit 1. The failing assertion remains enabled and cleans/joins the exact discovered test-owned handles before raising. No skip, xfail, exclusion or dependency modification.

## Authority and identity

Cwd `/root/Code/slo-message-queue/slo`; branch message-queue; HEAD remains `82c3f5c6de9345af34a673a3d975366ca8c1624c`. Original 1309-line specification read fully. Current unconditional GPT author authorization supersedes the historical DeepSeek stop. No nested agent/workflow, git publication, system/package/installed executable or harness-watchdog change. Product watchdog only. SLO.md/docs/durable-composer reports preserved. Root AGENTS.md/RESEARCH.md and environments/tests.env absent on narrow validation; repository README is the authoritative maintained reference. No unrelated project-memory file created.

Skills resolved through matching SLO_SKILL_DIR/SLO_SKILLS_DIR installed roots. Consulted INDEX, actual code-test-review/shared workflow definitions, shared engineering routing/testing/ownership, coding design/rules/naming/test-policy/cadence/declarative guidance and all requested Python recipes. Existing source topology is retained instead of imposing the generic recipe's unrelated graph-class/synthesis refactor. Historical deviations in prior reports remain, not waived. This dispatch added lifecycle tests after the initial journey increment; passing tests added over already implemented branches are supplemental coverage, not invented original RED.

Counters unchanged except assigned dispatch: turn8 dispatch11/20, total59; eight started/zero completed/all partial, twelve historical execution retries, no workflow abort. Provider-stream continuation attempt2 is not a new workflow turn or dispatch. One owned test command exceeded its tool timeout (below); not silently labeled passing.

## Actual wiring

- Session scheduler creates one ToolExecutionControl per MessageRunState; readiness binds prebuilt/factory/lazy/rebuilt agents. Factory signature unchanged. Finally releases exact binding then closes control. No pool/spawn changes or new model/tool acquisition.
- Graph topology extracted once into `_compile_slo_graph`; bind/release reuses retained tool-bound LLM, original tools and output queue. Tool node enters tools synchronously before planning/interception/effects and enters settling after results. Full tool policy/executor cancellation is NOT implemented.
- Watchdog owns one reader plus urgency/phase/abort waiters; abort > done reader > active deadline > urgency; phase transition inside read disables provider timing. Reserve before cancel; join once-cancelled reader and retrieve waiters through repeated caller cancellation. Explicit item/end preserves actual None, and yield preserves suppressed-cancel item presence. Dead legacy raw-None read branches removed.
- Agent captures pre-attempt context; closes after read join; persists correlated interruption through restricted append-once/fsync before restoring context and advancing ordinary boundary. Interrupted accumulator skips normal answer finalization. Completed-open-tool race **fails closed**, rather than fabricating no-start evidence. Existing unchanged-context provider retries settle control after joined close; settlement errors bypass planners. Legacy unbound behavior preserved.
- Runtime run_retrying enum and additive stream correlation/interruption kinds added. Replay seals exact attempt/iteration and exports interruption/partial audit. Context projector excludes interrupted assistant-message iteration. No TUI activation; host remains normal-only.

## Requirement/evidence map

| Requirement | Evidence / limitation |
|---|---|
| A1 representative J2 | Four real journeys: first token / next token × flat/tree. Urgent accepted, one provider cancellation, first provider finally joined before second request; no release; exact Original/Urgent context; applied SQLite receipts and interruption-before-application ordering. All these assertions pass. Final cleanup assertion fails intermittently. |
| A7 | One next application/boundary observed; cached high-water control retains same or immediate next boundary. Existing delivery retry/rebuild regressions pass. Full backlog/slot matrix not newly established. |
| A8 | Restricted deterministic interruption run_retrying append through existing real store/fsync, both adapters. Complete-opening/no-start writer remains missing and fails closed. |
| A9 | Silent notice plus partial answer replay/export; no partial answer in live next context or replay model context. Multiple interruptions/private-anchor race matrix remains missing. |
| A10 | Actual None, phase exit inside read, suppressed cancellation returning None/value, repeated caller cancel join, abort precedence, completed item precedence, cleanup failure bypassing timeout covered. **Underlying framework queue waiter leak blocks ownership closure.** |
| A11 | Readiness/factory/rebuild regression paths exercised; legacy abort/usage/recovery suite repaired and passes. Full lifecycle/close-failure/storage-failure/pool matrix not established. |

## Commands and actual chronological results

All pytest commands synchronous and serial, runner `/root/.pyenv/versions/slo-harness/bin/python -m pytest -p no:cacheprovider -q`, cwd above. No containers, child workflows or executable fixtures. Root autouse fixture/state-isolation and scoped history/tool/delivery fixtures inspected; no fake-herdr requested. New tests create no executables. Selected real SQLite/history writes resolve under tmp_path. Existing ownership subprocess tests not selected.

Each test shell exported:
`SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 PYTHONPATH=$PWD PYTHONDONTWRITEBYTECODE=1`.

Logs under this directory's `logs/`:

| Log | Exact pytest arguments after runner | Actual result |
|---|---|---|
| urgent-journey-red.log | tests/integration/test_messaging_yield.py | Tool timeout60s; output only F. Test teardown incorrectly awaited synchronous session.abort; corrected before next command. No surviving owned process found. Not counted as complete RED/green. |
| urgent-journey-red2.log | same | exit1, 2 failed; held provider never resumes before 3s bound. Actual original journey RED. Pending framework waiter reported on teardown. |
| urgent-journey-first-green.log | same | exit0, 2 passed before stronger orphan assertion existed. |
| urgent-lifecycle.log | journey + test_watchdog_yield.py + test_watchdog_timer.py + test_graph_read_outcome.py + tool_execution/test_yield_control.py | exit1, 1 failed/29 passed; source waiter scheduled after tools entry rejected phase. |
| urgent-lifecycle-green.log | same | exit0, 30 passed after owner race repair. |
| urgent-replay-red.log | journey | exit1, 4 failed; missing replay notices. |
| urgent-replay-green.log | journey | exit0, 4 passed, including partial and silent. |
| urgent-regression.log | see feature command below | exit1, 12 failed/593 passed; legacy replay equality and retry-control settlement regressions. |
| urgent-regression2.log | same | exit0, 605 passed/328 warnings after repair. |
| urgent-cleanup-red.log | tests/agents/slo_agent/test_watchdog_yield.py | exit2 collection cycle; fixed type-only control imports. |
| urgent-cleanup-red2.log | same | exit1, 1 failed/7 passed; failed reader cleanup misclassified timeout. |
| urgent-cleanup-green.log | watchdog_yield + journey | exit0, 12 passed/10 warnings after fail-closed timeout repair. |
| urgent-agent-regression.log | see agent command below | exit1, 10 failed/175 passed; abort propagation and legacy error/usage semantics. |
| urgent-agent-regression2.log | same | exit0, 185 passed/82 warnings after preserving legacy branch and abort terminal. |
| urgent-resource-proof.log | journey | exit1, 3 failed/1 passed; explicit post-close task leak assertion added. |
| urgent-final-feature.log | final feature command below | **exit1, 2 failed/606 passed/328 warnings**, after test-owned leaked handles are cancelled/joined before failure. No destroyed-task warnings in final log. |

Feature command paths (all explicit, no deselections):
```
tests/integration/test_messaging_yield.py
tests/agents/slo_agent/test_watchdog_yield.py
tests/agents/slo_agent/test_watchdog_timer.py
tests/agents/slo_agent/test_graph_read_outcome.py
tests/agents/slo_agent/tool_execution
tests/agents/slo_agent/history
tests/agents/slo_agent/messaging/test_delivery.py
tests/agents/slo_agent/messaging/test_injected_activation.py
```
Agent command paths:
```
tests/agents/slo_agent/test_agent.py
tests/agents/slo_agent/test_graph.py
tests/agents/slo_agent/test_agent_recovery.py
tests/agents/slo_agent/test_agent_runtime_event.py
tests/agents/slo_agent/test_agent_streaming_dual_mode.py
tests/agents/slo_agent/test_agent_usage_commit_regressions.py
tests/agents/slo_agent/test_agent_image_history.py
tests/agents/slo_agent/test_graph_stream_parser.py
tests/agents/slo_agent/test_stream_event_dao.py
```

## Static checks/source identities

Final scoped `python -m black --check` and `python -m mypy` both exit0 on thirteen files: agent.py, watchdog_timer.py, turn_stream_accumulator.py, events/runtime.py, events/stream.py, graph/service.py, history/transcript.py, history/projector.py, sessions/service.py, tool_execution/yield_policy.py, new journey/lifecycle tests and existing test_yield_control.py. Initial mypy eleven errors repaired, including preexisting source-stub wrong take_one return annotation now reached transitively. No claim about full mypy or historical YAML/BaseMessage baseline (still unestablished/unwaived). Logs urgent-{black-check,mypy-final,diff-check}.log; final git diff --check exit0. Source SHA256 in logs/urgent-source-sha256.txt. Immutable preflight read-only verified unchanged: `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`.

## Lifecycle blocker and cleanup proof

Pinned installed LangGraph source (read-only inspection): `langgraph/pregel/__init__.py:2642–2643` creates `stream.wait()` using the loop directly; `pregel/runner.py:333–335` registers it, but cancellation at `:396–398` is after the async runner loop rather than a finally. Reader cancellation can bypass this tail. Observed exact leftover coroutine `langgraph/utils/queue.py::AsyncQueue.wait` line33, intermittently in both adapters, even after normal session close and five loop turns. No inference that provider cancellation alone joins this waiter.

The journey captures newly created exact tasks relative to its pre-session snapshot, records forbidden pending handles, cancels/awaits them, THEN fails assertion. This is failure-path test cleanup, not a product fix or passing ownership claim. Earlier discovery runs reported pending destruction; final run performs explicit cleanup. Every pytest subprocess was foreground and exited; no owned subprocess/container/workflow survives. Final read-only process survey: only pytest1261413/fake-herdr3382468 in deleted slo-94-herdr-integration and pytest3964084 in `/root/Code/claude-bridge/slo`, all unrelated and untouched. No same-checkout pytest remains. No executable-stub suite was run.

## Finite remainder / next closure

1. Resolve pinned LangGraph waiter ownership at a supported application/framework seam without installed dependency mutation, global task sweeping, a duplicate graph driver or private monkeypatch. Re-run the existing enabled no-orphan journey until deterministic pass; otherwise escalate the dependency constraint to operator. This is the immediate substantive blocker.
2. Connect trusted complete-opening/no-start durable writer and settled-race trace/usage handling; currently fails closed on completed tool openings, not an accepted A8 closure.
3. Add missing repeated-interruption/private-anchor and history-disabled transient journey; session close/join/history failure matrices and policy plumbing still incomplete.
4. Independent early read-only feedback may review this actual runnable-but-incomplete code; no READY implied. Then T3 tool policy/executors, bounded presentation and T4 activation; full gates/final independent review/completion later.
5. Full `make test PYTEST_WORKERS=6` remains separately BLOCKED by exact path-specific executable fixture consent in safety-audit.md. No substitute total or waiver. Full static also unrun. Do not promote scoped green receipts to full acceptance.
