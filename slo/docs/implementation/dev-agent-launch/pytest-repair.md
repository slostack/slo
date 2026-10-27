# Launch-isolation pytest repair

## Scope

Test-only repair of the sub-agent, workflow and resume variants of
`test_agent_isolation_does_not_isolate_project_commands`. Production behavior is
unchanged. The source-only test interpreter did not satisfy the installed-mode
precondition: `-I` correctly ignored cwd/PYTHONPATH, leaving `src` unavailable.

A module-local fixture builds the current checkout wheel and installs it offline
with no dependencies into a disposable virtualenv. It uses existing installed
dependencies, never changes the parent interpreter or pipx, and removes its
source/wheel/venv via TemporaryDirectory. Each probe first asserts the production
prefix equals `[sys.executable, '-I']`, then explicitly substitutes the installed
fixture interpreter. The original assertions, including the user's non-null
origin requirement, remain; an additional assertion requires origin inside the
fixture venv. This is finite import/isolation proof, not live CLI/provider proof.

## Verification

Interpreter: `/root/.pyenv/versions/slo-harness/bin/python`.

- Before repair: `python -m pytest -q tests/agents/slo_agent/orchestrator/test_launch_isolation.py`: 3 failed, 1 passed.
- After repair: same focused command: 4 passed.
- `python -m pytest -q tests/agents/slo_agent/orchestrator`: 1121 passed, 1 deselected, 57 warnings.
- Full: `python -B -m pytest -p no:cacheprovider --basetemp=/tmp/slo-pytest-repair/pytest-full -q`: 8520 passed, 20 deselected, 482 warnings, 1051.17 seconds, exit 0. No extra marker/path exclusions; project default non-E2E selection applies.
- Full command used clean `env -i`, explicit interpreter PATH/VIRTUAL_ENV, temporary HOME/TMPDIR, checkout PYTHONPATH/root/app, SLO_ENV=test, synthetic provider placeholder, gpt-5.4 default, auto-visualizer off, COLUMNS=120/LINES=40. No real provider credentials were forwarded.
- Scoped Black and diff whitespace check passed.

Read-only independent review session `db7ac333-f853-4c17-8376-0a1ae0210d36`: READY, no blockers.
Read-only completion session `848c98f9-3828-43bb-a774-24b819298f1d`: READY for this scoped repair.
Neither reran tests; both inspected the executable receipts before cleanup.

No services or standalone scripts were launched for this repair. Temporary test
resources/logs under `/tmp/slo-pytest-repair` are removed after evidence inspection;
this summary is retained intentionally. Unrelated pytest processes and temporary
roots are not touched. Prior default pytest temp roots were rotated by pytest;
no retained `installed-launch-isolation` fixture directory remained at cleanup.

The broader 292-error mypy baseline is not repaired or waived. This report accepts
only the pytest repair, not broader pending feature review. Local commit authorized
by the user; unrelated ChatTranscript work remains uncommitted.
