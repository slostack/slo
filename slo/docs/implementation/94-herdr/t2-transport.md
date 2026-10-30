# T2 transport increment — NOT READY

2026-10-18. Bounded transport/pure support implementation is present, but the complete requested branch evidence is not yet established. This is neither complete transport acceptance nor whole T2 acceptance. Reporter scheduling, publication/save/reservation accounting, lease-release composition, refresh, remote release, T5 assembly and independent review are not implemented by this increment.

## Scope and authority

Working root: `/root/Code/slo-94-herdr-integration/slo`, branch `feature-94-herdr-integration`. `routing.md`, `scope-plan.md`, source specifications and existing T1 receipts were not edited. T1 DAOs, fixture capability, identity predicate and formatter are reused. No agent dispatch, commit, globals, other-worktree changes, real Herdr/provider/window execution or enabled session assembly.

Read actual T2 task instructions/attachments B04/B06/B08–B22/B24/B25/C28/C29, complete B and relevant C final-drain contracts. AGENTS/CLAUDE and supplied research context plus root RESEARCH were consulted. Selected shared engineering, Python/style, cadence, environment and testing guidance was read. No claim of independent full-scope review.

## Implemented owners and branch ledger

| Requirement / method | Current evidence | Remaining qualification |
|---|---|---|
| `HerdrTaskJoin.wait` | complete/pending/error/single/repeated/owned cancellation | Pending owned cancellation distinction needs additional case |
| `HerdrTransportAdmission` | accepted/refused one-shot and exactly-once complete | Throwing admission callback atomicity needs explicit coverage |
| `HerdrCliTransport.invoke/_invoke_locked` | mandatory synchronous admission then registered spawn under one lock; timeout/waiter cancellation/stale/closed | Actual viewer-holder + durable A/B sequence G2 composition awaits reporter; current waiter tests hold real lock directly |
| `_spawn` | real registered regular executable, explicit allowlisted copied environment, DEVNULL/PIPE modes | More actual-boundary substitution cases required, not just existing capability-unit cases |
| `_read_bounded/_collect_pipes/_collect_result` | empty/exact 16KiB/overflow; simultaneous actual stdout/stderr, nonzero output discarded | Pipe-error and mixed exception-group evidence incomplete |
| `_observe_admitted/_drain_admitted` | spawn refusal, real success, late spawn and repeated cancellation | Explicit read-cancellation/exit-before-cancel branches incomplete |
| `_terminate_and_reap/_signal_owned` | real running/already-exited child, stubborn child timeout with .25s grace, injected terminate failure then kill/wait | Kill/wait defects, ProcessLookupError, platform-specific branches and group-descendant proof incomplete |
| `_finish_admitted/_complete_safely` | real reap before accounting, throwing accounting sink isolation | Unexpected finalizer exception handling still needs hardening/coverage |
| close/final local drain | seal, cached close, retained handles on two failed drains, distinct cached successful final drain, sticky uncertainty, no repeated accounting | Repeated cancellation during close, persistent final failure and lease composition incomplete |
| fixed diagnostics | accounting/cleanup/termination fixed categories; sink failure isolated | Rate-limit/recovery and gate diagnostics incomplete |
| pure projector | shared token guard, compact telemetry, detail ordering/history estimate, arbitrary model/effort omission | Full zero/negative/nonfinite/huge-integer/reasoning/privacy matrix incomplete; compact context ordering needs correction |
| pure gate/null | switch variants, no filesystem probes, inert lifecycle | Gate is `HerdrEnvironmentGate.build` returning null or config, deliberately not a partial `HerdrReporter`; complete invalid-field/classification diagnostics and protocol return annotation remain |
| actual root spawn guard | autouse wrapper invokes T1 guard before original `_spawn`; default refusal and valid real delegation | Mounted/headless negative proof and all substitution cases through actual boundary still required |

`service.py` is the single transport owner. No reporter process slot or scheduler was introduced. Gate/projector remain inert and unconnected to runtime callers. `tests/state_isolation.py` now explicitly classifies SLO_HERDR_METADATA_PROFILE in its override inventory as well as existing case-insensitive stripping.

## Actual cadence receipts

Commands ran from the root using verified `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7; `make test-env` returned fallback. Targeted commands use `bash docs/implementation/94-herdr/t1-dao-check.sh <test paths>` (exact safe fallback exports and PYTHONPATH; includes DAO/projection baseline each time).

- `t2-01` RED import failure → join/admission GREEN 50.
- `t2-02` RED missing transport → captured spawn plus actual fixture wrapper GREEN 78 with isolation/fixture surroundings.
- `t2-03` RED missing bounded reader → GREEN 55.
- `t2-04` RED missing collection → GREEN 57.
- `t2-05` RED missing termination → GREEN 59.
- `t2-06-red.log`: initial RED run exceeded the tool's 60s timeout after a failing test had already scheduled work. Test was corrected to assert method presence before creating its owned task; `t2-06-red-confirmed.log` recorded two AttributeErrors, then GREEN 61. Do not claim the timed-out run passed.
- `t2-07` RED missing terminal finalizer → GREEN 62.
- `t2-08` RED missing invoke → GREEN 64.
- `t2-09` RED missing close → GREEN 65.
- `t2-10-red.log` is **misnamed**: these additional real-lock/late-spawn/pipe evidence tests passed immediately (51); no implementation followed that receipt.
- `t2-11` actual termination-error RED → fallback kill/wait GREEN 75.
- `t2-12` shared predicate RED → GREEN 48.
- `t2-13` projector RED; first green attempt failed on formatter keyword; corrected to existing `count=` and exact existing half-up expectation 12,500→13k; final GREEN 49.
- `t2-14` detail RED → GREEN 51.
- `t2-15` gate/null RED → GREEN 61.
- `t2-16-evidence.log`: added quarantine/stubborn-child proofs passed 63 without further implementation.
- `t2-17` missing diagnostic RED → fixed sink-isolated diagnostics GREEN 64.

Most implementation increments were below approximately 50 substantive lines; gate/null increment exceeded that approximate target. No claim of perfect cadence compliance. Newly added test method annotations/docstrings also need a full convention pass; mypy baseline equality alone is not that review.

## Gates actually run

| Receipt | Command/result |
|---|---|
| t2-surrounding.log/.exit | DAO/projection plus Herdr, formatter/footer, AtomicFileWriter, headless request: 236 passed, 3 warnings, exit 0 |
| t2-full.log/.exit | First `make test`: 1 failed, 6489 passed, 19 deselected; missing metadata-profile isolation classification. Preserved failure output. |
| t2-isolation-green.log | Fixed inventory: 63 passed, 2 warnings, exit 0 |
| t2-full-final.log/.exit | Intermediate full gate: 6490 passed, 19 deselected, 405 warnings, exit 0 |
| t2-full-latest.log/.exit | Latest code full gate: **6491 passed, 19 deselected, 404 warnings, 524.99s, exit 0** |
| t2-smoke.log/.exit | **284 passed, 2 warnings, exit 0** |
| t2-black.log | Black --check all eight touched Python files: **8 unchanged, exit 0** |
| t2-lint-latest.log | `make lint`: **301 errors in 64 files, 699 checked, exit 2** |
| t2-lint-baseline-latest.diff | Exact error-line comparison to sequence-lint-final.log: empty; no new errors; baseline remains unwaived |
| t2-coreutils-latest.log/.exit | `dpkg -V coreutils`: empty, exit 0 |

`git diff --check` passed. Full-suite green does not establish missing requirement paths. Final documentation-only edits follow the latest code gate. No READY claim is made.

## Continuation

Finish the missing transport/guard/projector/gate branches and correctness issues above before transport READY. Then hand off the separately assigned reporter scheduler; do not label whole T2 complete. Independent full-scope review and fresh completion stay reserved after T6.

Accounting: turn 1 started 1/completed 0/historical partial 0; dispatch 9 consumed, 11 remaining of 20; unlimited turns; retries 0. This worker dispatched none.
