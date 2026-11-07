# Durable composer — independent EARLY integration feedback

**Checkpoint verdict: REVISE — one bounded runnable-evidence blocker (EF-01).**
This is advisory feedback **inside Step 1**, not final code review, feature acceptance, or a completed workflow turn. Do not implement DC03–DC09 merely to close this checkpoint. The architecture is suitable for extension; the immediate correction is to demonstrate the first mounted journey's claimed terminal behavior, not finish the feature.

## Scope and authority

Inspected branch `message-queue`, HEAD `5dd059cbf00134d5c5eef706875310a2eb677cdd`, tracked diff and all five untracked implementation/test files (including adapter `__init__.py`). Original requirements: ONLY `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/revised/01-durable-composer/`, numbered 01–09 plus task-list, routing, author/breakdown and resolved review reports. Historical author verdicts are not executable evidence. Read `acceptance-routing.md` and `implementation-handoff.md` fully; reused their skill/environment routing.

Read repository/global SLO instructions, README runtime/ownership/style/testing sections, installed Code-Test-Review **early-feedback** checklist, shared routing/ownership/testing, solution-design, coding-rules, naming/design/declarative guidance, verification policy and scoped Python/Textual rules. Vocabulary: session, source, client, admission, draft revision, binding version, receipt, accepted/applying/applied, retained input and application identity. Existing in-process SQLite/history owners remain authoritative; no new ORM/HTTP layer is needed. Consulted KB Welcome → slo README/gotchas and in-process TUI guidance; historical source locations are not current truth.

No tests, collection, lint, formatting or application imports executed. No agents spawned; no process, package, host, environment or Git mutation. Only this report written. Pre-existing `docs/` content was not opened or modified; absent research/instruction files were not recreated.

## Runnable architecture assessment

Verified path:

`SloTUI(messaging_enabled=True)` mount/reporting/preparation → `_activate_session_messaging` → session startup and injected-source binding → `LocalSessionMessagingClient` → component-owned `MessageSubmissionAdapter` → Enter's stamped revision → synchronous capture/reserve/register/clear → session scheduler → existing SQLite/application journal/history → real agent with `RecordingModel` at the vendor boundary.

Good foundations:

- `agent.py:283–301` preserves the injected object, checks idle/same-source/foreign-source, and changes only its source. `sessions/service.py:883–932` binds under execution ownership and retains existing startup unwind and sole scheduler. No second context writer was introduced.
- Ordinary messaging Enter bypasses the legacy clear/run/latest-wins branch (`app.py:1992–2028`); `component.py:779–879` captures revision, reserves before registration, and clears only after the local handoff. The intervening awaited adapter body has no suspension before task registration; early outcomes are stashed until commit.
- Startup failures use fixed notices and preserve text without memory fallback. Default composition remains legacy; production cutover has not been prematurely enabled.
- Typed immutable submission records and narrow register/handle/reset/close interface match the specified seam. Session owns durable execution, app owns client, component owns draft state, adapter borrows dependencies.

## Checkpoint blocker — finite closure list

### EF-01 — first mounted journey does not establish its exact-once provider/terminal claim

**Source:** DC01.A1/A4; DC02 §1, §8 A1; workflow Step 1 “Runnable” and verification-policy observable-outcome obligations. **Priority:** checkpoint evidence blocker, not an instruction to complete the full three-message A1 matrix now.

**Evidence:** `tests/tui/test_durable_composer.py:233–280` mounts the real app and checks two SQLite rows and the first history text. It never inspects `model.requests`, never requires exactly one history application for the first ID, and never asserts successful terminal history/answer. The final conditional allows extra applications when their count is not exactly two. Editing `x\ny` happens **after** releasing the provider at lines 253–257. The second Enter occurs before waiting for `model.entered`, so the test also does not establish that this admission occurs during an actual held provider request. `test_injected_activation.py:85–94` asserts one request and one history application for a different, non-mounted journey, but not that the request contains the exact instruction. These are useful real-persistence tests, not sufficient proof of all claims in the handoff.

**Impact:** a mounted wiring regression that applies history but loses/duplicates/changes the provider instruction, or fails the model run, can escape the claimed first-slice evidence. A passing test name/count cannot establish exact-once model delivery or successful completion.

**Closure:** extend the smallest mounted journey (one successfully applied prompt is sufficient for this checkpoint). Assert the exact normalized captured text and message ID correspond to one application/history event, occur once in the relevant recorded provider input, and produce the scripted successful terminal outcome. Wait for provider entry, type/pause with a bounded wait while its release remains unset, then release and settle. If retaining the busy second Enter, put it after that gate and explicitly classify it as retained rather than applied under the intentional stop hook. Preserve that valid retained-input scenario; do not weaken it into alleged DC02.A1 full coverage. Implementer runs the affected focused command and records its concrete result; reviewer ran nothing. Keep full three-busy-input ordering/application proof on the DC02 completion plan.

## Requirement → evidence / remaining-plan map

Legend: **W/T** = implemented, real entry wired, test assertions inspected (execution receipts below, not rerun); **partial** = some behavior/assertions only; **later** = missing/unwired/untested work explicitly pending. All source A-rows are retained below. Rows are not accepted merely because source code exists.

| Requirement | Current classification and evidence | Finite remaining closure |
|---|---|---|
| **DC01 A1–A3** | W/T injected activation, same-source idempotence and refusal; `test_injected_activation.py`. Real applied receipt, history, provider count, SQLite reopen and lease reacquisition. A2 simulates busy by assigning `_running=True` and mutates the second session ID; not the specified gated-running journey. | Add exact provider-content assertion (EF-01 counterpart); use constructor session ID and a genuine gated provider or foreign-source binding for refusal, rather than private state fabrication. |
| **DC01 A4–A5** | W/T mount creates store/client; held lease produces fixed refusal, preserves text, leaves history empty. Startup order is source-inspected, not asserted by test A4. No direct no-provider-call assertion in A5. | At completion add ordered preparation/reporting/readiness evidence, cancelled/displaced startup cleanup and explicit forbidden provider execution. |
| **DC01 A6–A7** | Partial: non-durable notice once; exit readback retains accepted input. Test A6 does not submit/check `durable=False`; A7 does not record client-before-session order or reacquire lease. | Add those assertions. Outstanding adapter retirement belongs to DC04, not a prerequisite to this checkpoint. |
| **DC01 A8** | W/T default legacy path retained; unchanged prompt-protocol regression included in recorded focused runs. | Keep regression green as later wiring changes. |
| **DC02 A1** | Partial mounted exact-first-history/application plus distinct busy admissions; **EF-01**. Stop hook intentionally pauses pending input; not full three-applied-input proof. | Close minimal EF-01 now; full distinct-ID/order/once-per-boundary three-input journey before DC02 is declared complete. |
| **DC02 A2–A4** | Implemented/wired rejection restore-or-keep, fixed feedback, one uncertain lookup and same-ID retry; **untested**. `component.py:901–1033`, adapter flows, `/messages` app/router intents. | Planned real sender-limit/held-admission, newer-draft and uncertain retry journeys; exact same-ID/no-extra-provider evidence. |
| **DC02 A5–A8** | Implemented/wired local 4-wait/16-draft/1 MiB gates, canonical size validation, early-outcome stash, edit/undo/redo/document revision boundaries; **untested**. | Planned capacity/discard, eager ordering, every edit-boundary tests; add host-held usage only with DC04. |
| **DC02 A9–A10** | Adapter lifecycle/protocol code exists; reset/close not yet wired from component lifetime, no new static snippet proof. Concrete join defects below. | Fix EF-02 during DC02 hardening; prove lifecycle and positive/negative registration typing. |
| **DC02 A11–A12** | Empty/slash routing, literal document and sealed-capture refusal present; Ctrl+Enter newline preserved in `_on_key`. New messaging tests absent. | Empty/whitespace/literal and sealed-binding journeys, including no admission and unchanged newer text. |
| **DC03 A1–A11** | **Later:** no owner observation/publication, subscribe-before-replay, application ID/hash transcript classification/dedup, recall-ID fallback, band, overflow recovery, corruption/conflict handling, compaction-aware echo or messaging run presentation. Existing generic render subscription is not this implementation. | Extend named session/history/transcript/component owners per 03 §§5–8; flat/tree live/replay, reset/clear, machine, overflow/authority and terminal-presentation tests. No new projector service. |
| **DC04 A1–A8** | **Later:** component reset/close remains suggestion-only; binding replacement raises when already bound. No joined retirement/handoff/host budgets/exit warning/stale-successor protection. | Implement 04 §§5–8 before exercising session replacement or cutting over; join before borrowed-client shutdown, acknowledgements before ownership transfer. |
| **DC05 A1–A9** | **Later:** retained paging/point read, registered exact consent, expiry/revalidation/replay-safe continue/cancel and slash confirmation absent. Existing store recovery primitives are not user wiring. | Real restart flat/tree and atomic replay/forgery/capacity/slash tests through session authority; no UI SQL. |
| **DC06 A1–A7** | **Later:** no messaging control branches for reusable abort/Ctrl+C, display-only clear or retire-close-adopt `/new`. Existing controls still key off legacy task ownership. | Complete 06 §§5–8; verify predecessor and successor stores/leases/drafts, running/full-handoff refusals. |
| **DC07 A1–A11** | **Later:** finite atomic cutoff/applying count, settlement wakeups, consumer exit/cancellation, actual hard stop, headless wiring and `/steer` admission absent. Legacy headless unchanged, but no new headless evidence inspected. | Real runner plus queue races/stop/concurrent close/cancellation/note retention and legacy regressions; wait outside execution/history/queue locks. Never invoke again just to wait. |
| **DC08 A1–A11** | **Later:** machine capabilities, original-target/digest verification, source rule, claimed paging/startup scan and receipt-only ack bridge absent. Legacy Inbox still has direct execution/history paths. | Complete 08 §§5–8 before cutover; preserve workflow advancement/policy; verify lost submit/ack, pruning/restart, malformed/forged/unknown claims and nonmessaging matrix. |
| **DC09 A1–A6** | **Later:** CLI flags, invariant/rollback guards, README update and theme×size/failure matrices absent; full gates unavailable/not passed. | Cut over only after DC01–08 completion and specified visual/liveness/failure journeys; full non-e2e/static gates or explicit operator disposition. |

## Advisory implementation risks (not extra checkpoint blockers)

**EF-02 — adapter joining does not currently satisfy its own lifecycle promise.** DC02 §5.8/A9, `adapters/message_submission.py:125–130,186–220`: starting another wait drops every already-done task without retrieving failures; an unexpected exception from `await shield(task)` escapes `_join_wait_tasks` immediately instead of joining siblings. Concurrent second `close()` returns at `_closed` while the first still waits; borrowed references are never actually released. This is a concrete defect in the pending DC02 lifecycle work, not a reason to demand DC04 now. **Closure:** retain/observe all owned results, join all siblings before rethrowing, give all close callers one completion barrier, release references last, and add deterministic failing-receiver plus held-sibling/repeated-cancellation tests. Do this before DC04 relies on the adapter contract.

**EF-03 — retirement remains genuinely absent.** `component.py:692–705` closes delivery before outstanding outcomes can settle; outcome handling then raises at 913–914. App close's docstring (`app.py:1098`) incorrectly says pruning joined prompt retirement. With held admission there is currently no adapter join. **Closure:** DC04 pre-pruning single retirement/handoff task and DC06 predecessor close; correct the premature comment and add the specified late-outcome tests. Do not use `/new` or claim full shutdown robustness from the current happy-path exit test.

**EF-04 — preserve ownership while extending.** `app.py:1108` inspects session-private `_messaging_start_task` to decide whether to close; `close_messaging` is already an idempotent session-owned lifecycle operation. Remove this cross-owner decision in favor of a public lifecycle operation/app-owned activation record. Also make client-close failure unable to skip session cleanup. Keep capture/reserve/register/clear suspension-free; decomposition must not insert awaits into that atomic section. The broad design is declarative; these corrections do not need another service layer.

**EF-05 — receipt recall needs the planned identity refinement.** `component.py:938–941` records `entry.raw_text` unconditionally, including non-restorable slash-originated drafts; `/steer` will have an already-cleared editor. DC03 must record submitted text/ID with one shared dedup rule and keep machine input out of recall. Complete this before DC07 wires slash submission.

## Execution evidence inspected — not executed here

Receipts were read from repository logs and `/root/.slo/sessions/history/95129c8e-3a7d-4a72-9c45-093a098c4051/events.jsonl`. Same cwd and synthetic environment as acceptance-routing; no real provider. Representative commands below omit only that documented environment prefix.

| Command / receipt | What is actually supported |
|---|---|
| Baseline `poetry run pytest tests/tui/test_prompt_component_protocol.py tests/integration/test_session_messaging.py tests/agents/slo_agent/messaging/ -m 'not e2e'` | `baseline-focused-pytest.log`: **435 passed**, 316 warnings. Pre-edit baseline only. |
| New two files, `timeout 120 poetry run pytest tests/tui/test_durable_composer.py tests/agents/slo_agent/messaging/test_injected_activation.py -m 'not e2e' -q` | Child events 4185–4187: **8 passed**, 4 warnings. RED log: 8 failed before implementation; initial failures largely missing API/wiring, not sensitivity proof for every assertion. |
| `timeout 300 poetry run pytest tests/tui/test_prompt_component_protocol.py tests/integration/test_session_messaging.py tests/agents/slo_agent/messaging/ tests/tui/test_adapter_registration.py tests/tui/test_slash_router.py -m 'not e2e' -q` | Events 4213–4216: **534 passed**, 317 warnings; concrete receipt, not merely handoff prose. |
| `timeout 300 poetry run pytest tests/agents/slo_agent/messaging/test_injected_activation.py tests/tui/test_durable_composer.py tests/tui/test_prompt_component_protocol.py tests/tui/test_slash_command_registry.py -m 'not e2e' -q` | Events 4654–4658 at 07:32:51Z: **39 passed**, 5 warnings, pinned HEAD printed. |
| Bounded TUI chunks | Inspected child command/result pairs for 128/197/422/67/255/470/221/52/52/26/515/129/73-pass summaries. One chunk reports **1 deselected**. These are useful surrounding receipts, not independently reconciled complete-suite coverage. Many commands pipe into `tail` without pipefail: shell exit 0 alone does not prove pytest exit; passing summaries are the evidence. |
| `make lint` | Baseline log: **8 missing-yaml-stub errors**, gate **BLOCKED**, not operator-excluded. Scoped mypy/Black successes are handoff claims, not re-executed here. |
| TUI aggregate / full gate | `tui-suite.log` records `-n 6` rejected (missing xdist); `tui-flat-suite.log` stops around 40% with no terminal summary. Serial timeouts/chunks do not establish `make test PYTEST_WORKERS=6` success. Full non-e2e gate remains unverified. No package/environment repair authorized. |

The child history confirms `run_completed` sequence 5229 at **07:33:11.703239Z** after the parent failure. This supports recovering its completed handoff, not retrying or treating its READY text as acceptance. No worker was signalled by this reviewer.

Read-only commands executed here: Git status/branch/HEAD/diff/stat/untracked inventory; source/spec/skill/KB/log reads via tools and bounded `cat`/`nl`/`sed`/`tail`; `python -B` using only stdlib JSON/path reads to inspect recorded child command/results; `git diff --check` **exit 0** (tracked diff only, not a test or formatter). No test or collection command was run by this reviewer.

## Handoff and counters

Return to the existing Step 1 implementer with **EF-01 only** as checkpoint repair; retain EF-02–EF-05 and every later A-row in the finite completion plan. Correct handoff claims for partially proved DC01 rows and DC02.A1. Final independent review and completion check are still required after all mandated implementation and gates.

Counters preserved from continuation authority: **turn 1; 1 started / 0 completed / 1 partial; this is dispatch 2/6**. Limits **8 started turns / 6 dispatches per turn**, at most 3 failed-task retries, none after abort. Reviewer spawned **0** agents and used **0** retries. The recovered original child does not require a retry. Early feedback does not complete a turn or authorize phase progression.
