# T3 composition 30 — INCOMPLETE

Same unfinished turn 1: started 1/completed 0/historical partial 1/dispatch 30/retries 0. User limits unlimited; no agents dispatched. No production changes or CLI/viewer/shared DAO edits. No commits, global/live/specification/other-worktree changes. Full feature Review/Completion remain later.

## New evidence (existing behavior, no production RED claim)

- `test_restore_process.py::test_concurrent_process_save_load`: two actual spawned processes simultaneously receive save/load commands. Each either succeeds exactly or returns fixed busy refusal; at least one succeeds. Subsequent explicitly issued save then cross-process load succeed exactly. No automatic product retry added. Owned children joined/terminated in finally; pipes closed. This does not assert both overlapping calls must succeed under the nonblocking lock.
- `test_restore_composition.py::test_real_store_failure_withdrawal`: actual store + actual reporter + actual guarded fake-executable transport. Establishes a durable advertised revision, makes restore directory insecure, publishes a new generation, then tests accepted/rejected withdrawal. No new restore argv, no new-generation acknowledgement, immutable old bytes. Rejected release preserves old binding/old acknowledgement and sends no replacement display. Initial test incorrectly demanded deletion of the old acknowledgement; corrected to the specified retained-old-generation policy (1 failed/63 passed, then 64 passed). Not a product defect.
- `test_restore_security.py::test_scan_entry_refusal`: entry stat failure, insecure mode, hardlink, FIFO, dangling symlink, foreign-owner stat; fixed private failure and preserved old bytes.
- `test_restore_io.py::test_record_descriptor_fault`: record-only open failure, released-descriptor close error, opened-inode replacement, mode mutation at open. Fixed safe traceback and old bytes retained. Initial inode fixture recursively intercepted Path.touch's os.open, producing a fixture failure; corrected using captured original syscall (1 failed/69 passed, then 70 passed). No unresolved-close recovery claim.
- `test_restore_security.py::test_directory_preparation`: mkdir failure, private/insecure competing mkdir winner, linked root and linked parent with contained targets; linked targets remain untouched.

## Existing proofs retained, not duplicated

STORE 29 owns exact quota arithmetic, actual 1,025-entry scan bound, independent padded load bounds and pre-replace child death. STORE 28 owns lease-cleanup privacy and actual file/directory fsync faults. `test_restore_faults.py` already covers load nonregular/link/mode/schema/reference/identity; `test_restore_save.py` owns old-byte durability and lock substitution. CLI 28's admission/pool/ordinary-slug contract remains unchanged; its historical 208-pass receipt is not a newly executed count.

## Actual remaining rows — technical READY withheld

1. Distinct ownership levels for owned root/parent and creation-parent depth; existing getuid mismatch test rejects the first checked directory, not each level independently.
2. Copied invalid nested pool validation plus private log/traceback scan at the store boundary (existing identity tests are not this proof).
3. Dangling allocation collision and occupied precommit target with writer-not-called assertion (scan dangling link refusal is a different branch).
4. Final exact acquire-stage fault reconciliation against shared lease tests; current open/platform/contention/substitution evidence is not claimed exhaustive.
5. Complete prescribed context ingestion/reconciliation: C 230–542 and tasks 1906–2108, accepted review/finalization, routing/scope plan and core selected skills were read; actual AGENTS/CLAUDE/docs RESEARCH were supplied in context, not freshly fully reread from disk. DAO recipe tail and routed KB companions were not fully refreshed. Do not infer complete ingestion from earlier receipts.

These are finite outstanding acceptance rows, not a generic demand to repeat quota/crash/CLI tests. STORE and overall T3 remain INCOMPLETE. No full make gate: requested after T3/T4 closure. Latest supplied lint baseline 300 errors/64 files remains unwaived, not green; no fresh mypy run.

## Receipts

CWD `/root/Code/slo-94-herdr-integration/slo`; verified `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7, `make test-env` = fallback. P = `bash docs/implementation/94-herdr/t1-dao-check.sh`, reviewed safe exports plus existing HERDR stripping/fake capability/terminal guards. All prefixes below have `.log` and `.exit` in this directory unless stated.

| Prefix t3-composition-30- | Command suffix / check | Result |
|---|---|---|
| process | P tests/agents/slo_agent/herdr/test_restore_process.py | 66 passed |
| reporter | P tests/agents/slo_agent/herdr/test_restore_composition.py | 1 failed, 63 passed; incorrect test expectation |
| reporter2 | same | 64 passed |
| security | P tests/agents/slo_agent/herdr/test_restore_security.py | 103 passed |
| io | P tests/agents/slo_agent/herdr/test_restore_io.py | 1 failed, 69 passed; fixture recursion |
| io2 | same | 70 passed |
| directories | P tests/agents/slo_agent/herdr/test_restore_security.py | 108 passed |
| package-cli | P tests/agents/slo_agent/herdr tests/cli/test_herdr_restore.py tests/cli/test_app.py tests/cli/test_typer_dispatch.py tests/cli/test_headless_request.py tests/cli/test_headless.py | 1124 passed, 5 warnings |
| final | same after directory tests and formatting | 1129 passed, 6 warnings; exit 0 |
| black | poetry run black --check src/agents/slo_agent/herdr/restore.py tests/agents/slo_agent/herdr/test_restore*.py | exit 0 |
| diff | git diff --check | exit 0 |
| coreutils | dpkg -V coreutils | silent, exit 0 |

Formatting logs: format.log and format2.log. Final package includes other existing lanes; count is not solely STORE additions. New tests were inspected directly (untracked files are not represented by ordinary git diff). No independent review or feature completion claim.
