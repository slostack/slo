# T1 bounded environment isolation — READY for this unit only

2026-10-17. Implemented and tested environment isolation plus tracked defaults only.
Other T1 foundations and T2–T6 remain pending. No activation, real Herdr execution,
live provider call, agent dispatch, commit, push, global/other-worktree or source-spec
change was performed. `routing.md` and `scope-plan.md` remain unchanged.

## Contract and file mapping

Authority: canonical Herdr `tasks.md` common execution rules and T1; reporting
chapter `94.b.1-herdr-reporting-adapter.md`, default-suite isolation prerequisite
(F2), items 1–2. Full-family prerequisite ingestion remains recorded in scope-plan.

- `tests/state_isolation.py`: selects inherited names case-insensitively for
  `HERDR_*` and `SLO_HERDR_METADATA_PROFILE`, removes them without retaining values,
  and forces `SLO_HERDR_DISABLED=1` before configuration imports.
- `tests/conftest.py`: repeats the same policy with monkeypatch before any
  application-module rebinding. Existing real-terminal blocker unchanged.
- `Makefile`: test and smoke fallback exports include disablement; unconditional
  post-selection export also defeats a local tests.env setting of zero.
- `environments/.env.template`: specified runtime defaults `0`/`compact`, with
  explicit local tests.env disablement instructions. No untracked env file edited.
- `tests/agents/slo_agent/herdr/test_test_isolation.py`: eight cases, covering fresh
  interpreter pre-config import, hostile reinjection before per-test rebinding,
  monkeypatch restoration, unrelated-variable preservation, ordinary autouse and
  terminal-blocker defaults, both Make targets with/without local tests.env, and
  tracked template defaults. Make recipes run with a NEW regular temp-owned poetry
  stub; all fixture writes check containment first. No system executable symlinks.

Implementation after RED: 37 added lines across the four existing files (including
comments/imports), below the 50-line increment cap. Shared name-selection policy
stays with existing test state isolation; no production subsystem introduced.
The optional fake Herdr registration/identity helper and real transport guard are
not implemented here. Environment flags are not activation permission. T2 must
land its independent spawn guard before activation tests.

## Environment and commands

CWD: `/root/Code/slo-94-herdr-integration/slo`.
`pyenv which python`: `/root/.pyenv/versions/slo-harness/bin/python`;
`python --version`: Python 3.11.7; `make test-env`: fallback. All exit 0.
Focused and regression commands used this routing-approved subprocess environment:

```bash
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1
PYTHONPATH="$PWD" poetry run pytest -q tests/agents/slo_agent/herdr/test_test_isolation.py
PYTHONPATH="$PWD" poetry run pytest -q tests/test_slo_home_isolation.py tests/tui/test_visualizer_launcher.py tests/test_smoke.py
poetry run black --check tests/state_isolation.py tests/conftest.py tests/agents/slo_agent/herdr/test_test_isolation.py
make test
dpkg -V coreutils
git diff --check
```

## Actual receipts

Logs and matching `.exit` files are beside this report.

| Receipt | Exit | Actual result |
|---|---:|---|
| `t1-red.log` | 1 | 7 failed, 1 passed, 2 warnings; written and run before implementation |
| `t1-green.log` | 0 | 8 passed, 2 warnings |
| `t1-regression.log` | 0 | 310 passed, 2 warnings |
| `t1-black.log` | 1 | New test file needed formatting; two files unchanged |
| `t1-black-final.log` | 0 | All three changed Python files unchanged |
| `t1-full.log` | 0 | 6280 passed, 19 deselected, 406 warnings, 472.95 seconds |
| `t1-coreutils.log` | 0 | Empty output after stubbing and again after full suite |

RED failures were inherited-context retention (both bootstrap probes), four Make
recipe probes exiting 42, and missing template defaults. The ordinary test already
passed under the explicitly disabled command environment; it was not the RED proof.
Black formatted only the new test file before the full suite. The full suite thus
covers the final formatted code. `git diff --check` exited 0; final tracked diff and
new test were reviewed for scope, preserved terminal guard, containment and order.
No failures were skipped or assertions weakened. Static baseline lint debt remains;
full mypy was not rerun or repaired in this bounded unit. No all-static-green claim.

## Workflow accounting and remaining gates

Turn 1 active; started 1, completed 0, historical partial 0. Dispatch 5;
consumed 5, remaining 15 of 20; unlimited turns; retries 0. No sub-agents spawned.
READY applies only to this implemented/tested unit, not all T1, Feature 94,
independent review, completion assessment or live compatibility acceptance.
