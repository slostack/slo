# Independent final-review partition — DC05–DC07

## Verdict: REVISE — scoped audit complete; two confirmed blockers

This is an independent read-only review of original DC05.A1–A9, DC06.A1–A7 and DC07.A1–A11, including their surrounding lifecycle and persistence contracts. It is not implementation, aggregate feature acceptance or the separate completion check. **Do not advance this partition as READY until R567-01 and R567-02 close.** The A4/A8 DC07 complementary-evidence questions are dispositioned below, not left for another reviewer to rediscover.

Authority: `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/revised/01-durable-composer/`, specifically the complete original files `05-retained-input-recovery.md`, `06-session-controls-abort-clear-new.md`, `07-finite-headless-and-steer.md`. No sibling scope or new urgency/IPC requirement is imposed.

Counters carried: turn2 dispatch5/20 parallel batch; 2 started / 0 complete; turn1 partial15; max60 turns; zero retries. No aborted task retried. No nested agents, implementation changes, staging, commit or test execution. Only this report was deliberately written. User SLO/docs/ASCII content preserved.

## Confirmed blocking findings

### R567-01 — High: cancellation can commit after the queue is sealed

**Rule/source:** DC05 §6.2 explicitly requires `Session sealed → completing → no commit`; §2.3 requires recovery/cancellation serialization before the queue mutex. DC07 makes queue seal the admission/finite linearization point.

**Where:** `src/agents/slo_agent/messaging/queue.py:440–452`; `src/agents/slo_agent/sessions/service.py:1810–1838,1857–1869`; readiness at `service.py:906–913`.

**Concrete failure:** an owner previews cancellation of retained input, the queue is sealed (for example by finite completion or host stop), and the owner confirms before session close. `cancel_retained_messages` authorizes the owner, but `_require_messaging_ready` checks closing/storage/accepting and does not check the queue seal or finite-stopping state. `_cancel_registered_messages` then calls queue cancellation. Unlike adjacent `recover`, `SessionMessageQueue.cancel_retained` checks only storage health under `_mutex`; it never rejects `_sealed`. `MessageStore.cancel_retained` also has no lifecycle guard. Consequently this valid, previously uncommitted selection can become cancelled after seal, rather than returning `completing` with unchanged retained rows. The queue mutex makes the missing guard particularly clear: there is an existing precise place to enforce the contract without a racy session pre-check.

**Evidence adequacy gap:** `tests/agents/slo_agent/messaging/test_retained_recovery.py::test_sealed_recovery_refuses_without_mutation` seals and checks *continue*, then closes the entire session before checking *cancel*. Closing triggers a different guard and masks this case. The existing successful tests and full green suite do not prove cancellation after seal.

**Required correction:** reject a new retained cancellation under the queue's mutex when sealed, using the existing `completing` error, before store mutation. Keep session consent validation and already-committed replay semantics intact; do not move the check outside serialization or make close the only cutoff.

**Closure:** a real-session/SQLite regression previews cancellation, seals while the session remains otherwise ready, confirms, and requires `completing`, no cancellation and exact retained identities/bytes. Include the admission/cancel-versus-seal ordering boundary using the existing executor gate if needed. Retain the current exact/cached/expired committed replay and all-or-none tests. Source-confirmed finding; no runtime reproduction was executed in this read-only partition.

### R567-02 — Medium, mandatory convention blocker: new recovery DAOs omit field descriptions

**Rule/source:** installed `languages/python/build-domain-features/SKILL.md`, “Field-Declaration Convention”: every Pydantic field, including required and internal value fields, must use `Field(..., description=...)`. The original DC05 schema specifies these fields and their meanings but does not waive this convention.

**Where:** `src/agents/slo_agent/messaging/dao.py:610–657`: `RetainedSelectionDAO.target/items/next_after_sequence`, all five `CancelRecoveryConfirmationDAO` fields, and both `CancelRecoveryOutcomeDAO` fields. Some are bare annotations; existing `Field` calls carry constraints but no description. By contrast the newly added `QueueStateDAO.applying_records` and `FiniteCutoffDAO.outcome` document their fields.

**Consequence:** these new public typed consent/selection boundaries fail the required self-documenting/schema contract. This is not a runtime validation failure or a request to convert unrelated historical DAOs.

**Required correction/closure:** add concise field descriptions to these ten fields, preserving requiredness, defaults, bounds and validators exactly. Verify the generated schema descriptions and unchanged validation behavior; run affected typing/format checks. No new data model, table or migration is needed.

## Source and ownership trace

```text
Mounted slash/key entry
├─ SlashRouter → typed MessagesCommandDAO / submit_text / control result
├─ SloTUI → page/pending-confirmation presentation; replacement ordering
│  ├─ SloAgentSession → owner consent, clock, recovery lock, pause/resume
│  │  └─ SessionMessageQueue → mutex serialization → MessageStore transaction
│  └─ PromptInputComponent → public retirement/replacement/draft handoff
└─ HeadlessRunner → one invoke publication → finish_finite_messaging
   └─ Session → execution lock → history barrier → queue cutoff
      ├─ single scheduler and idle-note consumer
      └─ stop → cancel/join consumers → reconcile history → retain pending
```

Inspected current cumulative queue/store/DAO and headless diffs, current session consent/scheduler/reconciliation/finite/stop/close code, app recovery/control/replacement/steer/close wiring, router parsing and real Typer true-flag sites. Untracked tests were read as source, not omitted from the diff: complete retained recovery, mounted messages, session controls, finite completion, headless messaging and steer files. Also inspected the changed store retained test. Existing source owners remain the implementation boundary; no ORM, new application-service class, new CLI verb or graph topology is required.

## Original A-row reconciliation

“Supported” means independent source/assertion inspection supports that row and it is included in the inspected passing final-suite receipt; it does not mean this reviewer reran it. File abbreviations: **R**=`tests/agents/slo_agent/messaging/test_retained_recovery.py`; **S**=`tests/agents/slo_agent/messaging/test_store_retained.py`; **M**=`tests/tui/test_messages_command.py`; **C**=`tests/tui/test_messaging_session_controls.py`; **F**=`tests/agents/slo_agent/messaging/test_finite_completion.py`; **H**=`tests/cli/test_headless_messaging.py`.

### DC05 — consent and retained persistence

| Original row | Independent source and decisive test evidence | Disposition |
|---|---|---|
| A1 | Session `_reconcile_message_applications` validates raw history, resets unprepared claims, reconciles identity, reconstructs projection before marking applying receipts. R `test_restart_reconciles_without_provider_and_lists_retained[flat/tree]` seeds pending/applying/applied/committed-compacted together, starts two successive owners, checks exactly one applying/applied history event, compacted original absent, only pending listed, zero requests, and exact final SQLite states. | Supported |
| A2 | `_continue_registered_message` delegates original transfer to queue/store and resumes only after committed accepted outcome. R `test_confirmed_continue_executes_original_once[flat/tree]` checks original sender/submission/target, destination generation, exact provider HumanMessage, one transfer row, unchanged stored submission JSON and untouched sibling. | Supported |
| A3 | Registry outcome replay and store `transfer_id` replay precede expiry. R `test_lost_reply_retry_returns_saved_outcome` commits through the real queue without populating session cache, advances six minutes and checks equal outcomes twice plus one transfer row. This is real durable replay, not a simulated return-only mock. | Supported |
| A4 | `_require_unexpired_recovery` uses injected clock and `>=`; R expiry test requires conflict, two retained bodies and no model call. Exact five-minute boundary additionally exercised by cancel and mounted expiry. No transfer mutation is reachable after the guard. | Supported |
| A5 | Exact evidence is re-read under recovery serialization; R changed-selection test confirms separate cancel first, then stale continue conflicts with no provider. Existing terminal store handling does not re-execute cancelled input. | Supported |
| A6 | Session validates whole ordered set, store validates all before updates inside SAVEPOINT. R concurrent confirmations return identical ordered cancelled receipts, expired cached retry same outcome; mixed-set refusal preserves sibling. M declines/re-previews/confirms cancel; S applied-member refusal verifies rollback. | Supported normal/replay/atomic behavior; sealed boundary is R567-01 |
| A7 | Source registration is object-identity based and single use; preview checks exact DAO/action/principal, bounded16/5min registry. R forged source, altered DAO, previous-owner consent and seventeenth preview tests assert unauthorized/queue_full, expiration frees capacity; separate strict cursor/UUID/page/foreign-owner cases. | Supported |
| A8 | Store `find_identity` validates stored identity and can decode pruned terminal proof. S `test_cancel_replay_and_point_identity_read` checks invalid/absent lookup, repeated cancelled identity equality, pending+applied rollback, nine-day pruning and surviving applied history identity. | Supported |
| A9 | Router parses; app resolves full or unique≥8 prefix only from last page and delegates session consent. M real Enter flow checks list/preview/decline/confirm, off-page usage, one model execution, exact closed applied/cancelled rows. Injected lost-reply real-session subclass checks same confirmation object and one execution; expiry clears held consent. | Supported |

Beyond table rows, DC05 §6.2 sealed-cancel contract is **Partial**, blocked by R567-01. New record documentation is blocked by R567-02. No acceptance row has been silently removed or redefined.

### DC06 — mounted session controls

| Original row | Independent source and decisive test evidence | Disposition |
|---|---|---|
| A1 | App `action_interrupt`/slash abort choose bound messaging session and avoid escalation; session abort latches reusable pause. C `test_abort_pauses_and_keeps_pending[False]` holds actual provider, admits two pending IDs, asserts hint/no app task/zero escalation, aborted history, one request and both accepted/not-retained receipts. Notes alone do not resume. | Supported |
| A2 | Session admission resumes only nonretained agent_input. Same test `[True]` asserts ordered first/second/third/next application IDs, exact cumulative provider contexts including note-before-input, and all applied closed-store rows. | Supported |
| A3 | `_clear_transcript_and_prompt_queue` avoids legacy slot/band removal on messaging binding. C `/clear` and Ctrl+L variants check cleared user widgets, unchanged band/recall, newer draft, public replay of old applied event gives no second echo, pending later applies/echoes once. Additional test preserves recoverable snapshots. | Supported |
| A4 | Candidate preparation precedes retirement; committed replacement joins old messaging before adoption. C `test_new_retires_binding_closes_old_and_never_redirects` verifies old observation done, adapter/client retired, old pending retained, real execution lease reacquisition, old/new Inbox leases, exact old-target host draft, refused old retry, and successor DB containing only fresh input. Held-close variants additionally prove no early adoption, cancellation join and cleanup-failure notice/safety. | Supported |
| A5 | Existing running refusal is retained before candidate construction. C held-provider test checks refusal text, zero candidate sessions and identical live session/client/observer. | Supported |
| A6 | Retirement failure discards candidate before old revocation. C full16-host-draft test checks discarded candidate close, unchanged old binding/session/client/observer, component draft intact and actual same-ID retry/resubmit on old scripted binding. Test-owned script adjustment is not replacement of an application collaborator. | Supported |
| A7 | Actual Pilot Ctrl+C variants exercise running pause versus idle unsent warning then exit; escalation probe remains0 and running pending receipt remains accepted. Resource references clear on idle teardown. | Supported |

### DC07 — finite settlement, stop and steer

| Original row | Independent source and decisive test evidence | Disposition |
|---|---|---|
| A1 | Runner `_drain_session_stream` invokes once, then waits on session finite owner, updating exit state without re-emitting terminal. H second-run variants admit at first terminal, require exactly two original/external rows, two requests/two stdout terminals and exit0/2 from second result. | Supported |
| A2 | Queue `seal_if_quiescent` reads under mutex; committed eligible input blocks seal. F admission-before-cutoff queue test plus `test_registered_admission_at_session_cutoff[True]` gate actual worker completion and prove real scheduler drains before terminal/seal. | Supported |
| A3 | Same queue mutex seals before waiting unaccepted admission; queue admission refuses completing without storage. F queue case and registered session `[False]` require completing, zero identity/provider, tracked calls emptied and bounded finish. Joins are outside execution/history/queue locks. | Supported |
| A4 | F `test_terminal_between_check_and_wait_cannot_hang` actually changes revision by admission during the execution-lock wait. Scheduler settlement updates latest terminal before clearing run and notifying. Captured revision/event precede checks; compare follows lock release, with no suspension before Event.wait. Detailed disposition below. | Supported by complementary deterministic test and source proof; not literal terminal-gap injection |
| A5 | Cutoff ignores notes, retains under execution/history ownership and wakes paused consumers to exit. F pending-note test checks no provider, retained identity, same consumer handles completed and closed SQLite accepted/retained1. | Supported |
| A6 | One shared finite task is shield-joined; waiter cancellation propagates only after owned completion. F before/after seal variants issue three cancellations, hold provider or registered receipt, then require completing on later admission. | Supported |
| A7 | Close publishes closing before joins, seals and joins finite/stop outside locks. F concurrent-close test requires bounded finish+close, both consumers done, not-ready and reacquirable real lease. | Supported |
| A8 | Runner timeout delegates to public stop before observer cancellation; stop seals, sets permanent guard, cancels/joins real consumers, reconciles under execution/history then retains. H hung-provider exit2/pending readback plus F observer/cancellation, prepared-journal repair and repeated-stop join cases. Detailed disposition below. | Supported complementary real-boundary evidence |
| A9 | Store counts current-generation applying records before either lifecycle branch; queue checks applying before eligible input/seal. F both accepting states and orphan test require recovery_required/run_failed, no model and applying count1, not successful cutoff. | Supported |
| A10 | Router ready branch returns submit_text; app delegates normal durable draft capture with intent_revision=None, not legacy steering. Complete `tests/tui/test_messaging_steer.py` checks held-run band, exactly one adjust echo/application, exact next provider context and no steering_message event. | Supported |
| A11 | Constructor default remains false; cumulative headless diff keeps legacy invocation path and existing signal/watchdog/control/status/notifier/reporting owners. Existing headless/herdr/watchdog/child-abort suites were included in source§8 regression and final full suite. No legacy test deletion in inspected headless diff. | Supported compatibility, not a new default-host acceptance claim |

## DC07 A4/A8 and locking: final disposition

**A4 accepted as complementary proof of the invariant.** The test name is broader than its actual interleaving: admission advances revision while finish waits for execution ownership. It does not force a terminal between the final comparison and wait. That literal scheduler interleaving cannot occur there in this single-event-loop code: no await occurs between comparison and calling Event.wait, and Event.wait returns immediately for an already-set event. Notifications increment revision, swap event, then set the old event synchronously. The scheduler records latest terminal in `_settle_invocation_observers` (`service.py:5411–5422`), clears `_message_run` and notifies in finally (`995–1070`). Admission notifies in finally (`2124–2158`), pause/close/stop notify synchronously, and inspected storage-failure sites notify. Queue cutoff's `may_seal` recheck is after awaited store work. Test coverage plus these actual source facts establish no lost wake without manufacturing an artificial callback between synchronous statements.

**A8 accepted as complementary tests, not one combined experiment.** The runner journey keeps the provider gate unset through grace and exit2; the session hard-stop journey additionally checks `cancelling()>0`, completed consumers and assigned `run_aborted`; the prepared-journal journey uses actual claim/prepare APIs, public stop and exact-once history/applied readback. Reconciliation first validates raw history/compaction evidence, resets unprepared claims, repairs prepared identities via append-once, reconstructs projection membership, and only then acknowledges applying records. A held provider has already passed initial application; adding an unrelated second prepared journal to that runner is not necessary to prove the owner contract. No claim of one combined crash-window experiment is made.

**Lock/lifecycle inspection:** finite checks take execution→history→queue; stop joins consumers before acquiring execution/history; call snapshots and consumer joins are outside those locks; recovery lock is not held with execution ownership. Queue's settled operation retains mutex ownership through worker outcome and signal publication, including cancelled waiters. Consumer guards follow resumed/work/note wakes and execution acquisition. On finite stop, resumed is set so paused consumers can exit rather than spin. Shared close/finite/stop tasks do not call back into close in a cycle. R567-01 is a cutoff-policy hole, not a lock-order defect.

## Mandatory hard-rule disposition (post-hook)

The full installed Python `code-review-rules` checklist was read, not only its first section. Scoped application:

- **Tell Don't Ask / ownership:** session owns consent and execution, store owns transactional mutation, queue owns cutoff, app owns presentation and adoption. Original specs explicitly place these host operations in SloTUI; generic suggestions to move every app operation into new services or `run_worker` do not override that precise contract. No UI SQL or second scheduler was found.
- **Declarative structure:** finite flow is decomposed into cutoff/retention/join/terminal helpers; consent into registered-preview/evidence/replay/cancel helpers; replacement into prepare/retire/commit/close/adopt owners. Atomic mutex/transaction blocks are coherent boundaries and are not split merely to meet a line quota. Nested native lock contexts preserve required lock ordering; they are not nested policy conditionals. Existing large session/app methods are not an authorization for unrelated refactoring.
- **Types/named arguments:** inspected new public signatures and DAO/result unions are typed. Business-operation multi-input calls use keywords. Callable callbacks, sqlite execute positional-only API and variadic asyncio calls are not treated as keyword-capable domain calls. Internal state holders follow the original specification's private lifecycle shape. No new unconstrained `Any` boundary was found in this partition. Full mypy receipt is passing but not substituted for inspection.
- **Docstrings/schema:** public consent/cutoff/finite/stop operations document purpose, ownership and outcomes; short obvious validators need no invented boilerplate. **R567-02 fails the separate mandatory Field-description rule.** Do not report blanket convention compliance while it remains.
- **Naming:** message_id, confirmation_id, original target, execution_generation, retained, applying, cutoff and settlement revision match the spec. “Identity”, “evidence” and “handoff” are actual feature vocabulary, not newly invented review terms. Preserve source-specified names rather than global renaming.
- **Test-first:** dispatch7 continue/cancel RED→GREEN, dispatch8 controls RED→GREEN and dispatch9 cutoff RED→GREEN log endings independently inspected. Reports distinguish setup errors, interface RED and later assertion-only additions; no claim that every later test first failed. This is evidence of incremental development, not reconstruction of all editing chronology.
- **Public injection / simple tests:** real SQLite/history and ordinary pytest/Pilot; injected clock, executor gate, model/agent factory, successor/session subclasses and public prompt replacement. Direct access to real queue/store for a documented lost-reply/prepared-journal state is not swapping a private collaborator. Read-only task/lock assertions establish ordering. Provider factory patch in H is the expressly permitted vendor boundary. No added BDD/custom runner or mocked persistence in these scoped tests.
- **No regressions:** relevant full/affected receipts pass, meaningful old controls remain, no scoped assertion deletion found. This does not prove warning-free operation or excuse R567-01's missing branch. Broader historical test changes remain the aggregate review's ownership.
- **Not applicable:** FastAPI namespace/envelopes, SQLAlchemy model/migration rules, Vue/SSE, DBOS registration, new Typer command naming and new LangGraph gateway/topology diagrams. No user ASCII/comment cleanup requested.

## Gate evidence inspected — no ceremonial rerun

All below are existing execution receipts, not commands executed by this reviewer. Cwd is this app root; final Make command uses the recorded existing slo-harness environment and project synthetic fallback. No waiver/exclusion was inferred.

| Receipt | Independently opened evidence |
|---|---|
| `logs/turn2-d3-final-full.command/.log/.exit` | Exact `make test PYTEST_WORKERS=6`; Python3.11.7/pytest9.0.3, six workers/12269items; **12269 passed,1267warnings,627.91s,exit0**. |
| `turn2-d3-affected.log/.exit` | **3383passed,538warnings,258.96s,exit0**. |
| `turn2-d3-repeat-{1,2,3}.log/.exit` | Each **47passed,40warnings,exit0**,54.50/54.47/54.15s. |
| `turn2-d3-final-focused.log/.exit` | **47passed,40warnings,52.07s,exit0**. |
| `turn2-d3-final-lint.log/.exit` | `poetry run mypy src/ tests/`; **980files clean,exit0**. |
| `turn2-d3-black-final.log/.exit` and `turn2-d3-black-paths.txt` | **59 cumulative tracked/untracked Python files clean,exit0**; inventory includes all scoped new tests. |
| `turn2-d3-collection.log/.exit` |12269/12290 collected,21project-marker deselections,exit0; not execution. |
| `turn2-d3-final-{diff,coreutils}.log/.exit` |exit0, empty output. Reviewer also ran read-only `git diff --check`:exit0. |

Read the full final-full warning section, not counts alone. Scoped R/F/H/M/C/steer warnings fall in LangGraph's Pydantic `model_fields` deprecation group (2/10/6/2/13/2 respectively). Other categories include pythonjsonlogger relocation, LangGraph serializer pending deprecation, OpenAI model_kwargs warnings and unawaited AsyncMock warnings attributed to CLI mock tests and a legacy queued-prompt test. These are not evidence that this partition leaks real scheduler tasks; they also are not certified harmless globally. Aggregate review should retain their attribution and historical harness context. No warnings were suppressed or waived here. Aborted dispatch2 full141/83% is not passing evidence.

## Instruction loading, limits and handoff

Read current SLO.md, README opening/runtime ownership/testing/maintainer rules, Makefile/pyproject, current acceptance-routing, current handoff and ledger pointers, historical final-review and final-review-turn2, dispatch7/8/9/12 reports and turn2-d3 handoff. One initial oversized combined historical read truncated; subsequent bounded reads supplied current routing/handoff and relevant reports, and no unseen truncated portion is claimed as reviewed. Root and docs RESEARCH are absent; no replacement was created. No nested src/tests instruction files found.

Installed root used: `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`. Loaded exact Code-Test-Review and shared workflow; engineering routing/testing/ownership/review; coding solution-design/coding-rules/code-design-principles/naming/declarative/test-verification/cadence; Python root, named args/types, docstrings, declarative, imports, application/domain build recipes and application/domain/graph test recipes; Textual build recipe; review-feature-code and complete Python hard checklist. Scope-specific SQLite and original module ownership override unrelated PostgreSQL/FastAPI examples. No external-client build recipe is imposed on this in-process queue. KB Welcome, slo README/gotchas/conventions/environment/TUI-session and supported shared MEMORY consulted; stale KB platform/path advice yields to live project files. The explicit output path overrides historical KB-only prose destinations.

### Completion checklist / finite next action

- [ ] **Must-fix code:** R567-01 sealed cancellation guard at the serialized mutation boundary.
- [ ] **Required tests:** real still-open/session-sealed cancellation regression, unchanged atomic/replay tests and affected gates.
- [ ] **Mandatory documentation in code:** R567-02 ten recovery DAO field descriptions, preserving schema semantics.
- [x] **DC07 A4/A8 disposition:** complementary evidence accepted for the stated invariants, with exact limitations above.
- [x] **Scoped original A-row mapping and hard-rule pass:** complete; no independent full-feature/completion claim.
- [ ] **Later:** aggregate review reconciles sibling partitions and these stable findings; separate completion follows only after accepted aggregate review. No staging/commit permission follows from this report.
