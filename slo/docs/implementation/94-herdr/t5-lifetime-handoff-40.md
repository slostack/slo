# T5 finite SESSION LIFETIME family — READY for technical handoff

Continuation 40, same unfinished workflow turn 1: started 1, completed 0,
historical partial 1, dispatch 40, retries 0. User turn and dispatch limits are
unlimited; historical limits are void. No agents were spawned. This is a bounded
technical family handoff, NOT all-T5 completion, independent review, release
acceptance or a green static gate. Independent review remains a later phase,
not an unclosed row in this family.

## Scope and actual changes

Preserved all prior work. No TUI/headless wiring, commits, push, PR, reset, clean,
stash, global/KB/live/specification/other-worktree edits occurred.

- `sessions/service.py::_start_herdr_once` now contains defective inner
  `CancelledError` as an activation failure. Its retained task is never cancelled
  by public waiters. This lets the public waiter join close before re-raising its
  own cancellation. Previously `.result()` escaped before close in this composed
  case. Change: one exception clause plus its rationale; no new task owner.
- `herdr/dao.py::HerdrReporterProtocol.build_visualizer` returns the concrete
  viewer or raises fixed unavailable, matching canonical B 7.1.
- `herdr/service.py::NullHerdrReporter.build_visualizer` is annotated `NoReturn`.
  This minimal annotation correction is the only change in that support file.
  Runtime remains the existing fixed `HerdrRestoreUnavailableError`; it never
  returns None. No cast, ignore, nullable protocol or replacement protocol.
- `test_session_lifetime.py` adds seven parametrized cases and replaces the
  candidate composition's 30 scheduler yields with pool-entry/release and final
  reporting-entry Events. Existing assertions were retained.

## Complete finite family mapping

All test names below are in `tests/agents/slo_agent/herdr/test_session_lifetime.py`.
The entire module and surrounding partition pass on this snapshot. Prior rows
from continuation 39 are preserved and included rather than silently narrowed.

| Required branch | Passing evidence |
|---|---|
| Disabled/outside, no task/capture/assembly | `test_prepare_disabled_does_not_prepare_capture`, `test_disabled_activation_allocates_no_task` |
| Invalid identity, no capture | `test_invalid_identity_never_prepares_capture` |
| Suppression permanent/repeated/future start; attempted activation refused | `test_suppression_is_permanent`, `test_suppression_rejects_attempted_activation` |
| Enabled close before start | `test_enabled_close_before_start_has_no_commands` |
| Actual preparation/activation/initial publication/shared transport | `test_enabled_preparation_assembles_after_capture`, `test_actual_enabled_activation_publishes_and_closes` |
| Factory/start/viewer failure and throwing diagnostic sink | `test_actual_factory_fault_retains_owner[factory,start,viewer]` |
| Exactly one activation; defective retained task results | `test_activation_is_once_and_retains_attempted_owner`, `test_failed_activation_task_is_accounted_by_close[RuntimeError,CancelledError]` |
| Close races preparation/start | `test_close_during_activation[prepare,start]` |
| Public repeated cancellation of start/drain | `test_public_gateway_repeated_cancel_joins_owner[start,drain]` |
| **Activation failure composed with public cancellation** | NEW `test_activation_failure_with_public_cancellation[RuntimeError,CancelledError]`: real factory assigns owner; explicit start barrier; repeated cancellation; close completed, sealed/drained transport, same reporter, revoked viewer authority before cancellation escapes |
| Multiple cancelled close callers | `test_close_cancel_shares_owner` |
| Viewer/reporter/transport/revoke/evidence RuntimeError and inner cancellation | Ten cases of `test_cleanup_fault_keeps_later_owners`; ordered later cleanup, cached conservative evidence |
| Viewer failure retains owner; ordinary close idempotence/order | `test_failed_viewer_close_retains_owner`, `test_close_revokes_and_joins_once` |
| Final drain ordinary/inner cancellation/evidence fault and contradictory getter | `test_final_drain_fault_is_retained`, `test_final_outcome_cannot_disagree_with_drained_getter[close,drain]` |
| Final drain absent/repeated/error; safe/late/persistent finish | `test_retired_drain_requires_completed_close`, `test_retired_local_drain_cached`, `test_finish_retired_cleanup_preserves_safe_close`, `test_finish_retired_cleanup_single_local_attempt` |
| Actual child + lease + GC, late reap / persistent defect | `test_session_retains_real_transport_and_lease_through_gc[False,True]`: actual registered fake executable, same process/sequence owner, lock contention, one accounting result, three reap attempts total, one final local attempt |
| **Lease-only session quarantine + GC** | NEW `test_lease_only_session_quarantine[False,True]`: actual pane lease; transport already sealed/drained with no child; failed unlock; weakrefs through explicit retained session root; competing acquire refused; exactly two unlock attempts (close, final), final result cached; late success permits acquire, persistent failure keeps lease locked; zero executable entries |
| **Remote-only uncertainty collectability** | NEW `test_remote_only_uncertainty_is_collectable`: real reporter/lease and session final cleanup; sticky uncertain + drained; no final drain task allocated; no remaining resource claim; weakrefs to session AND reporter cleared by GC after local references leave scope; zero executable entries |
| Candidate absent pool / own pool / repeat / history preserved / old pool untouched | `test_candidate_disposal_only_drains_candidate` |
| Candidate pool failure/cancel + diagnostic failure | `test_candidate_pool_cancel_and_failure` |
| **Candidate reporting fault/persistent retention plus independent pool disposal** | Strengthened `test_candidate_pool_disposal_with_reporting_fault[False,True]`: explicit pool-entry/release Events and final-reporting-entry Event, no bounded-yield scheduling guess; old pool untouched, candidate pool once; persistent reporting still pending |
| **Null visualizer semantics and shared return contract** | NEW `test_null_visualizer_contract[platform,unavailable]`: fixed unavailable error, NoReturn implementation, concrete viewer protocol annotation; runtime behavior unchanged |

The lease-only test's first failed run was a **test assumption error**, not
production RED: `fake_herdr` pre-creates an empty capture file. All resource/GC
assertions passed; only `not capture.exists()` failed in three cases. Corrected
assertion checks exact empty bytes/text. Those coverage additions pass without a
production fix. Candidate barrier strengthening also passed initially. Only the
activation cancellation regression required a production behavior correction.
Null RED tested annotation truth, not a previously returning-None runtime.

The explicit retained-session root proves session-level ownership, not the future
mounted app quarantine slot. Existing persistent-finish and actual child tests
prove pending final cleanup. No mounted `/new`/unmount acceptance is claimed by
these session tests.

## Canonical reconciliation and reads

Authority: read-only canonical root
`/root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr`.
B 7.1 explicitly says shared `build_visualizer() -> HerdrVisualizerLauncher`,
null raises a fixed unavailable error, and platform/unavailable callers must not
invoke it. C lifetime composition calls it only for `herdr`. The prior nullable
protocol was not the canonical runtime contract. `NoReturn` truthfully specializes
that protocol without importing the viewer into the null implementation.

Consumed routing.md, scope-plan.md, current t5-code-test and t5-lifetime-39;
AGENTS/CLAUDE and docs/RESEARCH supplied project context, root RESEARCH, actual
Makefile/helper/interpreter selection, source lifetime/protocol/null/real reporter
cleanup, tests and registered-fake containment/identity guards. Consulted KB
Welcome, slo README and gotchas read-only. Read checkout engineering routing,
ownership/testing, coding rules/cadence/declarative, Python root/DAO/application
service/declarative, exact code-test-review workflow and workflow SKILL. Generic
SQL/web examples add no dependencies. Relevant canonical C 7.9 session/candidate
lifetime and final-drain/7.14 contracts, exact T5 task body, B null/join contracts,
and accepted independent turn-4 decisions were consulted. This is not a new
whole-B/C/D or independent implementation review.

## Verification receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved `slo-harness` Python 3.11.7;
existing Poetry configuration, no installation/new venv. Helper is
`bash docs/implementation/94-herdr/t1-dao-check.sh`; it includes DAO/projection
checks, exports the reviewed safe fallback and invokes pytest `-m 'not e2e'`.
Inherited HERDR stripping, force-disable, independent registered-fake identity and
containment checks and real-terminal guard remain enabled. No live Herdr/provider
or real windows. Tests create no system symlinks or PATH stubs.

F = `tests/agents/slo_agent/herdr/test_session_lifetime.py`

S = `tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/orchestrator/test_bootstrap.py`

Receipt prefixes below live beside this file; each has `.log` and `.exit`.

| Exact command / stage | Receipt prefix | Actual result |
|---|---|---|
| helper + F, barrier strengthening | t5-40-barriers | 114 passed, 2 warnings; exit 0 |
| helper + F, activation RED | t5-40-activation-red | 1 failed, 115 passed, 2 warnings; exit 1; failed composed CancelledError case |
| helper + S, activation GREEN | t5-40-activation-green | 1184 passed, 11 warnings; exit 0 |
| helper + F, initial GC coverage | t5-40-gc | 3 failed, 116 passed; exit 1; pre-created capture assertion error only |
| helper + F, corrected GC coverage | t5-40-gc-corrected | 119 passed, 2 warnings; exit 0 |
| helper + F, null annotation RED | t5-40-null-red | 2 failed, 119 passed; exit 1 |
| helper + S, final surrounding | t5-40-final-surrounding | 1189 passed, 11 warnings; exit 0 |
| `make test` after final production/test formatting | t5-40-full | **7466 passed, 19 deselected, 408 warnings in 551.99s; exit 0** |
| `make smoke` | t5-40-smoke | 288 passed, 2 warnings; exit 0 |
| `make lint` | t5-40-lint | **299 errors / 63 files; exit 2**, unwaived |
| changed-file Black check (below) | t5-40-black | exit 0 |
| `git diff --check` | t5-40-diff | silent; exit 0 |
| `dpkg -V coreutils` after full and after smoke | t5-40-coreutils, t5-40-coreutils-final | silent; exit 0 |

Black command: `poetry run black --check src/agents/slo_agent/herdr/dao.py src/agents/slo_agent/herdr/service.py src/agents/slo_agent/sessions/service.py tests/agents/slo_agent/herdr/test_session_lifetime.py`.

`t5-40-lint-attribution.log` compares normalized diagnostic multiplicities against
`t5-39-lint-final.log`: **zero added, zero removed**. No new typing error is hidden;
299/63 remains red and unwaived. Full gate was required and run because activation
behavior changed. Earlier 7459/1182/288 receipts remain historical, not relabeled
as current evidence. All warnings remain in full logs. Source/test self-check
confirmed the finite map and small production diff; no independent reviewer ran.

## Distinct remaining families — not SESSION LIFETIME gaps

- **Capture/publication:** finish committed generation/capture reuse and revocation,
  complete supported mutation/persistence/startup/provenance boundary map, and
  publication hooks using existing usage facts (no per-event I/O or new counters).
- **Attention/run state:** operation/attention tokens, working across retries/tools,
  final usage before settlement, fixed human reasons and original result/error/
  cancellation preservation.
- **Headless/scheduler:** activate/close/final-drain in existing outer finally with
  credential cleanup/JSONL unchanged; actual scheduler spawn strips only HERDR keys.
- **App and viewer callers:** mounted retained quarantine slot and successor
  suppression, `/new` transaction, timer/session-keyed inbox lease transfer,
  monotonic shutdown, final prompt registration/disposition, both tracked viewer
  callers and platform-thread joining. No TUI wiring has been started here.
- Later integrated T5/T6 acceptance, 64-case cutoff matrix, two-process restore,
  independent review/completion and separately authorized live acceptance remain.

These are the already allocated finite families, not new unbounded requirements.
The static baseline is an explicit outstanding gate, not a reason to withhold
this authorized technical SESSION LIFETIME handoff.
