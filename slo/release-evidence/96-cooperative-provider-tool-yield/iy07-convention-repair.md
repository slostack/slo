# IY-07 bounded convention repair — turn 9 / call 1

2026-11-05. **READY only for independent scoped IY-07 review.** Author code+test result, not independent review, A.2 Step1 readiness, formal whole-feature review or completion. Original A.2 acceptance and `closure-verification.md` remain unchanged. IY-03 was not repaired.

## Scope, routing and ownership design

Cwd `/root/Code/slo-message-queue/slo`; branch `message-queue`; HEAD `82c3f5c6de9345af34a673a3d975366ca8c1624c`, preexisting dirty work retained. This dispatch is **turn9 call1/20,total69;9 started,0 whole-A2 complete;8 previous partial + turn9 open;12 historical execution retries,no aborts;this task0 execution retries**. Default limits60 turns/20 calls. Turn8's independent REVISE legitimately returns to repair; this is not a budget-only reset. Local tests/static corrections are not dispatches or execution retries.

Reused unchanged `routing.md` prerequisites: Python3.11 asyncio/LangChain/LangGraph, existing one-shot graph, real session/SQLite/history. Read README/SLO, requested existing closure/handoff/ledger/safety artifacts, original spec §§2.3/3.3–3.4 and provider lifecycle contracts, active installed INDEX and requested workflow/shared/Python/tool guidance. Root/nested applicable AGENTS/CLAUDE were absent; root/docs RESEARCH absent. Consulted KB Welcome → slo README/gotchas; no unrelated docs/KB/skill/harness work. Active skill root from both SLO_SKILL_DIR/SLO_SKILLS_DIR: `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`. Existing shared persistence and one-shot graph contract refines recipe examples; it does not waive conventions. No new framework, topology, pool, scheduler or driver.

Current → target: `_make_agent_node` used standalone substantive `_invoke_joined_provider` with nested consumer; now both direct/pool branches request `GraphEventStream.invoke_joined_provider`. The existing transport owner owns public-stream assembly/close (`_consume_provider_response`) and cancel-once/shield/result retrieval (`_join_provider_response`). It retains no new mutable shared state. This is meaningful separation of consumption from cancellation joining, not arbitrary line splitting. The existing `invoke` graph gateway and completed-response ContextVar sink remain unchanged. Node retention stays in the same synchronous place after response retrieval.

Acceptance/risk map:

| Exact closure / source rule | Changed symbols | Evidence |
|---|---|---|
| Core lifecycle class ownership: README Maintainer Reference Style rules; engineering-ownership; coding-rules; original §2.3 | Remove free `graph/service.py::_invoke_joined_provider`; existing `GraphEventStream` classmethods own consume/join; `_make_agent_node` delegates | Two direct owner-contract tests; real graph ContextVar/retained-completion proof; final graph and session journeys |
| Significant explicit types: Python named-arguments-and-type-hints §2; agent/graph guidance | `stream: AsyncIterator[BaseMessageChunk]`, `chunk: BaseMessageChunk`, `completed: Optional[BaseMessageChunk]`, `provider_task: asyncio.Task[BaseMessage]`, `cancellation_requested: bool`; explicit signatures and Google Args/Returns/Raises | Four-file mypy/Black, source delta |
| Named supported multiargument calls: README Style rules / named-arguments-and-type-hints §1 | `ToolExecutor._join_invocation`: `asyncio.wait(fs={task, urgent}, return_when=...)`; provider stream uses supported `input=messages` | Sequential/concurrent yield-policy tests, same exact tasks and ordering |
| Preserve direct no-astream fallback, original model/request/kwargs, task context, assembly and retained completion, repeated cancel-once join, suppression and failure propagation | No bind/build/request shaping/cancellation policy/terminal arbitration change | Backend no-astream stub in existing `test_graph.py`; actual graph context+identity test; suppressed durable no-start; direct/pool failures; held cleanup/repeated cancellation; real retry identities |

The legacy no-astream fallback deliberately keeps `llm.ainvoke(messages, **kwargs)`: existing `_BackendStub.ainvoke(messages, **kwargs)` has no `input` parameter. The single meaningful request operand remains positional for compatibility; optional mapping is unchanged. Streaming uses the actual public model's supported `input=` parameter. Variadic asyncio shield/gather and positional-only builtins retain their supported calling forms.

## Preservation and actual worker delta

Before any test/production edit, captured only four affected file snapshots `logs/iy07-before-*.py.txt`, their hashes in `iy07-before.sha256`, and existing tracked dirty diff in `iy07-before-tracked.diff`. `iy07-worker-delta.diff` compares those worktree snapshots to final files (not HEAD), isolating this worker's changes from earlier dirty implementation. `iy07-final.sha256` identifies final four files. Protected docs/durable-composer hashes were captured and verified in cleanup; SLO and immutable preflight hashes match their before values. No global formatting, unrelated source edits, installed file/binary mutations, commits, push, packages, infrastructure, containers or nested agents/workflows.

Only four source/test paths changed:
- `src/agents/slo_agent/graph/service.py` — existing caller rerouted, old free helper removed, consumed import removed.
- `src/agents/slo_agent/graph/event_stream.py` — three cohesive typed documented classmethods, required imports.
- `src/agents/slo_agent/tool_execution/executors.py` — exactly one `fs=` keyword change.
- `tests/agents/slo_agent/test_graph_stream_lifetime.py` — three small ordinary pytest owner/real-caller tests; no AST harness or internal patching.

## Safety audit and command environment

Before tests, checked live process cwd: historical1261413/3382468 are PPid1 in deleted `/root/Code/slo-94-herdr-integration/slo`; left untouched. No same-checkout pytest active. All test commands foreground, serial, bounded60/120sec tool timeout, no xdist or child workflow. Shell ownership PIDs and UTC start/end/actual pytest exit are embedded in each log; outer capture shell success is not confused with test exit.

Inspected chosen seven modules and root conftest/state_isolation, imported helper dependencies (`test_delivery`, `test_store_journey`, `test_session_messaging`, `test_durable_composer`, `test_prompt_component_protocol`, path-suggestion/scroll helpers). No nested conftest applies to selected agents/integration paths. Importing TUI helpers does not collect TUI modules or apply their directory conftest. Selected tests use disposable data/history/SQLite and in-process provider/tool/observer collaborators; no fake-herdr/executable fixture requested. Root guards prohibit real terminal/Herdr spawn. Existing policy plugin reload writes contained ordinary Python plugin data, no chmod/bin/tool stub. Existing real-tool effect writes verify resolved test-root containment. No command-stubbing suite run; no fabricated host-binary integrity claim.

`environments/tests.env` absent; inspected project pyproject/Makefile contract; all pytest commands use this exact fallback environment:

```bash
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD"
/root/.pyenv/versions/slo-harness/bin/python -m pytest -p no:cacheprovider -q <exact scope below>
```

No real provider or credential used. Interpreter CPython3.11.7, executable/prefix `/root/.pyenv/versions/slo-harness`. This typed environment is **not** the Poetry base prefix. Static commands use PYTHONDONTWRITEBYTECODE1/PYTHONPATH=$PWD and project pyproject config (Black110; mypy strict_optional/ignore_missing_imports). `--follow-imports=silent` bounds static diagnostics to explicit changed files; it is not full `make lint`.

## RED-before-production / GREEN chronology

| Log under logs/ | Exact pytest scope after prefix | Actual result / owner shell PID |
|---|---|---|
| iy07-red.log | `tests/agents/slo_agent/test_graph_stream_lifetime.py::TestGraphEventStreamProviderOwnership` | **exit1,2 failed,2 warnings,1.94s**, PID363715; 02:03:11–18UTC |
| iy07-green.log | `tests/agents/slo_agent/test_graph_stream_lifetime.py` | exit0,9passed9warnings2.10s, PID366682 |
| iy07-affected.log | Six-file scope below | **exit1,1failed95passed99warnings25.50s**, PID375066 |
| iy07-pool-isolation.log | `tests/integration/test_yield_retry_identity.py::test_real_pool_exhaustion_retries_low_budget_without_new_claim_or_binding` | exit0,1passed4warnings3.29s, PID377997; no source/test change |
| iy07-affected-final.log | Same six-file scope | exit0,96passed97warnings23.14s, PID379163; unchanged assertions |
| iy07-graph-compat.log | `tests/agents/slo_agent/test_graph.py tests/agents/slo_agent/test_graph_stream_lifetime.py` | exit0,39passed15warnings3.00s, PID382763 |
| iy07-final.log | `tests/agents/slo_agent/test_graph.py` plus six-file scope below | **exit0,125passed102warnings24.43s**, PID385403; final code/test bytes |

Six-file scope, exact order:
```text
tests/agents/slo_agent/test_graph_stream_lifetime.py
tests/integration/test_messaging_yield.py
tests/integration/test_yield_consumer_contract.py
tests/integration/test_yield_retry_identity.py
tests/agents/slo_agent/tool_execution/test_yield_control.py
tests/agents/slo_agent/tool_execution/test_yield_policy.py
```

RED was written/run **before production edit**. It proves the requested class-owned consumption/join interface was absent (`AttributeError` on `GraphEventStream.invoke_joined_provider`), not a fabricated preexisting behavioral cancellation defect. After owner move both pass: actual two-chunk assembly consumes original provider queues; repeated cancellation cannot finish before held cleanup, exactly one close, actual CancelledError retrieved. Added supplemental real graph caller test afterward (not claimed RED): ContextVar reaches actual external provider through graph/consumption tasks, exact bound model retained, one actual completed response retained, context reset afterward. Existing real session/SQLite/history tests supply lifecycle/failure/suppression evidence, not mocks of internal ownership.

The first affected run failed existing pool-exhaustion oracle: `len(session.selections)` was2, expected1 (line582). No test assertion or production behavior was changed to address it. It passed isolated, same six-file rerun, and final seven-file run unchanged. **Cause not established; timing-sensitive intermittent failure remains disclosed, not called a proven baseline or waived.** Final passing evidence does not erase it. Independent reviewer should assess this residual verification risk; no claim of universal no-regression proof.

Inspection of backend fallback prompted retaining its exact original positional request call (initial moved version used input=, reverted before dedicated compatibility/final runs). No failing behavioral run was fabricated for that inspection correction. Static initial pass preceded supplemental ContextProvider; next static attempt (`iy07-static-final.log`) caught its Pydantic constructor typing (`Unexpected keyword argument responses`). Added explicit test-provider constructor, then final125 passed. These are local test/static corrections, not retries of a failed dispatch.

## Final scoped static and cleanup evidence

`logs/iy07-static-verified.log` (PID388421):
```text
/root/.pyenv/versions/slo-harness/bin/python -m black --check src/agents/slo_agent/graph/service.py src/agents/slo_agent/graph/event_stream.py src/agents/slo_agent/tool_execution/executors.py tests/agents/slo_agent/test_graph_stream_lifetime.py
# exit0, 4 unchanged
/root/.pyenv/versions/slo-harness/bin/python -m mypy --follow-imports=silent src/agents/slo_agent/graph/service.py src/agents/slo_agent/graph/event_stream.py src/agents/slo_agent/tool_execution/executors.py tests/agents/slo_agent/test_graph_stream_lifetime.py
# exit0, no issues in4 files
git diff --check
# exit0
```

Author reviewed `iy07-worker-delta.diff` for preservation, exact provider task/stream, cancellation-once/error retrieval, no-astream compatibility, caller retention order and keyword-only executor delta. No independent judgment claimed.

`iy07-cleanup.log`: protected docs/durable-composer hashes all OK; SLO/preflight hashes unchanged. All owned pytest commands returned/reaped. Process match survey includes current worker/coordinator/capture shell command text as false positives, plus the two unrelated historical processes; **no owned pytest remains**. No signals sent, no containers or OS children created by this worker. Existing strict `isolated_journey_tasks` remains enabled for graph/session lifecycle tests and passes without leaked handles; gates release and exact tasks join in finally. No production/test edits after final125/static evidence.

## Limits and next action

Independent scoped review and scoped completion check are upcoming, not performed here. Whole A.2 remains **INCOMPLETE / Step1 blocked**: IY-03 post-read settlement abort residual; required full non-E2E suite permission-blocked; full `make lint` failed8 missing-yaml-stub errors and whole Black13 failures, all unwaived; historical process/test-first deviations unwaived; formal whole-feature final review/completion pending. Prior evidence remains historical and was not overwritten or promoted. No new full-suite run, exclusion, waiver, package installation or executable-fixture consent inferred. READY here means only this bounded IY-07 code+test delta is ready for independent scoped scrutiny.
