# Dispatch 6 — NOT READY

Turn 1 dispatch 6/20; max60 turns, no retries, nested agents, headless runs,
commits or pushes. Production cutover and original dirty contributions retained.
Parent owns independent review/completion. This is not feature-core acceptance.

## Changes and evidence

- Both abort/failure warning paths now capture exactly once BEFORE warning layout
  or pending-answer rendering. Warning-only terminal updates also publish the exact
  snapshot/source. Thinking expansion now captures before visibility mutation and
  publishes the same boundary message. New mounted tests in
  `tests/tui/test_stream_snapshot_boundaries.py` exercise warning-only/dirty-answer,
  both terminal warnings, expansion, and timer/terminal flush for both widgets.
  RED: 5 failed, 4 passed. GREEN surrounding partition: 52 passed.
- Migrated optional `app._chat_transcript` test observations to
  `app.query_one(ChatTranscript)` rather than production aliases or type ignores.
  Corrected obsolete absent-scroll test to exercise the actual uncomposed-app
  contract, not corrupt the retained component scroll. Narrowed three remaining
  task/summary observations with assertions.
- Broad affected run found four genuine introduced startup-paint regressions at
  60x20 in Feature89. Exact archived HEAD baseline passes all 50 presentation tests.
  Startup changes available transcript height after the first follow pin. Component
  Resize now schedules retained-follow restoration after layout. Existing painted
  assertions unchanged: 83-test presentation/component/scroll partition passes.
  An attempted extra release-pin scroll did NOT fix them and was reverted.
- Formatted changed Python paths; final affected suite passes 1965 tests, including
  TUI, five integration modules and archive/resource tests. No core binary changes
  reported by `dpkg -V coreutils` after these checks.

## Exact command environment

All current-tree commands cwd `/root/Code/tui-refactor/slo`:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0
# which python: /root/.pyenv/versions/slo-harness/bin/python
```

Final affected command additionally used the complete Makefile fallback:

```bash
export SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
unset SLO_OPENAI_API_KEY SLO_KIMI_FOR_CODING_API_KEY SLO_OPENROUTER_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY
PYTHONPATH="$PWD" poetry run pytest -q tests/tui \
 tests/integration/test_feature89_model_flows.py \
 tests/integration/test_openrouter_full_flow.py \
 tests/integration/test_openrouter_scheduled_preparation.py \
 tests/integration/test_workflow_progress_tui.py \
 tests/integration/test_workflow_child_abort_tui.py \
 tests/cli/test_chat_transcript_resources.py
```

**1965 passed, 1 deselected, 186 warnings in 550.71s, exit 0.** Normal configured
marker only; no added exclusions. `dispatch6-affected-final.log/.exit`.

Other exact commands (same basic environment above):

```bash
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_stream_snapshot_boundaries.py
# dispatch6-snapshot-red.log: 5 failed, 4 passed, 2 warnings, 1.98s
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_stream_snapshot_boundaries.py tests/tui/test_assistant_stream_block.py tests/tui/test_assistant_stream_thinking_block.py tests/tui/test_chat_transcript.py
# dispatch6-snapshot-green.log/.exit: 52 passed, 23 warnings, 30.87s, exit 0
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_feature89_presentation.py tests/tui/test_chat_transcript.py tests/tui/test_scroll_follow.py
# dispatch6-resize.log/.exit: 83 passed, 23 warnings, 37.61s, exit 0
poetry run mypy src/ tests/
# dispatch6-static-final.log/.exit: 292 errors in 58 files, 758 checked, exit 1
poetry run black --check <paths in dispatch6-format-paths.txt>
# dispatch6-black.log/.exit: 45 unchanged, exit 0
 git diff --check
# exit 0
 dpkg -V coreutils
# exit 0, empty output
```

Initial affected receipt `dispatch6-affected.log`: 4 failed, 1959 passed,
1 deselected, 186 warnings in 562.95s. Failed experimental pin receipt
`dispatch6-pin.log`: 4 failed, 79 passed. No claim either was green.

## Static baseline (not waived)

Archived HEAD without touching this checkout:

```bash
baseline=$(mktemp -d /tmp/f96-static-baseline-XXXXXX)
git -C .. archive HEAD slo | tar -x -C "$baseline"
(cd "$baseline/slo" && "$VIRTUAL_ENV/bin/mypy" --cache-dir "$baseline/cache" src/ tests/)
```

Baseline path recorded in `dispatch6-baseline-path.txt`; log/exit in
`dispatch6-static-baseline.log/.exit`: **292 errors in 58 files, 747 checked,
exit 1**. Current has exactly the same diagnostic multiset after removing line
numbers and normalizing the intentional projector rename. **Zero added or removed
diagnostics** (`dispatch6-static-comparison.txt`). This removes the introduced
Optional migration errors from dispatch5; full mypy remains a blocked, unwaived
gate, not passing. An initial archive invocation from the subdirectory failed
path resolution before extraction; corrected by `git -C .. archive` above.

The archived baseline presentation command was
`PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_feature89_presentation.py`
from the extracted application root, same basic test environment: **50 passed,
2 warnings, 7.46s**, `dispatch6-paint-baseline.log/.exit`.

## Acceptance delta / remaining blockers

| Acceptance | New evidence / remaining work |
|---|---|
| AC05, T02 capture | Nine mounted snapshot tests pass; warning and expansion defects closed. Native destination/input/growth/supersession/two-axis/x-only/hide/clear matrix still incomplete. Current x-only handling may stop y; cancellation still stops both axes without retaining x ownership. Hidden native admission guard still needs correction/proof. |
| AC07 | Startup-resize follow regression closed by actual 60x20 painted tests. Hidden/no-geometry, not-ready geometry and complete modal-focus journeys remain incomplete. |
| AC06 | No new lifecycle closure here. Real subscriber backpressure/repeated cancellation/post-snapshot notice/mixed or empty prepend/partial active-tool tests remain required. Initial partial hydration retry can duplicate prefix and needs a defined safe failure treatment. |
| AC01/09/10/11/13 | Production/integration tests rerun successfully; injected SessionFactory and BOTH launcher route journeys and exact replay-before-subscribe proof remain incomplete. Do not infer these from the broad count. |
| AC12 | Archive tests rerun successfully in final affected gate. |
| Static | Introduced diagnostics eliminated; exact 292-error HEAD baseline reproduced. Baseline is unwaived, not green. Changed Python formatting and diff checks pass. |

Full default pytest intentionally NOT run: core acceptance remains unfinished;
user explicitly reserves this for completion. No manual interactive smoke or
independent approval. Documentation owner-map cleanup and remaining exact original
spec reconciliation are still needed. No genuine environment blocker was found.
Next continuation must finish these finite behavior/evidence gaps, not declare
READY from the affected gate or use baseline static errors as permission to waive.
