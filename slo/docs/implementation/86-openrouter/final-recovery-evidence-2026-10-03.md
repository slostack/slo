# Feature 86 — final authorized recovery Call 4

Date: 2026-10-03. **Verdict: REVISE.** Backend model identifier is not exposed by this session. No independent Step 2/3 approval is claimed.

## Changes and verified scope

- `ModelCapabilitiesDAO.supports_max_tokens`: optional strict boolean evidence, backward-compatible None default. Converter retains only actual booleans from `reasoning.supports_max_tokens`; no budget control added. Six tests cross conversion and actual schema-2 save/reload. Overview §§7.2–7.3; a.2 §7.2; F86-17/18. Prepared-entry and explicit no-budget-wire matrix remain incomplete.
- `ModelCatalogOverrideService._increases_optional_limit`: None → None is not an increase. The required real override-removal test exposed that lowering an output cap while leaving unknown TPM unchanged was incorrectly rejected. Actual cache and override bytes now prove lower cap/relabel/hide, unchanged raw cache, remove override, reset/load, and exact original entry restoration. a.2 §§7.3/8.2; F86-29.
- Default-effort regression now calls real LLMFactory/OpenRouterChatOpenAI and captures one SDK MockTransport request with `reasoning.effort=high`. Initial test omitted the factory's explicit reasoning input and failed: factory defaults to off, whereas the session/caller supplies its selected level. The corrected test passes the catalog default explicitly, preserving that existing contract. Existing explicit-off/unknown-permission wire matrix also passes. a.3 §§7.2/8.1; F86-17/18/39.
- Picker projection ORs enabled-control and disable-control evidence and filters unsupported off from advertised levels. Two converter→projection→engine detail tests are red→green. **This is partial G1 repair:** `/reasoning` router semantics and mounted two-size paint are NOT corrected/proven here. Direct/internal wire profiles were not changed.
- Added real schema-2 first-read tests: execute actual loader, hold async delivery, commit removal/publish or rotate captured credential, then reject public admission. **Important limitation:** removal invokes the ordinary force-refresh branch because membership is absent; the test supplies a safe `fresh` refresh result to isolate admission and assert zero client construction. It is not the requested entirely unmocked zero-HTTP admission proof. Rotation does not need that refresh outcome. Synthetic predecessor tests remain unchanged.

## Selection failure isolation

The exact selection module ran before production edits: **14 passed, 2 warnings in 14.45s**. The final complete suite also passed. No selection production/test code changed; no sleep, skip, retry-to-green, or weakened selection assertion was introduced. Current app/picker diff and test source were inspected, but **no causal connection between picker decomposition and Call3's offset failure was established**. Green execution is not a repair or root-cause proof. Required diagnosis remains open.

## Execution receipts

Owned root: `.f86-final-recovery-O3ZPKA/`; `ownership.txt` records resolved checkout/root and owner. All commands used approved `/root/.pyenv/versions/slo-harness/bin/python -B`, `env -i`, repo-owned HOME/TMPDIR/SLO_HOME/auth/basetemp, `PYTHONDONTWRITEBYTECODE=1`, `SLO_AUTO_VISUALIZE=0`, checkout PYTHONPATH and `-p no:cacheprovider`. No live OpenRouter/credential/inference or external network operation was intentionally performed. Tests use synthetic transports. No Git mutation, workflow launch, installation, shared interpreter/skill modification, system/PATH write or external KB write.

Scoped command suffix: `-m pytest -p no:cacheprovider --basetemp=<root>/<run>-base <nodes> -q --tb=short`.

| Log prefix | Nodes | Actual result |
|---|---|---|
| isolation | tests/tui/test_selection_scroll_highlight.py | 14 passed, 2 warnings; exit 0 |
| budget-red | tests/agents/model_catalog/test_openrouter_budget_evidence.py | 6 failed, missing field; exit 1 |
| budget-green | tests/agents/model_catalog | 308 passed, 2 warnings; exit 0 |
| default-wire | tests/agents/providers/test_openrouter_reasoning_semantics.py | 1 failed, 19 passed, 1 warning; exit 1 |
| default-wire-green | same | 20 passed, 1 warning; exit 0 |
| real-store | tests/agents/model_catalog/test_openrouter_real_store_recovery.py | 2 failed, 1 passed, 3 warnings; exit 1 |
| real-store-green | same | 1 failed, 2 passed, 2 warnings; exit 1 (None TPM defect) |
| override-fix | tests/agents/model_catalog | 311 passed, 2 warnings; exit 0 |
| presentation-red | tests/tui/test_openrouter_reasoning_presentation_recovery.py | 2 failed, 2 warnings; exit 1 |
| presentation-green | preceding module plus test_model_catalog.py, test_slash_suggestion_engine.py, test_openrouter_picker.py, test_picker_g8.py | 50 passed, 2 warnings; exit 0 |

Initial real-store failures were fixture limitations: required fingerprint absent from override fixture; removal correctly requested refresh and hit the no-client tripwire. These were not represented as production regressions. Complete logs preserve all output.

### Fresh complete final functional gate

After the last source/test edit, using separate `full-home`, `full-tmp`, `full-slo`, `full-base`:

**5136 passed, 18 deselected, 196 warnings in 327.78s (0:05:27); exit 0.**

Expanded command: `.f86-final-recovery-O3ZPKA/full-command.txt`.
Full output: `.f86-final-recovery-O3ZPKA/full-non-e2e.log`.
Exit receipt: `.f86-final-recovery-O3ZPKA/full.exit`.

No code/test edits followed this gate. Diff whitespace check passed; read-only `dpkg -V coreutils` exited 0 with empty output. Warnings include unawaited AsyncMock warnings; not suppressed. The 18 exclusions include E2E/default-disabled live/fixture harness cases, not executed provider evidence. Black/mypy were not run: static waiver only, not green.

## Remaining requirements and process limits

1. Explain/reproduce Call3's selection failure causally; neither isolated nor complete green execution supplies that explanation.
2. Finish G1 `/reasoning` supported-disable/unknown-disable semantics and actual mounted picker/router paint at both mandated sizes.
3. Extend G2 strict metadata proof through prepared admission and no-budget SDK requests, including absent metadata.
4. E1 real-store admission proof is bounded by injected refresh result; do not claim the stronger all-real zero-HTTP removal composition.
5. Independent Step 2 rereview and Step 3 completion assessment remain outstanding. Full functional green is not workflow approval.

Read all six immutable engineering contracts individually, request and dependency index, and relevant overview §§7.1–7.6. Root RESEARCH and supplied repository/global instructions consulted. Loaded cadence/type/declarative/docstring/test-verification skills and TUI orientation. Not all requested layer guidance/report reconciliation was completed; do not infer full convention/read-checklist compliance. No immutable contract or historical report was edited. Prior Call3 failure and independent review remain valid historical evidence.
