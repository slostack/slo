# 96.a.2 acceptance contract — source-ID mapped, unverified

**Status:** contract only. No test, lint, Black, collect-only, or runtime feature command was executed. Every row below is **UNVERIFIED**. This file does not claim implementation, review, completion, or family approval.

## 1. Authoritative inputs

- Spec: `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md` (read in full).
- Context: `overview.md` §§2–7; `request.md` §§4.3–6, 10–11; read-only A.1/A.3/C.1.
- Baseline: `message-queue` HEAD `82c3f5c6de9345af34a673a3d975366ca8c1624c`.
- A.1 prerequisite: treated as completed by explicit user authority. KB `slo/codebase-index.md` still carries a stale "A.1 not activated" historical note; it is not current-code evidence and does not reopen the prerequisite.
- Change boundary: A.2 only. No IPC, attached composer, Inbox retirement, replacement supervisor/pool, child suspension, A.3 pending protocol, C.1 duplicate modules, generic plugin registry, SQL migration, or dependency addition.

## 2. Non-negotiable implementation rules

1. **Test-first.** Each behavior increment gets a failing real-boundary proof first, then the smallest implementation, then green + refactor. No bulk-write-then-test.
2. **Journey first.** Real entry (editor/local client -> `SloAgentSession` -> scheduler -> agent/graph/tools -> canonical history/SQLite) -> persisted state read back. New feature tests must not mock the queue, SQLite, filesystem history, scheduler, graph, or executors.
3. **Doubles.** Replace only external model/provider boundaries with `FauxChatModel`/controlled provider-boundary streams. Inject internal clocks, cancellation ports, and timing collaborators through constructors/factories/parameters. No patching private methods, no `obj._dependency = ...`.
4. **Tell-don't-ask / declarative.** The owner enforces invariants; callers request behavior. Flat guard clauses, named steps, one decision per method, no nested orchestration.
5. **Types and names.** Pydantic 2 DAOs for new carriers: `ConfigDict(extra='forbid', strict=True, frozen=True)`, documented `Field`s, validators; runtime handles `arbitrary_types_allowed=True`, `exclude=True`, `repr=False`. Explicit parameter/return annotations; keyword arguments for multi-argument calls; Google-style docstrings. Domain vocabulary from the spec, not invented synonyms.
6. **No regressions.** Preserve every existing keyword/default, legacy nonmessaging behavior, temporary Inbox compatibility, existing retry budgets, and the original child pool/spawn aggregate. Never delete/disable/weaken tests to manufacture green.
7. **Fail closed.** A failed join/close/history write/settlement check blocks every automatic retry/reconnect/compaction/LLM recovery branch and further provider requests. Accepted receipt != applied != provider success != tool rollback.
8. **No new SQL schema.** `messaging.v1.sqlite3` remains `PRAGMA user_version=1`; A.2 metadata is additive JSON history/stream metadata.

## 3. A1–A14 acceptance rows

Aliases A1–A7 retain `96.a.2-AC01`–`AC07`. Each row states a concrete observable outcome and the forbidden effect. Scenario paths are proposed by spec §9.1; implementation must create them before they can be evidence.

| ID / AC | Required observable outcome | Forbidden effect / principal risk | Milestone | Depends on | Proposed evidence |
|---|---|---|---|---|---|
| **A1 / AC01** | With the first/next provider token held, an urgent submission through the real local client/session joins and closes the provider reader before the next request; exactly one urgent instruction is applied at the next boundary. | No next provider call while a reader/cleanup is unjoined; no completed partial answer treated as truth; no second `anext`/`aclose` | T2 | T1; watchdog race; session control binding | Journey `tests/integration/test_messaging_yield.py::test_silent_provider_urgent_delivery` |
| **A2 / AC02** | A real tmp-owned blocking/write-like/unregistered-plugin/offloaded tool running when urgency arrives emits one defer notice, keeps the actual effect/result, and safely denies later unstarted calls. | No inferred rollback, no fabricated success, no cancellation of a thread being treated as proof it stopped, no defer notice storm | T3 | T1/T2; executor guards/policy | Journey + executor integration `tests/agents/slo_agent/tool_execution/test_yield_policy.py::test_default_defer` |
| **A3 / AC03** | Whole-group, sequential-remainder, and concurrent-start races produce exact source-ordered paired call/result messages; every started task joins; concurrent gather results are never lost. | No abandoned start, missing result, reordered pair, eager concurrent cancellation, or success fabrication | T3 | T1/T2; tool node/executors | Journey `tests/agents/slo_agent/messaging/test_yield.py::test_group_settlement` |
| **A4 / AC04** | Controlled cancel port matrix: valid ack, wrong ID, success-status ack, unfinished task, exception, five-second threshold expiry, late ack, naked cancel. One callback per invocation; both handles joined; a real normal result wins when simultaneous. | No second callback, no unjoined port/invocation, no invalid ack as terminal truth, no retry/next provider after unsettled group | T3 | T1/T2; policy/port; exact task identity | `test_yield_policy.py::test_cancellation_ack_matrix`; `test_yield.py::test_cancel_join_failure` |
| **A5 / AC05** | Existing spawn/children/permits/aggregate remain intact under A.1+A.2; held child work defers. No A.3 import/type/registration/duplicate dispatch. | No pending-dispatch protocol, early permit release, child cancellation, or replacement pool/spawn tool | T3 | T1/T2; unchanged orchestrator | Journey `tests/integration/test_messaging_yield.py::test_without_pending_dispatch_slice` |
| **A6 / AC06** | Pilot proves Enter normal, Ctrl+Enter urgent, Alt+U urgent fallback, command-palette urgent, Shift/Meta+Enter newline, Tab completion unchanged, slash local precedence, blank no-op; one submit; visible interruption/defer paint. | No dual submit, no stale draft clear, no remote urgent slash text, no geometry/theme change beyond requested hint/notice | T4 | T2/T3; component/action/palette/widgets | `tests/tui/test_app.py::test_local_urgent_action_and_interrupted_paint` |
| **A7 / AC07** | Older urgent backlog cannot interrupt its own boundary; only newer high-water can. Cached empty/note/instruction/both slots and retry/rebuild reuse the same cursor; one safe boundary advance; notes alone do not revive reasoning. | No busy loop/seal spin, extra claim, reset high-water, batch-drain, or second boundary advance | T2 | T1; session/control/source | Journey `tests/agents/slo_agent/messaging/test_yield.py::test_cached_slots_and_retry_cursor` |
| **A8** | Real opening/result/no-start writes through both flat and tree adapters: append-once exact event, fsync before continuation, crash-before/after-fsync and unknown-reply behavior fail closed; raw marked groups validate before selection/healing; no-start excludes exactly its group/anchors. | No fake `ToolMessage`, inferred no-start from absence, duplicate/conflicting raw event, startup readiness over unresolved group, or tree cursor advance without persisted evidence | T1 | A.1 store/application evidence; existing append-once mechanics | `tests/integration/test_messaging_yield.py::test_durable_no_start_disposition`, `::test_raw_group_recovery_without_a3` |
| **A9** | Two interruptions in one run plus later success, reopen/export: partial answer/thinking visibly interrupted exactly once per exact `(attempt_turn_id, iteration)`, next iteration distinct, silent interruption still shows notice, exports retain markers. | No private continuation anchor/model-context leakage, no false abort/failed run, no merge with next iteration, no late text/thinking end sealing the wrong block | T1/T2 | T1; accumulator, transcript, projector, stream | `tests/agents/slo_agent/history/test_transcript.py::test_multiple_interrupted_iterations_replay` |
| **A10** | Deterministic precedence: abort > completed reader > deadline > urgency; completed reader beats simultaneous yield; tools/phase exit disables provider deadline inside the pending read; reserve -> cancel once -> join; suppressed cancellation retained; repeated caller cancellation cannot abandon joins; close once. | No concurrent `anext`/`aclose`, next reader before join, timeout misclassified as yield, cleanup abandonment, or ownership release without join | T2 | T1/T2; watchdog/settlement | `tests/agents/slo_agent/test_watchdog_timer.py::test_read_yield_timeout_abort_precedence`; `test_yield.py::test_cancel_suppression_cannot_start_tools` |
| **A11** | Injected/prebuilt/lazy/factory/rebuilt agents, direct and pool provider paths, low existing retry budgets, abort/hook/owner/client close: same source/control/cursor per run; no duplicate LLM build/pool/spawn; failed cleanup bypasses every retry; pause retains input; close joins correctly. | No control reset/reuse, duplicate model build or child pool, extra provider call/claim after settlement failure, or lock/ownership release before joins | T2/T3/T4 | T1; session lifecycle/graph bind/release | `tests/agents/slo_agent/messaging/test_yield.py::test_post_yield_settlement_transition` |
| **A12** | Capability identity is the exact original tool object and exact invocation task; same-name wrapper/clone/duplicate registration/illegal transition rejected with fixed `ToolYieldCapabilityError`; live guard never heals; result status retained; marked compaction group-atomic. | No name/hash/equality lookup, no capability inherited by replacement, no healing as proof, no unresolved group sliced/removed, no plugin-overridable result status | T1/T3 | T1/T3; policy/DAOs/reconciler/projector/compaction | `test_yield_policy.py::test_capability_matches_object_not_name`; `tests/agents/slo_agent/history/test_message_contract_reconciler.py::test_live_group_refuses_healing`; `tests/integration/test_messaging_yield.py::test_marked_group_compaction_is_atomic` |
| **A13** | Urgent admission rejection/unknown outcome and newer edits/binding retirement/retry preserve the original urgent ID/bytes; no normal downgrade/overwrite; unsupported legacy host keeps the draft and refuses urgent text. | No fresh-ID guess, no normal fallback, no silent draft clear, no changed priority under same ID | T4 | T4; component/adapter/client | `tests/tui/test_composer_prerequisites.py::test_urgent_unknown_outcome_preserves_snapshot` |
| **A14** | Real tmp-contained offloaded leaf held while provider/tool/admission work runs: keyboard editing and an actually painted update occur before release; two themes x 60x20, 80x24, 120x40; focus/recall/queue band preserved. | No extra process/panel/receipt UI, no blocking leaf on the UI loop, no cancellation-as-stop proof, no default geometry change | T4 | T3/T4 | `tests/integration/test_messaging_yield.py::test_blocking_leaf_keeps_editor_responsive`; `tests/tui/test_app.py::test_urgent_visual_matrix` |

### Parameterized obligations that must appear inside the owning rows

- Strict live guard: orphan, empty ID, reused ID, duplicate ID, `invalid_tool_calls`, interleaving, missing result.
- Historical repair placeholders use `status='error'`; never evidence of live settlement.
- Normal framework `None` item is a valid item, distinct from exhaustion (`GraphReadOutcomeDAO` presence flag).
- Exact reader task identity; tools transition before awaited plugin/effects; post-result plugin join.
- Tool result status cannot be upgraded to success by after-tool patches.
- History-disabled transient parity without durable claims.
- Usage counts are observed only, never estimated.
- Redacted diagnostics: no bodies, credentials, arbitrary exception text, or provider-private anchors.
- New urgent during retry; before-agent plugin invalid pairing blocked.
- Both flat and tree adapters for cooperative append-once and raw validation.

## 4. Requirement-linked journeys

| Journey | Real start | Terminal observable | Rows |
|---|---|---|---|
| J1 Ordinary input | `PromptInputComponent` stable draft -> adapter -> local client | Durable accepted receipt; applied once at next natural boundary; no active cancellation | A1/A13 (negative), regression of A.1 |
| J2 Silent-provider urgent | Local client with urgent -> real session/scheduler -> controlled provider stream held | Reader joined/closed; one urgent instruction applied before next provider call; interruption audit + visible notice | A1/A7/A8/A9/A10/A11 |
| J3 Tool urgency | Same session -> real graph/tool node -> real executor + injected port/timing | Defer once or validated cancel ack; every started task joined; exact paired results; no rollback claim | A2/A3/A4/A5/A11/A12 |
| J4 Restart/replay/export | Reopen real session over flat and tree history | Raw marked groups validated before context selection/compaction; interrupted entries survive replay/export; unresolved blocks readiness | A8/A9/A12 |
| J5 Local TUI activation | Pilot-mounted `SloTUI` with real composer/session | Correct priority/key/slash behavior; visible interrupted/deferred paint; editor remains responsive under held offload | A6/A13/A14 |

## 5. Risk map

| Risk | Required proof | Rows |
|---|---|---|
| Lost/duplicated tool result or fabricated success | Exact call/result pairing, source order, joined tasks, no-start marker only after joined reader | A2/A3/A4/A8/A12 |
| Provider reader not actually cancelled/joined | Exact owned reader identity, join before close, suppressed-cancel item retained, close error fails closed | A1/A10 |
| History crash/unknown reply mistaken for success | Raw append-once ID/digest equality, fsync barrier, retry exact event, unresolved blocks startup | A8/A9/A12 |
| Interrupted context leaks private provider anchors | Context restore/exclusion, transcript sealing, export checks | A9 |
| Retry/reconnect/LLM recovery masks settlement failure | `UnsettledToolGroupError`/`CooperativeYieldSettlementError` classified before generic planners; low-budget exhaustion proof | A4/A10/A11 |
| Urgency interrupts its own backlog or spins on seal | High-water snapshot, predicate recheck, no signal-claim without predicate | A7/A10 |
| Partial TUI activation/dual submit | Keys/fallback/palette/host capability widened together; old Ctrl+Enter branch removed, not duplicated | A6/A13 |
| Blocking leaf freezes UI | Real held offload + painted update before release; no thread-cancel-as-stop | A14 |
| A.3/C.1 scope creep | No pending-dispatch import/type/registration; no IPC/attached composer; original pool intact | A5/A11 |
| Test-harness overreach | Focused pytest only; no custom runner/DSL/multi-service harness; full gate remains required | All |

## 6. Baseline, commands, and gate status

**Environment (verified read-only):** Python 3.11.7; pytest 9.0.3; xdist 3.8.0; PyYAML 6.0.3; mypy 1.20.2; Black 26.5.1. `/root/.pyenv/versions/slo-harness/bin/python` resolves to `/root/.pyenv/versions/3.11.7/bin/python3.11`, the same interpreter Poetry uses. No project `.venv`; Poetry skips virtualenv creation. `environments/tests.env` is absent; the Makefile fallback is the only test environment contract.

**Baseline:** UNEXECUTED. No passed/failed/skipped counts, warnings, or existing failures are known for this task. No baseline exception or waiver is approved. Previous durable-composer counts are not inherited.

**Required gates:**

| Gate | Status | Exact command / disposition |
|---|---|---|
| Focused new A.2 journey + decision tests | UNVERIFIED | `PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' <new/affected audited paths>` |
| Existing affected regressions | UNVERIFIED | `... tests/agents/slo_agent/messaging tests/agents/slo_agent/tool_execution tests/agents/slo_agent/history tests/tui/test_prompt_component_protocol.py tests/tui/test_slash_command_registry.py tests/tui/test_durable_composer.py` (audit executable fixtures first) |
| Full non-E2E | **BLOCKED / UNVERIFIED** | `make test PYTEST_WORKERS=6` (default `pytest -n 6 -m 'not e2e'`) |
| Full serial reproduction | **BLOCKED / UNVERIFIED** | `make test-serial` (same complete suite; not a substitute gate) |
| Static | UNVERIFIED | `make lint` (`poetry run mypy src/ tests/`) |
| Format | UNVERIFIED | `poetry run black --check` on changed paths plus project requirements; baseline scoped to pre-existing dirty work |
| End-to-end | NOT REQUIRED YET / UNVERIFIED | A.2 has no mandatory e2e |

**No smaller total substitutes for the full suite.** The full gate stays BLOCKED until the operator resolves the executable-fixture consent described in `safety-audit.md`. Excluding tests, changing their markers, or running a selected subset is not an accepted gate.

## 7. Decisions

| ID | Decision | Rationale / consequence |
|---|---|---|
| D1 | Milestone M1 = T1 + T2 only; host remains normal-only until T4. | Produces a runnable silent-provider journey with fail-closed history while avoiding a partially urgent composer. Tools/TUI cannot activate early. |
| D2 | No initial `cancel_confirmed` built-in. All built-ins/plugins/thread-backed/spawn defer. | The safe default is defer; A.2 must not claim rollback. The port/policy seam exists but is exercised only by an injected trusted test port. |
| D3 | `ToolExecutionMode`/read-only classification never implies cancellation safety. | A read-only batch still defers unless an explicit trusted registration exists. |
| D4 | No new SQL, history kind, dependency, config flag, IPC target, process, or supervisor. | A.2 uses additive JSON metadata and existing owners. Unknown/corrupt metadata blocks readiness. |
| D5 | History-disabled mode gets transient parity only. | No durable interruption/recovery claim; a durable-store failure may not silently select this mode. |
| D6 | Activation is atomic at T4. | Component priority, host capability, Ctrl+Enter/Alt+U/palette, and interrupted/defer paint land together; the old Ctrl+Enter newline branch is removed, never dual-submitted. |
| D7 | A.3/C.1 remain read-only context. | No pending-dispatch import/registration, attached composer, IPC, or duplicate TUI modules. |
| D8 | Full gate remains the complete `make test PYTEST_WORKERS=6`. | Focused/affected evidence is progress, not completion. No skip/xfail/baseline waiver. |
| D9 | Reviews are independent and read-only at the early gate. | Early reviewer runs no tests; final review/completion are separate `gpt-6.1-sol` high-reasoning assignments. |
| D10 | Preserve unrelated dirty work and installer scripts. | No edits to `SLO.md`, `docs/`, durable-composer reports, `deploy-install-worker.sh`, system/installed executables, or packages/environments. |

## 8. Definition of done for the bounded M1 assignment

M1 is READY only when all of the following have current evidence and no unapproved gap:

1. T1 carriers, strict live guard, raw marked-group validation, and cooperative append-once exist in both real stores; normal A.1 journey still works.
2. A1/A7/A8/A9/A10/A11 scenarios for the silent-provider path pass through the real local client/session/SQLite/history, with interruption audit and visible notice.
3. No tools-phase capability is claimed yet; all tools in M1 remain on the existing path.
4. Focused tests and affected regressions pass; static checks are reported with baseline separation.
5. Early independent read-only review returns no blocking finding; review is not completion.
6. The full suite is reported BLOCKED, not passed, and no substitute total is claimed.
