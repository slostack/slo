# T5 session lifetime 37 — INCOMPLETE

The lifetime family is not READY. This checkpoint implements additional session-owned seams but does not claim the complete finite fault matrix or full normative review. Whole T5 app/inbox/viewer/headless/scheduler integration remains future work. Publication/attention/capture work is outside this slice.

## Scope and accounting

Changes in this continuation: `src/agents/slo_agent/sessions/service.py`, `tests/agents/slo_agent/herdr/test_session_lifetime.py`, and this implementation evidence directory. Existing work preserved. No agents, commits, pushes, PRs, resets, cleaning, stashing, specifications, global/live or other-worktree changes. Same unfinished turn 1: started 1, completed 0, historical partial 1, dispatch 37, retries 0. User unlimited turns/dispatches applies.

## Implemented and proved subset

- `suppress_external_reporting`: monotonic unavailable destination; future activation does not allocate; repeated suppression accepted before activation, attempted activation rejects suppression without losing its reporter.
- `drain_retained_external_resources`: requires completed close; one retained local-only task; cached outcome; errors remain retained/uncertain; no remote retry.
- `finish_retired_reporting_cleanup`: one retained cancellation-resistant final owner. Drained normal close preserves safe evidence. Retained close permits one local drain; successful final drain stays uncertain. Persistent retained result leaves final owner pending, not successful. Test-only private owner cancellation tears down the deliberate never-completing fixture.
- `dispose_unmounted_session`: candidate-only attached pool abort-and-drain through one retained task, including repeat/cancel/error; old pool untouched; rename metadata retained. Unmounted/not-running is a documented caller precondition, not newly detected mounted state.
- Failed viewer close is conservatively retained even if reporter reports drained; session retains viewer and reporter references. No repeated viewer close is attempted by final local drain.
- Deterministic preparation/start races and repeated close-waiter cancellation exercise existing close behavior; these cases initially passed except one fixture counting error described below.

## Still required before lifetime READY

1. Complete session fault matrix: before/after actual factory build failures, diagnostic failure combined with start-task result retrieval, revocation failure, transport/reporter evidence failures, retained outcome/getter disagreement, direct final-drain repeated cancellation, close-before-start under enabled capability, start-caller repeated cancellation and real lease contention.
2. Prove strong reachability with weakref/GC and real registered fake transport/lease quarantine, not only object identity and recording null-owner tests. Existing real enabled activation test is retained but does not prove this full matrix.
3. Retrieve defective activation task results conservatively in close and ensure every cleanup owner is attempted; current close only joins start. Review cancellation from inner owners separately from public waiter cancellation.
4. Review candidate cleanup failure semantics and disposal under reporting faults/persistent retention. No app callers were wired.
5. Finish required full canonical C7.9–7.14/B close/D cancel and accepted-review reading. C7.11 and final-drain contracts plus exact T5 samples 2401–3720 were read; not all surrounding canonical prose/reviews were ingested. Shared routing/ownership/testing, coding rules/loop/declarative, Python root/domain/application/declarative and exact code-test-review workflow were read. No independent review claimed.

## Executed evidence

CWD `/root/Code/slo-94-herdr-integration/slo`; approved Poetry fallback reports Python 3.11.7. All targeted commands use `bash docs/implementation/94-herdr/t1-dao-check.sh` (disabled default, existing independent fake-executable and terminal guards). No live Herdr/providers/windows used.

Two argument sets:

- **F**: `tests/agents/slo_agent/herdr/test_session_lifetime.py`
- **S**: `tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/orchestrator/test_bootstrap.py`

The helper additionally runs DAO/projection tests. Exact command is helper plus the argument set above. Every prefix below is in this directory with `.log` and `.exit` files.

| Prefix (`t5-37-`) | Args | Result / exit |
|---|---|---|
| suppress-red | F | 2 failed, 70 passed / 1 |
| suppress-green | S | 1140 passed / 0 |
| drain-red | F | 2 failed, 72 passed / 1 |
| drain-green | S | 1142 passed / 0 |
| finish-red | F | 1 failed, 75 passed / 1; pre-close guard initially passed |
| finish-green | S | 1144 passed / 0 |
| retention-initial | F | 78 passed / 0; no fabricated RED |
| retention-surrounding | S | 1146 passed / 0 |
| candidate-red | F | 2 failed, 78 passed / 1 |
| candidate-green | S | 1148 passed / 0 |
| pool-initial | F | 82 passed / 0; no fabricated RED |
| pool-surrounding | S | 1150 passed / 0 |
| viewer-red | F | 1 failed, 82 passed / 1 |
| viewer-green | S | 1151 passed / 0 |
| race-initial | F | 85 passed / 0; existing behavior |
| race-surrounding | S | 1153 passed / 0 |
| cancel-initial | F | 1 failed, 85 passed / 1 |
| cancel-surrounding | S | 1 failed, 1153 passed / 1 |
| cancel-corrected | S | 1154 passed / 0 |

Cancellation test failure was a fixture mistake, not a product defect: NullHerdrReporter.close_transport delegates to close, so the close mock counted twice. The test now independently stubs transport close; no production cancellation behavior was changed for that case.

Post-format full `make test`: **7431 passed, 19 deselected, 408 warnings**, exit 0 (`t5-37-full.log/.exit`). This is actual current suite evidence, not proof of untested lifetime requirements.

`poetry run black src/agents/slo_agent/sessions/service.py tests/agents/slo_agent/herdr/test_session_lifetime.py`: exit 0 (`t5-37-black`). `git diff --check`: silent/0 (`t5-37-diff`). `dpkg -V coreutils`: silent/0 (`t5-37-coreutils`, before full suite). Post-full `make smoke`: 288 passed, exit 0 (`t5-37-smoke`). `make lint`: 324 errors in 68 files, exit 2 (`t5-37-lint`), versus the unwaived 300-error/64-file baseline; increase has NOT been attributed or resolved. `poetry run black --check` on the same two files: exit 0 (`t5-37-black-check`). Post-full `dpkg -V coreutils`: silent/0 (`t5-37-coreutils-final`). No lint-green claim; this is an additional readiness blocker.
