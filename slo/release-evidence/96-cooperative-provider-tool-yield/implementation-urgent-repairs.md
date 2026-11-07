# 96.A.2 finite urgent repairs — dispatch 13

## Verdict: INCOMPLETE / REVISE, not milestone READY

The current representative urgent journey and abort cleanup proofs pass, including strict pre-cleanup orphan assertions. UJ-02 is **not closed**, and full UJ-01/UJ-04 closure still needs output/history/consumer failure and cancellation matrices. No claim of accepted whole runnable milestone or Step 1 readiness. TUI remains normal-only.

Cwd `/root/Code/slo-message-queue/slo`; branch `message-queue`; HEAD `82c3f5c6de9345af34a673a3d975366ca8c1624c`. Carried counters: turn 8 dispatch 13/20, total 61; eight started, zero complete, all partial; twelve historical execution retries, no workflow aborts. This finite repair scope has zero failed-execution retries; failing development tests are not agent execution retries. No nested agent/workflow launched.

## Closure map

| Finding | Current disposition |
|---|---|
| UJ-03 | Inherited current test already has function-scoped async cleanup fixture protecting setup, assertions, close and final SQLite checks. It snapshots only the isolated function test loop, cancels exact captured handles and repeatedly shields their gather. Pending handles remain a teardown failure even after cleanup. Session client close is nested under session-close finally. Formatting/type correction only this dispatch; no fabricated new RED for inherited changes. Primary test failure and teardown error are independently retained by pytest. Failure/cancellation injection proof remains needed. |
| UJ-01 | Four real first/next-held-token × flat/tree journeys now pass strict orphan assertion. Live text AND structured thinking are asserted in canonical history before submitting urgent/releasing provider. One graph driver uses updates-only, no messages/custom/subgraphs waiter path. Public callback supplies original model chunks. Full timeout/repeated-cancel/pool/output matrices remain. |
| UJ-04 | Held provider cleanup prevents abort terminal; raising cleanup now surfaces CooperativeYieldSettlementError instead of successful abort. Exactly one provider cleanup observed. Agent unconditional finally closes before post-read output drain; inherited changes inspected and retained. Full output/history/consumer failure proof remains. |
| UJ-02 | NOT CLOSED. Settled item still absorbed before close and does not fully capture completed usage/audit. Complete-opening/no-start branch remains intentionally fail-closed. Trusted marked live opening/result producer and retained exact event/opened_at no-start disposition still missing. Do not enable tools/TUI or claim acceptance. |

## Supported transport decision and current design

The suggested v2 `astream_events(version='v2', stream_mode='updates', subgraphs=False)` was present in inherited dirty source. It passes the four delivery journeys and held abort, but fails the raising-provider-cleanup public test: observed successful `run_aborted` despite cleanup RuntimeError. Adding public chain-error callback did not repair this. Exact evidence below. No installed package was changed.

Current simpler supported seam: one invocation-owned task drives `graph.astream(..., stream_mode='updates', subgraphs=False)`; public AsyncCallbackHandler forwards original ChatGenerationChunk messages to its queue. No private streaming-handler inheritance (an exploratory import was removed before execution), copied runner, task factory, product all_tasks sweep, second graph driver or dependency edits. Agent retains same graph/model/tool/output queue. Queue terminal joins the exact driver and finally retrieves its failure through repeated shielded gather.

A public `llm.ainvoke(stream=True)` still lost raising cleanup through framework generation gather cancellation. The graph node now owns one public `llm.astream` consumption task, joins it through repeated cancellation, and converts the actual normally completed message chunk using public message_chunk_to_message. This is the sole provider call, not another graph invocation. Provider errors observed through public on_llm_error are retained because graph cancellation may otherwise select CancelledError. Existing direct injected ainvoke-only adapter remains supported. Existing legacy injected graph `astream` adapters retain original messages/updates contract; real compiled graph uses new transport.

**Risks remaining:** callback currently accepts all model token callbacks rather than selecting agent-node run identity; queue is unbounded and lacks output-queue wake while a tool is held; callback completion retention/no-start settlement not wired. These are concrete remaining implementation issues, not waived by green counts. Full API/normal-completion/pool identity compatibility needs final review.

## Serial test receipts

All commands foreground/synchronous, one owned cycle at a time; no containers/subprocess fixtures/workflows. Runner `/root/.pyenv/versions/slo-harness/bin/python -m pytest -p no:cacheprovider -q`. Every command cwd above with:

`SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 PYTHONPATH=$PWD PYTHONDONTWRITEBYTECODE=1`.

No readable environments/tests.env; retained Makefile fallback. Scoped fixture audit reused from routing/safety/previous receipt; new tests write no executable files. SQLite/history beneath resolved tmp_path.

Logs under `logs/`:

| Log | Arguments/result |
|---|---|
| repairs-inherited-boundary.log | journey + test_graph_stream_lifetime.py: **1 failed, 5 passed**, exit1. Raising cleanup falsely publishes abort. This is actual inherited boundary RED, not authored-then-tested evidence for pre-existing source. |
| repairs-callback-proof.log | same: **1 failed, 5 passed**, exit1; public v2 chain callback insufficient. |
| repairs-owned-driver.log | same: **6 failed**, exit1; updates-only callback alone does not request provider streaming. |
| repairs-explicit-stream.log | same: **1 failed, 5 passed**, exit1; ainvoke(stream=True) delivers chunks but still loses raising cleanup. |
| repairs-provider-owner.log | same: **1 failed, 5 passed**, exit1; shielding ainvoke alone insufficient. |
| repairs-provider-failure.log | same: **1 failed, 5 passed**, exit1; public LLM callback alone insufficient. |
| repairs-public-provider-stream.log | same: **6 passed, 12 warnings**, exit0, 2.75s after owning public provider stream. No skips/xfails/deselections or weakened assertions. |
| repairs-agent-regression.log | prior nine-path agent command: **20 failed, 165 passed**, exit1. Legacy injected stream shape/ainvoke-only compatibility broken. |
| repairs-agent-regression2.log | same after compatibility repair: **185 passed, 82 warnings**, exit0, 11.89s. |
| repairs-feature.log | prior feature command plus graph lifetime tests: **610 passed, 330 warnings**, exit0, 80.42s. |

Feature arguments:
```
tests/integration/test_messaging_yield.py
tests/agents/slo_agent/test_graph_stream_lifetime.py
tests/agents/slo_agent/test_watchdog_yield.py
tests/agents/slo_agent/test_watchdog_timer.py
tests/agents/slo_agent/test_graph_read_outcome.py
tests/agents/slo_agent/tool_execution
tests/agents/slo_agent/history
tests/agents/slo_agent/messaging/test_delivery.py
tests/agents/slo_agent/messaging/test_injected_activation.py
```
Agent arguments:
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

Scoped static initially found five errors (logs/repairs-mypy.log), then corrected typing and formatted only six seam files. Final static/verification/source identity receipts follow in separate logs; no full static success inferred. Full `make test PYTEST_WORKERS=6` remains BLOCKED by original path-specific executable fixture consent; not run, excluded, waived or substituted.

## Final source verification and resource disposition

After typing/format corrections, reran exact feature and agent commands serially: `logs/repairs-final-feature.log` **610passed/330warnings/exit0**,78.97s; `logs/repairs-final-agent.log` **185passed/82warnings/exit0**,14.07s. Six files in `logs/repairs-source-sha256.txt` pass Black --check and mypy (exit0); git diff --check exit0. Logs `repairs-final-{black,mypy,diff}.log`. Final process survey shows only unrelated historical1261413/3382468, left untouched; no owned pytest remains. Function-isolated strict pending-task teardown passed every current journey/lifetime case. No executable-stubbing suite ran, no containers or test child processes acquired. Source self-inspection identifies the unresolved callback filtering/queue/settled-truth defects above; no independent acceptance claimed.

## Next finite implementation

1. Retain completed node truth on this same transport through cancellation; after successful joined close consume once via named settlement owner. Preserve actual observed usage without completing interrupted answer.
2. Trusted marked opening/result producer, stable opened_at/events, reserved no-start after exact fsync then context/private-anchor exclusion. Unknown write blocks every retry/next request. Keep current fail-closed branch until safe.
3. Agent-node callback lineage filter and output queue wake; held live output proof. Failure/consumer/timeout/repeated cancellation proof. Then multiple interruptions, exact replay key `(attempt, iteration, block)`, reopen/export/private-anchor and history-disabled evidence.
4. Independent bounded rereview after actual closure, not READY based on these counts. T3 tools, bounded presentation, T4 TUI/full gates/final review/completion remain later.
