# T1 foundations — incomplete execution receipt

Entire T1 is **NOT READY**. This continuation implemented only the registration/identity core, not all requested remaining foundations. No product blocker has been established; this is incomplete execution, not a request for authorization.

## Actual bounded code/test cycle

- `tests/state_isolation.py::FakeHerdrSpawnGuard` implements B23's registration and pre-delegation identity revalidation. It rejects unregistered, relative, traversal, linked, outside-root, nonregular and replaced executable/capture targets. No production activation or transport exists yet.
- `tests/agents/slo_agent/herdr/test_spawn_guard.py` creates only new regular files in its own resolved temporary root; substitution uses a separately created file to guarantee a different inode. Symlink refusal uses only a test-owned target, never a system executable.
- RED: `foundations-guard-red.log`, pytest exit 1, **9 failed**, missing helper before implementation.
- GREEN/surrounding: `foundations-guard-green.log`, pytest exit 0, **29 passed**, covering the Herdr test folder and `tests/test_slo_home_isolation.py`.
- Implementation increment: under 50 added implementation lines before GREEN.
- Black formatted only the new test; `poetry run black --check tests/state_isolation.py tests/agents/slo_agent/herdr/test_spawn_guard.py` exit 0 (2 unchanged). `git diff --check` exit 0.
- `dpkg -V coreutils`: exit 0, silent after the stub-containing surrounding run.

Commands used routing.md's exact fallback environment and `PYTHONPATH="$PWD" poetry run pytest -q` with the named test paths. Interpreter verified `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. No full suite was rerun in this continuation; prior full-suite receipt remains historical, not post-change proof.

## Outstanding requirements

1. Finish test-local fake executable/capture/barrier creation capability and conftest fixture; additional missing-file/link-parent cases. Real transport wrapper remains T2 by allocation.
2. All shared frozen public/private DAOs/protocols and session attention/provenance vocabulary.
3. Complete identity closure extraction and strict UUID helper; exact formatter extraction and footer delegation.
4. Secure distinct-scope lease and durable hashed sequence store, including real process contention/restart/failure evidence.
5. Complete exact scoped tests, changed-file Black, final full non-E2E suite and scope review.

No consolidation of `t1-code-test.md`: its entire-T1 readiness prerequisite is not met. Routing, Makefile, earlier isolation behavior, source specs, globals and other worktrees were not changed. No spawned agents, commits, pushes, live Herdr or provider calls. Independent full-scope review/completion remain later gates. Supplied accounting retained: turn 1 active, started 1/completed 0/historical partial 0; dispatch 6, 14 remaining of 20; unlimited turns; no retries.
