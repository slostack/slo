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

- `src/integrations/slotui/` is deliberately dependency-free production scaffolding: it does **not** import `slotui` or install anything at runtime.
- An explicit `--presentation slotui_core --slotui-core-reference <absolute-json>` request reads a typed local reference, verifies the exact manifest bytes SHA-256, strict manifest schema, local regular-wheel URL/path, filename, wheel SHA-256, dist-info name/version, export surface, and terminal/editor/events/session/history/replay/slash/live-transcript capability declaration. The only generated installation plan is `python -m pip install --disable-pip-version-check --no-index --no-deps <exact-wheel>` for a clean release venv.
- Missing/invalid proof fails closed with an operator-clear error. `textual_current` remains the bare CLI default, and headless rejects all interactive presentation selection rather than silently changing behavior.
- `SlotuiParityMatrix` records b.2 adapter boundaries only. Images, LaTex, and Mermaid are literal/raw fallbacks; this work makes no rich parity claim. Tests use wheel-shaped zip and typed manifest fixtures that raise if imported, so b.0.1's uncommitted source tree is never consulted at runtime.

## Verification

- Focused session-rate-limit coverage is under
  `tests/agents/slo_agent/test_session_rate_limits.py` and
  `tests/agents/slo_agent/test_session.py`.
- Use `make test` for the non-E2E suite and `make lint` for static checking.
