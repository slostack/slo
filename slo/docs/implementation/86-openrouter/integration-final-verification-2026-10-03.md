# Feature 86 — final Step 1 integration verification

**Date:** 2026-10-03  
**Scope:** sequential integration after Owners A–D. This is a Step 1 correction/integration record only. It does **not** claim Step 2 review or Step 3 completion.

## Verdict

**REVISE.** The four owner corrections are present and their cross-owner boundaries were inspected. The one fresh, complete non-E2E gate required for this phase failed, so Feature 86 cannot be reported READY.

No live OpenRouter/authenticated-provider/paid-inference proof ran. Local `httpx.MockTransport`, synthetic credentials, Faux/fixture models, and finite local child processes prove implementation contracts only; they do not establish remote availability, entitlement, or provider behavior.

## Inputs and safety

Read before assessment: repository instructions (`AGENTS.md`, `SLO.md`, `CLAUDE.md`), `docs/RESEARCH.md`; Code-Test-Review and mandatory coding/test skills; the Feature 86 request, overview, completion/index artifacts, and all six 86.a.1–86.a.6 slices; the relevant Slo KB pages; current/review/continuation ledgers; and all four owner reports.

I preserved the pre-existing dirty and untracked work. No Git staging, commit, push, merge, rebase, reset, clean, or worktree operation occurred. No specification was edited. No system/PATH location, package, credential store, network endpoint, or external service was changed. Test state was isolated under fresh checkout-contained roots, with an isolated `HOME`, `SLO_HOME`, `TMPDIR`, auth path, bytecode disabled, and `-p no:cacheprovider`.

## Cross-owner source and test map

| Boundary | Current source owner(s) | Evidence inspected |
|---|---|---|
| Catalog generation, credential recheck, durable same-key admission | `src/agents/model_catalog/service.py`, `store.py`, `dao.py` | Owner A’s stale-publication barrier, rotation, lock cancellation/chmod/flock cleanup tests; `test_openrouter_admission_security.py`, catalog lifecycle/store tests. |
| Compaction caps and pool fallback | `src/agents/slo_agent/compaction/compacter.py`, `src/agents/providers/model_pool.py`, `src/agents/providers/openrouter.py` | Owner C’s marker-based selected-lane cap mechanism, direct MockTransport request, fallback-cap tests, and one summary seam. |
| Visible reasoning / continuation | `src/agents/providers/openrouter.py`, extension/history seams | Owner C streamed and non-streamed detached assistant projection tests: display-only reasoning omitted from outbound request without mutating source or stripping same-route private extension/tool output. |
| Auth verification, listing rotation, modal state | `src/auth/openrouter_authentication.py`, `src/integrations/openrouter/{client,exceptions}.py`, authentication TUI | Owner D tests distinguish rejection/timeout/protocol safely and retain saved-state truth while clearing stale verified dismissal evidence after listing-time `credential_changed`. |
| Capture lease, cancellation, reservation, FD/mode lifecycle | `src/agents/slo_agent/orchestrator/{spawn_env,relaunch,workflow_registry,capture_writer}.py` | Owner B writer-lifetime lease transfer, reaped-launcher tail ordering, late stdout/stderr opener cleanup, pre-adoption rollback, descriptor cleanup, and 0700/0600 creation tests. |
| Exact unlisted route guidance | `src/agents/model_catalog/service.py` | Integration correction adds the required literal `unsupported variant; choose a catalog entry or /model refresh` while retaining the exact requested route in the preparation error. |

### Integration correction made

A cross-owner product-copy requirement remained absent from catalog preparation errors: manually supplied unlisted OpenRouter variants were rejected but did not include the required actionable variant guidance. The smallest correction is in `ModelCatalogService.prepare_models()`: its OpenRouter membership exception now retains the exact requested canonical route and adds the literal required guidance. It does not strip suffixes, select another model, perform a single-model lookup, or alter direct-provider handling.

A pre-existing strict-build test remained green before the change and does not exercise this asynchronous catalog membership branch. The changed behavior was then included in the focused integration partition below.

## Tests and checks actually run

### Focused integrated boundaries — passed

```bash
/root/.pyenv/versions/slo-harness/bin/python -B -m pytest -q \
  -p no:cacheprovider --basetemp=<fresh-checkout-root>/tests \
  tests/agents/model_catalog/test_openrouter_admission_security.py \
  tests/agents/slo_agent/test_catalog_generation.py \
  tests/agents/providers/test_openrouter_transport.py \
  tests/agents/providers/test_openrouter_nonstream_boundary.py \
  tests/agents/providers/test_openrouter_reasoning_semantics.py \
  tests/agents/providers/test_pool_fallback_integration.py \
  tests/agents/slo_agent/compaction/test_compacter.py \
  tests/auth/test_openrouter_authentication.py \
  tests/tui/authentication/test_openrouter_authentication.py \
  tests/agents/slo_agent/orchestrator/test_capture_control_protocol.py \
  tests/agents/slo_agent/orchestrator/test_capture_writer.py \
  tests/agents/slo_agent/orchestrator/test_relaunch.py \
  tests/agents/slo_agent/orchestrator/test_workflow_registry.py \
  tests/agents/slo_agent/orchestrator/test_workflow_command_service.py --tb=short
```

**Result:** `322 passed, 2 warnings in 18.42s`.

The directly relevant catalog integrity/read-view/session preparation partition was also run after the message correction: **30 passed, 2 warnings in 1.16s**.

### Fresh required complete non-E2E gate — failed

Command (single complete run; timeout 1200 seconds):

```bash
env -i PATH=/root/.pyenv/versions/slo-harness/bin:/usr/bin:/bin \
  VIRTUAL_ENV=/root/.pyenv/versions/slo-harness \
  HOME=<fresh-root>/home TMPDIR=<fresh-root>/tmp SLO_HOME=<fresh-root>/home/.slo \
  SLO_AUTH_FILE=<fresh-root>/home/authentication.json SLO_ENV=test \
  SLO_AUTO_VISUALIZE=0 SLO_PLUGINS_DISABLED=1 PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$PWD" /root/.pyenv/versions/slo-harness/bin/python -B -m pytest -q \
  -m 'not e2e' -p no:cacheprovider --basetemp=<fresh-root>/tests tests --tb=short
```

**Actual result:** `29 failed, 5036 passed, 15 deselected, 196 warnings in 357.66s` (exit 1).

The 15 deselections are the repository’s E2E-marked tests. No additional tests were deselected.

Failures are finite and fall into three groups:

1. **Catalog message compatibility (10):** this integration correction initially omitted the exact route expected by existing catalog tests. The source was immediately adjusted to include both the route and the required variant guidance; the dedicated catalog partition then passed. The complete gate is historical evidence of the pre-adjustment wording and was not rerun, per the user’s one-full-gate instruction.
2. **Capture exact-entry assertion (1):** `test_production_capture_opener_uses_exact_isolated_entry_without_spawn` expected a fixed append-lock FD number. The corrected writer-lifetime lease adds the inherited lease descriptor, making allocation numbering non-deterministic. This is an owner-B test-contract failure requiring an assertion that validates descriptor wiring without hard-coding the allocation number.
3. **Plugin tests under isolated home (18):** plugin loader/session/TUI tests expected managed/user plugin fixtures under the normal home location. The mandated fresh isolated `HOME` makes those paths absent, yielding empty plugin registration/discovery. This is test-environment/fixture isolation compatibility, not a live-provider failure; it must be resolved without weakening the local-only gate or using the operator home.

### Diff check

```bash
git diff --check
```

**Result:** exit 0.

## Ledger status

The current ledgers were reconciled only as current records; historical reports remain untouched.

- Owner A’s catalog stale-adoption/publication ordering, credential recheck, lock-FD ownership, and DAO declaration work is locally green.
- Owner B’s independent writer lease, cancellation/reservation, descriptor cleanup, and private capture-mode work is locally green.
- Owner C’s visible reasoning continuation, direct/pool compaction cap, reasoning metadata, and provider declaration/type work is locally green.
- Owner D’s safe auth outcome and listing-time credential-change modal work is locally green.
- Historical full-suite counts are historical only. The fresh 29-failure complete gate above is the current integration-gate result.
- The static waiver applies **only** to Black/mypy. Formatting and mypy were not run as blockers here. It does not waive functional failures, security requirements, missing artifacts, or this failed pytest gate.

## Finite remaining requirements before READY

1. Repair Owner B’s exact-entry capture test/contract for inherited append-lock descriptor allocation without weakening lease-transfer coverage.
2. Make plugin fixture discovery compatible with the required fresh isolated `HOME` (or inject test-local managed/user plugin roots) while retaining no operator-home reads and no network/install behavior.
3. Run exactly one newly fresh complete non-E2E gate after those edits, with the same approved harness/interpreter/local-only containment, and require exit 0.
4. Reconcile the current ledgers with that new result; do not call the incomplete audit approved. No Step 2 or Step 3 claim belongs to this phase.
