# T6 unified journey / lifetime matrix 136 — INCOMPLETE

## Scope and retained accounting

User accounting retained: unfinished turn 1, started 1, completed 0, historical
partial 1, dispatch 136, retries 0; unlimited turn/dispatch budgets. No agents
were dispatched here. No source, harness, shared status, specification, global,
other-worktree or live-state edits. Existing partial work is preserved.

This increment only adds `tests/integration/test_herdr_lifetime_matrix.py`.
`test_herdr_full_flow.py` was read but not modified. The requested unified single
mounted journey is therefore **not implemented by this increment**.

## Implemented bounded family

C section 8 (94.b.2, lines 2103–2119) supplies the axes, not invented categories:

- trigger: runtime_disable / session_close / new / unmount
- phase currently implemented: queued_viewer
- diagnostic: healthy / raising

Eight cases run an actual mounted config-backed session, native save/report
activation, actual registered viewer, shared CLI lock and registered fake CLI.
They check shared reporter/viewer transport identity, real inbox/lease setup,
queued work, no split after revocation, cleared task registry and replacement
identity. Runtime disable is caused by a real reservation failure path, not an
environment toggle or assigned disabled flag. Close/new/unmount use their
production gateways. No gateway or transport response is mocked.

Limits: the raising sink is installed but this family does not prove it was
called. Runtime-disable sequence diagnostics are not independently instrumented.
Inbox creation is checked, not a competing delivery cutoff. This is bounded
queued-viewer evidence, **not complete all-owner matrix acceptance**.

## Actual verification

Interpreter: `/root/.pyenv/versions/slo-harness/bin/python`.
Explicit tracked-fallback environment: SLO_ENV=test, root/app dirs=$PWD,
SLO_APP_NAME=slo, SLO_LOG_FORMAT=text, default model gpt-5.4,
SLO_AUTO_VISUALIZE=0, SLO_HERDR_DISABLED=1, synthetic Anthropic key,
COLUMNS=120, LINES=40, PYTHONPATH=$PWD. Root fixtures control Herdr and windows;
only registered temporary executables run.

Receipts: `t6-unified-matrix-136-receipts/` next to this file.

1. `python -m pytest -m 'not e2e' tests/integration/test_herdr_lifetime_matrix.py -vv`
   initially: **6 failed, 2 passed**, exit 1 (`queued-viewer.log`). The test
   incorrectly awaited legitimately cancelled viewer tasks as successful tasks.
   Corrected the test to accept cancellation while retaining forbidden-effect
   assertions; no production defect was established.
2. Same command after correction: **8 passed**, exit 0
   (`queued-viewer-corrected.log`). Each case ID is recorded in verbose output.
3. After Black, explicit safe surrounds:
   `python -m pytest -m 'not e2e' tests/integration/test_herdr_lifetime_matrix.py tests/tui/test_herdr_platform_commit.py -vv`
   **14 passed**, exit 0 (`safe-surround.log`).
4. `python -m black --check tests/integration/test_herdr_lifetime_matrix.py`:
   exit 0, one file unchanged.
5. `python -m mypy --follow-imports=silent tests/integration/test_herdr_lifetime_matrix.py`:
   exit 0, one file clean (`mypy.log`). This is scoped, not global mypy.
6. `git diff --check -- tests/integration/test_herdr_lifetime_matrix.py`: exit 0;
   this new file is untracked so this does not constitute a tracked-diff review.
7. `dpkg -V coreutils`: exit 0, no output, before and after test execution.

## Remaining obligations

- Unified PromptInput/Faux tool + retry + pool fallback, usage/rename/model/new,
  attached AND detached viewer paths in one mounted lifetime is outstanding.
- Remaining 56 matrix cases: queued/admitted report, admitted viewer,
  precommit/committed platform, queued capture and running save × four triggers
  × two diagnostic modes. They are not collected, skipped or claimed passing.
- G1/G2 existing matrices were not changed, but the requested explicit mapping
  and fresh verification remain outstanding.
- Full 64-case all-owner/retention assertions and receipts remain outstanding.
- Full suite and two-process harness were neither collected nor run (HOLD).
- Global static baseline remains unwaived; no fresh global count is claimed.
- Independent review and live Herdr acceptance remain unproven.

Verdict: **INCOMPLETE**, not READY and not feature approval.
