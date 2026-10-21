# T5 attention continuation 49 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 49, retries 0. Unlimited turns and dispatches. No agents dispatched. No workflow acceptance or family READY claim.

## Exact seven failures and causal findings

`t5-attention-49-red.log/.exit`: approved helper with attention and publication-isolation files: **7 failed, 120 passed**, exit 1. Four real config-backed Faux/tool cases expected 35 and got 23; three stale-startup cases rejected calls to `_publish_herdr_snapshot`.

Usage defect is in existing runtime ownership, not a Herdr total. `agent.py` retained only the most recent captured totals; session `_sync_usage_snapshot_commit` added that value only when explicitly refreshed. A multi-iteration run without UI refresh lost the first response. Session now calls its existing commit seam when receiving each agent event, before subscriber dispatch. No Herdr subscriber accumulates tokens; no usage/history/stream event was added.

Further test-first probes exposed two necessary adjacent corrections in the authorized shared owner `src/agents/slo_agent/agent.py`:
- Distinct iterations with equal usage were suppressed by numeric equality. Deduplication now also matches the current iteration; run initialization clears that identity.
- Incremental messages-mode usage was captured as though it were completed usage. Capturing individual chunks plus the completed update overcounted. Messages-mode no longer captures usage; completed updates/finalization remain the capture seams.

These are pre-existing source-path defects, not provider/Faux changes. No clean-baseline execution was performed; baseline attribution is source-based, not an independently executed historical checkout. Partial failed-stream usage, multiple completed assistant messages in one iteration, and eventless completed updates need explicit follow-up coverage before broader accounting closure is claimed.

Stale-startup failures were fixture-boundary assumptions. C7.10 explicitly permits operation publication. Tests now observe actual reporter publications through the production guard: exact working/working/idle sequence; original capture only before replacement; both later publications have no capture and generation exactly +1; no adoption, no false blocked reason, pending preparation preserved and operation retired. Thus no blanket assertion disable or production suppression was introduced.

## Changes and receipts

Python edits limited to agent.py, sessions/service.py and two Herdr tests. No TUI/headless/scheduler/viewer changes, no provider/Faux implementation changes, no spec/global/live/other-worktree/git lifecycle edits. Existing partial changes preserved.

All pytest commands use `bash docs/implementation/94-herdr/t1-dao-check.sh` (which adds DAO/projection tests). Python resolved through approved slo-harness 3.11.7; no venv creation. Logs below are in this directory, each with matching `.exit` unless noted.

| Receipt prefix `t5-attention-49-` | Paths / result |
|---|---|
| red | attention + publication_isolation: 7 failed, 120 passed; exit 1 |
| stale-green | publication_isolation + publication + pending_direct_recovery: 108 passed; exit 0 |
| usage-green | invocation typo `test_session_rate_limit.py`: no tests ran; exit 4; not product evidence |
| usage-green2 | attention + isolation + session_usage + agent + session + session_rate_limits: 299 passed; exit 0 |
| equal-red | attention with equal-usage/refresh-cadence cases: 8 failed, 110 passed; exit 1 |
| equal-green | preceding surrounding partition + cache_control: 321 passed; exit 0 |
| chunks-red | attention with incremental usage chunks: 16 failed, 118 passed; exit 1 |
| chunks-green | same surrounding partition: 337 passed; exit 0 |
| surrounding | entire herdr + session + session_usage + session_rate_limits + session_manual_compaction + agent + tests/auth: 1774 passed, 119 warnings; exit 0 |
| final | post-Black attention + publication_isolation: 155 passed, 76 warnings; exit 0 |
| lint | make lint: 299 errors / 63 files; exit 2; unwaived |

`lint-comparison.log`: normalized exact error-line Counter comparison against t5-publication-47-lint.log: ADDED [], REMOVED []. `black.log/.exit` formats only four changed files, exit 0. `diff-check.log` and `coreutils.log` are silent (both commands exit 0). Agent diff inspected; no broad completion/review claim.

## Finite family map

- Original seven failures: CLOSED by the evidence above.
- Real config-backed factory/graph/local echo/final response: expanded to 32 cases, equal/different totals, per-event/no UI refresh, incremental/default chunks, authentication retained, optional reporter failures. CLOSED for this finite matrix.
- Stale-startup success/failure/cancel: CLOSED for actual publication/capture cutoffs.
- Existing token/preparation/manual orchestration/route-filter tests: retained green in whole Herdr surrounding gate; not substituted for remaining composed flows.
- Manual actual persisted compaction failure/cancellation and busy refusal: OPEN.
- Authentication selection and OpenRouter preparation/race/error audit: OPEN.
- Actual routed pool fallback and explicit route-observer forbidden-I/O/fault proof: OPEN.
- Actual retry/recovery/passive cooldown/abort/cancellation continuity matrix: OPEN.
- Usage failure/partial-stream/eventless completion regression matrix: OPEN after shared-owner correction.
- Complete required normative/build-rule ingestion: OPEN. Several combined tool reads were truncated; prior full-read claims are not inherited as current read closure. Read C7.10 directly and actual usage/agent/Faux/session owners; broader required C/B/tasks/reviews must still be completed.
- Full make test/smoke: NOT RUN because family is not closed, as requested. No fresh full-suite green claimed.

Remaining scope is session attention and substantiated usage owner verification only. Do not advance to app/headless or independent acceptance from this receipt. No capacity or dispatch-budget stop is asserted.
