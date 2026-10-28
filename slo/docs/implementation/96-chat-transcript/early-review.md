# Feature 96 — bounded early integration review

**Advisory READY — continue Task 01; not Task 01 completion or feature acceptance.**

2026-10-26 · Code-Test-Review turn 1, dispatch 2/20; task limit 60 turns; no retries or child dispatches. Independent inspection of the first runnable milestone described in `handoff.md`. No tests, application launches, package builds, implementation edits or commits performed. This review writes only this report.

## Scope and authority

Compared the new `src/tui/components/chat_transcript/` package and `tests/tui/test_chat_transcript.py` with the original spec family at `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/tui-refactor-side-quest/`: `request.md`, overview, engineering acceptance/ownership/lifecycle contracts and task boundaries. Current authorization overrides the historical headless/harness instructions. Retain the handoff's recorded precedence: explicit old-app follow wiring during Task 02; no invented Task 04 deferral.

Applied actual installed engineering routing/ownership/review/testing, Python conventions/review rules, Textual build guidance, test-verification policy and the named Code-Test-Review workflow. Consulted project instructions, RESEARCH and KB entry/index/gotchas. Scope is Python/Textual presentation and real temporary-file pytest journeys, not CLI/backend redesign.

## Milestone checklist

| Stated behavior | Inspection / existing evidence | Assessment |
|---|---|---|
| Retained scroll/content; reader-only dependency | `component.py:39–80`: retained widgets, `DEFAULT_CSS` resource, injected reader; no session invocation, subscription, abort or storage writer | Implemented at the component boundary |
| Newest 30 entries; successful hydration idempotent/read-only | `component.py:99–106`; first test seeds 32 real session entries, checks the retained user/answer sequences and byte-identical `events.jsonl` after two hydrations | Suitable first-slice proof; not the complete 65-entry journey |
| Parent projection and accepted user echo | `component.py:108–136` delegates to the existing `TranscriptProjector`; first test drives a real Faux session, checks live content, painted final answer and persisted prompt/answer counts | Wired in the component test, **not production** |
| Initial reader failure keeps surface usable | `component.py:82–97`; second test injects an `OSError` reader then paints a user echo | Appropriate bounded failure test |
| Local adapters and CSS ownership | Type-only owner imports; docstring-only initializers; fresh registration and append-order recording; workflow notice delegates to public admission; scoped `css.tcss` | Implementation present; dedicated new-adapter/style assertions remain pending |
| Old app alone remains active | `src/tui/app.py:557–583,620–631,3104–3177` still composes its own scroll, hydrates before subscribing and projects through its own host | Intentional Task 01 boundary, not accidental missing wiring |

Read existing receipts: `task01-final.log` reports **2 passed / 19 warnings / 3.05s**; `task01-focused.log` reports **82 passed / 19 warnings / 16.14s**. These are author-run receipts, not tests executed by this reviewer. The test directly iterates `session.invoke`; it does not exercise production subscription or PromptInput. Its explicit `scroll_end()` before the paint assertion does not prove automatic following. `test_transcript_adapter.py` still imports the **old app-bound adapters**, so its passing cases do not prove the new adapters' contracts. The handoff already correctly limits these claims.

## Planned remainder and closure conditions

These are concrete unfinished obligations, **not blockers to this first-slice checkpoint**. Do not promote the current component to production before closing them.

| ID / priority | Source and risk | Closure condition / owner |
|---|---|---|
| ER01 — high | Engineering §8.1 / AC06; `component.py:65–97,138–150`. `close()` sets `_closed` outside lifecycle admission and joins only the reader. A cancellation-suppressing reader can return entries to hydration, which does not recheck closure before publication. Close also does not join an already-running projection. No lifecycle race tests exist yet. | Task 01: implement the prescribed lifecycle/generation publication and cleanup protocol, not merely another boolean guard. Controlled real-store readers must prove no repaint after close/clear/bind and backpressured, non-dropped live delivery. Include close during awaited projection and cancellation settlement. Already explicitly listed in the handoff. |
| ER02 — high | AC01/04/06; `_load_older_cursor` is assigned but unused. No older-loading, summary or 500/10 window owner exists. | Task 01: stable prepend and cursor accounting with 65 entries (30 + 30 + 5), concurrent tail notice, partial-projection failure, protected live/tail widgets and non-reentrant window convergence. Preserve tree exclusion and unbounded logical-log semantics. |
| ER03 — high | AC05/07; `component.py:159–180` constructs unchanged streaming widgets; `assistant_stream_block.py:258–279` still discovers app bottom state. The new surface has no native navigation/follow/visibility owner. | Tasks 01/02: finish component authority and explicit immutable callbacks; preserve active old-app following during transition. Verify actual native inputs, final growth without a rescue delta, stale callbacks and hidden reading anchors through existing Pilot/compositor tests. |
| ER04 — medium | AC12/13; new adapters/CSS are only incidentally exercised. Explicit component resource inclusion is absent from `pyproject.toml`; no archive proof is supplied. Workflow-progress relocation remains undone. | Task 01: mounted adapter isolation/record/before/notice assertions, fresh-process import orders, both themes at required sizes with sibling non-leak checks, wheel/sdist/extracted-resource proof. Relocate progress physically without transferring its app ownership. Use existing pytest infrastructure, no new harness. |
| ER05 — high at cutover | AC02/03/08–11/13; production remains on `app.py`, including steering, expansion, clear/new/queue, copy, tree and child/workflow filtering. Reusing the projector alone does not migrate these behaviors. | Task 03 after Tasks 01/02: route each production caller once, rename the existing projector, remove old ownership/aliases and migrate affected app journeys. Prove hydration-before-subscription, single persistence, queue outside transcript, tree sibling survival and workflow/clipboard independence. |

## Decision

**No concrete blocker to continuing this bounded milestone.** The dependency direction is sound: component owns presentation, session owns execution/persistence, app retains subscription and child/workflow routing. The next increment should prioritize ER01 and older publication before adding more lifecycle-dependent behavior. Keep Task 01 open; no AC01–AC13 is fully closed here. Full-suite/static/package/final independent acceptance gates remain future obligations, not failed or waived early-review gates.
