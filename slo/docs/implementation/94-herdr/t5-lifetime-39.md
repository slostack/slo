# T5 session lifetime 39 — INCOMPLETE

Same unfinished workflow turn 1: started 1, completed 0, historical partial 1,
dispatch 39, retries 0. User turn/dispatch limits are unlimited. No agents,
commits, external operations, live Herdr/providers/windows, global/specification/
other-worktree edits or destructive Git commands. Existing changes preserved.

## Delivered corrections

1. `herdr/dao.py::HerdrReporterProtocol` now declares the implemented
   `revoke_viewer_admission` and `record_publication_failure` methods and nullable
   `build_visualizer` return. No cast, ignore, replacement protocol or union escape.
2. Session close contains defective inner `CancelledError` separately from public
   waiter cancellation, at viewer, reporter, transport, revocation and evidence
   boundaries. Every later cleanup owner still runs. Public cancellation continues
   to join its retained task and then escape.
3. Final local drain contains inner cancellation/evidence failure as retained and
   uncertain, caches one attempt, and never reissues remote withdrawal.
4. Candidate disposal now closes reporting, drains its own pool in finally, then
   finishes retained reporting cleanup. Persistent reporting quarantine therefore
   cannot prevent candidate-pool disposal; it still prevents successful teardown.
5. Final transport outcome saying retained is not erased by a contradictory
   drained getter. A later successful transport outcome can supersede the earlier
   reporter-close resource state (the reporter normally still holds its lease).

All production increments were below approximately 50 lines and followed RED →
GREEN + surrounding tests before the next implementation increment.

## Exact finite map

Tests below are in `tests/agents/slo_agent/herdr/test_session_lifetime.py` unless
another module is named. Existing proofs were retained, not rewritten as passes.

| Branch | Evidence and status |
|---|---|
| Disabled/outside; invalid identity; no capture/assembly | Existing `test_prepare_disabled_does_not_prepare_capture`, `test_disabled_activation_allocates_no_task`, `test_invalid_identity_never_prepares_capture` pass |
| Suppression before start, repeat, future start after close, rejection after attempt | Existing `test_suppression_is_permanent`, `test_suppression_rejects_attempted_activation` pass |
| Enabled close before activation | NEW `test_enabled_close_before_start_has_no_commands` forbids factory construction and start task |
| Actual factory before build, reporter start after assignment, viewer assembly failure; throwing sink | NEW `test_actual_factory_fault_retains_owner[factory,start,viewer]` passes; real assembly outside injected failing boundary, owner retained, uncertainty sticky |
| Activation once and defective retained activation result | Existing activation-once and RuntimeError/CancelledError task-result regressions pass |
| Close during prepare/start | Existing deterministic barrier tests pass |
| Public start/direct-drain repeated cancellation | NEW `test_public_gateway_repeated_cancel_joins_owner[start,drain]`; retained work stays uncancelled and close joins |
| Public close multiple cancelled callers | Existing `test_close_cancel_shares_owner` passes |
| Viewer/reporter/transport/revocation/getter RuntimeError and inner cancellation | NEW 10-case `test_cleanup_fault_keeps_later_owners`; exact revoke/viewer/reporter/transport order, cached outcome; failed viewer or evidence retains resources |
| Final drain RuntimeError/inner cancellation/getter failures | NEW four-case `test_final_drain_fault_is_retained`; one cached conservative attempt |
| Final returned retention versus drained getter | NEW `test_final_outcome_cannot_disagree_with_drained_getter[close,drain]` passes |
| Local final drain absent/repeat/error, finish safe/late/persistent | Existing retired-drain and finish tests pass, including intentional pending cleanup and cancellation-resistant waiter |
| Actual child + actual pane lease + GC + late reap/persistent defect | NEW `test_session_retains_real_transport_and_lease_through_gc[False,True]`: actual registered fake executable/transport, actual lease contention, same process/sequence owner reachable from explicit retained session root after GC; exactly three reap attempts (command, close, final), exactly one executable entry and one accounting callback; late reap unlocks, persistent failure stays pending and locked |
| Candidate absent pool/pool/repeat/history/no old pool | Existing candidate disposal tests pass |
| Candidate pool failure/cancel + diagnostic failure | Existing two-case pool test passes |
| Candidate reporting failure/persistent retention plus pool disposal | NEW `test_candidate_pool_disposal_with_reporting_fault[False,True]` passes; old pool never called; candidate pool called once even while final reporting cleanup is pending |

### Precisely unclosed evidence / gates

- **Static gate remains red and unwaived:** 299 errors / 63 files. Exact normalized
  multiplicity comparison to `t4-31-lint-verified.log` (300/64) has zero added,
  one removed diagnostic. All six new service diagnostics are gone; fixing the
  shared contract also removes the baseline reporter return-type diagnostic.
- **Null visualizer semantic discrepancy:** actual `NullHerdrReporter.build_visualizer`
  has a `None` annotation but raises `HerdrRestoreUnavailableError`, as canonical B
  7.1 explicitly requires. It does NOT currently return None. This continuation
  preserves runtime compatibility and changes only the shared type. The user's
  parenthetical “null returns None” is not an observed runtime fact. A literal
  return-None behavior change and its regression are not delivered here.
- **Lease-only session quarantine/GC and remote-only collectability** are not
  independently proved by the new child+lease test. Reporter-level lease/unlock
  tests remain passing, but that is not a substitute for those session composition
  variants. The new test deliberately proves an explicit session retention root,
  not a mounted app slot.
- **Activation failure plus simultaneous public cancellation** is not composed in
  one test; ordinary factory/start/viewer failure and public repeated cancellation
  are tested separately. Candidate composition's scheduling check uses bounded
  event-loop yields, not an explicit pool-entry barrier; strengthen that evidence.
- Solo source/test self-check only; no independent review/completion phase occurred.

These are finite gaps, not a generic “remaining lifetime work” placeholder.
Capture/publication/attention, headless/TUI caller wiring, actual mounted quarantine
slot, repeated /new suppression, inbox and viewer caller acceptance are expressly
outside this family's requested edits and are not claimed complete.

## Commands, logs and exits

CWD `/root/Code/slo-94-herdr-integration/slo`; approved `.python-version` is
`slo-harness`; `poetry run python --version` reports 3.11.7. No installation.
Makefile fallback and `t1-dao-check.sh` reviewed; inherited HERDR stripping,
independent registered-fake spawn guard and real-terminal guard remain enabled.
No system symlinks or PATH binaries were written. Persistent test-only tasks are
cancelled only in fixture teardown; real fixture processes are then reaped and
fixture leases released.

F = `tests/agents/slo_agent/herdr/test_session_lifetime.py`

S = `tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/orchestrator/test_bootstrap.py`

Each receipt prefix below is in this directory with `.log` and `.exit` (format
commands additionally have log-only receipts). Test commands prepend exactly
`bash docs/implementation/94-herdr/t1-dao-check.sh` to F or S; helper always includes
DAO/projection tests, so focused counts include those tests.

| Command | Receipt prefix | Actual result |
|---|---|---|
| `make lint` before protocol edit | t5-39-protocol-red | 306 errors / 65 files; exit 2 |
| helper + S after protocol edit | t5-39-protocol-green | 1156 passed / 11 warnings; exit 0 |
| helper + F cleanup fault RED | t5-39-fault-red | 5 failed / 93 passed; exit 1 |
| helper + S cleanup fault GREEN | t5-39-fault-green | 1166 passed / 11 warnings; exit 0 |
| helper + F drain RED | t5-39-drain-red | 2 failed / 100 passed; exit 1 |
| helper + S drain GREEN | t5-39-drain-green | 1170 passed / 11 warnings; exit 0 |
| helper + F factory/start cancellation evidence | t5-39-boundaries | 108 passed; exit 0 |
| helper + F candidate RED | t5-39-candidate-red | 1 failed / 109 passed; exit 1 |
| helper + S candidate GREEN | t5-39-candidate-green | 1178 passed / 11 warnings; exit 0 |
| helper + F actual transport/GC | t5-39-reachability | 112 passed; exit 0 |
| helper + F disagreement RED | t5-39-evidence-red | 1 failed / 113 passed; exit 1 |
| helper + S disagreement GREEN | t5-39-evidence-green | 1182 passed / 11 warnings; exit 0 |
| `make lint` final | t5-39-lint-final | 299 errors / 63 files; exit 2 |
| `make test` after source closure/format | t5-39-full | 7459 passed / 19 deselected / 408 warnings in 567.69s; exit 0 |
| `make smoke` | t5-39-smoke | 288 passed / 2 warnings; exit 0 |
| `poetry run black --check src/agents/slo_agent/herdr/dao.py src/agents/slo_agent/sessions/service.py tests/agents/slo_agent/herdr/test_session_lifetime.py` | t5-39-black | exit 0 |
| `git diff --check` | t5-39-diff | silent; exit 0 |
| `dpkg -V coreutils` before/full-after/smoke-after | t5-39-coreutils, t5-39-coreutils-postfull, t5-39-coreutils-final | all silent; exit 0 |

`t5-39-lint-attribution.log` retains exact added/removed messages, normalizing only
line numbers and preserving multiplicities. Removed diagnostic:
`src/agents/slo_agent/herdr/reporter.py:LINE: error: Incompatible return value type (got "NullHerdrReporter", expected "HerdrReporterProtocol") [return-value]`.
Baseline is not waived or described as green. Full warnings remain in the log;
no assertions/skips were weakened to obtain green.

## Explicit read receipt

Read current t5-lifetime-38, t5-code-test, routing, scope-plan, root RESEARCH;
AGENTS, CLAUDE and actual maintained docs/RESEARCH are supplied in project context.
Read Makefile, interpreter selection, fake-only fixture and actual lifetime source,
protocol, null/real reporter, transport close/drain and neighboring tests. KB
Welcome + slo README + gotchas consulted read-only.

Loaded checkout engineering routing/ownership/testing, coding rules/cadence/shared
declarative, Python root/named arguments/docstrings/declarative/application
structure/domain DAO/application services, exact code-test-review workflow and
workflow SKILL. No DB/web framework dependency imported from generic examples.

Canonical read-only C 7.9–7.14 read completely (lines 605–2121), including candidate
pool disposal, all-owner order, one-final-drain and intentional pending teardown.
Read exact T5 task body (201–244) and complete attachments (2401–3720); accepted
independent turn-4 review read in full. B affected shared contracts read at
195–260, 656–689, 1423–1580, 2050–2155; D shared ownership/destination/cancellation
contracts at 145–247, 374–384, 540–626. No claim of a fresh whole-B/D feature review.

## Durable local lesson

Resource evidence and remote replacement evidence are separate. A final owner
explicitly returning retained must not be discarded because a getter disagrees.
Likewise an intentionally pending optional-reporting final drain must not prevent
an independent candidate pool from receiving its own cleanup call. This note is
local only: KB/global edits were prohibited by the current request.
