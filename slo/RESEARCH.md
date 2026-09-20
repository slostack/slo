# Slo Codebase Index

This root-level index is the project memory entry required for feature work. The
maintained runtime notes live in [`docs/RESEARCH.md`](docs/RESEARCH.md); read that
document before planning or changing a feature.

## Rate-limit preflight

- `src/agents/slo_agent/sessions/service.py` owns session-local request and token
  windows, advisory preflight waits, cooldown status, and the provider-stream
  boundary.
- `src/agents/slo_agent/sessions/dao.py` holds immutable session-scoped data
  carriers.
- Local rate-limit calculations are advisory. Provider outcomes remain the source
  of truth for request-size, context, quota, and rate-limit decisions. Each successful
  `PreflightDecisionDAO` owns the exact estimate reused for local accounting and redacted
  provider-limit observations; failed local preflight writes no accounting.
- `preflight_bypassed` and `provider_limit_observed` are audit-only history events,
  excluded from model replay. A confirmed initial context overflow retries only after
  committed compaction; a no-op/failed compaction, a second or visible failure, and HTTP
  413 do not retry.

## Slotui core consumer scaffold (spec 79.integration)

- `src/integrations/slotui/` is deliberately dependency-free **Slo adapter-fixture** scaffolding, not a Slotui b.1 owner schema: it never imports `slotui`, installs a wheel, or claims clean-venv execution.
- An explicit `--presentation slotui_core --slotui-core-reference <absolute-json>` request verifies exact local reference and manifest bytes, canonical non-self-referential manifest hash, exact local regular wheel, `METADATA` name/version/`Requires-Python`, source identity/clean assertion, immutable module-qualified generic export signature/hash via archive AST (no import), exact required generic capability list, opaque b.0 stream / b.0.1 live-transcript evidence hashes, and core test-report hashes. Package registry, VCS, source directory, relative path, duplicate/missing/rich-only export, or static archive mismatch fails closed.
- A **verified** core fixture still fails with the clear integration-unavailable error before a Textual factory/session is constructed; it never falls through to `textual_current`. This preserves the default and headless separation until a real Slo core presentation assembly exists.
- There is intentionally no pip argv: future b.3 installation/execution must require an independently provisioned fresh Python, distinct from the Slo interpreter. `SlotuiParityMatrix` records b.2 adapter boundaries only. Images, LaTex, and Mermaid are literal/raw fallbacks; this work makes no rich parity claim. Tests use wheel-shaped ZIP fixtures that raise if imported, so protected core source is never consulted at runtime.

## Verification

- Focused session-rate-limit coverage is under
  `tests/agents/slo_agent/test_session_rate_limits.py` and
  `tests/agents/slo_agent/test_session.py`.
- Use `make test` for the non-E2E suite and `make lint` for static checking.
