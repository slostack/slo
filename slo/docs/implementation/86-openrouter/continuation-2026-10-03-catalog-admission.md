# Feature 86 — Catalog-admission continuation — 2026-10-03

**Terminal Step 1 verdict: REVISE.** This is a one-owner continuation in the existing dirty workspace, not a workflow launch, formal review, completion assessment, or claim that Feature 86 is ready. Requested call/model setting: **gpt-6-astra medium**; backend identity is not independently attestable.

## Scope and source correction

This continuation addressed accepted independent finding **G1 / A1** at `ModelCatalogService._prepare_openrouter_admission`: a warm process could combine a fresh same-credential durable provider slice with a stale in-memory snapshot and admit removed or capability-stale data.

The current `src/agents/model_catalog/service.py` correction is retained and formatted. It reads the current raw cache during credential-aware admission, projects a coherent matching provider slice through `_adopt_current_openrouter_slice`, validates/apply overrides before publishing it, and returns that newly published immutable generation. The existing fast path still requires both current evidence and requested exact route membership. The correction does not add HTTP discovery, stale in-memory reconstruction, a second catalog owner, mutable run snapshots, or persistence writes. A snapshot supplied by a caller remains pinned and is not re-admitted.

Two deterministic local tests in `tests/agents/model_catalog/test_openrouter_admission_security.py` now exercise the actual admission path:

1. `test_prepare_models_adopts_fresh_same_key_disk_removal_before_admission` warms the in-memory snapshot from an initial same-key cache, then exposes a complete external durable publication that removes the route. The next admission raises `ModelPreparationRequiredError`; it cannot retain stale membership.
2. `test_prepare_models_adopts_fresh_same_key_disk_cap_before_admission` uses the same warm/external-publication ordering and proves the next returned admission snapshot changes the route output cap from 3000 to 512. No client is configured or invoked.

These checks establish both requested same-key external removal and capability-cap adoption through the durable catalog. They do not change admitted runs: that is still governed by existing immutable session/run snapshot pinning.

## Causal hang diagnosis

The prior 1200-second focused invocation was a **test-construction fault**, not a catalog lock/deadlock.

- The removal test patched `ModelCatalogStore.load_provider_cache` with a finite two-item `side_effect` (`initial`, then `removed`).
- The corrected admission path has additional legitimate reads: cold warm-up, current admission cache read, and the stale-list fallback read. Exhausting that iterator raises `StopIteration` inside `asyncio.to_thread`.
- Python cannot set `StopIteration` on the awaiting Future (`TypeError: StopIteration interacts badly with generators and cannot be raised into a Future`), leaving the coroutine awaiting a Future that never resolves. The diagnostic stack showed the main task idle in `asyncio` selector polling and the worker idle, not blocked in catalog lease acquisition.
- `--collect-only` completed in 0.14 s. A bounded direct reproduction and the original pytest node timed out; the retained diagnostic trace is `.f86-catalog-trace-QDZ9t7/faulthandler.log`. After replacing the finite side effect with explicit warm `initial` followed by stable `return_value=removed`, the test first failed promptly when one remaining fallback read was exposed, then passed with the complete expected read contract.

No test was skipped, slept, or weakened. The corrected test models an external publication deterministically and prevents this async `StopIteration` hang from masking a test failure.

## Commands and results

Every pytest command used only `/root/.pyenv/versions/slo-harness/bin/python -B`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH="$PWD"`, `-p no:cacheprovider`, and a newly created checkout-contained resolved `--basetemp`. All test artifacts were local synthetic `tmp_path`/checkout-owned paths; no live credential, network, system/PATH, package, Git, specification, KB, or external write occurred.

| Purpose | Command shape | Result |
|---|---|---|
| Collection isolation | `python -B -c ... pytest.main(["--collect-only", ...])` | 1 collected, 0.14 s |
| Bounded causal trace | `timeout 60s python -u -B -X faulthandler -c ...` on original node | timeout; trace identifies finite mock `StopIteration` → invalid Future state |
| Corrected removal node | `timeout 60s python -u -B -m pytest -q -p no:cacheprovider --basetemp="$BASE/tests" ...::test_prepare_models_adopts_fresh_same_key_disk_removal_before_admission` | 1 passed, 1 warning, 0.37 s |
| New cap node | same command shape for `...disk_cap_before_admission` | 1 passed, 1 warning, 0.18 s |
| Focused module | same shape, `test_openrouter_admission_security.py` | 13 passed, 2 warnings, 1.46 s |
| Catalog surrounding partition | same shape, admission-security + lifecycle + residuals + atomic-publication modules | 57 passed, 2 warnings, 3.47 s |
| Scoped quality | `python -B -m black --check --no-cache service.py test_openrouter_admission_security.py`; `python -B -m mypy --follow-imports=silent --cache-dir="$BASE/mypy" ...`; `git diff --check` | Black 2 unchanged; mypy success (2 files); diff check exit 0 |

The required explicit `>=1200` timing budget was used for both final focused and surrounding catalog test commands (`timeout 1200s`), although each completed quickly. No current full non-E2E suite was run in this continuation, so historical full-suite counts are not presented as current verification.

## Truthful finite handoff

The G1 catalog removal/cap correction is locally validated. Feature 86 Step 1 remains **REVISE** because the accepted independent A/C queue is not complete and no fresh full non-E2E gate has run after this continuation.

1. **G2 / B1 — live visible-reasoning continuation:** real second live SDK request with displayed reasoning plus tool/summary must strip only internal display reasoning while preserving same-route private continuation.
2. **G3 / B2 — compaction output cap:** bound summary reserves to the pinned direct/pool lane policy and prove absent/small cap plus fallback wires.
3. **G4 / C1 — append lease after launcher exit:** move/retain ownership with the independent writer and prove reaped-launcher old-tail-before-replacement-byte ordering.
4. **G5 / C2 — cancellation before capture handoff:** drain/close late open results and roll back pre-adoption reservations; prove stdout/stderr late success/error and control EOF/reap cases.
5. **G6 / C3 and A2 — FD ownership:** close catalog and capture allocation/chmod/flock failure descriptors and prove lease reacquisition.
6. **G7 / C4 — private modes:** enforce/verify capture directory 0700 and file 0600 under permissive creation conditions.
7. **G8 / A3/A4 — auth categories:** distinguish timeout/rejection/protocol and listing-time credential change through service and painted modal assertions.
8. **G9 / B4 — reasoning metadata:** implement/test known enabled effort without mandatory disable permission; preserve conservative unknown/none policy.
9. **G10/G11:** complete mandatory field descriptions/type narrowing/declarative owner-local work and missing named operator artifacts only after exact cited source/spec review.
10. **Gates:** run a newly fresh complete non-E2E suite only after remaining edits, then report actual result. Global static disposition remains separately required by the current ledger; it is not declared green here.

R2/R3/R4, transport pagination correction, and the existing compacter partial corrections were not modified or re-certified by this continuation.
