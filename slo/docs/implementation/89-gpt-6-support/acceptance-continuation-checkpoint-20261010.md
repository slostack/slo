# Feature 89 acceptance continuation — REVISE

Inline Code+Test only. Branch/HEAD verified as feature-gpt_6_support / ea8601c53f04fa06a0baeeb47d385c44cc9a5364. No production changes, installs, nested agents, commits or external actions. Existing dirty work retained. This is a bounded checkpoint, not functional closure or independent review.

## Exact files changed this dispatch

- tests/agents/model_catalog/test_backend_eligibility.py: distinct synthetic denied seed merged with cached True remains False; OAuth raises and API key remains allowed.
- tests/tui/test_feature89_presentation.py: distinct denied row retains unavailable text while all three GPT-6 rows retain neutral subscription status. Row reads forbid credential I/O. First attempt lacked lifecycle status initialization and failed; corrected fixture uses the public authentication refresh boundary.
- tests/integration/test_feature89_model_flows.py: existing headless real SDK tool flows now assert omitted session reasoning emits medium/auto on every direct request, and scan every noncredential history file for JWT, refresh-token, account, OpenAI-key and gateway-key sentinels.
- tests/agents/slo_agent/test_feature89_selection.py: six selection/refresh cells use distinct old/new JWTs and public invoke; actual SDK Authorization bears the new JWT, successful completion releases the lock. Four additional public invoke failures cover provider-refresh exception/cancellation, malformed JWT and missing account claim, preserving credential bytes and lazy state and releasing the public lock.

The refresh provider result remains injected: actual refresh HTTP serialization is NOT proved. An attempted omitted raw-factory argument extension was reverted: the raw factory retains its existing default, whereas fresh public session composition supplies medium. The retained acceptance-omitted-medium receipt is a rejected test-design attempt, not an outstanding runtime regression.

## Executed incremental receipts

All under .f89-evidence, with command/log/exit files:

- acceptance-negative-merge: 36 passed, 2 warnings.
- acceptance-negative-picker: 1 failed, 49 passed (fixture omitted lifecycle status).
- acceptance-negative-picker-green: 50 passed, 2 warnings.
- acceptance-headless-medium-scan: 8 passed, 27 deselected, 18 warnings.
- acceptance-warning-isolation: 92 passed, 73 warnings with RuntimeWarning promoted to error; selection plus entry-path and model-flow modules. No AsyncMock warning reproduced. This does not attribute delayed full-suite garbage-collection warnings or prove baseline provenance.
- acceptance-distinct-refresh-wire: 37 passed, 10 warnings.
- acceptance-refresh-failures: 41 passed, 10 warnings.

## All fifteen ACs — incremental status against prior checkpoint

| AC | Current evidence / remaining qualification |
|---|---|
| 1 | Prior exact seed/opposite-False matrix plus new distinct synthetic opposite-True denied merge. |
| 2 | Prior 84 two-lane tool cycles plus real public headless omitted-medium wire assertions for all three models/both lanes. |
| 3 | Prior tool IDs, echo and mounted/resume matrix retained; headless assertions strengthened. |
| 4 | Prior protected Platform policy and OAuth constructor separation retained unchanged. |
| 5 | Distinct refreshed bearer through public invoke added; failure/cancel/malformed/account byte-preservation and lock cleanup added. Actual refresh HTTP, no-op/no-refresh-token and primary/secondary pool refresh acceptance remain open. |
| 6 | Prior entry composition retained; explicit/default/preference/child OAuth-specific composition remains open. |
| 7 | New distinct synthetic picker negative; existing both-size paint/keyboard and cache tests retained. |
| 8 | Frozen controls, snapshot and independent flags unchanged. |
| 9 | Prior dual-lane compaction/context tests unchanged. |
| 10 | OAuth committed-output failure/cancellation expansion remains open. |
| 11 | Existing frozen-reader compatibility tests retained; consult fresh full gate when available. |
| 12 | Required fresh full/static gates must be read from actual receipts, not inferred; baseline failures remain unwaived. |
| 13 | Jev null semantics untouched. |
| 14 | Prior separate-transport both-direction Codex/Jev fallback retained. |
| 15 | Headless public/history sentinel scope expanded. Complete new OAuth artifact scan, including remaining flows, is still open. |

## Remaining finite work

1. Refresh transport serialization with distinct old/new synthetic JWT, no-op/fresh/no-expiry/no-refresh-token paths, primary/secondary pool refresh through public invoke.
2. OAuth explicit/default/preference/child entry composition (avoid repeating auth-independent parser branches without discriminating assertions).
3. OAuth committed-output failure/cancellation composed paths and complete credential sentinel scans.
4. Attribute prior full-suite unawaited AsyncMock warnings with allocation evidence; focused clean run alone is insufficient.
5. Final full non-E2E, changed/full Black, exact fresh frozen mypy comparison, diff and binary integrity after final edits. Retain baseline Black13/mypy296-in59 as UNWAIVED until actual new comparison is read.

Independent kimi-k3/max review and unassigned fresh assessment remain pending. No feature approval, release readiness, paid inference or live entitlement claim. Shared KB edits omitted under the user's restricted artifact scope.
