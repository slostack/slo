# Feature89 continuation6 — NOT READY

Step1 only; HIGH plan retained. Same dirty feature-gpt_6_support at ea8601c53f04fa06a0baeeb47d385c44cc9a5364. Only tests/integration/test_feature89_model_flows.py changed by this continuation, besides local evidence/reports. No production edits, agents, installs, external actions, commits, real inference/state, terminals or shared KB/spec edits.

## Executed evidence and important failure

Six direct mounted flows now dispatch actual mounted app /model from gpt-5.4/high, then /reasoning off/medium through the real router. They assert flat echo encoding, exact persisted user/assistant content, call_89 identity, args/result, tree parent linkage and canonical run model. Fresh-session resume remains same-process, not CLI/subprocess acceptance.

Added real authenticated Jev preparation using existing jev_transport: literal full fixture, pinned clock, real GET client/resolver/store/converter. Mounted /model and /reasoning, real EchoTool and SDK fragmented Chat Completions SSE, fresh-session third request, private anchor same-route replay pass. Exact cap is max_completion_tokens=4096 on locked SDK wire. An initial max_tokens assertion was a FIXTURE error, not production red. Broader public-channel sentinel scan/re-admission spy and exact full Jev history assertions remain to strengthen.

Both real prepared mixed-pool orders complete tools after first-lane HTTP429. Existing OpenAI SDK retries remain: four failing HTTP attempts precede fallback, versus one for OpenRouter. Initial test mistakenly allowed only one OpenAI request (fixture error); production retry settings were not changed. Both headers/URLs are asserted but separate provider transport objects and stronger tool/usage assertions remain unfinished.

**Unresolved discriminating production/contract conflict:** committed Luna content delta -> httpx.ReadError records run_failed with partial_output_committed=true and automatic replay disabled, then existing session continuation submits a new prompt beginning `Continuation attempt 2/5`. This triggers the test's second-request assertion and subsequent SDK/recovery requests (13 captured total). Jev committed case is terminal and passes. Actual pre-feature HEAD contains `_derive_stream_continuation_attempt_plan` (git show HEAD:slo/src/agents/slo_agent/sessions/service.py), so do NOT claim this was introduced by Feature89. Spec requires no other-lane inference/no raw replay while also preserving existing recovery policy. Determine whether acceptance should target the pool/agent boundary or distinguish the existing semantic continuation before changing production. The current strict session zero-additional-request assertion is retained red, not skipped/xfail. Broad pytest.raises(Exception) needs tightening to the actual terminal exception once this boundary is resolved.

Mounted tests also had a real FIXTURE synchronization defect inherited from continuation5: workers.wait_for_complete does not await app._in_flight_task (ordinary asyncio task). Larger runs produced missing answer assertions. Corrected to await the actual owned task; all seven mounted cases now pass in the affected partition without sleeps or weakened assertions.

## Commands/results

All pytest invocations: `bash .f89-evidence/run-test.sh <prefix> -q <paths>`. Exact expanded executable/arguments, combined output and exits are retained in `<prefix>.command/.log/.exit`. Existing env-i runner/tests.env only, preimport isolated HOME/SLO_HOME/TMPDIR. Every bash timeout1800. Intended parent10800/child7200 not exercised or runtime-verified.

| Prefix | Result |
|---|---|
| continuation6-mounted-router |6 passed20 warnings exit0|
| continuation6-direct-surrounding |482 passed43 warnings exit0|
| continuation6-jev-first |7 passed22 warnings exit0|
| continuation6-jev-resume |1 fixture failure20 passed exit1 (wrong cap spelling)|
| continuation6-jev-green |21 passed23 warnings exit0|
| continuation6-pool-first |2 fixture failures7 passed exit1 (invoke prompt vs text)|
| continuation6-pool-green |1 fixture failure17 passed exit1 (SDK retries)|
| continuation6-pool-retries |18 passed27 warnings exit0|
| continuation6-committed-first |1 failed10 passed32 warnings exit1|
| continuation6-final-affected |8 failed502 passed34 warnings exit1 (committed + task-wait fixture)|
| continuation6-final-isolated |4 failed7 passed23 warnings exit1 (same boundaries)|
| continuation6-final-task-wait |**1 failed509 passed55 warnings exit1**|

Final affected command paths: tests/integration/test_feature89_model_flows.py tests/agents/providers/test_pool_fallback_integration.py tests/agents/providers/test_openrouter_transport.py tests/agents/providers/test_openai_platform.py tests/agents/model_catalog/test_feature89_jev_lifecycle.py tests/tui/test_slash_router.py.

Static runner continuation6-static.py and final stdout continuation6-static-final.log: existing locked executable .f89-evidence/venv/bin/python; OpenAI2.38.0/Pydantic2.13.4/LangChain OpenAI0.3.35/core0.3.86/httpx0.28.1/Textual8.2.8. Final changed-file Black1 unchanged exit0. Mypy296errors59files665checked exit1; one newly authored dict-inference diagnostic corrected. Exact multiplicity baseline comparison not rerun this turn; count and absence of changed-file diagnostics verified only. Canonical Black14 prior baseline remains RED/UNWAIVED; no waiver. git diff --check exit0. dpkg -V coreutils empty exit0, continuation6-integrity.log/.exit. No command-stub suite/full gate executed; containment inspection still pending.

## All15 AC residuals

1. Retained seed/unit proofs; four-route disk composition residual.
2. Retained21 reasoning/SDK matrix; complete frozen legacy resolution residual.
3. Six mounted direct router/tool/history/resume strengthened and passing; CLI resume separate.
4. Prior merge/positive tests retained; finite residual audit unchanged.
5. Prior atomic/credential proofs retained; mixed integration now successful but finite guards still audit.
6. Fresh/saved/default/child/CLI resume precedence pending.
7. Prior two-size paint retained; no new compositor acceptance here.
8. Prior A/B snapshot proofs retained; broader lifecycle residual unchanged.
9. Summary reserved cap/total-context/advisory composed tests pending.
10. Both fallback directions execute; committed Luna contract conflict above; cancellation/watchdog surrounding gate not run.
11. Frozen schema2 retained; released coexistence/observer pending.
12. Latest affected RED1/509; static baseline red unwaived; full unrun.
13. Jev actual prepared mounted null-cap wire now passes; prior converter/lifecycle retained.
14. Jev tools/private replay and two pool orders added; stronger formats/usage/public sentinels and committed boundary unfinished.
15. Jev fresh-session prepared resume passes; headless/child/CLI/cross-entry residuals remain.

## Exact next operation

Read `_derive_stream_continuation_attempt_plan`, `_is_stream_continuation_eligible` and the finite e.1 committed-error text together; isolate pool/agent vs session semantic-continuation evidence. Do not disable baseline continuation or add model-specific recovery. Resolve/tighten the retained failing committed Luna test at the correct contract boundary (ask operator if policy interpretation changes product behavior). Then strengthen pool request2 tool format/IDs, routed usage and per-provider transports/public sentinels, Jev exact history/re-admission evidence; run watchdog/cancellation surrounding tests. Continue remaining e.1 headless/child/compaction/compatibility; full nonE2E only after functional completeness. No review until Step1 gates ready.

## Discovery qualification

Read the full safety contract; specific current user prohibition overrides its detached execution instructions. Used project instructions in context, current checkpoints, installed formal workflow and always-on Python/TUI conventions, KB Welcome/slo README/gotchas. Seven specs were opened in aggregate; truncated a/b/c were subsequently read individually. Root RESEARCH aggregate output was truncated; prior checkpoint context retained. This turn did not independently redo full user-override catalog enumeration or all87 dependency comparisons; no claim of a new complete discovery audit. These qualifications must not be reported as fully satisfied process gates.
