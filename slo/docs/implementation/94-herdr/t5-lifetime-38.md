# T5 session lifetime 38 — INCOMPLETE

No family READY or full-feature review claim. Same unfinished turn 1: started 1, completed 0, historical partial 1, dispatch 38, retries 0. Unlimited user turn/dispatch budgets remain effective; no agents launched. Existing partial work preserved. No caller, global, live, specification, other-worktree or destructive Git changes.

## Changes and verified evidence

- Added real result retrieval for the retained activation task during session close. An ordinary task failure or inner-task cancellation now makes replacement evidence uncertain while later cleanup still proceeds. Inner-task cancellation is distinguished from cancellation of the public waiter.
- Added both regression cases before implementation: 2 failed / 86 passed. After the five-line production repair, full surrounding partition: 1156 passed, 11 warnings.
- Repaired all 18 new nullable typing errors in lifetime/capture/publication tests with explicit assertions of the required fixture state. No Any, ignore or cast added.
- Investigated a concrete-union session annotation as a possible scoped repair. This reduced service errors to one, but HerdrReporter.build returns HerdrReporterProtocol. Reverted that experiment rather than retaining a type escape or imposing an untested runtime type restriction.

## Exact lint attribution and scope boundary

The comparison baseline is `t4-31-lint-verified.log` (300 errors / 64 files), NOT the older `baseline-lint.log` (301 / 64). Final fresh `make lint`: **306 errors / 65 files, exit 2**. All six additional errors are in session service:

- assignment and two returns: NullHerdrReporter.build_visualizer returns None whereas HerdrReporterProtocol promises a non-null launcher;
- two revoke_viewer_admission calls and one record_publication_failure call: these implemented methods are absent from the protocol.

` t5-38-lint-attribution.log` (filename without leading space) compares error messages with line numbers normalized and multiplicity retained: six added, zero removed. The 18 test errors are gone. Baseline remains unwaived.

The truthful shared-contract fix belongs in `src/agents/slo_agent/herdr/dao.py`: describe nullable null-owner visualizer construction and declare the two existing methods. That file is outside this request's explicit session-service/bootstrap/session-tests ownership. It was not edited. A replacement local protocol or cast would hide rather than fix the shared declaration. This is an explicit remaining authorization boundary, not a claim that the family is complete.

## Finite remaining branch map (reuse existing proofs)

| Family | Existing proof / remaining work |
|---|---|
| Disabled/outside/invalid identity, activation once | Existing lifetime tests retained; no duplicate matrix needed |
| Suppression before start, repeated suppression, future start after close | Existing `test_suppression_is_permanent` and attempted-activation rejection retained |
| Close during prepare/start; multiple cancelled close callers | Existing deterministic barrier tests retained |
| Defective activation terminal result | NEW RuntimeError and CancelledError regressions pass; close result uncertain |
| Factory failure before/after build and diagnostic failure | Still needs real factory boundary fault coverage; not replaced by the new task-result test |
| Start caller repeated cancellation | Still needs direct public-start proof |
| Close before enabled activation | Still needs enabled no-command proof |
| Viewer failure, reporter failure | Existing tests retained; inner cleanup cancellation and full later-owner ordering not yet closed |
| Revocation, transport, evidence/getter failure and outcome disagreement | Remaining finite fault table; no claim of coverage |
| Local-only final drain, one attempt, persistent pending | Existing final-drain and finish tests retained; direct drain repeated cancellation still missing |
| Actual transport / lease quarantine / GC | Existing enabled fake transport proves ordinary activation/close only; strong-root reachability, retained real lease and late drain still missing |
| Candidate-only pool disposal | Existing candidate/old-pool and cancellation/error tests retained; reporting fault/persistent-retention composition still missing |

App quarantine slot, publication/operation/attention, inbox and viewer callers remain later work. Session-family evidence must not substitute for those app-level guarantees.

## Commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved Poetry interpreter reports Python 3.11.7; no environment installed. Existing safe helper uses disabled defaults and guarded fake executable / terminal isolation.

F = `tests/agents/slo_agent/herdr/test_session_lifetime.py`

S = `tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/orchestrator/test_bootstrap.py`

| Exact command | Receipt prefix under this directory | Result |
|---|---|---|
| `bash docs/implementation/94-herdr/t1-dao-check.sh` + S | t5-38-typing-green | 1154 passed, 11 warnings / 0 |
| `bash docs/implementation/94-herdr/t1-dao-check.sh` + F | t5-38-task-red | 2 failed, 86 passed / 1 |
| `bash docs/implementation/94-herdr/t1-dao-check.sh` + S | t5-38-task-green | 1156 passed, 11 warnings / 0 |
| `make lint` (temporary union experiment) | t5-38-lint | 301 errors / 65 files / 2; not final source |
| `make lint` (final source) | t5-38-lint-final | 306 errors / 65 files / 2 |
| `poetry run black src/agents/slo_agent/sessions/service.py tests/agents/slo_agent/herdr/test_session_lifetime.py tests/agents/slo_agent/herdr/test_session_capture.py tests/agents/slo_agent/herdr/test_session_publication.py` | t5-38-black | 0 |
| `git diff --check` | t5-38-diff | silent / 0 |
| `dpkg -V coreutils` | t5-38-coreutils | silent / 0 |

Each prefix has `.log` and `.exit`. Full make test deliberately not rerun: family remains unfinished. Historical 7431 full / 288 smoke is not post-change proof.

## Read receipt and limitations

Read current t5-lifetime-37 and t5-code-test, routing and scope plan, root RESEARCH; supplied AGENTS/CLAUDE/docs RESEARCH are in context. Read actual lifetime/capture/publication tests and session lifetime implementation; factory/null/join boundaries inspected. Consulted KB Welcome, slo README entry and gotchas. Loaded engineering routing/ownership/testing, coding rules/cadence/declarative, Python conventions/domain/application/declarative, exact Code-Test-Review workflow. Read canonical C7.11 and C7.14, C7.9 opening ownership/capture section, C7.13 opening retention section and accepted independent turn-4 review in full.

Remaining normative reading is NOT claimed complete: remainder of C7.9–7.10 and C7.13, exact tasks T5 attachments, B/D shared ownership details, workflow SKILL and additional routed build/style files. Earlier receipts are historical, not proof this continuation ingested those sections. No independent review occurred.
