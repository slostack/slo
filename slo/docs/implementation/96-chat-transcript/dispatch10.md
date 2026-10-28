# Dispatch 10 — partial matrix closure, NOT READY

Turn1 dispatch10/20, max60, retries0. No nested agents, headless work, commit,
push or full suite. Dispatch9 closed integration cases were not repeated.

## Changed files and verified behavior

- `tests/tui/test_chat_transcript_navigation.py`: 94 parameterized cases using
  existing TranscriptTestApp and a local after-refresh recording subclass. No
  harness/platform, private-state assignment, replacement geometry or animator.
- `tests/tui/test_chat_transcript_lifecycle_matrix.py`: five real-store/graph
  lifecycle cases.
- `component.py`: synchronous plain notice settlement is now queued on the newly
  mounted widget, not immediately on its owner. Otherwise the owner can consume
  the reading anchor before the queued mount changes layout, shifting a tree
  reading line by one row. Dedicated RED then GREEN in dispatch10-notice-*.log.

| Assigned case | Current executable evidence |
|---|---|
| Above/below growth before deferred start / after movement before settlement; both themes and sizes | `test_native_destination_survives_growth` (32 cases). PageUp plus delivered ScrollUp track message; actual chrome-click wiring for vertical track remains unproved. |
| Deferred PageUp→End / End→PageUp, reordered starts, duplicate completion, final/later growth | `test_delayed_starts_and_duplicate_completions_respect_latest_input` (4). Named row and latest marker; covers delayed starts, not precise mid-animation timing. |
| X-first real history, public y/focus, Right/ctrl/shift wheel/actual horizontal track | `test_x_first_real_history_preserves_reading` (32; both themes and sizes). Upper/lower growth then later upper growth, row retained and x changes. |
| Pending PageUp/End before/after start, paired and y-only followed by Right | `test_horizontal_interruption_retains_vertical_destination` (8). Start released before second input in started variant; does not guarantee second input lands during motion rather than after completion. |
| Pending bottom pin / release, old/new delivery order | `test_x_only_pending_pin_survives_old_release` (4), final bottom marker and retained x. |
| Removed candidate numerical fallback | `test_removed_reading_candidate_uses_clamped_numeric_fallback`. Public remove; clamped y, no bottom jump. |
| Two-axis different distances, x-at-edge, covering before/after animator and duplicates | `test_two_axis_completion_order_and_no_movement` (6). ScrollTo handler boundary, not mouse-drag wiring; different distances do not prove unequal finish times. |
| Hide/clear stale paired callbacks | `test_stale_two_axis_callbacks_after_visibility_or_reset` (4). Before start / held settlement after animation. Actual hide during motion remains unproved. |
| Focus interruption | `test_programmatic_reveal_interrupts_pending_native_operation` (2). Mounted focus API, no stranded operation and later growth. |
| Notice reading-row regression | `test_synchronous_notice_above_tree_keeps_reading_line`, failed one-row drift before production fix, passes after. |
| Mixed user/thinking/tool/empty event replay and exhausted prepend | `test_mixed_replay_and_empty_prepend_preserve_order_and_bytes`: actual file/projector, adjacency/order and unchanged bytes. Empty assistant event emits no block; not an all-empty mounted prepend sentinel case. |
| Partial older failure with active tool | `test_partial_older_failure_preserves_active_tool_identity`: retained prefix, retry latch, partial not terminal, same live result target. |
| Active inference/tool-result lifecycle | `test_active_inference_tool_result_survives_presentation_change[clear,hide]`: actual app/session/agent/graph/Faux, event-gated harmless tool, session stays running, result/user/terminal persisted once. Clear uses existing unmatched-result logical notice contract; hide keeps tool block result. |
| Concurrent clear/bind/close | `test_concurrent_clear_bind_close_join_before_live_delivery`: cancellation-suppressing real replay, serialized callers, late tool-result admission refused after terminal close. |

## Exact final focused verification

Cwd `/root/Code/tui-refactor/slo`:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0
PYTHONPATH="$PWD" poetry run pytest -q \
 tests/tui/test_chat_transcript_navigation.py \
 tests/tui/test_chat_transcript_lifecycle_matrix.py \
 tests/tui/test_chat_transcript.py tests/tui/test_scroll_follow.py \
 tests/tui/test_stream_snapshot_boundaries.py \
 tests/tui/test_transcript_adapter.py tests/tui/test_transcript_projector.py
```

**221 passed, 27 warnings, 141.13s, exit 0**; dispatch10-final.log/.exit.
Black check of the two added tests and component: 3 unchanged, exit0.
`git diff --check`: exit0. Scoped mypy reports 10 imported-source diagnostics in
6 existing files, none in the two new test files; it is NOT green and does not
replace/waive the 292-error whole-repository baseline. `dispatch10-mypy.log`.

Intermediate failures were fixture/oracle errors unless noted: wrong theme name;
re-finalizing sealed blocks (changed setup to live set_answer); scrollbar glyphs
in full-screen equality (use named row); wrong history reasoning/output fields;
start announcement does not mount tool (use call_end); clear drops tool maps so
unmatched result is a logical notice; wide rows wrapped (shortened repeated row
within declared width); content wrapper clipped x (set wide content explicitly);
close is terminal, not reopenable. No production behavior changed for these.
The notice regression was isolated in its own failing test before the fix; an
owner-deferred experimental fix failed and was removed, then widget scheduling
passed. The original two-axis subsequent mutation now uses awaited live answer
mount/growth; the separate notice regression retains the failing scenario.

## Still unclosed — do not infer full assigned closure from counts

No environment blocker. Remaining work is evidence/implementation, not a waiver:

- Exact mid-animation gates (as opposed to before start/after movement), unequal
  axis finish times, public animated-y interruption with pre-stop paint oracle;
  no-movement request with preexisting other-axis animation.
- Full native wheel/key/vertical chrome track/drag input matrix, controlled genuine
  stale Rendered delivery, all old-pin/user-echo/clear/hide orderings, settled-bottom
  x-only variants beyond pending-pin tests, geometry-not-ready/stale-show cases.
- Prescribed hidden real-history older/prepend + upper answer/thinking growth
  orders and nonfirst named-line oracle; current tests do not close that matrix.
- Active real tool-result **backpressure while cleanup is blocked**, distinct from
  active inference clear/hide and direct tool-result concurrent lifecycle tests.
- Empty-content older sentinel and hidden partial-prepend named-row combinations.

Parent retains full/default/static/resource/manual gates, documentation cleanup
and independent review/completion. No feature-completion claim.
