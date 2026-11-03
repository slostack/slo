# Independent final-review partition DC01–DC04

## Verdict: REVISE — scoped audit complete, not whole-feature acceptance

This partition reconciles **all 39 original A rows** (8+12+11+8), EF01–05 and FR01–03. The finite blocking list is DC-R01–DC-R04 below. Later synthesis review and a separate completion check remain mandatory. No acceptance of DC05–09 is implied.

Authority: only original numbered specifications 01–04 in `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/revised/01-durable-composer/`. Read each in full. Historical reviews and author reports are navigation/evidence records, not replacement requirements. Counters carried unchanged: **2 started / 0 completed; turn1 partial15; turn2 dispatch5/20 (parallel batch); max60; zero retries**. Aborted prior worker not retried. No code/test edits, test execution, staging, commits, nested agents or host changes. Only this file written; an initial durable finding milestone preceded this final report. User SLO/docs/ASCII changes preserved.

## Findings — finite repair list

### DC-R01 — High: settled outcomes accumulate without bound in the production editor

**Source:** DC02 §3/§5.5–5.8 bounded draft ownership; engineering ownership; coding-rules information hiding; test-verification-policy injected stubs.

**Where:** `src/tui/components/prompt_input/component.py:155–158,1133–1136`; test consumer at `tests/tui/test_durable_composer.py:1057` and outcome-record consumers throughout the composer/identity/prerequisite tests.

Every tracked outcome is unconditionally appended to `_recorded_outcomes: list[SubmissionOutcomeDAO]` before adoption. The comment says production never populates these test hooks, but the append has no guard. Successful adoption releases `_tracked_drafts`, not this list; reset, replacement and close never clear it. Thus each settled prompt retains its full text, snapshot and outcome for the component lifetime, outside the four-wait/16-draft/1MiB reservation and 4096-ID recall bounds. FR02 repaired adapter Task retention but not this independent retention path. `_outcome_failures_remaining` also embeds test-only failure behavior in the production owner and is set privately by a mounted test.

**Correction:** remove production recording/failure-test hooks. Obtain receipt/identity assertions through the real client/store or an injected recording client/component/receiver at a public construction/binding seam. Keep the real mounted journeys and failure/sibling/cancellation assertions; do not simply delete their oracles. A test-owned recording receiver already exists in this file and demonstrates the adapter seam.

**Closure:** repeated mounted successful submissions and reset/rebind must release settled snapshots; a failing injected receiver still joins all siblings and releases borrowers last. Audit all `_recorded_outcomes` consumers (including other partitions' tests) when replacing the seam. Static unconditional append and absence of cleanup establish this defect without a runtime probe.

### DC-R02 — Medium, mandatory evidence blocker: A7 never exercises eager execution

**Source:** DC02.A7 and §5.5–5.6 require an outcome arriving before registration/clear commit under eager task execution.

**Where:** `tests/tui/test_durable_composer.py:1327–1365`; adapter `message_submission.py:133`; component `component.py:1045–1065,1137–1139`.

The test supplies an immediately answering async client but uses ordinary `asyncio.create_task`. No test installs a task factory or otherwise causes receiver delivery inline before `handle` returns. On the recorded Python3.11 environment, the task runs only after the uninterrupted capture/register/clear section yields. The test therefore proves fast asynchronous success, not `entry.committed == False` / `early_outcome` adoption. Searching the tests for `set_task_factory` and `early_outcome` found no corresponding exercise. Removing the early-outcome stash would not invalidate this test's stated oracle.

**Correction/closure:** add a small deterministic test using the existing public injection surface and a locally scoped eager scheduling mechanism appropriate to the approved interpreter (restore it in finally). Prove delivery actually occurs while the entry is uncommitted, then prove no editor mutation before clear and exactly one post-commit adoption/recall. Do not substitute another immediate-return client or private assignment of `early_outcome`. No new test framework or Python upgrade is requested.

### DC-R03 — Medium, mandatory evidence blocker: revision test does not prove restoration refusal after edits

**Source:** DC02.A8 explicitly requires both revision advancement and refusal of restoration after any edit; §5.1 expressly includes editing back to empty.

**Where:** `tests/tui/test_prompt_component_protocol.py:660–701`; `tests/tui/test_durable_composer.py:1099–1166`; component `_outcome_may_restore` at `component.py:1173–1193`.

The A8 test proves incrementing revisions for typing/undo/redo/replace/clear/recall, but contains no pending submission and delivers no late rejection. Its final comment says restoration stays refused without asserting that behavior. The newer-typing test leaves `C` nonempty, so it passes even if the revision comparison is removed: `self.text == ""` already prevents restoration. Reset coverage also ends empty, but is a different lifecycle boundary. No inspected composer test holds a same-binding rejection, edits and returns the cleared editor to empty, then releases rejection.

**Correction/closure:** extend the mounted delayed-rejection journey to exercise same-binding edit→empty and the specified revision boundaries (parameterized where practical). Assert the newer empty editor remains empty, original snapshot remains recoverable, and no extra admission occurs. Keep the existing revision-counter assertions and untouched-clear restoration test. This is the original A8 safety obligation, not optional matrix expansion.

### DC-R04 — Medium: new boundary records and test signatures miss explicit mandatory conventions

**Sources:** DC02 §2.3 (new DAOs frozen, extra-forbid, described fields); README Style rules; Python hard checklist §1.1–1.2; named-arguments/type-hints and method-docstrings.

**Finite locations:**

- `src/tui/slash_router.py:57–64`: `MessagesCommandDAO` is mutable (`ConfigDict(extra="forbid")`, no `frozen=True`), and its three fields have no descriptions. This new cross-owner intent is part of DC02, even though DC05 later extends its action union.
- `src/tui/components/prompt_input/commands.py:89,98` and `src/tui/components/chat_transcript/commands.py:137`: new submission/discard/application fields lack the specified described `Field` contracts. `RecordAcceptedPromptDAO.message_id` is likewise undocumented at its field boundary.
- `tests/tui/test_composer_transcript_identity.py:408` (`HeldReplaySession.__init__(**kwargs: Any)`) uses unrestricted `Any` without an explanatory typing exception; concrete session construction inputs are visible immediately below. `tests/tui/test_durable_composer.py:1126,1193,1300` use bare `tuple` for recoverable draft views rather than `tuple[RecoverableDraftDAO, ...]`.
- New multi-argument pytest decorators in `test_observation.py:82`, `test_composer_transcript_identity.py:79,95,285`, `test_composer_retirement.py:334,424`, `test_durable_composer.py:821,877` use positional argnames/argvalues despite supported keyword forms. These are not positional-only framework APIs.

**Correction/closure:** freeze and describe the new boundary intent/fields; use specific recoverable-draft/container and constructor types, and keyword decorator arguments. Re-run static registration/DAO tests and existing relevant journeys. No broad repository restyling or conversion of explicitly specified private lifecycle dataclasses is requested. Existing stdlib positional-only calls are not findings.

## Runtime trace and ownership audit

```text
Mounted SloTUI
├─ reporting + ready model preparation → _activate_session_messaging
│  └─ session.start_messaging → execution lock → lease/store/reconciliation
│     └─ injected agent.bind_message_source → queue readiness → sole scheduler
├─ Enter → stamped draft revision → exact normalized capture
│  └─ component reserve/register/clear (no suspension before commit)
│     └─ borrowed MessageSubmissionAdapter → LocalSessionMessagingClient
│        └─ session-tracked admission → queue mutex/authorization → SQLite transaction
│           └─ scheduler → canonical history append → agent insertion → mark_applied
├─ observe_messaging (registered before replay)
│  └─ verified event + owner summary → existing transcript projector ID/hash
│     └─ human echo / machine notice; shared receipt/application recall ID
└─ retirement
   └─ stop/join observation → join prompt waits → exact acknowledged memory handoff
      └─ release adapter borrowers → close clients → session retain/close → release lease
```

Source inspected beyond the last adapter repair: agent binding and boundary insertion (`agent.py:283–302,1126–1145`); session activation/scheduler/application preparation+commit (`service.py:896–1280`), owner authorization, observation/admission (`2038–2157`), close/release (`2355–2465`), barrier hydration (`2669–2683`); client complete file; queue admission/summary and store transaction/identity insertion/application settlement/owner-summary paths; ownership ancestor-open correction; history provenance validator/classifier/lazy exports; complete new submission records/adapter initializer/adapter; component revision, commands, capture/adoption/retry, reset/retire/rebind/close; app activation/preparation/reporting, observer/band/presentation, Enter/draft commands, pre-pruning/client/session close and exit warning; typed command/protocol/registry/router changes and transcript component/projector cumulative diffs.

No second execution consumer, new history writer, UI SQLite reader, migration or generic wrapper service is introduced. Admission deadlines abandon waits, not session work. Adapter reset/close capture outstanding siblings, observe results, retain one sticky failure, and release Task references on completion; close shares one completion barrier and releases client/receiver in finally. Component accepts outcomes during closing, seals capture before retirement, and joins outside receiver locks. Handoff refusals preserve the old adapter and exact snapshots; lost positive acknowledgement retries the same key/content. Host-held drafts cannot be retried into a successor. DC-R01 is the exception to otherwise bounded transient ownership.

Observation publication is synchronous; subscription has 256-event/1MiB limits and a sticky replay-gap error. Draining detaches a bounded snapshot before awaiting summary; new publications retain their own wake signal. Authorization excludes machine readers from owner observation. History replay holds the barrier; canonical event-ID/run validation precedes human/machine classification. ID/hash identity survives run reset/clear and is retired on actual history rebind/close. Invalid provenance produces fixed text without payload. Compaction uses projected history rather than fabricating echoes from coverage. The overflow test's public HydrateTranscriptDAO join is valid: `_hydrated` is set before mount completion, whereas the public call crosses the active hydration lock before cursor paging. Its exact514-ID assertion is preserved.

## Original A-row reconciliation

Legend: **Implemented** means inspected production wiring plus adequate inspected assertions and passing current receipts for that row; it is not whole-feature approval. **Partial** identifies a finite blocker above. All paths below are app-relative. Test aliases: **D**=`tests/tui/test_durable_composer.py`; **P**=`tests/tui/test_composer_prerequisites.py`; **R**=`tests/tui/test_composer_retirement.py`; **I**=`tests/tui/test_composer_transcript_identity.py`; **O**=`tests/agents/slo_agent/messaging/test_observation.py`; **A**=`tests/agents/slo_agent/messaging/test_injected_activation.py`. Source references are to the original file's §8 row, not an author reinterpretation.

### DC01 — original `01-injected-agent-activation-and-opt-in-host.md`

| Row | Production and assertion evidence | Independent disposition |
|---|---|---|
| A1 | agent binding; session activation; A::test_injected_agent_binds_session_source_and_delivers_once: same injected object, exact HumanMessage, one application, closed SQLite applied row/reopen | Implemented |
| A2 | startup except→release; A::test_injected_agent_refusal_releases_store_and_lease: constructor foreign source, unsupported, no rows/provider, second owner acquires | Implemented |
| A3 | idle/same/foreign source guards; A::test_bind_message_source_is_idle_and_idempotent: real held provider makes busy refusal, then idle success | Implemented |
| A4 | app preparation/reporting gates and activation; D::test_mount_starts_messaging_after_reporting_setup[False/True]: exact lifecycle sequence, database/client target, no provider; cancelled/displaced activation test verifies unwind | Implemented |
| A5 | inactive Enter refuses legacy fallback; D::test_startup_failure_refuses_prompts_without_memory_fallback: real held lease, kept text, no history/provider/task/slot | Implemented |
| A6 | post-hydration ephemeral notice; D::test_ephemeral_session_announces_non_durable_messaging: one notice, accepted/applied durable=False, no disk database | Implemented; recording seam repair required by R01, assertions must survive |
| A7 | pre-pruning retirement, app client-close then public session-close; D::test_exit_closes_client_then_session_and_retains_pending: client probe before close, retained row and reacquired lease; close-failure test | Implemented |
| A8 | constructor false/default legacy branch; unchanged `test_prompt_component_protocol.py::test_enter_clears_prompt_and_persists_real_turn`: real user/answer/history terminal order and native editing | Implemented |

### DC02 — original `02-durable-composer-submission.md`

| Row | Production and assertion evidence | Independent disposition |
|---|---|---|
| A1 | app Enter→component→adapter→SQLite/scheduler; D::test_busy_enters_admit_three_distinct_durable_messages: provider held after first entry; three IDs/sequences, exact cumulative model contexts, three exact applications/answers, closed applied rows, Ctrl+Enter/new typing/no legacy slots | Implemented; R01 affects long-lived resource contract |
| A2 | `_outcome_may_restore`; P::test_real_sender_limit_preserves_or_restores_draft[True,sender_limit/queue_full]: actual gated SQLite rejection, C retained, B listed, no provider B/two durable rows | Implemented |
| A3 | same restoration owner; P false cases plus D::test_rejection_restores_unchanged_cleared_draft: B restored/cursor end/reservation released | Implemented |
| A4 | adapter one lookup + identical retry; P::test_real_unknown_outcome_retry_observes_single_committed_identity: actual .05s submit/lookup uncertainty, slash same-ID retry, exactly one real model input/closed applied row; D scripted call-count case | Implemented |
| A5 | four-wait component gate and adapter invariant; D::test_fifth_waiting_draft_is_refused_before_clear: four actual held submissions, fifth preserved, release before teardown | Implemented |
| A6 | canonical count/byte cost including host reservations; D::test_recoverable_budget_counts_waiting_and_retained_bytes + R::test_handoff_and_component_share_canonical_byte_budget:16 snapshots, discard frees slot, canonical sum under cap | Partial overall bounded ownership: DC-R01. Tests prove reservation budgets, not absence of settled-record retention |
| A7 | committed/early_outcome branch exists | Partial: DC-R02; named test only proves ordinary fast async completion |
| A8 | synchronous edit/document/undo/redo revision hooks; `test_prompt_component_protocol.py::test_draft_revision_advances_at_every_edit_boundary` | Partial: DC-R03; counters verified, edit→empty late-refusal guarantee not exercised |
| A9 | complete adapter lifecycle; D loop/closed/reset/cancel/failing receiver/client/held sibling/200-completion tests, including concurrent close and sticky failure | Implemented adapter contract; production component test hook remains DC-R01 |
| A10 | MessageSubmissionProtocol class-side register and Self return; `test_adapter_registration.py` positive exact type and negative dependency/call diagnostics, final full lint | Implemented; boundary record convention defect separately DC-R04 |
| A11 | existing strip/empty/slash/literal route; D::test_empty_and_literal_drafts_follow_existing_rules: whitespace no record and exact bracket/newline provider/history text; slash retry/discard actual Enter elsewhere | Implemented (test docstring's claim literals never admit is inaccurate; its assertions correctly require literal admission) |
| A12 | sealed capture refusal; D::test_enter_during_session_change_keeps_text_with_notice plus R::test_retirement_refuses_capture_retry_and_survives_cancellation | Implemented via complementary real retirement sealing/public refusal. D alone manually fabricates seal and its unused client is not admission proof |

### DC03 — original `03-messaging-observation-and-transcript-identity.md`

| Row | Production and assertion evidence | Independent disposition |
|---|---|---|
| A1 | session publication, app band, transcript ID/hash; I::test_live_echo_once_per_id_with_band[flat/tree]: three ordered user/answer pairs, band two→gone, recall once | Implemented |
| A2 | same test remounts fresh generation over same flat/tree store: three echoes, empty recall, unchanged model request count | Implemented; combined test covers original separate row |
| A3 | projector reset versus RetireHistoryBindingDAO; I adapter test plus test_component_clear_preserves_identity_until_history_rebind public begin/clear/rebind: no duplicate until real rebind | Implemented |
| A4 | shared component recall identity; I::test_application_before_receipt_records_recall_once: delayed real client response, canonical echo/recall before receipt and still one after | Implemented; recording-hook dependency repaired under R01 |
| A5 | bounded subscription/gap loop/barrier replay; O count+byte overflow and I two257-event mounted overflow recovery, exact514 IDs/no conflicts/live observer; public hydration join reviewed | Implemented |
| A6 | canonical sender/kind classification and app human-owner recall predicate; I machine adapter and mounted component routes: sub-agent-notice, zero user widgets/recall | Implemented projection boundary; actual trusted machine admission belongs to DC08, not independently accepted here |
| A7 | history projector validates deterministic event ID/run; `history/test_transcript.py::test_invalid_messaging_provenance_replays_fixed_note`: invalid payload hidden, following valid event renders; paired/hash validation test | Implemented |
| A8 | projector conflict set; I::test_conflicting_same_id_evidence_fails_safely: exactly one fixed notice and one initial echo across repeats | Implemented |
| A9 | barrier replay/compaction summary classification; I::test_compacted_messages_are_not_fabricated_on_replay[flat/tree]: real original compaction setup, summary and only retained four-body tail | Implemented |
| A10 | owner authorization/single slot/finally detach/end observation; O::test_observation_authority_single_stream_and_close and cancellation/barrier test: conflict, unauthorized, held execution survives detach, completing | Implemented |
| A11 | app begin/finish run presentation + stream terminal routing; I::test_run_presentation_follows_session_execution: two real runs, spinner and context/usage refresh; fast-provider ordering test | Implemented |

### DC04 — original `04-binding-retirement-and-draft-handoff.md`

| Row | Production and assertion evidence | Independent disposition |
|---|---|---|
| A1 | component reset owned barrier; R::test_reset_joins_waits_and_keeps_binding + real SQLite admission[reset]: cancellation joins, empty editor, recoverable refusal, same adapter reusable/client open | Implemented |
| A2 | retire→exact handoff→close→register; R::test_rebind_hands_off_then_registers_fresh_adapter: two exact host-held snapshots, old borrower released/client untouched, real successor history input; shared budget test | Implemented |
| A3 | handoff negative ack unseals old binding; R::test_full_handoff_blocks_replacement_and_preserves_drafts:16 host snapshots, original retained, same-ID retry works, further capture refuses | Implemented |
| A4 | one component close task accepts outcomes until join; R actual remove + three cancellation test and real SQLite[close]: same barrier, no late editor mutation, handoff, client/session still accessible | Implemented |
| A5 | seal/version before join prevents successor publication; R::test_late_old_binding_outcome_never_paints_successor: distinct successor target, held replacement, newer text unchanged, original target retained; host retry never redirects | Implemented |
| A6 | app exact content/key acknowledgement; R idempotent/conflicting test and refused/wrong-ID/exception/lost-ack cases: same retry content/key, one host reservation | Implemented |
| A7 | app exit confirmation; R::test_intentional_exit_warns_once_about_unsent_drafts: first /exit remains, second exits; D ordered client/session cleanup supplies complementary close-order proof | Implemented |
| A8 | pre-pruning memory notice + dropped feedback; R forced teardown twice→one notice; refusal-close test releases only after joining and explicitly reports loss | Implemented |

## Historical finding closure

| Finding | Independent disposition |
|---|---|
| EF01 | **Closed.** D minimal mounted journey now waits for held provider, checks exact HumanMessage once, one matching application ID, scripted answer and exact applied-first/retained-second SQLite rows. Full three-input journey separately proves DC02.A1. A injected test also asserts exact provider text. |
| EF02 | **Closed for adapter join defect.** All outstanding siblings joined before failure; shared concurrent close, borrower release in finally, repeated-cancellation tests and failure-during-shield test inspected. Does not excuse DC-R01 component retention/test hooks. |
| EF03 | **Closed.** Actual reset/retire/rebind/close and native mounted remove exist; outcomes accepted during closing; acknowledgement before release; pre-pruning join inspected and asserted. |
| EF04 | **Closed.** Host no longer reads session-private start-task to decide cleanup; public idempotent close invoked after every client attempt even on failure. Injected real failing-close client test reacquires lease and verifies no provider. |
| EF05 | **Closed.** Receipt uses submitted text (including slash-originated drafts), common bounded ID set/deque with application fallback; replay does not add recall and machine sender never enters human recall. |
| FR01 | **Closed.** Loop guard, then closed, then type; genuine public lifetimes test supported/unsupported closed and foreign-loop calls without reopening private fields. |
| FR02 | **Closed for Task history defect.** Done callbacks observe/release, first exception only, traceback reset before rethrow,200-completion success/failure cases plus held siblings. Distinct component retention is DC-R01, not a claim this repair failed to remove Tasks. |
| FR03 | **Closed for specified private client swaps/reopening.** All helper callers now use awaited public replace_submission_binding and fresh adapter assertion; isolated tests register legitimate lifetimes. Separate remaining private failure hook is DC-R01. |

## Hard-rules post-hook

Read complete installed Python code-review-rules checklist and applied the scoped sections after flow/assertion inspection.

| Rule family | Disposition |
|---|---|
| Explicit types/keyword calls/docstrings | **FAIL DC-R04** at finite new-code locations above. Most public lifecycle methods document owners, ordering and errors; no blanket mypy-implies-style claim. |
| Declarative structure / Tell Don't Ask | Existing owners preserved; host does not reimplement SQLite policy. Atomic capture/register/clear is intentionally cohesive and suspension-free per original spec; do not mechanically split it into awaited fragments. Lifecycle helpers name meaningful join/handoff/release stages. Generic eight-line signal is interpreted by Python specialization's explicit meaningful-decomposition rule, not a formatter quota. |
| Boundary data | Frozen strict submission/handoff records and typed protocols; **FAIL DC-R04** mutable messages intent/missing descriptions. Private lifecycle dataclasses are explicitly permitted by this task's original design/routing; no unrelated conversion required. |
| Test policy / decision coverage | Real mounted TUI/SQLite/history/provider boundary throughout; public scripted-client binding repaired. **FAIL DC-R01–03** production test hooks and missing exact eager/revision decision proof. Resource-state inspection alone is not private collaborator replacement. |
| TUI layers/tasks/style | Parser remains router; transcript identity stays existing projector; app coordinates the named original host duties. Retained task handles and joined lifecycle, semantic classes, existing TCSS. Original spec expressly requires create_task-owned adapter/session lifetimes; generic run_worker wording does not override those named owners. |
| Naming/cross-layer vocabulary | Message ID, target, draft revision, binding version, handoff/ack, receipt, accepted/applying/applied retain their original meanings. No invented synonym or new authority-bearing DAO. Misleading production-hook comment covered by R01. |
| Persistence/auth/resources | Existing SQLite transaction/queue mutex/history barrier/lease hierarchy; client timeouts do not cancel accepted work; owner-only observation. No schema change, no second writer. Unbounded settled data violates resource rule: R01. |
| FastAPI/ORM/DBOS/Celery/Vue/HTTP | Not applicable. No new domain ORM trio, HTTP client, middleware, worker framework or frontend introduced. Build-application-services guidance does not require replacing this specified session facade with an artificial invoke wrapper. |
| CLI/graph rules | No new CLI verb, graph node/edge or gateway in this partition. Agent binding leaves invoke/model/tools intact; existing ASCII diagrams preserved. Default CLI cutover/full graph review belongs to other partitions. |
| Review output | Every original A row dispositioned; defects cite source/locations/consequence/closure; no optional scope, deferral or waiver invented. |

## Evidence receipts — inspected, not rerun

Cwd recorded `/root/Code/slo-message-queue/slo`; Python3.11.7 approved slo-harness, pytest9.0.3, xdist3.8.0; Make/pyproject default `not e2e`, synthetic fallback. No environment failure claim is made.

- `logs/turn2-d3-final-full.command/.exit/.log`: exact **make test PYTEST_WORKERS=6**, six workers/12269items; **exit0,12269 passed,1267 warnings,627.91s**.
- `turn2-d3-repeat-{1,2,3}` receipts: complete three regression files, six workers; **each exit0,47 passed,40 warnings**,54.50/54.47/54.15s. The overflow original A5 is among these; scroll/Herdr broader acceptance belongs to the other partition/synthesis.
- `turn2-d3-final-focused`: **exit0,47 passed,40 warnings,52.07s** after formatting.
- `turn2-d3-affected`: complete TUI+messaging directories, **exit0,3383 passed,538 warnings,258.96s**.
- `turn2-d3-final-lint`: **exit0,980 files clean**. `turn2-d3-black-final`: **exit0,59 files unchanged**; read the complete cumulative path inventory including untracked production/tests. Initial `turn2-d3-black.exit=1` remains historical, not overwritten.
- Separate collection: **12269/12290,21 deselected**, exit0; these are project e2e exclusions, not executed skips. No execution skips reported.
- Final diff/coreutils receipts exit0; current reviewer `git diff --check` also exit0. No tests run by this reviewer and no post-test integrity check invented.

Warnings are **not waived**: final full log lists pythonjsonlogger/LangGraph deprecations, provider model_kwargs UserWarnings, and unawaited AsyncMock RuntimeWarnings attributed at collection/GC locations in CLI dispatch/update and legacy queued-prompt tests. No warning-free or demonstrated baseline-equivalence claim is made. Those warning locations are not proof of allocation origin; synthesis must retain their unresolved attribution rather than turn them into passing lifecycle evidence. They do not conceal R01–04 and are not used as an unavailable-environment excuse. D2 interrupted exit141 is not a pass. Green suites cannot supply missing assertions identified above. Receipts attest execution history; they do not provide cryptographically pinned source identity.

## Review inputs and scope accounting

Read current SLO.md; README opening/runtime ownership/durable composer/style/testing sections; Makefile test/lint and pyproject tool/dependency rules; release-evidence README; acceptance-routing, implementation-handoff, full continuation ledger, early-review, final-review, final-review-turn2, turn2-repair, turn2-d3 continuation, dispatch5/DC03 and dispatch6/DC04 reports. Inspected cumulative tracked inventory/diffs and untracked files named above, not only the final repair. Entire A/D/P/R/I/O feature test files were read, plus static-registration file, changed history tests and prompt revision/legacy entry assertions. Other partitions' production/tests were followed only where they supply named complementary boundaries (same-ID retry, lifecycle, persistence); this is deliberately not a whole-feature diff sign-off.

Installed guidance read: exact Code-Test-Review and shared workflow; engineering routing/testing/ownership/review; coding solution-design/coding-rules/naming-and-clarity/code-design-principles/declarative-method-structure/test-verification-policy; Python root, full hard checklist, named-arguments/type-hints, method-docstrings, declarative specialization and build-application-services; full Textual recipe; review-feature-code. Installed INDEX/manifest routing inspected. No applicable personal override in supplied manifest. Domain ORM/build-clients recipes excluded because this scoped work extends existing SQLite/session owners and in-process protocols, not a new ORM entity/API client. No missing RESEARCH/build-rule file was created. KB Welcome→slo README, relevant gotchas, conventions, operational-reference and TUI/session runtime sections consulted; shared project MEMORY read. Current instructions/spec override historical KB paths and generic documentation destination rules.

## Completion checklist / handoff

- [ ] **Must-fix code:** DC-R01 unbounded production outcomes/test failure hooks; DC-R04 boundary immutability/descriptions and specific type/keyword violations.
- [ ] **Required tests:** DC-R02 genuine precommit eager delivery; DC-R03 same-binding edit→empty restoration refusal; retain all real journey/closure assertions while replacing R01 hooks.
- [ ] **Reverification:** focused impacted tests/static snippets, affected suites and required final gates after revisions; independent affected re-review.
- [ ] **Synthesis:** reconcile this partition with DC05–09 and warning attribution; then separate independent completion. No commit authority follows this report.
- **Product/spec decisions:** none requested, none deferred; no optional work promoted to a blocker.
- **Documentation:** only this report changed; historical reports and user edits preserved. No KB writes authorized in this partition.
