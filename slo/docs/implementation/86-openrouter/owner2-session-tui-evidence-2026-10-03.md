# Owner 2 — session/TUI/auth Step-1 evidence (2026-10-03)

## Scope and boundary

Owner 2 reviewed and corrected only the session/TUI/auth acceptance seams on the
existing dirty branch. No catalog/provider boundary source or tests were modified,
and no fixture/live-harness/current-status/implementation-log files were changed.
No Git staging, commit, push, reset, clean, rebase, worktree, installation, real
credential access, DNS/network, or paid/live provider request occurred.

All new test writes were under newly created, resolved checkout-owned pytest roots:
`$PWD/.owner2-session-tui-*/tests`; each command used the required Python 3.11.7
harness with `-B`, `PYTHONDONTWRITEBYTECODE=1`, isolated `HOME`/`TMPDIR`/`SLO_HOME`,
`-p no:cacheprovider`, and `timeout 1200`. Local synthetic HTTP/SSE `MockTransport`
remained the only integration transport.

Inputs reviewed before work: repository `AGENTS.md`, `SLO.md`, `CLAUDE.md`,
`docs/RESEARCH.md`; coding and Textual skills; KB `slo/README.md`,
`tui-cli-session.md`, `authentication-oauth.md`, and `feature-86-openrouter-status.md`;
immutable Feature 86 overview, dependency index, 86.a.4, 86.a.5 and 86.a.6; and
current independent/correction/remediation/implementation/status/remaining-requirement
records. The current correction source and tests were inspected before changes.

## Clauses and results

| Requirement | Exact governing clauses | Evidence/result |
|---|---|---|
| Refresh notice count/time | 86.a.5 §7.6: bounded count/time/status safe copy; overview §7.10: bounded success/failure/count/time message | `SloAgentSession.refresh_model_catalog()` now counts only OpenRouter entries that are both `visible_in_picker` and `availability == "available"`. This is the exact visible/eligible selection set—not raw cache membership, hidden rows, or tombstones. It keeps the catalog lifecycle's actual `catalog_checked_at`, or literal `unknown`; it does not manufacture a check time for `fresh`, failed, or credential-changed/coalesced outcomes. The router remains a pure session consumer. |
| Pending direct recovery | 86.a.4 §4: pending TUI allows `/auth`, `/model refresh`, **or choosing a direct model**, while prompts remain blocked; §7.4 atomic selection; overview §7.9 recovery behavior | Mounted and session tests prove a credentialed direct selection leaves the pending OpenRouter selection rejected, clears the pool, saves the preference only after commit, remains prompt-gated until ready, and cannot be overwritten by either a late startup success/failure or cancellation of the old startup worker. Runtime route, readiness, catalog snapshot, and lazy-agent invalidation are asserted. |
| Previous full-run painted-auth failure | 86.a.6 §7.1/§7.3 and §9 require mounted/local flow and functional gates; 86.a.5 §7.3 requires tracked modal task/safe painted outcome | Investigated all six nodes in the retained first `full-non-e2e.log`, rather than treating the auth node as isolated. Five were deterministic stale test contracts: one forbidden reasoning expectation; one duplicate catalog `load()` expectation; one AsyncMock without a returned snapshot; two startup mocks that only allowed the old OpenRouter route and rejected the newly permitted direct route. The sixth was the mounted auth assertion. Its trace establishes candidate verification, persistence, and listing completed, but the fixed twenty `pilot.pause()` polling loop did not observe the success compositor state. The later full gate and current exact module run passed, but that is not a root-cause proof. Twenty independent, fresh isolated runs of the exact mounted test also passed. No source fixture ordering/lifecycle cause was reproduced and no lucky rerun is called a fix. Residual evidence is therefore 20/20 isolated repetitions plus the later surrounding partition—not a causal attribution for the original order-sensitive miss. |

## Red → green test evidence

### 1. Count semantics

**RED** (new test before the correction):

```text
/root/.pyenv/versions/slo-harness/bin/python -B -m pytest ... \
  tests/agents/slo_agent/test_refresh_catalog_notice.py
2 failed, 7 passed, 2 warnings in 1.27s
```

Both `refreshed` and `fresh` cases reported `3 models` for one visible eligible
OpenRouter route plus a hidden route and a removed route.

**Correction:** `src/agents/slo_agent/sessions/service.py` filters the count by
OpenRouter provider, picker visibility, and `availability == "available"`.

**GREEN:**

```text
... tests/agents/slo_agent/test_refresh_catalog_notice.py
9 passed, 2 warnings in 1.11s
```

The tests cover fresh/refreshed/failed/credential-changed outcomes, empty catalog,
nonempty visible/hidden/removed catalog, actual check time, and unknown check time.

### 2. Pending direct selection and cancellation

Existing direct late-result test was extended with an explicit old-startup task
cancellation case; the mounted test proves the same path through `SloTUI` and its
tracked preparation worker. The implementation already satisfied this test prior to
its addition, so there was no production correction for this decision path.

```text
... tests/agents/slo_agent/test_pending_direct_recovery.py
3 passed, 2 warnings in 1.12s

... tests/tui/test_openrouter_startup.py
6 passed, 1 warning in 1.63s
```

No sleeps were added; the tests use `asyncio.Event` barriers and explicit task
cancellation.

### 3. Surrounding regression partition

```text
... tests/agents/slo_agent/test_refresh_catalog_notice.py \
    tests/agents/slo_agent/test_pending_direct_recovery.py \
    tests/agents/slo_agent/test_catalog_generation.py \
    tests/tui/test_openrouter_startup.py \
    tests/tui/test_slash_router.py \
    tests/tui/test_openrouter_picker.py \
    tests/tui/test_picker_status_publication.py \
    tests/tui/authentication/test_openrouter_authentication.py \
    tests/integration/test_openrouter_full_flow.py
122 passed, 5 warnings in 50.49s
```

This is not a full non-E2E suite; final integration owns that gate.

### 4. Intermittent mounted-auth investigation

The historical six-node inventory was read from
`.f86-remediation-retry-QS5PwP/full-non-e2e.log`; its auth traceback shows GET `/key`,
credential persistence, and GET `/models/user` completed before the paint assertion.
The current targeted partition containing all six original nodes passed:

```text
... test_openrouter_capability_recovery.py test_catalog_generation.py \
    test_openrouter_full_flow.py test_openrouter_startup.py
47 passed, 5 warnings in 46.95s
```

The exact mounted test was then run in 20 separate fresh isolated roots:

```text
20 iterations × tests/integration/test_openrouter_full_flow.py::
  test_mounted_openrouter_auth_picker_router_session_and_resume_flow
20 passed; each 2.80–3.06s, 5 warnings
```

This quantifies non-reproduction only. It does not establish that the historical
failure was fixed, and no test assertion, sleep, retry count, skip, or xfail was
weakened.

## Files changed by Owner 2

- `src/agents/slo_agent/sessions/service.py`
  - Count semantics for the public `/model refresh` notice.
- `tests/agents/slo_agent/test_refresh_catalog_notice.py`
  - Exact eligible/visible count, unknown time, and outcome coverage.
- `tests/agents/slo_agent/test_pending_direct_recovery.py`
  - Direct-selection preservation when the old pending startup is cancelled.
- `tests/tui/test_openrouter_startup.py`
  - Mounted direct positive escape/cancelled-old-worker lifecycle evidence.
- `docs/implementation/86-openrouter/owner2-session-tui-evidence-2026-10-03.md`
  - This truthful Owner-2 evidence report.

`git diff --check` passed after the work. Static formatting/mypy were intentionally
not run because the user waived those gates.

## Limitations and verdict

**REVISE.** Owner-2 session/TUI/auth acceptance is locally ready for the corrected
count semantics and controlled pending-direct behavior, but Feature 86 cannot be
called ready here: this owner did not run the full suite; the historical mounted-auth
paint miss has not been causally reproduced or fixed; and the finite Feature-86
requirements outside this owner remain for the integration owner. The original
intermittent is retained as an unresolved reliability signal, not erased by a green
rerun.
