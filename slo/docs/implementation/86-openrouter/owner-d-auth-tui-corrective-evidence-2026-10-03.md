# Feature 86 Owner D — Auth/TUI corrective evidence

**Date:** 2026-10-03  
**Verdict:** REVISE — this owner slice is locally green; Feature 86 remains in the documented overall REVISE state and no full-suite gate was run.

## Scope and ownership

Changed only Owner D's OpenRouter authentication/client outcome boundary and matching
service/modal tests:

- `src/auth/openrouter_authentication.py`
- `src/integrations/openrouter/client.py`
- `src/integrations/openrouter/exceptions.py`
- `tests/auth/test_openrouter_authentication.py`
- `tests/tui/authentication/test_openrouter_authentication.py`

These paths were already untracked dirty work. No Git mutation, spec edit, credential
resolver/session/catalog-store/capture/provider/compacter edit, network request, live
credential, package installation, or system/PATH write occurred.

## Exact requirements interpreted

1. **Safe auth outcome distinctions.** Overview §7.2 and 86.a.5 §§7.2–7.3 require
   failed verification to preserve existing bytes and distinguish a rejected effective
   key from timeout/protocol failure without exposing exception or wire text. The fixed
   copies implemented are:
   - rejection: `OpenRouter key was rejected. Check /auth or SLO_OPENROUTER_API_KEY.`
   - timeout: `OpenRouter request timed out. Retry authentication later.`
   - protocol: `OpenRouter returned an invalid verification response. Retry authentication later.`

2. **Listing-time credential rotation.** 86.a.5 §7.2 says a refresh uses the same
   captured private credential, while the overview/auth contract permits a credential
   race to reject publication. When catalog refresh returns `credential_changed`, the
   authentication result now clears `key_verified`, `catalog_checked`, and the private
   dismissal credential. It preserves `replacement_saved=True` when the verified
   submitted candidate was already synchronously persisted. The mounted modal therefore
   remains on the API-key input with the retry notice instead of showing success.

3. **`/model refresh` count/check-time.** Overview §7.10 and 86.a.5 §7.6 prescribe a
   bounded count/time/status result. The existing owner interface remains a safe string
   returned by `SloAgentSession.refresh_model_catalog()` through `SlashRouter`; its
   current `CatalogRefreshResultDAO` has only status/generation/safe message. Adding
   count/check-time requires catalog/session ownership, explicitly outside this slice.
   No TUI wire parsing or speculative DTO was added.

4. **Pending direct selection and unlisted variants.** 86.a.4 §7.2 explicitly blocks
   all pending selections; the current direct-model block is therefore not an escape to
   change here. The overview §7.3 requires the exact unlisted-variant guidance
   `unsupported variant; choose a catalog entry or /model refresh`; that catalog
   admission owner is outside this slice. No suffix stripping, router architecture, or
   identity behavior changed.

## Test-first corrective loop

The pre-change focused owner partition was green (24 tests), demonstrating the missing
branches were not asserted. Tests were strengthened first for rejection/timeout/protocol
copy and listing-time stale-evidence dismissal, then the minimal exception/category and
result-state changes were made.

### Focused green

```text
26 passed, 2 warnings in 2.58s
```

Nodes:

```text
tests/auth/test_openrouter_authentication.py
tests/tui/authentication/test_openrouter_authentication.py
```

The service test uses local `httpx.MockTransport` and a verified `tmp_path` descendant.
The compositor test mounts the real `AuthenticationScreen`, blocks refresh on a local
barrier, returns `credential_changed`, then proves the literal retry copy is painted,
the candidate is absent, `SuccessWidget` is absent, API-key input remains, and the
private verified dismissal credential is cleared.

### Surrounding green

```text
112 passed, 2 warnings in 4.07s
```

Nodes:

```text
tests/integrations/openrouter/test_client.py
tests/auth/test_openrouter_authentication.py
tests/tui/authentication/test_openrouter_authentication.py
tests/tui/test_slash_router.py
tests/tui/test_openrouter_startup.py
tests/tui/test_openrouter_picker.py
```

All pytest writes used fresh, resolved checkout-owned roots via `--basetemp`; `HOME`,
`SLO_HOME`, `SLO_AUTH_FILE`, and `TMPDIR` were private descendants. The harness used
`/root/.pyenv/versions/slo-harness/bin/python -B`, `env -i`, local synthetic transports,
`SLO_ENV=test`, `SLO_PLUGINS_DISABLED=1`, and no cache provider.

### Static/diff checks

```text
black --check --no-cache (five owner paths): 5 unchanged
git diff --check: exit 0
```

## Remaining limitations

- No full non-E2E suite, mypy, live provider, authenticated discovery, or paid inference
  ran; do not treat the focused result as Feature 86 completion.
- The count/check-time refresh result and direct pending-selection/unlisted-variant
  changes require their named catalog/session owners and remain outside Owner D scope.
- This correction keeps store-byte preservation, source precedence, no raw exception
  text, and current exact canonical route behavior intact.
