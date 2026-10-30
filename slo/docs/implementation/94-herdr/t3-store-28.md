# T3 STORE 28 — INCOMPLETE

Store-only continuation. Public save/load signatures unchanged. Exclusive production
edit: restore.py; new tests: test_restore_boundaries.py, test_restore_io.py,
test_restore_security.py. No shared status, CLI/viewer, specification, KB, global,
other-worktree, agent, commit or external changes. Preserve prior 109/845 receipts.
Counters preserved: turn 1 started 1/completed 0/historical partial 1,
dispatch 28/retries 0; user unlimited turns/dispatches; no dispatch here.

## Actual correction

Lease.close previously ran outside the fixed-error exception boundary. Both public
save and load leaked an injected OSError and its private message at cleanup.
Two failing tests establish this. Three production lines now translate cleanup
OSError/HerdrSequenceUnavailableError without chaining. Actual descriptor release
occurs before injected failure in these tests; this does not establish recovery
from an OS close that leaves a descriptor open. Shared lease/writer unchanged.

## Evidence

CWD /root/Code/slo-94-herdr-integration/slo. Approved pyenv slo-harness Python
3.11.7 verified; make test-env returned fallback. P below is
`bash docs/implementation/94-herdr/t1-dao-check.sh` (includes 62 DAO/projection
cases). All prefixes below have .log/.exit in this directory.

| Prefix | Command suffix | Actual result |
|---|---|---|
| t3-store-28-boundaries | P tests/agents/slo_agent/herdr/test_restore_boundaries.py | 75 passed, 2 warnings; existing implementation initially correct |
| t3-store-28-io-red | P tests/agents/slo_agent/herdr/test_restore_io.py | 2 failed, 64 passed; cleanup error leak |
| t3-store-28-io-green | P tests/agents/slo_agent/herdr/test_restore*.py tests/agents/slo_agent/herdr/test_sequence_store.py | 154 passed, 2 warnings |
| t3-store-28-security | P tests/agents/slo_agent/herdr/test_restore_security.py | 97 passed, 2 warnings; initial pass |
| t3-store-28-package | P tests/agents/slo_agent/herdr | 903 passed, 4 warnings, exit 0 after formatting |
| t3-store-28-black | poetry run black --check src/agents/slo_agent/herdr/restore.py tests/agents/slo_agent/herdr/test_restore*.py | exit 0 |
| t3-store-28-diff | git diff --check | exit 0 |
| t3-store-28-coreutils | dpkg -V coreutils | silent, exit 0 |

Package includes concurrent disjoint lane work; count is not solely this lane's
increment. No full make/static-green claim. Baseline 301 errors/64 files remains
unwaived. No independent review/completion phase performed.

## Branch map (prior proofs reused, not duplicated)

| Store branch | Concrete evidence | Remaining |
|---|---|---|
| inert construction / missing load | test_restore.py | none for absent entire state |
| prepare existing/new directories | test_restore_save.py roundtrip; security missing_root/lock save vs load | mkdir errors/race; linked parent/root chain; owned-parent depth |
| private directory ownership/mode | security root_mode,parent_mode,owner | real chain substitution and distinct ownership levels |
| acquire/platform/release | prior process contention, lock substitution; security platform/open; io cleanup fault | acquire-stage individual faults; actual unresolved-close ownership |
| copied config and canonical IDs | security 15 save/load/stored variants | invalid copied nested pool and private validation/log scan |
| allocation 0/1/2/3 collisions | boundaries test_three_allocation_attempts exact draw/writer counts, unchanged old bytes | dangling collision and occupied precommit target writer-not-called |
| record quota | boundaries 65535/65536/65537 save plus exact load | independently authored padded load boundaries |
| projected count | boundaries 1023/1024/1025 | actual scan iterator spy proving <=1025 inspection |
| projected bytes | boundaries 67108863/67108864/67108865 real sparse corrupt record | none for arithmetic boundary |
| scan errors / unsafe entries | security scan; prior quota directory | entry stat faults and every insecure entry category |
| writer outcome | prior exception/uncommitted/warning; io real file+directory fsync failures | pre-replace process crash |
| read syntax/reference/identity/size | prior test_restore_faults and partial read | opened inode substitution, post-open security mutation, descriptor-close fault |
| open/read unsupported protection | security open/read/nofollow | narrowly isolated record-open failure distinct from lock-open |
| concurrency/crash | prior child contention and post-save orphan termination | successful concurrent save/load race and pre-replace crash |
| reporter composition | existing test_restore_batch_closure retained | actual real-store failed-save/no-advertisement composition |

## Context / limitations

Read frozen routing/scope plan, prior T3 receipts, actual store/lease/writer/tests,
root RESEARCH and supplied AGENTS/CLAUDE/docs RESEARCH, KB entry/index/gotchas,
full C chapter in three bounded reads, exact tasks 1906–2108, accepted turn-4
review/finalization. Read shared workflow/routing/ownership/testing/coding cadence
and Python root/DAO/service/declarative guidance. Some combined skill reads were
truncated; not every frozen-routing companion was freshly fully ingested.

**Store READY withheld.** The explicit remaining cells above are acceptance gaps,
not waived by the package pass. T3CLI may continue against unchanged public APIs;
T5 must not treat this receipt as complete store dependency acceptance.
