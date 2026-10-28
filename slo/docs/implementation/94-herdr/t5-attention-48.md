# T5 operation/attention continuation 48 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 48, retries 0. Unlimited turns AND dispatches; no agents dispatched. Capture/publication READY47 and lifetime READY40 remain historical prerequisite receipts, not proof that the current combined worktree is green.

## Changes and finite branch ledger

Only session service and `herdr/test_session_attention.py` were changed in Python during this continuation. No app/headless/scheduler/viewer wiring. No git lifecycle, global/live, specification or other-worktree edits.

| Family | Current evidence / remaining work |
|---|---|
| Token/precedence/closing | Retained 47 tests; matching clear, independent work, stale end, suspension and closing suppression |
| Tracked startup | Added `_startup_reporting_scope` around actual locked preparation, extracted unchanged adoption body into `_prepare_startup_locked`; success clears captured preparation attention only; exception fixed reason; cancellation retires; stale config does not adopt. New tests pass, but existing stale-publication contract FAILS (below). |
| Readiness rejection | Nonready invoke publishes preparation reason without allocating operation; active run preserves existing attention/working. Existing exception ordering preserved. |
| Manual terminal matrix | Returned failed result now sets fixed failure; final usage refresh runs before token retirement, including escaping error/cancel. 16 status/fault combinations pass; complete actual persisted compaction failure/cancellation and busy-refusal composition still needed. |
| Auth boundary | Existing lazy OpenAI eligibility and provider credential require use `_require_reporting_credential`, with no additional lookup; ValueError sets fixed authentication reason and rethrows original object. Outer scope preserves auth over generic terminal failure. Selection and OpenRouter preparation/auth race/error branches require further audit. No modal caller wiring. |
| Route observation | One internal subscriber; ignores child lifecycle/tagged events, deltas and tool partials; normalized parent boundary compares routed model with usage snapshot, rebuilds without committing invented usage; catches optional faults. Ten cases pass. Actual pool-route composition and explicit forbidden-I/O/fault coverage still needed. |
| Real tools and usage | New real config-backed Faux factory + actual echo tool + final no-tool response, crossed with persistent auth and reporter failure. FAILS: terminal totals 23 instead of 35. No expectation relaxed. |
| Retry/recovery/cooldown | Actual composed continuity, passive cooldown no attention, cancellation/abort and busy-refusal matrices remain pending. |
| Final gates | Full make test/smoke deferred because family is not ready. Fresh lint remains identical unwaived baseline. |

## Exact open failures

1. `test_real_faux_tool_submission_keeps_working_and_commits_totals` all four cases: `assert session.usage_snapshot().session_totals.total_tokens == 35`, actual 23. Two scripted responses carry 12 and 23 tokens. Session currently commits only the last observed capture at final refresh when no UI refresh runs between iterations. Investigate existing agent `usage_capture_version`/`last_usage_totals`, actual session event and trace timing before selecting the correct commit boundary. Do not invent usage or weaken to 23; do not change agent/provider behavior outside ownership.
2. Existing `test_stale_startup_never_publishes[success,failure,cancel]`: expected no `_publish_herdr_snapshot` calls, actual three. New startup operation begin/final refresh/end publish while adoption remains refused. Reconcile operation projection with stale capture prohibition using actual public capture/state assertions, preserving original no-stale-adoption guarantee. Do not simply delete assertion. Current combined worktree is NOT regression-free.

## Commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. `pyenv which python`: `/root/.pyenv/versions/slo-harness/bin/python`; Poetry Python 3.11.7, no venv creation. All pytest runs use `bash docs/implementation/94-herdr/t1-dao-check.sh <paths>` (includes DAO/projection tests and safe environment).

Logs under this directory; test exit values below are printed immediately after each invocation; final runs additionally have `.exit` files.

- `t5-attention-48-preparation-red.log`: attention file, **5 failed, 70 passed**, exit 1. GREEN `preparation-green.log`: attention + publication + pending-direct-recovery + session/usage/rate/manual-compaction + tests/auth, **513 passed**, exit 0.
- `t5-attention-48-manual-red.log`: attention, **16 failed, 75 passed**, exit 1. GREEN `manual-green.log`: attention + session/usage/rate/manual-compaction + tests/auth, **504 passed**, exit 0.
- `t5-attention-48-route-red.log`: attention, **4 failed, 97 passed**, exit 1. First `route-green.log`: **4 failed, 510 passed** (invalid test route gpt-5.4-mini caused rebuild failure/repeat). Corrected fixture uses catalog-known claude-sonnet-4-6; `route-green2.log`: **514 passed**, exit 0, same surrounding paths as manual GREEN.
- `t5-attention-48-auth-red.log`: attention, **1 failed, 101 passed**, exit 1. First `auth-green.log`: **1 failed, 514 passed**, missing earlier OpenAI eligibility require hook. Corrected `auth-green2.log`: **515 passed**, exit 0; same surrounding paths.
- `t5-attention-48-composed.log`: four fixture errors (subscribe requires keyword handler); `composed2.log`: four fixture errors (usage_snapshot is a method). These are not production RED. Corrected real assertions expose usage failure in following runs.
- `t5-attention-48-surrounding.log`: entire herdr package + session/usage/rate/manual-compaction + tests/auth, **7 failed, 1667 passed, 34 warnings**, exit 1.
- Final post-format `t5-attention-48-final.log/.exit`: attention + publication_isolation, **7 failed, 120 passed, 20 warnings**, exit 1; exact seven failures above.
- Black formatted only service/attention test; `t5-attention-48-black.log`: both unchanged, exit 0.
- `git diff --check`, `dpkg -V coreutils`: silent, exit 0, repeated after final test/static run. Initial receipt files `t5-attention-48-diff-check.log`, `t5-attention-48-coreutils.log` are empty.
- First lint `t5-attention-48-lint.log`: **302/64**, three new test Optional narrowing errors. Added explicit non-None assertions; `t5-attention-48-lint-final.log/.exit`: **299 errors/63 files**, make exit 2. Exact Counter comparison of `: error:` lines with line numbers normalized against `t5-publication-47-lint.log`: ADDED [], REMOVED []. Baseline remains unwaived.

## Read closure limitations

Read handoff47 and actual attention/session preparation/run/manual/usage/auth/dispatch code, publication composition and stale-startup tests; current routing/scope/status; KB Welcome, slo README/gotchas; engineering routing/ownership/testing, coding rules/cadence/declarative, Python root/domain/application/declarative and portions of agent-test/workflow skills; canonical C attention requirements/7.10/section8 and tasks 2401–2600. Existing AGENTS/CLAUDE/docs RESEARCH were supplied in context; root files were inspected via shell but not all content returned. Several combined reads were truncated. Full requested normative/build-rule read closure (including tasks through 3720, accepted review and B) is NOT claimed. Complete it before technical READY.

Safety: inherited isolation/disabled/terminal guards retained; no executable fixture or system writes added. Faux/synthetic credential patched before config-backed execution. No real provider/Herdr/window. Full T5, independent review, app/headless/scheduler/viewer caller integration and T6 remain future.
