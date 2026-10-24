# Selection fence 103 — READY causal fix (bounded selection lane)

Same unfinished workflow turn 1: started 1, completed 0, historical partial 1,
supplied dispatch count 103, retries 0. Effective turn and dispatch budgets are
unlimited. No agents dispatched here. This is not whole-feature acceptance or
independent workflow review. Full make test remains deferred until parallel lanes
finish, as requested.

## Scope and mechanism

Changed only `tests/tui/test_selection_scroll_highlight.py` and the new helper
`tests/tui/selection_fixture_fence.py`, plus these 103 receipts. No production
file was edited; in particular the parallel owner's `src/tui/app.py` was not
changed. Existing partial work was preserved. No commit/push/PR, reset, clean,
stash, specification, shared KB, other-worktree or live-system changes.

Read selection-cause-102.md and its actual probe and test. Its established cause
is a deferred follow pin overwriting the successfully applied reveal, not stale
vertical target geometry. The new fixture fence is installed before the finite
fixture writes. It delegates the actual app and transcript-viewport
call_after_refresh callbacks and counts each until execution completes. A parent
remains outstanding while it schedules descendants. Thus the lazy scroll-end
closure and clear-follow callback are both accounted for; the boolean follow
latch alone is not a completion signal.

Before testing callback completion, the helper awaits mounted transcript widgets
and fences their message queues bottom-up. It then fences each transcript
ancestor through the app. This delivers existing Rendered messages through their
actual bubbling route rather than fabricating messages or assuming a single
Pilot pause drains descendant work. These fixtures finalize answers or call
set_thinking synchronously; there is no active token stream to await.

After counted callbacks finish, a real call_after_refresh marker fences the
resulting compositor commit. If callbacks introduced more descendants during that
refresh, the counter forces completion before another paint marker. This loop
waits for work, never for target visibility and never repeats scrolling. The
same paint fence follows exactly one scroll_visible call. User bodies request
top alignment on that first/only reveal, replacing the previous second reveal.
No global task drain, sleeps, timeout increases, skips, latch override, disabled
follow policy or production behavior changes were introduced. Existing
post-drag and post-scroll Pilot waits remain unchanged.

The original exact offset lookup, native mouse drag, highlight-color assertion
and selection-after-scroll assertion remain. Exact selected text and clipboard
assertions were additionally strengthened to require `bravo` before scrolling.

## Controlled causal evidence

`selection_probe_103.py` derives from 102's retained observational probe. It holds
only real queued follow pins and preserves their callbacks and arguments. Its
GREEN mode releases those pending callbacks at fence entry; the fence must wait
for their real descendants. RED bypasses only the pre-reveal fixture fence and
releases the held callbacks after reveal application, reproducing the proven
wrong ordering. The post-reveal completion fence cannot repair an already
superseded reveal. No assertion is weakened for either experiment.

- `selection-103-old-red.log`: unchanged old test + 102 probe: **1 failed,
  62 passed**, exit 1, original offset-not-visible failure.
- `selection-103-controlled-1-red.log`: new test with pre-reveal fence bypassed,
  forced old ordering: **1 failed, 62 passed**, exit 1, same offset failure.
- `selection-103-controlled-{2,3,4}-green.log`: three held-callback dark-thinking
  executions: **63 passed each**, exit 0.
- `selection-103-all-controlled.log`: all six body/theme combinations plus
  module/foundation cases: **76 passed**, exit 0.
- `selection-103-final-controlled.log`: after final typing/assertion edits,
  all six combinations again: **76 passed**, exit 0.

GREEN teardown asserts exactly one scroll_visible call, fixture commitment before
it, and no executed pin/lazy-scroll-end/clear-follow descendant after it.
`selection-103-order.log` extracts release → fixture committed → one reveal
from the final full traces. The complete traces retain callback identities,
geometry and actual scroll application. These are controlled scheduling proofs,
not claims of timing-neutral observations.

## Real uninstrumented verification

All commands ran from `/root/Code/slo-94-herdr-integration/slo`, using the approved
Python 3.11.7 fallback harness, no new virtual environment:

```bash
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <suffix>
```

The harness sets Faux-safe placeholders, `SLO_AUTO_VISUALIZE=0` and
`SLO_HERDR_DISABLED=1`; suite isolation/terminal guards remain active. No real
provider/Herdr/window run was requested. No system symlinks or stubs were created.

Suffixes:

- Initial module: `tests/tui/test_selection_scroll_highlight.py` — **76 passed,
  2 warnings**, exit 0 (`selection-103-first.log`).
- Surrounding partition:
  `tests/tui/test_selection_scroll_highlight.py tests/tui/test_selection_copy.py tests/tui/test_selection_copy_e2e.py tests/tui/test_selection_observer.py tests/tui/test_markdown_content_compiler.py tests/tui/test_user_message_block.py`
  — initial **200 passed**, then three final repetitions **200 passed, 2 warnings
  each**, exit 0 (`selection-103-final-{1,2,3}.log`). The 62 mandatory foundation
  tests are included in these totals.
- Controlled node: `'tests/tui/test_selection_scroll_highlight.py::TestPilotVisibleSelection::test_selection_paint_and_scroll_remain_native_for_every_visible_body_and_theme[slo-dark-thinking]'`
  with `-p docs.implementation.94-herdr.selection_probe_103 --selection-order=red|green -s`.
- All controlled: module path with the same plugin and `--selection-order=green -s`.
- Old RED: same node with `-p docs.implementation.94-herdr.selection_probe_102 --selection-order=red -s`.

Static checks:

```bash
PYENV_VERSION=slo-harness poetry run mypy --follow-imports=silent tests/tui/selection_fixture_fence.py tests/tui/test_selection_scroll_highlight.py
PYENV_VERSION=slo-harness poetry run black --check tests/tui/selection_fixture_fence.py tests/tui/test_selection_scroll_highlight.py docs/implementation/94-herdr/selection_probe_103.py
git diff --check
dpkg -V coreutils
```

Final scoped mypy: **Success: no issues found in 2 source files**. Initial mypy
caught DOMNode versus Widget inference; fixed with the actual Widget walk filter,
not an ignore. Black: all three unchanged, exit 0. Diff check and coreutils:
silent, exit 0; coreutils checked again after final controlled run. Test diff
reviewed in `selection-103-test.diff`; new helper reviewed separately. Receipts
include exact exits. No full-repository static-clean claim.

## Context and remaining boundary

Consulted supplied AGENTS/CLAUDE/docs RESEARCH, root RESEARCH, KB Welcome,
slo README and gotchas; vendored engineering routing/testing/ownership,
code-test-loop, Python/declarative/Faux, Textual and workflow SKILL. Also read
coding/named-argument/docstring guidance (a combined broad read was truncated).
Routing is Python/Textual composed Pilot testing with Faux, not API/database,
provider, CLI or product scrolling redesign. Framework reads include actual
AwaitMount, Pilot message fence, Screen callback drain and app follow/render
owners. No shared documentation updated under the output restriction.

The helper is intentionally for finite selection fixture mutations, not a generic
idle detector for running streams. It uses installed Textual mount-event and
message/refresh semantics; a framework upgrade should rerun the controlled proof.
No product scroll-intent generation/cancellation policy is implied by this fix.
Full make test and independent integration review are still outstanding across
parallel lanes. **READY causal fix for this selection lane only.**
