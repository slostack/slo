# Acquisition owner170 — bounded R161-1 author READY OFFLINE

Code+Test revision turn5/global170/currentdispatch1; started5/completed0/historical stopped partial1; prior turns1–4 REVISE/incomplete; retries0; effective turn/dispatch budgets UNLIMITED. No spawning. This is finite author evidence, not independent approval or a completed workflow turn.

## Preservation and scope

Verified branch `feature-94-herdr-integration`, origin `https://gitlab.com/core-27/slo.git`, HEAD `d0e3a756689f2675e5507034d43cd8b272d3c6b8`. Supplied base omitted leading `d`; actual HEAD agrees with169/168. No Git mutations, package/global/specification/other-worktree/live changes. Existing work,159 usage,156 profile,151 oracle and146 guards preserved. Other core findings remain closed by169; this change addresses only its remaining High R161-1.

Read supplied AGENTS/CLAUDE/docs RESEARCH, disk CLAUDE/root RESEARCH/Makefile, routing/scope,169 report and actual acquisition probe,163–168 receipts/API ledger, canonical B acquisition/close and C final-drain ownership, relevant source/tests and root guards, KB Welcome/slo README/gotchas. Checkout exact workflow/cadence, engineering routing/ownership/testing, coding rules, Python root/types/declarative/docstrings/application-service guidance apply. Python asyncio ownership and real temporary filesystem integration are the affected categories; no CLI/widget/DAO/framework redesign. Some oversized aggregate reads truncated; this is not a fresh exhaustive whole-feature or public-API audit. Ledger168 is updated only for the new accessor and corrected projection.

## Failure and minimal correction

Actual pane descriptor opens, native lock or counter load fails, rollback close becomes ambiguous. `_lease_held` remains false correctly because usable acquisition never succeeded, but previously both final cleanup and resource projection used that success flag and silently discarded retained ownership.

- `HerdrSequenceStore.retains_external_resources` delegates to its existing lease owner. Pure evidence after joined acquisition/cleanup, never authority to reserve or send.
- Reporter resource projection and `_release_lease` consult this evidence instead of `_lease_held`. No admission change, new manager, raw-descriptor retry or uncertainty reset.
- Existing transport seal/drain guard remains before reporter lease cleanup. Existing cached final/local attempts, same-inode ambiguity, remote once-only behavior and session owner retention remain unchanged.
- Session implementation needs no change: its already-correct final consumer now receives truthful evidence.

## Test-first chronology and permanent coverage

New `test_failed_acquisition_ownership.py` ran BEFORE production edits. `red`: **9 failed/3 passed**. Seven failures establish false retained/drained ownership (including released/reused descriptors left unreconciled); two inspection variants also exposed fixture teardown running before patch removal. Initial lock injection was the native-lock adapter seam; final strengthening patches actual `fcntl.flock` instead. Historical169 probe is not claimed as new RED.

Minimal production change: one eight-line property and two predicate substitutions. First surrounding run `green`: **2 failed/155 passed**, only inspection fixture teardown faults. Undoing fault hooks before independently owned fixture cleanup fixes those without weakening assertions. `green-fixed`: **157 passed** across matrix, whole sequence, cleanup matrix and reporter modules.

Next bounded increment crosses reporter and session final-drain gateways: **24 cases** = native `flock` failure / post-lock load failure × rollback held / released / different-file recycled FD / same-inode recycled FD / EBADF / inspection failure × reporter / session owner. Actual temp-owned descriptor opens before injection. Assertions cover one raw close, failed admission, zero automatic reservations/spawn, explicit reserve refusal, unchanged absent counter, same reachable owner, truthful final retained/drained evidence, sticky uncertainty and writable/readable replacement descriptor. Existing `LeaseCloseFault` independently knows the generation for teardown; no real/system executable or symlink is created. Persistent-retention cases use the finite public local-drain gateway, not the intentionally never-returning final-disposal waiter. No polling/sleeps or induced indefinite waits. Activation has a bounded waiter; all test-owned faults are cleaned in finally.

`session-matrix` and final native-seam `native-matrix`: **87 passed** each (whole session lifetime plus new matrix). Final full selections below include the strengthened native seam and formatted test.

## Exact receipts

Runner: `acquisition-owner-170-run.sh`; expanded argv, full logs, exits and coreutils output: `acquisition-owner-170-receipts/`. CWD is this checkout. Explicit `/root/.pyenv/versions/slo-harness` VIRTUAL_ENV/PATH/PYENV_VERSION; approved Python3.11.7 environment, tracked synthetic fallback (`make test-env=fallback`), no sourced secrets. Root terminal/fake-only transport guards unchanged.

| Receipt | Actual result |
|---|---|
| red | 9 failed,3 passed,2 warnings; exit1 (includes two fixture teardown faults) |
| green | 2 failed,155 passed,2 warnings; exit1 (fixture teardown only) |
| green-fixed | 157 passed,2 warnings; exit0 |
| session-matrix / native-matrix | 87 passed,2 warnings each; exit0 |
| owned-core | **1229 passed,18 warnings,92.05s; exit0** |
| surrounds | **969 passed,353 warnings,372.68s; exit0** |
| lint | **81 source files clean; exit0** |
| black | **80 files unchanged; exit0** |
| diff | silent; exit0 |

Owned-core is the entire169 selection plus the new24 cases: all direct Herdr tests except session/attention, extracted identity/token/context reader, session lifetime and both activation modules. Surrounds include all session/attention modules, CLI restore/headless Herdr/retained, **all** TUI Herdr modules (activation/candidate/initialization/replacement/lifecycle/viewer/cutoffs), and composed full-flow integration. Selections overlap; do not sum counts as unique tests. All runner coreutils outputs are empty; no host anomaly observed. No ignores/Any/casts/suppressions/waivers or weaker expectations introduced.

Full `make test`, smoke, full lint and exact chapter gates were NOT rerun170;168 results are historical and not post-change proof. Run these next dispatch before whole-feature readiness. Independent finite core verification remains required, followed by wiring/harness/static review, full-review synthesis, fresh Completion and separately authorized delivery. Live **USER-DEFERRED**, compatibility **UNVERIFIED**.

## Durable lesson / shared state

Successful acquisition is an admission fact, not a failed-start resource inventory. Always project disposal from the existing resource owner, including rollback failures. Same inode never proves the descriptor generation and never authorizes a second raw close. Shared KB remains read-only under this task; this receipt and research pointers record the lesson locally. Counters above remain unchanged; this author pass does not close Review or Completion.
