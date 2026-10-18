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

## Installer launcher finalization

- `install.sh` discovers the authoritative pipx root only through `pipx environment --value PIPX_HOME`; an exported `PIPX_HOME` must never be used as a recovery fallback.
- The isolated-launcher finalizer treats `mktemp` output as hostile until its canonical parent is exactly the validated pipx `venvs/slo/bin` directory and its filename remains a `.slo.*` stage. Revalidate before stage write, file fsync, chmod, activation, and cleanup; cleanup must not delete a rejected external path.
- The release Docker matrix supplies `SLO_INSTALL_SMOKE_IMAGE`; `tests/cli/test_install_smoke.py` validates and runs exactly that supported image, and the repository-parent mount exposes its helper at `/src/slo/tests/cli/install_smoke_container.sh`.

## Feature 87 skills reorganization integration

- Authored skills now follow ownership boundaries: generic coding/engineering rules stay generic, while Python, Go, TypeScript, and frontend recipes own language/framework requirements. Removed non-declarative `skills/coding/` redirects are fully mapped in the attempt-2 worker ledger; old paths must not be treated as active recipes.
- `skills/coding/declarative-method-structure/SKILL.md` is the active shared owner with Python/Go/TypeScript specializations. Its historical source is explicitly reconstructed/evidence-based rather than claimed byte-for-byte; the complete old forwarder is preserved in the external attempt-2 ledger.
- `skills/INDEX.md` is generated only by `make refresh-skills` or `make build-skill-index`. Packaging checks enumerate the current filesystem so untracked authored skills are included and deleted files excluded.
- Active links to removed redirects must be distinguished from fixture paths, source examples, generated index text, and historical inventory/ledger records. Final integration evidence: `/root/Code/specifications/projects/slo/specifications/87-skills-reorganization/attempt-2/final-integration-ledger-20261011T185600Z.md`.

## Feature 95 scoped skill maintenance

- Workflow definitions and orchestration skills now live in `skills/orchestration/`;
  names and runtime user/workflow override precedence are unchanged. In the
  original relocation baseline, the six moved files retained base content except
  frontmatter group and relocation references. Subsequently accepted mode-removal
  and headless reasoning amendments intentionally changed five moved bodies:
  the four workflow resources and the headless guide. The relocation-only claim
  is historical, not a description of those final amended bodies.
- The scheduled TUI skills are explicitly frozen. The old headless-skill pointer
  at `skills/tui/tui-scheduled-workflows/SKILL.md:47` remains intentionally stale;
  reference validation allows only that exact source/target pair.
- Context gathering is an on-request, language-neutral evidence companion;
  unavailable sources are not empty findings. Solution-design's vertical addendum
  refines its existing document contract without authorizing a design exercise.

## Verification

- Focused session-rate-limit coverage is under
  `tests/agents/slo_agent/test_session_rate_limits.py` and
  `tests/agents/slo_agent/test_session.py`.
- Use `make test` for the non-E2E suite and `make lint` for static checking.
