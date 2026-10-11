# Final dispatch checkpoint — REVISE, not functional closure

Inline Code+Test only on feature-gpt_6_support, HEAD ea8601c53f04fa06a0baeeb47d385c44cc9a5364. Existing dirty work preserved. No production edits, nested agents, installs, live inference, commits or external actions. A provider request-processing error interrupted the turn; continuation recovered without repeating writes. Independent review/self-approval not performed.

## Exact edits this dispatch

- tests/agents/slo_agent/test_feature89_selection.py: extended existing public-invoke selection test with fresh, no-expiry and still-valid near-expiry/no-refresh-token cases. Assert zero refresh, byte-identical credential file and original bearer on real SDK HTTP. Existing refresh cases retained.
- tests/integration/test_feature89_model_flows.py: existing committed-output and cancellation cases now exercise both API-key and OAuth credentials; assert Codex origin/bearer, unchanged semantic continuation versus raw replay, stream/lock cleanup, no fallback, and synthetic JWT/account/refresh/key absence in public events and noncredential history artifacts.
- This checkpoint and subsequent results receipt under docs/implementation/89-gpt-6-support.
- Evidence support files: .f89-evidence/warning_probe.py, run-warning-test.sh, final-dispatch-static.py; command/log/exit receipts and final-dispatch-inventory.txt. Inventory contains the whole dirty worktree, NOT attribution of all changes to this dispatch.

## Executed focused evidence

Every named test receipt has .command/.log/.exit under .f89-evidence.

- final-committed: 8 passed,31 deselected,12 warnings, exit0.
- final-flow-surrounding: 41 passed,79 warnings, exit0.
- final-refresh-noops: 59 passed,28 warnings, exit0.
- final-warning-owners: plugin import failed, exit1; no application tests executed.
- final-warning-owners-retry: 88 passed,11 warnings, exit0. Tracemalloc plus per-test teardown collection attributes nine unawaited AsyncMock coroutines to tests/cli/test_typer_dispatch.py helpers at lines487/532/589: they create AsyncMock invoke, then mock asyncio.run to return0 without consuming its coroutine. Allocation passes through src/cli/typer_dispatch.py:224. Those helpers are unchanged in git diff and exist verbatim in frozen HEAD (final-warning-frozen-owner.txt). This establishes these concrete pre-existing owners, NOT that every full-suite warning has been attributed. No warning suppression or unrelated CLI cleanup applied.

## Fifteen-AC assertion map and qualifications

| AC | Executable assertion owners; remaining qualification |
|---|---|
|1|tests/agents/model_catalog/test_model_catalog_seed.py; test_backend_eligibility.py::test_policy_survives_copy_merge_override_and_alias plus distinct denied cached-True test; exact seeds and no Jev.|
|2|tests/agents/test_feature89_reasoning.py; tests/agents/providers/test_openai_platform.py both-lane streamed/JSON effort matrix; test_feature89_model_flows.py::test_feature89_headless_routes_use_shared_admission omitted-medium wire.|
|3|test_openai_platform.py locked SDK tool cycles and test_feature89_model_flows.py::test_mounted_gpt6_tool_cycle_and_resume (12 cases, real echo, matching IDs, resume).|
|4|test_openai_platform.py protected option constructor/bind/call/extra-body and legacy temperature assertions; production unchanged.|
|5|test_feature89_credentials.py resolver/precedence; test_feature89_selection.py::test_oauth_selection_and_near_expiry_refresh_build and ::test_oauth_public_invoke_failure_preserves_store_and_unlocks. No-op branches now proved. Actual refresh HTTP and primary/secondary pool refresh remain open.|
|6|test_feature89_entry_paths.py::test_feature89_cli_fresh_saved_explicit_precedence, ::test_feature89_child_model_selection, ::test_feature89_cli_pool_resume_and_explicit_model_precedence; mounted OAuth resume retained. OAuth-specific explicit/default/preference/child inference composition remains open.|
|7|tests/tui/test_feature89_presentation.py two-size paint/keyboard, neutral subscription and distinct ineligible row, lifecycle cache tests.|
|8|test_backend_eligibility.py and catalog overrides/cache tests; test_feature89_selection.py::test_sync_switch_and_reasoning_use_session_snapshot; presentation snapshot tests.|
|9|tests/integration/test_feature89_capacity.py both-lane reserved-summary-cap/no-cap transaction, total context/advisory assertions.|
|10|test_feature89_model_flows.py::test_prepared_mixed_pool_tool_fallback, ::test_committed_pool_failure_boundaries and ::test_prepared_pool_cancellation_closes_stream_without_fallback now both lanes. Cancellation test waits before output; no new claim of cancellation after committed output.|
|11|tests/compat/test_feature89_frozen_reader.py and released history/shared-state tests; tests/cli/test_visualize_state_independence.py. Must consult final full receipt.|
|12|Full non-E2E and fresh static comparison required below; baseline static failures remain UNWAIVED.|
|13|tests/agents/model_catalog/test_feature89_jev_lifecycle.py and converter/null metadata tests retained.|
|14|test_feature89_model_flows.py::test_prepared_mixed_pool_tool_fallback separate transport ledgers, both auth lanes/orders; mounted admitted Jev tool/resume.|
|15|headless sentinel scans retained; new committed/cancel public/history scans. Complete remaining OAuth logs/stdout/stderr/error/artifact scan coverage still open; existing membership/rotation/removal proofs retained.|

This is an assertion-owner map, not a completed exact-node audit for all fifteen criteria. Earlier detailed acceptance maps remain applicable; no automatic AC approval follows from passing counts.

## Precise finite remaining work

1. Real refresh serialization: production OAuthProvider.refresh uses aiohttp.ClientSession, NOT httpx. Existing tests/auth/test_oauth_provider_refresh.py owns local aiohttp transport proof. SDK MockTransport cannot alone establish refresh serialization. Compose the real provider serializer/parser with a contained transport seam, distinct old/new JWT, and actual post-refresh SDK bearer; do not claim patched refresh result is HTTP proof.
2. Valid primary/secondary pool refresh through public invoke, with one provider-wide OpenAI credential and no invented per-model lane.
3. OAuth-specific explicit/default/preference/child entry composition with actual SDK wire discriminators, not redundant parser-only assertions.
4. Cancellation after committed output is not covered by the newly expanded pre-output cancellation case; verify the requested boundary explicitly.
5. Remaining sentinel scans across all newly composed OAuth flows (logs, headless channels, errors and noncredential artifacts).
6. Attribute any remaining full-suite AsyncMock allocations beyond the nine concrete CLI owners. No blanket baseline-only assertion is made.
7. Finish an exact node/assertion AC audit; this report intentionally does not represent the remaining partial rows as closed.

## Final gates and successor authority

The intermediate final-dispatch-full passed 6088 tests/18 deselected/330 warnings. The static comparison exposed one introduced test-only type inference error (297 versus baseline296); an explicit typed nested updates map corrects it. Final source/test/support-doc edits precede final-dispatch-corrected-full and final-dispatch-corrected static receipts. Read their actual results from .f89-evidence; no anticipated pass. Final static script freshly extracts real frozen HEAD, compares normalized mypy diagnostics and Black paths, checks all changed Python including untracked files, and records diff/coreutils integrity. Full static failures are UNWAIVED even if identical to baseline. A results-only receipt may follow the gates.

Independent kimi-k3/max review remains pending and must not run before Code+Test gates. Fresh assessment model/reasoning assignment is still unprovided; ask only when that phase is reached. Do not launch another agent from this dispatch, reset caps, install, touch real state, publish, or claim live subscription entitlement. This checkpoint is for the authorized owner successor, not a new autonomous continuation authorization. Restricted notes scope means shared KB/specs were not edited.
