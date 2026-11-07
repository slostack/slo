# Independent final review — turn 2 dispatch 4

## Verdict: INCOMPLETE — not acceptance

This review did **not** complete the entire original DC01–DC09 audit or the mandatory hard-rules post-hook. Do not advance to completion or a local commit. This is an independent review attempt, not implementation. No new production defect is established by this partial inspection; lack of a finding is not READY.

Authority: original specifications only at `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/revised/01-durable-composer/`. Historical `final-review.md` is preserved. No source/test changes, staging, commits, publication, agents, workflow launch, package or host modifications. Only this report was written.

Counters carried unchanged: turn 1 partial 15 dispatches; turn 2 dispatch 4/20; 2 started / 0 completed, maximum 60 turns; zero retries. Earlier dispatch 2 aborted and was not retried. No invented workflow budget or watchdog exhaustion is asserted. The limitation is incomplete review execution, not failed tests or an unavailable environment.

## Inspected boundaries and concrete observations

### FR-01 — closed-wins repair present; focused source/assertions inspected

Read the complete current `src/tui/components/prompt_input/adapters/message_submission.py` and `tests/tui/test_durable_composer.py::test_submission_adapter_rejects_bad_input_loop_and_closed`.

`handle` now pins the loop, rejects closed delivery, then validates input type. The test registers genuine adapter lifetimes, checks unsupported-open TypeError, supported/unsupported-closed RuntimeError, and supported/unsupported foreign-loop refusal before and after public close. It does not reopen private state. This addresses the concrete historical closed-versus-type finding. This dispatch did not independently execute the test or complete all DC02 interface checks.

### FR-02 / EF-02 — bounded observed tasks and sibling joins present

`_observe_completed_wait` retrieves each noncancelled task's exception, removes the task from `_tasks`, and keeps only the first failure, initially without its traceback. `_start_wait_task` drains already-done entries and handles eager completion; reset/close capture and join outstanding siblings. `_join_wait_tasks` does not escape immediately when a shielded sibling raises. Shared close releases borrowed references in `finally` and never closes the borrowed client.

Inspected these exact tests and assertions:

- `test_submission_adapter_repeated_completions_release_tasks_and_bound_failures`: 100 completions with resets plus 100 without lifecycle calls, success/failure parametrization, empty task ownership, sticky exception identity, bounded traceback depth, repeated close, released borrowers, zero client closes, exactly 200 deliveries.
- `test_submission_adapter_retired_failure_still_joins_held_sibling`: both reset and close remain pending through three cancellations until the held sibling settles; sticky failure is then raised, both deliveries recorded, borrowers released by close.
- `test_submission_adapter_joins_held_sibling_after_in_progress_receiver_fails`: concurrent closes stay pending after first failure and retain borrowers until the other wait settles; both callers receive failure.

These directly address the historical retained-Task defect and important EF-02 failure/cancellation boundaries. They are materially stronger than merely counting successful submissions. Full lifecycle integration and the complete hard-rule disposition remain unfinished.

### FR-03 — inspected injection helper repaired

`tests/tui/test_durable_composer.py::_rebind_scripted_client` now awaits `prompt.replace_submission_binding(client=..., address=...)`, asserts a fresh adapter, and asserts predecessor borrower release. Reading private fields to assert identity/resource lifetime is not the former private collaborator replacement. The isolated loop test uses `register`, not private reopening. The entire file and every helper caller were **not** exhaustively read in this dispatch; do not convert this focused confirmation into a complete test-policy audit.

### Three regression corrections

**Overflow:** inspected `test_composer_transcript_identity.py::test_overflow_raises_replay_gap_and_host_rebuilds` and the real `ChatTranscriptComponent.hydrate` / `_present_history_tail` methods (component.py approximately1120–1183). `_hydrated` is set before awaited projection and cursor publication; the new public `HydrateTranscriptDAO` call acquires the same hydration lock held through presentation. It therefore joins completion rather than just observing an early flag. Both257-event batches, applied-receipt checks, exact514-ID set, empty conflict set, live observation task and no-unavailable-notice assertions remain. The change is causally connected to the incomplete-ID oracle; it is not an identity fabrication or relaxed assertion. Complete DC03 replay/observer production trace remains outstanding.

**Unequal-axis scroll:** read all of `tests/tui/test_chat_transcript_precise_scroll.py` and its cumulative diff. The correction pauses the real Textual animator timer after actual start callbacks, obtains actual registered `SimpleAnimation` objects, asserts x duration is shorter, evaluates both at x completion, invokes x's real completion callback, and preserves x==1 / intermediate-y / pending_axes=={'y'}. It resumes the real timer and retains both covering-callback orders, duplicate callback checks, final navigation retirement and painted-row stability after growth. This is framework-internal timing instrumentation, not an application collaborator swap. It is a deterministic callback-order proof, **not** evidence of arbitrary wall-clock timing. The separate compositor-frame test remains present. Textual implementation and the full navigation-owner trace were not independently audited here, so final adequacy remains open.

**Herdr:** the cumulative diff adds public `current.prepare_startup()` and a ready assertion after actual successor selection, before shutdown owners are armed. This does not fabricate readiness. The entire28-case harness and preparation/shutdown production trace were not inspected, so the author's causal explanation and preserved-oracle claim are not independently closed in full.

### DC07 A4 / A8 complementary evidence

Read original DC07 in full; read all of `test_finite_completion.py` and `test_headless_messaging.py`, the complete headless cumulative diff, and session finite/stop/close code at approximately2194–2440.

- **A4:** the named test actually advances settlement revision by admission while finish waits for execution ownership; it does not inject a terminal into a literal check-to-wait gap. In production `_wait_for_finite_cutoff` captures revision/event before awaited checks and compares revision after releasing locks. There is no suspension between equality and entering Event.wait. The complementary rationale is credible for lost-wakeup safety; test naming alone is not proof of the exact named interleaving. Scheduler notification sites and queue implementation remain to be fully traced before accepting A4.
- **A8:** actual HeadlessRunner test leaves the provider unreleased, requests cooperative abort, requires exit2 and reads applied initial/retained pending SQLite rows. Session hard-stop test independently requires scheduler cancellation, completed consumers and observer `run_aborted`. Prepared-application test creates a genuine claimed/prepared journal through queue/store operations, invokes the same public stop owner, and requires applied identity plus exactly one matching history event. Production headless escalation delegates to `stop_messaging_execution`; that owner cancels/joins consumers and reconciles under execution/history ownership. These are complementary assertions, not one combined runner/crash-window experiment. No need for an artificial second prepared journal inside a provider-held run has been established. Reconciliation internals, all lock/wake paths and complete runner lifecycle remain unreviewed; A8 is not finally accepted here.

### DC08 §5.6 same-gateway displacement

Read original §5.6/A-row table, complete `tests/tui/test_inbox_displacement.py`, and `app.py::_scan_recovered_inbox_claims`, `_is_inbox_scan_current`, `_admit_legacy_inbox_message` (approximately1821–1963).

The test calls the same scan method used by activation, after mounting. It uses real prior admission/application and failed ack, then holds either actual claimed-page return or actual successful verification return. Actual `/new` adopts a successor before the old await is released. It asserts no extra ack, original claim retained, no successor identities, unchanged successor transcript lines, and no provider requests. The scan captures session/store/lease/owner and rechecks current binding after page/verification awaits; successor is not substituted into the old operation. This supports the requested displacement boundary; it is not an initial-mount concurrency test. Full activation wiring, ack owner, authorization/digest/pruning and all A1–A11 remain unaudited.

## Evidence receipts inspected, not rerun

- `logs/turn2-d3-final-full.command`: exact `make test PYTEST_WORKERS=6`.
- `logs/turn2-d3-final-full.log`: header identifies Python3.11.7, pytest9.0.3, project config/root and six workers/12269 items; final summary **12269 passed,1267 warnings,627.91s**. Matching `.exit` is0.
- `logs/turn2-d3-final-focused.command`: complete three regression files, `-n 6 -m 'not e2e' -q`; terminal summary **47passed,40warnings,52.07s**. Its exit receipt was not separately read here.
- `logs/turn2-d3-final-lint.log` and `.exit`: `poetry run mypy src/ tests/`, **980 source files clean**, exit0.
- Ran `git diff --check`: exit0/no output. This does not validate untracked file formatting.

No pytest or application probe executed by this reviewer. No ceremonial full-suite rerun. Repeated47-pass, affected3383-pass, cumulative Black59, collection21 deselections and coreutils receipts were read as author report claims but not independently opened/reconciled in this dispatch. Historical d2 exit141/83% must not be represented as passing. Warnings are not waived; their complete categories/source relationships remain to inspect. Receipt contents support execution history, not every acceptance assertion or immutable source provenance.

## Original acceptance reconciliation — exact remaining scope

No original row is accepted by this partial report. This table records review progress rather than silently replacing the original A rows with broader summaries.

| Original rows | This dispatch's independent boundary | Remaining before disposition |
|---|---|---|
| DC01.A1–A8 | No complete source/row audit | Full spec, activation/binding/preparation/reporting/refusal/ephemeral/cleanup/legacy entry journeys and EF01 closure |
| DC02.A1–A12 | Spec lines1–260; complete adapter; selected FR/lifecycle tests | Remaining spec; component/host atomic capture, all caps/revisions/retries/static typing/slash/sealing; whole test file and FR03 callers |
| DC03.A1–A11 | Overflow test and hydration join inspected | Original spec, session observation, verified history/hash, flat/tree replay, recall, machine styling, compaction, run presentation; EF05 |
| DC04.A1–A8 | Adapter join primitives only | Original spec; component retirement/replacement/unmount, app acknowledgement/handoff/caps, borrower lifetime, exit warning; EF03/04 |
| DC05.A1–A9 | Not audited | Full consent/expiry/forgery/revalidation/atomic continue/cancel/replay and mounted slash journeys |
| DC06.A1–A7 | `/new` observed through displacement test only | Full abort/resume/clear/new/Ctrl+C implementation, persistence and refusal evidence |
| DC07.A1–A11 | Full spec and two test files; finite/stop source subsection and headless diff | Queue/store cutoff and applying count, scheduler/notes/notification and reconciliation trace; remaining surrounding headless code, steer, legacy evidence; final A4/A8 disposition |
| DC08.A1–A11 + §5.6 | §5.6 same-gateway page/verification displacement source and test | Full spec and capability/source/digest/original-target verification, pruning/restart, ack/policy, bounded malformed paging and legacy matrix |
| DC09.A1–A6 | README feature hunk; selected regression changes and full-gate receipt | Full spec, default roots/guards/rollback and theme×size/failure/liveness matrices; complete regression assertion audit |

## Mandatory rules and instruction-loading disposition

Read current repository SLO.md in full, README opening1–200 and heading inventory, acceptance-routing, historical final review, early review, turn2 repair, turn2-d3 continuation and dispatch12 report. Checked common ancestor instruction paths; command produced no ancestor file contents. Read review-feature-code in full and engineering-review. Python hard checklist was split across reads: initial combined output truncated its beginning; subsequently read lines1–500, while the previous retained output supplied later sections. **No completed hard-rule pass against the cumulative diff is claimed.**

Some combined KB/report reads exceeded output limits. KB entry/README/gotchas were requested but cannot be credited as complete untruncated reads. Remaining applicable README runtime/ownership/testing/maintainer sections, KB routing, installed INDEX/exact/shared workflow, engineering routing/testing/ownership, generic design/style/test guidance and scoped Python/Textual/build recipes remain to load fully. Makefile/pyproject rules and nested instructions also remain to inspect. Do not rely on the author's routing summary as a substitute.

No applicable mandatory style violation is waived. Declarative decomposition/Tell Don't Ask, keyword/type/docstring rules, layer ownership, test-first history, collaborator injection, simple behavioral tests and no regressions must still be checked on the whole diff. No optional cleanup blocker is invented. HTTP/ORM/Vue/DBOS obligations should not be imposed on this SQLite/Textual change merely because the checklist includes those stacks.

## Feature scope for a later local commit — not staged

The inspected `git diff -- README.md` has one hunk: the durable-composer runtime/commands/priority/rollback paragraph inserted near1678 and the following queued-prompt heading qualified as legacy. This matches the feature's documented scope and is mechanically separable from SLO.md and docs/. It is a **candidate feature hunk**, not an attestation of authorship or authorization to stage all README content. Recheck the live diff before any later commit. Preserve unrelated SLO.md edits and untracked user docs/.

## Durable handoff / next audit boundary

Continue this same independent final audit, not a new implementation cycle based solely on incompleteness. Start with the uncompleted instruction/skill/spec reads, then all unreviewed production/test changes including untracked submission records, adapter initializer and every acceptance test. Review cumulative `git diff` plus untracked contents; do not limit scope to the last repair. `implementation-handoff.md` and `continuation-ledger.md` remain unread this dispatch and must be read. Per-ID author evidence is navigation only.

Already useful independent work to reuse: complete adapter read; focused FR assertions; overflow hydration causality; full finite/headless test files; finite/stop/close subsection; headless diff; full displacement test and scan/verification host subsection; exact final-full and lint receipts; README hunk identification. Everything else remains open as mapped above.

### Completion checklist

- Must-fix code: no new confirmed defect from this partial inspection; historical FR repairs have focused confirmation, not whole-feature acceptance.
- Required review: all outstanding original rows, full cumulative source/test diff, EF01–05 reconciliation, mandatory hard-rules post-hook and warning/receipt reconciliation.
- Product decisions: none added or waived.
- Documentation: historical final-review.md preserved; this report records exact inspected/remaining boundaries.
- Separate independent completion: mandatory **only after** a complete READY review.
- Local commit: prohibited at this stage; no staging or commit performed.
