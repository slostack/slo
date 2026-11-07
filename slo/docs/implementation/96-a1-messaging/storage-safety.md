# EF96-01 / EF96-02 storage revision — REVISE

Useful bounded Code+Test progress, **not full EF01/EF02 closure**, Step1 READY,
module acceptance or full A.1. Formal independent Review and Completion remain
pending. No external blocker; remaining work is concrete implementation/proof.
Turn 2/60 dispatch 1/20; prior turn partial and retry accounting unchanged.
Ledger untouched. No nested agents, commit/push, runtime wiring, canonical-spec
edits, queue/client/recovery implementation or ownership rewrite.

## Authority and source reconciliation

Read continuation ledger first; project AGENTS/CLAUDE/SLO, root RESEARCH and
supplied docs/RESEARCH; current early-feedback, change2-plan, change2-retry1 and
commands. Active installed skill sources and bounded plan are recorded in
[storage-safety-plan.md](storage-safety-plan.md). Consulted KB Welcome,
slo/README and gotchas. Python 3.11.7 at
`/root/.pyenv/versions/slo-harness/bin/python` (documented slo env absent), SQLite
3.45.1, Pydantic 2.13.5. No environment/package changes.

Canonical HTML `96.a.1-session-owned-durable-delivery.html` §8 store
(`#srcagentsslo_agentmessagingstorepy`) supplies private no-follow storage,
pragmas, exact core DDL, sealed startup, state/sequence agreement, immutable
original target and current-generation live submit (including duplicates).
§3 plus `assets/a1-runnable-core.md` and `a1-implementation-walkthrough.md`
require no automatic execution at restart and explicit history reconciliation.
Storage seal is **not** that session reconciliation. Note-boundary index is
already in this core; no later-only tables or services were added.

Independently reproduced first RED: 10 failures/8 passes, including WAL/SHM
acceptance, public/foreign inodes and corrupt-open descriptor leak. Existing
`/proc/self/fd` opening was not assumed broken: real WAL/reopen test passed before
repair. No claim that uri=True alone repairs SQLite safety.

One old test oracle was corrected: `test_retry_after_reopen_returns_original_outcome`
expected retained_for_recovery=False after reopening accepted input. Canonical
restart/no-autoexecute rule requires True. Actual `ef02-startup-green2.log`
records the sole failure (148 others passed). The corrected assertion compares
**all** original receipt fields, changing only the documented recovery flag.
Tests still explicitly enable lifecycle where live admission is intended;
production open never autoaccepts. No test weakened to accept corrupted data.

## Requirement → evidence

| Finding / requirement | Implemented / public real-boundary proof | Remaining before closure |
|---|---|---|
| EF96-01 / M2 worker path safety | All traversal, creation, permission/inode validation on store worker. No-follow descriptor-relative directory walk; no pathname chmod. DB/WAL/SHM require current UID, regular file, 0600, single link; held descriptors persist until connection close. Canonical absolute session/name checked before filesystem access. 15 hazard cases plus linked ancestor unchanged-destination assertions. | **Not complete**: stdlib SQLite VFS can canonicalize descriptor URI to ordinary paths; held descriptors/rechecks do not eliminate same-UID replacement races inside VFS. Supported-local-filesystem detection and full unsupported-platform proof absent. |
| EF96-01 / partial startup and cancellation | Connection and fd lifetime unwind on corrupt DB, real SQLite authorizer-denied journal pragma, and schema failure. Worker shutdown observed; repeated cancelled startup joins real failing operation before cancellation returns. Concurrent/repeated cancelled close tests retained. Actual connection-local busy_timeout=1000, foreign_keys=1, synchronous=2, journal_mode=wal observed on worker. | **Not complete**: cleanup exceptions/failure honesty, repeated cancellation during cleanup itself, and race-safe native VFS close after permanent namespace replacement not proved. New successful replacement test fails publication; live substitution tests restore original namespace before native close, explicitly not a permanent-replacement close guarantee. |
| EF96-02 / schema and metadata | Version 1 validates complete core SQL definitions (including constraints/index predicates), rejects extra triggers/columns/missing table/index, integrity_check and foreign_key_check, exact meta keys, canonical generation/sequence/lifecycle and next_sequence > max. Failed startup does not change DB bytes/meta in eight corruption cases. No fallback. | Definition comparison normalizes whitespace/case but may reject semantically equivalent quoting/formatting; full compatible-shape matrix incomplete. Integrity/validation currently scans lifetime records before operations; bounded paging/performance remains unsolved. |
| EF96-02 / sealed current-generation startup | Every successful reopen atomically seals, adopts owner generation, retains accepted **and applying** input without rewriting submission/claim identity. Same/new-generation tests prove old accepted/unprepared claims cannot execute before or after enablement; new input gets sequence 2. Sealed fresh claim returns None. | Prepared-journal/terminal multi-generation and history-evidence reconciliation matrix incomplete. Full recovery/reset contracts EF96-04 remain open. |
| EF96-02 / cross-record trust and authorization | Startup and public operations validate decoded principal/target/receipt/identity, body digest, original target, source/kind/priority, mirrored state/sequence/run/generation, deterministic claim ID and timestamps. 13 external real SQL corruption cases refuse receipt/admit/reopen with unchanged record/counter dump. Full-principal mismatch is unauthorized for duplicate/receipt, and summary discloses no text. Live stale target refused before duplicate; original same-generation outcomes preserved. Terminal cancelled tombstone survives pruning/reopen; prior applied/prune test retained. | **Not complete**: application/event/journal consistency and exact normalized evidence EF96-03; original source shape/receipt state matrix; identity-only digest verification after pruning (body unavailable), recovery/compaction/observation trust matrices. Validation is before operation, not an atomic snapshot around every subsequent read/transaction: concurrent external mutation remains a gap. |

No M1–M7 whole acceptance claim. M2 improved but remains REVISE. M3 unchanged
(EF96-06 open). M4/M6 concrete skeletons and M5 session-owned behavior remain
undelivered; no competing execution owner added. M7 integration expressly excluded
by user, not delivered. Existing early-feedback EF03–06 and Change2 finite list
still apply except the bounded sub-behaviors evidenced above.

## Exact commands and receipts

Cwd `/root/Code/slo-message-queue/slo`, branch `message-queue`. Every pytest command
used this exact Makefile fallback environment (no tests.env):

```bash
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
```

Each stem below has complete `.log` stdout/stderr and actual `.exit` beside this
report. Wrapper exit is not the test verdict. Logs never overwritten after a
subsequent run: numbered/final names distinguish attempts.

| Receipt | Exact command | Actual result |
|---|---|---|
| ef01-path-red | `python -m pytest tests/agents/slo_agent/messaging/test_storage_safety.py -q` | exit 1, 10 failed / 8 passed |
| ef01-path-green | same | exit 0, 18 passed |
| ef01-focused-first | `python -m pytest tests/agents/slo_agent/messaging/ -q` | exit 0, 131 passed |
| ef01-cleanup-red | `python -m pytest tests/agents/slo_agent/messaging/test_storage_safety.py::TestSQLitePartialStartup -q` | exit 1, 4 failed (new construction seam absent) |
| ef01-cleanup-green | `python -m pytest tests/agents/slo_agent/messaging/test_storage_safety.py -q` | exit 1, 2 failed / 20 passed; test readback hit SQLite thread affinity before closed check |
| ef01-cleanup-green2 | `python -m pytest tests/agents/slo_agent/messaging/ -q` | exit 0, 135 passed; real test factory disables check_same_thread solely to inspect closed connection after worker shutdown |
| ef02-startup-red | `python -m pytest tests/agents/slo_agent/messaging/test_storage_safety.py::TestSealedValidatedStartup -q` | exit 1, 13 failed / 1 passed |
| ef02-startup-green | `python -m pytest tests/agents/slo_agent/messaging/test_storage_safety.py -q` | exit 1, 36 failed; implementation missed forwarding required target keyword, corrected immediately |
| ef02-startup-green2 | `python -m pytest tests/agents/slo_agent/messaging/ -q` | exit 1, 1 failed / 148 passed; false retained-flag oracle described above |
| ef02-records-red | `python -m pytest tests/agents/slo_agent/messaging/test_storage_safety.py::TestStoredRecordTrust -q` | exit 1, 16 failed; prebuilt coroutine tuple caused unawaited warnings on early failure, changed to lazy callable construction |
| ef02-records-green | `python -m pytest tests/agents/slo_agent/messaging/ -q` | exit 0, 165 passed |
| ef02-claims-red | `python -m pytest tests/agents/slo_agent/messaging/test_storage_safety.py::TestStartupClaimIsolation -q` | exit 1, 3 failed |
| ef02-claims-green | `python -m pytest tests/agents/slo_agent/messaging/ -q` | exit 0, 168 passed |
| storage-affected | `python -m pytest tests/agents/slo_agent/ -q` | exit 0, 2486 passed, 220 warnings, 112.91s |
| ef02-summary-red | `python -m pytest tests/agents/slo_agent/messaging/test_storage_safety.py::TestLiveReadTrust -q` | exit 1, 1 failed / 3 passed |
| ef02-summary-green | `python -m pytest tests/agents/slo_agent/messaging/ -q` | exit 0, 172 passed |
| storage-focused-final | same | exit 0, **173 passed**, 2 warnings, 12.56s |
| storage-affected-final | `python -m pytest tests/agents/slo_agent/ -q` | exit 0, **2491 passed**, 220 warnings, 114.39s |
| storage-scoped-mypy-final | `python -m mypy src/agents/slo_agent/messaging/{store,dao,ownership}.py` | exit 0, 3 files |
| storage-black-final | `python -m black --check src/agents/slo_agent/messaging tests/agents/slo_agent/messaging` | exit 0, 14 files unchanged |
| storage-diff-check | `git diff --check` | exit 0; tracked whitespace only, not untracked-file review |
| storage-mypy | `python -m mypy src/agents/slo_agent/messaging` | exit 1: 4 empty-body errors in unchanged queue.py:82,157 / client.py:116,128; **not waived**, do not fix outside scope |

An additional diagnostic `python -m mypy src/agents/slo_agent/messaging/store.py tests/agents/slo_agent/messaging/test_storage_safety.py`
exited 1 with six imported provider errors (faux.py, anthropic_claude_code.py,
openai_codex.py); no retained receipt or passing claim. Full `make test` / `make lint`
not run in this bounded increment, still mandatory before overall Step1 readiness.
No baseline exception. Extra final terminal regression reuses existing behavior
and is confirmation, not claimed new RED/GREEN behavior.

## Files and self-check

Changed `messaging/store.py`; added `test_storage_safety.py`; one cited assertion
repair in `test_store.py`. DAO, ownership, queue/client/delivery and all untracked
prior artifacts preserved. Compact docs only elsewhere. Reviewed new untracked
source/tests directly, not just git diff. No real tools stubbed, system paths
modified, real credentials used or terminal launched. All hostile files,
symlink/hardlink/foreign-owner fixtures live under tmp_path. Factory seams use the
real sqlite3 engine and native authorizer/trace callbacks, not durability mocks.

## Finite next closure targets

1. Finish EF01 VFS containment/publication/close race and failure cleanup guarantees
   **before activation**. Rechecks must not be represented as race-free open.
   Keep resources held or fail closed where safe cleanup cannot be established.
2. Finish EF02 atomic startup/read validation and full compatible shape/corruption
   matrix, including prepared journal and pruned terminal states across generations.
   Do not turn the lifetime scan into a falsely bounded reader.
3. EF03 exact event proof, EF04 consent-bound local recovery, EF05 paging/compaction,
   EF06 ownership path stability, remaining M1/M4/M5/M6 and overall gates follow
   original authority. No additional scope is silently accepted here.
