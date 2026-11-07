# Dispatch 5 — DC03 observation and transcript identity

**Verdict: REVISE / implementation milestone delivered; acceptance BLOCKED by missing yaml stubs.** DC03 A1–A11 behavior evidence is present below, but source §8 requires make lint and it fails. No waiver, independent final review or completion is claimed. Production default remains off. Whole Code+Test remains NOT READY (DC04–09 and full pytest required later).

Branch `message-queue`, cwd `/root/Code/slo-message-queue/slo`; turn 1: started 1, completed 0, partial 1; dispatch 5/20, zero retries; max 60 turns. No agents/workflows launched; no repeated early review. Existing SLO.md, docs/, DC01/DC02 implementation preserved. No commit/push/PR/merge, dependency, host or package changes.

## Owners changed

- `messaging/dao.py`: strict frozen MessagingObservationDAO.
- `sessions/service.py`: one authorized subscription, initial registration before yield, bounded 256-event/1-MiB backlog, synchronous publication after admission/claim/application, typed gap/close/storage failures, cancellation-only detach, history-barrier hydration. Return annotation is AsyncGenerator (a subtype of the specified AsyncIterator) so aclose is statically available.
- `history/transcript.py`: canonical projector provenance verification, fixed invalid-entry note, paired metadata/hash, human input versus machine/note classification; active compaction summary is visible without invented identity.
- `history/__init__.py`: lazy transcript exports preserve public imports and prevent the new transcript→messaging import from creating a messaging→history-package→transcript cycle. history.dao still never imports messaging.dao.
- `chat_transcript/{commands,component}.py`, existing `adapters/transcript_projector.py`: typed live application route, sole binding-lifetime ID/hash/conflict owner; begin/reset/clear retain identity, history rebind/close retire it.
- `prompt_input/{commands,component}.py`: shared receipt/application recall identity, bounded latest-4096 deque/set; accepted slash-origin draft records submitted text, not already-cleared raw editor contents (EF-05).
- `app.py`: tracked observation task, subscribe-before-replay/repeated-gap rebuild, owner-local capped band, application route/recall fallback, run spinner/reset/terminal cleanup; exit cancels and joins observation before client/session cleanup. Full retirement/handoff remains DC04.
- Tests: new `tests/tui/test_composer_transcript_identity.py`, `tests/agents/slo_agent/messaging/test_observation.py`; additions to existing `history/test_transcript.py`.

No new projector/history writer/UI store read; queue/store/history projector unchanged. Existing adapter protocol, registration, flat/tree persistence and legacy path retained.

## All DC03 acceptance rows

| Row | Current executable evidence |
|---|---|
| A1 | `test_live_echo_once_per_id_with_band[flat/tree]`: real mounted three Enter admissions held behind first provider; three exact ordered user/assistant pairs, owner-next band then removal, once-only recall, spinner cleanup. |
| A2 | Same test remounts a fresh owner over the same flat/tree history: exact three echoes once, empty recall, provider count unchanged. Combined journey rather than separate duplicate setup. |
| A3 | `test_reset_and_clear_preserve_binding_identity` adapter plus `test_component_clear_preserves_identity_until_history_rebind` public mounted begin/clear/rebind routes. Clear removes presentation, repeat does not re-echo; actual rebind allows reconstruction. |
| A4 | `test_application_before_receipt_records_recall_once`: real LocalSessionMessagingClient subclass holds only response after durable admission; one echo/recall before receipt, still one afterward. `test_recall_identity_is_bounded_and_uses_submitted_slash_text` covers EF-05 and exact 4096 bound. |
| A5 | Session `test_overflow_raises_replay_gap[count/bytes]`: real 257 small /18 large settled SQLite notes; explicit gap, replacement subscribe before replay and all IDs recover. Mounted `test_overflow_raises_replay_gap_and_host_rebuilds`: two 257-event overflows while real barrier replay result is held; third read succeeds; paging rebuilds exactly all 514 canonical IDs without conflicts, observation still live. Private identity inspection verifies complete paged set; not a claim all 514 widgets coexist beyond normal transcript window limits. |
| A6 | Adapter parameterized scheduler context/input/transcript notes; mounted `test_machine_application_component_route_never_records_recall`: semantic sub-agent-notice widgets, no user widgets or recall. Actual machine session admission remains DC08, so this uses the specified existing public transcript route, not forged session authority. |
| A7 | `test_invalid_messaging_provenance_replays_fixed_note`: wrong deterministic event ID hides payload, continues to valid next entry. Paired/malformed metadata/hash boundary tests also pass. |
| A8 | `test_conflicting_same_id_evidence_fails_safely`: same ID/different canonical event hash mounts exactly one fixed conflict notice; no second echo or repeat notice. |
| A9 | `test_compacted_messages_are_not_fabricated_on_replay[False/True]`: reuses original real session compaction setup, remounts actual flat/tree store; summary visible, only four retained tail bodies echo, compacted instructions 0/1 never fabricated. Original setup compacts two, not all six. |
| A10 | `test_observation_authority_single_stream_and_close`: initial revision/target, conflict/unauthorized, exact published application/receipt ID, detach leaves held real execution running, close→completing. `test_cancelled_observation_detaches_and_barrier_replay_waits`: cancel releases subscription and actual history barrier blocks hydration. |
| A11 | `test_run_presentation_follows_session_execution`: two successive real runs, each spinner/reset and terminal context/usage cleanup. `test_fast_provider_echo_precedes_answer` also proves already-released provider ordering and no stale spinner. |

## Verification receipts

Environment prefix for every pytest: `SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH=$PWD`. `make test-env` → fallback. Every pipeline used `set -o pipefail`; commands below from app root; logs in this directory's `logs/`.

| Command | Status / receipt |
|---|---|
| `timeout 90 poetry run pytest tests/tui/test_composer_transcript_identity.py -q` before identity implementation | exit 1, 5 failed/2 warnings; dispatch5-identity-red.log (missing retire route, human classification/hash identity). |
| `timeout 90 poetry run pytest tests/tui/test_composer_transcript_identity.py tests/agents/slo_agent/history/test_transcript.py -q` first identity GREEN | exit 0, 26 passed/2 warnings; dispatch5-identity-green.log. |
| `timeout 90 poetry run pytest tests/agents/slo_agent/messaging/test_observation.py -q` before observation | exit 1, 3 failed/2 warnings (missing owner API); dispatch5-observation-red.log. Earlier collection exposed import-order cycle, fixed by lazy package export before this RED. |
| `timeout 120 poetry run pytest tests/agents/slo_agent/messaging/test_observation.py -q` | exit 0, 3 passed/3 warnings; dispatch5-observation-green.log. Initial test-construction errors (missing message ID/kind) fixed, not production behavior RED. |
| `timeout 60 poetry run pytest tests/agents/slo_agent/history/test_transcript.py -k active_compaction -q` before summary handler | exit 1, 1 failed/23 deselected/2 warnings; dispatch5-compaction-red.log. Summary now covered by final GREEN. |
| `timeout 240 poetry run pytest tests/tui/test_composer_transcript_identity.py tests/agents/slo_agent/messaging/test_observation.py tests/agents/slo_agent/history/test_transcript.py -m 'not e2e' -q` | exit 0, **44 passed**, 13 warnings; dispatch5-focused-final.log. |
| `timeout 240 poetry run pytest tests/tui/test_transcript_component_protocol.py tests/tui/test_transcript_projector.py tests/tui/test_adapter_registration.py tests/agents/slo_agent/history/ -m 'not e2e' -q` | exit 0, **403 passed**, 2 warnings; dispatch5-affected-history-final.log. |
| `timeout 240 poetry run pytest tests/tui/test_durable_composer.py tests/tui/test_prompt_component_protocol.py tests/integration/test_session_messaging.py tests/agents/slo_agent/messaging/ -m 'not e2e' -q` | exit 0, **465 passed**, 325 warnings; dispatch5-messaging-regression.log. Added cancellation/barrier test postdates this receipt and passes final focused command. |
| `timeout 180 poetry run pytest tests/tui/test_app.py -k 'QueuedPrompt or AuthMount or Submission' -m 'not e2e' -q` | exit 0, **20 passed**, 142 deselected/2 warnings; dispatch5-legacy.log. |
| `poetry run black --check <13 DC03 Python paths listed below>` | exit 0, 13 unchanged; dispatch5-black.log. |
| `poetry run mypy <same 13 paths>` | exit 1, one unchanged missing-yaml-stubs error in skills/service.py:13; dispatch5-mypy-final.log. |
| `timeout 120 make lint` | exit 2, 8 missing-yaml-stubs errors/967 files; dispatch5-make-lint.log. **BLOCKED**, never excluded. |
| `git diff --check`; `dpkg -V coreutils` | exit 0/no output each. No new test stubs binaries. |

13 paths for static commands: `src/agents/slo_agent/history/{__init__,transcript}.py src/agents/slo_agent/messaging/dao.py src/agents/slo_agent/sessions/service.py src/tui/app.py src/tui/components/chat_transcript/{commands,component}.py src/tui/components/chat_transcript/adapters/transcript_projector.py src/tui/components/prompt_input/{commands,component}.py tests/tui/test_composer_transcript_identity.py tests/agents/slo_agent/{messaging/test_observation,history/test_transcript}.py` (shell brace expansion).

Intermediate logs retained: integration initial caught ephemeral notice erased by initial rebuild (fixed by announcing after replay); compaction first assertion incorrectly assumed all six bodies compacted (corrected to original exact two-covered/four-retained setup); terminal recording app initially used wrong relative CSS path (test fixed); recall test initially used wrong receipt field (test fixed). No false behavioral RED claimed for those setup mistakes. Added assertion-only journeys passed on first execution against implementation. Existing early review was not rerun.

## Precise remaining closure

1. DC03 static acceptance remains BLOCKED: missing yaml stubs, no package authority/waiver. Independent final review/completion still required later, not performed by this worker. Complete host replacement/unmount retirement is not claimed from exit observation join; EF-03 stays DC04.
2. DC04 A1–A8 joined prompt retirement/reset/rebind/unmount, bounded acknowledged unresolved-draft handoff, stale successor suppression/exit warning.
3. DC05 A1–A9 retained paging, consent/expiry/revalidation and atomic replay-safe continue/cancel with flat/tree restart + slash confirmation.
4. DC06 A1–A7 reusable abort/Ctrl+C pause, display-only controls, retire-close-adopt /new/refusals.
5. DC07 A1–A11 finite headless cutoff/applying count, revision wake/cancellation/shutdown, steer and legacy runner.
6. DC08 A1–A11 trusted machine Inbox capabilities/original identity/digest/target, receipt-only ack/restart/pruning/claimed paging and forgery safety.
7. DC09 A1–A6 production cutover/rollback guard/README/theme×size/failure matrices; full non-e2e pytest (`make test PYTEST_WORKERS=6`, existing missing xdist unresolved), all static gates, then independent final review and completion. Full pytest not attempted or waived in this bounded DC03 call.

DC01/DC02 milestone and historical receipt references are preserved verbatim below the current entry in implementation-handoff.md and continuation-ledger.md.
