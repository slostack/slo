# T2-36 lifetime TEST lane — INCOMPLETE: one retained regression

Only `tests/agents/slo_agent/herdr/test_final_lifetime_closure.py`, this report,
and `t2-36-*` receipts were authored. No production edits, agents, delivery,
global/KB/specification/other-worktree changes. Preserve all other partial work.
Accounting unchanged: turn 1, started 1/completed 0/historical partial 1,
dispatch 23, retries 0. Workflow-turn and dispatch budgets are unlimited.

## Concrete correction required

New `test_retained_cleanup_emits_one_recovery_after_actual_drain` fails at the
final exact diagnostic assertion. Actual messages: `[herdr_cleanup_unavailable]`.
Expected: `[herdr_cleanup_unavailable, herdr_cleanup_unavailable_recovered]`.
The actual guarded transport invokes one child; injected `_terminate_and_reap`
failures retain that child/spawn handle through invocation cleanup and ordinary
close. The third, final local drain delegates to the real reap. Handles and real
pane lease are then drained, the final task is cached, accounting remains exactly
once and no remote retry occurs. Those assertions PASS before the missing recovery.

Owner: `src/agents/slo_agent/herdr/service.py`, `HerdrCliTransport` diagnostic
accounting around `_finish_admitted` / `_drain_quarantined_resources`.
`_log_failure` retains timestamps but no cleanup episode/recovery state; successful
quarantined drain simply clears handles. Add bounded cleanup episode tracking and
emit one fixed, sink-isolated recovery only after proven successful local drain.
Do NOT clear sticky `_cleanup_failed`, reopen admission, repeat accounting, retry
remote release, or treat recovery as safe replacement. Repeated cached drains must
not repeat the message. B section 6 requires rate-limited failures plus one recovery;
C final-drain contracts separately require sticky uncertainty. These obligations
are compatible. This is an observability regression, not evidence of a leaked
resource on the successful final-drain path. The test remains enabled, not xfailed.

## Finite requirement/test map

All new tests are in `test_final_lifetime_closure.py`:

| Requirement | Evidence | Result |
|---|---|---|
| Shutdown deadline expires while real durable reservation thread held; no late release; reservation joined | `test_shutdown_deadline_joins_durable_reservation[False,True]`: real two-second deadline, thread barrier, durable counter advances from 1 to 2, no ticket/admission/send afterward, repeat close, repeated caller cancellation | 2 pass |
| Persistent actual transport retention + reporter lease retention; final failure cached; repeated cancellation; no remote retries | `test_persistent_transport_failure_retains_real_lease[False,True]`: exact child/spawn identity, real contender blocked before/after final refusal, three cleanup attempts total, one accounting callback and executable entry | 2 pass |
| Actual lease-close faults retain correct owner; final success or persistent fault | `test_real_lease_close_fault_retains_owner[False,True]`: exact-fd `os.close` refusal, real lease/sequence/transport, same fd retained, contender refusal, final successful unlock permits contender, cached repeat makes no third attempt | 2 pass |
| Admitted cancellation preserves absent/existing diagnostic episode and later successful recovery | `test_admitted_cancellation_preserves_diagnostic_episode[False,True]`: actual child entry then cancellation, possible binding/no ack, drained handles, no diagnostic mutation, subsequent successful claim recovers once | 2 pass |
| Retained cleanup diagnostic episode ends once after successful final local drain, without remote retry or loss of uncertainty | `test_retained_cleanup_emits_one_recovery_after_actual_drain` | **FAIL: missing recovery** |

Reuse, not duplicate: `test_reservation_composition.py` covers current/stale/close/
cancel/error-cancel reservation ownership; `test_retained_transport_composition.py`
covers successful third actual drain with and without repeated cancellation;
`test_reporter_final_drain.py` covers retained reporter gateway errors and cache;
`test_transport_lifetime.py` covers queued cancellation, late spawn, real pipes,
termination escalation, accounting fault and transport quarantine. All were rerun
in the surrounding receipt. Existing terminal-operation matrix and t2-35 cancelled
diagnostic correction remain intact. No claim that unrelated T2 save/worker families
are missing or completed by this lane.

## Cadence and executed gates

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified `pyenv which python` =
`/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7; `make test-env` =
`fallback`. Read `t1-dao-check.sh` before running: safe test exports, synthetic key,
Herdr disabled by default, terminal blocker, project PYTHONPATH. No dev env sourced.

Every pytest command uses `bash docs/implementation/94-herdr/t1-dao-check.sh`;
the wrapper includes 62 DAO/projection tests. Prefixes below have full `.log` and
actual `.exit` siblings under this directory. First three increments passed on
first execution: coverage-only, not fabricated RED. Final regression was written
before any production correction; no correction is authorized in this lane.

| Receipt prefix | Arguments after wrapper | Result |
|---|---|---|
| t2-36-reservation | new test file | 64 passed, 2 warnings; exit 0 |
| t2-36-retained | new test file | 66 passed, 2 warnings; exit 0 |
| t2-36-lease-cancel | new test file | 70 passed, 2 warnings; exit 0 |
| t2-36-recovery-red | new test file | 1 failed, 70 passed, 2 warnings; exit 1 |
| t2-36-surrounding | new file plus the four reused modules listed above | 1 failed, 94 passed, 2 warnings; exit 1 |
| t2-36-package | tests/agents/slo_agent/herdr | **1 failed, 729 passed, 4 warnings; exit 1** |

The package includes concurrent other-worker additions; count is not attribution
to this lane. Sole package failure is the new missing-cleanup-recovery regression.
`poetry run black tests/agents/slo_agent/herdr/test_final_lifetime_closure.py`
formatted only the owned file (`t2-36-format`, exit 0).
`poetry run black --check tests/agents/slo_agent/herdr/test_final_lifetime_closure.py`
passed (`t2-36-black`, exit 0). `git diff --check` passed silently (`t2-36-diff`);
the new untracked file was also read back in full after formatting. `dpkg -V
coreutils` was silent after surrounding and package runs (`t2-36-coreutils` and
`t2-36-coreutils-final`, both exit 0). No full make test/smoke/lint: integration
owner retains those gates. Prior 301 errors/64 lint files remains unwaived, not green.

## Safety and reading scope

Actual fake capability/containment/device-inode guard remains enabled. Executable
and capture/barrier are existing fixture-owned regular files under resolved
`tmp_path`; executable changes revalidate the guard first. Thread waits, actual
child sleep, async entry/cleanup waits and test shell calls are finite. Teardown
releases barriers and drains only owned tasks/children and leases. OS refusal
injections are bounded seams around real transport/filesystem/lease composition,
not certification of native kernel failures. No providers, real Herdr, terminal
windows, system symlinks or production state are used.

Read actual AGENTS/CLAUDE, root and full docs RESEARCH; routing/scope-plan,
t2-35-integration, t2-34 diagnostics/reporter, t2-reporter; actual reporter/service/
sequence owners and named existing tests. Read shared engineering routing/testing/
ownership, generic coding rules/cadence/declarative, Python root/declarative/types/
docstrings/test-environment guidance; KB Welcome and Slo README/gotchas. Read exact
T2 attachment lines 446–1905 and relevant B deadline/lifetime/diagnostic ledger and
C retained lifetime/final-drain contracts. No full-feature specification ingestion,
independent review or completion assessment is claimed. No KB write was permitted.

Family verdict is **INCOMPLETE solely for the reproduced cleanup recovery defect**;
rerun this file and package after the production owner's correction. Independent
full-feature Review/Completion and integration-wide gates remain separate later work.
