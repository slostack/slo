# Recovery 11 — containment correction verified; Step 1 incomplete

Branch and HEAD checked: `feature-gpt_6_support`, `ea8601c53f04fa06a0baeeb47d385c44cc9a5364`. Existing dirty work preserved. No reset, commit, install, agent spawn, specification output or shared KB change.

## Actual change and executions

`tests/tui/test_git_diff_content_service.py` now creates `git_repo` at `tmp_path/repository`. Its escape fixture writes `tmp_path/outside.txt`, asserts resolved containment before that write and symlink creation, and asserts the link resolves outside the repository but inside the test root. The existing service rejection assertion remains. The unsafe original was never run for red evidence.

Used existing `.f89-evidence/run-test.sh` and its existing venv, with env-i and synthetic tests.env. Read runner, tests.env, tests/state_isolation.py and tests/conftest.py before execution. No dependency installation or new environment.

Receipts, each with `.command`, `.log`, `.exit`, under `.f89-evidence/`:
- `recovery11-containment-focused`: 1 passed, 26 deselected, 4 warnings; exit 0.
- `recovery11-containment-module`: 27 passed, 2 warnings; exit 0.
- `recovery11-containment-surrounding`: show_git_diff tool tests, 6 passed, 2 warnings; exit 0.
- `recovery11-coreutils`: `dpkg -V coreutils`, empty output, exit 0.

Commands used timeout 1800. These are separate executions, not full-suite or cumulative acceptance evidence. No claim that shell settings change the parent runtime.

## Explicit incomplete work

Full non-E2E suite NOT RUN. Full fixture safety audit NOT complete: only a symlink search, the diff fixture, bash containment helper, and opening installer fixture source were inspected this turn. No new distinct unsafe operation has been established and no new authorization request is made.

The required complete fresh reading/discovery pass was NOT completed. The supplied headless instructions and formal workflow were fully read; the discovery receipt, recovery10 report and relevant containment module were read. Other required specs, handoffs, KB and conventions were not all freshly read; do not treat supplied context or historical receipts as that completion.

Actual released Feature89 compatibility/observer acceptance, finite AC1/4/7/8 and CLI parsing audit remain unfinished as recorded in recovery10. Fresh canonical Black/mypy, changed-files cleanliness and frozen-base attribution were not executed. Historical Black14 and mypy296errors/59files remain RED UNWAIVED, not fresh results. No functional-completion claim. No independent review or assessment performed. Verdict REVISE, not READY.
