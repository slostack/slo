# Ordinary Slo configured-credential tool-error disclosure — UNWAIVED

## Scope and status

Separate security finding, not a demonstrated Herdr publication leak. No fix, waiver, provider change or global sanitizer was authorized or implemented. Reports 129–131 and their failing receipts remain unchanged. Report 131's attribution to a newly requested stronger public-stream requirement was unsupported and is superseded by the user's explicit contract adjudication.

## Exact bounded reproduction

From `/root/Code/slo-94-herdr-integration/slo`:

```sh
PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/integration/test_herdr_full_flow.py::test_secret_tool_error_preserves_enabled_disabled_event_parity
```

The helper supplies explicit synthetic test fallback, disables real windows/Herdr, and includes 62 foundation cases. Existing root isolation and independently registered temp fake capability remain intact. Python resolves to `/root/.pyenv/versions/slo-harness/bin/python`, 3.11.7. No real provider is called.

The test configures `sk-SYNTHETIC-input-credential-parity-132` as the synthetic OpenAI key and resolver result; the native factory returns Faux. The real graph invokes NowTool, whose controlled boundary raises `RuntimeError('CONTROLLED-TOOL-ERROR ' + secret)`. Actual terminal `tool_result.content` equals `Error: CONTROLLED-TOOL-ERROR ` plus the entire sentinel in BOTH enabled and disabled mounted sessions. Full ordered event streams compare equal under the existing strict SemanticTrace generated-identity normalization. No field/content suppression is added. The Herdr argv contains no sentinel.

Observed isolated result after fixing test authentication setup: **63 passed, 6 warnings, exit 0, 2.80s**. Passing means the reproduction and feature parity are established, NOT that the security defect is fixed. Final combined oracle run also includes this reproduction: **103 passed, 86 warnings, exit 0, 37.31s**.

## Source evidence and impact

- `src/agents/slo_agent/tool_execution/executors.py:123–129`: catches tool exception, calls `log_error` with it, constructs terminal message `content=f"Error: {exc}"`.
- `src/agents/slo_agent/sessions/service.py:5862–5870`: `_dispatch_event` forwards the event to plugins/subscribers without an all-provider sanitizer.
- Report 131 retains unchanged-owner comparisons versus HEAD. This reproduction executes current enabled/disabled paths, not a historical-checkout runtime.

A tool exception containing a configured credential can therefore expose it to ordinary event consumers/transcript. The executor logging call is a further exposure surface requiring separate security review; this test's exact assertion proves event disclosure, not every log sink. Four sentinel labels in the reporting matrix are categories, not four executed provider integrations. All these composed runs use gpt-5.4 with Faux.

Required future security work must explicitly define ordinary Slo public/log/private-history boundaries and actual admitted credential lifetime, rotation and pool ownership. Do not silently make Herdr own it or add credential lookups to publication. The present finding remains open and unwaived, outside this oracle correction.
