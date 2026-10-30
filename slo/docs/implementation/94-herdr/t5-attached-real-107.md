# T5 attached real composition 107 — INCOMPLETE (static/read closure)

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 107, retries 0. Unlimited user turn/dispatch budgets; no agents launched. No production edit, commit, push, PR, reset, clean, stash, global/live/specification/other-worktree edit in this continuation.

## Actual new evidence

`tests/tui/test_herdr_attached_composed.py` mounts actual SloTUI with a config-backed session and the existing pre-construction Faux factory. Ordinary app bootstrap records successful standard provenance; no provenance fields are forged. Default history is redirected to the test-owned SLO_HOME (not a custom history root). Canonical parent metadata is persisted by rename_session and valid context is written for that same actual parent/workdir. The registered regular fake CLI supplies the strict split response. Real activation creates the reporter and shared transport; test asserts capture exists, agent is not injected and viewer shares reporter transport.

An actual `sub_agent_spawned` DAO with synthetic child ID passes through `_render_event`. The app registers its worker, production launch_async selects the session gateway, and T4 sends through the actual guarded CLI subprocess boundary. No gateway/launch_async/transport mocks. Only the forbidden platform leaf is patched to raise. No actual agent child process or viewer process is launched.

Exact wire assertion: one `pane split --pane synthetic-pane --direction right --no-focus`, then rename to `Slo workflow <actual-parent-prefix>`, then `pane run viewer 'slo visualize --session <actual-parent> --follow'`. No focus/get/close. Actual adapter receives exactly one submitted notice, not opened/paint evidence. Task is awaited and registry drains. Enabled case also verifies final reporter resource drain after unmount.

Initial run failed the test's own containment assertion: suite default home was a separate per-test directory, not tmp_path. Corrected SLO_HOME and cached default-home fixture setup before session construction. This is **fixture RED, not production RED**. Existing production behavior then passed; no fabricated runtime defect or production patch.

## Finite attached branch map

| Branch | Evidence |
| --- | --- |
| Enabled, eligible actual parent | New composed enabled case, exact wire and submitted notice |
| Repeat while registered | New case sends second render event before awaiting task; exact task identity, one wire sequence |
| Repeat after completion | New enabled case sends third event; no new registered task |
| Auto-off | New mounted case: no worker, no split/rename/run, no submitted notice |
| Unavailable/revoked authority | New mounted case revokes reporter authority; unavailable selector, no split/rename/run, forbidden OS fallback |
| Invalid/missing/corrupt/ordinary/wrong-workdir/default-changed history; standard/custom provenance | Existing real gateway `test_session_visualizer.py`, freshly included in surrounds |
| Five typed outcome notices and closing/replacement/quiescing/errors | Existing `test_herdr_attached.py`, freshly included; these are mocked-outcome tests, not wire proofs |
| Registry join/replacement/public shutdown | Existing viewer registry/replacement and app shutdown/replacement modules, freshly included |
| Original platform first/repeat/parent/outcome/reset | Migrated subagent routing plus launcher modules, freshly included |
| Detached migration/shared renderer | **Not done**; formatter remains interim, not full D acceptance |

## Commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. All logs/exits are adjacent `t5-107-<name>.log/.exit`. Focused runner includes 62 DAO/projection tests. Approved `PYENV_VERSION=slo-harness`; no environment creation.

- `initial`: `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/test_herdr_attached_composed.py`: 1 fixture assertion failed, 62 passed; exit 1.
- `composed`: same command after correcting default temporary home: 63 passed, 2 warnings; exit 0.
- `surrounds`: same runner with `tests/tui/test_herdr_attached_composed.py tests/tui/test_herdr_attached.py tests/tui/test_visualizer_launcher.py tests/tui/test_subagent_event_routing.py tests/tui/workflows tests/tui/test_workflow_receive_path.py tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_replacement.py tests/tui/test_herdr_viewer_registry.py tests/tui/test_herdr_viewer_replacement.py tests/agents/slo_agent/herdr/test_session_visualizer.py`: 264 passed, 2 warnings; exit 0.
- `full`: `PYENV_VERSION=slo-harness make test`: **8148 passed, 19 deselected, 600 warnings in 723.85s**, exit 0.
- `smoke`: `PYENV_VERSION=slo-harness make smoke`: **288 passed, 2 warnings**, exit 0.
- `lint`: `PYENV_VERSION=slo-harness make lint`: **295 errors in 60 files (788 checked)**, make exit 2. No diagnostic names the new test. Errors are unwaived; complete baseline comparison not established here.
- `black`: initial file-list command used repository-root-prefixed diff paths from application cwd; rejected nonexistent `slo/src/...`, exit 123. Corrected command: `{ git diff --name-only --relative; git ls-files --others --exclude-standard; } | grep '\\.py$' | sort -u | xargs env PYENV_VERSION=slo-harness poetry run black --check` (shell grep expression executed as `\\.py$` with one backslash): `black-corrected`, 134 files unchanged, exit 0.
- `diff`: `git diff --check`, silent exit 0.
- `coreutils`: `dpkg -V coreutils`, zero-byte output, exit 0.

Black formatted only the new test before surrounds/full. A final shell display command used invalid tail syntax; test/static exit files had already been written. Subsequent reads retrieved their actual results; no failed gate was hidden.

## Remaining closure and verdict

Read 106 receipt, real gateway and mounted activation fixtures, bootstrap, app registry/formatter, isolation fixture, routing/scope plan and D 7.4/7.5. Supplied project instruction/research context applies. One oversized combined prerequisite read was truncated; complete prerequisite/read closure (including C and exact task samples/accepted reviews) is **not claimed**. No durable architectural change requiring research/KB mutation was made.

The missing real attached composition is now present and green, including full non-E2E execution. **Overall requested READY-family verdict remains INCOMPLETE** because required complete read closure and static-baseline reconciliation remain outstanding, with lint red and unwaived. This is not live Herdr compatibility, viewer paint, independent review, detached migration, or full D/T5 completion.
