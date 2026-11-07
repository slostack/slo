# Dispatch 8 — DC06 session controls

**REVISE / bounded DC06 implementation milestone delivered; mandatory lint acceptance BLOCKED.** No independent acceptance, final review or completion is claimed. Whole Code+Test remains NOT READY. Production opt-in/default unchanged; DC07–09 untouched.

Branch `message-queue`, turn1 started1/completed0/partial1, dispatch8/20, zero retries, max60 turns. Requested assignments remain Code+Test gpt-6.1-sol/medium and review/completion gpt-6-astra/medium; no agents or nested workflows launched. No Git publication, package/host changes, external KB changes, SLO.md/docs edits or missing research/instruction recreation. All preexisting edits and receipts preserved.

## Authority, design and ownership

Read original **06-session-controls-abort-clear-new.md in full**, referenced 01/03/04/05 dependencies and overview lifecycle contracts, current implementation owners, project README/SLO/ancestor instructions, KB Welcome → slo README/gotchas and operational/in-process references, installed workflow/shared skills, shared engineering/generic/Python/Textual routing. Existing source-specific owners override generic architecture examples: no new service, queue, schema, router behavior or execution owner.

Plan followed: test real mounted abort/clear first → messaging-only host branches → test retirement/close/adoption and refusals → insert joined predecessor lifecycle operations → cancellation/cleanup failure assertions → affected suites/static checks. Session still owns reusable pause/resume/close unchanged; prompt component still owns joined retirement unchanged; app owns ordering and last authorized observed pending count. Legacy controls retain app-task escalation and queue clear.

Only production file changed this dispatch: `src/tui/app.py`:
- Messaging Ctrl+C uses `session.is_running`; idle exits through existing draft warning; running aborts cooperatively without escalation. Slash abort reuses unchanged router/session abort and renders last-observed pending hint, never reads storage.
- Messaging clear runs existing ClearTranscriptDAO without touching legacy slot or observed band. Binding identity/recall/drafts stay with existing owners.
- `/new` retires mounted input immediately after prepared-candidate/app-closing recheck and before predecessor revocation. DraftHandoffError discards candidate, gives fixed notice, preserves old binding.
- Existing committed replacement task transfers delivery/lease, then joins observation → owner client → old session messaging before reporter close/adoption. Cleanup failure disables replacement delivery safety but adoption continues; its notice is rendered **after** successor UI clear so it remains visible. Recovery selection cleared by existing close/adoption; run presentation/count reset before successor activation. Legacy Inbox clients do not exist yet (DC08 hook remains later).

New `tests/tui/test_messaging_session_controls.py` reuses RecordingModel/RealAgentFactory, ScriptedMessagingClient, existing mounted helper patterns and closed SQLite reader; all real history/SQLite paths under tmp_path. Test-local session gateway holds actual close rather than patching internals; model gate always releases before teardown, including failures. No harness expansion.

## DC06 A1–A7 evidence

| Row | Journey / decisive proof |
|---|---|
| A1 | `test_abort_pauses_and_keeps_pending[False]`: held real provider, two Enter receipts pending; slash abort hint; escalation probe remains zero; release produces run_aborted in real history, one provider call only, both receipts accepted/not-retained while mounted. Joined shutdown SQLite retains both, not cancels. Context note admission alone does not resume. |
| A2 | Same `[True]`: explicit next Enter resumes second/third/next; exact ordered IDs/text in real history, exact cumulative HumanMessage contexts (including the deliberately admitted context note), four provider requests, closed SQLite each agent input applied once/not-retained. Confirmed continue behavior reuses DC05 mounted tests in affected suite. |
| A3 | `test_clear_never_cancels_or_reechoes[/clear/ctrl+l]`: one applied/one pending, cleared user widgets, band text unchanged, recall unchanged, Ctrl+L newer draft preserved; replay exact applied event through public component route gives no second echo; pending later echoes/applies once. `test_clear_preserves_recoverable_drafts_and_abort_without_pending_is_quiet` proves recoverable snapshot/adapter remain and zero-pending hint absent. |
| A4 | `test_new_retires_binding_closes_old_and_never_redirects`: aborted/idle old owner with accepted pending plus recoverable draft; old observation done, adapter closed/references released, old owner client returns completing, session no longer ready; old DB pending retained=1, execution lease reacquired and released; Inbox lease old absent/new correct owner; host-held exact old-target snapshot, retry fixed refusal, successor new target accepts only fresh ID; joined successor DB exactly one fresh applied row, no old IDs. |
| A5 | `test_new_refused_while_running`: actual held provider, existing notice, no candidate construction or client/observation close, same ready old owner. |
| A6 | `test_new_refused_when_drafts_cannot_be_kept`: 16 host-held plus component draft, candidate discarded/reporting close joined, fixed refusal before old revocation, same usable adapter/session/client/observation; same-ID explicit not_found retry actually resubmits exact immutable submission through old binding (two recorded submits), no successor admission. |
| A7 | `test_ctrl_c_distinguishes_idle_and_running[False/True]`: actual pilot Ctrl+C; running pauses, pending accepted and one provider call, never escalation/exit; idle with unsent warns/remains open, second Ctrl+C closes resources. |

Additional lifecycle evidence: `test_new_joins_predecessor_cleanup_before_adopting[False/True]` holds injected real close gateway; verifies adapter → observation → client retirement already complete, old still selected and successor not activated until release. Repeated caller cancellation joins committed replacement; failure after actual close sets safety false, adoption still completes and fixed cleanup notice survives UI reset. These are assertion-only additions after initial implementation except the erased-notice defect, which failed then was fixed.

## Exact commands and receipts

Cwd `/root/Code/slo-message-queue/slo`. `make test-env` → fallback; `poetry run python -V` → Python3.11.7. Every pytest uses `set -o pipefail` and this prefix:

`SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH=$PWD`

Logs under `logs/`; pipelines tee logs (some tail terminal display only). No unlogged passing command inferred from shell success.

| Command after prefix for pytest | Result / receipt |
|---|---|
| `timeout 90 poetry run pytest tests/tui/test_messaging_session_controls.py -q` before control branches | exit1, **4 failed/6 warnings**, missing hint and removed band; dispatch8-controls-red-current.log. First `-xq` attempt timed out90 (exit124) because assertion failure entered joined teardown with held vendor; test cleanup corrected, not claimed behavioral RED. |
| Same after branches | exit0, **4 passed/11 warnings**, dispatch8-controls-green.log. |
| `timeout 90 poetry run pytest tests/tui/test_messaging_session_controls.py -k new -q` before replacement insertion | exit1, **2 failed/1 passed/6 deselected/4 warnings**; dispatch8-new-red-current.log. Missing predecessor cleanup and uncaught full-handoff error. Earlier new-red had missing required session_id in test factory; corrected, not production RED. |
| `timeout 120 poetry run pytest tests/tui/test_messaging_session_controls.py tests/tui/test_composer_retirement.py -m 'not e2e' -q` final | exit0, **31 passed/18 warnings**, dispatch8-source8-final-corrected.log. Source §8 command plus bounded timeout/quiet. |
| `timeout 180 poetry run pytest tests/tui/test_herdr_replacement.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_double_escape_resets.py -m 'not e2e' -q` | exit0, **40 passed/8 warnings**, dispatch8-source8-replacement.log. |
| `timeout 360 poetry run pytest tests/agents/slo_agent/messaging/ tests/tui/test_messaging_session_controls.py tests/tui/test_messages_command.py tests/tui/test_slash_router.py tests/tui/test_slash_command_registry.py tests/tui/test_durable_composer.py tests/tui/test_composer_retirement.py tests/tui/test_composer_transcript_identity.py tests/tui/test_prompt_component_protocol.py tests/tui/test_adapter_registration.py tests/integration/test_session_messaging.py -m 'not e2e' -q` | exit0, **633 passed/355 warnings**, 270.17s; dispatch8-affected-regressions.log. Final production behavior; later only strengthened A6 same-ID retry script/assertion, rerun final source8. |
| `timeout 120 poetry run pytest tests/tui/test_app.py -k 'QueuedPrompt or AuthMount or Submission or Abort' -m 'not e2e' -q` | exit0, **23 passed/139 deselected/2 warnings**, dispatch8-legacy-controls.log. |
| `poetry run black --check src/tui/app.py tests/tui/test_messaging_session_controls.py` | exit0, 2 unchanged; dispatch8-black.log (final repetition below). |
| `poetry run mypy --no-incremental src/tui/app.py tests/tui/test_messaging_session_controls.py` | exit1, only baseline missing yaml stubs in unchanged skills/service.py:13; dispatch8-mypy-current.log. No introduced typing errors, gate still blocked. |
| `timeout 120 make lint` | exit2, **one missing-yaml-stubs error/971 files**; dispatch8-lint.log. Not waived or repaired. |
| `git diff --check`; `dpkg -V coreutils` | exit0/no output each. No command stubs added. |

Other intermediate evidence retained honestly: first full new run had unscripted get_receipt in test retry; fixed scripted answer. Expanded provider oracle initially omitted admitted note from resumed context (existing note-before-input contract), corrected exact expected context, not application fix. Cleanup-failure notice test initially failed after replacement UI erased the notice; production now carries bool cleanup outcome and renders after clear. Final strengthened A6 first expected two lookups but real adapter does one lookup then direct same-ID submit; corrected exact expected calls, 31-pass final receipt. No assertions disabled.

## Remaining / next exact target

DC06 mandatory lint remains BLOCKED. Full non-e2e pytest is mandatory at **whole feature completion**, not run or waived in this bounded slice; no xdist/serial runtime assumption is accepted. Formal independent review/completion still pending; early-review.md remains historical advisory, not restarted.

**Next bounded target: DC07.A1–A11**, read original `07-finite-headless-and-steer.md` filename from source directory before proceeding: finite atomic cutoff including applying count, revision/check/wait notification safety, single joined finish/hard-stop, actual session scheduler cancellation/close, headless finite wait and steer admission with legacy regressions. DC08.A1–A11 remains trusted Inbox capability/original identity/digest/target, receipt-only ack and restart/claimed paging/forgery tests. DC09.A1–A6 remains production cutover/rollback/runtime README/theme×size/failure matrices, full non-e2e and static gates, then mandated independent review/completion. No later slice was implemented here.
