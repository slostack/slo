# Recovery 12 — actual complete gates, REVISE

Branch `feature-gpt_6_support`, HEAD `ea8601c53f04fa06a0baeeb47d385c44cc9a5364` retained. No commits, resets, installs, external calls, agent launches, specification/shared-KB writes. Parent dispatch budget not reset.

## Changes and actual verification

- Extended the existing real v0.20.1 tree/flat rollback-history test over all four Feature89 saved route IDs, retaining the old OpenRouter case. It asserts exact ordered pre/post rollback transcript and unchanged existing events. This tests durable readability/append compatibility, not inference on the released version. Focused `recovery12-compat`: 12 passed; surrounding `recovery12-compat-surrounding`: 31 passed, including real observer zero catalog/auth accesses and isolation tests. All exit 0. No production-red claimed for this additional acceptance.
- First complete gate: **9 failed, 5955 passed, 18 deselected, 267 warnings**, exit 1 (`recovery12-full`). Eight failures corrected without weakened assertions:
  - Four Feature89 store-driven selection cases saw stale `config.cfg.__cfg__['OPENAI_API_KEY']` left by earlier config reload tests. Their module now isolates that fallback plus the environment key. Provider-before-selection regression partition: **440 passed**, exit 0 (`recovery12-selection`).
  - Three old picker fixtures returned `object()` where lifecycle capture now requires a CredentialDAO/auth_type. Replaced those fixtures with synthetic typed credentials, keeping paint/cache assertions: **48 passed**, exit 0 (`recovery12-picker`).
  - Canonical `ModelCatalogEntryDAO` import leaked the forbidden old picker namespace. Use the canonical module-qualified annotation, not a competing entity name. Identity/module partition: **28 passed**, exit 0 (`recovery12-identity`).
- Fresh complete post-correction non-E2E gate: **1 failed, 5963 passed, 18 deselected, 275 warnings in 403.07s**, exit 1 (`recovery12-full-final`). Exact remaining node:
  `tests/cli/test_release_automation.py::TestReleaseAutomation::test_gitlab_hosted_release_jobs_override_default_e2e_deselection_and_collect_the_smoke`.
  Its real `subprocess.run(['poetry', 'run', 'pytest', ... '--collect-only'])` raises `FileNotFoundError: [Errno 2] No such file or directory: 'poetry'` under the approved env-i PATH. No dependency installed or substitute stub introduced. This is NOT a green full gate.

All receipts are `.f89-evidence/<name>.command/.log/.exit`. Timeout 1800 used. Prior counts are not summed. Existing 21 SDK, mounted/resume, independent fallback, committed-failure, cancellation, headless and compaction tests ran in both full gates; no duplicate replacement tests.

## Fresh static and integrity gates

`.f89-evidence/recovery12-static.py` records the exact expanded invocations and extracts actual frozen HEAD using regular-file/directory containment checks; no worktree or installation.

- `recovery12-black-changed`: **39 changed Python files clean**, exit 0.
- `recovery12-black`: **14 files would be reformatted / 653 unchanged**, exit 1, UNWAIVED.
- `recovery12-baseline-black`: frozen HEAD **19 files would be reformatted / 635 unchanged**, exit 1. All 14 current paths are in that baseline set; five baseline paths were already formatted in changed work.
- `recovery12-mypy`: **296 errors / 59 files / 667 checked**, exit 1, UNWAIVED.
- `recovery12-baseline-mypy`: **296 errors / 59 files / 654 checked**, exit 1. Exact diagnostic multisets after removing line numbers have **zero added and zero removed** occurrences, not merely equal totals. See `recovery12-static-comparison.json`.
- `recovery12-diff`: `git diff --check`, exit 0, empty.
- `recovery12-integrity`, and checks after both full suites: `dpkg -V coreutils`, exit 0, empty.
- `recovery12-versions.log`: actual interpreter and every installed distribution versus poetry.lock; OpenAI 2.38.0, Pydantic 2.13.4, LangChain OpenAI 0.3.35/core 0.3.86. Existing `.f89-evidence/venv` only.

## Acceptance audit boundaries

AC11 now has actual Feature89 saved-ID released tree/flat append/read proof plus passing existing auth/cache coexistence and observer tests. Pre-feature schema2 writer and frozen legacy matrix proof remains in `test_feature89_frozen_reader.py`, also passed in full gates. These distinct readers are not interchangeable.

AC4 retained constructor matrix checks four model/level policies × eight temperature inputs × five cap cases, exact parsed answer and unchanged extras; streamed 21 cells exercise bound top-level and late-body forbidden fields and exact SDK tool roundtrip. Legacy four-case temperature oracle and shallow custom-endpoint cases remain intact. No new transport implementation.

CLI audit: `test_app.py` covers actual Typer parsing of resume ID/name and workspace combination; `test_typer_dispatch.py` covers reference delegation and actionable missing reference; `history/test_filesystem_store.py` covers exact ID precedence, normalized name, unknown reference; Feature89 entry-path tests cover canonical model/preference/pool precedence and actual child parser, and mounted flows use real CLI metadata/config owners. These are compositional assertions, not one new full-command-to-inference resume test.

AC1/7/8 finite source-to-assertion audit is not fully closed: existing exact seed/memory/disk, lifecycle revision, mounted auth and pinned-generation assertions passed, but this turn did not finish a branch-by-branch proof for every cache-key invalidation case. Do not infer closure solely from the passing full-suite cases.

## Read/safety qualification

Fresh full reads: supplied headless instructions, actual AGENTS/CLAUDE/root+docs RESEARCH, all seven final specs, formal workflow, Step1 cadence and four always-on skills, application-service/client/graph-testing skills, config and SkillsLoader, user skill names (no selected-name override), relevant KB Welcome/slo README/gotchas/model-pool, recovery9/10/11, discovery receipt and approved HIGH plan. Additional TUI-layer skill was not freshly loaded before the annotation-only namespace correction; no full convention-completion claim.

Read run-test.sh, synthetic tests.env, preimport/pertest isolation and released/observer fixture owners. Inspected command-stub wrappers, installer/update/launcher write targets, symlink searches and child default-deny hooks. No additional concrete escape was established. This was targeted source safety inspection, not an exhaustive proof of every test write. The two full executions completed; no host anomaly observed and coreutils unchanged. Do not describe the incomplete exhaustive audit as completed.

## Decisions required / remaining work

**REVISE, not READY or functional-complete.** Resolve the missing-Poetry collection environment through an explicitly approved existing-tool invocation or narrow test portability correction (no install), then rerun full gate. The 296/59 mypy and 14 Black baseline failures require explicit baseline-fix scope or explicit waiver; none exists. Do not broad-fix or count baseline equivalence as green. Complete finite AC1/7/8 audit and support documentation scope. Independent reviewer remains separate kimi-k3 max, not yet dispatched; assessor unassigned is not the current blocker.
