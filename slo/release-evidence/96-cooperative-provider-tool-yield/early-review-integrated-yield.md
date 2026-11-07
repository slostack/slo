# 96.A.2 — bounded independent integrated-yield rereview

**Verdict: REVISE / NOT READY. Step 1 remains BLOCKED.** The urgent provider/tool/TUI journey is connected and has substantial retained author evidence. Eight finite findings below remain: six behavioral/ownership gaps, one mandatory-convention repair, and one explicit acceptance-evidence gap. This is advisory early integration feedback **inside Step 1**, not formal Step 2, final acceptance, completion, or a new workflow turn.

## Authority, scope, and evidence limits

- Governing source, read fully: ORIGINAL `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md` (1309 lines). Section/acceptance references below refer to that file, not a revised sibling.
- Read all nine requested receipts: current handoff, urgent-TUI implementation, core hardening, core yield, early urgent review, continuation ledger, routing, acceptance, safety audit. Reuse the accepted cutoff/append/raw reviews at their bounded scope; no foundation restart or reopened A.1 prerequisite.
- README read first, including runtime, watchdog, TUI ownership, testing, and Maintainer style rules; actual SLO.md and Makefile consulted. Root RESEARCH.md is absent; report-only authority does not permit creating it. Consulted KB Welcome → slo/README and gotchas. Current explicit destination overrides older KB-only documentation advice.
- Git metadata text confirms `message-queue`, HEAD `82c3f5c6de9345af34a673a3d975366ca8c1624c`. Used structured HEAD/worktree diffs for graph/service.py, agent.py and app.py; directly inspected new and affected source/tests. This is not a certification of the entire unrelated dirty tree.
- Skill root is the current user-supplied equal SLO_SKILL_DIR/SLO_SKILLS_DIR `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`; no executable environment probe was made. Read installed INDEX, exact workflows/code-test-review.md early checklist/shared workflow, engineering routing/review/testing/ownership, overarching solution-design/coding-rules/naming/test policy/declarative/code-design guidance, Python root/keyword-types/docstrings/declarative/review, scoped graph/gateway/tool/testing recipes and Textual recipe. Original spec's one-shot graph/custom executors and shared real-persistence policy govern over generic examples calling for a topology rewrite or mocked internals. No relevant user override selected.
- **No shell commands, tests, collection, static checks, imports, product executable, nested agent/workflow, dependency/system/package/executable mutation, or git write.** Only this report is written. No test resource was created or process signalled. Unrelated PIDs 1261413/3382468 and other checkouts remain untouched. Installed framework files were read only; no dependency change is requested.
- Counters supplied for this assignment: **turn 8, dispatch 17/20, total 65; eight started, zero complete, all partial; twelve execution retries, no aborts; limits 60/20**. Three calls remain this turn. This review adds no execution retry and resets no count. Author gpt-6.1-sol medium / reviewer requested high remains current authority; historical DeepSeek/quota conditions are superseded. No independent harness-model attestation claimed.

## Actual connected path

```text
TyperDispatch interactive startup/resume (messaging_enabled=True)
  → PromptInputComponent key/request_submission + stamped Submitted(priority)
  → SloTUI submitted handler / slash precedence / immutable draft capture
  → existing MessageSubmissionAdapter → LocalSessionMessagingClient
  → session admission → SessionMessageQueue → real SQLite commit/receipt
  → sole scheduler → one MessageRunState + ToolExecutionControl / retained policy
  → readiness binding → same graph compiler / retained bound LLM, tools, queue, mode
  → agent boundary (note then instruction, identity before acknowledgement)
  → watchdog-owned reader → updates-only graph driver / public model callbacks
       provider: reserve → cancel/join → close → truth/no-start/interruption settlement
       tools: enter before effects → preflight → exact invocation task → defer/ack + joins
  → trusted CooperativeHistoryWriter → append-once/fsync → raw certification/live pairing
  → one continuation gate/boundary advance
  → best-effort bounded presentation → exact answer/thinking widgets / replay/export
```

Source anchors: `src/cli/typer_dispatch.py:134–154`; prompt component `:183–196,525–544,997–1096`; `src/tui/app.py:1140–1150,2374–2428,2773–2822`; `messaging/client.py:105–165`; `sessions/service.py:1010–1095,1172–1224,5710–5754,7402–7435,8126–8354`; `agent.py:330–372,773–1112,1290–1425`; `graph/service.py:194–272,335–389`; `tool_execution/executors.py:78–191,389–471`. Agent-relative abbreviated paths in this report are under `src/agents/slo_agent/`.

Actual source retains one scheduler and live-context writer; generic clients and SQL schema stay unchanged. Normal Enter does not request cancellation. Host urgent capability, Ctrl+Enter replacement, Alt+U, palette callback, immutable priority, unsupported legacy refusal, slash precedence and fixed widget treatment now land together. Earlier reports saying “TUI normal-only” are historical, not current facts.

## Finite findings and closure conditions

### IY-01 — High — a pool can switch providers *inside cancellation cleanup*

**Spec:** §§5.3.4/7, 6.5; A10/A11: reserved yield/failed cleanup must not switch/reconnect or make another provider request.

**Source:** `graph/service.py:226–272` cancels its retained provider-consumer task, but does not communicate cancellation ownership to the retained ModelPool. `src/agents/providers/model_pool.py:387–407` catches any `Exception` before the first chunk and runs ordinary fallback. `credit_exhaustion_policy.py:245–246` classifies a RemoteProtocolError/ReadError as switchable disconnection.

**Concrete scenario:** silent pooled member is cancelled after urgent reservation; its finally/cleanup raises a switchable transport exception instead of CancelledError. The pool catches that exception **before** `_invoke_joined_provider` or watchdog can translate it, cools the member, and starts fallback with the old context. Catching Exception rather than CancelledError is insufficient: the cleanup failure is an ordinary exception. Current `test_real_model_pool_retains_live_thinking_and_member_on_urgent_yield` proves normal cancellation, not this branch.

**Closure:** keep cancellation/settlement authority visible at the provider/pool boundary so a member error after an owner cancellation request is terminal cleanup failure, never fallback. Preserve normal pre-output fallback when no cancellation was requested. Failing-first real-session/SQLite + real ModelPool proof: held first member, urgency, cleanup raises switchable error, fallback count zero, no extra application/claim, pending urgent retained, fixed settlement failure, all owned work joined. Use low existing budgets; no dependency patch/new pool/parallel provider driver.

### IY-02 — High — public consumer close does not join the nested generator chain

**Spec:** §§3.4.7, 5.3.7–8, 5.5.6, 6.5; A10/A11; one owner joins before release, including consumer failure.

**Source:** `agent.py:1714–1727` forwards `_execute_run` with bare `async for` and immediately clears attempt/running state in finally. The same forwarding pattern appears at `:1633–1640`, `:1328–1335`, `:1230–1240`. Only the innermost `_stream_graph_turn` owns graph close. `sessions/service.py:6984` closes `agent.invoke`, not every suspended child iterator.

**Concrete scenario:** consume a live text event from public `agent.invoke`, then explicitly aclose it (or fail in a session-side consumer while that event is yielded). Closing an outer async generator does not synchronously aclose its suspended inner iterator. The outer finally can mark the agent idle before inner graph/provider cleanup completes; eventual async-generator finalization is not a join barrier. The retained `test_consumer_close_after_live_chunk_joins_provider_once` (`test_graph_stream_lifetime.py:214–264`) starts at **stream_graph_events**, so it cannot prove this public chain. Messaging compatibility-observer detachment is a separate contract and correctly must not abort the scheduler.

**Closure:** retain/close each delegated iterator, or give the public invocation one cohesive retained teardown owner that reaches the graph and joins before clearing running/attempt state and before session binding release. Carry close failures as terminal settlement failures. Add a public-agent close test with held provider cleanup, repeated close-wait cancellation, exact close-once and not-idle-before-join; exercise one actual session-side consumer failure with SQLite/history and prove no retry/extra claim. Keep borrowed observer/client detach semantics unchanged. No product all_tasks sweep.

### IY-03 — High — abort arriving during the reserved-yield join can become completed

**Spec:** §§5.3.3, 5.5.7, 6.5; A10/A11: abort wins, no synthetic success, accepted pending input survives.

**Source:** `watchdog_timer.py:194–201` reserves then awaits join and returns yield without re-arbitrating abort. `_stream_graph_turn` then emits interruption (`agent.py:952–984`); `_execute_iteration_with_retry:1241–1242`, `_react_loop:1374–1375`, and `_execute_run:1642–1643` return on abort with comments assuming run_aborted was already emitted. It was not emitted on this path. Session tracker defaults aborted=False; normal exhaustion reaches `_finalize_successful_attempt` (`sessions/service.py:6019–6023,6176–6245`), whose else writes run_completed. Scheduler can also synthesize completed when no terminal was observed.

**Concrete scenario:** urgent reservation has won; provider cancellation cleanup is held; operator aborts before releasing that cleanup. This is after the watchdog's initial abort check, so the existing simultaneous-abort unit test does not reach it. Continuation is prevented, but the final outcome can falsely be completed (and post-success compaction may run).

**Closure:** after joined cleanup, resolve the final stop/settlement outcome before returning yield/terminal. On successful cleanup publish/persist exactly one abort, retain unapplied urgent and pause; on cleanup failure retain failure precedence. Prove with real admission/session/SQLite, abort while reserved cleanup held, no early terminal/next request and no completed terminal. This shares the lifecycle repair seam with IY-01/IY-02, not a new phase.

### IY-04 — Medium — interrupted partial tool identities are not response-scoped

**Spec:** §§6.4.4, 7.2; A6/A9: seal only matching response's incomplete arguments, preserve other iterations, ignore stale repair.

**Source:** `src/tui/components/chat_transcript/adapters/transcript_projector.py:134–138,316–369,471–477,779–823`. Answer/thinking maps are correlated, but tool widgets/buffers/recorded IDs remain keyed only by call ID. `_tool_responses[call_id]` is overwritten by a newer response. The interrupted-key guard at `:264–271` omits tool_call_delta/end.

**Concrete scenario:** first interrupted provider leaves partial call ID `c`; later iteration/attempt reuses `c` (valid because the interrupted opening was excluded from live context). The second delta reuses the first incomplete widget and its identity slot; or a late delta/end for the interrupted response recreates its cleared buffer. The new mounted test uses **different** IDs first/second, so it proves other-response filtering but not this ownership collision. `ToolExecutionBlock.update_tool_call` does not undo is_incomplete.

**Closure:** key partial-tool widget/buffer/dedup ownership by exact response plus call ID and reject late argument repairs for interrupted response keys. Results must still address their matching live call without altering other responses. Add one mounted same-ID-across-responses regression and one late interrupted argument repair case; preserve retained first partial, distinct successor widget/result, terminal liveness and no buffer revival. No new panel/widget type or provider ID renaming.

### IY-05 — Medium — declared cooperative stream contract is only partly produced

**Spec:** §4.3, §5.3.4 (original line 697), §6.4.2, §7.2 (line 1064): requested diagnostic and corresponding notices carry validated reason/correlation, never applied acknowledgement.

**Source:** `yield_policy.py:188–210` captures requested canonical audit, and `agent.py:938–951` writes it after close; **no source producer constructs kind=yield_requested** (only enum/projector references). `agent.py:968–973` constructs iteration_interrupted with attempt/iteration/text but no cooperative_yield_v1 metadata. `sessions/service.py:8310–8319` correctly supplies typed metadata for defer. `events/stream.py:89–106` adds a field/kinds but no cooperative consistency validation. Runtime assistant_delta/completed trace mapping also does not add the §6.4.2 promised attempt_turn_id metadata (`agent.py:2033–2084`, session runtime handler `:8156–8197`); durable event.turn_id currently supplies replay correlation instead.

**Closure:** emit the specified nonterminal requested observation without awaiting observers, carry the same captured typed metadata on interruption, and stamp/validate attempt correlation at the session's publication/persistence boundary. Keep canonical audit awaited at settlement, deduplication and safe fixed copy. Tests assert actual emitted kinds/metadata agree with persisted audit and reject mismatched reason/disposition/attempt correlation. No fake applied receipt and no stream run_retrying cooldown for yield. This is a named original contract gap, not a request for extra UI notices.

### IY-06 — Medium — retired observer handlers escape the bounded registry

**Spec:** §3.5.3–6: at most 64 external registrations/retained ownership; failure/expiry/overflow retires the observer, bounded lifetime and cleanup.

**Source:** `sessions/service.py:4044–4062` prunes joined retired mailboxes before capacity checks, but `_subscribers` is appended separately. Mailbox retirement on exception/expiry/overflow (`sessions/presentation.py:49–64,82–106`) never removes that handler from `_subscribers`; final publication close also leaves it intact. Consequently repeated failed observers + new subscriptions can grow this parallel strong-reference list indefinitely while mailbox count remains under 64. Existing capacity test retires via explicit unsubscribe before workers run; that does not exercise automatic retirement/pruning.

**Closure:** give the session registry one bounded authority for live/retiring observer registrations; automatic retirement and joined pruning must release the corresponding handler references without losing suppressing workers. Preserve sync unsubscribe compatibility and exact join operation. A finite repetition/weak-reference test through session subscribe/publication proves capacity and release after failure and final close; held suppressing callbacks remain reachable until joined. No second registry/event service or task per event.

### IY-07 — Medium — finite changed-code convention hardening is still required

**Rules:** original §2.3; README Maintainer Style; installed keyword/type/docstring/declarative/ownership rules. Scoped Black/mypy is not a convention waiver.

**Concrete changed sites and required correction:**

1. `agent.py:773–984` mixes transport construction/decoding, stop arbitration, retry eligibility, audit transfer and settlement in one expanded orchestration body; `ConcurrentToolExecutor.execute:389–459` mixes batch validation/preflight, registration and result/exception ordering; policy `_settle:578–643` embeds temporal ack authority and terminal selection. Extract only meaningful typed steps inside their existing owners (read/arbitrate/settle; preflight/register/join; ack validity/terminal outcome). Keep state-machine decisions with control/policy, not caller reads of private fields. No eight-line mechanical splitting or architecture rewrite.
2. New `graph/event_stream.py::stream_graph_events` and `retain_completed_response` contain core lifecycle behavior as free functions, outside README's tool-bridge/node/test-helper exceptions. Put this cohesive transport behavior behind one class-owned operation, preserving one graph driver and the public callback seam; do not refactor the entire preexisting graph builder. The spec expressly exempts the existing topology, not new transport ownership.
3. Fix newly added multiargument positional calls where keywords are supported: `graph/service.py:370` adispatch_custom_event(name=..., data=...), `src/tui/app.py:2377` SystemCommand(title=..., help=..., callback=...), `yield_policy.py:610–614,619` asyncio.wait(fs=...). Existing framework positional-only overrides remain framework contracts, not targets for a signature-breaking change.
4. Complete changed public contracts: bind/release_tool_execution lacks Args/Raises and join/recompile preconditions; agent.invoke omits message_run/attempt_turn_id; build_slo_agent omits new control/policy; executor execute docs omit control/policy. Explain terminal cleanup failure/cancellation ownership, not implementation trivia. Give new significant task/result/preflight variables concrete annotations; avoid new bare dict/list signatures in the added lifecycle/cancellation tests (`test_graph_stream_lifetime.py:30`, `test_yield_policy.py:1155`). Framework Any kwargs remain necessary but should be identified as framework data, not an untyped application contract.

**Closure:** one scoped convention pass over these changed seams with the behavioral repairs, unchanged meaning/identity/ordering, affected regressions plus current scoped static evidence. This list is finite; no unrelated historical style cleanup, new generic registry, or blanket graph-class conversion is requested.

### IY-08 — High acceptance-evidence gap, not an asserted product defect — finish the named A7/A11/§3.5 remainder

**Spec:** §§3.4, 3.5 final paragraph, 5.1–5.2, 6.5; A7/A11 and §9.1 additional assertions.

**Current evidence:** `test_yield_retry_identity.py:118–220` covers instruction × factory/prebuilt × rebuild/no rebuild with urgency during retry and exact successful binding/source/delivery/LLM bind counts. `test_delivery.py:755–812` already covers a genuine configured lazy **normal** run; `:2510–2631` covers ordinary note/both/empty behavior, including a private-source empty test rather than active controlled retry. Retained pool urgent and ordinary fallback tests are useful, not full exhaustion/cleanup evidence. Mailbox unit tests cover error/byte/budget; real tool journey covers a held subscriber, but not failed/overflowed subscribers through the **whole** defer → result → next application → terminal route required by §3.5. Handoff lines 30–31 acknowledges these limits.

**Finite closure:** use representative cases, not a Cartesian product:

- active controlled cached **empty, note-only, both** retry selections preserve frozen delivery/high-water/cursor and do not claim newer arrivals early; existing instruction proof stays accepted;
- one genuine production-lazy urgent/retry binding path (external provider substituted only at its boundary), plus real pool retry/exhausted low-budget case: retained source/control/policy/mode/tool/output-queue identity and no duplicate child pool/spawn/LLM bind;
- close the pooled cleanup failure and public consumer failure with IY-01/IY-02 tests rather than duplicate supplements;
- one whole-session failed subscriber and one whole-session overflowed subscriber route, proving actual history/SQLite/result truth and next input/terminal independent of presentation retirement, with joined final observer ownership.

Reuse existing stop-hook/abort/source-order/flat-tree/transient proofs where their assertions reach the changed behavior. No duplication of every matrix at TUI, graph and store. Maintain one author-owned test cycle, release gates/retain and join all tasks/leaves on success/failure/cancel, verify no owned resources remain before reporting test completion. No executable fixture authority is added.

## Prior UJ-01–04 disposition

| Prior ID | Current source/test/receipt check | Disposition |
|---|---|---|
| UJ-01 framework waiter orphan | `graph/event_stream.py:194–236` owns one updates-only driver, drains backpressure and joins exact driver; public structured callbacks supply live chunks; retained lifetime file covers saturated close, timeout/repeated cancel, held/raising provider cleanup. Enabled isolated_journey_tasks remains in feature tests. | Original messages/custom transport leak path repaired for normal compiled path; narrow closure accepted. Do not extend that to public delegated-iterator lifetime (IY-02) or failed pooled cancellation (IY-01). No dependency escalation justified here. |
| UJ-02 suppressed completed truth | `agent.py:986–1064` consumes retained exact completion after close, captures observed usage, emits trusted opening/no-start/interruption; writer/real adapters certify. `test_messaging_yield.py:234–343` covers flat/tree × transient/durable × opening/no-opening, zero starts, 10 observed tokens, private-anchor exclusion. | Closed at original seam; no new foundation work requested. |
| UJ-03 cleanup skipped after early assertion failure | Outer `isolated_journey_tasks` fixture `test_messaging_yield.py:82–109` owns isolated-loop cleanup in finally, retains pre-cleanup pending-task failure; main journey acquisition/client/session cleanup protected `:132–230`. | Original defect closed. New author tests must preserve the same discipline; the fixture is not permission for a production task sweep or proof of every leaf's ownership. |
| UJ-04 fallible drain before close / early abort | `_stream_graph_turn` closes unconditionally before its trailing drain; direct abort closes before terminal; controlled trace errors translate terminal. Lifetime/history/output-failure tests present, 752 aggregate includes them. | Original ordering defects closed for those paths. Public consumer chain and abort during reserved join are new precise remaining cases IY-02/IY-03, not a reopening of successful direct proofs. |

## A1–A14 source/evidence acceptance map

“Supported” means source/assertions and retained author receipt support the named behavior; **not reviewer-executed**, not final row acceptance while related findings remain.

| Row | Source / actual evidence inspected | Current disposition |
|---|---|---|
| A1 | watchdog/control/agent settlement; real silent/partial × flat/tree journey; mounted provider tests | Connected/supported; IY-01–03 prevent full lifecycle acceptance. |
| A2 | guarded sequential executor, offload shield/semaphore; real write effect/result and mounted thread/paint test | Default defer/denied remainder/effect truth supported; §3.5 failed/overflow whole-route evidence in IY-08. |
| A3 | concurrent all-preflight → await-free registration → joined source sort; tests for held interception, all-task registration, sibling error | Supported; no eager concurrent policy invocation. No separate Cartesian demand. |
| A4 | exact original tool/task port registry; actual normal wins; callback-once, five-second monotonic threshold/defer, early/wrong/success/naked/late ack, post-result plugin and repeated cancellation tests | Dense policy support; full-session critical cutoff uses IY-01/02/08. Cancellation is not rollback. |
| A5 | unchanged original spawn/pool; test_spawn_yield holds real pool permits/aggregate with injected child timing, no real child | Supported at authorized no-real-process boundary; no A.3 import/type/registration demanded. |
| A6 | prompt priority/key branch + app action/palette + real mounted provider tests/keys | Connected/supported; incomplete-tool exact ownership IY-04 and contract IY-05 remain. |
| A7 | boundary cache/control high-water; older-urgent backlog real journey, new urgency during instruction retry | Partial; exact missing classes IY-08. |
| A8 | trusted writer deterministic IDs/full ordered arrays/core status; append-once/fsync; raw before selection/startup; unknown reply live both adapters | Supported; reuse cutoff/append/raw acceptance unchanged. No new source defect found in these retained barriers. |
| A9 | accumulator interrupt, exact answer/thinking keys, correlated replay/export; two interruptions/reopen; no-start/excluded private anchor; tools retain actual anchor/results | Supported for inspected proofs; IY-04 partial-tool collision and IY-05 stream correlation remain. |
| A10 | closed None/item/end/yield outcomes; phase exit, abort/item/deadline/urgency arbitration; repeat-cancel/close-once tests | Partial; IY-01–03 are concrete missing interactions, not entire-matrix restart. |
| A11 | one control/cursor per run, compiler reuses retained LLM/tools/mode/queue, factory contract preserved; mounted /new/own close/borrowed client/OS lease | Strong partial; IY-01–03/08. Binding after production lazy build is present even though constructor does not forward control directly. No independent defect asserted for that equivalent ordering. |
| A12 | exact-object capability/weak retired-task guard, strict live nonhealing guard after plugin context, core error status cannot upgrade, raw marked validation/group-atomic compaction | Supported at retained bounded scopes. No claim every unrelated dirty file is convention-clean. |
| A13 | immutable nested priority, existing adapter same-ID query/retry, real SQLite rejection/unknown/new edits/retirement; legacy refusal | Supported; no normal downgrade or new-ID guess seen. |
| A14 | six actual thread-leaf theme/size cells: output + native edits/paint/defer before release/effect, same geometry; provider matrix and existing recall/band tests | Supported for specified responsiveness. No extra process/panel/token introduced. |

**Do not invent two extra blockers:** original §§6.4/7 and A14 require durable interruption before next request and visible responsive paint before **held leaf release**; they do not require a frame acknowledgement before the next model request. Best-effort observers are explicitly nonblocking. Current core audit/application ordering + mounted paint is relevant evidence; no renderer wait should be added to execution. Likewise the registered palette command/callback is exercised in a mounted real journey and shares request_submission. Actual palette search-navigation is useful supplemental UI coverage, **not an independently established defect or additional acceptance blocker**. At 60×20, native scrolling to older content is not a geometry regression or a promise that all past notices remain simultaneously visible.

## Receipts checked — not run or recomputed

Read final raw outputs and exact scope/environment narrative in implementation-urgent-tui.md:

| Author artifact under logs/ | Raw recorded result |
|---|---|
| tui-affected-final2.log | 411 passed, 155 warnings, 339.24s |
| tui-core-final.log | 752 passed, 393 warnings, 94.35s |
| tui-agent-final.log | 185 passed, 82 warnings, 11.68s |
| tui-mypy-final.log | Success, 19 files |
| tui-black-final.log | 19 files unchanged |
| hardening-final-feature5.log | 710 passed, 375 warnings, 89.69s; superseded scope, do not add to 752 |

The final raw files are stdout/stderr captures, not embedded full command/exit manifests. Exact commands, cwd, synthetic environment and author exit-0 statements are in their implementation receipts; source SHA256 manifests were read **not recomputed**. No cryptographic/current-byte execution attestation is claimed. Counts are not combined into a suite total or promoted to full gates. Source/test assertions inspected govern adequacy.

Read retained mounted RED/green samples: Ctrl+Enter old behavior failure; late exact interruption marker repair; different-attempt partial-tool failure and its 2-pass green. These support their stated chronology, not newly invented RED for supplements. Earlier aggregate timeout and startup timeout remain disclosed, not silently erased by final passes. Final process log lists the two unrelated historical PIDs only; that is retained author cleanup evidence, not a reviewer live survey.

## Gate blockers — separate from product repairs

| ID | Required gate / truth | Exact closure |
|---|---|---|
| GATE-01 | Full non-E2E **BLOCKED**, no consent or waiver. Required command remains `make test PYTEST_WORKERS=6` from application root with verified Makefile test environment. Serial reproduction does not avoid the consent issue. | Explicit operator C1/C3/C4 permission below, then audited safe final full run, no exclusion/skip/xfail/subset substitute; owned resource cleanup and required host-integrity verification after command-stubbing suite. |
| GATE-02 | Full lint/full Black **UNRUN / unwaived**. Scoped 19 and prior 17-file evidence does not cover src/ + tests/. | Run `make lint` and project-wide `poetry run black --check src/ tests/` safely on final source, report exact results/baseline attribution; do not autoformat protected/unrelated work. No YAML-stub/baseline exemption inferred. |
| GATE-03 | Historical implementation-before-RED deviations remain **unwaived**; later sensitivity probes/supplements cannot change chronology. | Preserve explicit deviation/evidence ledger; use failing-first tests for each new repair. This rereview grants no retrospective compliance, waiver, or instruction to manufacture RED. Unresolved mandatory-process status prevents READY. |
| GATE-04 | Formal independent final review/completion **not performed**. | Only after Step 1 required implementation/evidence/gates are acceptance-ready; this report cannot be substituted for either phase. |

### Exact permission blocking the final suite

Only existing `tests/cli/test_deploy_install_worker.py` verified temp `bin/curl` write/chmod0755/child-PATH fixture is currently consented. It was not run here. `safety-audit.md §4` still needs:

- **C1:** existing non-E2E rows 1–23: create/chmod disposable fake executables and bin directories **only inside their verified pytest temp roots**, child-only PATH. Families: fake_herdr; CLI install/update/isolated-launcher/layout/writer/mirror/source-smoke; scheduling helpers/OS integration; TUI Herdr activation/editor wrapper; contained integration Herdr restore/safety fixtures. Includes regular passthrough wrappers that exec absolute tools, never writable symlinks to real binaries.
- **C3:** listed temp-owned **non-executable** data/directory mode changes: auth credential-store/file-split, TUI messaging-failure matrix, connector store, plus audited data fixtures.
- **C4:** listed child executions of real bash against fixture PATHs (install/update/isolated launcher), no real-system binary mutation.
- **C2 is not needed for this default gate**: row 24 is E2E-only and default command excludes e2e by its established contract, not a new exclusion.

These are bounded fixture permissions, not permission for host/package/install/dependency changes. Unlisted sites remain unauthorized pending audit. If any required permission is refused or another unsafe transitive fixture is found, report the full gate BLOCKED; do not weaken it.

## Safe finite next action / stop boundary

One cohesive author repair assignment can finish IY-01–07 and the representative IY-08 evidence together: protect the public invocation and pool cancellation boundary; resolve abort after joins; finish exact partial-tool/stream contracts; bound observer registration lifetime; perform the specified changed-seam convention pass. Use existing pytest/session/SQLite/history/controlled provider/port fixtures, no new harness. Reuse accepted foundations and successful TUI/offload/OS-lease proofs; rerun affected proofs and safe static checks serially after relevant revisions. No tests are authorized **for this reviewer** and no final full-suite consent is implied for the author.

Use the remaining three dispatch calls for cohesive repairs, safe gates and honest handoff, not additional ceremony or cosmetic matrices. If full-suite permission is still absent, stop with a compact current handoff identifying repaired/open IY IDs and GATE-01–04. **No READY, no formal Step 2 progression, no completed turn, no commit/publication/rollout.** Only this file was written; prior receipts, SLO/docs/durable-composer/preflight and source/tests were preserved.
