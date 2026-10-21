# T5 inbox handoff 92 — INCOMPLETE: viewer-owner closure not proved

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 92, retries 0. Effective turn and dispatch limits unlimited. No agents dispatched. No arbitrary unit/dispatch cap used.

## Scope and result

Changed only `tests/tui/test_herdr_inbox_disposition.py` and this report plus `t5-92-*` receipts. No production, other existing tests, canonical specs, shared status, KB, global configuration, system/PATH files or other worktree edits. No commit/push/PR/reset/clean/stash. No new retention module was needed. Parallel changes preserved.

24 mounted cases now pass (previously 20). The helper runs real config-backed SloAgentSession with LLMFactory patched to Faux, actual Textual app, actual temporary inbox/store/history, disabled Herdr and existing fake-capability/terminal guards. No live provider/Herdr/window operation or system symlink.

## Finite canonical mapping

Authority: canonical `94.b.2-session-publication-and-native-restore.md` C7.9 disposition ledger and C7.14 T3-F1. The requirement is not a four-mode × all-error Cartesian product.

| Canonical row | Actual owned test/evidence |
|---|---|
| empty | `test_inbox_delivery_disposition[empty]`: no file, invoke or ack |
| closed_entry | same named parameter: pending bytes unchanged, no invoke/ack |
| claim_error | same named parameter: OSError propagated, pending bytes unchanged |
| advance_error | same named parameter: OSError propagated, claimed bytes retained, no ack/invoke |
| handler_cancel | same named parameter: cancellation propagated, claimed bytes retained, no ack/invoke |
| chat_open | same named parameter: real Faux run once, real ack/done, output prefix |
| notice_open | same named parameter: real notice, no invoke, real done |
| note_open | same named parameter: real transcript note, no invoke, real done |
| context_open | same named parameter: real persistent context note, duplicate ID rejected, real done |
| context_pending_at_close | `test_context_pending_at_close`: barrier before actual history write, close prefix, write completes and original store acknowledges once |
| ack_false | same named disposition parameter: one admitted execution, claimed retained, no reclaim |
| ack_error | same named disposition parameter: one admitted execution, error propagated, claimed retained |
| ack_pending_at_close | `test_already_registered_ack_pending_at_close`: exact pre-cutoff registered task and captured ack identity; four combinations of store displacement and normal/operator abort |
| T3-F1 claim_pending | `test_durable_advance_then_shutdown[*-claim_pending]`: original claim held before filesystem call; public unmount prefix precedes release; workflow stays running, no invoke/ack |
| T3-F1 workflow_advance_pending | same test, named cutoff: actual running→completed handle commit before barrier; close refuses delivery; completed handle retained |
| T3-F1 before_chat_registration | same test, named cutoff: synchronous closing flag at actual notice seam, no artificial yield in registration; no registered task/invoke/ack |
| T3-F1 already_registered | `test_already_registered_ack_pending_at_close`: same registered task, no shutdown abort/cancel, one invoke and successful original ack/done |

All three refusal cutoffs now run with healthy AND throwing fixed-diagnostic sinks. All six remount a fresh app/session with the identical session ID/history root, poll with zero invoke, verify unchanged claimed bytes and unchanged durable events, then submit one explicit user prompt. Exactly that user message is persisted, no tool_call is recorded, and retained machine text never enters history. This is fresh-app restart evidence, not OS-process/native Herdr restore acceptance.

Navigation-history, user echo and queue spies assert non-entry for the base disposition matrix and all three refusal cutoffs. Registered abort now pauses an actual `text_delta` subscriber inside the real session invocation, requests `action_interrupt`, releases the barrier and verifies exactly one durable `run_aborted`; it is no longer a pre-coroutine abort substitute. Normal variants assert no aborted record. Both use the original Faux/session execution path.

## Cleanup coverage and exact remaining gap

The common mounted helper now spies on actual preparation cancellation, session reporting close, reporter close, transport close, unsubscribe, timer-stop helper, captured lease-release helper and final selected-session resource cleanup. Every owned case requires each to be attempted and public shutdown to finish within five seconds. Closing/quiescing remain true. Disabled fixtures explicitly assert no session Herdr viewer and no retired session.

**This is not yet every canonical cleanup owner.** Current `src/tui/app.py::_finish_app_shutdown` attempts preparation/reporting/delivery and selected/retired final drains, but has no `_cancel_visualizer_launches` call or tracked viewer-task registry. `_maybe_launch_visualizer` still calls the synchronous existing launcher. C7.9/C7.13 and exact T5 C26 require the app viewer cleanup owner independently. The present disabled/no-viewer fixture cannot prove that owner is attempted, and asserting its absence is not equivalent. Similarly, the helper proves the absent-retired branch, not an occupied retired owner per cutoff. Those remain precise missing evidence for the requested all-owner finite family; READY is withheld rather than treating no deadlock as proof. Production changes are forbidden in this lane and were not attempted. No behavioral RED is claimed from source inspection alone.

Remaining follow-up: compose the four named cutoffs with the actual tracked viewer owner once the parallel source owner provides it, and a genuine retained-session owner; assert their independent cleanup calls alongside the existing spies. This is a finite ownership closure, not permission to expand to arbitrary errors or edit the parallel source lane.

## Executed checks and failure classification

CWD `/root/Code/slo-94-herdr-integration/slo`. `check` means exactly `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`; reviewed helper supplies safe fallback environment, non-E2E selector and 62 DAO/projection checks. No new environment/venv installed.

| Receipt prefix | Command / result |
|---|---|
| t5-92-owners | `check tests/tui/test_herdr_inbox_disposition.py`: 82 passed, exit 0 |
| t5-92-cutoffs | same: 86 passed, exit 0 |
| t5-92-restart | same: 6 failed, 80 passed, exit 1; test bug: typed payload indexed as dict, `TypeError: 'SessionHistoryEventPayloadDAO' object is not subscriptable` |
| t5-92-restart-corrected | same after `.payload.content`: 86 passed, exit 0 |
| t5-92-abort | same: 2 failed, 84 passed, exit 1; test used history kind assistant_delta instead of live stream kind text_delta, barrier timed out |
| t5-92-abort-corrected | same after exact stream-kind correction: 86 passed, 15 warnings, exit 0 |
| t5-92-surrounding | `check tests/tui/test_herdr_inbox_disposition.py tests/tui/test_herdr_inbox_cutoffs.py tests/tui/test_app.py tests/tui/test_workflow_receive_path.py tests/tui/workflows tests/scheduling`: **412 passed, 39 warnings, 184.26s, exit 0** |
| t5-92-format | `PYENV_VERSION=slo-harness poetry run black tests/tui/test_herdr_inbox_disposition.py`: exit 0 |
| t5-92-black | same with `--check`: exit 0 |
| t5-92-mypy | `PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent tests/tui/test_herdr_inbox_disposition.py`: success, one source file, exit 0; no ignores added |
| t5-92-diff | `git diff --check`: silent exit 0; untracked owned file separately read/formatted/typechecked |
| t5-92-coreutils | `dpkg -V coreutils`: zero bytes, exit 0 |

Each prefix has `.log` and `.exit`. The two failures were fixture errors, not production RED, and no assertion was relaxed. Full make/test/smoke/lint remains integration work as instructed; baseline 298 errors / 63 files remains unwaived and was not reverified. No full feature acceptance or independent review claimed.

## Actual read closure and limitations

Read actual AGENTS.md in 1–510/511–1013 chunks, CLAUDE.md, root RESEARCH.md, all docs/RESEARCH.md, scope-plan.md, scope-routing-assessment.md, frozen routing.md; Makefile and pyproject test/static declarations; approved check helper; relevant isolation/terminal/fake guard implementation. KB Welcome, actual slo/README index and gotchas read (slo/index.md does not exist).

Canonical C7.9 read 605–1189 and 1190–1364; C7.10–7.14 and section 8 through document end read 1364–2175. Exact C25/C26/C30 task attachments read at 3410–3588. Accepted independent-review-turn4 read in full, including its distinction between source-plus-prescribed probes and mounted acceptance. Other T5 attachments and additional accepted-review artifacts were NOT all reread here; do not treat this as full T5 prerequisite closure.

Loaded shared engineering routing/testing/ownership, coding-rules/code-test-loop, Python root, Faux testing recipe, Python and shared declarative owners, Textual, named-argument/type hints, method-docstrings, workflow SKILL. One combined read exceeded output bounds; the omitted Python-root section was reread separately. No full-family implementation review is implied. Current test scope is composed offline Python/asyncio/Textual/filesystem; no DB/HTTP/CLI verb or production architecture change.

Final verdict: **INCOMPLETE for the requested all-owner finite family; strengthened disposition, refusal/restart and actual-stream abort checks are green.**
