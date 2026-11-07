# Core yield implementation — dispatch 14

## Verdict: substantial runnable core progress; INCOMPLETE / NOT READY

Turn8 dispatch14/20,total62;8started/0complete/allpartial;12 historical execution retries,no aborts;new cohesive scope0 execution retries. Original retry identities remain unchanged in continuation-ledger.md. No nested agents/workflows. Branch message-queue / HEAD82c3f5c6de9345af34a673a3d975366ca8c1624c unchanged. TUI remains normal-only. Independent rereview/final review/completion still required; this is author evidence, not workflow acceptance.

## Actual wiring and requirement map

- **UJ02/A1/A8/A9/A10:** Same ONE owned updates-only compiled graph driver and ONE provider astream consumer retained. A ContextVar-scoped synchronous completion sink retains actual node response before graph cancellation can discard it. Agent closes/joins first, consumes settled update plus retained exact object once, captures observed usage, emits completed audit without answer finalization. Real suppressed-completion journeys prove full opening → deterministic append-once/fsync no-start → interruption → next urgent request, zero tool starts. Both adapters and history-disabled transient receipt parity pass; exact observed 7+3=10 tokens retained. Interrupted private anchor absent from next context/replay.
- **A8/A12:** Session runtime handler owns group opened_at, full ordered opening arrays, deterministic call/result/no-start IDs, core statuses and exact retained canonical event objects. Plugin metadata never supplies group proof. Existing append_cooperative_event_once handles writes; opening traces precede returned result publication. require_reserved_no_start is checked after graph close, rejects actual results; no invented ToolMessage for reservation. Durable write uncertainty stops continuation. Existing raw validators/compaction retained.
- **A2/A3/A4/A12:** Exact ToolInvocationDAO Task[ToolMessage], frozen strict runtime-handle carriers, trusted structural cancellation port and identity registration. Empty registry means defer for every built-in/plugin/spawn/offload. Sequential guard before lookup/interception, after interception, immediate task registration; denied remainder exact error. Post-result plugins inside exact task; core errors cannot upgrade to success. Concurrent executor passes no policy to individual calls, joins started siblings and returns source order. Dense concurrent proof confirms registered tools still defer and no eager callback.
- **A4/A10:** Policy owns one callback/settlement task per exact invocation; validates loop/object/ID, actual normal wins, joins port even if normal wins. One five-second monotonic threshold (injected short budget in tests), not abandonment. Invalid/exception/late/naked-cancel paths defer/join, valid late error ack can settle; no valid result raises UnsettledToolGroupError. Duplicate registration rejected. Same-control policy replacement rejected.
- **A2/A10/A11:** Existing blocking helper now shields/drains actual asyncio.to_thread leaf and holds semaphore through repeated wrapper cancellation. Real tmp file test proves wrapper cannot finish before leaf effect.
- **§3.5/A2/A10/A11:** Trusted history and herdr accounting moved out of optional subscriber list and remain awaited. Session presentation publisher reuses pull buffers/terminal slot. sessions/presentation.py owns one worker per external handler/dispatcher, no task per event, 256-event/1MiB queue, max64 retained external owners, one-second TimerHandle budget. Overflow/failure/cancellation retires once; suppressing callback keeps exact worker pending until joined. Close seals all before joins and releases OS lease afterwards. Unsubscribe retires synchronously and session retains worker for final join (see remainder: no explicit awaitable per-unsubscribe join API yet). Real held tool_result observer cannot prevent urgent application/next request.
- **UJ01/UJ04 transport:** Callback filter accepts model runs directly descended from actual agent-node run, excluding foreign tool-model callbacks. Queue now max256 with awaited backpressure instead of unbounded intermediate loss. Public LangChain custom callback wakes existing tool output queue without LangGraph custom/messages mode. Existing output queue is unchanged. Held repeated output test passes, but its preexisting schedule also passed before wake addition: do NOT claim an authored output-wake RED; initial output test failure was malformed fixture, corrected. Bounded queue filter proof is coverage of current implementation, not invented RED. Byte-bound transport and saturated close proof remain below.
- **A9:** Replay late-thinking key now exact (attempt,iteration,block), failing-first regression repaired. Real two interruptions + success run proves same run/attempt, iterations0/1, reopen/export markers and no partial context. Actual tool anchors/results retained. No T4 paint claim.
- **UJ04/A11:** Controlled runtime trace failures translate to terminal CooperativeYieldSettlementError before all recovery planners; failing-first injected history proof passes. Prior held/raising cleanup tests remain green.

## Test-first chronology and exact receipts

All logs below relative to `release-evidence/96-cooperative-provider-tool-yield/logs/`. Cwd `/root/Code/slo-message-queue/slo` throughout. Runner `/root/.pyenv/versions/slo-harness/bin/python -m pytest -p no:cacheprovider -q`. Environment for EVERY test command:

```
SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo
SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
COLUMNS=120 LINES=40 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
```

`environments/tests.env` rechecked unreadable/absent; Makefile fallback retained. No executable fixtures, containers, test subprocesses or workflows. Tests use real session/client/SQLite/history/graph/executors/files; provider boundary scripted; internal timing/ports injected explicitly.

| Increment / log | Exact pytest arguments / exit / result |
|---|---|
| core-no-start-red.log | tests/integration/test_messaging_yield.py -k suppressed /1/2failed,4deselected; missing marked evidence |
| core-no-start-green.log | same file without -k /0/6passed |
| core-tools-red.log | same file -k real_tool /1/2failed,6deselected; second tool actually starts |
| core-tools-green.log | same file /0/8passed |
| core-observer-red.log | same file -k real_tool /1/2failed,6deselected; held observer blocks application |
| core-observer-green.log | same file /2/collection IndentationError introduced during edit; fixed, not a behavioral RED |
| core-observer-green2.log | same file /0/8passed |
| core-offload-red.log | tests/agents/slo_agent/tool_execution/test_blocking_yield.py /1/1failed; wrapper finishes before leaf |
| core-offload-green.log | preceding file + tests/agents/slo_agent/tool_execution/test_plugin_interceptors.py + tests/agents/slo_agent/messaging/test_delivery.py::test_history_uncertainty_prevents_next_provider_step /0/6passed |
| core-policy-red.log | tests/agents/slo_agent/tool_execution/test_yield_policy.py /1/7failed missing DAO/policy |
| core-policy-green.log → green2.log | same /1/1failed6passed then /0/7passed (valid ack race corrected) |
| core-policy-journey-red.log | integration file -k real_tool /1/4failed6deselected missing session policy keyword |
| core-policy-journey-green.log | integration file /0/10passed |
| core-feature-first.log | feature list below /1/2failed612passed; old tests expected plugin success upgrade and later corruption detection |
| core-mailbox-existing-proof.log | policy file /0/8passed; suppressing overflow proof, no invented RED |
| core-output-red.log → red2/held/final-red.log | integration -k real_tool: first /1/4failed malformed snapshot fixture; corrected versions /0/4passed6deselected BEFORE custom wake. Filenames do not establish product RED. |
| core-output-wake.log | integration + policy files /0/18passed |
| core-replay-red.log | tests/agents/slo_agent/history/test_transcript.py -k exact_attempt /1/1failed24deselected |
| core-transient-replay.log → replay2.log | integration + transcript files /1/4failed33passed test used usage_snapshot property incorrectly; corrected /0/37passed |
| core-worker-red.log → green.log | policy -k one_worker /1/1failed9deselected; then policy+integration /0/22passed (removed task/event) |
| core-threshold-red.log → green.log | policy -k monotonic /1/1failed10deselected; policy /0/11passed |
| core-unknown-red.log | policy -k unknown_tool /1/1failed11deselected; guard moved before lookup |
| core-seal-red.log | policy -k sealed_source /1/1failed12deselected; predicate recheck implemented |
| core-policy-hardening.log | policy /1/1failed12passed; threshold fixture lacked newer urgency after new predicate guard |
| core-registration-red.log / hardening2.log | policy -k registration_is_bounded then policy: both fixture-construction failure, NOT product RED (session lacked config). Corrected fixture and bounded retained owner guard; hardening3.log /0/14passed |
| core-callback-existing-proof.log | policy /0/15passed; backpressure/filter proof, no invented RED |
| core-trace-red.log → red2.log → green.log | policy -k controlled_trace: first fixture omitted cached delivery, then /1 actual raw history RuntimeError; after translation policy /0/16passed |
| core-two-interruptions-existing-proof.log | integration -k two_provider /0/2passed12deselected |
| core-anchor-proof.log | integration /0/14passed |
| core-binding-red.log | policy -k policy_replacement /1/1failed16deselected; exact policy identity enforced |

Two existing assertions deliberately updated to the authoritative new contract (not skips/weakening): plugin core-error upgrade now forbidden; raw marked-opening certification detects corruption BEFORE next input claim, so second receipt remains accepted rather than applying. Provider remains one request and terminal failure retained.

### Final serial regression gates

**core-final-feature.log: exit0,639passed,353warnings,82.86s**
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
**core-final-agent.log: exit0,185passed,82warnings,11.87s**
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
Earlier core-feature.log625passed and core-agent.log185passed superseded by final above.

Scoped Black --check exit0:16files (`core-final-black.log`). Scoped mypy exit0:13files (`core-final-mypy.log`); intermediate typing findings repaired, no exemption. Paths/source identities in `core-source-sha256.txt`: ten source seams plus integration, policy/offload/interceptor/transcript/delivery tests. Black adds interceptor/transcript/delivery tests to mypy's thirteen-file scope. git diff --check exit0 (`core-final-diff.log`). Full static unrun/unwaived.

## Lifecycle and safety

Every command synchronous foreground; one test cycle at a time, shell tool returns after pytest join. Tests acquire no containers/real subprocess fixtures. Strict isolated_journey_tasks remains enabled and pre-cleanup orphan detection passed every current integration/lifetime test; needed cleanup still fails proof. Other added tests retain exact tasks and release/join in finally; thread fixture releases gate in finally. No owned process remains: final process survey `core-final-processes.log` contains ONLY unrelated1261413pytest and3382468fake-herdr, untouched. No executable-stubbing suite ran. Full make test PYTEST_WORKERS=6 remains BLOCKED by safety-audit C1/C3/C4; no exclusion, waiver or substitute gate.

## Exact finite remainder before core READY

1. **Bounded transport:** queue is event-count bounded256 but NOT serialized-byte bounded; provider callback ancestry currently direct agent parent, real ModelPool nested callback/live-thinking identity not yet proved; saturated queue/close/cancel suppression needs deterministic no-deadlock proof. Existing output-update queue unchanged/unbounded; review bounded producer behavior before claiming whole transport bound. One supported driver preserved; do not reintroduce messages/custom LangGraph waiter.
2. **Observer lifecycle:** synchronous unsubscribe retires and retains worker for final close, but explicit per-unsubscribe awaitable join, /new/nonmessaging final teardown/plugin unload ownership need completion. Dispatcher emits swallows per-observer exceptions, so mailbox cannot detect those and retire the dispatcher on observer failure yet. Full one-second budget/capacity/byte-overflow/cancellation and held-close session ownership matrix still needed. Retired worker references bounded64 until joined/pruned. No no-op deferred sink remains, but canonical deferred/requested audit is not yet persisted at settlement (only presentation deferred notice + provider interruption audit).
3. **Strict writer extraction/hardening:** nested persist_group is cohesive but large; exact retained event on duplicate runtime ID currently reused without comparing new payload to retained payload. Add conflict test and compare/fail closed. Diagnostic canonical events not yet retained in same cache on uncertainty. Trusted runtime handler None in history-disabled mode means only transient control gates, no transient group producer; current no-history no-start/usage/receipts passes but needs explicit exact transient-group parity proof. Raw marked consistency after newly produced whole group before continuation deserves explicit gate/test rather than relying only on strict messages/startup.
4. **Policy/executor full contracts:** naked-cancel/unfinished/late-ack/result-plugin-held/abort repeated-cancel matrix beyond present valid/wrong/success/exception/late/normal cases; reject direct cancel_and_join call without tools/newer urgency and classify capability errors terminal before every planner. Policy settlements strongly retain completed invocation tasks for session policy lifetime (potential growth) — retire per-run ownership without losing callback-once semantics. Concurrent async interception currently each call registers after its own check, not a whole-batch post-interception atomic start; implement specified preflight-all/register eligible batch and test urgency during pending interception. Concurrent defer reason currently noninterruptible_tool rather than concurrent_batch. Spawn/pool unchanged but held original child aggregate/permit path not newly exercised.
5. **Failure/identity evidence:** real write-uncertainty through newly wired writer (both adapters) plus low retry/no-next-provider; output/history/consumer error and timeout/repeated cancellation, same-run rebind/rebuild/pool/control/cursor identity. Existing prior foundations have valid evidence but do not imply new producer coverage. No-tool completed cancellation-race audit (current journey uses opening), full close ordering under output/history failure. Exact replay key test repaired; mounted T4 rendering intentionally next task.
6. **Review/gates:** independent bounded rereview now useful for current runnable core; fix findings then remaining core tests/static. Full required suite still permission-blocked, full lint/Black unrun. No final independent review/completion, no milestone/Step1 READY.

Preserved all unrelated SLO.md/docs/durable-composer/preflight edits, no commits/publication/packages/system/infrastructure/installed executable/watchdog setting changes. Original authoritative spec unchanged. Durable lessons intentionally recorded here rather than modifying protected docs/KB during incomplete work.
