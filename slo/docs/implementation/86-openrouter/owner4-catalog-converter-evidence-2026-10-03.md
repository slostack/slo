# Feature 86 — Owner 4 catalog admission and reasoning converter evidence

Date: 2026-10-03

## Scope

This Step 1 correction owns only the independent rereview findings:

1. OpenRouter next-admission must not return a stale snapshot when the first asynchronous durable-cache read returns after a newer same-key publication.
2. OpenRouter reasoning conversion must preserve explicit disable-only evidence and must apply advertised/default enabled efforts without inferring disable permission.

No immutable specification, shared status document, remaining-requirements document, or implementation log was modified. Existing dirty/untracked work was retained. No live provider, network request, real credential, package/environment installation, or Git mutation was used.

## Production changes

- `src/agents/model_catalog/service.py`
  - Equal-slice admission now calls `_revalidate_unchanged_admission_snapshot()` after the first asynchronous cache read.
  - The helper rechecks effective credential identity, performs a second offline durable-cache read, and either returns the unchanged snapshot, adopts the newer durable view, or rejects credential rotation. It preserves supplied-snapshot behavior, run-pinned snapshots, offline-only adoption, and no stale republish.
- `src/agents/model_catalog/openrouter.py`
  - Separates explicit disable permission from known enabled efforts.
  - A `none`/disable-only advertised record with `mandatory=false` retains the disable control; missing/unknown metadata remains unavailable.
  - A valid advertised default effort, or the lowest known enabled effort, is now selected even when `mandatory` is absent; absent mandatory still does not authorize an explicit disable request.
- `src/agents/reasoning_capabilities.py` and `src/agents/base.py`
  - Carry the two capability facts independently into the existing resolver/factory path so the actual SDK request emits `reasoning.enabled=false` only when explicit disable permission exists.

## Test-first evidence

All commands used `/root/.pyenv/versions/slo-harness/bin/python -B`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, isolated owned `HOME`, `TMPDIR`, `SLO_HOME`, `SLO_AUTH_FILE`, and checkout-contained `--basetemp`. No cache was reused.

### RED

```text
pytest tests/agents/providers/test_openrouter_reasoning_semantics.py
2 failed, 18 passed, 1 warning
```

The new exact assertions exposed both defects:

- `supported_efforts=["none"]`, `mandatory=false` omitted the required `{"enabled": false}` wire control.
- A valid `default_effort="high"` with mandatory absent resolved as `off` rather than `high`.

```text
pytest tests/agents/model_catalog/test_openrouter_admission_security.py::test_prepare_models_rechecks_unchanged_initial_cache_after_newer_removal_publication
1 failed, 1 warning
```

The deterministic barrier captured the first cache value, published an external same-key removal before delivery, then resumed the unchanged candidate. The old behavior admitted the removed route.

### GREEN

```text
pytest tests/agents/providers/test_openrouter_reasoning_semantics.py tests/agents/model_catalog/test_openrouter_converter_metadata.py
66 passed, 1 warning
```

The converter and actual `LLMFactory -> OpenRouterChatOpenAI -> httpx.MockTransport` request path now cover:

- omitted/null/empty/unknown metadata;
- explicit disable-only `none` effort;
- mandatory clamp;
- explicit default and fallback default enabled efforts;
- absence of disable permission when mandatory is absent.

```text
pytest tests/agents/model_catalog/test_openrouter_admission_security.py
17 passed, 2 warnings
```

The new public `prepare_models()` barrier cases prove both a distinct same-key removal and credential A-to-B rotation after the first completed cache read cannot admit stale state.

```text
pytest tests/agents/model_catalog/test_openrouter_admission_security.py tests/agents/providers/test_openrouter_reasoning_semantics.py tests/agents/model_catalog/test_openrouter_converter_metadata.py
83 passed, 2 warnings
```

```text
pytest tests/agents/model_catalog tests/agents/providers/test_openrouter.py tests/agents/providers/test_openrouter_capability_recovery.py tests/agents/providers/test_openrouter_reasoning_semantics.py tests/agents/providers/test_openrouter_runtime_boundaries.py
358 passed, 2 warnings
```

`git diff --check` over the touched paths exited 0.

## Limitations and verdict

This is bounded Step 1 evidence only. It does not run or claim a fresh full non-E2E suite, static gate, live-provider availability, entitlement, or feature completion. Existing warnings are recorded above and were not suppressed.

STEP1READY
