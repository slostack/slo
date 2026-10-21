# T6 platform matrix 139 — INCOMPLETE acceptance; 64/64 matrix green

## Scope, plan and accounting

Owned test: `tests/integration/test_herdr_lifetime_matrix.py`; uniquely named helper `_matrix139_platform`. Only this report and `t6-matrix-platform-139-receipts/` are additional repository writes. No production/full_flow/harness/shared-status/spec/other-worktree changes, agents, commits, external actions, full suite or integration-directory collection. Two-process HOLD retained.

Continuation accounting supplied by user: unfinished turn 1, started 1, completed 0, historical partial 1, dispatch label 139, retries 0; unlimited turns/dispatches. No new dispatch performed. Author checks are not independent review.

Plan executed: preserve six existing phase families; add two real synchronous platform boundary families; run sixteen first, whole matrix, distinct G1/G2 and all-owner compositions; inspect bounded ownership evidence; record limitations without production repair. Python/Textual composed offline integration, not live end-to-end certification. Read project instructions/root and docs RESEARCH, KB Welcome/slo README/gotchas, routing/testing/ownership, Python and Textual conventions, coding cadence/declarative guidance and workflow counting. Canonical C section 8/7.14, D 7.5 and tasks T6 distinguish platform lifetime from Herdr revocation; accepted review summary is specification acceptance only. Broader 7.9–7.13 and skill prerequisite review was not exhaustively completed; no blanket convention-compliance claim.

## Platform evidence

Sixteen IDs are `healthy|raising` × `precommit_platform|committed_platform` × `runtime_disable|session_close|new|unmount`. They share the original matrix test function, not calls to existing tests. Existing 48 IDs retained.

Real `VisualizerLauncher.launch_async` → `_launch_platform_joined` → synchronous `launch` → Linux command construction → `_spawn_detached` executes. Discovery alone is held for precommit_platform; actual default-spawn callable entry is held for committed_platform. The spawn spy delegates exclusively to the suite's guarded test stub. Counts before stop/release are 0 versus 1; final count is exactly 1. Discovery-blocked work is already synchronously admitted: cancellation may submit it late, but cannot lose its thread. This is not a claim that already-admitted discovery is rejected before spawn. Additional scheduling after new/unmount cutoff is refused.

A separate genuinely activated pane session supplies runtime-disable via sequence reservation failure and session close via the actual close gateway. The mounted platform session is independently classified explicitly disabled at activation; no destination property is mocked and no Herdr failure becomes platform fallback. New/unmount run the actual mounted app gateways. Integration-only stops do not terminate independent platform work; explicit viewer caller cancellation tests its retained join separately. This distinction is material, not an equivalent four-stop app shutdown claim.

Repeated viewer cancellation leaves viewer/closing tasks pending while the thread is blocked, and selected session remains captured old identity. After release, cancellation completes, registry empties, captured parent is the sole submitted argv, new adopts only after join, old inbox lease releases only on app replacement/unmount, and no launch outcome notice occurs. Reporter acknowledgements remain unchanged after cutoff; no later ordinary report/viewer command occurs. Transport/ticket/save/reservation and retired-session assertions cover participating owners; final pane cleanup verifies drained transport and released lease.

All 64 diagnostic variants assert the diagnostic sink was actually called. Platform variants inject real reporter withdrawal/sequence failures and patch the warning sink healthy/raising. They do not claim a throwing *platform renderer* sink was invoked: late notices are forbidden and asserted absent.

## Fresh commands and results

Cwd: `/root/Code/slo-94-herdr-integration/slo`. Interpreter `/root/.pyenv/versions/slo-harness/bin/python`, observed 3.11.7. Explicit fallback: `SLO_ENV=test`, `SLO_PROJECT_ROOT_DIR=$PWD`, `SLO_APP_ROOT_DIR=$PWD`, `PYTHONPATH=$PWD`, `SLO_APP_NAME=slo`, `SLO_LOG_FORMAT=text`, `SLO_DEFAULT_MODEL=gpt-5.4`, `SLO_AUTO_VISUALIZE=0`, `SLO_HERDR_DISABLED=1`, synthetic `SLO_ANTHROPIC_API_KEY`, `COLUMNS=120`, `LINES=40`. Root fixtures isolate state/strip HERDR; native_factory installs Faux and temp-owned regular plain-slo; fake_herdr supplies registered capability. No real provider, Herdr or terminal.

Commands use that interpreter:

- `-m pytest tests/integration/test_herdr_lifetime_matrix.py -k platform -x -q`: red.log first failed with undefined new helper (test scaffold RED, **not production RED**); platform-initial.log then **16 passed, 48 deselected**, 14.33s.
- `-m pytest tests/integration/test_herdr_lifetime_matrix.py --collect-only -q`: collection.log, exit 0, 64 cases.
- `-m pytest tests/integration/test_herdr_lifetime_matrix.py -vv -o faulthandler_timeout=40`: matrix.log **64 passed**, then stronger late-ack assertions and final formatting; matrix-final.log **64 passed, 2 warnings, 68.72s**, exit 0. Final receipt controls.
- `-m pytest tests/agents/slo_agent/herdr/test_session_publication_compositions.py::test_real_session_save_barrier_latest_publication tests/agents/slo_agent/herdr/test_reporter.py::test_viewer_lock_waiter_superseded_report_never_spawns tests/tui/test_herdr_all_owner_cutoffs.py tests/tui/test_herdr_platform_commit.py -vv -o faulthandler_timeout=40`: surrounds.log **44 passed, 20 warnings, 23.98s**, exit 0. These unchanged tests ran separately from the matrix.
- `-m black --check tests/integration/test_herdr_lifetime_matrix.py`: final green, one file unchanged.
- `-m mypy --follow-imports=silent tests/integration/test_herdr_lifetime_matrix.py`: final green, one source file. Not global mypy.
- Scoped `git diff --check`: green; test is untracked, so direct file inspection, not tracked diff coverage.
- `dpkg -V coreutils`: silent before and after; final empty coreutils-final.log, exit 0.

Global static baseline **281 errors/58 files** is user-supplied, unwaived, not rerun. No full gate authorized/run.

## Finite evidence map (not a substitution claim)

| Contract/owner | Fresh executable cases | Actual proof and boundary |
|---|---|---|
| C phase cutoff matrix | `test_lifetime_cutoff_matrix`, 64 IDs | Six original Herdr phases plus two independent platform boundary phases; diagnostic sink calls in every case |
| G1 same capture/newest usage | `test_real_session_save_barrier_latest_publication[usage_rename]` | Real Faux usage 15 tokens, rename during real immutable save, one save, latest token wire and display ack |
| Changed capture contrast | same test `[reasoning]` | Old save not advertised; second save matches changed capture; distinct from G1 |
| G2 actual shared-lock viewer/A/B | `test_viewer_lock_waiter_superseded_report_never_spawns[cutoff-changed_generation]`, cutoff superseded/close/cancel/timeout × False/True, 8 IDs | Actual guarded viewer child owns lock, durable A reservation, B supersession, A never spawns; newer sequence only on superseded; other cutoffs retain no binding/lifecycle ack |
| Current + retired owner cleanup | `test_all_owner_claim_pending`, 28 IDs | Seven cutoff modes × persistent/transient drain × healthy/throwing notice; actual retained viewer/transport fixture, captured lease identity, both timers, preparation, current close/final, retired final/drain, unsubscribe attempted |
| Inbox/late ack | same 28 IDs | claim_pending/workflow_advance_pending/before_chat_registration preserve claimed bytes, no invoke/history/ack/replay; already_registered/registered_abort/registered_original_store/registered_abort_original_store finish through original store; no queued successor |
| Diagnostic isolation in full-owner composition | same 28 IDs | Actual preparation cleanup failure produces exactly one cleanup notice; raising notice cannot skip later owners |
| Platform surrounds | `test_platform_launch_join`, 2 IDs; `test_platform_commit_joins_app_lifetime`, 4 IDs | Real synchronous continuation, repeated cancellation and app lifetime joins; independent corroboration, not matrix replacement |
| Initialization, attention, prompt-registration boundaries | Existing dedicated files, not freshly run here | **Unverified in this receipt**; 64-case matrix does not replace these |
| Unified prompt/tool/retry/pool/restore journey | full_flow/two-process held | **Not run**, no completion claim |

## Remaining limitations / parent handoff

**INCOMPLETE**, not READY64 acceptance: although exact matrix execution is green, comprehensive per-case all-owner and late-ack obligations are not established across the retained original 48 cases. They assert their participating reporter/viewer/save owners, not all timers/inbox/current+retired owners in every matrix row. The separately run 28-case all-owner composition remains distinct evidence and cannot honestly be called that missing cross-product. Platform integration-only stop cases explicitly cancel their independent viewer; reporter disable itself does not stop that viewer. No new production RED was found and no production edit was made.

Next closure work must reconcile those precise coverage boundaries with C7.9–7.14, freshly run required initialization/prompt-registration complements under safe explicit IDs, complete prerequisite review, then obtain independent review. Full suite, two-process restoration and live acceptance remain separately held/unverified. No shared status was updated.
