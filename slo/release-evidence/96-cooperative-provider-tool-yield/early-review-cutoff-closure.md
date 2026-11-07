# A.2 bounded independent early re-review — cutoff closure

## Verdict

**REVISE — one finite B2 assertion repair remains.** B1's null-container defect and B2's masked malformed-call decisions are repaired in current source. The real journey now joins close and reads durable SQLite/history evidence, including exact durable terminal counts and the application/receipt/boundary linkage. However, its observer assertions still accept duplicate failure terminals and synthetic success/abort, and its durable opening/terminal records are counted without checking that they identify the same attempt. Close those small assertion gaps at the existing test owner; no product rewrite or completion of all A.2 is requested.

**Source code acceptance:** the bounded live guard, provider cutoff and terminal exclusions are accepted by inspection; no new product-code defect found in this scope. **Execution acceptance:** unverified. B3 is now accurately acknowledged, not fabricated, but a reproducible current execution receipt is still missing. Even after the small assertion repair, the most this checkpoint can establish without that receipt is **code-only advisory READY**, not a passing execution gate.

This is early integration feedback inside Step 1. The main urgent silent-provider journey, new race/control/policy, cooperative history implementation and TUI activation remain **unimplemented**. Full final review and independent completion are **not due yet**, not performed here, and not claimed skipped or satisfied. No workflow turn is completed by this report.

## Scope and provenance

- Repository `/root/Code/slo-message-queue/slo`, branch `message-queue`; read-only git queries confirm HEAD/baseline `82c3f5c6de9345af34a673a3d975366ca8c1624c`.
- Read `current-handoff.md`, `cutoff-proof-closure.md`, `early-review-cutoff-repair.md`, `routing.md`; inspected current tracked product diffs, current reconciler/tests and the **complete untracked** `tests/agents/slo_agent/messaging/test_provider_settlement_guard.py` (646 lines). Read relevant original specification §§4.3, 6.1–6.3, 8.2, and traced actual session/provider/history owners rather than accepting the ledger's verdict.
- Authority is `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md`, not a revised sibling. README architecture/maintainer rules and KB `Welcome.md`, `slo/README.md`, `slo/gotchas.md`, `slo/operational-reference.md` consulted. Root `RESEARCH.md` is absent; the report-only authorization does not permit creating it.
- Both actual environment aliases resolve to `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`. Used that installed root for engineering routing/ownership/review/testing, generic coding/naming/declarative/test-verification guidance, Python root/signature/docstring/declarative review rules and scoped graph/gateway/application guidance. Read the **actual installed** `orchestration/workflows/code-test-review.md` Early integration feedback (§ at lines 181–196) and workflow counting guidance. Its bounded read-only checklist governs this assignment, not the Step 2 final-review procedure. Project one-shot graph/session contracts specialize generic framework examples; no new synthesis node, ORM or service framework is required.
- **Reviewer executed no tests, static checks, collection, application/import probes or mutation experiments.** Read-only shell operations inspected text, environment aliases, git state/diffs and existing log excerpts only. No nested agents, model switching, packages, executable/bin changes, infrastructure actions or git writes. Only this new Markdown report is authored. Existing `SLO.md`, `docs/`, preflight and prior reports remain untouched. No fixture consent was exercised or broadened.
- Accounting carried from the request: turn 3, this dispatch **4/20**; turn 1 partial 7 calls, turn 2 partial 4 calls, 0 complete; 60-turn maximum; four execution retries (audit 1/provider 1/repair 2), never retry an abort. Primary author model remains exact assigned DeepSeek/default, fallback only for concrete quota exhaustion; reviewer assignment is exact `gpt-6.1-sol` high. This report does not independently attest transport/model selection.

## Finite requirement-to-source assessment

| Item | Current evidence read | Disposition |
|---|---|---|
| B1 / §6.1 null canonical calls | `history/message_contract_reconciler.py:157–163` now rejects every non-list, including `None`. `test_message_contract_reconciler.py:378–403` covers null, zero, empty string/tuple/mapping, noniterable and accepted omitted/default/explicit empty-list forms. | **Source closed.** Canonical list semantics retained, not falsey normalization. |
| B2 duplicate opening decision | `test_message_contract_reconciler.py:314–322` supplies duplicate A declarations **and one A result**. `_settle_pending_result` removes all matching A values, so removing duplicate-opening rejection would now let the test pass through the guard and fail its expected exception. | **Source closed; sensitive.** No downstream missing-result mask. |
| B2 parser-invalid decision | `test_message_contract_reconciler.py:406–416` supplies invalid calls alongside otherwise settled A/result A. | **Source closed; sensitive.** Removing the invalid-call rejection no longer leaves a separate open A failure. |
| B2 malformed entry decisions | Direct pure-validator cases at `test_message_contract_reconciler.py:283–311`: blank/whitespace/nonstring ID, blank/nonstring/missing name, nonmapping entry. Public guard reaches that owner at reconciler `:164–166`. Missing/nonmapping args tests `:350–375` supply matching A results. | **Source closed.** Pure decision tests avoid the blank-result guard masking the opening check. |
| Existing nonmutation/compatibility | Detached snapshots `test_message_contract_reconciler.py:174–200`; success/error statuses preserved; matching out-of-source-order results remain accepted `:246–259`. | **Retained.** No new result-name/schema restriction. |
| B2 POST-CLOSE durability | Journey `test_provider_settlement_guard.py:562–646` joins `close_messaging()` at `:571`, then reads the closed SQLite row via read-only URI helper `:357–385`, loads history and reopens the real `MessageStore`. | **Substantial repair accepted**, with remaining exact terminal assertions below. |
| ER-01 / §6.5 three terminal exclusions | `agent.py:973–977` before transport/rate classification; `:1208–1213` before injected LLM recovery; `sessions/service.py:6363–6367` before reconnect/continuation/compaction planners. Shared predicate remains reconciler `:30–45`. | **Previously accepted, unchanged and retained.** No new ER-01 demand. |
| Direct/pool provider cutoff | Graph `service.py:199–213` guards before either provider branch. Untracked test uses real `ModelPool`, two counting external members, negative zero/zero and valid tool-free positive one/zero. | **Source accepted**, not pooled urgent-yield or fallback certification. |
| B3 latest receipts | Current handoff and closure ledger explicitly admit missing invocation/exit headers; inspected latest green/red/mutation/mypy log excerpts agree. | **Reporting correction accepted; reproducible execution gate remains open.** |

### What the post-close journey now actually proves in its assertions

`test_provider_settlement_guard.py:582–644` correlates:

1. Exactly one SQLite message row, applied and not retained, at **boundary 0**.
2. Exactly one history `run_started`, exactly one `run_failed`, zero `run_completed`/`run_aborted`; no recovery/retry/reconnect/compaction kinds listed there.
3. Exactly one `messaging_v1` application; its message ID and sequence 1 match the stored delivery; application metadata/run turn match the stored logical run ID.
4. Exactly one applied identity receipt with that message/run ID; `identity.history_event_id == application.event_id`; retained application journal event has that same event ID, logical run and metadata.
5. Zero provider entries and exactly one plugin iteration (`["0"]`).

These are real local client → session → SQLite/filesystem boundaries. Public `session.invoke` selects the observer/client path at `sessions/service.py:5308–5313`; the canonical application owner writes `workflow_update` using the delivery logical run at `:1200–1234`. Reads now occur **after joined close**, not before it. This closes the earlier timing and applied-receipt-only weakness. It does **not** by itself prove there was no empty cached boundary claim, and this review makes no such claim.

## Remaining B2 — small test-only exact-terminal repair

**Medium verification gap; not a newly found product defect.** Existing `test_real_messaging_session_settlement_failure_is_terminal` is the owner. The preceding review explicitly requested exact stream terminals and rejection of success/abort; current `:573–578` still checks only membership of `run_failed` and absence of some recovery events. A stream containing two `run_failed` events, or a failure plus `run_completed`/`run_aborted`, satisfies those assertions. Exact durable counts do not prove exact observer publication.

Also, `:595–598` counts durable opening/terminal kinds but never compares their attempt `turn_id`s. A single opening for attempt X plus a failure wrongly stamped Y would pass. **Do not fix this by equating an attempt UUID with the logical message run UUID.** Current session deliberately allocates a fresh attempt UUID (`sessions/service.py:5623,5730–5737`); application history uses the delivery logical run (`:1221`). New cooperative attempt/run metadata is T1/T2 work, not required for this cutoff repair.

**Finite closure:** in this same journey, after the existing joined close:

- Assert the observed terminal-kind subsequence is exactly `["run_failed"]` (or equivalent exact counts plus zero success/abort); explicitly reject reconnect/compaction stream kinds if claiming their absence at the observer boundary.
- Select the sole durable opening and failure already counted; require a non-null, equal attempt `turn_id`, correct `session_id`, and opening-before-terminal history sequence. Preserve the existing logical-run/application/boundary assertions separately. No new production metadata or full urgent correlation protocol is needed.
- Supply authorized author execution evidence for the changed journey/current focused repair. Reviewer runs none. Missing receipt is not permission to rewrite code or weaken assertions.

No other cutoff code repair is requested. Source acceptance of B1 and malformed-decision repairs should not be reopened merely because B3 lacks execution provenance.

## B3 evidence disposition — honest but not verified

Existing logs visibly report 79 focused passes, 194 affected passes and one durable-journey pass. The null RED log reports 1 failed/42 passed. Targeted removed-check logs name the relevant duplicate/invalid-call/ID/name/nonmapping failures. These support the author's sensitivity account as retained output, **not** independently reproduced executions, exact invocations, exit statuses or independently verified test-first chronology. Do not sum overlapping totals or label mutation exercises pre-implementation RED.

**Remaining reproducible-receipt blocker:** a future authorized author must record actual command/node selection, cwd/environment, source identity, actual exit status and passed/failed/skipped totals with captured output for the current repair. No retrospective command/exit reconstruction. A current rerun cannot manufacture missing historical test-first chronology; retain that limit explicitly.

- `make test PYTEST_WORKERS=6`: **BLOCKED / UNVERIFIED**, other executable fixtures lack consent. No subset/serial substitute or waiver.
- Full static gate: **UNRUN / UNVERIFIED**, not inherently blocked by fixture consent and not run by this reviewer.
- Three-source mypy log: observed `yaml` missing-stub failure; **baseline not independently established**. No install or baseline waiver authorized.
- Only existing deploy-worker `tmp_path/bin/curl` stub chmod0755, child-only PATH and verified temp root has narrow consent. It authorizes no other executable mutation, directly or indirectly.

## Next minimal T1 closure target — metadata + restricted append-once only

After this finite cutoff assertion/receipt repair, take a bounded **T1 sub-slice**, not all of T1 or A.2. Source: original §§4.3, 6.2, 8.2. Existing owners already provide the mechanics:

- `history/store_protocol.py:112–121` defines application append-once/raw evidence.
- `history/filesystem_store.py:417–455,573–602` owns locked shielded/joined workers, raw-ID/digest matching, high-water repair and redaction verification.
- `history/tree_store.py:289–312` delegates canonical bytes to flat storage without tree enrichment and only advances a newer cursor.
- `history/dao.py::SessionHistoryEventDAO.application_sha256` owns the canonical digest. Existing `messaging/test_history_application.py` exercises both adapters, metadata repair, conflicts, raw-tail recovery and joined cancellation; extend/reuse those conventions, not a new harness.

**One concrete deliverable:** add the spec's typed `ToolGroupMetadataDAO` in `tool_execution/dao.py` and strict/frozen/forbid `CooperativeYieldMetadataDAO` in `history/dao.py`; add the restricted `append_cooperative_event_once(*, event) -> SessionHistoryEventDAO` to the existing protocol and both adapters. Keep normal message applications on `append_message_application_once`, with their existing validation unchanged. Extract shared private raw append-once mechanics in the flat owner rather than calling the application-only public validator or copying its writer.

**Closure conditions for this sub-slice:**

1. Validate version, UUID5 identities, attempt/group/iteration and ordered distinct call IDs, UTC opening time, result-only status and allowed diagnostic/no-start combinations from §4.3. Only validated marked tool calls/results and cooperative/no-start `run_retrying` records enter this API; arbitrary records and untrusted metadata do not become proof.
2. Equal deterministic ID plus equal canonical digest returns the persisted event without another raw line. Conflicting/duplicate IDs, invalid evidence, redaction changes and uncertain persistence fail closed with fixed `CooperativeYieldSettlementError`; extend the existing terminal-family predicate when that producer lands, preserving all three exclusions. Never allocate a new timestamp/ID on uncertain retry or add an automatic live retry budget.
3. Both real adapters prove exact persisted readback, identical retry, conflict rejection, high-water repair after a durable line/stale metadata, and cancellation joined before releasing serialization. Tree retry must not regress its cursor or enrich canonical bytes. Use real temp-root files and existing pytest/DI seams; no framework, packages, executable stubs, schema migration or broad monkeypatch platform.
4. Author works test-first in small increments, records actual RED/GREEN and affected normal application regressions within authorized safety boundaries, with typed named inputs, declarative ownership and no-regression review.

This sub-slice must **not activate new record producers/consumers** before the remaining T1 raw-group validation/startup/context/compaction/status-replay barriers (§§6.1, 6.3) are implemented and proven. Session trusted stamping/opening-before-result publication and T2 urgent interruption correlation remain subsequent work. No claim of complete T1, A3/A8/A9/A12, main silent-provider milestone, composer activation, final review or completion follows from this bounded target.
