# Feature 86 — Owner A catalog corrective evidence — 2026-10-03

**Owner scope:** `src/agents/model_catalog/{service,store,dao}.py` and
`tests/agents/model_catalog/**` only. No specifications, capture/provider/auth/TUI
owners, Git state, network, credentials, installations, or system/PATH locations were
changed. Existing dirty and untracked work was preserved.

## Verdict

**REVISE — Feature 86 overall.** The finite Owner A catalog corrections below are
implemented and locally green. Other owners' outstanding Feature 86 findings and the
required final full non-E2E gate remain outside this ownership slice and were not run.

## Corrected behavior

### 1. Admission adoption cannot overwrite a newer publication

`ModelCatalogService._adopt_current_openrouter_slice()` now delegates its post-await
reference-swap decision to
`_publish_admission_candidate_if_current()`. That owner-local step:

1. rechecks the effective OpenRouter credential fingerprint after async candidate
   construction;
2. reads the raw durable provider cache again;
3. publishes only when that cache is still the exact cache used to build the candidate;
4. otherwise retries adoption from the current durable cache instead of publishing the
   stale candidate.

This preserves the single catalog service/publication owner, cold `load()` purity,
no-HTTP durable adoption, save-before-publish refresh semantics, last-good refresh
behavior, caller-supplied snapshot behavior, and run-pinned admitted snapshots.

### 2. Real catalog-store lease FD ownership

`ModelCatalogStore` now:

- annotates `refresh_lease()` as `AsyncIterator[None]`;
- closes an already-open lock descriptor if post-open `chmod` fails;
- owns the `asyncio.to_thread` opener as a task, shields its transfer, and, if the
  caller is cancelled first, awaits and closes the late descriptor before propagating
  cancellation;
- continues to release/close descriptors after unexpected `flock` failures.

No capture code was touched.

### 3. Required catalog DTO declarations

Affected discovery/cache/tombstone/lifecycle/refresh-result DAO fields now have
explicit `Field(description=...)` declarations, including private fingerprint
provenance. This is a declaration-only clarification; their serialized shapes and
ownership remain unchanged.

## Test-first evidence

All commands used only `/root/.pyenv/versions/slo-harness/bin/python -B`,
`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, isolated `HOME`/`SLO_HOME`/`TMPDIR`,
and a new checkout-contained `--basetemp` whose ancestry was asserted by the tests.
No HTTP client was configured for durable-adoption tests; no network request occurred.

| Phase | Test/result |
|---|---|
| Red — stale adoption | `test_adopt_current_openrouter_slice_does_not_overwrite_newer_generation_after_candidate_await` and `test_adopt_current_openrouter_slice_rejects_rotation_after_candidate_await`: **2 failed** before the service recheck. The failures showed stale candidate publication and no credential-rotation rejection. |
| Green — stale adoption | Same two deterministic asyncio-barrier tests: **2 passed, 1 warning, 0.20s**. The generation test proves a newer 512-token publication remains authoritative instead of an older 1024-token candidate overwriting it. The rotation test changes the resolver-effective key during the candidate await and receives `ModelPreparationRequiredError`; no candidate generation is published. |
| Existing real-store partition | Before this change, existing `test_openrouter_admission_security.py` real durable-slice removal/cap tests passed. They use no finite `side_effect` iterator and cover same-key external removal plus 3000→512 cap adoption without client invocation. |
| Red — lease tests | Added the contained lock tests; initially the chmod test failed because its fault was injected into parent-directory setup rather than the post-open branch. The test was corrected to allow parent privacy setup and fail the second chmod invocation. |
| Green — lease tests | `TestModelCatalogStoreRefreshLease`: **3 passed, 1 warning, 0.19s**. Covers late cancelled off-loop open closure plus reacquisition, post-open chmod closure, and unexpected flock failure cleanup/reacquisition. |
| Surrounding catalog partition | `tests/agents/model_catalog`: **293 passed, 2 warnings, 6.51s**. |
| Scoped quality | Black: **5 files unchanged**. Mypy: **Success: no issues found in 3 source files**. `git diff --check`: exit 0. |

## Files changed

- `src/agents/model_catalog/service.py`
- `src/agents/model_catalog/store.py`
- `src/agents/model_catalog/dao.py`
- `tests/agents/model_catalog/test_openrouter_admission_security.py`
- `tests/agents/model_catalog/test_model_catalog_store.py`
- this evidence report

## Limits and preserved boundaries

- The real owned-filesystem requirements for same-key removal/cap are preserved by
  the existing catalog admission tests; this correction adds the required deterministic
  publication and credential-rotation barriers.
- No full suite was run, per exclusive-owner instruction. The passing catalog partition
  is not a claim that Feature 86 is complete.
- This work does not resolve other-owner items such as adapter continuation,
  compaction pool-cap behavior, capture lifecycle/FD creation, auth UI outcome
  distinctions, or provider reasoning policy.
