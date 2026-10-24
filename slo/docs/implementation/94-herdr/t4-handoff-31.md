# T4 handoff 31 — entire T4 technical READY

T4 adapter/reader scope is **technical READY**. The two remaining executable
compositions, required read audit and task-regression reconciliation are closed.
This is not integrated Step-1 acceptance, independent review, complete chapter D,
feature completion, live Herdr compatibility or viewer-paint acceptance.

Same unfinished turn 1: started 1, completed 0, historical partial 1, dispatch 31,
retries 0. Unlimited turns AND dispatches supersede historical numeric limits.
No agents dispatched here. No production, T3/T5/shared-DAO, spec, KB/global,
other-worktree, commit/push/PR or live-system changes. Historical receipts and
routing/scope-plan are preserved, not reset to their stale all-pending status.

## Exact changes and cadence

Only two existing T4 test files changed this continuation:

- `tests/agents/slo_agent/herdr/test_visualizer_lifetime_acceptance.py`: add
  `tmp_write` to the real sequence-failure × split/rename/run composition (3 cases).
  The real NamedTemporaryFile creates the contained sibling; only that instance's
  `write` raises. The real AtomicFileWriter handles failure/removal. Assert write
  reached exactly once, temporary file removed, previous destination unchanged,
  reporter authority revoked, shared transport still open, queued operation not
  admitted, immutable ledger unconsumed and executable capture empty. Existing
  `write` case remains historical **file fsync** failure, not literal write proof;
  `fsync` is directory durability warning and overflow remains unchanged.
- `tests/agents/slo_agent/herdr/test_visualizer_acceptance.py`: add
  `test_public_viewer_joins_already_admitted_report[False,True]`. Actual reporter
  batch A reserves durably and enters registered executable, public viewer queues
  behind its shared transport lock, same/changed-generation B publishes, then A
  releases. A's exact old identity is confirmed; no lifecycle/restore/display ack
  credits B, B remains pending, no stale A follow-up executes. Actual log is exactly
  report-agent → split → rename → run. Viewer returns submitted, not painted/running;
  command resources and pending registry drain. No mocked transport invocation.

Each composition was tested with its surrounding module before the next edit.
Both initially passed existing correct production behavior: **initial green
coverage**, not invented production RED/GREEN. No production edits were needed.
A later static annotation correction introduced a test-only runtime defect:
`_TemporaryFileWrapper[str]` is not runtime-subscriptable on 3.11. Quoting the
annotation fixes it without Any/cast/ignore. Original failing log is retained;
all final gates below ran after that correction. No assertions weakened or skips.

## Finite whole-T4 requirement map

Paths in this table abbreviate `tests/agents/slo_agent/herdr/` as V.
All listed tests ran in the fresh package gate unless explicitly surrounding.

| Contract / decision | Owner and passing evidence | Status |
|---|---|---|
| D 7.2 exact envelope, failed/absent/malformed/non-UTF8 JSON, wrong types/error envelope, empty/control/category-C/128-byte bounds, unrelated fields | visualizer `_parse_split_pane_id`; V/test_visualizer.py parser matrices; real oversize/failure in acceptance | CLOSED |
| Captured-owner no-focus split, fixed label, single plain-slo run string; no caller shell data, no missing target/slug | `_viewer_command`; test_viewer_commands, test_builder_rejects_invalid_identity, test_builder_rejects_missing_pane | CLOSED |
| D 7.4 reserve before await; unknown split retained; known pane before label; label rejection continues; run failure/timeout never retries | `_launch_or_reuse`, `_split_and_submit`, `_mark_uncertain`, `_label_and_submit`; test_split_retains_result, test_public_retained_outcome, test_public_timeout_retains_effect, test_ordinary_exception_retains_manual_recovery | CLOSED |
| Repeated/simultaneous requests, shared waiter shield, task error retrieval and identity-only callback removal | `invoke`, `_on_launch_done`; test_simultaneous_then_retained, test_cancelled_waiter_does_not_cancel_shared_launch, test_done_callback_identity_and_retrieval | CLOSED |
| Immutable one-shot split/rename/run ledger, stale reservation, closing/revoked/unknown target, completion cannot renew | `_admit_viewer_operation`, HerdrViewerAdmission; test_operation_is_consumed_once, test_operation_refused, test_completion_guards_preserve_reservation, test_send_uses_real_transport | CLOSED |
| D 7.5/B 7.13 live authority under shared lock, all seven facts × three queued operations | test_queued_operation_revocation (21); actual T2 transport and registered fake | CLOSED |
| Already-admitted effect versus newly refused public request; later commands suppressed, no rollback/resend | test_admitted_effect_survives_but_new_request_is_refused (21) | CLOSED |
| Real counter tmp.write/file-fsync/directory-fsync/overflow failure revokes queued split/rename/run without closing shared transport | test_real_sequence_failure_revokes_queued_viewer (12), including NEW 3 literal write cases | CLOSED |
| Opposite G2 viewer lock → durable queued A → B → release, same/changed generation; close/cancel/timeout | test_operational_viewer_supersedes_queued_report (8); original two release plus six continuation-30 cases preserved | CLOSED |
| Already-admitted report A accounted, no B acknowledgement/no remaining A commands, composed with PUBLIC viewer | NEW test_public_viewer_joins_already_admitted_report (2), real batch/counter/transport/executable | CLOSED |
| Close cancels/joins owned launches, repeated cancellation, multiple parents, known-pane retention, no shared transport/pane close | test_close_joins_pending; test_repeated_close_cancellation_joins_all_parents (3), real reap with explicit delay barrier | CLOSED |
| D 7.5 one lower-layer existing-file/schema reader; ordinary slug and UUID; invalid/missing/malformed/OS failures without payload logging | orchestrator/context_reader.py; test_context_roundtrip, test_unavailable_context, test_invalid_identity, test_os_error | CLOSED |
| Existing loader delegates, no second parser, ordinary discovery unchanged | workflow_visualizer_loader.py; test_context_delegates_to_shared_reader and complete existing loader module | CLOSED |
| No focus/query/replacement/close/resend, no duplicate map/subscriber/process owner; no await between admission and tracked spawn | Exact argv/capture assertions above; source audit of visualizer and service.py `_invoke_locked` (lock → try_admit → create_task → first await); no changes to shared transport | CLOSED |
| Required reads and exact task regressions | Audit and receipts below | CLOSED |

`active_reporter` explicitly supplies positive activation/lease policy facts; these
compositions acquire the real sequence lease where durability matters. They do
not claim real startup activation or mounted session eligibility. T2 package tests
cover shared transport/authority. Session eligibility, default-root/history checks,
plain-slo availability policy, destination selection, attached/detached caller
wiring and notices are **T5**, not missing adapter responsibilities. Mounted full
journey, two-process native restore, documentation integration and separately
approved supported-release/paint are **T6**. T4 technical readiness does not move
those obligations into this lane or claim they have passed.

## Completed read audit and reconciliation

Canonical read-only root H:
`/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`.

- Actual AGENTS.md 1–510 and 511–1013; actual CLAUDE.md; root RESEARCH.md;
  actual docs/RESEARCH.md 1–633; Makefile, pyproject.toml, .python-version;
  current routing.md, scope-plan.md, t4-code-test.md, t4-final-29.md, t4-g2-30.md.
- H/D **entire 1–711**, exact T4 task definition/acceptance at 163–199 and
  exact allocated D04–D07 samples **2109–2400**. B 235–654 (queue/close,
  transport/privacy, sequence, publication/accounting, lock-held admission/G2),
  B **2077–2221** (complete final authority/ownership/tests). C **1476–2045**
  (session activation/close, monotonic shutdown, retained ownership and final
  local-drain contracts relevant to T4). No claim of re-reading all unrelated
  restore-store/inbox implementation sections in this continuation.
- Entire overview, both subordinate legacy integration/publication documents,
  accepted independent-review-turn4.md and finalization-receipt.md. Accepted
  review is specification acceptance only; legacy focus/current-pane/model-label
  recommendations do not override final B/C/D contracts.
- KB Welcome.md, actual slo/README.md (no index.md), complete gotchas.md;
  skills-and-kb.md, tui-cli-session.md, headless-workflow-orchestration.md.
  Initial combined KB output truncated its beginning; Welcome/README/gotchas
  were then read individually in full. No missing-read deferral remains for T4.
- Full selected committed skills: engineering routing/testing/ownership; generic
  coding-rules, code-test-loop, declarative-method-structure; Python root,
  build-domain-features (1–800/801–1525), build-application-services, declarative,
  named arguments/types and method-docstrings; complete Textual recipe; exact
  Code-Test-Review workflow and shared workflows/SKILL. Routing.md remains the
  source-tier/override/exclusions record. Database examples add no database here.
- Actual viewer and all four viewer test files; context reader/tests and loader
  delegation/diff; AtomicFileWriter, sequence reservation, reporter admission,
  current acknowledgement and actual old-effect accounting; real transport
  lock-held spawn registration; isolation/terminal/fake capability guard and
  approved fallback script. One mistaken transport.py probe found no file;
  actual transport is in service.py and was inspected. One malformed parallel
  tool invocation read nothing; corrected individual reads above supply evidence.

Final source reconciliation: existing adapter owns its one attempt map and one
pending registry; T2 owns shared transport and reporter authority; reader owns
only existing orchestrator_context.json parse; loader delegates. No production
changes this continuation, no new DAO/service owner. The current task definition
allows adapter test composition separate from T2's original test_cli_transport.py:
new assertions reside in the related T4 acceptance files and the exact prescribed
transport test module is also rerun. No requirement omitted because its illustrative
test name differs. Shared documentation/KB updates remain integration-owned under
the restricted write set; no new runtime architecture was introduced here.

## Exact commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`, branch
`feature-94-herdr-integration`. `pyenv which python` resolved
`/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7; `make test-env`
returned `fallback`. No installation/environment creation. P below is exactly
`bash docs/implementation/94-herdr/t1-dao-check.sh` (adds the existing DAO/projection
modules). It uses approved fallback exports, pre-import/per-test HERDR stripping,
forced disablement, real-terminal guard and independent per-test fake spawn
permission. Only registered contained regular executables/capture/barrier files;
no system symlinks, live Herdr, real provider or OS window.

All prefixes are under this document's directory, with `.log` and `.exit`:

| Prefix | Command after P | Result |
|---|---|---|
| t4-31-write | tests/agents/slo_agent/herdr/test_visualizer_lifetime_acceptance.py tests/agents/slo_agent/herdr/test_visualizer_lifecycle.py | 137 passed, 2 warnings, exit 0 |
| t4-31-admitted | tests/agents/slo_agent/herdr/test_visualizer_acceptance.py tests/agents/slo_agent/herdr/test_reporter_compositions.py | 86 passed, 2 warnings, exit 0 |
| t4-31-final-compositions | tests/agents/slo_agent/herdr/test_visualizer_lifetime_acceptance.py tests/agents/slo_agent/herdr/test_visualizer_acceptance.py | 12 failed, 111 passed, exit 1; test annotation TypeError, not product defect |
| t4-31-corrected | same two files | 123 passed, 2 warnings, exit 0 |
| t4-31-package | tests/agents/slo_agent/herdr tests/agents/slo_agent/orchestrator/test_context_reader.py tests/tui/test_workflow_visualizer_loader.py | **1027 passed, 4 warnings, exit 0**, 64.93s |
| t4-31-regressions | tests/agents/slo_agent/history/test_atomic_io.py tests/agents/slo_agent/orchestrator/test_bootstrap.py tests/agents/slo_agent/orchestrator/test_spawn_env.py tests/tui/test_visualizer_launcher.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_workflow_visualizer_loader.py tests/agents/slo_agent/orchestrator/test_context_reader.py | **214 passed, 2 warnings, exit 0** |
| t4-31-task | tests/agents/slo_agent/herdr/test_visualizer.py tests/agents/slo_agent/herdr/test_cli_transport.py tests/agents/slo_agent/orchestrator/test_context_reader.py tests/tui/test_workflow_visualizer_loader.py | **138 passed, 2 warnings, exit 0**; exact tasks.md list |

Package count includes concurrent disjoint T3 additions; this lane added exactly
five cases, not 29. No skips/deselections reported by these bounded commands.

- `t4-31-format.log`: `poetry run black` only the two changed tests (then lifetime
  file after annotation change). Final quoted annotation requires no format change.
- `t4-31-black`: `poetry run black --check src/agents/slo_agent/herdr/visualizer.py src/agents/slo_agent/orchestrator/context_reader.py src/tui/workflow_visualizer_loader.py tests/agents/slo_agent/herdr/test_visualizer*.py tests/agents/slo_agent/orchestrator/test_context_reader.py tests/tui/test_workflow_visualizer_loader.py` — 9 files unchanged, exit 0.
- `t4-31-diff`: `git diff --check` — exit 0; tracked loader/test diff also read;
  untracked viewer/test contents reviewed directly (git diff does not include them).
- `t4-31-coreutils`: `dpkg -V coreutils` — **empty output, exit 0**, rerun after
  final task regression. No host anomaly.
- `t4-31-lint`, `t4-31-lint-final`, `t4-31-lint-verified`:
  `poetry run mypy src/ tests/` — respectively 302/66, 301/65, **300 errors/64
  files**, exit 1. First had this lane's wrapper annotation error plus a concurrent
  T3 provider typing error; final verified receipt has neither. No T4 diagnostic,
  no new ignore. Existing global failures remain **unwaived**, not green.

Integrated `make test`/`make smoke` is intentionally not run: latest inspected
`t3-code-test.md` still withholds T3 technical READY. User orders full make after
both T3/T4 closure. Do not treat this bounded handoff as permission to skip that
integrated gate or independent review/completion. T4 has no remaining assigned
bounded executable/read/regression unit; overall feature gates remain open.
