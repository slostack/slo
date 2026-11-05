# Claude follow-ups — independent final rereview

## Current verdict: READY

Turn 2 / dispatch 2. Independent reviewer; no implementation authorship, source/test edits, nested agents or commits in this dispatch. READY applies to the authorized FU01–FU07 follow-up slice and FR01/FR02 repairs, with the explicit feature-only verification boundary below. It is not a full Claude bridge acceptance, workflow completion assessment, or live-native compatibility certification.

Read the prior review and revision handoff, then inspected actual bridge/model, adapter, SDK runtime, host abort/failure/session integration and relevant test assertions. Untracked source was read directly; ordinary git diff alone would omit it. Reused the original FU/E1–E4 contract and prior unaffected parser evidence, rerunning the entire authorized feature gate. Unrelated dirty features were not audited.

### Executed verification

CWD `/root/Code/claude-bridge/slo`:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest -q tests/bridges/claude tests/cli/test_claude_bridge.py --tb=short
```

**Exit 0: 233 passed, 95 warnings in 12.10s; no skips reported.** Independently reproduces the reported feature count. Warnings are pythonjsonlogger, LangGraph and Pydantic deprecations. Reviewed temporary HOME/history isolation and the scripted native transport/authentication seam before execution. No full suite, static/build tools, live external calls or native executable runs were performed.

### Finding closure

**FR01 — CLOSED (previously High).** `src/agents/slo_agent/agent.py:744–763` now routes both graph-read exception and available-item abort outcomes through `_prepare_aborted_terminal` (`:1381–1405`). The abort check also precedes EOF return. The helper awaits retained bridge closure before either trace persistence or returning `run_aborted`. A close exception propagates instead of falling through to aborted publication. `_react_loop` emits terminal failure and re-raises; bridge routes have no iteration retry/recovery policy.

Traced failure ownership through `SloClaudeBridge.close` → adapter `close` → runtime `cancel/close` and `_disconnect_until_settled`. The model seals admission, joins its separately retained cancellation task, and requests adapter closure. Unconfirmed disconnect leaves the same runtime/owner retained waiting for cleanup retry; successful cleanup joins the owner. It does not replace the runtime, discard callbacks without ownership, or replay the query. A subsequent close may retry failed cleanup; a settled close is idempotent.

Executed `test_host_abort.py::test_available_tool_boundary_abort_joins_before_terminal[False,True]` in the gate. This real-session/graph/SDK/MCP journey requests abort at `tool_call_start` after a native callback is pending, not while response delivery is blocked. It holds disconnect externally and checks no observable or persisted abort and a live owner before release. Success checks owner done, callbacks empty and transport closed **at** the aborted terminal, exactly one persisted abort, no completion, one query and no tool-result delivery. Failure checks the unconfirmed-closure exception, no aborted/completed history, the same live owner retained, denied new admission, successful explicit cleanup retry and repeated-close idempotence. Source additionally establishes `run_failed` propagation; the new test does not explicitly assert the count/content of that failure event. Author-reported RED is preserved in the handoff; this reviewer did not revert source to reproduce RED.

**FR02 — CLOSED (previously Medium / mandatory convention).** `src/bridges/claude/bridge.py:97–229` retains the async generator and its lifecycle scope while delegating admission, tool/terminal history transitions, proven-unsent audit retention, boundary conversion and cleanup policy to named private operations. `_record_tool_boundary` retains the full assistant content and ordered calls; `_record_live_context` preserves detached semantic history and excludes SystemMessage only from history-off host context. `_retain_unsent_audit_prefix` clears invocation identity without replaying the failed input. Fresh validation remains before the cleanup scope, so invalid fresh input does not newly seal admission. No new wrapper class, moved SDK task owner or parser rewrite was introduced. The remaining stream loop owns event delivery and delegates the independent policies identified in FR02; no mechanical line-count splitting is requested.

### Original requirements and affected regression evidence

| Contract | Rereview evidence and disposition |
|---|---|
| FU01–02 native continuation / only new prompt | Inspected SDK `options.resume` and single `client.query(prompt=text)`, semantic-prefix validation and context recording. Executed real-session history-on/off and compaction-threshold journeys: exact two prompt strings, one tool receipt despite changed source file, distinct answers and two completions. **Proves wiring, not actual native memory.** |
| FU03 turn isolation / repeated and stale IDs | Fresh per-invocation runtime, response assembly and MCP binding retained. Three tool-bearing turns assert three changed file receipts exactly once; stale prior invocation is rejected before current waiters/results change; foreign resumed terminal fails rather than completes. All rerun. |
| FU04 / E1 safe explicit retry | Nine actual-invoke auth/connect failure cases rerun, including later history-on/off. Assertions cover zero failed-attempt wire sends, retained resume identity, one explicit retry, audit-only failed input and bounded typed errors. Extracted unsent-history transition preserves these contracts. |
| FU05 uncertain send and cancellation | First/later recorded-write-then-fail cases refuse replay and demand a new session. Resumed blocked-response cancellation still passes; FR01 now adds delayed/failed cleanup on the normal available-item host branch. |
| FU06 / E3 resource closure | Stop-hook journey still observes joined owner/empty callbacks at completion. Resumed connect/response × successful/failed cleanup cases preserve owner identity and deny admission until explicit closure; repeated closes do not redo settled cleanup. |
| E2 history-off / compaction | Detached live prefix remains system-free; host retains system-prefix ownership. Shared compaction guard remains before compacter invocation; threshold test proves compaction would otherwise trigger. Existing restored/external-history rejection remains in passing gate. |
| E4 concurrent admission / auth closure | Adapter reserves admission across auth and revalidates closure before native start. Executed barrier cases for competing invoke, session close and adapter close/auth-task join; no late native prompts. |
| FU07 parser preservation | Entire fragment and response-boundary suites rerun in the feature gate. FR02 delegates history/chunk construction only; native fragment parsing and validation were not rewritten by this repair. Prior CF evidence remains applicable. |

### Convention pass, recommendations and limits

Completed the vendored `review-feature-code` flow and Python `code-review-rules` post-hook for the scoped repair and affected contracts, using engineering routing/ownership/testing/review, Python root, declarative-structure, named-argument/type, documentation and test-verification rules. New helper signatures are explicit and named; lifecycle/history contracts are documented; canonical invocation/response/tool IDs remain intact. The native session ID mapped to SDK `resume` remains distinct from the host session ID. Existing graph and SDK ownership are preserved. No new HTTP/database/CLI/UI architecture is in scope.

**No remaining blocking findings in this rereview.** Optional strengthening: explicitly assert one persisted/observable `run_failed` with the cleanup diagnostic in the FR01 failure case. The present exception, forbidden-terminal, retained-owner and recovery assertions plus inspected failure wiring are sufficient for FR01 closure; this is not a new gate.

Limitations: available-item/tool-boundary and blocked-response abort paths have executed evidence; EOF-abort uses the same inspected barrier but has no new dedicated race test. No full-suite or nonbridge regression certification, static/build verification, manual TUI verification, or live native transcript persistence/resume/MCP parity was obtained. **Live native resume parity remains unverified and is not claimed.** The user explicitly restricts verification to feature pytest, overriding the usual full-suite acceptance gate for this review only. Historical wider bridge scope remains outside this verdict.

Only this review artifact was edited. The prior REVISE assessment and its evidence remain below as history; its open checkboxes are superseded by the closures above. A separate completion assessment can consume this READY review; no workflow completion is asserted here.

---

# Historical independent final review — turn 1 / dispatch 5

## Historical verdict: REVISE

Turn 1 / dispatch 5. User-authorized unlimited turn/dispatch budgets; no nested dispatch performed. This is an independent Step 2 review of the follow-up slice, not author self-review or a Step 3 completion assessment.

The serial-turn implementation and its feature gate are substantially supported, but the normal host abort branch can publish its terminal event before native cleanup joins. The blocked-response cancellation tests do not cover that branch. A scoped mandatory declarative-structure issue also remains in the modified model orchestration.

Scope: FU01–FU07 and early E1–E4 as recorded in `implementation/claude-followups-handoff.md` and the current request. Inspected actual untracked bridge source, host integration and test assertions, rather than relying on git diff or the handoff verdict. Unrelated dirty files/features were not reviewed. Current user authorization overrides the historical KB artifact-location restriction for this requested file and the repository-wide full-suite gate.

## Executed verification

From `/root/Code/claude-bridge/slo`:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest -q tests/bridges/claude tests/cli/test_claude_bridge.py --tb=short
```

**Exit 0: 231 passed, 92 warnings, 10.45s; no skips reported.** This independently reproduces the reported count. Warnings are pythonjsonlogger, LangGraph and Pydantic deprecations. No full suite, static/build tools, live external execution, source edits, nested agents or commits were performed.

## Actual integration trace

`SloAgentSession.invoke` validates live-session admission, loads persisted projected context (or the bridge's detached live context when history is off), and invokes the real agent/graph. Bridge routes disable iteration retry/recovery. `SloClaudeBridge._validate_messages` compares the semantic consumed prefix and extracts one new HumanMessage. `_start_invocation` passes only that text to the adapter. The adapter reserves admission across authentication and replaces only a successfully settled runtime; `ClaudeSDKRuntime` supplies the completed native session ID as SDK `options.resume` and calls `client.query(prompt=text)` once.

Each runtime owns a new response assembly, MCP tool bridge, invocation binding and delivery queue. Host tool execution remains in the graph; native MCP callbacks receive the exact host result batch. Native terminal identity is checked, SDK disconnect settles, and only then terminal completion becomes available. Host stop hooks call `finish_host_turn`; pending native tools cause permanent closure. Session resource closure reaches the retained agent and adapter; headless finalization and TUI shutdown/replacement call that seam.

## Requirement and early-finding reconciliation

| Contract | Status and inspected/executed evidence |
|---|---|
| FU01 native conversation retained | Implemented SDK resume wiring. `test_followup_retains_native_tool_context_without_replay` executes real session/graph/read/SDK/MCP/history for history-on/off and threshold crossing. The substitute preserves a native receipt across connections and checks `[None, "native-test"]` resume options. **Actual native transcript persistence and resume parity remain unverified**, not certified by this test. |
| FU02 only new prompt, no replay | Supported: exact prompt lists, changed on-disk tool input after first receipt, one tool result, two answers/completions; `_validate_messages` strips only validated consumed prefix and runtime queries only new text. |
| FU03 per-turn isolation, repeated IDs, stale results | Supported: fresh runtime/assembly/tool bridge; three real tool-bearing turns reuse native IDs and obtain three different file receipts exactly once. `test_stale_invocation_results_cannot_release_resumed_waiters` rejects the prior invocation while current MCP callbacks remain unresolved, without reserved results or extra wire receipts, then completes current delivery. Foreign resumed terminal test proves failure rather than completion. |
| FU04 / E1 safe explicit retry | E1 closed within the tested contract: nine actual-invoke failures cover session auth, invoke auth and connect; first/history-on and later/history-on/off. Failed input remains audit-only; explicit retry sends once; later SDK construction retains prior native resume identity. Runtime marks query attempted before awaited query; only settled, uncancelled pre-query failure becomes `ClaudeSubmissionNotStartedError`. |
| FU05 uncertain submission | Supported: first/later write-recorded-then-failed tests refuse automatic and explicit resend with new-session guidance. Model seals uncertain attempts. |
| FU05–06 cleanup/cancel | **Partial — FR01 below.** Resumed blocked connect/response × successful/once-failed cleanup proves retained owner, denied admission, explicit cleanup retry, eventual owner join and idempotence. Blocked-response host abort passes, but does not establish cleanup ordering for abort while graph events remain available. |
| E2 history-off / automatic compaction | Closed: live history is deep-detached and excludes SystemMessage; host reconstructs its own system prefix. Shared compaction seam returns false for bridge routes, including forced/automatic paths. Threshold test first proves the real checker would compact, then verifies suppression and successful next prompt without summary. External/restored-history rejection remains covered by feature gate. |
| E3 stop-hook orphan | Original stop-hook finding closed: `test_host_stop_joins_native_tools_before_terminal` observes completed owner, closed transport and empty callbacks at `run_completed`, zero submitted tool results and repeated close once. This is distinct from FR01's abort-event branch. |
| E4 concurrent admission / auth closure | Closed at portable adapter boundary: deterministic auth barriers prove competing invocation rejection and no late native submission after session or adapter closure, including adapter auth task join. Session auth closure also revalidates configuration before assignment. |
| FU07 parser preservation | Existing fragment/response-boundary tests were included in the passing feature gate; no fragment parser rewrite was required for this slice. No live-native certification follows. |

## Blocking findings

### FR01 — High: normal abort publishes terminal before joining retained native work

**Requirement:** FU05/FU06 safe cancellation and cleanup; retained-owner lifetime contract; host terminal must not imply settled cleanup while native work remains outstanding.

**Where:** `src/agents/slo_agent/agent.py:759–769` and `:1076–1082`; `src/bridges/claude/bridge.py:290–300`.

**Evidence:** `SloAgent.abort()` requests cancellation synchronously. The bridge's `request_cancellation()` only creates an asynchronous cancellation task. When the next watchdog read returns a graph item rather than raising, the `_abort_event` branch immediately emits/publishes `run_aborted` without awaiting the bridge owner. Only the exception branch at `agent.py:747–755` explicitly closes before publication. `_react_loop` then returns on the abort flag before reaching `finish_host_turn`. Closing the graph generator in the streaming `finally` is neither a join of the separately retained cancellation task nor a pre-publication barrier.

**Consequence:** If abort arrives while a text/update/tool-boundary event is buffered and native disconnect is slow or fails, consumers can observe `run_aborted` while the SDK owner/callbacks remain live. At a completed tool boundary the model intentionally retains the native owner, so closing the graph is not equivalent to closing that owner. Later session shutdown is too late to establish the required terminal ordering.

**Evidence limitation:** This is a source-demonstrated missing join, not an executed new reproduction. Existing `test_cancel_resumed_turn_joins_before_host_terminal` and `test_abort_interrupts_blocked_native_response` deliberately block native response delivery; they exercise the error path, not this available-item branch.

**Repair:** Route all bridge abort terminal paths through one cancellation-and-join operation before trace persistence/publication. Preserve the native owner and report unconfirmed closure if cleanup fails; do not publish a settled outcome early or automatically replay.

**Closure:** Add a deterministic real-session journey that aborts with a graph item/tool boundary available and holds native cleanup behind an external transport barrier. Assert no aborted terminal is observable before cleanup release, then owner done and callbacks empty at terminal. Cover raised cleanup with retained ownership and explicit retry. Rerun the authorized feature gate.

### FR02 — Medium, mandatory convention: follow-up orchestration still mixes independent policies

**Rule:** `skills/coding/declarative-method-structure/SKILL.md` (one decision type, flat orchestration), Python specialization, and hard-rules review §1.3. This is not a mechanical eight-line quota finding.

**Where:** `src/bridges/claude/bridge.py:89–181`, particularly `_astream`'s continuation admission, event conversion, consumed/completed history construction, safe-unsent audit retention and failure cleanup branches.

**Evidence/consequence:** The modified streaming gateway constructs assistant tool-call messages and semantic snapshots inline under event-type and pending-state branches, while also deciding submission/retry eligibility and permanent closure. The new terminal-history and unsent-history policies are repeated list/deepcopy constructions inside that lifecycle orchestration. Reviewers must reason about independent history and lifecycle transitions together; the claimed completed convention pass has not resolved this mandatory structure issue.

**Repair:** Keep the async generator/lifecycle owner in place, but extract cohesive private operations for recording a tool boundary, recording terminal live context, and retaining a proven-unsent audit prefix. Let the stream orchestrate those named transitions rather than constructing their data inline. Do not introduce wrapper classes, move SDK ownership across tasks, or broadly refactor the parser/unrelated host code.

**Closure:** Scoped source re-review shows those independent policies owned by named operations with explicit contracts/types, preserving existing prefix, no-history, retry and cancellation tests; authorized feature gate passes. An explicit convention-owner exception would also resolve the rule conflict, but none was supplied.

## Conventions / recommendations / limitations

Applied the vendored feature-review and exact Code-Test-Review workflow, engineering routing/ownership/testing/review, Python root and hard-rules post-hook, declarative-structure, keyword/type and documentation rules. Scope is Python async lifecycle, existing LangChain/LangGraph and official SDK integration; no database/router/new CLI verb/UI feature was inferred. Core dependency ownership and canonical invocation/response/tool IDs remain intact; SDK `resume` maps a native identity, not the host session ID. No unrelated architecture audit was added.

The feature tests use real filesystem history and real SDK/MCP processing with controlled external native authentication/transport. Their receipt assertions are meaningful but cannot prove the native executable persists and reloads the same transcript, preserves MCP parity, or remembers prior tools. That explicitly unverified live boundary is not treated as proven or as a newly invented blocking requirement under the no-live authorization.

Full-suite regression evidence, static/build evidence, manual TUI behavior and live external/native parity were not obtained. The feature-only gate is the user's approved gate, not a full-repository regression claim. No recommendation to expand into unrelated features.

## Finite next steps

- [ ] Must-fix code: FR01 pre-terminal cancellation join; FR02 scoped model transition decomposition.
- [ ] Required tests: FR01 available-item/tool-boundary abort with delayed/failed cleanup; rerun feature-only pytest.
- [ ] Re-review affected source and evidence; preserve E1–E4 closure history above.
- [ ] Keep live-native resume parity explicitly unverified; no live execution without authorization.
- [ ] Update handoff after repair, then independent completion assessment. This review does not mark the workflow complete.
