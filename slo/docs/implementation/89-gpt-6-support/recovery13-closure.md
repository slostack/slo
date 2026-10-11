# Recovery 13 — inline Step 1 closure ledger

Branch feature-gpt_6_support, HEAD ea8601c53f04fa06a0baeeb47d385c44cc9a5364 preserved. No spawning, installs, commits, external changes, specification or shared-KB outputs. Independent reviewer kimi-k3/max is pending; assessor is unassigned and not yet reached. REVISE, not READY.

## Correction and finite audit

Retained red: recovery12-full-final reports FileNotFoundError for poetry before real E2E collection. The CI command string remains asserted verbatim. Only the local subprocess now invokes sys.executable -m pytest with unchanged -o addopts=, -m e2e, --collect-only and exact 2/6 collection assertions. This executes the current locked pytest, not a success stub or installer. Focused: 1 passed; surrounding release/hosted module: 20 passed, 2 E2E deselected. Both exit 0. Coreutils verification empty/0.

AC1 source/assertion audit: seed test compares complete identity/runtime/reasoning profiles for all three entries; source-registration test counts calls before dictionary collapse and rejects future/datestamped family matches and Jev seed. Defaults projection compares every runtime field plus temperature and override removal. No further redundant matrix added.

AC7/8 finite cache audit found missing discriminating assertions for each cache-key component. Added five cases to test_feature89_presentation.py: same-key hit (detached list, identical cached rows); snapshot identity with unchanged generation; generation with identity isolated; active route; auth revision; lifecycle revision. Each invalidation rebuilds exactly once; subsequent row reads do not resolve credentials. Authentication clearing removes cached types. Focused 5 passed; surrounding presentation/status/model catalog: 80 passed. These are added acceptance assertions against existing correct behavior, not claimed production-red fixes.

Retained AC7 evidence: three unique direct rows, missing/API-key/OAuth projection, missing/incompatible cropped paint, direct keyboard selection and admitted Jev keyboard/provider-default paint at 60x20 and 120x40; existing eight-row window regression unchanged. Retained AC8: override candidates schema-validated before delegated guard, cold/refresh nonpublication, both flags through alias/copy/metadata/merge/removal and writer-only exclusion; SDK A/B runtime/reasoning pinning, session A/global B switching, startup Event-barrier A/B mounted marker-once proof. Cache-key additions close the identified finite assertion gap; independent review remains required.

## Safety audit before full execution

Read approved runner, synthetic tests.env, pre-import state isolation and per-test conftest. Inventory retained in .f89-evidence/recovery13-safety-inventory.txt (1345 search hits including comments/non-write references), recovery13-symlinks.txt, recovery13-write-audit.txt. Inspected all symlink sites and risk-bearing owners: FakeBin, launcher layout/writer, update finalizer, release/deploy tests, hosted/wheel opt-in gates, git-diff escape fixture, bash spill/escape helper, frozen archive runner, capture child default-deny and process wrappers, temporary plugin git fixtures, catalog/credential isolation and mounted fixtures.

No system-target symlink was found: fake Python targets are regular scripts under tmp_path, including the deliberately external-to-venv targets; real interpreters are exec'd by wrappers. Capture outside-write negative is rejected by the installed child audit hook before open; bash escape test only resolves/rejects and never writes through the link. Corrected git-diff escape stays within tmp_path while outside tmp_path/repository. Release dry runs do not execute publication; invalid-tag execution rejects before git; deploy curl stubs fail before WORKDIR creation/publication. Hosted/wheel/install real E2E bodies remain excluded and collection alone does not execute fixtures. No real provider credential is available in env-i; provider acceptance uses synthetic injected transports. Existing local-loopback auth tests are not provider calls. Terminal spawn seam remains suite-stubbed.

This completes the finite source risk inventory for the intended non-E2E command; it is not a formal proof of arbitrary Python/shell execution, nor a retroactive exhaustive-safety claim for recovery12. Prior full counts establish execution only. No newly identified unsafe original was executed in this continuation. Tests use owned temporary fixture roots; runner receipts live in the approved worktree evidence directory. No runtime-parent timeout/model claim is made by shell exports.

## All fifteen acceptance criteria — evidence map

Paths abbreviated below are under tests/.

| AC | Source/assertion evidence and qualification |
|---|---|
| 1 | agents/model_catalog/test_model_catalog_seed.py, test_catalog_integrity.py; agents/test_ai_model_config.py exact rows/defaults/no Jev/template |
| 2 | agents/test_feature89_reasoning.py: 21 cells, defaults/highest/invalid and legacy omission |
| 3 | agents/providers/test_openai_platform.py real SDK 21 streamed echo cycles; integration/test_feature89_model_flows.py six mounted direct off/medium cycles |
| 4 | test_openai_platform.py protected keys, cap aliases, include/sampling, constructor temperatures and unchanged inputs; frozen legacy temperature oracle distinct |
| 5 | agents/providers/test_feature89_credentials.py captured key/env precedence; agents/slo_agent/test_feature89_selection.py atomic final race, sync switch and lazy pre-refresh rejection |
| 6 | integration/test_feature89_entry_paths.py explicit/default/preference/pool/child precedence; test_feature89_model_flows.py fresh-session replay. CLI parsing/resume reference owners compose with these, not a newly claimed single subprocess-to-inference proof |
| 7 | tui/test_feature89_presentation.py lifecycle auth/unique rows/two-size paint and keyboard; existing bounded-window suites retain eight-row assertion |
| 8 | model_catalog/test_backend_eligibility.py, test_model_catalog_overrides.py, test_cache_file_separation.py; Platform pinned clients; session snapshot tests; startup barrier and new five cache invalidations |
| 9 | integration/test_feature89_capacity.py total context, override, advisory TPM, real reserved-cap manual summary; unchanged threshold regressions |
| 10 | integration/test_feature89_model_flows.py independent mixed transports, four committed-error cases and cancellation; existing watchdog/stream recovery surrounding tests |
| 11 | model_catalog/test_feature89_frozen_reader.py exact pre-feature schema-2/legacy oracle; compat/test_session_resume_mixed_versions.py real v0.20.1 tree/flat append across all four saved IDs; existing auth/cache coexistence and CLI observer zero-access proof |
| 12 | frozen old seed/alias/profile and temperature expectations plus existing complete non-E2E regression suite; static gates remain RED UNWAIVED |
| 13 | model_catalog/test_openrouter_converter_metadata.py full Jev metadata, null/absent safe cap, strict malformed and independent eligibility gates |
| 14 | integration/test_feature89_model_flows.py real admitted Jev echo/resume/private anchor/public scan, separate keys/transports and both mixed orders |
| 15 | model_catalog/test_feature89_jev_lifecycle.py rotation/removal/expiry/incomplete/stale constraints; entry-path/headless/child/resume admission and mounted provider-default wording |

The map is implementation evidence, not independent feature approval. Provider fixtures are offline synthetic, never live availability/entitlement or paid inference.

## Support documentation

README now documents exact IDs, credential lanes, fresh medium/off differences, total context/local caps, metadata-only pricing/rates and authenticated refresh for old Jev cache. AGENTS.md and both RESEARCH entries now describe the actually wired adapter/session/projection and writer exclusion instead of stale partial-construction claims. No new pricing, provider, migration, command or fallback scope.

## Final execution receipts

Actual post-source/test/support-doc full gate: **5969 passed, 18 deselected, 267 warnings in 410.71s; exit 0**. Receipt: `.f89-evidence/recovery13-full-final.{command,log,exit}`. Command: `/bin/bash .f89-evidence/run-test.sh recovery13-full-final -q -m 'not e2e'`. The runner uses env-i, synthetic tests.env and `/root/Code/slo-gpt-6-support/slo/.f89-evidence/venv/bin/python -m pytest`. Tool timeout 1800; shell guards 10800/7200, not claimed parent-runtime changes. No new skips or weakened assertions.

Fresh static runner: `env -i PATH=/usr/bin:/bin HOME="$PWD/.f89-evidence/home" TMPDIR="$PWD/.f89-evidence/tmp" PYTHONDONTWRITEBYTECODE=1 .f89-evidence/venv/bin/python .f89-evidence/recovery13-static.py`. Exact expanded changed-file list and each frozen/current command retained in individual .command receipts.

- Changed Python Black: **40 files clean**, exit 0.
- Full `python -m black --check --line-length 110 src/ tests/`: **13 would reformat, 654 unchanged**, exit 1, UNWAIVED. Frozen HEAD: 19 would reformat/635 unchanged. All 13 current paths are in the frozen set. Reduction from prior 14 is only the now-touched release test's existing slice-spacing line; no unrelated baseline files formatted.
- Full `python -m mypy --cache-dir <owned-temp> src/ tests/`: **296 errors in 59 files, 667 checked**, exit 1, UNWAIVED. Real frozen HEAD: **296/59, 654 checked**. Normalized exact diagnostic multisets have zero added and zero removed occurrences (`recovery13-static-comparison.json`).
- `git diff --check`: empty, exit 0. `dpkg -V coreutils`: empty, exit 0 after full and static runs.
- Versions freshly compared: Python3.11.7, OpenAI2.38.0, Pydantic2.13.4, LangChain OpenAI0.3.35/core0.3.86, httpx0.28.1, Textual8.2.8 match lock. Installed application/test distributions match; bootstrap pip/setuptools have no poetry.lock entry and are reported separately, not treated as locked dependencies.

Functional gate is green. Step1 remains **REVISE** solely at required static gates; baseline equivalence is not a waiver. Operator decision: explicitly waive these exact attributed baseline Black/mypy failures for Feature89, or authorize a separate scoped baseline repair and repeat gates. No additional functional busywork is requested. Independent reviewer kimi-k3/max has not run and cannot be self-approved; fresh assessor assignment is requested only after review is reached/completed. Final report-only ledger update follows the executed gates; no production/test/support-document change afterward.
