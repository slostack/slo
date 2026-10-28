# Dispatch 9 — READY for the assigned four integration gaps only

Turn 1, dispatch 9/20, max60; no retries or nested dispatches. No headless runs,
commits, pushes, new framework/harness, navigation expansion or full suite.
Production files and all prior work are unchanged in this dispatch.

## Evidence mapping

Added ordinary pytest module `tests/tui/test_chat_transcript_app_integration.py`:

- `test_injected_factory_new_session_persists_only_to_replacement`: the same
  injected factory builds initial and replacement real Faux-backed sessions.
  Pilot submits `/new replacement`, checks exact unsubscribe/build/startup/subscribe
  ordering and config forwarding, same component identity, old content removal,
  retired-session delivery exclusion, then submits a real prompt and reads exactly
  one user/answer from the replacement's real temporary filesystem store. Initial
  session has no user-message write; teardown unsubscribes the replacement.
- `test_replay_is_mounted_before_startup_and_live_subscription`: seeds real history,
  resumes it, observes real hydration start/return, startup and subscription in exact
  order. Both startup and subscribe observers assert complete replay widgets are
  already mounted (reader-return alone is insufficient). Hydration leaves events
  byte-identical; a subsequent Pilot prompt appends once after replay.
- `test_both_visualizer_routes_use_injected_launcher[False/True]`: actual session
  event relay → app → attached child route / detached launch-tool route. One shared
  injected recorder receives the correct two distinct parent identities; duplicate
  events do not relaunch. Exact success/fallback strings and `sub-agent-notice`
  classes remain intact, with no foreground child answer. No OS launch occurs.
- `test_hide_show_retains_progress_modal_focus_and_usable_prompt`: hiding focused
  transcript content returns base-screen focus to the editor; show does not steal
  it. With a real SessionProgressScreen active, hide, hidden live delivery and show
  retain modal focus/stack and widget identity without rereading history. Dismissal
  restores prompt focus and Pilot typing works without an explicit refocus.
  This is focus/integration evidence, not the remaining geometry/navigation matrix
  or a new proof of coordinator-owned minimize behavior.

Only the provider is Faux; real session invoke/subscription, app routing, component,
projector and filesystem persistence run. ObservedSession overrides public methods
only to record/observe boundaries, delegating behavior to production. Local factory
and launcher recorders use existing constructor seams. Existing pytest isolation
and TUI auth/terminal guards remain in force.

## Test-first results and correction

Tests were written before any production edit. Initial five cases passed as added:
**5 passed, 5 warnings in 2.81s**, `dispatch9-first.log`. No invented production RED
or behavior-fix claim. Strengthening base-screen focus assertions exposed a test
scheduling error: **1 failed, 4 passed** in `dispatch9-focused.log`. `Widget.focus()`
schedules focus; the assertion ran before Textual settled. Adding the ordinary
`await pilot.pause()` before observing focus corrected the test, without relaxing
the focus outcome or changing production. Affected run then passed **75 tests** in
24.30s. Final strengthening also observes mounted replay at startup, not just at
subscribe; final post-edit evidence follows.

## Exact commands / final results

Cwd `/root/Code/tui-refactor/slo`:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0
# which python => /root/.pyenv/versions/slo-harness/bin/python
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript_app_integration.py tests/tui/test_replay_resume.py tests/tui/test_workflow_receive_path.py tests/tui/test_subagent_event_routing.py
# 75 passed, 7 warnings in 24.47s; exit 0
# dispatch9-final.log / dispatch9-final.exit
poetry run black --check tests/tui/test_chat_transcript_app_integration.py
# 1 file unchanged; exit 0
PYTHONPATH="$PWD" poetry run mypy --follow-imports=silent tests/tui/test_chat_transcript_app_integration.py
# Success: no issues found in 1 source file; exit 0
 git diff --check
# exit 0
```

The scoped mypy check does NOT supersede the unwaived repository baseline.
Self-review verified test boundaries, exact oracles, safe side-effect injection and
that no existing production changes were overwritten. Independent review/completion
remain parent-owned. No manual smoke or full-suite acceptance claim.

## Remaining feature gaps (unchanged except the four above)

Dispatch7/8 navigation/deferred completion and two-axis timing matrix; geometry-not-ready,
hide-during-motion and stale show/reset settlement; mixed/empty replay, partial older
insertion with active tool, concurrent lifecycle ordering and real active inference/
tool-result subscriber journeys; AGENTS/docs owner-map reconciliation; full non-E2E,
resource/static final gates, unwaived 292-error/58-file mypy baseline, manual smoke and
independent review/completion remain pending. This dispatch's simple real prompt
journeys do not claim to close those broader concurrency/tool obligations.

Changed authored files: this report, `handoff.md`, and the new pytest module only.
Adjacent ignored logs/exit receipts are execution artifacts, not additional source
changes. No durable new architectural decision or production bug was discovered.
