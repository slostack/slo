# Authorized exact-entry retry — bounded behavioral qualification

## Result

Step 1 remains **REVISE**, Step 2 not eligible. This retry delivered a changed test-local implementation and real passing late-kernel-failure execution, not a startup-seam report. No production, spec, shared interpreter, PATH, other worktree, credential, or network changes were made. Existing dirty work was retained.

## Requirement decision

Read-only authoritative source: `/root/Code/specifications/projects/slo/specifications/86-openrouter-intergration/86.a.4-prepare-and-pin-openrouter-runtime-contexts.md`, §§7.6–7.7 requires existing drain/status/notify lifecycle, consistent identity and the trusted credential boundary. The source does not prescribe literal test-wrapper argv equality. The earlier exact-entry report already distinguishes that from the task qualification. Under the user's explicit authorization to replace an overspecified assertion with stronger behavioral proof, the two qualification tests now describe **body/native IO/resource inheritance**, not exact subprocess argv. The independent production-opener exact-argv/FD/cleanup test remains unchanged.

## Concrete implementation

Only `tests/agents/slo_agent/orchestrator/capture_test_safety.py` and `test_capture_contained_lifetime.py` changed:

- Removed custom RawIOBase/stdout replacement and `os.write` substitution.
- Removed RLIMIT_FSIZE injection and reporter-side restoration entirely.
- Retained audited, finite test-root bootstraps and exact inherited-descriptor checks. Writer executes the shipped source via runpy as `__main__`; reporter executes the exact shipped inline body with its original `-c` payload and `<string>` filename. This is explicitly not literal exec-argv equivalence.
- A test-local trace observes actual shipped `invoke`/drain frames. It verifies native BufferedWriter/FileIO and unchanged stdout/os.write, records source hash, source path, main entry and inherited limits.
- After the first real redacted stdout flush, the trace opens the SAME owned capture inode read-only and dup2s it onto that writer's FD 1. The next native FileIO write raises real kernel **EBADF (9)**. No Python exception is manufactured and no resource limit affects the reporter. This models a descriptor-access failure, not disk-full or quota exhaustion.
- Workload output is gated by successful launcher communicate/reap; second output waits for a nonempty first capture. Workload remains alive at health/status observation and is released/reaped afterward.
- Reporter records exact body hash/payload, empty nonstandard descriptor tuple, environment (only CPython locale coercion may add LC_CTYPE), unchanged inherited limit, and a completion receipt after the real store call returns.
- Live assertions require exactly two writer proofs, exactly one kernel error and reporter completion, redacted nonempty stdout/stderr, unchanged workload PID/PGID/launching state, and fresh store/status safe health. Clean path requires two writer proofs and no reporter receipt.
- Both previously reported reporter-test mypy errors are fixed. Checking the helper also found its direct Popen assignment diagnostics; changed that assignment to the existing MonkeyPatch owner.

The wrappers still install Python audit/tracing instrumentation. They are not a general OS sandbox, and this does not claim native interpreter startup equivalence or whole-feature security acceptance. The fault deliberately changes only the owned capture descriptor's access mode; the same inode/path remains test-owned.

## Executed evidence

All Python commands used `/root/.pyenv/versions/slo-harness/bin/python -B`, with `PYTHONDONTWRITEBYTECODE=1`. Fresh roots were created by `tempfile.mkdtemp(prefix=..., dir=Path.cwd())`; pytest used `-q -p no:cacheprovider --basetemp=<root>/tests --tb=short`. No roots were deleted.

1. First materially changed implementation, module `test_capture_contained_lifetime.py`: **38 passed**, 2 warnings, 11.78s. Root `.f86-entry-retry-p0nr6kms`.
2. Added live shipped-frame/hash/errno/resource/reporter-completion assertions. Module plus `test_capture_control_protocol.py` and `test_capture_ack_cleanup.py`: **73 passed**, 2 warnings, 11.89s. Root `.f86-entry-retry-final-2tvval5b`.
3. Mypy both touched Python files initially found two helper Popen assignment diagnostics. Root `.f86-entry-retry-static-i91tdar3`. Corrected through existing MonkeyPatch ownership.
4. Final same three-module partition: **73 passed**, 2 warnings, 11.75s. Root `.f86-entry-retry-gates-2h0s8kgy`. Includes both corrected qualification tests and actual reaped-launcher late-kernel-failure test.
5. `python -B -m black --check --no-cache <both touched Python files>`: **2 unchanged**.
6. `mypy.api.run(['--follow-imports=silent', '--cache-dir=<final-root>/mypy', <both touched Python files>])`: **Success: no issues found in 2 source files**.
7. `git diff --check`: pass before final documentation and rerun after it.

## Remaining matrix

| Requirement | Current evidence |
|---|---|
| Production opener exact command/FD cleanup | Retained independent passing no-spawn test |
| Contained writer/reporter semantic qualification | Passing corrected tests plus live receipts; wrappers explicitly disclosed |
| Reaped launcher, late kernel fault, fresh reporter/store/status | Passing real EBADF case, native IO, unchanged resource limits and live workload identity |
| Clean path reporter nonexecution | No reporter receipts with two positive writer receipts |
| Complete safety/security acceptance | Not closed: broader child-write/cleanup adversarial matrix and raw-body/rotated-key artifact coverage remain |
| Plan B append drain | Pending |
| OS-process resume contention | Pending |
| Full non-e2e and whole-project static gates | Not run; no completion claim |

KB was consulted read-only; no writes outside the checkout. No system command stubs or binary changes were used.
