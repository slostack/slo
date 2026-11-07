# Dispatch 10 — DC08 trusted legacy Inbox bridge

**REVISE / tested DC08 author milestone; mandatory full lint BLOCKED. Whole Code+Test NOT READY.** No independent acceptance. DC09 untouched; production defaults remain off. Turn1 started1/completed0/partial1, dispatch10/20, zero retries, max60turns. Requested Code+Test gpt-6.1-sol/medium and final independent gpt-6-astra/medium remain assignments, not evidence that independent phases ran. No agents/nested workflows, Git publication, package/host/infrastructure edits. SLO.md/docs/prior source edits preserved.

## Scope and design

Original `08-trusted-legacy-inbox-bridge.md` read in full, dependencies01/03/05/06 interfaces inspected, routing/handoff/ledger/dispatch9 consumed. README, Makefile/pyproject, ancestor instruction inventory, KB Welcome/slo README/gotchas/conventions/environment and supported memory consulted. Installed workflow/shared engineering, generic coding/design/naming/testing and Python style/application/domain-test/Textual guidance loaded. Existing real-store fixtures and vendor RecordingModel reused. No migration, new consumer, transport retirement, payload provenance, fallback runner, random replacement ID or automatic recovered-claim admission.

Plan executed: failing capability tests → session/store/queue verification → GREEN; failing paging test → bounded Inbox reader → GREEN; failing mounted bridge tests → admission/ack/scan/client lifecycle → GREEN; restart/pruning failure → exact history evidence repair → GREEN; affected regression/static/diff gates. Interfaces follow original spec; no new service fanout.

Changed owners:
- `messaging/dao.py`: strict frozen LegacyInboxAdmissionDAO reuses canonical submission validation with fixed-width placeholder routing, no authority/target fields.
- `messaging/store.py`: exact legacy source correlation and worker-owned sender-before-digest verification; point identity decoder shared with find_identity. Original target, principal and digest remain immutable.
- `messaging/queue.py`: mutex-owned verify_admission through existing cancellation-settled storage operation; absence is a point read, no wake or publish.
- `sessions/service.py`: exact owner/client registration capabilities; stable legacy principal values across generations, identity-based registration checks; restricted machine submissions/own receipt reads; recovery/observation remain owner-only; revoke maps after call joins. Applied projection membership uses surviving exact history evidence when journals have been pruned; applying path remains journal-based.
- `history/inbox/store.py`: UUID-sorted ≤16 claimed paging, strict pre-I/O limit/cursor validation, prefix on corruption then typed filename cursor, invalid UTF-8 treated unreadable. No lane mutation in reads.
- `tui/app.py`: register two clients in activation, unchanged workflow advance/ui_notice before machine admission, original UUID/source/text, priority normal, receipt-only ack, unknown reply one receipt lookup, bounded held ack/unknown claims, original-proof retries, startup scan with binding/lease collaborator checks, clients closed before session on shutdown/replacement. Messaging fail-closed readiness replaces only legacy idle task gate.
- Tests: new `tests/agents/slo_agent/messaging/test_legacy_admission.py`, `tests/tui/test_legacy_inbox_bridge.py`; extended `tests/agents/slo_agent/history/test_inbox_store.py`.

## DC08.A1–A11 evidence map

| Row | Passing evidence / boundaries |
|---|---|
| A1 | `test_claim_admits_original_identity_and_acks_after_receipt`: real scheduler note before provider (zero requests); workflow terminal while held real human run, receipt/ack and stable machine sender, persisted original UUID/source/normal priority/text payload; two provider requests total; actual workflow handle completed; machine widgets/no machine recall or user echo. Existing producer policy untouched and regressions green. Handle advancement is verified by durable final state, not a spy call-count assertion. |
| A2 | `test_response_loss_retries_same_id_then_acks`: injected CompletionGate at public session admission holds real SQLite worker before commit; both .02s submit/lookup deadlines expire, claim kept; release and next poll verifies/acks; exactly one identity, one provider request and applied application. No second submission path on recovered claims. |
| A3 | `test_ack_failure_repeats_verification_not_execution[False/True]`: real Inbox subclass injected via constructor returns False/raises OSError; next poll proof/ack, two ack calls, one identity, no provider. |
| A4 | `test_restart_scan_acks_matching_admission_after_generation_change[None]`: real remount, original target differs from current, applied note body actually absent from messages after maintain(+9days); original proof acks and no provider. `[retained]` separately proves accepted retained claim ack without continuation. |
| A5 | same restart journey `[text/kind/source]`: changed content/mapped kind/source class stays claimed, original identity count unchanged, no provider. Session tests distinguish conflict versus unauthorized sender. |
| A6 | restart `[unknown]`: claimed never-admitted file remains, zero identities/provider. `test_startup_scan_continues_after_malformed_claim` verifies 19 unknown claims across bounded pages plus corrupt file, no republish. |
| A7 | `test_forged_capabilities_are_unauthorized`: equal owner, copied client, decoded/equal principal refused; registration idempotent; revoked maps refuse. `test_machine_clients_close_before_session_and_successor_rejects_old_client`: all clients return completing before real session close, successor refuses old client. Recovery/observation cannot use machine authority. |
| A8 | `test_store_verify_admission_precedence`: real SQLite exact verification, foreign sender unauthorized before changed digest conflict, absent not_found; malformed source correlation refused. |
| A9 | `test_read_claimed_pages_by_uuid_and_surfaces_malformed`:20 real claims, UUID pages16+4, invalid limit/types/cursor ValueError, malformed UTF-8 prefix then typed filename UUID, mismatched body UUID typed error. Startup malformed journey continues after corrupt cursor. |
| A10 | `test_noncanonical_inbox_id_is_refused_without_replacement`: invalid ID file kept claimed, no done/pending, zero SQLite identities/provider. DAO tests additionally reject blank/oversize/invalid-UTF8/target/principal data. |
| A11 | Original unchanged legacy disposition/cutoff matrix passes in492-pass regression; affected Herdr/replacement/shutdown/activation/history/composer suites green. |

Lock/lifetime inspection: verify holds queue mutex only, uses settled worker reads and never execution/history locks; no new task consumer. Session close joins calls before revocation/resources. App startup scan belongs to activation await and captures current session/store/lease store/owner; successor scans its own ID only. /new continues to use existing joined close gateway. Unknown claims are not moved to pending.

## Exact commands and receipts

Cwd `/root/Code/slo-message-queue/slo`. `make test-env`→fallback; `poetry run python -V`→3.11.7. Prefix for pytest:
`SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH=$PWD`.
All pipelines used `set -o pipefail`; logs under this directory's `logs/`. No deselected/skipped rows in final selected commands.

| Command | Exit / result / receipt |
|---|---|
| source§8: `timeout 60 poetry run pytest tests/agents/slo_agent/messaging/test_legacy_admission.py tests/tui/test_legacy_inbox_bridge.py tests/agents/slo_agent/history/test_inbox_store.py -m 'not e2e' -q` |0; **35passed/5warnings**,5.54s; dispatch10-source8-delivery-final.log |
| source§8: `timeout 300 poetry run pytest tests/tui/test_herdr_inbox_disposition.py tests/tui/test_herdr_inbox_cutoffs.py tests/agents/slo_agent/messaging/ -m 'not e2e' -q` |0; **492passed/344warnings**,116.65s; dispatch10-source8-regression-final.log |
| `timeout 300 poetry run pytest tests/tui/test_herdr_replacement.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_herdr_app_shutdown.py tests/tui/test_durable_composer.py tests/tui/test_composer_retirement.py tests/tui/test_messaging_session_controls.py tests/tui/test_composer_transcript_identity.py tests/tui/test_messages_command.py tests/agents/slo_agent/history/ -m 'not e2e' -q` |0; **421passed/42warnings**,101.89s; dispatch10-affected-final.log |
| `timeout 120 poetry run pytest tests/tui/test_herdr_activation*.py tests/tui/test_herdr_init*.py tests/tui/test_herdr_all_owner_cutoffs.py tests/tui/test_herdr_combined_cutoffs.py tests/tui/test_herdr_stale_release.py tests/integration/test_session_messaging.py tests/cli/test_headless_messaging.py -m 'not e2e' -q` |0; **188passed/48warnings**,78.08s; dispatch10-lifecycle-regression.log |
| `poetry run black --check` nine Python files listed above |0;9unchanged; dispatch10-black.log; later assertion additions formatted again |
| `poetry run mypy --no-incremental` same9files |0;9clean; dispatch10-mypy-final.log. Does not waive full lint. |
| `timeout 120 make lint` |2; unchanged missing yaml-stubs1error/976files at skills/service.py:13; dispatch10-lint.log; BLOCKED, not excluded |
| `git diff --check`; `dpkg -V coreutils` |0/no output each; no command stubs added |

Intermediate evidence retained honestly: initial capability RED import error was shown but tee failed because assumed root logs/ was absent (no saved RED log); subsequent receipts use explicitly created evidence/logs. Paging RED1failed/13deselected; bridge RED2failed; domain GREEN16passed. Recovery initial4failed/6passed revealed pruned-journal startup defect; fixed10passed. Expanded focused first1failed/31passed was incorrect test API call missing owner_session_id, corrected. First affected command exit4 typo nonexistent test_herdr_shutdown.py; corrected real file. Affected419passed/2failed exposed slower applying projection path after broad history reread; narrowed to applied identities only, final421passed. No assertion disabled. Scoped mypy initially revealed actual introduced typing errors, corrected; full lint remains blocked despite scoped success.

## Honest remaining closure

DC08 has author implementation/evidence for A1–A11, not independent acceptance. Additional adversarial combinations remain unproven as dedicated DC08 mounted cases: shutdown/displacement inside startup page/verification await, concurrent on-disk edits during held ack retry, hard storage failure at machine verification. Existing binding guards and broader cutoff tests are evidence of preservation, not proof of every such new combination. Ack fault tests cover OSError/False, not arbitrary programmer exceptions. Startup UUID sorting bounds content reads, not filesystem directory enumeration. No claim of all possible receipt states separately exercised; applied and retained accepted have restart journeys.

Full non-e2e pytest is still mandatory at final feature completion; not run/waived in this bounded DC08 author slice. Missing xdist is not an exemption. Next authorized target is **DC09.A1–A6** default cutover/rollback/theme-size/failure matrices, README runtime contract, full static/default-suite gates, followed by independent gpt-6-astra/medium review/completion. Do not begin cutover merely because this author report lists green focused tests. Any independent finding returns to its exact acceptance row. No independent model substitution or agent launch occurred.
