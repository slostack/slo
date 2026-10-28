# Dispatch 12 — code closure; acceptance blocked on exact proof disposition

Turn 1, dispatch 12/20, max 60; retries 0. No agents, headless processes,
commits or pushes. Independent review/completion remain parent-owned.

## Implementation and finite evidence

The production cutover is code-complete, with one additional regression repaired:
`ChatTranscript._start_native_navigation` normalizes animated targets to cells.
Textual 8.2.8 `Widget.validate_scroll_target_y/x` rounds them. End→PageUp during
observed animation previously retained a fractional target forever in pending_axes.
The new test failed with that pending operation, then passed after normalization.
No unrelated static repairs or compatibility aliases were added.

- `test_chat_transcript_closure.py::test_native_supersession_during_observed_motion`:
  actual Pilot keys in both orders; bounded wait observes intermediate movement
  before second key, later growth, named row/bottom and no stranded operation.
- `test_chat_transcript_navigation.py::test_horizontal_interruption_retains_vertical_destination`:
  started variants now require actual intermediate y, not merely released start;
  PageUp/End, paired/y-only, destination row or final bottom.
- `test_x_only_pending_pin_survives_old_release`: 16 combinations of old pin vs
  release, FIFO/reverse duplicate callbacks, Right/echo/hide/clear.
- `test_chat_transcript_closure.py::test_old_show_callbacks_do_not_override_current_intent`:
  six hide/clear/echo × FIFO/reverse cases, geometry-unready output and duplicate
  show callbacks; named reading row or current content, not only coordinates.
- `test_hidden_real_prepend_and_upper_growth`: 24 combinations, both themes and
  80×24/120×40, both mutation orders, hide before load / at first prepend mount /
  partial failure at second mount. Same named row, changed y, exact prefix/order,
  no show reread, unchanged real history bytes, partial retry refused and recovery
  summary painted. Uses existing public mount/read seams, not a new harness.

## Exact remaining blocking conflict (not an exemption)

Normative `96.e.1-chat-transcript.html` #navigation-tests requires (1) deliberately
unequal axis completion with covering/native completion delivered in both orders,
and (2) every-paint observation proving public animated-y interruption never
paints its old endpoint. Existing recorder controls owner after-refresh callbacks,
not native animator callback delivery or each terminal paint. ScrollTo uses a fixed
0.1s for both axes; different distances in that route do not prove unequal finishes.
Right merging a pending y can use speed-based unequal durations, but current tests
only prove final destination/retirement, not an observed unequal completion interval.
No unequal-completion or every-paint claim is made. Safely proving those exact
requirements needs additional animator/paint scheduling instrumentation beyond the
existing recorder, or explicit acceptance of the narrower actual-motion/pre/post
paint evidence. The user prohibits an elaborate harness; none was introduced.
Parent must disposition this finite proof conflict; another broad matrix is not
proposed. Manual synthetic terminal smoke likewise cannot be claimed from Pilot:
the specified child/manual harness is explicitly prohibited and no safe interactive
manual mechanism has been established. These are acceptance blockers, not reasons
to withhold the required full default run.

## Full default gate — executed after production/test edits

Cwd `/root/Code/tui-refactor/slo`. Exact reproducible invocation and safe environment:
`bash docs/implementation/96-chat-transcript/dispatch12-full-command.sh`.
Python and Poetry use `/root/.pyenv/versions/slo-harness/bin/python`, 3.11.7;
synthetic Anthropic placeholder, real provider env overrides unset, test mode,
fixed gpt-5.4, auto-visualizer disabled, COLUMNS=120/LINES=40. Existing root fixtures
isolate collection/per-test SLO_HOME and HOME. No package/environment changes.

Command inside script: **`PYTHONPATH="$PWD" poetry run pytest`** — no paths,
additional markers, exclusions or xfail changes. Project default `not e2e` applies.
**8502 passed, 19 deselected, 482 warnings in 993.11s; exit 0.**
Receipt: `dispatch12-full.log`, `dispatch12-full.exit`. Warnings include existing
LangGraph/Pydantic deprecations, SDK option warnings and unawaited AsyncMock warnings;
not a warning-free claim. `dpkg -V coreutils` afterward produced no output (exit 0).

Earlier focused evidence: hidden 24 passed/15 deselected; order 24 passed/82
deselected; closure final 8 passed. Expanded focused/resource gate initially had
2 failures/153 passed: a reading-line capture before owner callbacks settled, and
an animation capture before its paint caught up. Added bounded Pilot settlement
before those oracles; final default gate passes both. This is fixture timing
correction, not a second production repair. The first key-posting experiment timed
out because direct widget Key posting did not drive app binding dispatch; replaced
with actual Pilot key tasks. No invented production RED for that experiment.

## Static/resource/ownership checks

- Full default includes both real archive/resource tests: wheel/sdist exact CSS,
  extracted isolated import; no installation. `test_chat_transcript_resources.py`.
- Exact changed/new Python inventory from `git ls-files -m -- '*.py'` plus
  `git ls-files --others --exclude-standard -- '*.py'`, sorted unique, passed to
  `poetry run black --check`: **50 unchanged, exit 0** (`dispatch12-format.log`).
  This includes inherited feature edits; no broad mutating formatter ran.
- `poetry run mypy src/ tests/`: **292 errors in 58 files, 763 checked; exit 1**.
  Compared against archived HEAD baseline `dispatch6-static-baseline.log`, ignoring
  line numbers and canonical TranscriptProjector→TranscriptProjectionAdapter rename:
  identical diagnostics. `dispatch12-static-comparison.txt`. Unwaived, not green.
- `git diff --check`: exit 0. Owner-map cleanup in AGENTS.md and docs/RESEARCH.md
  names component-local notice adapters, canonical projector and physically-local
  but app-owned workflow progress adapter. No workflow ownership moved.

## Acceptance map for independent review

| Normative ID | Evidence and status |
|---|---|
| AC01 | Real 65-entry replay/30+30+5, read-only bytes; dispatch9 app hydrate→startup→subscribe and real new/Faux persistence. Full gate passes. |
| AC02 | Projector, stream widgets, stream_snapshot_boundaries; normalized repair/terminal/coalesced snapshots. Full gate passes. |
| AC03 | Tool/steering and lifecycle matrix; actual blocked-clear tool-result backpressure from dispatch11. Full gate passes. |
| AC04 | Production 500/10, saturation/convergence, older cursor/window tests in test_chat_transcript. Full gate passes. |
| AC05 | Navigation/remaining/closure + scroll_follow tests pass; fractional completion fixed. Exact unequal-axis/every-paint proof conflict above remains blocking. |
| AC06 | Real-store cancellation/read/projection/concurrent lifecycle tests plus partial prefix/retry latch. Full gate passes. |
| AC07 | Hidden 24-case matrix, show/pin tests, dispatch9 retained modal focus. Full gate passes; manual proof remains blocked as stated. |
| AC08 | Native selection/copy/highlight suites included in default gate (filename e2e is not itself a marker exclusion). |
| AC09 | App queue/clear/expansion/new tests included; queue remains app-owned input sibling. |
| AC10 | Tree sibling/exporter tests included; component owns neither export nor execution. |
| AC11 | Injected attached/detached launcher and workflow progress/abort integration tests included. |
| AC12 | Component no-app-CSS themes/sizes and archive/extracted-import tests included. |
| AC13 | Adapter registration/import-order/projector migration tests included; owner map reconciled. |

Passing counts do not substitute for the two exact AC05 proofs or manual evidence.
Static baseline is also unwaived. Code closure and full-default regression gate are
complete; final acceptance is **BLOCKED**, not READY/approved. Parent retains the
independent source review and original-spec completion assessment.
