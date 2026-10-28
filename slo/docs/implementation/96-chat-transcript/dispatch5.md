# Dispatch 5 — production cutover landed, INCOMPLETE

Turn 1 dispatch 5/20; max60 turns, no retries, agents, commits or pushes.

## Actual running path

SloTUI now composes one ChatTranscript, hydrates before subscription, routes parent events/user/steering/notices to it, closes after unsubscribe, and binds replacement history before session assignment. Queue/input/focus/clipboard/tree export/workflow decisions remain app-owned. SessionFactory and shared attached/detached visualizer injection are present. Old app transcript mechanics/constants/state are deleted. Old adapter files were physically deleted; workflow progress lives at the prepared component package path but still borrows SloTUI. Canonical projector renamed TranscriptProjectionAdapter with no alias; dormant pane manager imports migrated. Transcript CSS removed from app.tcss.

Frozen FollowSnapshotDAO and exact Rendered source/snapshot transport replace duck typing in both stream widgets. Component implements retained common-coordinate reading anchors, generation-bound callbacks, revision/sequence pins, translated native vertical inputs using Textual's engine, completion settlement, hidden/show restoration, explicit bottom intent and mutation capture/finish. This is implemented, not complete race-matrix evidence. Temporary old-app callback wiring was removed with cutover.

Test observations migrated broadly to the mounted component. Removed eight tests of deleted private helpers (three slice arithmetic, two fetch helpers, read-error helper, mocked single-flight helper, app run_worker handler); their behavior is covered by existing component real-history/read-failure/single-flight/window tests, but coverage reconciliation still needs review. Other affected tests now snapshot logical lines before teardown: close intentionally clears them. No production aliases added for tests.

## Evidence

All pytest commands cwd application root, environment VIRTUAL_ENV=/root/.pyenv/versions/slo-harness, its bin first on PATH, SLO_ENV=test SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0, PYTHONPATH=$PWD, `poetry run pytest -q` (some --tb=short). Normal default marker applies.

- dispatch5-follow-red.log: 1 failed/27 deselected, missing final bottom paint. Initial follow-green-named log ALSO FAILED; filename is not verdict. Subsequent /tmp/f96-follow.log passed after allowing two layout refreshes; no rescue delta.
- dispatch5-focused.log: component + answer/thinking + old production scroll tests: 46 passed, 22 warnings, 31.11s.
- dispatch5-cutover-red.log: new real app journey fails before composition change.
- dispatch5-cutover-green.log: real production app/persisted turn/clear journey 1 passed, 28 deselected, 3 warnings, 1.80s.
- dispatch5-core.log: component, projector, pane manager, archive resources: 107 passed, 23 warnings, 35.94s.
- dispatch5-app-results.log: initial migration 16 failed, 156 passed. Failures subsequently migrated; no ignored failures.
- dispatch5-app-final.log: app/replay/scroll/adapters 3 failed, 179 passed, 186.84s. App file was green; remaining replay post-close observations and scroll callable reference subsequently corrected.
- dispatch5-boundaries.log: 2 failed, 192 passed, 91.83s; subagent post-close observations subsequently corrected.
- dispatch5-integration.log: 1 failed, 97 passed, 97.37s; child-abort post-close foreground comparison subsequently corrected.
- dispatch5-final-focused.log: component/adapters/replay/scroll/child-abort integration: **53 passed, 25 warnings, 55.63s, exit 0** after corrections.
- dispatch5-black.log: 12 changed core/component/widget/test files unchanged, exit 0. Not all migrated tests formatted yet.
- dispatch5-static-full.log: `poetry run mypy src/ tests/`, **653 errors in 76 files**, exit 1. Many newly migrated tests dereference optional `_chat_transcript` without narrowing; not waived. Earlier scoped app mypy after guards has no app errors but imported baseline errors remain.
- git diff --check: exit 0.

No full default suite: feature genuinely unfinished, per requested final-only gate timing. No manual smoke or independent review.

## Finite remaining work

1. Complete viewport correctness and evidence: precise callback identity/capture-order tests for both widgets; final warning/layout mutation capture (mark_aborted/mark_failed mutate warning before flush); thinking expansion callback; hidden/no-geometry and geometry-not-ready; exact native destination/growth-above/below, supersession/two-axis/x-only/hide/clear matrix. Current cancellation stops both axes without recording whether x was requested; x-only base _scroll_to stops y, needs spec-aligned handling. Native admission needs stronger hidden/detached guard before revision changes. Initial partial hydration retry can duplicate prefix; resolve specified failure policy.
2. Complete lifecycle subscriber backpressure/repeated cancellation/post-snapshot notice and partial replay active-tool/mixed-content/empty sentinel matrix. Existing real-reader/direct projection evidence retained, not a substitute for subscriber proof.
3. Finish integration tests for injected SessionFactory and BOTH launcher routes, visibility modal focus, replay-before-subscribe; audit uncomposed guards and lifecycle error handling. Production path is wired, not deferred to another task.
4. Finish affected test migration/type narrowing; run remaining affected integration suites (OpenRouter/feature89 etc.) and all TUI affected tests. Address 653-error static gate honestly, separating reproduced baseline from introduced errors. Check changed test formatting.
5. Update stale documentation completely (AGENTS currently has an accurate cutover banner but old owner map remains), RESEARCH and durable KB if warranted. Full default pytest exactly once only after actual completion, no extra exclusions; final static/resource/diff gates. Parent retains independent final review/completion.

No environment blocker established. This is unfinished acceptance and implementation detail, not READY. Do not revert intentional baseline or cutover to preserve obsolete private tests.
