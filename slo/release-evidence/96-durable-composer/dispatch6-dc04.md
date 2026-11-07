# Dispatch 6 — DC04 binding retirement and draft handoff

**REVISE / DC04 implementation milestone delivered; acceptance BLOCKED by missing yaml stubs.** EF-03's missing retirement is implemented and behavior-tested; formal independent closure is not claimed. Whole Code+Test remains NOT READY: DC05–09, full non-e2e pytest, final review and completion remain. Production default stays off.

Branch `message-queue`, cwd `/root/Code/slo-message-queue/slo`; turn 1 started 1/completed 0/partial 1; dispatch **6/20**, zero retries; limit 60 turns. No agents/workflows, review restart, Git publication, package/host changes, user-doc/SLO.md changes or research recreation. Prior DC01–03 evidence preserved in dispatch4 handoff and dispatch5-dc03.md. Tests use routing's synthetic fallback environment, Python 3.11.7, contained real SQLite/history and existing fixtures. Every logged pipeline uses pipefail.

## Changed owners (this dispatch only)

- `src/tui/components/prompt_input/submission.py`: frozen exact handoff/ack/usage DAOs, runtime host capability and fixed error; UUID and 16/1-MiB canonical validation.
- `src/tui/components/prompt_input/component.py`: reusable reset, public retirement, replacement and irreversible close each own joined barriers. Repeated caller cancellation joins before propagating. Seal/version advance precedes old outcome join; only exact typed positive ack releases snapshots. Failed/uncertain ack preserves the old adapter, snapshots and identical retry handoff. Borrowed clients/sessions never close here. Forced refusal drops only after adapter join, posts loss feedback, releases references last. Host reservations join component capacity checks. No component lock introduced.
- `src/tui/app.py`: bounded memory receiver, host-held list/discard/refuse-retry, combined prefix resolution; first intentional exit warning; pre-pruning mount/replacement join → observation detach/join → prompt close → memory-only notice → workflow observation close. Client then session cleanup remains downstream. Prompt close failure is contained by the existing shutdown-step owner so framework/session cleanup is not skipped.
- `tests/tui/test_composer_retirement.py`: 19 mounted/workflow cases, reusing ScriptedMessagingClient and CompletionGate; real successor session and SQLite readback; actual native remove; ack-loss/error/refusal/conflict; repeated reset/retire/rebind/close cancellation; capacity and host commands.
- `tests/tui/test_durable_composer.py`: two prior capacity tests now release their owned holds **before** run_test teardown. DC04 deliberately joins them; old post-context release relied on leaked waits and deadlocked. Assertions retained. No adapter/session/store changes this dispatch.

Implementation refinements: `_delivery_closing`, not source sketch `_closing`, because Textual owns `_closing`. Reset/replacement also use single owned tasks so cancellation cannot stop halfway. Uncertain handoff retries retain the exact ID/content rather than allocating a fresh key and duplicating ownership. Adapter unexpected delivery errors have already joined siblings; retirement translates them to handoff failure, retains recoverable snapshots and forced close still releases borrowers. Native framework flags and suggestion prompt_version semantics remain separate.

## DC04 A1–A8 map

All names below are in `tests/tui/test_composer_retirement.py` unless noted.

| Row | Evidence / forbidden effects |
|---|---|
| A1 | `test_reset_joins_waits_and_keeps_binding`: held late rejection, three caller cancellations, empty editor/no restore, recoverable snapshot, same adapter next submit, client untouched. `test_real_admission_joins_before_lifecycle_returns[reset]`: actual Enter and CompletionGate-held real SQLite admission; reset blocks until receipt, closed-store one-ID readback. |
| A2 | `test_rebind_hands_off_then_registers_fresh_adapter`: two exact snapshots positively retained, old adapter refs closed/released but client not closed; second ready real session accepts exact new target/input, real history readback. `test_handoff_and_component_share_canonical_byte_budget`: canonical usage sums and sixteen host reservations block capture before clear. |
| A3 | `test_full_handoff_blocks_replacement_and_preserves_drafts`: host holds sixteen; replacement raises fixed error, old adapter remains usable/unsealed, original snapshot retained; same-ID retry still works, next capture refuses before clear. |
| A4 | `test_unmount_close_joins_through_repeated_cancellation`: held rejection plus three cancelled close awaits and actual mounted `remove()`; same close task, outcome adopted without editor change, host holds old snapshot, component seals last, real client still returns not_found and session remains open. Real gated SQLite `[close]` additionally proves receipt settlement before cancelled close returns. |
| A5 | `test_late_old_binding_outcome_never_paints_successor`: distinct successor address; replacement stays unpublished until old rejection joins; repeated caller cancellation does not split operation; newer editor text survives; host retains exact old route/ID and successor has no old submission. `test_host_held_actions_never_retry_into_successor` explicitly refuses retry and proves no successor submit/lookup. |
| A6 | `test_host_handoff_is_idempotent_and_refuses_conflicts`: identical key/content returns same acknowledgement without reserving twice; changed content refuses. `test_ack_failure_preserves_binding_and_exact_retry[refused/wrong_id/exception/lost_ack]`: no premature release/rebind, same handoff retry, exactly one host reservation even after stored-but-lost ack. |
| A7 | `test_intentional_exit_warns_once_about_unsent_drafts`: public /exit first warns/remains open, second exits with client/session cleared. Existing `test_durable_composer.py::test_exit_closes_client_then_session_and_retains_pending` and `::test_client_close_failure_still_joins_session_cleanup` rerun, retain exact client-before-session order/failure cleanup proof. |
| A8 | `test_forced_teardown_reports_memory_only_drafts`: pre-pruning retirement twice gives one not-saved notice while host attached, prompt closed/observation gone. `test_close_refusal_discards_only_after_join_and_reports_loss`: forced refusal counts one dropped snapshot, closes borrower not client, clears drafts and renders fixed dropped notice. |

Extra safety: concurrent public rebinds share one replacement and never overwrite the first published adapter; public retirement seals capture and retry immediately, joins the same task under repeated cancellation, and the host renders the sealed retry notice. No old draft is automatically retried into another session. `/new` predecessor orchestration remains DC06, not implemented here.

## Exact verification receipts

Environment prefix for each pytest: `SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH=$PWD`. `make test-env` → fallback; `poetry run python -V` → 3.11.7. Logs under `logs/`.

| Command | Status / results / log |
|---|---|
| `timeout 90 poetry run pytest tests/tui/test_composer_retirement.py -q` before implementation | exit 2; missing DraftHandoffDAO collection error, 2 warnings; dispatch6-red.log. Missing-interface RED only, not behavioral sensitivity for every row. |
| `timeout 120 poetry run pytest tests/tui/test_composer_retirement.py tests/tui/test_durable_composer.py tests/tui/test_prompt_component_protocol.py -m 'not e2e' -q` final | exit 0; **67 passed**, 12 warnings, no skips/deselections; dispatch6-source8-current.log. |
| `timeout 150 poetry run pytest tests/tui/test_composer_transcript_identity.py tests/tui/test_transcript_component_protocol.py tests/tui/test_adapter_registration.py -m 'not e2e' -q` | exit 0; **44 passed**, 12 warnings; dispatch6-transcript-final.log. Last later edits only add sealed retry notice and extract unchanged adapter join handling; final source8 reran those boundaries. |
| `timeout 180 poetry run pytest tests/tui/test_transcript_projector.py tests/tui/test_slash_router.py tests/tui/test_slash_command_registry.py tests/integration/test_session_messaging.py tests/agents/slo_agent/messaging/ -m 'not e2e' -q` | exit 0; **588 passed**, 318 warnings; dispatch6-wider.log. Unchanged session/store/transcript owners; final local lifecycle refinements covered by source8. |
| `timeout 120 poetry run pytest tests/tui/test_app.py -k 'QueuedPrompt or AuthMount or Submission' -m 'not e2e' -q` | exit 0; **20 passed**, 142 deselected, 2 warnings; dispatch6-legacy.log. |
| `poetry run black --check src/tui/app.py src/tui/components/prompt_input/{component,submission}.py tests/tui/test_composer_retirement.py tests/tui/test_durable_composer.py` | exit 0; five unchanged; dispatch6-black-current.log. |
| `poetry run mypy` same five paths | exit 1; only baseline missing yaml stubs in unchanged skills/service.py:13; dispatch6-mypy-closure.log. No introduced error remaining. |
| `timeout 120 make lint` | exit 2; eight baseline missing-yaml-stub errors, 968 files; dispatch6-lint-closure.log. **BLOCKED**, no exclusion/waiver. |
| `git diff --check`; `dpkg -V coreutils` | exit 0/no output each; final tool receipt. |

Intermediate honest receipts: first lifecycle tests hung (120/35/25-second bounded runs) because component `_closing` collided with Textual; temporary async task dump isolated native message-pump exit, removed afterward. First combined regression timed out at 180s after two failure cases and held-capacity cleanup: existing tests released holds after teardown; fixed release ordering inside tests. `dispatch6-regression-diagnosis.log` records unexpected receiver failure reappearing at pre-pruning close; existing shutdown-step containment now preserves owner cleanup. Test construction corrections: missing successor public principal name, scripted retry without scripted lookup answer, initial real session omitted enable_history, subclass relative CSS path, and Path-vs-str static assignments. These were not production-contract RED claims. Black initially flagged the last test edit, then formatted and rerun clean. No assertions were disabled.

## Remaining gates and next target

- DC04's mandatory lint remains blocked; no formal independent review/completion was performed. EF-03 has implementation/behavior evidence, not independent acceptance. Full pytest remains mandatory at **final feature stage**; not run or waived here. Historical xdist absence is not a serial-suite waiver.
- **Next bounded target: DC05.A1–A9** retained-input recovery: read/paging, exact registered consent, expiry/revalidation, replay-safe atomic continue/cancel, flat/tree restart and slash confirmation. Consume original 05 and current interfaces first.
- DC06.A1–A7: reusable pause/abort/Ctrl+C, display-only clear, predecessor retire-close-adopt /new with running/full-handoff refusals.
- DC07.A1–A11: finite atomic headless cutoff/applying counts, wake/cancellation/concurrent close/hard stop, steer admission and legacy runner.
- DC08.A1–A11: trusted machine Inbox identity/digest/original target, verified receipt-only ack, lost submit/ack/restart/pruning/claimed paging and forgery safety.
- DC09.A1–A6: production cutover only after prior slices, rollback guards, runtime README instructions and theme×size/failure matrices; full non-e2e/static gates, independent final review and completion.

Durable learning recorded externally in KB slo/gotchas.md and Reinforcement/textual-closing-is-framework-owned.md. No project/user documentation edited.
