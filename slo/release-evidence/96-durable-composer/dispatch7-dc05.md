# Dispatch 7 — DC05 retained-input recovery

**REVISE / DC05 implementation milestone delivered; mandatory lint acceptance BLOCKED.** A1–A9 have executable evidence below; no independent review/completion or whole-feature acceptance is claimed. Production default stays off; DC06–09 not implemented. Branch message-queue, turn1 started1/completed0/partial1, dispatch7/20, zero retries, max60 turns. Code+Test gpt-6.1-sol/medium; final review/completion gpt-6-astra/medium unchanged.

No agents/workflows, Git publication, host/package modifications or side quests. Existing SLO.md, docs/ and other edits preserved. Absent research/instruction files not recreated. No external KB edits: no non-obvious external constraint/learning arose requiring a new entry.

## Owners and interfaces

- messaging/dao.py: strict frozen RetainedSelectionDAO, CancelRecoveryConfirmationDAO and CancelRecoveryOutcomeDAO; UUID/unique selection/hash/aware UTC/cancelled-only validation.
- messaging/store.py: validated primary-key find_identity, reusable by DC08; same cancellation SAVEPOINT accepts already-cancelled IDs without rewriting their terminal timestamps and still rolls back changed subsets. No schema changes.
- sessions/service.py: injected consent clock; bounded single-use object-identity source registration; 16 live five-minute previews; exact action/DAO/principal consent; canonical hashes/revalidation; recovery lock before queue mutex, never execution lock; cached/store outcome replay before expiry, committed wake/publication. Existing queue recover/cancel and history owners reused unchanged. Authorization rechecked after acquiring recovery lock.
- tui/slash_router.py and slash_command_registry.py: typed list/cursor, continue/cancel and confirm/decline intents/usage; no persistence.
- tui/app.py: last-page selection/prefix authority, one held confirmation, fixed preview/decline/expiry/retry notices, same-object uncertain retry, clear selection at messaging close or adoption. No UI SQL.
- New tests: tests/agents/slo_agent/messaging/test_retained_recovery.py, tests/tui/test_messages_command.py; extended tests/agents/slo_agent/messaging/test_store_retained.py.

Current source authority is original revised/01-durable-composer/05-retained-input-recovery.md read in full, overview recovery interfaces and task dependency index. Project README/SLO/global ancestor, KB Welcome→slo README/gotchas and applicable shared/Python/Textual routing policies consumed. Existing session/store owners specialize generic application/domain examples: no speculative service, ORM, database or modal was introduced.

## A1–A9 evidence

Names without paths are in test_retained_recovery.py.

| ID | Executable evidence and boundaries |
|---|---|
| A1 | test_restart_reconciles_without_provider_and_lists_retained[flat/tree]: one database seeds pending, prepared applying, applied and committed-compacted input; **two new session owners** restart same history/session ID; exact pending page only, applying repaired exactly once, applied evidence once, compacted original absent, zero provider requests; joined-close SQLite all states read back. |
| A2 | test_confirmed_continue_executes_original_once[flat/tree]: page cursor, exact original text/ID/sender/target, new execution generation; exactly one recorded provider HumanMessage and one transfer row; exact submission JSON unchanged; other original retained. |
| A3 | Same test repeats confirmation; test_lost_reply_retry_returns_saved_outcome commits through existing real queue seam without session cache publication then advances clock six minutes: two retries return identical stored outcome, exactly one transfer row. Private queue access is intentional lost-reply injection at existing commit boundary, not a fake store or changed owner state. |
| A4 | test_expired_preview_requires_new_consent: six-minute clock advance, conflict, two original retained bodies and no provider call. Exact five-minute boundary also covered for cancel and mounted host. |
| A5 | test_changed_selection_refuses_stale_consent: separate cancellation consent commits first, stale continue conflicts, no execution. |
| A6 | test_cancel_is_all_or_none_and_replay_safe: concurrent exact confirmations give same ordered cancelled receipts; expired cached replay unchanged; closed rows both cancelled. Mixed-selection workflow preserves untouched sibling; store rollback test below. Mounted slash journey declines then re-previews/confirms cancellation without writing on decline. |
| A7 | test_consent_requires_session_registered_sources_and_capacity: equal caller-created source unauthorized, altered exact DAO unauthorized, 17th preview queue_full, expiration frees capacity, old-process confirmation unauthorized after new owner. Paging_validation adds strict ints, UUID/duplicates/size and foreign owner refusals; action-specific token refusal covered. |
| A8 | test_store_retained.py::test_cancel_replay_and_point_identity_read: unknown/invalid point read, cancelled replay same receipt, applied selection recovery_required and pending sibling unchanged, terminal identity after nine-day pruning, cancelled receipt unchanged. |
| A9 | test_messages_command.py::test_slash_recovery_flow_with_confirm_and_decline: real mounted editor Enter route list→continue id8→decline→continue→confirm; off-page cancel usage, one execution, cancel decline/confirm, exact closed SQLite outcomes. test_confirm_retries_identical_consent_after_lost_reply uses injected real-session subclass that commits normally then loses first reply; identical confirmation object retry, one execution. Expired host confirmation clears and second confirm says Nothing to confirm. |

Additional evidence: strict page 16+1 with cursor16; cancellation expired/mixed/committed-replay outcomes; sealed recovery completing and closed cancellation completing without mutation. All persistence/files confined to existing tmp_path fixtures; provider replaced only by RecordingModel. The host lost-reply subclass is constructor-composed, never patched internals.

## Exact receipts

Cwd app root. Every pytest used `set -o pipefail` and prefix:
`SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH=$PWD`.
`make test-env`: fallback; `poetry run python -V`: Python3.11.7. Logs in logs/.

| Exact command (after prefix where pytest) | Status / counts / log |
|---|---|
| timeout 60 poetry run pytest tests/agents/slo_agent/messaging/test_retained_recovery.py -q (before implementation) | exit1; 3 failed/2 warnings, missing clock seam; dispatch7-recovery-red.log. Interface RED, not sensitivity proof for every row. |
| Same command after continue increment | exit0; 3 passed/4 warnings; dispatch7-continue-green.log. |
| Same command before cancel methods | exit1; 2 failed/4 passed/4 warnings; dispatch7-cancel-red.log. |
| Same after cancel methods | exit0; 6 passed/4 warnings; dispatch7-cancel-green.log. |
| timeout 60 poetry run pytest tests/tui/test_messages_command.py -q before slash implementation | exit1; 2 failed/2 warnings; dispatch7-slash-red.log. One failure was incorrect test adapter attribute (fixed to public logical_copy_text), other missing router intent. |
| Same after implementation | exit0; 2 passed/3 warnings; dispatch7-slash-green.log. |
| timeout 90 poetry run pytest tests/agents/slo_agent/messaging/test_retained_recovery.py tests/agents/slo_agent/messaging/test_store_retained.py tests/tui/test_messages_command.py -m 'not e2e' -q | exit0; **19 passed**, 6 warnings; dispatch7-source8-current.log. Source §8 focused command with bounded timeout/quiet only. |
| timeout 180 poetry run pytest tests/agents/slo_agent/messaging/ -m 'not e2e' -q | exit0; **429 passed**, 320 warnings; dispatch7-messaging.log (before final sealed test added). |
| timeout 300 poetry run pytest tests/agents/slo_agent/messaging/ tests/tui/test_messages_command.py tests/tui/test_slash_router.py tests/tui/test_slash_command_registry.py tests/tui/test_durable_composer.py tests/tui/test_composer_retirement.py tests/tui/test_composer_transcript_identity.py tests/tui/test_prompt_component_protocol.py tests/tui/test_adapter_registration.py tests/integration/test_session_messaging.py -m 'not e2e' -q | exit0; **621 passed**, 342 warnings, 206.02s; dispatch7-final-regressions-300.log, final code/tests. Same combined command at timeout180 expired (exit124, no terminal count; dispatch7-final-regressions.log), not a passing receipt. |
| timeout 120 poetry run pytest tests/tui/test_app.py -k 'QueuedPrompt or AuthMount or Submission' -m 'not e2e' -q | exit0; **20 passed**, 142 deselected/2 warnings; dispatch7-legacy.log. |
| poetry run black --check (nine Python paths above) | exit0; 9 unchanged; dispatch7-black.log. |
| poetry run mypy --no-incremental (same nine paths) | exit0; no issues; dispatch7-mypy-final.log. Earlier scoped run reported existing yaml error plus 3 introduced annotations, fixed; intermediate current run found 2 test inference errors, fixed. Final scoped success does NOT waive full lint. |
| timeout 120 make lint | exit2; **one missing yaml-stubs error** in unchanged skills/service.py:13, 970 files; dispatch7-make-lint.log. Prior dispatch8-error baseline remains historical; current count one. No package change, baseline exclusion or waiver. |
| git diff --check; dpkg -V coreutils | exit0/no output each, final tool receipt. No new binary stubs. |

Intermediate setup correction: first continue run hit missing _require_uuid import; fixed. A 60s run then timed out because RecordingModel.release was unset and close correctly waited on provider; fixture now releases before execution. Do not call this an application hang or passing receipt. No regression assertions disabled. Added assertion-only boundary/restart tests passed first run; no invented RED claimed. Self-read of changed owner paths/diff performed; not independent review.

## Remaining gates and next closure

DC05 mandatory make lint remains BLOCKED, not accepted. Full non-e2e pytest remains mandatory at final feature stage, not run/waived here; historical absent xdist is not an exemption. Formal independent review/completion still pending. No production cutover.

**Next bounded target: DC06.A1–A7**, original 06-session-controls-abort-clear-new.md: reusable abort/Ctrl+C pause and continue/submit resume, display-only clear, retire-close-adopt /new, running/full-handoff refusals, predecessor/successor stores and lease/draft proof. Do not expand to DC07–09 during that bounded slice.

Later unchanged remainder: DC07.A1–A11 finite atomic headless cutoff/applying counts, scheduler wake/cancel/close/hard stop, steer/legacy runner; DC08.A1–A11 trusted Inbox provenance/original identity/digest/target, verified receipt-only ack/restart/pruning/lost responses/claimed paging/forgery; DC09.A1–A6 cutover/rollback/runtime README/themes×sizes/failure matrices/full gates; then independent final review and completion. Preserve prior dispatch5-dc03.md, dispatch6-dc04.md, early-review.md and historical DC01–02 references.
