# Dispatch 8 — INCOMPLETE

Turn 1 dispatch 8/20, max60 turns, no retries. No nested agents, headless runs,
commits or pushes. Existing cutover/contributions preserved. Parent retains
independent final review/completion.

## Implemented

Added a failing mounted ancestor-hidden navigation test, then corrected the owner
admission boundary in `src/tui/components/chat_transcript/component.py`.
`_has_visible_geometry` now refuses native admission, native completion and reading
anchor capture when an ancestor is not displayed. Previously only the scroll
transport refused hidden execution: the owner still changed viewport revision and
acquired a navigation operation from PageUp under a hidden Screen.

## Exact evidence

Working directory `/root/Code/tui-refactor/slo`. Environment:
`VIRTUAL_ENV=/root/.pyenv/versions/slo-harness`, its bin prefixed to PATH,
`SLO_ENV=test SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0`.

- `PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript.py -k ancestor_hidden`:
  **1 failed, 36 deselected, 2 warnings in 0.73s**, `dispatch8-red.log`.
- `PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript.py tests/tui/test_scroll_follow.py tests/tui/test_stream_snapshot_boundaries.py`:
  **50 passed, 23 warnings in 36.79s, exit 0**, `dispatch8-focused.log/.exit`.
- `poetry run black --check src/tui/components/chat_transcript/component.py tests/tui/test_chat_transcript.py`:
  **2 unchanged, exit 0**.
- `git diff --check`: **exit 0**.

## Remaining actual gaps

This does not close the requested deliverable. Dispatch7.md's remaining matrix is
still outstanding except the new ancestor-hidden admission case. In particular:

- `component.py`: full native deferred start/completion growth timing, two-axis
  unequal completion/order/duplicate matrix, x-only history/focus/wheel/track and
  pending pin/PageUp/End cases; geometry-not-ready, hide-during-motion and stale
  show/reset settlement proof. Other geometry paths have not been audited by this
  bounded correction.
- `test_chat_transcript.py`: mixed/empty replay, partial older insertion with an
  active tool, concurrent lifecycle ordering and real active inference/tool-result
  subscriber journeys remain incomplete.
- `app.py` integration: injected SessionFactory, both injected visualizer routes,
  exact hydration-before-subscribe and modal-focus/usable-input evidence remain.
- AGENTS/docs owner-map reconciliation remains unfinished.
- Full default pytest was **not run** because core acceptance is still incomplete;
  resource checks and static gate were not rerun in this dispatch. Prior exact
  **292 errors / 58 files** mypy baseline remains **unwaived**, not green. No
  unrelated static fixes attempted. No manual smoke or independent approval.

No environment blocker was established. This is unfinished work, not READY or an
external-gate-only disposition. The full suite must still run after core completion
with the recorded complete safe environment and no added exclusions.
