# Core contracts165 — R161-3 implemented; R161-4 partial, REVISE

Accounting: Code+Test turn4/global165/current dispatch4; started4/completed0/historical stopped partial1/retries0; effective budgets UNLIMITED. No subagents. No full-feature approval, independent review or Completion. Live DEFERRED; compatibility UNVERIFIED.

Verified branch feature-94-herdr-integration, origin https://gitlab.com/core-27/slo.git, merge base d0e3a756689f2675e5507034d43cd8b272d3c6b8. Existing work preserved; no reset, stash, commit, package, global, other-worktree, specification or live edits. KB read-only; no new external knowledge writes.

## R161-3

Reporter `_close_outcome` now projects only remote/sticky-defect evidence with default resources=drained. Normal physical lease retention no longer invents uncertainty. `close_transport` still checks actual retained resources after sealed transport drain and restore/pane lease cleanup. No early unlock, changed atomic admission section, repeated ambiguous-FD close or erased sticky cleanup failure. Session aggregation now preserves every uncertain outcome instead of ignoring retained intermediate evidence.

RED-first: revised intermediate test fails on replacement safe expectation (1 failed); session aggregation regression fails for retained intermediate uncertainty followed by safe final local evidence (1 failed/1 passed). Both pass after their minimal owner corrections. Added actual fake-CLI activation/withdrawal matrix covers normal/refused/unsafe/sticky-cleanup paths; a competing real lease acquisition must fail between intermediate and final close. Final safe/drained only for normal path. Existing retained-final and 164 ambiguous-close/restore tests remain green.

The additional matrix initially omitted mandatory binding fields (4 validation failures/73 passed); corrected the fixture, not production validation. This is fixture correction, not additional behavioral RED evidence. Full matrix module then 77 passed. Logs retained.

## R161-4 — documentation expanded, exhaustive closure NOT claimed

Expanded Google contracts for reporter construction/build/publication/start/close/final drain/viewer and admission; transport construction/invoke/close/final drain/admission; gate/projector; restore constructor/save/load/close; lease validate/acquire/require-held/close and sequence construction/acquire/reserve/close; viewer construction/invoke/admission; DAO close/resource/save/admission protocols. Documented cancellation joins, deadline versus OS reap, read-only load, immutable records/orphans, retained-owner preconditions, and intermediate versus final evidence. Preserved164 inspection-only ambiguity documentation and corrected store-close overlap error description. Identity docs now describe actual any-version UUID parsing, not UUID4-only; token helper comment names the extracted owner. Context reader already describes read-only tolerant failure behavior; package init is inert documentation only.

Remaining before R161-4 can be declared complete: a systematic final public-API inventory against actual full bodies (including protocol/start, null and small public boundaries) and missing applicable Args/Returns/Raises. This dispatch inspected targeted public bodies but does not claim a complete fresh seven-file body audit. Do not turn the substantial doc additions or passing tests into that missing review evidence.

## Executed evidence

Runner `core-contracts-165-run.sh`, logs/exits/coreutils receipts in `core-contracts-165/`. Explicit VIRTUAL_ENV/PATH/PYENV_VERSION use /root/.pyenv/versions/slo-harness; tracked synthetic fallback, no sourced env file. Root fake-only/window guards unchanged; actual test programs remain fixture-owned. Every runner coreutils receipt silent. No host anomaly observed.

- close-red: 1 failed/72 deselected; close-green:90 passed.
- aggregation-red:1 failed/1 passed/59 deselected; aggregation-green:101 passed (whole session lifetime plus mounted replacement/shutdown/lifecycle).
- Incremental documentation module gates: reporter77, transport38, restore20, lease45, counter49, activation92, viewer31, projection43, protocol90, extraction62, admission169, transport-admission25, viewer-admission31, final-protocol29 — all exit0.
- final-owned-core: **1113 passed,4 warnings,69.87s**, exit0, final production/test bytes. All direct Herdr test_*.py except test_session_*/test_attention_*, plus session identity/token/context-reader tests; same161/164 selection with new cases.
- surrounds: **745 passed,293 warnings,293.92s**, exit0. Herdr session/attention modules, CLI restore/headless_herdr/headless_retained, TUI session_lifecycle/replacement/app_shutdown/init_*/initialization/combined_cutoffs, integration full_flow. This is after final behavioral changes, before later doc-only additions.
- scoped mypy: **83 files clean**, exit0; scoped Black:83 unchanged, exit0 (before final two constructor doc-only additions). Scope: herdr production/tests plus sessions service/identity/token and context_reader.
- git diff --check silent at static checkpoint.

Full make test/smoke/lint are explicitly next dispatch, not run here. Independent core re-review, wiring/harness/static/full-feature review and fresh Completion remain pending. R161-1/2 implementation preserved, not independently approved here.

## Read qualification / handoff

AGENTS first disk read; complete supplied AGENTS/CLAUDE/docs RESEARCH context, root RESEARCH, Makefile,161/163/164 reports, worktree workflow/cadence and routing, ownership/testing/coding/Python/declarative/types/docstrings consumed. Domain DAO/application recipe aggregate output truncated; no complete reread claim. Canonical B7.9 exact intermediate/final definition, B19/B20 and C23 close aggregation prose read; old83 workaround is not authority. KB Welcome/slo README/gotchas consulted. Routing/scope aggregate partly truncated. Remaining full prerequisite/audit reads must be completed before claiming the exhaustive R161-4 closure.

No numeric workflow stop or budget exhaustion is asserted. This is a partial author handoff with explicit remaining work, not READY for the combined R161-3/4 assignment.
