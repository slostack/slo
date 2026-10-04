# OpenRouter fixture bundle — synthetic provenance

Every asset is authored synthetic, specification-derived wire data, **not observed
provider traffic**, account data, availability evidence, or paid inference evidence.
No live key or opaque provider capture is included. Sanitization means authoring
without account/secret data, not claiming post-capture redaction.

## Executable consumers

`tests/integrations/openrouter/test_harness_contract.py` runs in the normal non-E2E
gate and consumes these assets across real production boundaries:

| Asset | Meaningful consumer |
| --- | --- |
| `key-valid.json` | Production GET verification and candidate authentication before persistence |
| `models-user-page.json` | Production GET, converter, authentication-to-catalog publication, disk reload, and exact smoke route admission |
| `errors.json` | Production auth rejects 401 and HTTP-200 error envelopes without persistence; SDK/adapter 429 propagates after exactly one request |
| `chat-completions-tool.sse` | Actual OpenRouterChatOpenAI/SDK streaming decode, bound in-memory tool execution, second tool-result request |
| `private-anchor.json` | Synthetic reasoning details injected into SSE and checked unchanged on the adapter's second request; excluded from harness result |

The filenames retain the existing Owner 3 bundle instead of duplicating payloads
under overview §7.11's illustrative names. `key-valid` corresponds to `key`,
`models-user-page` to `models_user`, and the SSE plus anchor to
`stream_tool_reasoning`. No `models_public` observed fixture is fabricated and no
public-model endpoint is called: it is not authenticated entitlement evidence.
This finite synthetic/documented-shape evidence must never be described as a
public observed capture. Existing full-flow and converter matrices remain separate
coverage, not implied consumers of these assets.

## Disabled-by-default, fixture-only harness

`OpenRouterLiveHarness.invoke_fixture` in `test_live_openrouter.py` requires an
explicit supplied mapping before invoking any credential supplier or constructing
an HTTP/production client. Non-E2E tests prove denial with construction tripwires.
No environment enumeration or host credential lookup is needed.

- `fixture-discovery`: `/key` then `/models/user`, real GET client and converter;
  inference is denied at the transport boundary.
- `fixture-paid-smoke`: separate opt-in, mandatory exact discovered route; one
  harmless no-argument `fixture_echo` execution returning `fixture-ok`; at most
  two SDK inference requests, each with a 256-token output ceiling; zero SDK
  retries, no fallback/sweep, and no third call even if the second asks for tools.

The transport is always a bounded `httpx.MockTransport`. It rejects alternate
origins/endpoints, route changes, missing/excess output caps, and a third attempt
before the responder. GETs are metadata calls, not part of the two inference-call
budget. Tool name/argument/count violations stop before execution or continuation.
Results contain only canonical names and counters, never account responses, keys,
answers or reasoning payloads.

The three legacy E2E-marked harness checks are normally deselected. The meaningful
execution and adverse-path checks are in the default non-E2E gate; no skip/xfail is
used to hide disabled behavior. Both surfaces remain synthetic only. A live run
requires new explicit authorization, credentials, separately consented discovery
versus paid inference, and a reviewed real-transport procedure. **No live GET,
DNS, paid inference, provider availability or live acceptance is claimed.**
