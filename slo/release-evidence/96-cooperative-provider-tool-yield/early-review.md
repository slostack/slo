# A.2 independent early integration feedback — first provider cutoff

**Verdict: REVISE — bounded safety correction, not rejection of the remaining feature plan.**

This is the independent, read-only **Step 1 early-feedback** review, using the installed workflow's “Early integration feedback” checklist, not its Step 2 final-review checklist. The strict reconciler and graph cutoff are a useful runnable foundation. They are **not the silent-provider urgent milestone**, completed T1/T2, full A12, acceptance-ready A.2, or a completed workflow turn. One concrete current-path blocker is ER-01 below. Other missing feature behaviors are expected subsequent work, not demands for final coverage in this slice.

## Review boundary and evidence provenance

- Repository/cwd: `/root/Code/slo-message-queue/slo`; branch `message-queue`; HEAD/baseline `82c3f5c6de9345af34a673a3d975366ca8c1624c` verified read-only.
- Original specification: `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md` (sections cited below refer to this original, not a revised sibling).
- Read all six requested reports: `routing.md`, `acceptance.md`, `implementation-t1.md`, `implementation-provider-guard.md`, `current-handoff.md`, `safety-audit.md`, in this directory.
- Inspected tracked product/test diffs against the baseline **and** the untracked `tests/agents/slo_agent/messaging/test_provider_settlement_guard.py`; traced surrounding graph, agent, session, recovery, provider-pool, projector and executor code. Unrelated `SLO.md`, `docs/` and durable-composer evidence were not changed.
- **No reviewer tests, collection, lint, Black, application invocation, import probe, mutation experiment, nested agent, system/package/infrastructure operation, or git write was performed.** Commands were source/environment reads and git status/diff/revision queries. Only this new report is authored. No test fixture consent was exercised or broadened.
- Reported author results are evidence receipts, **not independently rerun results**: focused 59 passed; normal delivery/projector 122 passed; agent/recovery/plugin 90 passed; scoped Black four files unchanged and scoped mypy two files clean. These totals must not be summed into a full-suite gate. The original T1 report's strict source-order assertion is superseded by the later provider-guard decision.
- Installed `SLO_SKILL_DIR` and `SLO_SKILLS_DIR` were verified equal to `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`. Read its INDEX, actual `orchestration/workflows/code-test-review.md`, overarching solution-design/coding-rules/naming/test-verification/declarative guidance, engineering routing/ownership/testing/review, and routing-selected Python root, signature/docstring/declarative, graph/gateway/tool/application-service and test recipes. The exact project/spec one-shot graph and real-persistence contract specialize generic examples; no graph-class rewrite, synthesis node, ORM, or mock-everything convention is requested.
- Consulted KB `Welcome.md`, `slo/README.md`, `slo/gotchas.md`, message hierarchy, TUI/session and operational references. Root `RESEARCH.md` is absent; no file was created under this read-only assignment. Current user authorization permits this report only; no KB/docs updates were made.
- Accounting carried forward: turn **1 started / 0 completed**; dispatch **7/20**, effective limit **60 turns**; **2 execution retries total** (audit-handoff 1, provider-guard 1); never retry an abort. Primary author remains exact assigned DeepSeek; review assignment `gpt-6.1-sol` high; no fallback invoked. This report does not complete a workflow turn.

## What is actually connected

```text
SloAgentSession.invoke (legacy/prebuilt path in the new test)
  -> _invoke_submission -> _run_attempt_lifecycle
  -> _stream_prompt_with_retries (injects retry AND recovery policies)
  -> SloAgent._react_loop
       -> _inject_before_agent_turn_messages (await dispatcher, append messages)
       -> _execute_iteration_with_retry -> _stream_graph_turn
       -> compiled graph agent_node
            -> require_settled_live(list(state.messages))
            -> pool.ainvoke(raw messages), OR
               adapt_chatgpt_backend_request -> direct.ainvoke(shaped messages)
```

The shared guard at `graph/service.py:200–213` is before either provider branch, after the before-agent contributions (`agent.py:1044–1047,1147–1176`). It is synchronous, copies the list only, delegates the invariant to the existing history-contract owner, starts no task, acquires no queue lock and mutates no live message. The local factory import avoids the documented history/compaction/graph initialization cycle without adding another owner.

For a pool, `providers/model_pool.py:314–410` subsequently selects a member, applies the existing per-member request adapter, unwraps bindings and invokes member `_agenerate`/`_astream`; lane switching is internal to that pool. Invalid input rejected by the graph never enters that loop. No new check inside every pool lane is needed to duplicate the same invariant. Pool `except Exception` does not itself catch Python 3.11 `CancelledError`; reserved-yield propagation/SDK cleanup still needs T2 evidence, not an early claim.

**Important limit:** the new session test never calls `start_messaging`, passes no config/store/`enable_history=True`, and does not submit through `LocalSessionMessagingClient`. From `sessions/service.py:814–828,5303–5317`, this is a real **nonmessaging, history-disabled session cutoff**, not a SQLite/history messaging journey. That is useful first-path evidence; the implementer report's implication that this new test writes SQLite/history must be corrected.

## Concrete findings and closure

### ER-01 — High: settlement failure is still eligible for automatic LLM recovery

**Source:** spec §§3.3,5.5.6,6.5; A11/A12. **Current-slice blocker**, not a request to implement all urgency now.

`UnsettledToolGroupError` is an ordinary `Exception` (`history/message_contract_reconciler.py:26–41`). There are no special exclusions at `agent.py:970–1000` (`_execute_iteration_with_retry`), `agent.py:1178–1218` (`_decide_iteration_recovery`) or `sessions/service.py:6324+` (`_derive_next_attempt_plan`). The stream classifier propagates this nontransport error; the ordinary rate classifier normally declines it. But the session always injects `RecoveryPolicy.classify` (`sessions/service.py:6838–6849,7454–7474`), whose `_is_fatal` does not recognize it and whose fallback is **LLM_RECOVERABLE** (`recovery/service.py:110–130`).

Consequently the actual session path can emit `recovery_started`, append recovery observations and re-enter the graph up to the existing budget of two (`agent.py:250,1056–1083,1237–1255`). In a messaging run that branch also increments the delivery boundary and clears its cached delivery, allowing further input claims/application after the failed settlement gate. The graph guard still blocks the same malformed context, so **zero provider calls plus eventual UnsettledToolGroupError can pass while forbidden recovery already happened**. This is a static causal trace, not a reviewer reproduction. Current reconnect/overflow planners appear to decline this fixed exception incidentally; that is not the explicit fail-closed contract and does not fix the LLM recovery branch.

**Close:** classify this error terminal before generic classification at all three spec-named boundaries; include `CooperativeYieldSettlementError` when introduced. Preserve existing budgets and legitimate provider recovery. Author tests should prove one cutoff/terminal result, no recovery/retry/reconnect/compaction observations, no additional plugin iteration or queue claim/application, unchanged cached boundary, and zero provider requests. Use a real client/session/store for the messaging case and read receipts/history back. An injected permissive recovery policy must not override the invariant. Do not “fix” this by disabling all recovery or weakening the guard.

### ER-02 — Medium evidence correction: distinguish unrun static gates from blocked execution gates

**Source:** installed engineering-testing evidence policy; spec §9.2. `implementation-provider-guard.md` calls full `make lint` and Black **BLOCKED by executable-fixture consent**; `current-handoff.md` also groups full static baseline with blocked gates. `Makefile:47–48` runs `poetry run mypy src/ tests/`; Black `--check` statically reads code. Neither inherently executes pytest installer fixtures or mutates stub executables.

**Close:** author should correct the next handoff/report: full test gate **BLOCKED/UNVERIFIED** pending specific fixture consent; full mypy/Black **UNRUN/UNVERIFIED**, unless a separate concrete static-tool blocker is evidenced. Retain the scoped results with their actual scope. Please correct the inaccurate causal claim; no reviewer execution is requested or authorized here. Do not run `make format` as a replacement for a check or reformat unrelated work.

### ER-03 — Bounded proof gaps in the new guard tests

**Source:** spec §§5.1.5,6.1,9.1 A11/A12; test-verification policy. **Next cutoff-hardening work**, not proof that pool wiring is absent.

- New provider tests exercise a direct model only. Add a small real `ModelPool` negative case (all external member recorders stay zero) and a valid settled-context positive case. Static common placement is correct, but existing pool construction/adapter tests do not prove this new negative cutoff.
- `RecordingProvider` counts only `_astream`; graph `.ainvoke` can use inherited `_agenerate`, while session dual streaming uses `_astream`. Count/record both external entry modes and include a positive request assertion so “zero” cannot be a dormant counter. Current graph `pytest.raises(UnsettledToolGroupError)` is independently useful and would fail if the guard were simply deleted; this is not a claim that both tests are vacuous.
- New session test discards every event and checks only eventual exception/count; it cannot detect ER-01. Capture the public stream and, in the durable variant, read history/receipts after joined close. Assert no recovery/extra claim rather than only final failure.
- The nonmutation test copies the list shallowly (`test_message_contract_reconciler.py:170–182`): mutating a shared message or status would change both sides equally. Compare detached serialized snapshots, including success/error status and call arguments, across passing and failing validation.
- Blank/duplicate call-ID and `invalid_tool_calls` tests leave groups unresolved, so removing those individual rejection checks may still fail at list end. Supply otherwise matching complete results; add nonmapping call entry, blank/missing name, whitespace/nonstring ID examples where they isolate the actual branch. Existing strengthened malformed-args tests correctly use matching results.

**Close:** focused, test-first author proofs that fail when each targeted decision/cutoff is removed; real flat/tree readback for durable claims. No Cartesian product of every unit case at every journey layer is required.

### ER-04 — Malformed outer call-container behavior remains unspecified by the implementation

**Source:** spec §6.1 complete/partial-structure validation; fixed safe error contract. **Small defensive hardening**, not a new tool schema policy.

`_open_live_group` uses `for tool_call in message.tool_calls or []` (`message_contract_reconciler.py:137`). Falsey malformed containers such as `{}`/`0` collapse to no calls; a truthy noniterable leaks `TypeError` instead of `UnsettledToolGroupError`. Normal Pydantic construction supplies a list, but the test strategy already uses `AIMessage.model_construct`, and trusted plugin message objects remain mutable. Entry mappings, name, args and IDs are checked once iteration reaches them; the outer structure is not.

**Close:** test the malformed outer shapes at the contract owner and reject them with the fixed safe exception before iteration, or demonstrate an enforced immutable upstream boundary excluding them. Preserve actual supported LangChain shapes; do not add argument-schema/JSON-content/unknown-tool/status/name-match restrictions unrelated to settlement. This is not a demand for arbitrary-object validation throughout the application.

## Compatibility and ownership assessment

- The current guard accepts both `ToolMessage` success and error and does not change either. Historical fabricated placeholders now explicitly use `status='error'` (`message_contract_reconciler.py:285–291`), as §6.1 requires. Status **replay retention** is not implemented: `history/projector.py:413–418` still creates results without core status, and current after-tool patches can replace `is_error` (`tool_execution/executors.py:168–210`). These are expected T1/T3 work, not claims that the live guard must reject ordinary error results.
- Pending-ID removal in any result order matches §6.1. Source ordering remains the executor's obligation (§5.4/A3); reimposing ordered-result rejection in this guard would add a restriction. ID uniqueness spans the supplied provider context, not all sessions/history, and IDs are checked for nonblankness without normalization. The new name/args structure checks are consistent with complete LangChain calls, not tool-schema validation.
- Valid ordinary conversations/settled groups still pass by inspection; signatures/defaults, request shaping, pool/tool identities, scheduler, SQL schema, composer priorities and legacy repair entry point are unchanged. Author-reported 122/90 regression results support ordinary compatibility but are not a full compatibility certification. No concrete unrelated new restriction was found in this diff.
- Strict live validation is not durable raw-history validation: the existing projector still selects/heals legacy history before the graph sees it. Do not describe a healed legacy placeholder as proof of newly marked-group settlement. Keep legacy unmarked compatibility while adding the spec's marked-evidence validation before selection.

## Expected remaining work — evidence map, not early-review blockers

| Spec / acceptance | Missing or unwired behavior and owner paths | Finite closure condition |
|---|---|---|
| §§4.2–4.3,6.1–6.3; A8/A12; remaining T1 | Validated metadata/DAOs, restricted cooperative append-once in `history/{store_protocol,filesystem_store,tree_store}.py`, raw validation in `history/projector.py`, startup scan and atomic compaction | Both actual adapters read back exact openings/results/no-start records; conflict/unknown reply/fsync/crash/page-boundary failures refuse readiness/continuation; replay status preserved; unresolved groups cannot be healed/selected away/compacted |
| §§3.3–3.4,5.2–5.3,6.5; A1/A7/A10/A11; T2 | `tool_execution/yield_policy.py` control/policy absent; `watchdog_timer.py` still caller-task `anext`, no urgent race/closed outcome; agent/session bind/rebuild/release and attempt correlation unwired | Real local urgent client → scheduler → silent held provider → joined reader/close → one boundary/application → next request without releasing held token; direct/pool, precedence, suppressed/repeated cancellation, normal None item, low budgets, seal and owner/client/abort/hook cases |
| §§5.5,6.4; A8/A9/A11; T1/T2 | Interrupted accumulator, canonical audit/no-start, private-anchor context exclusion, replay/export correlation, stream vocabulary/transcript sealing absent | Two exact correlated interruptions then success, silent notice, late thinking/text isolation, close/reopen/export readback; history-disabled transient parity without durable claims |
| §3.5; A2/A10/A11 | `sessions/service.py::_dispatch_event` still awaits optional plugins/subscribers; no owned bounded callback mailboxes | Held/failed/overflow observers cannot block result → application → terminal; core history stays awaited; teardown retains and joins retiring workers |
| §§5.2,5.4,6.5; A2–A5/A11/A12; T3 | Tool phase/checkpoints/default defer, cancellation port identity/ack/join, concurrent collection, offload drain in `tool_execution/{dao,executors,yield_policy}.py` and `tools/_blocking.py` absent | Real effect/result/defer and denied remainder; all started tasks/ports/post-result plugins joined; trusted controlled cancellation matrix; no success upgrade, rollback claim or lost gather result; original spawn/pool/permits intact, no A.3 protocol |
| §§7,9.1; A6/A13/A14; T4 | Component priority/request action, Ctrl+Enter/Alt+U/palette, urgent snapshot retry and interrupted/defer paint absent; `tui/app.py:1144` remains normal-only | Atomic capability/key/projection activation only after T2/T3; real mounted SQLite journey plus requested two-theme/three-size painted responsiveness and unchanged slash/newline/focus/recall/band behavior |
| §§8.2 T5,9.2–9.3; workflow acceptance-ready/final/completion | Full non-E2E gate blocked; full static baseline unrun; independent final review and completion not yet due | All A1–A14 appropriate evidence, affected/full/static gates on final code, no substitute total/waiver, then separate independent final review and independent completion |

## Bounded next plan and authorization

1. Repair ER-01 first and strengthen the cutoff proofs in ER-03; address ER-04 at the same existing reconciler owner. Correct ER-02 and the new session test's history/SQLite description in the author handoff. Preserve unchanged legacy APIs and ordinary recovery.
2. Finish only the prerequisite history/control contracts needed for the representative T2 silent-provider journey, with both-adapter settlement evidence. Keep one scheduler/graph driver/context writer and the host normal-only. Deliver the actual urgent journey before calling M1 ready; do not expand into all tools/TUI merely to satisfy this early review.
3. Continue T3 → T4 → T5 as the original dependency plan requires. No initial built-in `cancel_confirmed`, no replacement pool/spawn, IPC, pending-dispatch/A.3, new dependency/schema/process, or unrelated refactor is requested.
4. Full `make test PYTEST_WORKERS=6` stays **BLOCKED** pending the other specific fixture consents. Existing narrow consent covers only `tests/cli/test_deploy_install_worker.py`'s own `<tmp_path>/bin/curl` write/chmod0755/child-only PATH; it does not authorize another executable/bin/installer fixture directly or indirectly. Do not exclude tests, substitute serial/subset totals, or switch models to evade this boundary. Safety-audit consent questions are requests, not grants.
5. Static checks are separately **unrun**, not inherently blocked by that consent. Their later authorized results must distinguish baseline from introduced findings without modifying unrelated files. Reviewer ran none.
6. Required pipeline remains **runnable slice → independent early feedback (this report, no reviewer tests) → acceptance-ready all scope/full gates → independent final review → independent completion**. This feedback stays inside Step 1 and authorizes none of the later claims or external delivery operations.
