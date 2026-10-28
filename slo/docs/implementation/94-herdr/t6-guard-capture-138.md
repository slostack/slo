# T6 guard capture 138 — implementation landed; INCOMPLETE / HOLD

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 138, retries 0. Turn/dispatch budgets unlimited; no agents dispatched. No independent acceptance.

## Changes

Only bootstrap, entry and safety tests changed as code. `ProcessSafety.append_capture` opens without create/truncate using O_APPEND/O_NOFOLLOW/O_NONBLOCK, then requires regular single-link fstat and exact pre-registered device/inode before any write. Descriptor pathname containment/identity is checked again. Short writes are completed; zero progress fails; the descriptor closes in finally. This is bounded accidental-capability protection, not atomic filesystem confinement or a malicious-Python sandbox.

`capture_script` is now the single generated fake writer body used by entry `publish`. It embeds the capture identity and installs ProcessSafety before append. The entry no longer generates pathname-stat-then-buffered-open code. Positive product entry was NOT run.

The deterministic unit substitutes a parent-owned sibling victim between containment check and actual open by moving the old capture aside and moving the victim into its pathname. All paths remain inside the parent test tmp directory, with the victim originally outside the child allowed subtree. Refusal preserves old capture and victim bytes. No host files/system links are used.

## Executed evidence

Approved Python: `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7 verified through Poetry. Cwd is this checkout. Environment:

```sh
export PYENV_VERSION=slo-harness SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"
```

1. `poetry run pytest -q --tb=short tests/integration/test_herdr_restore_harness_safety.py -k capture_open_identity`: 2 failed/101 deselected, exit 1, missing append_capture. This is an API-first RED, not an executed exploit of the old generated body.
2. Added 25-line writer increment; whole safety module: 103 passed, 2 warnings, 53.57s, exit 0.
3. Generated script test RED: 1 failed/103 deselected, exit 1, missing capture_script. Added generator and replaced entry body, under 50 implementation lines. Whole module: 104 passed, 55.30s, exit 0.
4. Added actual Popen/run/asyncio/exec/posix_spawn calls inside supervised isolated Python with a contained inert dummy. Executable path is declared but identity intentionally mismatches; no PATH lookup or shell. Missing guard can only execute the harmless contained dummy in the disposable child. All five refuse. Whole module: 109 passed, 59.83s, exit 0. Black unchanged; mypy initially found three arg-type errors in the new open test helper, then corrected explicit signature without ignores.
5. Added six unsafe capture targets (missing/directory/hardlink/symlink/outside/traversal), fstat/write/zero-progress failures and partial-write completion with descriptor disposal checks. Final whole safety module: **119 passed, 2 warnings in 59.73s**, pytest exit 0. `black --check` and `mypy --follow-imports=skip` on all three changed Python files pass. `git diff --check` and `dpkg -V coreutils` silent. Each test command ran coreutils verification afterwards; no output on any run. Final shell exit 0. Output retained in tool transcript, not additional log artifacts.

The actual generated script positive runs via OwnedProcessRun.run_supervised, using approved Python -I -B, asserts append bytes and supervisor ECHILD. This is not the Herdr protocol-positive family. Refusal surface tests likewise assert receipt, zero return and supervisor ECHILD. No exec negative executes in pytest itself.

## Outstanding proof / precise HOLD

- Deterministic substitution is a direct writer unit, not the actual generated script paused at open in a supervised child. The original generated-body vulnerability has not been demonstrated by a safe old-body RED.
- Capture matrix still needs opened nonregular/multiply-linked substitution after admission, changed pathname after open, and generator registration refusals; current unsafe-target tests mostly exercise pre-open guards. Close-error semantics are not independently proved for this new writer.
- Execution refusal matrix exercises actual calls but has no controlled-bypass sensitivity receipts or matching-identity allowed registered subprocess positive. Exec/spawn always deny; Popen variants use the existing declared path with a deliberately mismatched identity.
- Parent positive wiring and broader installed mutation reconciliation remain deferred/HOLD. No overall READY bounded guard verdict is asserted.

## Context and scope honesty

Read 137 and PROCESS136 receipts; current safety123; root RESEARCH; routing/scope-plan; selected current bootstrap/entry/test chunks; engineering routing/testing/ownership, coding rules/cadence, Python root/declarative and shared declarative excerpts, canonical workflow counting section. AGENTS/CLAUDE/docs RESEARCH supplied in full context rather than freshly reread from disk. KB os/ROLE read first; Welcome, os README/workloads, Slo README/gotchas consulted in bounded excerpts. B default-suite safety and C lifetime mapping read-only. Dedicated Python process skill absent; existing supervisor contracts govern. Some required full skill/project reads remain incomplete; no full-context compliance claim. One malformed parallel read batch produced nine missing-path errors and read nothing.

No legacy probe, positive family, full make, provider, Herdr, window, global/live/spec/other-worktree/KB/shared-status changes. No commit/push/PR/reset/clean/stash. Existing dirty work preserved. Documentation limited to this receipt and a new current safety123 section, preserving history. Source changes are untracked already, so git diff alone does not show them; affected source and added tests were inspected through tool edits/read output. Final verdict: **INCOMPLETE / HOLD**, despite passing bounded implemented units.
