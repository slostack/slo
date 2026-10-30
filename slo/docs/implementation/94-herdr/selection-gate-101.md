# Selection gate 101 — INCOMPLETE, no causal repair claimed

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 101, retries 0. Effective turns and dispatch budgets unlimited. No agents dispatched. No production edits, app.py edits, commits, pushes, resets, clean/stash, specification, global/live or other-worktree changes. Temporary edits to the authorized selection test were removed by exact replacement; its final git diff is empty. All earlier partial work remains preserved.

## Failure and investigation

Read `t5-gateway-final-100.md`, `t5-init-complete-79.md` and their actual failed logs (`t5-100-test.log:494–553`, `t5-79-test-final.log:478–536`). Both fail the default-theme thinking case at the first requested native offset `(6,0)`, before dragging or asserting paint. The historical logs do not retain viewport geometry or callback order. Isolated/full rerun passes are not a repair.

Current test populates 20 filler lines, mounts the body, populates another 20, pauses 0.1 seconds, requests `block.scroll_visible(animate=False)`, then pauses 1 second. Only user bodies get a second top-aligned reveal. The intended assertions remain exact `bravo` native selection, native selection background and retained selection after scrolling.

Read actual production mount/follow methods and thinking render owner, and installed Textual 8.2.8 implementation:

- Completed thinking renders synchronously through `set_thinking` → `_flush`, then posts `AssistantStreamBlock.Rendered(was_following=...)`.
- App render notification and mount paths can schedule `_pin_transcript_to_end_after_refresh`; that calls `scroll_end`, which itself queues `_lazily_scroll_end` for another refresh. Follow latch clearance is another callback.
- Textual `scroll_visible` computes ancestor geometry and normally defers scroll application. If size is absent it defers the geometry computation too.
- `Pilot.pause(delay=...)` waits for queued screen messages **before** sleeping, then directly invokes the screen update. It does not assert that follow callbacks, virtual geometry and target hit-testing have committed together.
- Screen callback execution copies/clears the current callback list; callbacks scheduled by callbacks belong to a later pass. `batch_update` suppresses layout/paint but does not categorically suppress this callback drain. Thus treating one refresh or an elapsed pause as a full recursive commit barrier is unjustified.

These facts identify an ordering risk but do not establish the exact historical causal sequence.

## Controlled probes (not a fix)

Two batching experiments held either trailing filler construction or the complete test construction/reveal inside `app.batch_update()`. Each passed 76 tests including 62 mandatory foundation cases. Neither provided RED.

A subsequent test-local wrapper held only real `AssistantStreamBlock.Rendered` messages until after the existing reveal/pause boundary, then posted the original messages. No fabricated message payload or production method replacement. Added geometry to the offset failure. The complete final probe diff is preserved at `selection-101-probe.patch` for reproducibility; it is **not applied** to the final test.

- `selection-101-delivery-red.log`: 1 failed, 81 passed. Delayed dark-theme thinking case: `body=Region(x=3, y=-8, width=72, height=1), scroll=36, follow_pending=False`.
- `selection-101-delivery2-red.log`: after adding two additional default `pilot.pause()` calls, 82 passed. Despite its receipt name this is NOT RED or a causal fix.
- `selection-101-delivery-state.log`: same probe plus state prints, 2 failed, 80 passed. Ordinary/non-delayed dark answer failed at body y=-8, scroll=37; delayed dark thinking failed at body y=-8, scroll=36. Delayed messages recorded `was_following=True`. Other cases had body y=2 or 3, scroll=26.

The observed failure is a body above the viewport, not evidence of corrupt compiler offsets or selection background colors. However delay injection did **not** reproduce deterministically and failures also occurred without delayed delivery. Additional pauses did not reliably settle it. No claim that the delayed message is the historical root cause, and no speculative polling/reveal retry was retained.

## Required next evidence / precise remaining work

Capture a failing execution's exact native scroll transaction order and geometry: target virtual region at `scroll_to_widget`, viewport/max-scroll at computed scroll delta, subsequent `_scroll_to`/`_lazily_scroll_end`, and target hit-test. The existing `tests/tui/selection_observer.py` is relevant read-only prior machinery, but its owner capture primarily tracks answer bodies and its allowlist omits thinking-block source; it was not modified or activated here. A bounded test-local instrument can distinguish stale geometry during reveal from an overriding later follow pin.

Then force that **observed** ordering with a framework message/refresh or batch/viewport boundary and obtain repeatable RED. Only then replace the fixture's elapsed wait with the specific render/layout/follow completion prerequisite, issue the native reveal, and assert the exact requested native visible cells before the unchanged drag/paint/scroll assertions. This must not become repeated scrolling until an assertion passes. If evidence instead shows a user-visible production scroll defect, report that concrete defect before touching production; no such change is authorized or justified by this investigation yet.

No conclusion that repair necessarily requires out-of-scope production behavior. The blocker is missing deterministic causal evidence, not an authorization waiver. No READY verdict.

## Commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Verified `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7, Textual 8.2.8. Every pytest command used `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`; no venv created. That harness enables Faux-safe fallback, disables auto visualizer and Herdr, and includes DAO/projection tests. Existing autouse isolation strips inherited Herdr state and guards terminal spawning. No provider inference, real Herdr/windows or system symlinks used.

All receipt names below are prefixed `selection-101-`, with `.log` and `.exit` beside this report:

| Receipt | Harness suffix / command | Result |
|---|---|---|
| batch-red | tests/tui/test_selection_scroll_highlight.py | 76 passed, exit 0; no RED |
| batch2-red | same | 76 passed, exit 0; no RED |
| delivery-red | same, delayed-message variant | 1 failed, 81 passed, exit 1 |
| delivery2-red | same, extra framework pauses | 82 passed, exit 0; not repair |
| delivery-state | same + `-s`, instrumented probe | 2 failed, 80 passed, exit 1 |
| surrounding | restored test; suffix below | 200 passed, 2 warnings, exit 0; not repair |
| black | `PYENV_VERSION=slo-harness poetry run black --check tests/tui/test_selection_scroll_highlight.py` | exit 0 |
| diff | `git diff --check` | silent exit 0 |
| coreutils | `dpkg -V coreutils` | silent exit 0; also silent immediately after each probe |

Surrounding suffix: `tests/tui/test_selection_scroll_highlight.py tests/tui/test_selection_copy.py tests/tui/test_selection_copy_e2e.py tests/tui/test_selection_observer.py tests/tui/test_markdown_content_compiler.py tests/tui/test_user_message_block.py`.

Full `make test` was not run: reserved for integrated lanes as requested; this scoped investigation did not produce a fix to validate. No targeted repeat GREEN causal evidence exists.

## Guidance and scope audit

Supplied AGENTS/CLAUDE/docs RESEARCH context consulted; root RESEARCH and actual Makefile/isolation harness read. Read engineering routing/testing/ownership, code-test-loop, Python root/declarative/named arguments/docstrings, Textual, Faux recipe and workflow SKILL. Shared declarative guidance read in chunks. KB Welcome, slo README and gotchas consulted read-only. Some combined context output truncated; this is not a claim of complete fresh rereading of every broad prerequisite or independent review. Scope is Python/Textual composed Pilot testing, not provider, SQL, CLI or TUI redesign. KB/shared status left unchanged under the user's output restriction.

**Verdict: INCOMPLETE.** A viewport exclusion failure has been observed with concrete geometry; the causal commit barrier and deterministic reproduction remain unresolved. No test weakening or speculative repair remains in the worktree.
