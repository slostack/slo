# T6 harness safety close 142 — INCOMPLETE; positive HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 142, retries 0. Effective turn/dispatch budgets unlimited. No agents dispatched. This is author evidence, not parent verification or overall READY.

## Implemented and tested

Changed only bootstrap and safety-test code. Entry and parent wiring from 141 remain intact. Added opened-descriptor metadata validation to `ProcessSafety.descriptor_path`: reject nonregular/nondirectory descriptors and multiply-linked regular descriptors before the original write syscall. Directory capabilities remain allowed for existing dir_fd operations. Four implementation lines; no broad permission bypass.

Two new deterministic tests replace only the fstat result for an actual temp-owned regular descriptor with special-file or multiply-linked metadata while retaining its device/inode. Before correction both reached the write syscall: **2 failed, 140 deselected**, `Failed: DID NOT RAISE PermissionError`, pytest exit 1. After correction the complete safety module passed **142 tests, 2 warnings in 61.53s**, exit 0. These are injected metadata decision tests, not actual FIFO-race certification.

Added `test_actual_atomic_writer_and_lease_under_child_guard`: existing READY supervisor runs a contained regular Python script with installed guard before application persistence imports. Actual AtomicFileWriter executes temporary creation, buffered write/flush/fsync, chmod, replace and directory fsync/close. Injected replace failure executes real temporary unlink and preserves committed bytes; directory enumeration proves no leftover temporary. Actual HerdrFileLease executes create/write/close, verified reopening, flock, require_held and close. No positive product entry, model, Herdr protocol or window runs. This regression was already green: **1 passed, 142 deselected**, exit 0; no invented RED.

## Finite requirement reconciliation (not complete)

| Original requirement / remaining row | Evidence and current disposition |
|---|---|
| 122 direct-child timeout lacked descendant ownership | PROCESS136 supervisor READY, anchor/reap/retention tests retained and rerun in 143-test module |
| 127 missing descendant/leader-exit and cleanup failures | Later PROCESS136 proof remains authoritative within its stated exclusive-owner scope; not reopened |
| 122 integer/dir_fd mutation omission | Existing descriptor wrappers and directory-capability tests rerun; 141 eight installed mutation refusals retained |
| 122 alternate execution omission | 138 actual exec/spawn refusals plus 140 matching/substituted Popen/run/asyncio proofs retained and rerun |
| 122 unsafe sibling probe | 141 supervised probe uses enclosing-test-owned victim; request tests prohibit legacy subprocess.run |
| 138 generated append check/open race | 140 actual generated current-body preservation and controlled old-behavior exit-41 sensitivity retained and rerun |
| Opened special/multiply-linked descriptor metadata | New 142 fstat decision RED/GREEN closes these two descriptor_path branches |
| Actual atomic persistence and lock operations | New 142 installed-child regression passes success/failure cleanup and lease cycle |
| Parent positive wiring | 141 exact-request tests retained; both policies rerun without executing positive entry |
| Remaining opened-FD capture details | Still incomplete: actual after-admission nonregular/hardlink substitution, pathname disappearance/change after opening, mode-change policy reconciliation, capture-specific close-error disposition and generator registration refusal inventory |
| Complete used persistence/cleanup inventory | Still incomplete: history tree/flat creation/append/metadata/transcript, preferences and other reachable writers have not all been traversed and compared to installed child guard; unsupported-fallthrough reconciliation not finished |
| Required context closure | Still incomplete, detailed below |

The actual atomic writer uses NamedTemporaryFile (internally tempfile allocation), not a new hand-written mkstemp owner. Buffered file writes are admitted at open, not intercepted per buffer flush. fsync/close and flock are not currently wrapped by ProcessSafety. The new test proves these real owned operations work under the guard; it does not establish refusal for every descriptor operation. No all-API sandbox claim or expansion is made.

## Context read accounting

Read audit141 fully; bootstrap 1–240 and 578–742; entry fully; safety tests 1–529 and 1500–end; root RESEARCH; routing; scope-plan; historical 122/127/136/138/140 receipts; safety123 current sections. AGENTS, CLAUDE and docs RESEARCH supplied in context, not freshly reread fully from disk. Read AtomicFileWriter, restore.py and sequence_store.py fully; history mutation search is only navigation, not full owner traversal.

Read KB os ROLE first, then os README and KB Welcome. Selected engineering routing/testing/ownership and coding rules/cadence were fully read. Python root/declarative/named arguments/docstrings/Faux guidance were visible in a combined read; its beginning truncated shared declarative content. Canonical B1872–2070 was read; broader C construction, exact T6 attachments and accepted reviews/task-breakdown evidence were NOT freshly closed. Skills INDEX, complete workflow SKILL, remaining KB detail and historical safety-test lines remain unread here. A four-call malformed parallel batch read nothing. Two oversized combined reads truncated; they are not counted as complete ingestion. Thus the requested complete context closure is not claimed.

## Exact final verification

Cwd `/root/Code/slo-94-herdr-integration/slo`; no env file sourced. All test commands used:

```sh
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
P=/root/.pyenv/versions/slo-harness/bin/python
"$P" --version
"$P" -B -m black --check tests/integration/herdr_restore_process_bootstrap.py tests/integration/herdr_restore_process_entry.py tests/integration/test_herdr_two_process_restore.py tests/integration/test_herdr_restore_harness_safety.py
"$P" -B -m mypy --follow-imports=skip tests/integration/herdr_restore_process_bootstrap.py tests/integration/herdr_restore_process_entry.py tests/integration/test_herdr_two_process_restore.py tests/integration/test_herdr_restore_harness_safety.py
"$P" -B -m pytest -q --tb=short tests/integration/test_herdr_restore_harness_safety.py
dpkg -V coreutils
git diff --check
```

Actual final output:

```text
Python 3.11.7
4 files would be left unchanged.
Success: no issues found in 4 source files
143 passed, 2 warnings in 63.45s (0:01:03)
pytest=0 coreutils=0 diff=0
```

Black/mypy each exited 0. Coreutils silent after every pytest invocation. Warnings only pythonjsonlogger relocation and LangGraph allowed_objects pending default. Root fixtures retain pre-import/per-test HERDR stripping, fake-only permission and terminal guard. Child persistence test uses explicit empty environment plus supervisor disablement. Four-file mypy skips imports; not repository lint. Files remain untracked, so git diff does not inspect their bodies; added/changed sites were inspected directly and Black checked all four.

## Verdict

**INCOMPLETE — overall harness READY withheld.** Concrete metadata defect corrected test-first and actual atomic/lease compatibility proved. Remaining finite opened-FD decisions, complete reachable persistence map/unsupported refusal accounting and mandatory reads are not closed. Passing 143 units does not discharge those rows. Positive family/full make remain HOLD until an overall report is complete and parent verifies it and separately authorizes positive execution.

No agents, old probe, full make, positive family, real provider/Herdr/windows, system/global/live/spec/other-worktree changes, commit/push/PR/reset/clean/stash. Documentation writes only this report and a current section in safety123; historical material preserved. No shared workflow status change. No arbitrary workflow budget was applied, and this is not a completed workflow turn.
