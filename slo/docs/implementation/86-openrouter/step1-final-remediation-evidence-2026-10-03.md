# Feature 86 — final Step 1 remediation, Call 3 of maximum 4

Date: 2026-10-03. **Verdict: REVISE.** Backend model identity is not exposed by this session; no model label is invented. Independent review and Step 3 remain pending. This is not feature completion or approval.

## Scope and preservation

Preserved all accumulated dirty/untracked work. No Git mutation, specification edit/link repair, workflow launch, installation, environment/skill modification, live provider/network/credential/inference operation, or system/PATH write was performed. The checkout specification link is absent; immutable contracts were read directly at `/root/Code/specifications/projects/slo/specifications/86-openrouter-intergration/`. Owner5's report was absent and reported immediately; owner4 and owner6 reports and actual relevant code/tests were inspected.

Only three test files changed in this call:

- `tests/tui/authentication/_painted_output.py`: added a positive complete-message assertion over the widget's viewport-clipped compositor cells.
- `tests/integration/test_openrouter_full_flow.py`: sensitivity mutation on all eight actual auth error cases; real GET/catalog/session/router/paint refresh composition at both sizes.
- `tests/tui/authentication/test_openrouter_authentication.py`: listing-time credential-change test now covers 80×24 and 60×15 with widget-scoped positive paint plus full-viewport candidate/raw-marker absence.

No production correction was necessary for these bounded paint paths.

## Four Call 2 gaps

1. **Suppressed-paint sensitivity verified.** Each unauthorized/forbidden/protocol/timeout case at both sizes first positively checks the complete safe message. Test-local visibility suppression preserves `Static.render()` text while requiring the exact same positive compositor assertion to raise. A `finally` restores visibility and positive paint is rechecked. No screen-wide border concatenation is used for the positive assertion; whole-screen reads remain for secret absence.
2. **Credential-change dimensions verified.** Both mandated sizes pass. The real auth service and local verification client consume a barrier-controlled catalog credential-change result; no success widget/verified dismissal credential survives. This is a controlled catalog outcome, not a newly claimed real environment rotation test.
3. **Refresh composition verified.** Local GET `/key` and `/models/user` feed the actual converter/store/catalog, `SloAgentSession.refresh_model_catalog`, SlashRouter and mounted SloTUI. An event blocks listing until released; the dispatch task is awaited, not timed with sleeps. Count is exactly one, time is the actual complete-check timestamp, requests are exactly the two GETs, active direct route is unchanged, and viewport excludes the synthetic key. At 80×24 the complete safe notice paints together. At 60×15 the ordinary transcript viewport shows the first line and native scroll-end exposes the timestamp line; assertions cover both, without changing layout or truncating messages. This does not claim simultaneous visibility of the entire notice at 60×15.
4. **Bounded contract-reading reconciliation performed.** All six actual engineering contracts were read individually without combined-output truncation, including implementation, tests, acceptance, and dependency sections. Request was read in two bounded ranges; dependency index through its ownership/DAG/checkpoint sections; overview targeted §§7.1–7.6, 7.10a–7.12 and traceability. This is bounded relevant-clause reconciliation, not a claim of exhaustively rereading every historical ledger or unrelated overview paragraph.

## Original five corrections: independent inspection and limits

| Original finding | Exact contract | Current source/test evidence |
|---|---|---|
| G1 stale unchanged async read | overview §§7.4–7.5; a.2 §7.4; a.4 §7.3 | `ModelCatalogService._adopt_current_openrouter_slice` now routes equal entries through `_revalidate_unchanged_admission_snapshot`: identity checks before/after the second await, changed publication adoption, durable-view comparison. Public prepare barrier tests cover newer removal and credential rotation; affected catalog suite passes. **Qualification:** owner4's first-read barrier returns synthetic cache DAOs, not real disk bytes despite its report wording; its declared cache path is not written in those two tests. Do not claim those tests independently prove real-disk timing. |
| G2 reasoning semantics and request rejection | overview §7.3 truth table; a.2 §7.2; a.3 §7.2 | Converter separates known enabled efforts from explicit disable permission; default effort no longer depends on mandatory being supplied. Factory/policy forward disable-only control. Actual SDK off-wire matrix covers none-only, absent/null, advertised/unadvertised and mandatory clamp. Capability tests reject zero/negative/bool/above-cap before credentials/client and reject invocation overrides before HTTP. **Qualification:** the test named `test_default_effort_without_disable_permission_transmits_advertised_effort` asserts resolver state only, not transmitted HTTP; do not repeat the stronger owner-report claim. |
| G3 mounted auth/refresh paint | a.1 §7.2; a.5 §§7.2–7.3,7.6,8.2; a.6 §§7.1–7.3 | Actual safe auth error categories, unchanged store bytes/session, restored retry state, suppression sensitivity, credential-change both sizes, and composed refresh count/time now asserted. |
| G4 picker decomposition | overview §7.10a; a.5 §§7.4–7.5,8.3 | Actual diff shows `_model_argument_state` delegates ordering, bounded rows and `_bounded_model_state`; `_matching_model_entries`, `_empty_query_entries`, recent lookup and ranking remain in existing engine. Existing caps/rank/offset/ghost/viewport tests pass in affected partition. No new picker owner. |
| G5 current documentation | overview §7.12; a.6 §§7.5–7.6,9 | Owner6 current-facing summaries accurately label 5115 as retained pre-correction evidence, static waiver as waiver, offline tests as non-live, and review as REVISE. This call's canonical status/remaining/log updates record the newer failed gate without rewriting historical reports. |

Dependency reconciliation: a.1 identity/client feeds a.2 catalog and a.3 transport; a.4 joins preparation/pinning; a.5 consumes those owners; a.6 owns integration/evidence/docs. No new owner, remote procedure, gateway, retry loop or feature matrix was introduced. Historical capture/Plan B/argv topics were not rerun.

## Exact execution evidence

Fresh owned root: `.f86-current-step1-final-Ga9R1J/`.
All pytest commands used this prefix (with each named fresh basetemp):

```text
env -i PATH=/root/.pyenv/versions/slo-harness/bin:/usr/bin:/bin
HOME=<root>/home TMPDIR=<root>/tmp SLO_HOME=<root>/slo
SLO_AUTH_FILE=<root>/slo/auth.json PYTHONDONTWRITEBYTECODE=1
SLO_AUTO_VISUALIZE=0 PYTHONPATH=<checkout>
/root/.pyenv/versions/slo-harness/bin/python -B -m pytest -q
-p no:cacheprovider --basetemp=<root>/<run>-base <nodes> --tb=short
```

- `red.log`, exit 1: `tests/integration/test_openrouter_full_flow.py -k rejected`, **8 failed, 3 deselected**. New required assertion facility was intentionally absent.
- `sensitivity.log`, exit 1: same nodes, **8 failed**. Initial `patch.object` restoration could not delete Textual's style descriptor (`AttributeError: __delete__`). Replaced with explicit test-local try/finally restoration.
- `sensitivity-green.log`, exit 0: same nodes, **8 passed, 3 deselected, 2 warnings**, 4.59s. Hidden-paint failures are expected and caught; restored positive paint passes.
- `auth.log`, exit 0: `tests/tui/authentication/test_openrouter_authentication.py`, **13 passed, 2 warnings**, 2.59s.
- `refresh.log`, exit 1: `tests/integration/test_openrouter_full_flow.py -k refresh_paints`, **2 failed** because the unrelated first-run direct-provider auth modal covered the transcript. The test now cancels that modal through its ordinary action before refreshing.
- `refresh-green.log`, exit 1: **1 failed, 1 passed**; small transcript notice outside viewport.
- `refresh-visible.log`, exit 1: **1 failed, 1 passed**; scroll-visible showed first notice line but not timestamp.
- `refresh-scroll.log`, exit 0: **2 passed, 11 deselected, 2 warnings**, 2.06s. Native scrolling exposes the complete second line; no production change.
- `surrounding.log`, exit 0: **505 passed, 1 deselected, 5 warnings**, 31.28s. Nodes: full-flow module; `tests/tui/authentication`; picker_g8/openrouter_picker/picker_viewport_acceptance/slash_suggestion_engine/slash_router; `tests/agents/model_catalog`; provider reasoning_semantics/capability_recovery; session refresh_catalog_notice.

### Fresh complete non-E2E gate — FAILED

Exact expanded command is in `full-command.txt`; complete output in `full-non-e2e.log`; `full.exit` contains **1**. Uses separate `full-home`, `full-tmp`, `full-slo`, `full-base`, with the same clean environment and approved interpreter, `-m 'not e2e' tests`, tool timeout 1200 seconds.

```text
FAILED tests/tui/test_selection_scroll_highlight.py::TestPilotVisibleSelection::test_selection_paint_and_scroll_remain_native_for_every_visible_body_and_theme[slo-default-thinking]
E   AssertionError: offset Offset(x=6, y=0) was not visible
1 failed, 5124 passed, 18 deselected, 196 warnings in 333.61s (0:05:33)
```

No source/test edits followed this gate. No random retry or unrelated selection fix was attempted. The failure is not dismissed as flaky or claimed pre-existing solely because its node appears in historical records.

`git diff --check` passed. Post-suite read-only coreutils verification exited 0 with an empty log. Black/mypy were not run and are waived, not green. Ordinary 18 E2E exclusions remain; executed OpenRouter evidence is synthetic/local, not live authorization, availability or paid inference proof.

## Handoff

**REVISE**, not STEP1READY: the current complete non-E2E gate is red. Preserve its exact failure for bounded isolation in the remaining authorized call. The two G1/G2 evidence qualifications above also prevent treating owner-report prose as stronger independent proof than the actual assertions. Review and Step 3 remain pending.
