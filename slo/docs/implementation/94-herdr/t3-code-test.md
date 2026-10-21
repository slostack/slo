# T3 code/test — technical READY

## Current continuation — handoff 31 / CLI 28 (technical READY)

See `t3-handoff-31.md` for the complete finite branch map, explicit fresh-read audit,
CLI contract reconciliation and command/log/exit receipts. All five outstanding
T3 rows are closed. One production correction suppresses value-bearing Pydantic
serialization warnings before copied-config validation; strengthened tests proved
2 failures before the fix. Directory ownership/depth, collision and acquire-stage
proofs initially passed existing behavior; no fabricated production RED.

Final store/package + required CLI regressions: **1153 passed, 6 warnings**, exit 0.
Changed Black and diff pass; coreutils silent. Scoped mypy has seven dependency
errors in four files, none in either checked file; it is not green. Latest supplied
full lint 300 errors/64 files remains unwaived. Integrated make gates remain after
T3/T4 readiness, and independent full-feature Review/Completion remain later.

Entire T3 technical dependency includes the already implemented CLI and fresh
validated mutable pool reconstruction from immutable saved scalars, with no ambient
preference merge. No additional CLI contract gap identified. No CLI/viewer edits,
agents, commits, global/spec/other-worktree or live actions. Frozen routing/scope
records and all historical receipts preserved. Same unfinished turn 1: started 1,
completed 0, historical partial 1, dispatch 31, retries 0; budgets unlimited.

## Historical continuation — composition 30 / CLI 28 (INCOMPLETE)

`t3-composition-30.md` adds actual two-process concurrent save/load with safe
nonblocking refusal, actual store→reporter→guarded executable failure/withdrawal
composition, scan-entry security faults, record-specific descriptor faults and
directory creation/race/link cases. No production edits. Final Herdr package plus
required CLI regressions: **1129 passed, 6 warnings**, exit 0. Changed Black/diff
pass; coreutils silent. Initial reporter expectation and inode fixture failures
are documented, not misrepresented as production RED.

Remaining exact rows: distinct directory ownership/depth, copied nested-pool
validation/privacy, dangling allocation collision/precommit occupied target,
acquire-stage shared-proof reconciliation and complete requested context refresh.
STORE and overall T3 technical READY remain withheld. No full make or fresh lint;
latest supplied 300/64 lint baseline remains unwaived. Counters preserved: turn 1,
started 1/completed 0/historical partial 1/dispatch 30/retries 0; unlimited limits,
no agents dispatched. Full-feature review/completion remain later.

## Historical continuation — STORE 29 / CLI 28 (INCOMPLETE)

`t3-store-29.md` records added actual iterator-bound, padded-read and pre-replace
child-crash proofs, plus correction of the STORE test typing error. Post-format
STORE plus required CLI regression command: **299 passed, 5 warnings**. Changed
Black/diff pass; coreutils silent. No production change in STORE 29.

CLI behavior is implemented as recorded in `t3-cli-28.md`; its 208 targeted,
7,286 full and 288 smoke passes precede STORE 29 test edits. STORE still lacks
successful concurrent process save/load, real-store/reporter no-advertisement
composition and the remaining exact security/fault reconciliation in STORE 28.
Scoped mypy has no security-test error but dependency errors remain; no global
static-green claim. Overall T3 technical READY is withheld. No independent
review/completion or fresh full integration gate. Counters remain turn 1,
started 1/completed 0/historical partial 1/dispatch 29/retries 0; no new dispatch.

## Historical continuation — STORE 27 (INCOMPLETE)

See `t3-store-27.md` for the current branch ledger and exact receipts. Save now
exists with immutable allocation, private preparation, quotas and durability
refusal; load handles short reads. Four test-first production increments and
real child-process evidence landed. Final post-format Herdr package: **845 passed,
4 warnings**, exit 0. Changed Black/diff checks pass; coreutils verification silent.
STORE remains INCOMPLETE pending the explicit security/allocation/boundary/crash
matrix in that receipt. T3 overall also requires the separate CLI lane. No
independent review/full integrated make/static-green claim. Earlier section below
is preserved as historical evidence, not the current implementation description.

## Historical files (initial partial)

- `src/agents/slo_agent/herdr/restore.py`: inert constructor, noncreating load
  lease, canonical reference validation, bounded no-follow descriptor read,
  embedded reference and canonical session identity checks. Uses existing DAO
  error and shared lease. **No save implementation yet.**
- `tests/agents/slo_agent/herdr/test_restore.py`: constructor/missing-load
  inertness, four invalid reference forms, real private-file exact load.
- Existing `test_restore_batch_closure.py` preserved unchanged.
- CLI app/dispatch untouched. No shared contract change established yet.

## Test-first cadence and exact receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified `pyenv which python` =
`/root/.pyenv/versions/slo-harness/bin/python`, `python --version` = Python 3.11.7,
`make test-env` = fallback. Read `t1-dao-check.sh`: safe fallback exports,
synthetic credential, default Herdr disabled; no dev environment. Existing actual
spawn capability and terminal guards unchanged.

Prefix P = `bash docs/implementation/94-herdr/t1-dao-check.sh`.
Each receipt prefix below has `.log` and `.exit` siblings.

| Receipt | Exact command | Result |
|---|---|---|
| t3-01-red | P tests/agents/slo_agent/herdr/test_restore.py | Collection error: missing restore module; exit 2 (not a behavioral RED claim) |
| t3-01-green | P tests/agents/slo_agent/herdr/test_restore.py tests/agents/slo_agent/herdr/test_sequence_store.py | 108 passed, 2 warnings; exit 0 |
| t3-02-red | P tests/agents/slo_agent/herdr/test_restore.py | Exact-file load fails with unavailable error; 1 failed, 67 passed; exit 1 |
| t3-02-green | P tests/agents/slo_agent/herdr/test_restore.py tests/agents/slo_agent/herdr/test_sequence_store.py | 109 passed, 2 warnings; exit 0 |
| t3-black-format | poetry run black src/agents/slo_agent/herdr/restore.py tests/agents/slo_agent/herdr/test_restore.py | exit 0 |
| t3-black-check | poetry run black --check src/agents/slo_agent/herdr/restore.py tests/agents/slo_agent/herdr/test_restore.py | exit 0 |
| t3-coreutils | dpkg -V coreutils | silent; exit 0 |

First implementation approximately 50 lines; second approximately 40 logic/import
lines, tested before continuing. Black formatting followed the last test run;
no post-format pytest claim. No scoped mypy or final full gates run. Prior
301 errors/64 files lint baseline remains unwaived, not green.

## Remaining T3 requirements

1. Complete preparation/creation under distinct restore lock; verify all owned
   directory chain/security and lock substitution/refusal cases.
2. Implement validated copied save, three absent-name allocations, strict
   65536-byte/1024-record/67108864-total quotas with <=1025 inspected entries,
   unchanged AtomicFileWriter durable commit and no-overwrite/orphan semantics.
3. Complete real-file security/identity/schema/bounded-read/quota tests and actual
   separate-process contention/crash/concurrent save-load evidence; writer failure,
   fsync warning, old bytes preserved; reporter composition for no advertisement.
4. CLI option and preconstruction literal UUID/conflict admission; fixed errors;
   exact saved config with fresh validated mutable pool, no preference merge;
   actual CliRunner/Faux-boundary tests and ordinary slug compatibility.
5. Task-exact regressions, package/surrounding cadence, scoped static and changed
   Black; final integrated make gates after both lanes per parent instruction.
6. Finish required context ingestion before further implementation: entire C and
   exact T3 samples were read, but B/D relevant contracts, historical source
   documents and accepted review evidence have not all been freshly read in this
   continuation. Some initial combined skill reads truncated; Python/shared core
   and DAO opening were recovered separately. Do not claim full prescribed
   ingestion or complete requirements coverage from this partial receipt.

No independent review/completion or live compatibility claim. This continuation
spawned no agents and does not change parent-owned workflow accounting.
