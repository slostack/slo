# Independent DC08–DC09 review and gate-receipt audit — turn 2, dispatch 5

## Verdict: REVISE; useful bounded audit, not aggregate acceptance

Original authority: `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/revised/01-durable-composer/`, specifically original 08 and 09 (read completely). No sibling specification is used to add scope. HEAD inspected: `5dd059cbf00134d5c5eef706875310a2eb677cdd`. This is independent of authorship. Counters carried: **2 started / 0 completed; turn1 partial15; turn2 dispatch5/20 parallel batch; max60; zero retries**. No aborted task was retried.

The functional DC08 trace and DC09 matrix assertions are substantially present. Exact final test/static receipts are corroborated below. Two finite mandatory-convention findings remain. **This report is not READY:** complete instruction/recipe loading and the comprehensive cumulative hard-rule review were not finished. The remaining review work is explicitly separated from defects; do not turn incompleteness into a speculative implementation mandate. Aggregate review and separate independent completion remain mandatory.

Only this report was written. No implementation changes, tests executed, staging, commit, nested agents, package changes, host changes or publication. `git diff --check` was run read-only and returned 0/no output. Receipt inspection is not a test rerun.

## Finite findings

### DC89-F01 — new default-composition test helper patches internal construction

**Severity: Medium, mandatory-rule blocker.** `tests/cli/test_app.py:20–40`, especially37, replaces `SloAgentSession.build` using `patch(..., return_value=session)`. The new wiring test repeats this at approximately78. This helper supplies all six visual cells, twelve liveness cells, the failure matrix and prerequisite journeys. They do exercise the real constructed TUI and real injected session/SQLite after capture, so their outcomes are valuable; however, this is not constructor/factory/parameter injection of the internal session acquisition collaborator.

**Source:** installed `coding/test-verification-policy` Test doubles/Core Rule and Python `code-review-rules` §1.5 require internal collaborators to be passed through a real seam, not patched. DC09 §8 requires real mounted default-path journeys; the real root journey in this file is complementary but does not waive this mandatory convention for the other newly authored tests. Historical patch-heavy CLI tests are not a blanket exception for new helpers.

**Correction/closure:** replace the newly added session-build patch with a small typed injection seam at the existing composition owner, or another convention-compliant way to mount the genuinely default-composed host. Preserve production defaults and all fresh/resume/private-restore flag assertions, actual unmodified-session root journeys, all18 matrix cells, all failure cells and persisted forbidden-effect assertions. Capturing native terminal launch is a distinct test boundary; do not launch real terminals to remove a patch. Rerun affected/default matrices, wiring, full required gates and independent affected review. No new framework or public configuration is required.

### DC89-F02 — changed dispatcher recorder signatures remain untyped

**Severity: Medium, mandatory-rule blocker.** `tests/cli/test_typer_dispatch.py` changed `_capture_runner` definitions around386,410,438,469,501,532,580,640 add `messaging_enabled` but still omit explicit parameter and return types. Several surrounding captured containers remain bare `list`.

**Source:** README Style rules; installed `languages/python/named-arguments-and-type-hints` §§2/4 and full hard checklist §1.1. These apply to tests and revised signatures too. Mypy980 passing does not enforce annotation completeness with the current config.

**Correction/closure:** annotate these eight changed recorder signatures and their directly associated configuration collections using actual configuration/runner-double types; preserve the new true-flag checks and existing config/reasoning/resume assertions. Do not convert unrelated legacy tests. Scoped static and CLI behavior checks plus final required gates must remain green.

No independently demonstrated data-loss/security/runtime defect is asserted by these findings. No optional cleanup recommendations or new product scope are added.

## DC08 original acceptance rows — independent source/assertion disposition

Paths below use `src/agents/slo_agent/` as the agent prefix. All named feature tests were read, not merely found by name. PASS means the inspected behavior and current execution receipt support the row; it is not whole-feature acceptance or a waiver of findings.

| Original row | Production source and actual assertions | Disposition |
|---|---|---|
| A1 | `tui/app.py::_handle_inbox_message` advances the workflow handle before rechecking binding, routes ui_notice unchanged, then maps chat/context/transcript to machine admission. `sessions/service.py:1891–2000` issues stable `legacy:<source>:<session>` clients and restricts metadata/normal priority. `test_legacy_inbox_bridge.py::test_claim_admits_original_identity_and_acks_after_receipt` proves real done files, original UUID/source/normal text payload, scheduler/workflow sender kinds, two provider requests total, completed workflow handle, machine widgets, and human-only echo/recall. | PASS with precise boundary: scheduler note is delivered while idle (zero provider), workflow terminal while provider held. Busy-note behavior is supported by the same gate/admission branch, not a separately asserted busy-note cell. Handle advancement is durable final-state proof plus one source call, not a spy counter. Producers are unchanged. |
| A2 | Bridge unknown outcome performs exactly one client receipt lookup; held claims are reverified as recovered, never resubmitted. `test_response_loss_retries_same_id_then_acks` holds real persistence past both .02s deadlines, keeps claim, releases, repolls, proves one identity, one provider request, applied receipt and application event. | PASS. |
| A3 | `_ack_verified_inbox_claim` catches OSError or false ack, retains bounded DAO; next poll calls verification. `test_ack_failure_repeats_verification_not_execution[False/True]` proves two ack calls, one identity, no provider, cleared retry map and done file. | PASS. Fault scope is OSError/False, not arbitrary programmer exceptions. |
| A4 | `queue.py:359–404` serializes verification, reads original identity, checks sender and rebuilds submission with `identity.receipt.target`; store verifies immutable digest through `_duplicate_outcome`. Restart test `[None]` actually prunes messages to zero with maintain(+9days), remounts changed generation and acks; `[retained]` proves accepted retained receipt ack without running it. | PASS. Original target remains in returned receipt; no current-generation retarget. |
| A5 | Same restart test `[text/kind/source]` edits real claimed JSON and retains claim with unchanged identity count/no provider. Session test separately proves changed text/kind conflict and foreign workflow/scheduler sender unauthorized. | PASS. Source-class edit correctly gets unauthorized rather than claiming all source edits produce conflict. |
| A6 | Restart `[unknown]` leaves unknown claim and zero identities/provider; malformed startup scan processes20 claims with one corrupt file,19 investigation notices, no done files or identities. | PASS; no republish or move-to-pending. |
| A7 | Registration requires owner object identity; verification requires exact registered client identity. Reader authorizes registered machine principal by identity. `test_forged_capabilities_are_unauthorized` checks copied owner/client/decoded principal, idempotent registration, owner-only recovery/observation and post-close revocation. `test_machine_clients_close_before_session_and_successor_rejects_old_client` probes completing on every client before real close and refuses old client in successor. | PASS. General owner-reader equality is existing behavior; new machine registration/verification uses `is` as required. |
| A8 | Store `_duplicate_outcome` checks principal before digest. Real-store precedence test checks foreign sender unauthorized, changed bytes conflict, unknown not_found and invalid source correlation. `verify_admission` performs no write/wake. | PASS. |
| A9 | Inbox store `read_claimed:103–159` validates integer/nonbool1..16 and canonical cursor before lock/I/O; selects canonical filename UUIDs, sorts, reads only selected content, returns valid prefix or typed safe cursor. Actual test proves16+4, invalid types/cursors, invalid UTF8, mismatched UUID, resumed page and zero done files. | PASS. Bound applies to returned/content-read page, not directory enumeration. |
| A10 | `_admit_legacy_inbox_message:1906–1912` refuses noncanonical UUID before DAO/admission. Mounted test proves original claimed file, no pending/done, no replacement identity and no provider. DAO cases reject blank/oversize/surrogate/authority fields. | PASS; notice text checked in source, not explicitly asserted by that particular test. |
| A11 | Nonmessaging branch retains idle task gate/direct legacy routing. `test_herdr_inbox_disposition.py` and `test_herdr_inbox_cutoffs.py` are unchanged; complete gate includes them. The28-case all-owner regression retains original byte/ack/registered-task/lease/reporting assertions. | Regression receipt PASS; original two legacy files were not exhaustively reread in this dispatch. Do not claim an independent line-by-line acceptance of their entire matrix. |

### §5.6 same-gateway displacement

`app.py::_activate_session_messaging` registers both clients, replaces prompt binding, starts owned observation then awaits `_scan_recovered_inbox_claims`. The scan captures session/store/lease-store/owner ID and checks them before paging, after malformed-read await, before each verification and after successful verification before ack. `_admit_legacy_inbox_message` also rechecks selected session/delivery eligibility after verification. `_ack_verified_inbox_claim` independently requires captured session/store/current delivery.

Read all of `tests/tui/test_inbox_displacement.py`: both `[page,verification]` start with a real applied identity and failed ack, hold actual page or successful verified identity, invoke real `/new`, wait for successor activation and old close, then release. Assertions require no added ack, exact original claimed DAO, unchanged successor transcript, empty successor identities and zero provider calls. **This proves the exact scan gateway used by activation at a mounted displacement boundary, not initial-mount concurrency.** That distinction is acceptable for the stated same-gateway requirement; no invented initial-mount Cartesian matrix is demanded. The separate held-page shutdown case is complementary but manually sets the cutoff flag, not native unmount proof.

Machine-verification storage damage is also real: DROP identity in contained SQLite, poll, retain claim, paint storage_unavailable and refuse next admission. Ack retry retains the captured DAO rather than rereading a concurrently edited file; no claim of concurrent external-editor safety is made or required as a new optional scope.

## DC09 original acceptance rows

| Row | Source/assertions inspected | Independent disposition |
|---|---|---|
| A1 | Entire `test_composer_visual_matrix.py`; themes slo-dark/slo-default ×60×20/80×24/120×40, explicit legacy versus default-composed host. Exact region tuple equality, mounted focus, multiline bracket recall, Ctrl+Enter newline, band region and one-cell baseline gap. Recall seeded through public accepted-prompt command; actual application recall belongs to DC03. | Behavior supported for all6 cells; convention closure DC89-F01 required. |
| A2 | Same file, both provider/admission held ×6 cells.20 keys each assert exact prefix, press/pause bounded2s, holds remain unreleased, release yields one exact HumanMessage, newer draft survives, no legacy task/slot. | Behavior supported for all12 cells; DC89-F01 required. Native wall-clock animation timing is a separate regression, not a substitute for these liveness checks. |
| A3 | Entire failure matrix plus prerequisite file: corrupt/owned startup retains draft/no client/provider; urgent and ui_notice unsupported original ID, receipt not_found and no identity/provider; machine recovery unauthorized; ephemeral receipt durableFalse/no database; real poststart dropped-table refusal and observation notice; queue/sender limits ×newer/unchanged draft preserve/restore and read back only two applied inputs. Ctrl+Enter asserted in every geometry cell. | Required cells present, current full suite green; DC89-F01 required. Machine-recovery cell uses an unauthorized machine principal; registered machine capability refusal is independently asserted by DC08 test. |
| A4 | `typer_dispatch.py` diff is exactly true flags at115,134,320; constructors remain false. Actual fresh/resume/private-restore wiring tests and real interactive/headless root journeys prove applied identity/history/provider/terminal. `_register_prompt_task`/`_queue_prompt` invariant tests refuse without scheduling. | Functional wiring PASS; test-policy and changed-recorder typing findings block convention acceptance. |
| A5 | `service.py::has_messaging_store` presence-only/no open; TUI ordinary non-slash guard before clear; headless legacy guard before start/drain. Mounted corrupt-file rollback keeps draft/no events/task; real headless empty-file rollback emits exact run_failed, exit1, zero model requests. README states older binaries cannot enforce guard. | PASS for specified ordinary-execution guard. Not a universal old-binary safety guarantee. |
| A6 | Exact full non-e2e receipt and static/integrity below. Previous failed/aborted receipts not hidden. | Execution gate PASS as recorded; aggregate prerequisite acceptance, full hard-rule audit and separate completion remain open. Counts alone cannot accept DC01–07 or waive findings. |

Generic local clients retain normal+urgent defaults. The TUI-issued client explicitly binds normal-only before admission; target/closed error precedence remains. Session machine clients separately restrict priority. This addresses the documented default-host failure row without deleting existing low-level urgent ordering or implementing urgent interruption. No config/environment/schema change appears in this cutover.

## Three synchronization corrections — source trace and oracle assessment

1. **Overflow/hydration:** current `test_composer_transcript_identity.py:393–482` still publishes two257-event batches, waits every receipt applied, then requires exact514-ID set, no conflicts, live observation and no unavailable notice. `ChatTranscriptComponent.hydrate:1120` owns `_hydration_lock` through `_present_history_tail`; latter sets `_hydrated` before awaited mounts and publishes cursor afterward. Public HydrateTranscriptDAO joins the lock before paging. App observer subscribes before barrier replay and retries replay_gap. This corrects a started-versus-finished oracle; no identity assertion relaxed.
2. **Native animation:** complete precise-scroll file and actual Textual SimpleAnimation implementation inspected, plus component `_start_native_navigation`/`_native_navigation_completed:879–957`. Real animations are created; only timer ticks pause synchronously with released starts. Test asserts shorter x duration, computes x completion, evaluates real x/y objects (true/false), invokes actual completion callback, and still requires x1/intermediate y/pending_axes{'y'}. Both cover callback orders, duplicates, final retired navigation and painted row after growth remain. Production completion discards only axes at their clamped targets, then settles once. This is controlled native timing, not arbitrary scheduler-fairness proof; the separate every-compositor-frame test still observes real ongoing motion. No weakened numeric/paint oracle found.
3. **Herdr prepare/shutdown:** actual `prepare_startup:2515–2568` serializes duplicate callers, derives capabilities and commits ready without suspension at adoption. `/new` starts tracked preparation asynchronously; shutdown joins/cancels that owner (`app.py:626–680`). Added public prepare+ready precedes arming shutdown in the28-case legacy resource fixture. Original registered Faux streaming gate, abort, task join, original-store bytes/ack, no displaced writes, current/retired reporter cleanup, lease/timer and persistent cancellation assertions remain. This is a valid scenario precondition, not fabricated readiness or a production change. Historical private-patch harness is unchanged; it is not a model for new test seams.

## Prior repairs relevant to evidence

- FR01 current adapter pins loop, checks closed then type. Current public-lifetime test checks unsupported-open, supported/unsupported-closed and foreign-loop cases without reopening private flags.
- FR02 callback observes exception and discards Task, retains sticky first error; reset/close snapshot and join siblings before propagating. Read200-completion success/failure test, traceback bound, repeated close, no borrower close and held sibling through repeated cancellation. These directly address old unbounded bookkeeping.
- FR03 current `_rebind_scripted_client` uses public replacement and asserts predecessor borrower release. This closes the old specific helper defect, but does not authorize the distinct new DC89-F01 patch.
- Dispatch14 ownership diff opens existing ancestors no-follow before mkdir; preserves descriptor-relative final validation, not a weakened sandbox. Managed recorder forwards/asserts true flag. Refusal production path only handles pre-agent/no-delivery ValueError, pauses and retains before waking unassigned observers; post-agent ValueError still settles assigned observers then raises. Two-process restore now asserts applied-only visible prompts **plus exact retained refused input**, paused and healthy store, unchanged history and zero model calls. This is stronger than merely removing optimistic echo.
- Navigation regression adds settled initial pin and exact saved_y40; old final clamp/no-bottom paint remains. Atomic registration AST adds exact invariant and retains original atomic tail/no await. No timeout widening or removed outcome assertion found in these diffs.

## Exact gate and warning audit

All receipt paths below are under `release-evidence/96-durable-composer/logs/`. Commands, matching `.exit`, log headers/tails and relevant full warning section were independently inspected. Cwd is this app root; receipt header proves Python3.11.7/pytest9.0.3/xdist3.8.0/six workers. Current Makefile uses test-env fallback and `pytest -n $(PYTEST_WORKERS) -m "not e2e"`; manifest and Makefile are unchanged. No test execution by this reviewer.

| Receipt stem | Exact command/result disposition |
|---|---|
| turn2-d3-repeat-1/2/3 | `poetry run pytest tests/tui/test_composer_transcript_identity.py tests/tui/test_chat_transcript_precise_scroll.py tests/tui/test_herdr_all_owner_cutoffs.py -n 6 -m 'not e2e' -q`; each exit0,47passed40warnings;54.50/54.47/54.15s. Complete files, not selected nodes. |
| turn2-d3-affected | `poetry run pytest tests/tui/ tests/agents/slo_agent/messaging/ -n 6 -m 'not e2e' -q`; exit0,3383passed538warnings258.96s. |
| turn2-d3-final-focused | Same three complete files after formatting; exit0,47passed40warnings52.07s. |
| turn2-d3-final-full | **`make test PYTEST_WORKERS=6`; exit0;12269passed1267warnings627.91s**, six workers12269items. Started09:08:22Z, finished09:18:52Z November3. No execution skips/failures reported. |
| turn2-d3-final-lint | `poetry run mypy src/ tests/` via make lint; exit0,980files. |
| turn2-d3-black / black-final | Initial failure explicitly retained: precise-scroll would reformat,58others unchanged. Final exit0,59unchanged. Inventory matches current changed/untracked Python path **set**; sorting order differs only due locale. |
| turn2-d3-collection | `poetry run pytest --collect-only -m 'not e2e' -q`; exit0,12269/12290,21deselected. Collection is not execution. |
| turn2-d3-final-diff / final-coreutils | Each exit0/empty log. These corroborate recorded `git diff --check` and `dpkg -V coreutils`, not a newly executed coreutils verification. |
| turn2-d3-test-env | exit0, fallback. |
| turn2-d2-full | **exit141; log ends83%, no terminal summary. Interrupted, NOT PASS.** Finished marker cannot override this. |

**Current-source relation:** HEAD unchanged; current tracked/untracked Python set matches Black59; no src/tests Python file has an mtime later than final-full.started; precise-scroll mtime09:04:58Z precedes final run. Current cumulative precise-scroll+Herdr diff is byte-identical to `turn2-d3-final-reviewed-test-diff.log` (cmp0). This supports receipt reuse, but no cryptographic full-source snapshot was supplied; timestamps are corroboration, not immutable provenance. No requirement to invent a new provenance platform.

**21 exclusions:** unchanged Make/manifest marker policy and unchanged e2e paths, plus exact collection total corroborate the21 project e2e deselections. No additional `-k`, file filter or skip appeared in final command. This dispatch did not independently enumerate all21 node identities; do not claim an exact node-by-node exclusion audit. No new exclusion is approved.

**Warnings, not a warning-free gate:** full warning section has (a) pythonjsonlogger moved-module DeprecationWarning; (b) LangGraph allowed_objects pending deprecation; (c) LangGraph instance model_fields Pydantic deprecation across old and new tests; (d) provider parameter placement UserWarnings for include/extra_body/temperature/top_p/tools/tool_choice/parallel_tool_calls in unchanged agents/base.py; (e) four unawaited AsyncMock RuntimeWarnings attributed at garbage-collection sites in CLI dispatch/update and TUI queued-prompt tests. The same AsyncMock warning family exists in dispatch14 full receipt, but the final log does not identify allocation origin and the initial focused baseline does not prove all such warnings predate this feature. Thus the report's broad historical/pre-existing characterization is **not fully established**. Passing status is real under unchanged warning policy; warning count is not a failure count, nor permission to assert harmlessness. No suppression, package upgrade or broad warning cleanup is requested. Allocation-level origin/new-regression assessment remains an aggregate review evidence limitation.

## Hard-rule pass — scoped results, not blanket certification

Full installed Python hard checklist read (all1107lines in two bounded reads). Shared routing/testing/ownership/review and feature-review procedure read; exact workflow/shared workflow read (initial oversized read was followed by recovery of its omitted beginning). Generic solution-design, coding-rules, naming, test policy and declarative owner; Python root, named arguments, docstrings and declarative specialization; Textual build recipe were read. Relevant README runtime/testing/maintainer sections, current SLO, Makefile/manifest, KB entry→slo README/gotchas/conventions/runtime and environment portions, and supported MEMORY consulted. Routing/handoff/ledger, both previous final reviews, dispatch10/11/12/14 and d3 report read.

Remaining instruction-load limitation: full applicable application/domain/test recipe examples, installed index, operational-reference, remaining requested KB detail and remaining README portions were not fully consumed. Partial recipe reads are not credited as full reads. No RESEARCH was created (absent, explicit task write boundary).

| Hard-rule area | Result |
|---|---|
| §1.1 types/named args | FAIL at bounded changed recorder signatures DC89-F02. New capability/verification interfaces explicitly typed; no blanket pass over all59 files. |
| §1.2 docstrings | New public registration/verification/paging/presence contracts document outcomes/errors. Remaining whole-diff pass open. |
| §1.3 declarative / Tell Don't Ask | Persistence digest belongs to store, authority to session, mutex to queue, claim/ack/lifecycle to host per explicit DC08 ownership. Do not mechanically move specified host responsibilities or split solely by line count. Long bridge orchestration merits remaining cohesion pass; no ungrounded new refactor blocker asserted. |
| §1.4 canonical vocabulary | UUID/message_id/source_event_id/principal/target/receipt/digest flow consistently in reviewed boundary. |
| §1.5 evidence/doubles | Real Inbox/SQLite and injected timing/provider stubs are substantial. FAIL DC89-F01 for newly patched internal acquisition. Historical unchanged patch harness distinguished, not broadly rewritten. No new skips/xfails found in inspected files. |
| §2 backend / §3 Vue | FastAPI/ORM/DBOS/Vue absent from changed layer; not imposed. Existing SQLite schema/no migration retained. |
| §4 CLI | Root changes are construction flags only; no new CLI verb/env/Make mapping obligation. Helper typing/test seam findings remain. |
| §5 Textual | Existing components/typed commands/semantic styling retained; no feature TCSS change; runtime tasks explicitly owned. App bridge placement is specified, not independently grounds to demand a new framework. |
| §6 graph | No new graph/node topology in this partition; injection and sole consumer are owned by other partitions. No fabricated gateway migration requirement. |
| §§7–8 review/report | Original A rows individually mapped; finite defects/closure and limitations stated. Overall post-hook on the complete cumulative diff is still open. |

## Safe later commit inventory — NO staging/commit

The mechanically reconciled **59 Python paths** are exactly `logs/turn2-d3-black-paths.txt` (24 production,35 tests/helpers); this is the precise later candidate path manifest, not authorization to stage. It includes tracked and untracked files: especially the prompt adapter package/submission DAO and all new feature tests. Do not use tracked-only diff or `git add -u` as a complete inventory. New reports from parallel reviewers are evidence artifacts, not source acceptance.

- Candidate feature README hunk: sole current hunk at1678 adds durable runtime chain, `/messages`, normal-only host capability, default flags and upgrade/rollback rules; qualifies following queued-prompt description as legacy. This is explicitly DC09 scope. Recheck hunk before later selection; do not stage README wholesale if concurrent edits appear.
- Preserve **SLO.md** unrelated workflow-limit edit (8/6 removed); exclude from feature commit unless separately authorized.
- Preserve **docs/** preexisting untracked user data; exclude entirely; no inspection/edit/deletion/staging performed.
- `release-evidence/96-durable-composer/` contains task-local reports/logs, not an implicit release or blanket commit payload. Later operator must choose evidence scope explicitly; do not stage all untracked files.
- Makefile, pyproject/lock, Inbox producers/workflow application service and e2e policy are unchanged; no package/schema/host artifacts belong in this commit.
- Source assertions were inspected by partition and regression relevance, not all59 complete bodies. Candidate manifest is inventory, not whole-feature approval.

## Exact remaining audit / closure checklist

- [ ] Resolve DC89-F01 and DC89-F02 through bounded implementation/test/review, preserving all current outcomes; this reviewer made no edits.
- [ ] Finish applicable instruction/recipe reads and complete cumulative convention pass; aggregate with DC01–07 partitions rather than pretending this partition accepts them.
- [ ] Reconcile legacy A11 matrix source completely, exact21 deselected node inventory, and AsyncMock allocation-origin/regression disposition; existing passing receipts are not invalidated merely by this remaining audit.
- [ ] Aggregate review must reconcile DC08.A1's complementary idle-note/busy-terminal evidence explicitly; no fabricated busy-note test is claimed here.
- [ ] Separate independent completion only after aggregate accepted review and current gates.
- [ ] Later commit only with authorization and fresh scoped inventory; no stage/commit occurred.

Durable milestone: original DC08/09 source contracts mapped to real assertions, key security/restart/displacement/default guards traced, all named final receipt totals verified, three synchronization corrections causally assessed, prior repair oracle changes checked, and safe source/README versus SLO/docs inventory separated. This is **REVISE / incomplete final acceptance**, not FAILED execution, not an invented budget exhaustion, and not a completed workflow turn.
