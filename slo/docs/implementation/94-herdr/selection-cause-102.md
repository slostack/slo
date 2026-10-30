# Selection cause 102 — INCOMPLETE; overriding follow callback demonstrated

Same unfinished workflow turn 1: started 1, completed 0, historical partial 1,
supplied dispatch count 102, retries 0. Effective turn/dispatch budgets unlimited.
No agents dispatched. No production edits (especially no app.py edit), commits,
pushes, resets, clean/stash, global/live, specification or other-worktree changes.
Existing partial work preserved. All new artifacts are in this directory. The
selection test/helper diff remains empty.

## New evidence

`selection-102-observe.log` is an observational run of the unchanged selection
module with the test-only `selection_probe_102.py` pytest plugin. It wraps actual
Textual call_after_refresh callbacks and synchronous scrolling methods, delegates
original arguments, and records ordered queue/execute identities plus snapshots.
No fabricated Rendered messages, extra sleeps, reveal retries, skips or deadline
changes. Wrappers affect scheduling overhead, so this is an instrumented execution,
not a timing-neutral replay of historical gate 100.

Result: **1 failed, 75 passed**. The same dark thinking target fails at offset
`(6,0)`, with final body `Region(x=3,y=-8,width=72,height=1)`.

Within its `TRACE ...[slo-dark-thinking]` section:

- Record 0008: reveal is requested while scroll=0, max=36, viewport height=13;
  target parent virtual y=26, body screen y=28. Follow latch is true.
- 0013: Textual computes delta=15 and queues callback 7, `_scroll_to(None,15)`.
- 0021 onward: further real `_lazily_scroll_end` callbacks are queued by
  `_pin_transcript_to_end_after_refresh` (app.py:3846).
- 0122–0125: callback 7 executes, changing scroll from 36 to 15 successfully.
- 0130 onward: compositor geometry reflects body y=13 at scroll=15.
- Later `_lazily_scroll_end` callbacks execute `_scroll_to(0,36)`. Final body y=-8.
  Target parent virtual y stays 26; final virtual height=49, viewport height=13,
  max scroll=36. Width settles from 78 to 76 during scrollbar layout, but the
  vertical target remains stable.

**For this captured failure, a subsequent follow pin overrides a successfully
applied reveal. Stale vertical target geometry is not the causal explanation.**
See `selection-102-order-extract.log` and the complete trace for callback order.
The observer initially filtered names for scroll/following, so initial app pin
scheduling itself was not wrapped; its descendant queue source and execution are
recorded. The retained plugin additionally recognizes `_pin_transcript`.

## Controlled RED

Plugin option `--selection-order=red` holds only original queued
`_pin_transcript_to_end_after_refresh` callbacks. After the real reveal's
`Widget._scroll_to` executes, it releases those callbacks through the original
call_after_refresh gateway in their recorded order. It asserts that original
pending callbacks actually exist. This forces the observed decisive ordering:
reveal application → deferred app follow pin → lazy native scroll-end application.
It does not reproduce every incidental interleaving in the observational trace.

Two separate executions of the dark thinking node:

- `selection-102-red1.log`: **1 failed, 62 passed**, exit 1.
- `selection-102-red2.log`: **1 failed, 62 passed**, exit 1.

Both fail the original exact offset lookup, not a probe assertion. Both show
final scroll=36/body y=-8. The original selection assertions are untouched.
The 62 passes are the harness's mandatory DAO/projection foundation tests.

## Framework reading and remaining prerequisite

Read installed Textual 8.2.8 implementations of `scroll_visible`,
`scroll_to_widget`, `scroll_to_region`, `scroll_to`, `_scroll_to`, `scroll_end`,
Screen `_invoke_and_clear_callbacks`, `_on_timer_update`, `_refresh_layout`, and
Pilot `pause`/`_wait_for_screen`. Read app render-event, render notification and
follow helpers read-only.

`scroll_visible` computes from virtual geometry now and queues scroll application.
`scroll_end` queues a closure that reads max_scroll_y later. Screen drains a copy
of callbacks; callbacks queued during a drain belong to a later pass. Pilot's
message fence covers messages queued at its start, not all future descendants;
its pause concludes by calling `_on_timer_update`, which can schedule another
callback drain. A single elapsed pause or a single refresh fence is therefore
not the recursive follow-transaction completion prerequisite.

Required next work: implement and verify a test-only semantic fence that accounts
for *all* fixture mount/render follow descendants and their final compositor
commit **before issuing the one reveal**, then await reveal completion and its
paint commit before hit testing. The fence must also handle already-completed
follow callbacks and Rendered messages still in transit; simply waiting for the
boolean latch to turn false is insufficient because there are multiple pins.
No such fence has been implemented or validated here. Do not substitute repeat
scrolling, deadline increases, or polling until the target happens to be visible.

No production bug verdict is justified solely by a fixture calling programmatic
reveal while its own append/follow work is still pending. If a real user scroll
must supersede those queued pins, the app owner should investigate an explicit
scroll-intent generation/cancellation check at deferred pin execution. That is
an unverified product-policy alternative, **not an authorized or proven minimal
production fix**. No concurrent product edit was made.

## Verification and receipts

CWD: `/root/Code/slo-94-herdr-integration/slo`.
Every pytest command used:

```
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <suffix>
```

Harness sets Faux-safe configuration, SLO_AUTO_VISUALIZE=0 and
SLO_HERDR_DISABLED=1. Existing suite isolation and terminal guards remain active.
No provider/Herdr calls or windows intentionally exercised. No system symlinks
or command stubs created. Interpreter inspection reported Python 3.11.7 at
`/root/.pyenv/versions/3.11.7/bin/python` under the approved fallback invocation;
Textual 8.2.8. No environment created or installed.

Suffixes:

- Observe: `tests/tui/test_selection_scroll_highlight.py -p docs.implementation.94-herdr.selection_probe_102 -s`
- RED1/RED2: `'tests/tui/test_selection_scroll_highlight.py::TestPilotVisibleSelection::test_selection_paint_and_scroll_remain_native_for_every_visible_body_and_theme[slo-dark-thinking]' -p docs.implementation.94-herdr.selection_probe_102 --selection-order=red -s`
- Surrounding: `tests/tui/test_selection_scroll_highlight.py tests/tui/test_selection_copy.py tests/tui/test_selection_copy_e2e.py tests/tui/test_selection_observer.py tests/tui/test_markdown_content_compiler.py tests/tui/test_user_message_block.py`

Surrounding uninstrumented run: **200 passed, 2 warnings**, exit 0
(`selection-102-surrounding.log`). This is NOT a repair or causal GREEN.
Black check on unchanged selection test and receipt plugin passed. `git diff
--check` silent, exit 0. `dpkg -V coreutils` silent after probes and surrounding
suite, exit 0. Empty `selection-102-test.diff` records unchanged selection owner
files. Plugin was Black-formatted after RED receipts; no post-format behavioral
run claimed. Full integration/make test deferred as instructed.

## Context/routing audit

Python/Textual composed Pilot investigation with Faux session boundary, not an
editor redesign or provider/SQL/CLI change. Consulted supplied AGENTS/CLAUDE/docs
RESEARCH, root RESEARCH, harness and isolation code; vendored engineering routing,
ownership/testing, code-test-loop, Python root/declarative, Textual, Faux testing
and workflow SKILL. Consulted KB Welcome and slo gotchas; attempted slo/index.md
which does not exist (Welcome points to slo/README.md). Broad combined reads were
truncated; remaining broad coding/docstring guidance was not fully reread into
context. This is not a claim of completed convention review or independent
approval. KB and shared status were not changed under the output restriction.

**Verdict: INCOMPLETE.** New causal progress is the captured override sequence and
two controlled RED executions. The correct test framework completion fence,
causal GREEN repeats, and complete unchanged multi-frame selection proof remain
outstanding. No READY or resolved gate claim.
