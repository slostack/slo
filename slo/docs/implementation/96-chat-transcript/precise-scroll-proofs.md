# Dispatch 13 — two precise scroll proofs

**READY for these two assigned AC05 proof requirements only.** Feature/workflow
acceptance remains blocked; independent review and completion belong to the parent.
Turn 1, dispatch 13/20, maximum 60 turns, zero retries/nested dispatches.

## Scope and sources

Read current handoff and dispatch12; normative
`/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/tui-refactor-side-quest/96.e.1-chat-transcript.html#navigation-tests`
and Task02/03. Reused the installed skill tier at
`/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`:
engineering routing/ownership/testing; coding-rules, code-test-loop,
test-verification-policy, declarative-method-structure; Python conventions,
named arguments/types, docstrings and declarative structure; build-textual-tuis.
Read root research and KB Welcome, slo README/gotchas. This is a mounted
presentation proof, not a persistence/provider/CLI change.

Only new test file `tests/tui/test_chat_transcript_precise_scroll.py` and this
dispatch's evidence/current handoff were changed. No production repair was needed.
Existing dirty production/test contributions were not edited or reverted.
No new testing framework, animation driver, fake clock, native-callback replacement,
manual terminal harness, live provider, sub-agent, commit or push was used.

## Requirement → exact evidence

### 1. Unequal completion; covering/native completion in either order

`test_unequal_axes_retire_with_cover_before_or_after_native[True/False]`:

- Mounted real component, real wide literal rows, actual Pilot PageUp then Right.
  Existing `OrderedTranscript` holds only owner after-refresh starts/covering
  completions. Both starts are released through Textual; obsolete start rejects
  itself. No private completion helper is invoked by a test.
- Right merges pending vertical destination. Its duration is None: pinned
  Textual `Widget._scroll_to` selects speed 50; animator duration is distance/speed.
  One-cell x and a page-sized y genuinely finish at different times, unlike the
  fixed 0.1-second paired ScrollTo route.
- A bounded wait requires **x exactly at destination while y is strictly between
  origin and destination**, AND the real native callback has removed x from
  `pending_axes`, leaving exactly `{y}`. The covering callback is still held.
  This proves actual unequal completion and callback progress, not merely
  different requested distances or a simulated owner callback.
- Early-cover case releases duplicate covering callbacks and waits for refresh;
  asserts the same operation still exists and y is still moving. Native y then
  finishes. Late-cover case waits for real animation and settlement and requires
  no operation **before** releasing duplicate covering callbacks.
- Both require no pending operation without rescue output, the named requested
  row at its recorded cell, retained x, and that same row after later growth.

“Both orders” here is precisely the normative covering-before-native-final vs
native-final-before-covering order. x finishes before y in both runs; this does
not claim a separate y-before-x permutation (not requested by the cited exact
covering-completion clause).

### 2. Every composed frame during public animated-y interruption

`test_every_compositor_frame_excludes_interrupted_public_y_endpoint`:

- Public scroll_to first paints y=100 to establish a real old-destination row
  oracle; returns to y=30; starts public animated y=100, duration 2 seconds.
- Test-local `PaintObservedApp` adds only `post_display_hook`, an existing Textual
  testing hook. Observation begins **before** animated start and remains armed
  through Right, animation drain, settlement and later growth.
- Bounded wait requires actual intermediate y>=35 and two distinct observed
  compositor frames. There is no native owner operation at interruption.
  Captures the actual reading row/cell, sends actual Pilot Right, and requires
  that row retained after interruption and growth.
- Requires at least three frame observations and distinct frame contents;
  **every captured frame** excludes the calibrated old-endpoint label. Also
  requires x changed to 1 and no pending owner operation. The all-frame assertion
  is independent of final-coordinate/settled-row assertions.

### Why the hook is a frame boundary, not periodic sampling

Inspected the actual environment's Textual **8.2.8** sources:
`screen.py:1188–1235` (`Screen._compositor_refresh`) computes `render_update`
then calls `app._display(self, update)`; `app.py:3821–3894` calls
`post_display_hook()` synchronously in `_display`'s finally block. The hook reads
`screen._compositor.render_strips()` synchronously without an await or refresh.
No other event/animation step can interleave between display and capture on this
loop. This observes the composed screen at **every display attempt**, including
any no-op attempts, rather than selecting frames with `pilot.pause` or a polling
interval. Polling is used only to choose when to send the interrupt, not to
collect frames. Existing `painted_rows` provides the compositor strip oracle.

Headless `run_test` does not write ANSI to a physical terminal. These are all
Textual compositor display frames for this mounted scenario, **not** terminal
emulator/physical display observations or manual smoke. No claim about every
possible runtime timing is made. No screenshot/export call drives the animation.

## Test-first chronology and exact commands

Cwd `/root/Code/tui-refactor/slo`. All pytest runs used:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40
unset SLO_OPENAI_API_KEY SLO_KIMI_FOR_CODING_API_KEY SLO_OPENROUTER_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript_precise_scroll.py
```

Verified Python path `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7.
Existing root/TUI fixtures isolate state and prevent real terminal spawning.

1. First new-test run: **1 failed, 2 passed, 2 warnings**, exit 1,
   `precise-first.log`. Failure was an overly early test observation: x had
   reached its coordinate but its queued native completion had not yet removed
   x from pending_axes. Not a production defect. Corrected the bounded wait to
   require that callback's observable retirement while y is still intermediate.
   Also strengthened public-y setup to require distinct frames and actual motion,
   then asserted pre-interruption reading-row retention.
2. Second run: **3 passed, 2 warnings in 2.43s**, exit 0,
   `precise-second.log`. No claimed production RED/GREEN repair.
3. Strengthened early/late ordering assertions (same operation still moving after
   early cover; already retired before late cover). Final bounded gate:
   `bash docs/implementation/96-chat-transcript/precise-command.sh`:
   **158 passed, 23 warnings in 148.72s**, exit 0.
   Full command/environment in that script; `precise-regression.log` and `.exit`.
   Paths: precise_scroll, closure, navigation, scroll_follow, chat_transcript.
4. Three further executions of the exact new-file pytest command above:
   **3 passed, 2 warnings** each (2.41s, 2.44s, 2.39s), exits 0;
   `precise-repeat-{1,2,3}.log`. These are repeat stability observations, not a
   statistical guarantee or workflow retries.
5. `poetry run black --check tests/tui/test_chat_transcript_precise_scroll.py`:
   exit 0, one unchanged file. `git diff --check`: exit 0. Read final test for
   scope/oracle correctness; no independent-review claim.

## Unchanged limitations / parent gates

No full-suite rerun, mypy cleanup/check, manual smoke or baseline waiver was
requested or performed. Earlier full pytest **8502 passed / 19 deselected** and
**292 baseline mypy errors, unwaived** remain the dispatch12 historical receipts,
not fresh results. Manual synthetic terminal evidence remains unavailable under
the prohibited-harness constraint. The parent must still perform mandatory
independent review and completion assessment; bounded READY is not approval of
Feature 96 or permission to merge. If physical terminal paints rather than
Textual composed frames are required, that stronger interpretation remains
BLOCKED and needs explicit parent/user disposition, not inferred coverage.
