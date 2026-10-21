# CI repair — fleet layout failure (worker C)

**Status: READY (author gates green, ER-03 resolved).** Independent review and the
full merged-suite gate remain pending; no claim of CI success, live acceptance, or
completion. Continuation dispatch 3 (delta 3, retries 0); inherited turn/dispatch
budgets remain explicitly unlimited, historical counts preserved per
`current-ci-repair-plan.md`.

## Failure identity

- Test: `tests/integration/test_workflow_progress_tui.py::TestTwentyChildFleetJourney::test_twenty_child_fleet_journey[120x40-slo-default]`
- CI: pipeline 2970613678 / job 17338411077, trace `/tmp/herdr-ci-4ab10b0.log`, SHA `4ab10b0`.
- Exact assertion (line 1292): `assert (reopened_log.scroll_x, reopened_log.scroll_y) == (4.0, 5.0)`.
- CI observed: `(0.0, 5.0)` — `scroll_x` lost, `scroll_y` kept.
- Only the `120x40` variant failed; `60x20` and `80x24` passed in the same run.
- CI runs sequentially (`poetry run pytest -q`, one process, Python 3.11 `python:3.11` image, textual 8.2.8) on a loaded shared runner (`mgr-1`, docker executor).

## Journey leg that fails

Open the child's progress view → read history across two refreshes → set
`(scroll_x, scroll_y) = (4, 5)` → Escape (minimize, saving the viewport) → Enter
(reopen with the saved viewport) → assert the reopened log is at `(4.0, 5.0)`.

The viewport is saved correctly (y=5.0 survives). The reopened screen's restore
runs but `scroll_x` ends at 0.0.

## Reproduction

Not reproducible locally at commit `4ab10b0` in isolation, under the module
scope, under `tests/integration/` scope, or under 14-thread CPU saturation on
the 16-core 90 GiB host — because the failure is an event-loop-congestion race
that needs a Resize message to be processed *late* relative to the paint, which
a fast local loop never schedules.

Deterministic local reproduction of the exact CI signature was obtained by
injecting a 50 ms delay into `MessagePump._dispatch_message` for `Resize`
messages delivered to a `ProgressLog` (emulating CI runner congestion), then
running the failing variant:

```
RESTORE vp=(4.0,5.0,f=False) size_known=True def=0 allow_h=False max=(217,163) -> False scroll=(0.0,0.0)
```

## Root cause (causal chain, with evidence)

Two cooperating defects in `src/tui/workflows/dao.py::ProgressViewportDAO.restore`:

1. **Pre-layout clamp discards the saved pan.** When the restore runs before
   the log's first resize, the RichLog has rendered nothing: every `write()` is
   a deferred render (`RichLog.write` early-returns into `_deferred_renders`
   while `_size_known` is False). `lines` holds blank strips and
   `max_scroll_x` is 0. `restore()` treated this provisional zero range as
   authoritative, clamped `scroll_x` to 0, and returned True — landing the
   restore permanently at x=0 instead of staying pending.

2. **In-range horizontal pan dropped while the scrollbar is not yet shown.**
   Even when the range is already sufficient (`max_scroll_x=217 ≥ 4`), a
   horizontal pan only lands once `log.allow_horizontal_scroll` is True, which
   requires the horizontal scrollbar to be shown
   (`show_horizontal_scrollbar = virtual_size.width > width`, set during
   `_refresh_scrollbars` inside `_size_updated`/`_scroll_update`). If the
   restore runs while that scrollbar is still pending layout,
   `Widget._scroll_to` computes `maybe_scroll_x = x is not None and
   self.allow_horizontal_scroll` → False and **silently drops x**, applying only
   y. `restore()` had returned True, so the position was never retried. This is
   exactly the CI `(0.0, 5.0)`.

Both are congestion races: on a fast loop the resize/scrollbar settle before
the restore's `call_after_refresh` callback runs, so the defect is invisible.

## Fix (no assertion weakening, no sleep, no timeout inflation)

`src/tui/workflows/dao.py::ProgressViewportDAO.restore` now refuses to *land*
while the position cannot actually be reached, returning False so the existing
pending-restore machinery retries once layout settles:

- `not log._size_known or log._deferred_renders` → return False (content still
  provisional; a zero scrollable range is not authoritative).
- `self.x > 0 and not log.allow_horizontal_scroll` → return False (the
  horizontal scrollbar is not yet shown, so `scroll_to` would drop x).
- Otherwise: in-range → `scroll_to(x, y)` and return True; out-of-range → clamp
  and return False (unchanged existing retry-on-clamp behaviour).

`src/tui/workflows/session_progress_screen.py::on_mount` adds one more watcher
so the pending restore is retried when the horizontal scrollbar appears:

```python
self.watch(self._log, "show_horizontal_scrollbar", self._retry_pending_restore, init=False)
```

This complements the existing `virtual_size` watcher and `LayoutChanged` hook.
No timing, sleep, or assertion was changed; the screen still restores only via
the existing paint/navigation-revision guards, and user navigation still wins.

## Files changed (worker C only)

- `src/tui/workflows/dao.py` — `ProgressViewportDAO.restore` guards.
- `src/tui/workflows/session_progress_screen.py` — `on_mount` adds the
  `show_horizontal_scrollbar` retry watcher.
- `tests/tui/workflows/test_session_progress_screen.py` — new regression test
  `TestRestoreConvergence::test_zero_sized_restore_waits_for_layout`.
- `docs/implementation/94-herdr/ci-repair-fleet.md` — this report.

`src/tui/app.py` was **not** edited (owned by worker B); no app change was
needed — the defect is fully inside the owned viewport/log components.

## RED → green evidence

RED (deterministic unit repro, before fix):

```
python -m pytest tests/tui/workflows/test_session_progress_screen.py::TestRestoreConvergence::test_zero_sized_restore_waits_for_layout -q
# FAILED — assert (0.0, 5.0) == (4.0, 5.0)
```

RED (CI-signature congestion repro, before fix):
instrumented run of the real journey variant reproduced
`AssertionError: max_scroll=(217, 164) ... assert (0.0, 5.0) == (4.0, 5.0)` —
identical to CI.

Green (after fix):

| Command | Result |
|---|---|
| `pytest tests/tui/workflows/test_session_progress_screen.py -q` | 51 passed |
| `pytest tests/tui/workflows/ tests/integration/test_workflow_child_abort_tui.py -q` | 418 passed |
| `pytest tests/integration/test_workflow_progress_tui.py tests/integration/test_workflow_child_abort_tui.py -q` | 22 passed |
| `pytest tests/integration/test_workflow_progress_tui.py -q` (under `stress-ng --cpu 14`) | 19 passed |
| Congestion repro of the failing 120x40 variant, 20 runs | 20/20 passed |
| `poetry run mypy src/tui/workflows/dao.py src/tui/workflows/session_progress_screen.py` | no issues |
| `poetry run black --check <changed files>` | clean (test file reformatted) |

Every parameter variant of the journey (`60x20`, `80x24`, `120x40` ×
`slo-dark`, `slo-default`) passes.

## Preserved constraints

- Previous same-history replacement fixture fix from `4ab10b0` untouched
  (`TestOwnedWorkflowListToProgress` still passes).
- No assertion weakened, no sleep added, no timeout inflated, no production
  layout/sizing/scroll semantics relaxed. The user journey assertions
  (`(4.0, 5.0)`, `max_scroll_x > 0`, panel/region geometry) are unchanged.
- No overlap with workers A/B files; no commits, pushes, full-suite runs, or
  subagents.

## ER-03 resolution (early-review finding, dispatch 3)

**Finding** (`ci-repair-early-review.md` ER-03): the `x > 0 and not
log.allow_horizontal_scroll → return False` guard in
`ProgressViewportDAO.restore` was too broad. Once content is measurable,
`max_scroll_x == 0` means a **settled valid layout** (narrow content — no
horizontal scrollbar is ever shown), not a provisional one. The guard suppressed
both axes indefinitely, so a reopened view over narrow content lost its reachable
saved vertical offset (`(4,5)` stayed `(0,0)`).

**Correction** (`src/tui/workflows/dao.py`, guard only, two tokens added): the
scrollbar-availability guard now applies only while a real horizontal range
exists that a pan could not yet land in:

```python
if self.x > 0 and log.max_scroll_x > 0 and not log.allow_horizontal_scroll:
    return False  # pending until the scrollbar appears
```

With measurable content and `max_scroll_x == 0`, the normal path clamps x to 0
and applies the reachable y. The earlier provisional-content guards
(`_size_known` / `_deferred_renders`) are unchanged: a zero range is only
trusted once it is measurable. Unfulfilled intent is retained — when a saved
offset is clamped the restore still returns False, so the pending intent
survives under the existing navigation-revision guards and can land if a later
narrower layout makes it reachable. No assertion was weakened, no sleep added,
no timeout changed, and the deferred-render zero-sized regression and the six
fleet parameter variants are untouched.

**Test-first RED (before the guard change):**

| Test (all new in `TestRestoreConvergence`) | RED failure |
|---|---|
| `test_settled_narrow_content_clamps_x_and_restores_y` (saved `(4,5)`, 40 narrow entries at 120x40) | `assert (0.0, 0.0) == (0.0, 5.0)` — y lost |
| `test_pending_pan_lands_when_the_scrollbar_appears` (measurable range, `show_horizontal_scrollbar` held False via `set_reactive`) | `assert (0, 0) == (0.0, 5.0)` — everything stayed pending |
| `test_navigation_cancels_a_scrollbar_blocked_pending_restore` (up-key before the transition) | `_pending_restore` still set after the late transition (user input did not win) |

The scrollbar-blocked tests use `Widget.set_reactive` to hold
`show_horizontal_scrollbar` False against a measurable wide-content range, then
restore it. Transition fidelity was proved by an isolated experiment: assigning
the reactive (`log.show_horizontal_scrollbar = True`) fires the screen's
watcher, `set_reactive` does not — matching how `_refresh_scrollbars` delivers
the real transition in production.

**GREEN (after the guard change, same run):** `TestRestoreConvergence` 8/8,
full module `tests/tui/workflows/test_session_progress_screen.py` **54 passed**.

**Deterministic isolation of the scrollbar-only race (required by ER-03.2):**
with the `show_horizontal_scrollbar` watcher temporarily removed from
`session_progress_screen.py` (exact deletion, restored afterwards), the module
run gave **2 failed, 6 passed** in `TestRestoreConvergence`: exactly
`test_pending_pan_lands_when_the_scrollbar_appears` and
`test_navigation_cancels_a_scrollbar_blocked_pending_restore` fail, all other
convergence tests pass. The two tests therefore fail without the watcher and
pass with it — no other layout signal substitutes.

**User navigation wins (required by ER-03.3):** the third test presses `up`
while the pending restore is scrollbar-blocked, then flips
`show_horizontal_scrollbar`; the final assertions require the reader's own
offsets to survive and `_pending_restore` to be discarded. Green only because
`_retry_pending_restore` re-checks the navigation revision. The pre-existing
`test_navigation_cancels_a_pending_restore` and `TestNavigationWins` remain
unchanged and green.

### Verification commands (dispatch 3)

Cwd `/root/Code/slo-94-herdr-integration/slo`, `environments/tests.env` sourced
(local model `gpt-6.1-sol`), `SLO_HERDR_DISABLED=1`, `SLO_AUTO_VISUALIZE=0`,
`PYTHONPATH=$PWD`, interpreter `/root/.pyenv/versions/slo-harness/bin/python`
(3.11.7). No full suite run (plan-reserved for fan-in).

| Command | Result |
|---|---|
| `pytest tests/tui/workflows/test_session_progress_screen.py::TestRestoreConvergence` (pre-fix) | 3 failed, 5 passed (the 3 new RED tests) |
| Same, with watcher temporarily removed (post-fix) | 2 failed, 6 passed — watcher isolation proof |
| `pytest tests/tui/workflows/test_session_progress_screen.py` | **54 passed** |
| `pytest tests/tui/workflows/` | **418 passed** |
| `pytest tests/integration/test_workflow_progress_tui.py tests/integration/test_workflow_child_abort_tui.py` | **22 passed** (all six 20-child variants included) |
| `pytest tests/integration/test_workflow_progress_tui.py` under 14-thread CPU saturation | **not run — `stress-ng` is not installed on this host** (prior dispatch's stress evidence stands; the normal-congestion integration suite above passed) |
| `poetry run black --check` on the three owned changed files | clean |
| `poetry run mypy src/tui/workflows/dao.py src/tui/workflows/session_progress_screen.py` | no issues |
| `git diff --check`, `dpkg -V coreutils` | both exit 0, no output |

`tests/integration/test_workflow_progress_tui.py` was **not edited** — the
existing journey assertions already cover the reopened `(4.0, 5.0)` viewport;
its line-1292 assertion is unchanged. No `src/tui/app.py` edit was needed or
made (worker B owns it).

## Risks / limitations

- The `show_horizontal_scrollbar` watcher is a new reactive watch on the log;
  it only calls the existing `_retry_pending_restore` (guarded by
  `is_live`/navigation revision), so it cannot scroll a view the reader has
  navigated. Covered by `TestNavigationWins` and the new
  `test_navigation_cancels_a_scrollbar_blocked_pending_restore`.
- A saved x clamped by a settled narrow layout keeps its pending intent by
  design; it can only land if a later layout widens the range, and any user
  navigation discards it. This matches the existing clamped-retry policy.
- The fix relies on Textual internals (`_size_known`, `_deferred_renders`,
  `allow_horizontal_scroll`) — same stable surface the codebase already uses;
  pinned to textual 8.2.8.
- Local evidence is offline; the real CI rerun on the fixed SHA is the
  authoritative confirmation (pending fan-in full gate). The CPU-saturation
  confirmation from dispatch 2 was not repeated because `stress-ng` is absent
  on this host; the deterministic congestion repro and the watcher-isolation
  proof carry the race evidence.
