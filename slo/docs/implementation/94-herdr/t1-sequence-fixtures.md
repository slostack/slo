# T1 sequence and fake fixture foundations

T1 implementation handoff: READY subject to the final receipts below; no T2 activation or independent review claimed. Routing and source specifications remain unchanged.

## Owners and contracts

- `src/agents/slo_agent/herdr/sequence_store.py`: inert `HerdrSequenceStore(state_root, socket_namespace, pane_id)`, synchronous acquire/reserve/close for T2 to call off-loop. SHA-256 of an unambiguous JSON tuple (socket namespace, pane, source family) names adjacent JSON/lock files under sequence-v1. No session ID or raw private text in persisted state. Lifecycle/display counters are independent; the store rejects noninteger/bool/negative/unknown-version/overflow data and never repairs corruption.
- The same `HerdrFileLease` supports distinct pane/restore paths. Private owned directories, regular single-link files, no symbolic links/traversal, no-follow open plus device/inode matching, nonblocking native locking and failure cleanup. Lock files remain after close. POSIX contention/crash is actual OS-process evidence; Windows byte-lock branch is a recording-adapter test, not native Windows certification.
- Reservation revalidates held lock and state, calls unchanged `AtomicFileWriter.write_text_with_outcome`, and returns only after committed/no-warning evidence. Errors are fixed text; unsafe reservations poison the current state until close/reacquisition. A committed durability warning consumes a gap, never a sendable number. State reads are bounded at 4096 bytes. Local filesystems with supported locking are required; network-filesystem semantics are not certified.
- `tests/state_isolation.py`: existing guard now also rejects hardlinks and nonexecutable capability targets; frozen `FakeHerdrFixture` carries executable/capture/barrier/guard.
- `tests/conftest.py`: explicit per-test `fake_herdr_guard` starts ungranted; `fake_herdr` creates new contained regular files, registers every target, then sets synthetic opt-in variables. Actual fake execution records argv. Substitution of executable, capture or barrier is refused before delegation. Real-terminal guard remains unchanged. T2 must wrap its actual transport `_spawn` with this capability; no such transport exists or is enabled in T1.

Security scope: private owner-controlled local directories plus validation at use boundaries; no claim of protection from malicious concurrent code running as the same OS user. No real Herdr/providers, global state changes, agents, commits or source-spec edits. Only test-owned subprocesses are killed/reaped in crash tests.

## Test-first increments

All receipts are in this directory. Each numbered RED preceded its bounded implementation and GREEN included the surrounding Herdr folder (the DAO runner also selects its two existing modules). No implementation block exceeded approximately 50 executable lines between tests.

| Increment | Actual RED | GREEN |
|---|---|---|
| sequence 01 | missing module collection error | 66 passed |
| sequence 02 | missing store, 1 failed/49 passed | 67 passed |
| sequence 03 | overflow/reentrant ownership, 3 failed/55 passed | 75 passed |
| sequence 04 | unsafe reservation targets, 5 failed/58 passed | 80 passed |
| sequence 05 | missing-root and Windows branch, 2 failed/63 passed | 82 passed |
| fixture 01 | five missing-fixture errors/42 passed | 87 passed |
| sequence 06 | oversized state, 1 failed/74 passed | 103 passed including AtomicFileWriter |
| fixture 02 | hardlink/nonexecutable, 2 failed/53 passed | 101 passed |

`sequence-process.log`: 102 passed including real process contention, graceful restart and SIGKILL restart, writer error/committed warning/uncommitted refusal, malformed/version preservation. Later test-only coverage adds namespace isolation, unsupported platform refusal, descriptor-substitution races and unheld/invalid-source refusal. Tests never use a real Herdr binary.

## Commands and environment

CWD `/root/Code/slo-94-herdr-integration/slo`; verified pyenv interpreter `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7; `make test-env` = fallback. Targeted runs use `bash docs/implementation/94-herdr/t1-dao-check.sh <paths>`: that retained script records the routing-approved subprocess fallback exports and `PYTHONPATH`, then `poetry run pytest -q -m 'not e2e'`. It does not source development state.

Final authoritative gates: `sequence-full.log/.exit`, `sequence-smoke.log/.exit`, `sequence-lint-final.log/.exit`, `sequence-black-final.log/.exit`, `sequence-coreutils.log/.exit`. See consolidated `t1-code-test.md` for final counts. Earlier full receipt (6432 passed) preceded three additional test-only cases and is superseded by the final run.

Lint initially exposed two Windows module typing errors, corrected with a scoped native adapter Protocol; an added race-test annotation then exposed one argument-type error, corrected without ignores. Final diagnostic comparison must match `t1-lint-final2.log` exactly: 301 errors in 64 files. This is baseline debt, not a passing lint gate or waiver.

## Handoff

Use unchanged B 7.5/final helper contracts and tasks.md T1 attachments. T2 owns async thread joins, reservation-to-send ordering, fake-only actual spawn guard, activation release and disabled mounted/headless proof. T3 consumes the same lease mechanism on its distinct restore lock. T2–T6 and independent full-scope review/completion remain pending. Turn 1 started 1/completed 0/historical partial 0; dispatch 8 consumed, 12 remaining of 20; unlimited turns; retries 0. No dispatch made here.
