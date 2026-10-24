# Whole T5 author integration handoff 119 — REVISE (finite scope)

Author Code/Test reconciliation, NOT independent Review/Completion. Same unfinished
turn 1, started 1/completed 0/historical partial 1, supplied dispatch 119/retries 0;
unlimited turns and dispatches. No agents. No production/test changes, commits,
external actions, canonical/global/KB/live/other-worktree edits or destructive Git.

## Verdict

**Entire T5 technical READY is withheld for the exact D7.5 platform boundary
proof below and three existing contract-doc mismatches.** No new runtime defect
was established. This is not a capacity stop, a request for another blanket read
pass, resurrection of historical family blockers, or rejection because global
lint is red. The three substantive findings in 110 are corrected. The combined
family in 118 is closed. Do not rerun those families merely to recreate receipts.

### Remaining finite T5 work

1. **D7.5/A2 discovery-blocked and spawn-blocked platform evidence.** Canonical D
   lines 620–625 explicitly require `test_platform_launch_join` with
   before_commit/discovery_blocked/spawn_blocked/error/repeated_cancel and the
   existing spawn injection plus a discovery barrier. Actual
   `tests/tui/test_herdr_visualizer.py::test_platform_join_retains_thread_through_repeated_cancel`
   replaces all of `VisualizerLauncher.launch`. Actual
   `test_herdr_viewer_replacement.py::test_replacement_joins_actual_platform_thread`
   also replaces all of `launch`. These prove retained thread ownership, but
   cannot prove the real discovery-to-spawn continuation or at-most-one committed
   spawn at those separate boundaries. `test_async_platform_keeps_root_spawn_guard`
   proves guard traversal without either barrier. Searches across the current TUI
   Herdr tests find no discovery_blocked/spawn_blocked/test_platform_launch_join
   implementation; the full platform launcher suite has no thread/barrier case.
   Keep real `launch` executing, control discovery and the injected spawn separately,
   and assert join before replacement/unmount completion, no late notice, no spawn
   for rejected registration, at most one committed spawn and repeated cancellation.
   Reuse existing selector/registration/error tests where they establish an exact
   row; no new Cartesian matrix or live window is required. This is missing
   required T5 acceptance evidence, not a demonstrated production bug or T6 work.
2. **Touched contract documentation, still present in source:**
   `src/tui/app.py::_prepare_session_delivery` documents removed session/owner_id
   parameters instead of binding; `_publish_delivery_timers` documents session
   instead of binding/timers. `src/tui/visualizer_launcher.py::VisualizerLauncher`
   claims launch is its single public entry and all other methods are pure despite
   launch_async and owned thread joining. Correct these three docstrings. They
   are not T6 README/INSTALL/runtime-guide work. No behavior change is implied.

No fix was attempted: the outstanding behavioral item is a composed verification
increment rather than an identified <=50-line production defect. Source/tests
remain exactly snapshot 118. A next author increment can close the above finite
scope, run focused/surrounding gates, then fresh full/smoke/lint after edits. There
is no need to redesign owners or repeat all prerequisite reading.

## Authority and read coverage

H (read-only) = `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`.
Frozen `routing.md` and `scope-plan.md` remain authoritative for selected skills,
72 allocated samples, R1–R26/AC and T1–T6 boundaries. Their original PENDING text
is specification-phase history, not current implementation status.

Read closure is cumulative, not falsely relabeled as fresh ingestion: 88 records
complete B/C, exact tasks2401–3720 and accepted review; 100 records complete D and
gateway source/tests; 110 records full C/D/T5 attachments and accepted-review
closure; 117 records complete C7.9–7.14/D/T5/review reads; 118 explicitly completes
117's remaining frozen skills/KB/build and affected platform/inbox/multiple-parent
reads. Those unchanged receipts are reused as requested, not converted into
independent implementation approval. This continuation freshly read routing,
scope-plan, current entire t5-code-test ledger, 53 attention/usage, 62 headless,
82 INIT, 88 activation, 100 gateway, 109 migration, 110 audit, 111 corrections,
117/118 combined receipts; canonical T5 requirements/dependency allocation,
C950–1549 and2085–2175, D620–EOF. Supplied AGENTS/CLAUDE/docs RESEARCH remain
context; root RESEARCH was read from disk. Fresh shared routing/testing/ownership
skills and KB Welcome/gotchas were consulted. No new convention routing or design
ceremony is needed; full selected Python/DAO/service/Typer/Textual/Faux/declarative/
workflow skill reads remain recorded in118, not claimed freshly reread here.

Fresh source inspection: session2220–2949 (provenance/gateway/activation/publication/
close/capture), app shutdown/inbox/replacement/registry/shared runtime and touched
docstrings, launcher1–230, full renderer, service typed-result owner, headless
outer finally, scheduler exact prefix, bootstrap hooks. Actual platform test bodies,
combined all-owner assertions, multiple-worker test, and test inventories were
checked against the reports. No claim of independently rereading every unrelated
function or every assertion in all 140 files. Snapshot verification checks bytes;
it does not substitute for semantic evidence.

## Whole finite requirements → owners → executable evidence

Paths below abbreviate S=`src/agents/slo_agent/sessions/service.py`,
A=`src/tui/app.py`, Ht=`tests/agents/slo_agent/herdr/`, U=`tests/tui/`.
The detailed parameter rows in the linked finite receipts are retained; this table
reconciles their remaining dependencies rather than blindly chaining READY labels.

| Contract/method branch family | Current owner and tests | Disposition |
|---|---|---|
| C7.9 activation inputs: default/custom root, missing metadata, resumed/explicit workspace, resolution refusal | S `_prepare_herdr_capture_inputs`, `_resolve_herdr_capture_paths`; Ht/test_session_capture.py and test_session_publication.py | Closed;47/88, actual cached-path/source gates inspected |
| C7.9 begin/finish standard attachment, pristine/custom/injected/failed/early-return and mutation | bootstrap.py plus S provenance methods; Ht/test_session_publication{,_compositions,_isolation}.py, test_session_mutation.py; orchestrator/test_bootstrap.py | Closed; object identity, no general standard flag |
| C7.9 capture eligibility/pool/scalar order/aliasing/generation; usage/rename/fallback/catalog no churn | S `_capture_herdr_restore`, `_capture_herdr_pool`, `_adopt_herdr_capture`, `_withdraw_stale_herdr_capture`; Ht/test_session_capture.py, test_session_mutation.py, test_session_publication_compositions.py, test_session_publication_isolation.py | Closed; immutable allowed capture, invalidation distinct from legitimate commits |
| C7.9 inactive/projection/reporter/repeated diagnostic publication faults and no I/O | S `_publish_herdr_snapshot`; Ht/test_session_publication.py and test_session_publication_isolation.py | Closed; existing usage snapshot sole source |
| C7.9 prepare success/build/attach/name/cancel/root mismatch/deep copy | A `_prepare_replacement_session`, `_discard_replacement_session`; U/test_herdr_session_lifecycle.py | Closed;65, old subscription/queue intact before commit |
| C7.9 disposal none/pool/repeat/cancel/error | S `dispose_unmounted_session`, `_drain_unmounted_pool`; Ht/test_session_lifetime.py; mounted candidate cleanup tests | Closed; candidate-only pool, retained final drain |
| C7.9 commit safe/uncertain/error/repeated cancellation; old release before claim | A `_commit_replacement_session`, `_adopt_replacement_session`; U/test_herdr_replacement.py, test_herdr_activation_composed.py, test_herdr_viewer_replacement.py | Closed;111/118 close viewer-fault dependency |
| C7.9 captured lease, heartbeat/inbox callbacks, timer failure, late auth/viewer, postcommit UI/runtime faults | A transfer/release/renew/timer/shared runtime; U/test_herdr_init_{ownership,rollback,branches}.py, test_herdr_auth_capture.py, test_herdr_activation_{notices,cutoffs}.py | Closed behavior; two local docstrings remain |
| C7.9 four delivery modes; empty/closed/claim/advance/handler/ack failures and pending context/ack | A `_claim_and_handle_idle_inbox_message`, `_handle_inbox_message`, `_start_inbox_chat_turn`; U/test_herdr_inbox_disposition.py, test_workflow_receive_path.py | Closed; explicit bool, captured-store ack, durable context idempotency |
| C7.9 final local/queued/machine registration cutoff and admitted execution | A `_register_prompt_task`, local/queue callers; U/test_herdr_prompt_registration.py, test_herdr_inbox_cutoffs.py | Closed; exactly one task-assignment site, no await/hook inside final gate |
| C7.10 idle/active/attention/suspended/other-active/stale clear/end/closing | S operation/attention owners; Ht/test_session_attention.py, test_attention_boundary_closure.py, test_attention_auth_composed.py | Closed;53 plus captured modal88 |
| C7.10 real tools/retry/recovery/fatal/busy/abort/cancel/manual/startup/final usage | S run scope/usage commits; Ht/test_attention_{execution_composed,compaction_composed,preparation_races}.py; test_agent_usage_commit_regressions.py; integration/test_feature89_model_flows.py | Closed;53 final-snapshot qualification superseded by118 full gate, not a new accounting blocker |
| C7.11 once-only disabled/real/partial activation, close racing start, suppression before/after start, every cleanup owner | S start/close/suppress methods; Ht/test_session_lifetime.py, test_final_lifetime_closure.py; U/test_herdr_activation_composed.py | Closed;40/88 and current source |
| C7.12 dependency order | Existing T3 restore/T4 adapter feed session/app only in T5 | Satisfied; no new owner layer |
| C7.13 retained local resources vs remote-only uncertainty; one final drain, GC, repeated cancellation, persistent pending | S close/finish/drain; A selected+retired slots; Ht/test_session_lifetime.py; U/test_herdr_app_shutdown.py, test_herdr_viewer_retention_composed.py | Closed;118 actual child/lease composition, not mock-only evidence |
| C7.13 initializer reconcile/acquire/inbox/timer/activation/old close; captured binding rollback; join outside gate | A retained mount/shutdown/shared runtime; U/test_herdr_initialization.py, test_herdr_init_{ownership,rollback,branches}.py, test_herdr_activation_cutoffs.py | Closed;82/88 |
| C7.14 F1 four cutoffs, F2 quarantine, F3 gate order, F4 independent cleanup and throwing notices | U/test_herdr_all_owner_cutoffs.py, test_herdr_multiple_viewer_owners.py plus118 helper; exact original invoke/history refusal, store/session/owner release, shutdown-only timers, retired reporter close/drain | Closed;28 all-owner plus8 multiworker cases, actual retained resource fixture |
| C7.14 canonical UUID shared predicate/ordinary slug compatibility | sessions/identity.py, session/restore/CLI/viewer consumers; Ht identity/DAO/session tests, cli/test_herdr_restore.py and headless-request tests | Closed prerequisite retained; no duplicate regex/parser introduced |
| D persisted parent eligibility and post-await revocation | S `open_workflow_visualizer`, `_workflow_parent_is_persisted`, `_may_open_workflow_viewer`; Ht/test_session_visualizer{,_policy,_lifetime}.py | Closed;100 finite policy map and48 awaited-boundary cases |
| D attached/detached actual ingress and correct parent | A attached event and raw launch-result service delegation; U/test_herdr_attached_composed.py enabled/auto_off/unavailable × attached/detached | Closed;107/109 real gateway/shared transport/registered CLI, distinct detached parent |
| D typed service/renderer/registry consolidation | workflows/service.py returns HandleAdvanceOutcomeDAO; renderer schedule-only protocol; A registry; workflows tests/receive path/registry tests | Closed; obsolete names absent in actual source search |
| D registry duplicate/identity cleanup/failed notice reset/late result/multiple-worker failure | A `_schedule_visualizer_launch`, `_run_visualizer_launch`, `_cancel_visualizer_launches`; U/test_herdr_{attached,viewer_registry,viewer_replacement,multiple_viewer_owners}.py | Closed;111 corrections plus118 combined |
| D one destination, no enabled-failure fallback, five outcomes/manual reuse | launcher.launch_async + shared renderer; U/test_herdr_visualizer.py, workflows/test_workflow_renderer.py, test_herdr_attached.py | Closed;111 F3 conditional retained-pane/manual command |
| D platform offload/join real discovery/spawn boundaries | launcher `_launch_platform_joined` and real sync launch | **REVISE** exact missing proof above; no runtime failure established |
| C7.2 headless stdout/original result/terminal failures/adopted lifetime | cli/headless.py outer finally; cli/test_headless{,_herdr,_parity,_retained,_exclusions}.py | Closed;64/62 map, real retained child and exact JSONL parity |
| C7.2 scheduler fresh/resume exact prefix; child/detached/relaunch exclusions | scheduling/runtime/subprocess_runner.py and existing spawn_env/callers; test_runtime_helpers.py, test_headless_exclusions.py | Closed;111 supersedes62's incorrect broad-prefix description |

## Runtime/consolidation trace

CLI `_default` → TyperDispatch.tui resolves native reference before construction →
configured session → standard bootstrap provenance → mounted app shared runtime →
session activation → existing HerdrReporter/restore store/shared CLI transport/viewer.
Headless adopts session before noninteractive activation; outer finally closes and
finishes retained cleanup before clearing credential capture. No native headless restore.
Scheduler passes a copied environment minus exact case-insensitive HERDR_; other
launchers retain the existing allowlist rather than inheriting pane identity.

Session policy/history commits refresh private capture; usage/operation/attention
commits publish safe facts to the existing reporter. `/new` prepares candidate,
revokes predecessor, joins viewer workers outside the submission gate, transfers
captured delivery lease, closes, adopts synchronously, then starts shared runtime.
Unmount's irreversible prefix prevents new registration; admitted work keeps its
existing policy. Claim/advance cutoffs retain claimed bytes, not automatic replay.

Attached event and detached raw result converge on one app registry. Detached raw
text is parsed once by the service, returned as typed effects, then scheduled by
renderer. Async selector chooses platform/herdr/unavailable exactly once. Herdr
uses session persisted-parent gateway → existing T4 adapter/shared T2 transport.
OrchestratorContextReader stays below TUI; loader delegates. Renderer alone formats
both completion paths; submission is not viewer paint.

Actual recursive src search: no `LaunchResultOutcome`, `DetachedVisualizerLaunch`,
`handle_launch_result`, `_orchestrator_session_id_from_result`, `_pane_by_parent`;
only `_register_prompt_task` assigns an asyncio task to `_in_flight_task` (app1769).
109/110 deletion audit includes `_write_attached_visualizer_outcome`; no reason to
create a second parser/formatter/accounting/process owner. No obsolete-file deletion
was needed in119.

## Three audit110 findings and combined118 reconciliation

- F1: shutdown wraps viewer drain with `_shutdown_step`; replacement catches its
  ordinary failure and continues safe close/adoption; registry attempts all workers
  before raising, retaining failed handles. Source inspected.111 red/green tests
  plus118 real multiworker/retired-child/throwing-notice composition establish proof.
- F2: source now uses `key.upper().startswith("HERDR_")`; actual fresh/resume tests
  retain HERDR/HERDRFOO/herdrFuture and unrelated values.111 RED2 → GREEN124.
- F3: shared renderer says previous attempt, `if still present`, and exact captured
  parent manual command.111 RED2 → GREEN191. No query/focus/retry added.

118 supersedes117's exact lease/timer/retired reporter and original-session
invoke/history assertion gaps. It does NOT close the separately identified D
platform discovery/spawn gap:118 reread the platform suites, but those actual
bodies still patch all of launch. Neither full8205 nor a read receipt supplies a
missing boundary assertion. This is the substantive reason not to chain READY.

## Verification, unchanged snapshot and limitations

Cwd `/root/Code/slo-94-herdr-integration/slo`. Approved PYENV_VERSION=slo-harness;
existing3.11.7/Poetry fallback, no venv/install changes. Safe helper retains Faux,
HERDR stripping/default disable, independently registered temp regular fake
capability and real-window guard. No live providers/Herdr/windows.

Fresh119 commands (logs and exit siblings `t5-119-<stem>`):

- `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/agents/slo_agent/herdr/test_session_publication.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_herdr_visualizer.py tests/tui/test_app.py tests/tui/test_workflow_receive_path.py tests/tui/workflows tests/tui/test_visualizer_launcher.py tests/cli/test_headless.py tests/agents/slo_agent/orchestrator/test_bootstrap.py tests/agents/slo_agent/orchestrator/test_spawn_env.py tests/scheduling/test_runtime_helpers.py`
  — task: **470 passed,32 warnings,166.61s; exit0**.
- Same helper + `tests/agents/slo_agent/history/test_atomic_io.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/orchestrator/test_spawn_env.py tests/agents/slo_agent/orchestrator/test_bootstrap.py tests/cli/test_headless_request.py tests/cli/test_headless.py tests/cli/test_app.py tests/cli/test_typer_dispatch.py tests/scheduling/test_runtime_helpers.py tests/tui/test_app.py tests/tui/test_usage_status_bar.py tests/tui/test_visualizer_launcher.py tests/tui/test_workflow_visualizer_loader.py tests/tui/workflows tests/tui/test_workflow_receive_path.py`
  — surrounding: **532 passed,31 warnings,163.64s; exit0**.
- `PYENV_VERSION=slo-harness poetry run black --check $(cat docs/implementation/94-herdr/t5-118-python-files.txt)` — **140 unchanged,exit0**.
- `sha256sum -c docs/implementation/94-herdr/t5-118-snapshot.sha256` — **140 OK,exit0**.
- Sorted `git ls-files --modified --others --exclude-standard -- 'src/*.py' 'tests/*.py'`
  versus118 inventory — identical,exit0. No added unmanifested product Python file.
- Sorted full ` error:` lines of117 and118 lint logs compared with `diff -u` —
  silent,exit0. Exact diagnostic inventory unchanged; no normalization/ignores.
- `dpkg -V coreutils` — silent,exit0 after suites.
- `git diff --check` — final local hygiene receipt alongside this report.

Reused118 unchanged-product-snapshot gates: `PYENV_VERSION=slo-harness make test`
**8205 passed,19 deselected,626 warnings,763.10s,exit0**; `make smoke`
**288 passed,2 warnings,exit0**; `make lint` **295 errors/60 files,792 checked,exit2**.
These are reused receipts, not fresh119 full executions. Baseline is **UNWAIVED**,
not green and not a preclusion to technical T5 handoff. Counts overlap helper62
foundations and must not be summed. Warnings were not hidden. Source/test bytes
were unchanged throughout119; documentation-only finalization does not fabricate
new full-suite evidence.

## Next phase boundary

Close the two finite rows above, then entire T5 technical readiness can be assessed.
T6 remains separately required: full64 cutoff composition, two-OS-process native
restore, full journey/privacy acceptance, runtime docs and separately authorized
live supported-version/restart/pane paint. Independent full-feature Review and
Completion remain required afterward. No new 64-case requirement is imposed on
T5, and no live compatibility or release readiness is claimed.
