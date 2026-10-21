# Core owner164 — bounded R161-1/2 READY for independent re-review

Accounting: Code+Test turn4/global164/current dispatch3; started4/completed0/historical stopped partial1/retries0; effective budgets UNLIMITED. No subagents. R161-3/4 remain next-task scope; no whole-feature completion or independent approval. Live DEFERRED; compatibility UNVERIFIED.

Verified branch `feature-94-herdr-integration`, origin `https://gitlab.com/core-27/slo.git`, base `d0e3a756689f2675e5507034d43cd8b272d3c6b8`. All pre-existing work retained, including unattributed ambiguous-close implementation and revision163 bounded read loop. No Git mutation, package/global/spec/other-worktree/live action or private transcript read.

## Changes and contracts

- `sequence_store.py`: preserve inspection-only ambiguous-close policy; add resource ownership predicate. No repeated close of an ambiguous slot. EBADF/different inode establish absence under exclusive descriptor ownership (no external duplicate/close/replace); matching inode is NOT generation proof and remains unresolved. Inspection errors also remain unresolved. This is conservative ownership, not a finite cleanup guarantee.
- `restore.py`: replace operation-local lease with one store-owned lease. Nonblocking thread operation guard prevents overlapping operation/cleanup. New operations refuse while a retained lease exists; explicit close reconciles it only after operations join. The failed save/load never becomes success, and immutable orphan records remain untouched. A demonstrated release clears ownership, not a fabricated permanent resource.
- `dao.py`: optional typed `HerdrRestoreResourceOwner` capability, separate from save-only injected collaborator protocol.
- `reporter.py`: include concrete restore resource ownership in disposal evidence; join save before off-loop cleanup and repeat only inspection during final local drain. Pre-existing retained restore ownership makes cleanup uncertainty sticky even when inspection later establishes drain. No remote resend. Existing intermediate close semantics deliberately unchanged (R161-3).
- Replace unsafe retry-close expectations in `test_final_lifetime_closure.py`: even a second syscall that would succeed is prohibited. Fixture-only teardown uses independently known generation, not production inference.

Tests: `test_restore_lease_retention.py` real save/load cleanup and retained owner/refusal/serialization; `test_restore_lease_reporter.py` restore-only final disposal; `test_lease_cleanup_matrix.py` actual pane and restore final drains; shared `lease_close_fault.py` temp-only exact descriptor fault fixture. Matrix includes close-before-error, close-after-release, different-file reuse, same-inode reuse, EBADF, inspection failure; asserts one close, replacement usability, reachable owner, fixed/private failures and honest retained/drained evidence.

R161-2: retained163 EOF/bound fix. `test_sequence_refusal_composed.py` queues the real viewer at the shared transport lock, then fails real reservation through short reads (corrupt suffix/4097-byte overflow/read error). No ticket, reporter disabled, viewer refused under lock, no executable entry, unchanged counter bytes, no shutdown send/repair. Prior163 five RED cases remain the implementation RED evidence; new composition tests are additional acceptance, not claimed pre-fix RED.

## Executed evidence

Runner: `core-owner-164-run.sh`; logs/exits/coreutils receipts: `core-owner-164/`. Python3.11.7 at `/root/.pyenv/versions/slo-harness`, explicit VIRTUAL_ENV/PATH/PYENV_VERSION, `make test-env=fallback`; no sourced secrets. Root fake/window guards unchanged. No full suite run.

| Receipt | Result |
|---|---|
|restore-red|1 failed (missing retained store ownership API), current-state RED|
|restore-green|63 passed|
|reporter-red|1 failed (false drained restore owner)|
|reporter-green|97 passed|
|matrix|14 passed|
|operation-matrix|23 passed|
|sequence-composed|72 passed|
|serialization-red|1 failed (active operation could be closed)|
|serialization-green|155 passed|
|outcome-red|3 failed/9 passed (released restore fault lost sticky uncertainty)|
|outcome-green|17 passed|
|final-core-2|**1109 passed,4 warnings,69.83s**, exit0; final production/test bytes|
|surrounds-final|**653 passed,283 warnings,271.09s**, exit0; before final one-line sticky-uncertainty correction|
|final-lifecycle-corrected|**101 passed,10 warnings,15.19s**, exit0; after that correction|
|lint|mypy src/agents/slo_agent/herdr tests/agents/slo_agent/herdr: **79 files clean**, exit0|
|black|same directories: **79 files unchanged**, exit0|

Final core command: runner `final-core-2` with every `test_*.py` directly in `tests/agents/slo_agent/herdr` except `test_session_*`/`test_attention_*`, plus `test_session_identity.py`, `test_token_format.py`, `orchestrator/test_context_reader.py`.
Surrounds command: runner `surrounds-final` with Herdr `test_session_*.py`, `test_attention_*.py`, CLI `test_herdr_restore.py`, `test_headless_herdr.py`, `test_headless_retained.py`, TUI `test_herdr_session_lifecycle.py`, `test_herdr_replacement.py`, `test_herdr_app_shutdown.py`, integration `test_herdr_full_flow.py`.
Final lifecycle command: runner `final-lifecycle-corrected` with Herdr `test_session_lifetime.py`, CLI `test_headless_retained.py`, and those three TUI modules.

All completed suite coreutils receipts are silent; explicit check after interrupted command also silent. `git diff --check` silent. Initial combined core+surrounds shell timed out at240s during surrounds: no success claimed for that partial log; rerun standalone with600s completed653. One final lifecycle invocation used nonexistent `test_session_lifecycle.py` (exit4, no tests); corrected path passes101. These are command corrections, not agent dispatch retries. Historical logs preserved.

## Scope/read qualification and remaining work

Read current source/test seams,163/161 reports and probes/read ledger, root RESEARCH, supplied AGENTS/CLAUDE/docs RESEARCH, routing/scope-plan, KB Welcome/slo README/gotchas, exact worktree workflow/cadence, shared ownership/testing/routing/coding rules, Python root/types/docs/declarative/application-service guidance, canonical B7.5 and C store/lock/read-bound prose. Initial aggregate skill output truncated; exact workflow subsequently reread. No claim of a fresh complete B/C/sample or full complex-public-API audit;161 ledger remains navigation, not this author's new audit.

Finite remaining: R161-3 intermediate/final contract and consumer aggregation; R161-4 full complex public API documentation audit; independent re-review of R161-1/2 and all broader partitions; fresh full-suite/static integration and Completion later. No further R161-1/2 behavior gap identified in this bounded implementation review. Resource properties and optional protocol are documented at their declarations; no casts/Any/ignores/config suppressions introduced.
