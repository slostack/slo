# Dispatch 11 — bounded closure and exact residuals

Turn1 dispatch11/20, max60, retries0. No nested/headless work, commits, push or full
suite. Existing dispatch10 matrix retained, not duplicated. **Not full acceptance.**

## Added evidence

`tests/tui/test_chat_transcript_remaining.py` adds 17 cases using the existing
TranscriptTestApp, OrderedTranscript and compositor helpers. No new harness or
framework. `test_chat_transcript_lifecycle_matrix.py` extends the existing real
Faux/graph/store journey with one blocked-clear case.

| Requirement | Evidence / precise boundary |
|---|---|
| Genuine intermediate animation, public-y interruption, no-movement with preexisting x animation | `test_public_animation_interrupted_while_actually_moving[right,hide,home]`: public 1s native animation, bounded wait requiring intermediate x/y, pre-stop painted named row, final same row, no pending navigation. Home is issued at y=0 with x already moving. No replacement animator. Not an every-frame oracle. |
| Native input and genuine stale Rendered | `test_genuine_stale_rendered_after_native_wheel`: 11 wheel/key/actual vertical-track/drag variants. Captures actual emitted message at handler, releases same snapshot/source after input, checks reading row or final marker, then user echo. Up starts after PageUp to avoid the documented one-cell bottom tolerance. Four bounded refresh rounds settle deferred starts/pins; animation waits alone do not settle owner callbacks. |
| Hidden real older prepend and upper growth, both orders | `test_hidden_real_prepend_and_upper_growth`: 95 actual persisted entries; newest 30 hydrated; nonfirst later-user line; gated read; answer/thinking growth through present_event; prepend then growth and reverse while hidden; same painted row, changed y, exact replay order, two reads, unchanged bytes. Existing reader injection returns canonical store-produced entries, not fabricated DAOs. |
| Empty-content sentinel with concurrent tail | `test_empty_content_prepend_removes_sentinel`: public tail removal while hidden, actual older load, sentinel observed at public mount seam, nonfocusable, synchronous notice on first mount, all five older answers ordered, sentinel removed, notice once and last. Summary is preserved by ID. |
| Actual result backpressure during blocked cleanup | Existing real graph/session test `[blocked_clear]`: cancellation-suppressing history read holds clear; real tool releases and subscriber observes actual result; clear and run remain blocked, result not admitted to transcript, no run_completed persisted; release cleanup, result/final answer admitted and persisted exactly once. |

## Actual bug and fix

`ChatTranscript.set_visible(False)` formerly force-stopped a public animation
without retaining its pre-stop reading state when no native operation existed.
The original test failed: MOTION-004 disappeared and endpoint MOTION-099 painted.
`dispatch11-first.log` records RED. Hide now reuses the pre-stop reconciliation
already used for horizontal admission. Renamed that private method to
`_reconcile_visible_viewport` to describe both callers; no second state owner.
Final focused GREEN below. A speculative show-token change was removed: it is
not part of this delivery and has no claimed regression proof.

Fixture corrections, not production fixes: wait for initial follow/focus callbacks
before starting public animations; settle owner callbacks separately from animator;
use native PageUp before reading anchor capture; keep summary during empty-tail
removal and hide during removal to prevent automatic top-read racing teardown;
choose a complete repeated label rather than horizontally clipped prefix. Native
Up within one cell of bottom intentionally follows; test it from a settled reading
position, not by weakening the row assertion.

## Finite residuals — not waivers, do not silently expand

Source: original `96.e.1-chat-transcript.html`, `#navigation-tests` (line 415),
AC05/07 test table and scheduling paragraph (lines 400–410), and `#older-failure`.

1. **Unequal axis finish times** remain unproved. Production ScrollTo starts both
   axes with one duration (component `_on_scroll_to`, `_start_native_navigation`).
   Different distances alone cannot prove different completion times. Existing
   dispatch10 paired-axis covering/duplicate tests plus this dispatch's real
   intermediate public-animation tests are the safe bounded evidence. Forcing
   unequal native completion would require additional animator instrumentation;
   do not introduce that under the user's no-harness constraint. Parent must
   explicitly disposition this exact spec demand, not call it passed.
2. **Every-paint public-y interruption oracle**, exact native PageUp/End
   mid-motion supersession and paired mid-motion horizontal interruption remain
   narrower than the existing delayed-start/completion proofs. This dispatch
   observes genuine motion and pre/post paint, not every frame. The spec explicitly
   asks to observe each paint through a scheduling fixture; no new paint recorder
   was introduced.
3. Hidden **after-first-prepend-before-restore** and **partial-prepend plus named
   row** combinations remain unproved. Both full hidden growth orders now pass;
   existing partial failure/liveness evidence remains separate. New hidden tests
   use one theme/size, not the original both-theme/two-size cross product.
4. Full old-pin/user-echo/clear/hide permutations, settled-bottom x-only variants,
   geometry-not-ready and stale-show callback combinations remain as dispatch10
   reports. No stale-show fix or acceptance claim. Existing 99 cases should be
   reused, not multiplied into an invented matrix.

These are explicit remaining evidence requirements, not environmental blockers or
approved exemptions. Parent retains review/completion and final validation.

## Exact verification

Cwd `/root/Code/tui-refactor/slo`:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0
poetry run black --check src/tui/components/chat_transcript/component.py \
 tests/tui/test_chat_transcript_remaining.py tests/tui/test_chat_transcript_lifecycle_matrix.py
PYTHONPATH="$PWD" poetry run pytest -q \
 tests/tui/test_chat_transcript_remaining.py \
 tests/tui/test_chat_transcript_navigation.py \
 tests/tui/test_chat_transcript_lifecycle_matrix.py \
 tests/tui/test_chat_transcript.py tests/tui/test_stream_snapshot_boundaries.py
git diff --check
```

Final: **163 passed, 29 warnings, 148.46s, exit 0** in
`dispatch11-final-focused.log` / `.exit`. Black: three unchanged, exit0.
Diff whitespace check: exit0. Earlier intermediate receipts contain failures and
are not final gates. No full suite or mypy run; parent owns those next.
