# Dispatch 9 — DC07 finite headless and steer

**REVISE / DC07 tested implementation milestone; mandatory full lint BLOCKED. Whole Code+Test NOT READY.** Production defaults remain off. No formal independent review/completion performed; existing early feedback is not final acceptance. DC08/DC09 not implemented here.

Branch message-queue; turn1 started1/completed0/partial1, dispatch9/20, zero retries, max60turns. Requested Code+Test gpt-6.1-sol/medium; independent review/completion gpt-6-astra/medium remain phase assignments, not a claim that independent phases ran. No agents/workflows, commit/push/merge/PR, packages/host/infrastructure changes. SLO.md/docs and prior edits preserved.

## Authority and plan

Original `07-finite-headless-and-steer.md` read in full, original 01/02/03 dependencies and overview finite/lifecycle interfaces, current acceptance-routing, handoff, ledger, dispatch8 and affected dispatch5–7/early-review read. README/SLO, absent ancestor instruction/research inventory, Makefile/pyproject, KB Welcome/slo README/gotchas/conventions/environment/operational reference, supported memory and applicable installed workflow/shared engineering/generic/Python/Textual skills consumed. No new CLI verb/build-cli recipe, ORM, broker, new runner or harness. Existing source-specific owners govern.

Plan: real queue/session RED → atomic cutoff/count GREEN → finite/session cancellation/close/stop → real runner RED/GREEN → mounted steer RED/GREEN → affected suites/static/diff. Vocabulary: accepted/applying/applied, cutoff, settlement revision, execution generation, retained notes, observer, scheduler, normal agent_input.

## Changed owners (this dispatch)

- `messaging/dao.py`: read-only `QueueStateDAO.applying_records`.
- `messaging/store.py`: current-generation applying count in accepting and nonaccepting lifecycle branches. No schema change.
- `messaging/queue.py`: strict frozen exported `FiniteCutoffDAO`; mutex-owned `seal_if_quiescent` rechecks session predicate after worker read. Existing cancellation-settled store operation reused.
- `sessions/service.py`: one revision/event/latest terminal, shared cancellation-joined finite/stop tasks, consumer permanent-exit guards, admission/pause/failure/close notifications, assigned cancellation settlement, outside-lock call/consumer joins, close joins finite/stop before resource release. Stop cancels actual consumers, reconciles prepared applications, retains pending. Failed/aborted settled run pauses before another scheduler run. TUI abort itself remains reusable; submit resumes as before.
- `cli/headless.py`: default-false opt-in starts messaging before child control/drain, publishes once through invoke, awaits finite result for exit/status, grace escalates actual scheduler stop, cancellation joins execution, messaging closes before external reporting. Existing watchdog/control/notifier/status/pool/signal/catalog owners retained, bootstrap/typer_dispatch unchanged.
- `tui/slash_router.py`: typed submit_text intent on actual ready messaging; legacy steer unchanged. `tui/app.py`: slash submission uses same capture/register/error owner as ordinary Enter with intent_revision=None; no pending-steer UI for messaging.
- New `tests/agents/slo_agent/messaging/test_finite_completion.py`, `tests/cli/test_headless_messaging.py`, `tests/tui/test_messaging_steer.py`; real SQLite/history, existing RecordingModel/RealAgentFactory/CompletionGate, vendor factory replacement only for real runners. Disposable paths validated within tmp_path. Black also reformatted preexisting long lines in touched owner files, no deliberate unrelated behavior change.

Lock inspection: cutoff execution → history → queue; queue never waits for execution or tracked calls; all call snapshots/consumer/lifecycle joins outside execution/history/queue locks; lifecycle lock only creates/chooses close task. No second invoke, polling wait or terminal list.

## A1–A11 map

| Row | Evidence / boundary |
|---|---|
| A1 | Real runner `test_second_run_settles_without_second_publish[False/True]`: first held provider, public subscriber admits external second only after first terminal (forces separate scheduler run); exactly two rows/bodies and stdout terminals, two provider requests, second completed exits0 / second aborted exits2. Never re-enter invoke to wait. |
| A2 | Queue `test_admission_before_cutoff_is_pending` proves committed mutex owner returns pending; `test_registered_admission_at_session_cutoff[True]` real client/session gate then scheduler drains one provider/history application and seals. |
| A3 | Queue `test_cutoff_refuses_unaccepted_admission` and real tracked session race `[False]`: waiting mutex call returns completing, zero rows/provider, finish joins without deadlock. |
| A4 | `test_terminal_between_check_and_wait_cannot_hang`: finish captures before execution-lock check, admission advances revision, pending releases ownership and sole scheduler settles/wakes; bounded terminal result. This is real revision/wait race coverage, not an injected callback exactly between the final revision comparison and event.wait; those two operations have no intervening await. |
| A5 | `test_pending_notes_retain_and_consumers_exit`: note behind finish execution ownership retained, no provider, both same consumer handles done; close SQLite accepted/retained1. No settled run returns specified fixed failure. |
| A6 | `test_cancellation_joins_finite_task_without_reopening[False/True]`: three cancellations before seal with held provider / after seal with registered held receipt; owned finish joins then waiter rethrows; later admission completing. |
| A7 | `test_concurrent_close_joins_finite_stop_path`: held real run, concurrent finish/close, bounded join, consumers done/readiness false, execution lease reacquired. |
| A8 | Real runner `test_hard_abort_stops_actual_scheduler`: never release provider, existing5s grace, exit2, actual consumer done, closed DB applied initial + accepted retained pending. Session `test_hard_stop_cancels_scheduler_and_settles_observer` verifies assigned aborted observer and actual cancellation request; `test_hard_stop_reconciles_prepared_application` separately seeds real prepared journal through existing store seam and proves exact once history/applied repair. `test_repeated_cancelled_stop_joins_owned_persistence` proves concurrent stop and three waiter cancellations join same task. Prepared-journal repair and runner hung-provider are complementary tests, not one combined runner crash-window injection. |
| A9 | `test_applying_count_prevents_cutoff[False/True]` and `test_orphan_applying_record_is_recovery_required`: real claim with no owner, no provider, applying remains visible, recovery_required failure instead of successful seal. |
| A10 | Mounted `test_steer_uses_normal_admission_in_messaging_session`: held provider, normal agent_input metadata exactly once, band adjust, one user echo, next HumanMessage context includes adjust, no steering_message. Legacy slash tests remain green. |
| A11 | Existing headless/herdr/watchdog/child-abort regression suites unchanged, included in556-pass source§8 regression. |

Additional failure boundary: model script underrun follows existing three recovery attempts; exact forbidden queued input never reaches any provider request, pending retained and finite fails. Runner task cancellation stops/joins actual execution before resource close. `test_stop_during_cutoff_read_wins_before_seal` gates store read and flips lifecycle predicate: stopping, not successful seal.

## Exact verification

Cwd `/root/Code/slo-message-queue/slo`. `make test-env` fallback; `poetry run python -V`3.11.7. Pytest prefix:
`SLO_ENV=test SLO_ROOT_DIR=$PWD SLO_APP_DIR=$PWD SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH=$PWD`.
All pipelines used `set -o pipefail`; logs in `logs/`. No skipped/deselected cases in final full-selected commands below.

| Command | Exit / result / log |
|---|---|
| `timeout 60 poetry run pytest tests/agents/slo_agent/messaging/test_finite_completion.py -q` before implementation, corrected canonical DB path |1;5 failed/3warnings (missing applying/cutoff/finish APIs); dispatch9-finite-red-corrected.log. Initial red had4 path-fixture errors, not production sensitivity. |
| `timeout 60 poetry run pytest tests/agents/slo_agent/messaging/test_finite_completion.py -k 'not finish' -q` |0;4passed/1deselected/2warnings; dispatch9-cutoff-green.log. |
| `timeout 30 poetry run pytest tests/cli/test_headless_messaging.py -q` before runner flag |1;2failed/2warnings; dispatch9-headless-red.log. |
| `timeout 30 poetry run pytest tests/tui/test_messaging_steer.py -q` before steer wiring |1;1failed/3warnings (no messaging band); dispatch9-steer-red.log. |
| `timeout 40 poetry run pytest tests/agents/slo_agent/messaging/test_finite_completion.py tests/cli/test_headless_messaging.py tests/tui/test_messaging_steer.py -m 'not e2e' -q` final |0;**23passed/20warnings**; dispatch9-source8-delivery.log. |
| `timeout 300 poetry run pytest tests/cli/test_headless.py tests/cli/test_headless_herdr.py tests/cli/test_headless_watchdog.py tests/cli/test_headless_child_abort.py tests/agents/slo_agent/messaging/ -m 'not e2e' -q` |0;**556passed/332warnings**107.72s; dispatch9-source8-regression-final.log. Final production code; subsequent assertion-only stop/lease/path additions covered by23-pass final. |
| `timeout 240 poetry run pytest tests/tui/test_slash_router.py tests/tui/test_durable_composer.py tests/tui/test_composer_retirement.py tests/tui/test_composer_transcript_identity.py tests/tui/test_messaging_session_controls.py tests/tui/test_messages_command.py tests/tui/test_prompt_component_protocol.py tests/tui/test_messaging_steer.py -m 'not e2e' -q` |0;**194passed/39warnings**94.85s; dispatch9-composer-final.log. |
| `poetry run black --check` ten Python files listed above |0;10unchanged; dispatch9-black-closure.log; later assertion-only edits Black formatted. |
| `poetry run mypy --no-incremental` same ten files |0;10files clean; dispatch9-mypy-closure.log. Other runs report unchanged yaml error; cached/transitive mypy success never waives full lint. |
| `timeout 120 make lint` |2;1missing yaml-stubs error/974files, unchanged skills/service.py:13; dispatch9-lint-closure.log. BLOCKED, not excluded. |
| `git diff --check`; `dpkg -V coreutils` |0/no output each. No new command stubs. |

Intermediate receipts retained honestly: lifecycle test timeout60 exit124 exposed swallowed attempt cancellation returning scheduler to paused wait; permanent stop guard now set before cancellation, and consumed synthetic aborted terminal is retained. Later stop test initially expected Task.cancelled(), but existing attempt owner converts cancellation into aborted result; asserts actual cancelling()>0 plus done/observer/no provider release instead. Runner setup initially used wrong raw model factory product then missing OpenAI credential: corrected to actual LLMBuildResult and Anthropic route with Makefile synthetic credential. Steer first GREEN failed on nonexistent widget raw_markdown; corrected public text. Composer regression1failed/192passed found truthy unset mock readiness; actual bool True branch fixed,194pass final. Prepared-journal test initially lacked real history session metadata; added through real store owner. Failure test initially assumed no retry; corrected to forbidden second instruction across existing recovery attempts. No assertions disabled; no broad test waiver.

## Gates / next boundary

DC07 has implementation and focused evidence for all rows, with exact composite-evidence limitations above; **NOT acceptance READY**: mandatory full lint remains blocked and independent review/completion not run. Whole non-e2e pytest remains mandatory later, not run or waived here (no xdist exemption). No default cutover.

Next bounded implementation target **DC08.A1–A11** original `08-trusted-legacy-inbox-bridge.md`: private machine registration/original UUID/source/digest/target, receipt-only ack, lost submit/ack/restart/pruning, bounded claimed paging and forgery/malformed/unknown safety. Then DC09.A1–A6 default/rollback/theme-size/failure matrix and final full pytest/static gates, independent review/completion. Any independent DC07 finding returns to its exact row rather than starting unrelated infrastructure work.
