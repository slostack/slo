# T5 continuation 62 — READY: bounded headless/scheduler author audit

**READY only for this finite read/exclusion/test-map assignment.** This is Code-Test author checking, NOT independent review, full Step-1 acceptance, complete T5 approval, or release acceptance. The separate viewer race and final full-suite/static gates remain explicit below.

Same unfinished workflow turn 1: started 1, completed 0, historical partial 1, dispatch 62, retries 0. Effective turns and dispatches unlimited; old numeric limits do not apply. No agents dispatched here.

## Owned changes and evidence classification

- Added only `tests/cli/test_headless_exclusions.py`: four cases across sub-agent, detached launch, compatibility relaunch and command-adoption relaunch. Actual production caller/environment construction reaches a recording workload-spawn boundary; no agent workload is executed. Existing helpers supply isolated handle/capture roots.
- Added this report and `t5-62-*` receipts. No production, existing test, shared status, viewer, specification, global or other-worktree edits.
- Genuine **coverage gap**, not a discovered production defect: existing spawn-env tests asserted unrelated-variable rejection, secret filtering and allowed settings; caller tests asserted selected forwarded fields, but none explicitly asserted inherited HERDR exclusion across these launch paths. New tests pass immediately. No fabricated RED or production repair claimed. Had they failed, production changes would have remained with the authorized production owner.

## Finite source → test exclusion map

All paths below are relative to this checkout. The environment behavior is not broad inheritance for orchestrator children.

| Path / owner | Actual construction and exclusions | Executable proof |
|---|---|---|
| Shared `orchestrator/spawn_env.py::build_headless_child_env` | Starts from `_allowlisted_parent_env`, not `os.environ.copy()`. Exact basics: PATH, HOME, LANG, TERM, PYENV_ROOT, PYENV_VERSION. Uppercase `SLO_` settings pass unless their uppercase name contains KEY/TOKEN/SECRET/PASSWORD. Explicit exceptions: SLO_PLUGINS_DISABLED and SLO_OPENROUTER_API_KEY. HERDR names match neither allowlist; PYTHONPATH and unrelated variables do not pass. Workflow ID and nonempty trusted caller extras are then added. | `test_spawn_env.py`: exact basics, nonsecret SLO settings, plugin disable, four secret markers, PYTHONPATH/unrelated rejection, workflow/extras and empty extras. `test_openrouter_preparation.py::test_child_environment_forwards_only_openrouter_key_exception` preserves the explicit credential exception. |
| Sub-agent `process.py:337–381`, `_build_child_spawn_env` → `run` | Shared builder; extras only SLO_PARENT_PID and optional canonical SLO_CAPTURE_DIR. Actual create_subprocess_exec gets `env=child_env`. No HERDR reinsertion. | Existing `TestSubAgentProcessSpawnEnvironment` verifies actual spawn kwargs, secret rejection and parent/capture identity; new `test_subagent_excludes_herdr_at_spawn` explicitly rejects HERDR names at that same call and preserves timeout/parent environment. |
| Detached `launch_tool.py::_spawn_and_patch`, 286–332 | Shared builder with workflow ID; same mapping passed to injected/default spawn. Capture writer receives the explicit OpenRouter credential separately; it does not broaden workload inheritance. | Existing `TestAllowlistedEnv` and `TestLaunchWorkflowHappyPath`; new `test_detached_launch_excludes_herdr_at_spawn` drives the real tool, checks one spawn, absent HERDR, retained timeout/workflow ID and unchanged parent. |
| Relaunch `relaunch.py::invoke`, 259–287 | Shared builder with original workflow ID; explicit env at compatibility spawn. | Existing `test_invoke_preserves_workflow_id_env`, argv/resume and safe-error tests; new `test_relaunch_excludes_herdr_at_spawn[False]`. |
| Relaunch `relaunch.py::spawn_for_adoption`, 91–113 | Same shared builder at the command-owned adoption API; off-loop capture opens and explicit env at spawn. This second entry point must not be missed by auditing only invoke. | New `test_relaunch_excludes_herdr_at_spawn[True]`; existing append-lease cancellation/late-capture cleanup and two-process reservation tests retained and rerun. |
| Scheduler `scheduling/runtime/subprocess_runner.py:112–139` | Deliberately different: new dictionary of every inherited pair except `key.upper().startswith("HERDR")`, passed at the actual subprocess call. No mutation of parent; no orchestrator allowlist substitution. This follows the explicit user all-HERDR-prefix contract, broader than C7.2's historical HERDR_ spelling. | Existing `test_scheduler_child_drops_inherited_herdr_environment[False,True]` executes a NEW regular temp-owned child for fresh and resume, emits presence booleans only, rejects four historical keys plus HERDR_TEST/herdrFuture/HERDR, preserves synthetic SLO/provider/OTHER_HERDR_TEST and compares the complete unchanged parent dictionary. |

The shared builder's `extra` argument is trusted and can add arbitrary nonempty names; this audit does **not** misdescribe it as a universal denylist. Inspection of the actual callers above establishes that none passes HERDR extras. `SLO_HERDR_DISABLED` is a SLO setting, not a HERDR-prefixed pane identity, and may be forwarded. No claim that all provider credentials pass the orchestrator allowlist: the OpenRouter exception is explicit; scheduler preserves all unrelated values instead.

The current checkout's child argv is `sys.executable -m src.cli`, not the newer KB's `-I` form. Existing tests explicitly assert this checkout contract. No import-isolation change was smuggled into this audit; KB main-branch history is not source evidence for this feature checkout.

## Native restore and bootstrap

`HeadlessRunner._invoke_with_signal_owner` assigns `_session` before calling `start_external_reporting()` without interactive=True, and before stream drain. Session `start_external_reporting` defaults False; `_prepare_herdr_capture_inputs` returns ineligible before path/history preparation when noninteractive, and `_herdr_capture_eligible` also requires interactive activation. Standard bootstrap provenance therefore cannot make headless native-restorable.

`orchestrator/bootstrap.py::attach` checks already-agent/already-pool first, records pristine permission and policy sources before building tools, rechecks before attachment, and finishes exact provenance afterward. Headless bootstrap withholds detached launch/status tools. Existing `test_bootstrap.py` covers early returns/tool sets and identities. `test_session_publication_isolation.py::test_standard_origin_interactive_gate[False,True]` proves legitimate headless provenance still has no restore capture; injected-Faux provenance refusal remains separate.

Actual config-backed runner/Faux/registered fake-Herdr proof is in `test_headless_herdr.py::test_config_backed_faux_headless_never_advertises_restore` and `test_headless_parity.py::test_enabled_disabled_whole_jsonl_parity`: factory used, not injected session/agent; noninteractive/no capture; no --herdr-restore on captured wire; synthetic secret absent; enabled capture changes and disabled capture does not. Ordinary headless execution is allowed to report in a pane; automatic prompt replay/native restore is not.

## Reconciled finite family requirements

| Requirement | Existing exact proof, inspected and rerun |
|---|---|
| Adoption/start/close/final-drain ordering; completed/failed/aborted | `test_headless.py::test_reporting_lifetime_surrounds_headless_run` (three kinds), exit-code tests; actual runner invoke outer finally closes then finishes retained cleanup, credential cleared in further finally. |
| Activation ordinary fault/cancellation | `test_activation_exit_restores_signal_owner`: exact original ordinary exception or existing abort exit 2, signal/catalog and reporting cleanup. Session lifetime tests separately exercise actual retained activation/public cancellation and close races. |
| Preparation before adoption fails/cancels | `test_openrouter_preparation.py`: real dispatch/session/status/notifier failure with one identity/no inference; preparation cancellation and simulated SIGTERM restore signal and emit one abort; successful preparation enters ordinary stream once. No reporter exists before adoption. |
| Setup/status/notification original error | `test_adopted_setup_and_terminal_fault_restore_signal` five boundaries. These are orchestration proofs, not claims of successful persistence after a failing owner. |
| Optional cleanup and diagnostic faults | `test_reporting_cleanup_preserves_original_outcome` eight cases; `test_process_cleanup_preserves_original_outcome` six cases; `test_watchdog_stop_fault_preserves_terminal_status` three terminal kinds. |
| Combined cleanup versus terminal error/cancellation | `test_terminal_error_survives_combined_cleanup_faults` four cases: status/notification × ordinary/cancellation, combined watchdog/signal/catalog/reporting-close/final-drain faults; exact original exception identity and terminal JSONL retained. No unbounded errno/cartesian matrix added. |
| Complete JSONL parity | `test_enabled_disabled_whole_jsonl_parity` parses EVERY stdout line and compares entire ordered event objects, with no normalization/filtering. This is a successful Faux submission parity test; failure/abort behavior is covered separately by runner terminal/fault tests, not mislabeled whole-stream parity for every outcome. |
| Real retained child/lease, GC, repeated cancellation | `test_headless_retained.py::test_runner_retains_child_and_lease_until_final_drain[False,True]`: real runner/session/reporting/sequence lease/registered fake child, real activation, failed initial reap and close, final barrier, weakref-only owner observations after GC, contender refusal, repeated cancellation, successful final reap versus persistent pending cleanup. Exactly one captured activation command, no re-admission/remote resend. |
| Final local drain evidence/ownership | Session `finish_retired_reporting_cleanup` caches one task; drained close returns, retained close permits one final local attempt, persistent retention waits rather than falsely succeeds. `test_session_lifetime.py` covers close/start/drain cancellation, getter/outcome defects, cached attempts, lease-only retention and collectable remote-only uncertainty. Successful local cleanup does not erase remote uncertainty. |
| Fleet status gate | `TestHeadlessRunnerDrainGate`: status withheld for unresolved fleet, no-store no-op, matching child recorded, recycled/unreadable PID never signalled. Signals/reaps injected; no live fleet touched. |
| Notifications/logging | `TestHeadlessRunnerWorkflowNotifications`, `TestHeadlessNotifyEndToEnd` real temp inbox including failing enqueue, and headless events/logging/watchdog/request modules. Optional Herdr diagnostics remain stderr-only fixed text. |
| Child/scheduler exclusions | Explicit map above; four new launch cases and retained actual fresh/resume scheduler cases. |

Continuation54 first-increment gaps are reconciled by 55 signal ownership, 56 optional close isolation/config-backed composition, 57 process/watchdog faults, 59 retained-runner proof, 60 exact parity/combined faults and 61 truthful weakref/task narrowing. The 61 retained typing repair remains untouched. Historical passing counts are not substituted for this run.

## Required-read closure for this bounded assignment

Actual tool-output reads completed, not inferred from prior READY prose:

- On-disk AGENTS.md 1–1013 in two bounded ranges; CLAUDE.md 1–65; root RESEARCH.md; docs/RESEARCH.md 1–633 in two ranges. Frozen routing.md and scope-plan.md 1–180 read without edits; t5-code-test current/historical family summary and all available finite family handoffs 54,55,56,57,59,60,61. There is no separate headless58 Markdown handoff in the directory; 59 records that interruption. Initial oversized concatenation lost its prefix; routing/scope and 54/55 were reread separately. No truncated prefix is counted as read.
- Committed skills selected by frozen routing: engineering routing/testing/ownership; coding rules/code-test-loop/declarative/code-design/naming/test-verification/solution-design; Python conventions/named arguments/docstrings/declarative/application structure/build-domain/build-application-services/test-graphs-and-agents/switch-environments; product Typer and Textual; locate-KB; exact workflow SKILL and code-test-review.md. Long domain and Textual files were completed by offsets. Generic database/web/migration examples do not impose those stacks; no new design artifact/agents or operator Command scaffolding was introduced.
- KB read-only: Welcome, actual slo/README, gotchas, skills-and-kb, tui-cli-session, headless-workflow-orchestration; os ROLE then README and workloads-services-resources. Historical paths/timeouts/argv are not substituted for current source. No KB/live-state writes authorized or made.
- Build/safety: actual Makefile, .python-version, pyproject, approved t1-dao-check.sh; tests/state_isolation.py and conftest.py complete; actual FauxChatModel. Autouse pre-import/per-test isolation, disabled default, independent registered-file Herdr spawn capability and real-terminal guard remain active.
- Canonical read-only root `/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`: **C (`94.b.2-session-publication-and-native-restore.md`) complete 1–2175**, including 7.2 headless/scheduler, 7.9 provenance, 7.11 activation, 7.13 final drain and 7.14/section8 boundaries; exact T5 tasks allocation 195–241 and **all attachments 2401–3720** in three bounded reads. B relevant interface/gate/queue/transport/shared-lock 180–419 and safety/final-helper/revocation/lease-order/tests 1872–2221; D complete 1–711; accepted independent-review-turn4.md complete. That review accepts specifications only, not this implementation.
- Current affected source: full headless runner, scheduler subprocess runner, bootstrap, shared spawn_env (including isolated capture-writer environment); actual subagent spawn and detached spawn calls; both relaunch entry points and late-capture cleanup; session activation/publication/close/final-drain/capture gates 2280–2849. Tests: complete headless.py, herdr/parity/retained/lifetime, bootstrap/spawn-env/scheduler/preparation modules; actual caller-specific process/launch/relaunch test sections and new exclusion module. Read scope is the affected family, not every unrelated function in the repository.

No remaining required read is deferred for this bounded headless map. TUI replacement/inbox/viewer implementation auditing and independent full-scope review remain separate assignments, not recurring prerequisites used to keep this family open.

## Actual commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified `PYENV_VERSION=slo-harness pyenv which python` → `/root/.pyenv/versions/slo-harness/bin/python`; Python **3.11.7**. No installation/venv change. All pytest commands use the approved helper with test fallback, SLO_HERDR_DISABLED=1, terminal suppression and DAO/projection tests included in counts. Full commands are in adjacent `.command` files; full output and exit in `.log`/`.exit`.

| Stem | Result |
|---|---|
| t5-62-exclusions-initial | First two relaunch cases plus helper foundations: 64 passed, 2 warnings, exit 0 |
| t5-62-exclusions | All four exclusion cases plus foundations: 66 passed, 2 warnings, exit 0 |
| t5-62-required | Required headless, scheduler, bootstrap, spawn-env, process, detached launch, relaunch, session lifetime and provenance partition: **435 passed, 18 warnings, exit 0**, 13.91s |
| t5-62-preparation | Headless preparation compatibility partition plus foundations: **71 passed, 2 warnings, exit 0** |
| t5-62-black | Black --check new test: one file unchanged, exit 0 |
| t5-62-types | mypy --follow-imports=silent new test: no issues in one source file, exit 0; NOT global lint |
| t5-62-diff | git diff --check: silent, exit 0; new untracked test separately read in full and captured in t5-62-new-test.diff |
| t5-62-coreutils | dpkg -V coreutils after suites: **silent**, exit 0 |

The required partition's exact file list is preserved in `t5-62-required.command`. Counts overlap the helper's 62 foundation tests and must not be summed into unique coverage. No production RED occurred; no assertions/skips/timeouts were weakened. New tests record spawn arguments rather than running agent processes; scheduler and retained-child tests use only their existing contained regular fake files. No real providers, Herdr server or terminal windows.

## Explicit separate gates / limitations

- Viewer acceptance race from t5-60-full remains outside this write scope: `test_operational_viewer_supersedes_queued_report[False-release]` timed out waiting for `_command_lock._waiters`. This audit does not diagnose, repair, waive or claim another lane's repair. No viewer edits.
- No full nine-minute make test, smoke or global lint rerun here, as requested. Latest historical full failure and unwaived **299 errors/63 files** baseline remain historical evidence; scoped mypy is not global green. Final unchanged-integrated-snapshot gates belong to the completion owner.
- No TUI replacement/inbox/caller acceptance, T6 64-case matrix, two-process interactive native restore, live Herdr compatibility/paint, or independent review is claimed.
- READY means the finite headless/scheduler required-read and exclusion audit/test map is ready to hand off **except those explicitly separate race/final gates**. It does not permit bypassing them to claim feature completion.

No commits/push/PR/reset/clean/stash, agents, global changes, live-system changes, specification writes or other-worktree edits. All prior partial work preserved.
