# Owner C — provider and compaction corrective evidence — 2026-10-03

## Verdict

**REVISE — bounded Owner C corrections are implemented and locally verified; Feature 86 is not declared complete.** This report covers only the assigned provider/compaction corrective slice. It does not claim a full non-E2E gate, live-provider availability, paid inference, or completion of other owners' findings.

## Scope and safety

Allowed implementation owners changed:

- `src/agents/providers/openrouter.py`
- `src/agents/slo_agent/compaction/compacter.py`
- `src/agents/providers/model_pool.py` — indispensably changed and announced here: ModelPool remains the sole selector/fallback owner, but invokes the selected member's existing request-owner cap method for a compacter-marked summary request.
- `src/agents/model_catalog/openrouter.py` — reasoning truth-table correction required by the task.

Matching focused provider, converter, pool, and compaction tests were changed. Existing dirty/untracked work was preserved. No Git-mutating operation, install, network call, live credential, paid provider call, system/PATH mutation, specification edit, or non-test-owned filesystem write was performed. Every pytest run used `/root/.pyenv/versions/slo-harness/bin/python -B`, `httpx.MockTransport`, `-p no:cacheprovider`, an isolated environment, and a fresh checkout-owned `--basetemp` root.

## Corrective implementation

### 1. Pinned summary output caps

`Compacter._invoke_llm_summary()` retains the direct-route cap calculation from the admitted snapshot. Its pool request now carries only an internal `_slo_compaction_summary` marker. ModelPool still selects/retries/falls back exactly as before; after selecting each concrete lane it removes the marker and asks that selected adapter to cap the summary kwargs.

`OpenRouterChatOpenAI.cap_compaction_summary_kwargs()` caps only this marked internal request against its own `slo_output_ceiling`. This prevents a smaller OpenRouter fallback member from receiving the initial member's larger output budget. Ordinary explicit caller validation remains in `OpenRouterRequestPolicy.validate_output_cap`; no caller cap was silently relaxed and no alternate routing architecture was added.

Evidence added/retained:

- Direct prepared 3000-token ceiling remains capped at 3000.
- A real local SDK MockTransport request for an absent remote ceiling sends `max_completion_tokens: 4096` (LangChain wire spelling), returns `summary`, and does not contact a provider.
- A primary 3000-cap pool member fails before output; its 500-cap fallback receives `max_tokens: 500`.
- The one Compacter seam continues to serve manual, automatic, and overflow callers; no duplicate summary invocation path was added.

### 2. Visible reasoning continuation

The adapter retains its detached outbound assistant projection. Tests now prove actual SDK second requests for both streamed raw reasoning + tool calls and nonstream raw reasoning + tool calls:

- display-only `type="reasoning"` content is absent from the outbound assistant message;
- ordinary assistant plaintext and tool calls remain;
- same-route `reasoning_details` remain;
- the source `AIMessage.content` is unchanged after the request;
- the tool result remains in its normal wire message.

The existing outbound modality validator therefore remains strict: user/tool arbitrary reasoning and unsupported image blocks are still rejected rather than being treated as adapter-generated thinking.

### 3. Reasoning metadata truth table

`OpenRouterCatalogConverter` now distinguishes enabled-effort evidence from disable permission:

- known advertised enabled efforts remain available when `mandatory` is absent;
- absent `mandatory` keeps canonical `off` as the display/default state but does not authorize `reasoning.enabled=false`;
- explicitly `mandatory=false` continues to permit explicit disable;
- explicitly `mandatory=true` still removes `off` and clamps to the lowest enabled effort;
- empty, unknown, and none-only effective enabled effort sets remain conservative/no-control;
- converter-to-factory-to-real-local-SDK wire tests cover the resulting `reasoning` payload.

### 4. Local declaration/type discipline

`OpenRouterChatOpenAI` private Pydantic fields now have descriptions. `OpenRouterMessageCodec` retains validated `JsonValue` objects rather than broad internal `Any` dictionaries, validates opaque detail JSON at ingestion, and uses local merge helpers for indexed fragments. Provider catalog declarations already contain the required field descriptions and were checked as part of this owner slice.

## Test-first evidence

Initial red/green checkpoints:

| Checkpoint | Result |
|---|---:|
| Missing-mandatory known-effort converter expectation before implementation | 1 failed, 41 passed |
| Converter + factory wire correction | 58 passed, 1 warning |
| Stream/nonstream detached continuation assertions | 2 passed, 1 warning |
| Direct SDK cap + pool fallback cap shaping | 8 passed, 2 warnings |

Final focused/surrounding command used the isolated environment described above and selected:

```text
tests/agents/providers/test_openrouter_transport.py
tests/agents/providers/test_openrouter_nonstream_boundary.py
tests/agents/providers/test_openrouter_fragments.py
tests/agents/providers/test_openrouter_reasoning_semantics.py
tests/agents/providers/test_pool_fallback_integration.py
tests/agents/slo_agent/compaction/test_compacter.py
```

Result: **94 passed, 2 warnings in 2.44s**.

Quality checks:

```text
black --check --no-cache [10 assigned provider/compaction/converter test and source paths]
mypy --follow-imports=silent [4 changed source paths]
git diff --check
```

Results: **10 Black paths unchanged**; **mypy: Success, no issues found in 4 source files**; `git diff --check` exit 0.

## Limits and remaining work

- This local suite does not constitute the required full non-E2E gate.
- The direct cap proof is a real local SDK MockTransport request, but the pool fallback proof is a deterministic ModelPool member seam rather than a second real SDK pool transport composition.
- The continuation proof exercises factory/SDK messages directly. It does not independently add the larger `SloAgentSession` two-turn composed regression requested by the broader review; existing session/channel tests remain relevant.
- No automatic/overflow separately invokes a different compacter summary seam, so this report records shared-seam preservation rather than inventing duplicate tests/owners.
- No live provider, authenticated discovery, or paid inference was executed.
