# Slo Codebase Index

Acquisition170: [bounded correction](docs/implementation/94-herdr/acquisition-owner-170.md).
Failed pane acquisition can retain a lease without usable admission. Reporter final
cleanup/evidence now reads sequence-owner truth, not `_lease_held`. Native-lock/load
rollback matrix covers reporter and session drain; core1229/surrounds969 and scoped
statics pass. Author bounded READY only; fresh full gates and independent core
verification still required. Live USER-DEFERRED; compatibility UNVERIFIED.

Core168: [final author gates](docs/implementation/94-herdr/final-core-gates-168.md). Finite public-API documentation
audit complete; full8727/smoke288/lint813 and exact chapter/surrounding/Black
gates pass on unchanged1063 comprehensive inputs. Intermediate default drain
remains distinct from final disposal evidence; null final cleanup is independent.
Author READY OFFLINE only; independent core/wiring/harness/full review and fresh
Completion remain pending. Live USER-DEFERRED, compatibility UNVERIFIED.

Close167: [bounded regression receipt](docs/implementation/94-herdr/close-regression-167.md).
Final gateway failures cannot inherit intermediate default drained evidence.
Null final cleanup independently proves no resources rather than retrying its
intermediate close; session retains prior uncertainty. Focused/surrounding426
pass, scoped static5 clean. Full gates and R161-4 API ledger remain next;
feature REVISE, live DEFERRED/compatibility UNVERIFIED.

Core165: [contract correction receipt](docs/implementation/94-herdr/core-contracts-165.md).
Intermediate reporter close reports remote/sticky defects, not normal lease
retention; only final session close grants disposal evidence. Session aggregation
preserves all uncertainty. Owned1113/surrounds745 pass; public API documentation
expanded but exhaustive R161-4 audit remains pending. Combined assignment REVISE;
full make gates and independent re-review remain separate.

Core164: [bounded R161-1/2 receipt](docs/implementation/94-herdr/core-owner-164.md).
Restore stores retain one lease across operation cleanup failure; overlapping
operations/cleanup refuse nonblocking. Reporter final drain includes that owner.
An ambiguous close is never retried on its raw descriptor: same inode is not
same generation. Proven absence clears resources but not prior cleanup uncertainty.
R161-3/4 and independent re-review remain pending; no full-suite/live claim.

Revision160 integration: [receipt](docs/implementation/94-herdr/integration-revision-160.md).
Do not reload `sessions.service` merely to refresh config in tests: it replaces the
session class while headless/TUI consumers retain the old import, so later build
patches miss their target. Reload config only; retain a class-identity regression.
Exact combined1835 and full8680 now pass; independent Review/Completion pending.

Current revision156: [docs/implementation/94-herdr/profile-revision-156.md](docs/implementation/94-herdr/profile-revision-156.md) corrects the captured metadata-profile
connection to session publication. Validated activation profile is retained by the
session; events never reread it. Composed interactive/headless profile tests and
full8675/smoke288/lint805 pass. Independent review155 remains unfinished (R155-2);
fresh Completion pending; live user-deferred/compatibility UNVERIFIED. Earlier
154 readiness below is historical author evidence, not independent approval.

This root-level index is the project memory entry required for feature work. The
maintained runtime notes live in [`docs/RESEARCH.md`](docs/RESEARCH.md); read that
document before planning or changing a feature.

## Optional Herdr integration

Current author checkpoint: [integrated154](docs/implementation/94-herdr/integrated-gates-154.md)
marks T1–T6 **Code+Test READY USER-APPROVED OFFLINE**: full8667, smoke288,
exact chapter/surrounding gates, clean full lint804 and Black214; unchanged843-input
manifest. Independent full-feature Review and fresh Completion remain pending.
Live installed-launcher/native-restart/version/panes/paint/TTL/release acceptance is
explicitly user-deferred; compatibility UNVERIFIED. Older static-red/live-blocking
status below is historical. No global ordinary-tool redactor is promised.

Read [runtime owners and acceptance boundaries](docs/RESEARCH.md#feature-94-herdr--runtime-ownership-and-acceptance-boundary)
and [setup/privacy/retention/rollback](docs/INSTALL.md#optional-herdr-integration).
Session supplies private immutable capture; reporter owns save association and
transport admission; app owns lifetime and viewer task registration. Restore is
exact saved policy with current history, using the same SLO_HOME/default history
and plain installed Slo, not automatic prompt replay. Records have no automatic GC.
Claimed inbox refusal requires investigation before explicit resubmission. Herdr
0.9.2+ compatibility and live pane/restart evidence remain unproven; static failures
are unwaived. Current [T6 accounting correction151](docs/implementation/94-herdr/t6-accounting-fix-151.md)
proves the observer must count terminal return OR cancellation, not only returned
DAOs: real transport cancellation joins resources and completes owner accounting
before raising. Deterministic replacement coverage and full8653/D091669 pass.
The bounded fix is READY OFFLINE; overall T6 remains REVISE for unwaived lint281/58
and outstanding independent/live gates. No independent/live approval is claimed.
See historical [T6 docs/static diagnosis](docs/implementation/94-herdr/t6-docs-static-121.md).

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

## Verification

- Focused session-rate-limit coverage is under
  `tests/agents/slo_agent/test_session_rate_limits.py` and
  `tests/agents/slo_agent/test_session.py`.
- Use `make test` for the non-E2E suite and `make lint` for static checking.
