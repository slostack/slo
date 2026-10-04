# Feature 86 — Step 1 corrective implementation and verification evidence

**Date:** 2026-10-03  
**Scope:** Correct the retained 29-node complete-gate failure set only.  
**Verdict:** **READY for the requested Step 1 corrective gate.** This is not a
Step 2 review or Step 3 completion assessment.

## Governing material read

Before edits, this call read repository/global `SLO.md`, `AGENTS.md`, `CLAUDE.md`,
`docs/RESEARCH.md`; the Step-1 `code-test-loop`, `review-feature-code`,
`is-the-feature-completed`, named-arguments/types, declarative-method,
method-docstrings and test-verification skills; relevant agent/tool rules; Feature 86
overview and 86.a.6 immutable clauses; the integration report, all owner A–D
corrective evidence, current status, remaining matrix, implementation log and
independent A/B/C/final reviews; and KB `slo` entry/status/gotchas/harness material.
The installed read-only skill root
`/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills` was listed
successfully and was not modified. Relevant personal skills were listed; no Go or
TypeScript skill was applicable to these Python test-contract corrections.

The immutable spec root was read only. Historic incident files were not modified.
All existing tracked, untracked and scratch artifacts were preserved.

## Bounded TDD record

### 1. Capture descriptor contract

The retained failure showed the test expected
`SLO_CAPTURE_APPEND_LOCK_FD == descriptors[0] - 1`. The inherited append lease is
intentionally an extra descriptor after writer-lifetime transfer, so that allocation
number is not an identity contract.

`test_production_capture_opener_uses_exact_isolated_entry_without_spawn` now checks:

- the environment exposes an append-lock descriptor;
- it is not any locally allocated pipe descriptor;
- `/proc/self/fd/<descriptor>` resolves to the expected test-root
  `stdout.jsonl.append.lock` path;
- the same descriptor is passed through `pass_fds`;
- the pre-existing destination containment, FIFO, no-spawn, and all-pipe cleanup
  assertions remain.

Focused command/result:

```text
/root/.pyenv/versions/slo-harness/bin/python -B -m pytest -q \
  -p no:cacheprovider --basetemp=<owned-root>/tests \
  tests/agents/slo_agent/orchestrator/test_capture_contained_lifetime.py::test_production_capture_opener_uses_exact_isolated_entry_without_spawn --tb=short
# 1 passed, 2 warnings
```

Surrounding capture module: **38 passed, 2 warnings in 11.83s**.

### 2. Isolated-HOME plugin fixtures

The retained red gate exported `SLO_PLUGINS_DISABLED=1`; this is a production
kill switch, so plugin loader/session/TUI tests correctly found no candidates. The
actual defect was the invocation-level test environment suppressing tests that need
test-local plugin candidates. This was neither a loader production bug nor
permission to use the operator home.

`tests/conftest.py` adds an autouse, monkeypatch-owned fixture that removes **only**
that environment setting for an individual test. Existing plugin tests keep creating
synthetic regular plugin files under their `tmp_path` roots and supply explicit
managed/project/CLI roots. The explicit kill-switch test sets `SLO_PLUGINS_DISABLED=1`
after fixture setup and remains positive coverage of the production behavior.

Red reproduction under the exact isolated environment: **18 failed, 6 passed,
5 warnings**. Green under the same isolated environment: **24 passed, 5 warnings in
1.48s** across loader, session wiring, runtime command, and `/plugins` tests.
Positive registrations, tool/event behavior, command dispatch, project trust/reload,
and expected load-failure isolation all execute.

### 3. Catalog message compatibility

The first full red gate predated the already-present message correction. It had ten
failures because exact routes were missing from unlisted-variant messages. The source
now retains the exact requested canonical route and the literal required guidance:
`unsupported variant; choose a catalog entry or /model refresh`.

Fresh catalog integrity/read-view partition: **22 passed, 2 warnings in 0.99s**.

## Fresh required full gate

The final command used exactly the approved interpreter, bytecode disablement,
`env -i`, isolated owned HOME/SLO_HOME/TMPDIR/auth path, test-owned base temp,
no pytest cache provider, usual E2E marker deselection only, and an explicit 1200s
timeout:

```bash
timeout 1200 env -i \
  PATH=/root/.pyenv/versions/slo-harness/bin:/usr/bin:/bin \
  VIRTUAL_ENV=/root/.pyenv/versions/slo-harness \
  HOME="$ROOT/home" TMPDIR="$ROOT/tmp" SLO_HOME="$ROOT/home/.slo" \
  SLO_AUTH_FILE="$ROOT/home/auth.json" SLO_ENV=test \
  SLO_AUTO_VISUALIZE=0 SLO_PLUGINS_DISABLED=1 \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  /root/.pyenv/versions/slo-harness/bin/python -B -m pytest -q \
  -m 'not e2e' -p no:cacheprovider --basetemp="$ROOT/tests" tests --tb=short
```

**Result:** exit **0**; **5065 passed, 15 deselected, 202 warnings in 352.33s**.
The only deselections are the usual `e2e` tests. Complete log:
`.f86-step1-full-XyirL9/full-non-e2e.log`.

`git diff --check` also exited 0. No formatter or mypy gate was run, as the request
waives only those static gates.

## Safety and limits

- No live provider request, paid inference, real credential inspection, installation,
  deployment, or external network action occurred.
- No system/PATH file was written. Tests wrote only inside their pytest-owned roots;
  capture tests assert resolved containment and plugin fixtures are regular
  test-root files, not symlinks to system or operator-home files.
- No Git staging, commit, push, merge, reset, clean, rebase, worktree creation, or
  specification edit occurred.
- This call records correction evidence only. It makes no claim about independent
  review completeness or feature completion.
