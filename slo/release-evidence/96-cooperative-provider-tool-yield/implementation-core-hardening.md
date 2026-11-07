# Core hardening — turn8 dispatch15

## Verdict

**INCOMPLETE / core NOT READY; whole phase BLOCKED.** Concrete integrated safety repairs landed; not a foundation restart. TUI remains normal-only. No independent final review/completion is claimed. Same branch message-queue / HEAD82c3f5c6de9345af34a673a3d975366ca8c1624c, existing dirty work preserved. Counters: turn8 dispatch15/20,total63;8started/0complete/allpartial;12 historical execution retries,no aborts; this scope0 execution retries. Local tests/edits are not dispatches or turns.

## Closure/source/evidence map

1. **Trusted writer (§6/A8/A12):** `sessions/cooperative_history.py::CooperativeHistoryWriter` replaces the nested session producer, called only by `_runtime_handler_for_turn`. `persist` compares incoming canonical hashes (JSON key-order independent, bool/number distinct), retains first event/timestamp/opened_at/full array/status/diagnostic, rejects conflicting duplicate IDs. Both real adapters use existing append-once/fsync. `certify_settlement` reads ALL raw pages under history barrier, validates complete marked groups and compares exact retained event hashes against actual raw evidence before control settlement. History-disabled controlled attempts use same transient producer/validator, no durable claim. Existing no-start phase/join/no-results conditions preserved. Unknown reply raises terminal error; real client/session/SQLite journeys prove one provider request, no completion, urgent retained accepted after owning close in both adapters.
2. **Canonical audit (§3.4/§5.5):** control captures immutable requested/deferred correlation separately from best-effort sink; agent transfers to trusted runtime handler after close, before interruption/next boundary. Actual deferred tool journeys now assert canonical `deferred`; provider journeys assert requested then interrupted. No synthetic stream cooldown or applied receipt.
3. **Concurrent batch (§5.4/A3):** executor preflights ALL async interception, gathers with exception retrieval and repeated-cancel join, rechecks urgency and registers whole eligible batch with no awaits between invocation task starts. Exact original tools and Task[ToolMessage] preserved; source order and all-sibling join before propagation. Concurrent policy never cancels; reason `concurrent_batch`. Tests prove urgency while second interceptor held prevents first approved call starting, all three tasks exist before any body, and preflight failure waits held sibling.
4. **Capability/policy (§5.4/A4/A12):** direct cancel requires tools phase, exact group ID, newer urgency and owner loop; capability errors join terminal settlement classifier before all generic planners. One callback per exact task/control; normal wins; invalid/unfinished/naked/late/threshold/exception paths covered. New early-ack regression: ack returned before invocation join never gains authority from later naked cancellation. Post-result plugin held/suppressing test proves exact invocation-task ownership. Repeated owner cancel joins both handles. Scheduler closes control then `release_run` drops completed strong ownership; weak retired-task guard prevents callback reuse even through foreign fresh control without retaining completed tasks indefinitely.
5. **Observer lifetime (§3.5):** sync unsubscribe preserved; `join_unsubscribed` explicitly joins retained workers and recognizes repeated bound-method lookup. Owner reporting close (including nonmessaging, /new path) joins presentation before reporting disposal; messaging close already does before OS lease release. Plugin reload/trust joins retiring dispatcher before replacing it. `emit_for_session` surfaces isolated observer failure to mailbox retirement; legacy emit and decision interceptors unaffected. Existing max256/1MiB/max64/one-worker/1sec semantics now exercised for count/bytes/error/budget/repeated cancel/suppression. Invocation never waits on these callbacks.
6. **Transport (§5.3/A10/A11):** same one updates-only driver/public callback/provider astream retained. GraphEventQueue bounds256 events and1MiB serialized bytes with backpressure. One indivisible oversize truth is admitted ONLY when empty (no drop/fake completion), blocks following items; not a hard max-single-chunk guarantee. Nested agent callback ancestry accepted, foreign tool-model callbacks excluded. Real retained ModelPool member proves held live text/thinking, same bound pool and no fallback on urgent cancellation. Saturated byte queue consumer-close joins driver; timeout/repeated cancel/consumer/history failure proofs assert no early terminal/exact closeonce. Callback start chatter never enters meaningful transport/deadline path. Existing executor output snapshot queue remains same contract: producers await custom wake after each snapshot, consumer drains it; not claiming globally byte-bounded executor output.
7. **High-water (§5.2/A7):** real backlog journey found rejection when pending urgency emptied and next normal selection legitimately snapshots0. Retry still requires exact same boundary/high-water; next selected boundary may lower snapshot. Journey applies urgentA,urgentB,normal tail in four total requests with ONE provider cancellation; older urgency does not interrupt itself.
8. **Spawn/offload (A2/A5):** original SpawnSubAgentsTool + real SubAgentPool + injected SubAgentProcess timing (NO real child) holds MAX_CONCURRENCY slots, leaves extra child waiting through urgency, returns original aggregate once, all registry winners complete. Real thread test proves cancelled wrapper retains semaphore until actual leaf finish. No A3 imports/types/registration/newpool.

## Test-first chronology

Cwd for every command: `/root/Code/slo-message-queue/slo`. `environments/tests.env` absent/unreadable; Makefile fallback used. Every pytest command uses:

```
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD"
/root/.pyenv/versions/slo-harness/bin/python -m pytest -p no:cacheprovider -q <arguments>
```

Logs below in `logs/`, prefix `hardening-`. F=tests/agents/slo_agent; I=tests/integration/test_messaging_yield.py; P=F/tool_execution/test_yield_policy.py; W=F/messaging/test_canonical_yield_writer.py. RED filenames alone do not establish behavioral failure; fixture exceptions explicitly listed.

| Log suffix | Exact arguments after runner | Exit/result |
|---|---|---|
| writer-red | W |1/7failed missing writer module; new seam not behavior proof |
| writer-red2 | W |1/7failed:6 invalid ensure_session fixture,1 missing selected tool_input |
| writer-red3 | W |1/6failed1passed actual duplicate conflicts accepted |
| writer-green | W |0/7passed |
| audit-red | I -k suppressed |1/2failed2passed10deselected missing requested audit |
| audit-green | I W |1/4failed17passed existing interruption test counted all diagnostics; §6.4 requires disposition filter |
| audit-green2 | I W |0/21passed |
| concurrent-red | P -k concurrent |1/2failed16deselected: reason and early tool start |
| concurrent-green | F/tool_execution I |0/80passed |
| capability-red | P -k 'capability_requires or capability_failure' |1/4failed18deselected |
| capability-green | F/tool_execution I |0/84passed |
| unsubscribe-red / unsubscribe-green | P -k unsubscribe_join / P |1 fixture missing session_id; NOT product RED |
| unsubscribe-green2 | P |0/23passed; new API proof, no invented behavioral RED |
| transport-red | P -k 'transport_bounds or nested_agent' |1/2failed23deselected missing queue/nested lineage |
| transport-green | P I F/test_graph_stream_lifetime.py |0/41passed |
| policy-retirement-red / green | P -k release_run / P I |1/1failed25deselected missing API ->0/40passed |
| observer-failure-red / green | F/plugins/test_dispatcher.py -k session_observer / same file I P |1/1failed14deselected missing session emission ->0/55passed |
| nonmessaging-red / green | P -k nonmessaging_owner |1/1failed28deselected ->0/1passed28deselected |
| plugin-reload-red / green | P -k plugin_reload |1/1failed30deselected ->0/1passed30deselected |
| bound-unsubscribe-red / green | P -k bound_method_unsubscribe / P -k 'unsubscribe or plugin_reload or nonmessaging_owner' |1/1failed31deselected actual bound lookup retirement defect ->0/4passed28deselected |
| raw-barrier-red / green | W -k actual_raw / W I |1/2failed10deselected missing certification API ->0/29passed |
| raw-truth-red / green | W -k actual_raw / W I |1/2failed4passed10deselected structurally valid forged output ->0/33passed |
| backlog-red / green | I -k older_urgent / I -k older_urgent F/tool_execution/test_yield_control.py |1/1failed17deselected actual high-water defect ->0/1passed21deselected (the -k deselects control tests; final suite includes them) |
| canonical-order-red / green | W -k reordered / W |1/1failed16deselected ->0/17passed |
| early-ack-red / green | P -k early_ack / P I |1/1failed38deselected ->0/56passed |
| foreign-retired-red / green | P -k closed_run / P |1/1failed39deselected ->0/40passed |

Supplemental current-behavior proofs (not invented RED): writer-uncertainty-proof W9pass; detachment-red W -k detaches1pass9deselected; missing-raw-red W -k actual_raw4pass10deselected; unproven-proof P -k unproven2pass26deselected; policy-abort-proof1pass29deselected; observer-matrix-proof3pass32deselected; crossloop-proof1pass39deselected; atomic-batch-proof1pass40deselected; preflight-error-proof1pass36deselected; chatter-proof F/test_watchdog_yield.py9pass; no-tool-race-proof I -k suppressed8pass14deselected; pool-proof I -k real_model_pool1pass16deselected; spawn-proof F/tool_execution/test_spawn_yield.py1pass; offload-permit-proof F/tool_execution/test_blocking_yield.py2pass. All exit0.

Supplemental fixture corrections: live-uncertainty-proof/proof2 failed only incorrect public receipt/retained flag oracle; sticky storage failure returns storage_unavailable and pending retained=1 (§6.5), proof3 I -k unknown_reply2pass14deselected. Saturated-proof/proof2 invalid graph/cwd fixture, proof3 F/test_graph_stream_lifetime.py -k saturated1pass2deselected. Post-plugin-proof initially compared LangChain internal body task, corrected to exact executor message-task observed at post-result interceptor; proof2 P -k post_result_plugin1pass35deselected. Timeout-proof1pass3deselected, consumer-proof1pass4deselected, trace-close-proof1pass5deselected (same lifetime file selectors). No product changes were justified by these fixture failures.

## Serial milestone gates

- `hardening-final-feature5.log`: exit0 **710passed,375warnings,89.69s** (supersedes feature4 709passed; adds atomic batch proof). Exact args:
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
tests/agents/slo_agent/messaging/test_canonical_yield_writer.py
tests/agents/slo_agent/plugins/test_dispatcher.py
```
- Earlier feature-first679pass; final-feature697pass; final-feature2 **exit1,1failed707passed**: existing startup injected-executor gate timed out at3sec BEFORE cancellation/readiness assertions. No oracle/code change or baseline waiver. Same exact test isolated startup-isolated2pass102deselected; identical aggregate final-feature3 708pass, then final-feature4 709pass. This observed intermittent timeout is NOT erased by rerun; investigate if recurring. No orphan process remained.
- `hardening-final-agent2.log`: exit0 **185passed,82warnings,11.57s**; args same accepted185 paths: test_agent.py,test_graph.py,test_agent_recovery.py,test_agent_runtime_event.py,test_agent_streaming_dual_mode.py,test_agent_usage_commit_regressions.py,test_agent_image_history.py,test_graph_stream_parser.py,test_stream_event_dao.py under F.
- `hardening-foundation-regression.log`: exit0 **37passed,7warnings,2.85s**; F/messaging/{test_provider_settlement_guard.py,test_history_cooperative_append.py,test_startup_raw_tool_groups.py}.
- `hardening-final-black4.log`: exit0 **17files**. `hardening-final-mypy6.log`: exit0 **17files**, no exemption. Exact scope: all17 paths in `logs/hardening-source-sha256.txt`, invoked with `/root/.pyenv/versions/slo-harness/bin/python -m black --check <all17paths>` and `PYTHONPATH=$PWD ... -m mypy <all17paths>`, PYTHONDONTWRITEBYTECODE=1. Earlier mypy-first7errors,third2errors,final1error and mypy4 one coroutine qualname union error repaired; no exemptions. Final atomic test uses typed-safe getattr on same task/coroutine and passes1/40deselected in `hardening-atomic-batch-final.log` after this nonbehavior typing/format edit; final710 suite predates only that test expression/format change. Product source unchanged since710/185.
- `hardening-final-diff4.log`: git diff --check exit0. Preflight SHA25610fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638 preserved.

## Finite remainder before core READY (not external blockers)

1. A7/A11 explicit controlled retry/rebuild identity matrix still incomplete: real new urgency DURING retry must prove exact control/policy/source/cursor and frozen empty/note/instruction/both slots across factory/lazy/prebuilt/rebuilt paths. Existing delivery tests cover slots/rebuilds but some predate control and inspect private state; retained pooled/prebuilt live journey now passes, not the full matrix. Do not activate T4 based on counts alone.
2. Ownership integration needs mounted /new + nonmessaging teardown proof against retained observer workers, and OS lease acquisition refusal while final messaging close is held by a suppressing callback. Core gateways now join; actual TUI normal-only teardown callers are not newly exercised here. No new TUI activation implemented. Plugin reload join and bound-method unsubscribe defects repaired.
3. Remaining critical live failure proofs: output-update history failure (not merely text history), consumer failure through whole session, failed cleanup under pooled low existing budgets with no additional claim/request; direct timeout/repeated-cancel/consumer-close and newly wired flat/tree unknown-write already covered. Existing output queue remains unbounded snapshot contract; a producer awaits custom wake after each snapshot, and bytebound graph queue backpressures wake. Assess unusually large snapshots/many simultaneous producers before any claim of fully bytebounded output. No gratuitous queue redesign here.
4. Conventions/source review: new writer is cohesive attempt owner with two real adapters + transient variation, no second scheduler/writer. Executor preflight/start/join orchestration and policy `_settle` remain sizeable; ensure a bounded declarative extraction if independent review finds mixed knowledge. New API docs should be completed where Args/Returns/lifetime details remain terse. No broad unrelated refactor.

Full required make test PYTEST_WORKERS=6 remains **BLOCKED safety-audit C1/C3/C4**, not run/excluded/substituted/waived. Full lint/fullBlack unrun/unwaived. Independent bounded review, T4 activation and final review/completion remain later. No claim that genuine external blockers explain the four core remainder items above.

## Safety and ownership

Every pytest command synchronous foreground, never parallel. No owned workflow/container/real child processes or executable fixtures created. Spawn proof injects launcher at existing factory only. All new file writes resolve below tmp_path; plugin is ordinary .py data, not an executable stub. Real thread leaves released/joined in finally; foreign-loop test closes its loop. Strict isolated journey/lifetime pre-cleanup orphan assertion remains enabled, cleanup-required still fails. `logs/hardening-final-processes.log` and source manifest record final survey/identity; unrelated1261413pytest and3382468fake-herdr untouched. No packages/system/installed executables/harness watchdog changes, no commits/push/merge/PR. SLO.md/docs/durable-composer/preflight preserved. Missing root RESEARCH.md deliberately not created because repository-specific documentation preservation and current user evidence destination override generic creation advice.
