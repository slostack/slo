# Feature89 successor dispatch 3 — bounded picker correction

**NOT READY.** Dirty branch retained; no install/reset/commit/publication/nested orchestration. Existing locked interpreter and env-i run-test.sh only.

## Actual work

- Added mounted Jev display-name search and down/Tab/Enter canonical selection at 60x20 and 120x40, with real authenticated GET preparation, cropped compositor checks for provider-default/control text, context and footer.
- Added missing-key versus OAuth direct-row cropped paint at both sizes, with real temporary credential-store reads.
- Found the TUI-wide autouse credential fake was replacing `CredentialResolver.resolve`. This file now restores the captured real method before its tests: existing startup/admission tests also now run with real resolution. Prior synthetic GET evidence alone did not establish that resolver composition.
- Actual production red: Jev unknown-control text clipped at BOTH sizes; narrow OAuth status clipped context. `SlashSuggestionMenu._detail_for_terminal` now separates these status/context/provider/reasoning fields. Ordinary direct rows keep the existing two-line capacity; eight-row compositor regression passes unchanged.
- Updated three existing suggestion tests from `object()` credential stubs to typed synthetic CredentialDAO responses. Assertions unchanged.

## Executed receipts

All prefixes below are `.f89-evidence/successor3-`, with `.command/.log/.exit`:

| Suffix | Result |
|---|---|
| jev-paint-red | 2 failed: actual clipped provider-default text |
| jev-paint-green | 2 passed, 36 deselected, 2 warnings |
| picker-surrounding | exit4: mistakenly named nonexistent test_slash_suggestions.py; no tests ran |
| picker-surrounding-corrected | 3 failed,54 passed: preexisting object credential stubs incompatible with typed auth projection |
| picker-surrounding-green | 57 passed,2 warnings |
| auth-paint-red | 4 failed: TUI autouse resolver fake masked temporary credentials |
| auth-real-red | 1 failed,5 passed: real narrow OAuth context clipping |
| paint-surrounding-final | **61 passed,2 warnings,exit0** |

`git diff --check` passed; `dpkg -V coreutils` returned no output. No command-stub suite ran. Full non-E2E not run, safe full-suite stub inspection not completed. Canonical changed-file Black attribution and mypy296 baseline remain unresolved/unwaived; no fresh formatter/type gate claimed. No independent review or assessment.

## All15 AC residuals

1. Four-route identity/disk composition still pending.
2. Full frozen legacy reasoning matrix pending.
3. Prior21 SDK cycles retained; mounted tool/history/resume pending.
4. Remaining malformed/legacy/custom-endpoint request-policy matrix pending.
5. Preparation-error/cold-gateway and remaining lazy/synchronous branches pending.
6. Fresh/default/saved/switch/resume/child composition pending.
7. Added genuine Jev keyboard and cropped provider-default/context/footer plus direct missing/OAuth paint. Remaining cache-invalidation branches and broader mounted acceptance pending.
8. Existing startup tests now use real resolver; broader generation coverage pending.
9. Summary reserved cap/context/advisory composition pending.
10. Mixed fallback/committed-output/cancellation/watchdog acceptance pending.
11. Released coexistence/observer acceptance pending.
12. Focused61 green, not full-gate or static readiness.
13. Prior real converter/admission proof retained.
14. Prepared Jev tool cycle and both mixed-pool directions pending.
15. Jev picker now uses real resolver/admission; headless/child/resume composition pending.

## Next substantive action

Close preparation-error/cold-gateway selection and synchronous/lazy guard tests in `tests/agents/slo_agent/test_feature89_selection.py`; then finish strict/legacy request-policy matrix before adding e.1 composed mounted tools/history/resume. Do not repeat solved picker proofs or substitute focused counts for the final full non-E2E/static gates. This dispatch did not reach e.1.
