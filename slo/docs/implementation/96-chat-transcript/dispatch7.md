# Dispatch 7 — INCOMPLETE

Turn 1 dispatch 7/20, max60 turns, no retries, nested agents, headless work,
commits or pushes. Production cutover and original contributions preserved.
This is NOT closure of the assigned bounded deliverable.

## Changes

`component.py` now uses the original HTML's typed native-request/token/operation
contract, rather than the obsolete y-only tuple callback: horizontal inputs retain
vertical destinations; requested axes determine completion; covering callbacks
handle no movement; programmatic starts notify the owner; hidden native calls are
refused; obsolete public deferred starts are revoked; follow pins coalesce with a
dirty-release latch. Native easing/animation remains Textual-owned. The prescribed
algorithm was adapted directly from the current HTML, not a new coordinator.

Initial hydration now seals admission before projection. A partial initial failure
still propagates, retains the mounted prefix, and cannot duplicate it on another
hydrate call. Clear/bind permits a fresh attempt. This matches the retained-partial
older policy but needs explicit independent review of the initial-failure policy.

Added mounted tests for this partial failure, hidden programmatic calls, two
supersession orders/final growth, x-first after public programmatic y movement,
real session subscriber backpressure across repeated cleanup-caller cancellation,
and a notice arriving during actual child unmount after clear's snapshot.
The existing standalone TranscriptScroll constructor test was migrated to the
new callback contract. No runtime compatibility aliases were added.

## Exact verification

Cwd `/root/Code/tui-refactor/slo`; all commands used:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript.py -k 'hidden_programmatic or partial_initial'
# dispatch7-red.log: 1 failed (duplicate prefix), 1 passed, 29 deselected
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript.py tests/tui/test_scroll_follow.py tests/tui/test_stream_snapshot_boundaries.py tests/tui/test_feature89_presentation.py
# dispatch7-final2.log: 99 passed, 23 warnings, 43.74s, exit 0
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_app.py tests/tui/test_replay_resume.py
# dispatch7-app-final.log: 171 passed, 27 warnings, 183.13s, exit 0
poetry run black --check src/tui/components/chat_transcript/component.py tests/tui/test_chat_transcript.py tests/tui/test_app.py
# 3 unchanged, exit 0
poetry run mypy src/ tests/
# dispatch7-static-final.log: 292 errors in 58 files, 758 checked, exit 1
 git diff --check
# exit 0
```

Static diagnostic multiset is identical to dispatch6 (line numbers normalized),
`dispatch7-static-comparison.txt` empty. Baseline remains unwaived, NOT green.
Full pytest deliberately not run.

Intermediate evidence is retained: navigation test first used an incorrect widget
method (two test setup failures); a wrong event field caused teardown to await an
unreleased reader and the 120s command timed out. Corrected fields and relay wrapper
pass. Initial strict viewport token on initial geometry activation stranded an
early echo's pin; final initial-layout activation validates generation and current
visibility, then uses current owner intent. `dispatch7-final.log` records those two
failures, superseded by final2. An initial app partition timed out at 120s; final
300s invocation completed. No test expectation was weakened to hide those failures.

## Exact remaining deliverable gaps

No environment blocker established. The current changes do NOT constitute all
required proof; do not mark READY based on counts:

- Native scheduling matrix is still incomplete: held deferred starts/completions,
  above/below growth at both timing boundaries, destination named-line/cell proof,
  track/drag/wheel variants, paired axes with differing finish times, completion
  delivery order/duplicates, no-movement stale-other-axis, and focus interruption.
- X-only test currently covers Right after public y move with tree-sibling upper
  growth only. Still need original real-history/focus/modified-wheel/track cases,
  numerical fallback after removal, pending bottom pin orderings, pending PageUp
  and End before/after start, programmatic animated-y interruption and both themes
  and viewport sizes required by original specification.
- Hidden/no-geometry evidence is only a simple hidden public/private call; ancestor
  hidden, hide during two-axis movement, stale show/clear completion sequences and
  geometry-not-ready remain unproved. Current show/layout activation uses generation
  rather than exact viewport revision to avoid losing initial readiness; review
  exact stale-show behavior before acceptance.
- Lifecycle subscriber proof covers delta/terminal, not the requested tool-result
  and active inference journey. Concurrent clear/bind/close ordering, mixed replay
  (user/thinking/tool/empty content), active tool preservation during partial older
  insertion, empty prepend, and complete named-row preservation remain unproved.
- Initial partial-hydration retry has a regression test and explicit safe retained
  policy; no new recovery notice was introduced. Independent review required.

Parent-owned gaps remain unchanged: factory/BOTH launcher journeys, exact full
replay-before-subscribe integration, documentation owner-map cleanup, final full
suite/manual smoke, independent review/completion. No final feature acceptance.

Rules were read from actual installed `$SLO_SKILLS_DIR` (engineering routing,
ownership/testing; coding rules/test loop/test verification; Python root,
named arguments/docstrings/declarative structure; Textual). Original HTML native
contracts and tasks, root RESEARCH and KB Slo index/gotchas were consulted.
