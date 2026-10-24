# T3 STORE continuation 27 — INCOMPLETE

Scope: restore.py and test_restore*.py only, plus this receipt and t3-code-test.md.
No agents, commits, external actions, shared status/spec/other-worktree edits.
T3 overall still requires the separate CLI lane. No READY claim.
Counters retained: turn 1, started 1/completed 0/historical partial 1,
dispatch 27/retries 0; unlimited turns/dispatches. No dispatch here.

## Implemented

- Save validates a fresh config, allocates up to three UUID4-derived absent names,
  commits with unchanged AtomicFileWriter, refuses uncommitted/durability warnings.
- Private directory preparation, shared distinct nonblocking restore lease,
  precommit held-lock revalidation, private regular-file quota scanning.
- 65536 record bytes, 1024 projected entries, 67108864 projected total bytes,
  bounded scan stops at entry 1025. No eviction/latest pointer/history creation.
- Load now accumulates short reads to EOF or 65537 bytes rather than accepting a
  valid JSON prefix from one short read.
- Real files verify immutable revisions, quota refusals, writer error/outcomes,
  lock substitution, malformed/missing/oversized/schema/reference/identity data,
  mode/hardlink/directory/FIFO/symlink refusal. Symlink target is temp-owned only.
- Real spawned child tests prove contention and durable orphan survival after
  terminating only the test-owned child at the post-save/pre-advertisement barrier.

## Test cadence and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`; pyenv which python:
`/root/.pyenv/versions/slo-harness/bin/python`; Python 3.11.7;
`make test-env`: fallback. No development environment used.
P = `bash docs/implementation/94-herdr/t1-dao-check.sh` (includes DAO/projection tests).
All prefixes below are in this directory, with .log and .exit files unless noted.

| Prefix | P arguments / command | Actual result |
|---|---|---|
| t3-store-27-01-red | test_restore_save.py | 1 failed (missing save), 62 passed |
| t3-store-27-01-green | test_restore_save.py test_restore.py test_sequence_store.py | 110 passed |
| t3-store-27-02-red | test_restore_save.py | 4 quota refusal failures, 63 passed |
| t3-store-27-02-green | whole herdr package | 1 failed, 805 passed; parallel T4 test_close_joins_pending AttributeError, preserved output |
| t3-store-27-02-surrounding | test_restore*.py test_sequence_store.py | 119 passed |
| t3-store-27-03-red | test_restore_save.py | 1 lock substitution failure, 70 passed; writer outcome tests already green |
| t3-store-27-03-green | test_restore*.py test_sequence_store.py | 123 passed |
| t3-store-27-04-red | test_restore_faults.py | 1 short-read failure, 73 passed; other fault cases already green |
| t3-store-27-04-green | test_restore*.py test_sequence_store.py | 135 passed |
| t3-store-27-05-evidence | test_restore*.py test_sequence_store.py | 137 passed; process tests correct already, not claimed RED |
| t3-store-27-package | whole herdr package after formatting | 845 passed, 4 warnings, exit 0 |
| t3-store-27-black | poetry run black --check restore.py test_restore*.py (full repository-relative paths) | exit 0 |
| t3-store-27-diff | git diff --check | exit 0 |
| t3-store-27-coreutils | dpkg -V coreutils | silent, exit 0 |

Production increments were approximately <=50 lines then tested. No full make
suite/static completion claim; integrated full gates await T3/T4. Prior lint
301 errors/64 files remains unwaived. Package counts include parallel T4 changes.

## Branch ledger / exact remaining evidence

| Owner | Covered now | Remaining before STORE READY |
|---|---|---|
| constructor/load initialization | inert missing root; exact private read | missing lock/root independently, directory chain mode/owner/link matrix |
| preparation/lease | new root, existing root, actual process contention, lock substitution | each mkdir/acquire/close fault, unsupported platform, owned-parent preparation depth and races |
| save validation | ordinary fresh config roundtrip | invalid copied nested policy, canonical slug/uppercase/braces/compact/empty save/load gates, private validation traceback scan |
| allocation | distinct random real references | deterministic first/second collision and exactly three exhaustion; dangling link; precommit occupied target proof |
| capacity | oversize record, count quota, total quota, nonregular | exact at/below/above all three bounds; 1025 scan spy, unreadable/stat failure, all insecure entry categories |
| commit | prewrite exception, uncommitted, real write+warning orphan, old bytes intact | actual fsync failure injection rather than returned warning only; pre-replace crash; no-overwrite writer-call assertion |
| load | exact record, wrong JSON/schema/reference/session, missing, oversize, short reads, unsafe target types/mode/link | inode substitution/open/read/close faults; unsupported O_NOFOLLOW; post-open security mutation; complete private formatted traceback/log checks |
| composition/process | child-held lock refuses load/save; durable orphan crash with old exact revision retained | concurrent successful save/load process race; actual reporter failed-save/no-advertisement composition (existing test_restore_batch_closure retained but not substitute for real store evidence) |

Context: read full C (1–2175) and exact T3 attachments 1906–2108,
shared engineering/testing/ownership, coding rules/cadence, Python root and
DAO/application-service/declarative recipes, workflow and shared workflow accounting,
frozen routing/scope plan, supplied AGENTS/CLAUDE/docs RESEARCH, root RESEARCH and KB
entry/gotchas. Some combined initial reads truncated; do not claim every frozen
routing companion/current accepted review document was freshly fully ingested.
No independent review/completion phase has run. This is substantive partial save
implementation, not security-family acceptance. Preserve all earlier receipts.
