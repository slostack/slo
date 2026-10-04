# Owner 3 — Feature 86 synthetic fixture bundle and disabled harness evidence

**Date:** 2026-10-03  
**Scope:** HEADLESS Code-Test-Review Step 1, Owner 3 only.  
**Verdict:** **READY for the bounded Owner 3 delivery; Feature 86 remains REVISE.**

## Clauses implemented

- **86.a.6 §8.1 / §7.7:** added the prescribed provenance-labelled fixture bundle
  and `tests/integrations/openrouter/test_live_openrouter.py`.
- **86.a.6 §7.2 / §9:** fixture tests are local-only, validate representative
  key/model/error/SSE/private-anchor payload shapes, and assert secret-like/live
  claim material is absent from checked-in fixture payloads.
- **86.a.6 §7.5 / §9:** documentation truthfully distinguishes synthetic offline
  contract evidence from authenticated GET or paid inference evidence.
- Related **86.a.1 §8.1–§8.2**, **86.a.2 §8.4**, and **86.a.3** fixture contracts:
  payloads are finite representative wire shapes for local converters/transport
  checks, not raw provider captures.

## Artifacts

| Path | Purpose |
| --- | --- |
| `tests/fixtures/openrouter/README.md` | Truthful synthetic provenance, sanitization boundary, consumer table, and opt-in limit. |
| `tests/fixtures/openrouter/key-valid.json` | Minimal `/api/v1/key` success envelope. |
| `tests/fixtures/openrouter/models-user-page.json` | One eligible text/tool user-model row. |
| `tests/fixtures/openrouter/errors.json` | Representative auth/rate/protocol error shapes. |
| `tests/fixtures/openrouter/chat-completions-tool.sse` | One local tool-call SSE frame. |
| `tests/fixtures/openrouter/private-anchor.json` | Synthetic same-route private-anchor shape. |
| `tests/integrations/openrouter/test_fixture_bundle.py` | Parses the bundle, checks route identity and rejects live/secret-like content. |
| `tests/integrations/openrouter/test_live_openrouter.py` | E2E-marked, opt-in harness contract tests. |

The bundle deliberately does **not** attempt an arbitrary response matrix. Existing
component and full-flow tests remain its meaningful offline consumers; the surrounding
run below includes the real local MockTransport full flow.

## Harness safety contract

`OpenRouterLiveHarness.open_fixture_client_when_enabled()` calls
`require_opt_in()` before invoking the injected resolver or constructing an
`httpx.AsyncClient`. Without an exact `SLO_OPENROUTER_LIVE_HARNESS` value it raises
`PermissionError`; the disabled test proves its resolver and request handler were
not invoked.

The only accepted checked-in modes are deliberately fixture-only:

- `fixture-discovery`: zero paid requests and zero output-token budget;
- `fixture-paid-smoke`: records the future separately authorized cap of at most two
  requests and 256 output tokens, but the checked-in test makes no inference call.

The enabled test injects a synthetic credential and `httpx.MockTransport`, asserts
safe public output, and performs no DNS, socket, external HTTP, credential-store,
or environment credential lookup. The module is `pytest.mark.e2e`; the repository
normal default deselects it. An explicit `-m e2e` execution remains synthetic unless
an authorized future procedure replaces the injected transport; no live route,
credential, GET request, or paid inference was executed for this delivery.

## TDD and verification

All commands used Python **3.11.7** at
`/root/.pyenv/versions/slo-harness/bin/python -B`, `-p no:cacheprovider`, an
`env -i` process with owned `HOME`, `TMPDIR`, and `SLO_HOME`, plus a resolved
checkout-owned `--basetemp`. No full suite was run.

1. **Initial test-first harness draft (not a valid RED):**
   `tests/integrations/openrouter/test_live_openrouter.py` unexpectedly passed
   **3 passed** because the first draft tested only `require_opt_in()` and did not
   exercise the resolver/client entry boundary. This was corrected immediately; it
   is not claimed as RED evidence.
2. **Effective RED:** the strengthened disabled-path test called the integrated
   entry boundary before it existed. The implementation then added the minimal
   `open_fixture_client_when_enabled()` gate. (The first shell output was not
   retained separately; no false failure count is claimed.)
3. **Green focused:** fixture bundle plus harness: **9 passed, 1 warning**.
   Root: `.owner3-fixture-green-W8m1pP/`.
4. **Default-disabled collection proof:** normal repository marker settings
   deselected the three e2e harness tests before execution: **3 deselected**
   (pytest exit 5 because that command selected no tests). Root:
   `.owner3-fixture-default-i5xgM3/`.
5. **Explicit e2e synthetic proof:** `-o addopts='' -m e2e` ran only the harness:
   **3 passed, 1 warning**, still synthetic MockTransport. Root:
   `.owner3-fixture-e2e-h0aRxx/`.
6. **Final surrounding regression:** `tests/integrations/openrouter` plus
   `tests/integration/test_openrouter_full_flow.py`: **34 passed, 5 warnings in
   46.37s**. Root: `.owner3-fixture-check-final-LYMAQC/`.
7. **Scoped static checks:** Black reported **2 unchanged** and mypy reported
   **Success: no issues found in 2 source files** for the two new test modules.
   `git diff --check --` for the owned artifact paths passed.

The retained warning classes are `pythonjsonlogger` relocation, LangGraph pending
allowed-objects, and three LangGraph/Pydantic `model_fields` deprecations from the
existing mounted full-flow test. They were not suppressed or waived as functional
results.

## Limits and non-claims

- No live OpenRouter request, credential read, environment secret enumeration,
  DNS lookup, paid call, install, system/PATH change, Git mutation, or specification
  edit occurred.
- No real credential is represented by the fixture sentinels, and the README does
  not claim observed/live data or post-capture sanitization.
- This work intentionally does not modify catalog/session/TUI production owners,
  their owner tests, `implementation-log.md`, or current status.
- The future live procedure requires fresh explicit authorization, separate
  authenticated discovery versus paid-smoke consent, and an audited real-transport
  implementation. Therefore this delivery is offline harness/fixture evidence only,
  not Feature 86 completion or provider availability proof.
