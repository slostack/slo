# 86.b recovery plan — preparation only

Date: 2026-10-04

## Verdict and scope

**READY to begin 86.b.1 using the isolated red-test procedure below.** This is preparation readiness, not an implementation, test-pass, independent-review, or feature-completion claim.

- Authoritative working directory: `/root/Code/slo-openrouter-implementation/slo`.
- Verified branch: `feature-86-openrouter-implementation`.
- Parent harness directory `/root/Code/slo/slo` was not used for commands or edits.
- This phase changed only this new plan. No tests, application imports, provider requests, installation, Git mutations, or real user-state reads/writes were performed.
- No delegation was attempted. The deterministic parent owns sequential b1 → b2 → b3 → b4 → b5 dispatch and any independent review, retries, and completion assessment. Missing delegation tools are **not** a blocker.
- The user-approved defaults apply: one additional-provider credential file with a closed-enum future-provider constraint; fallback notice in the existing startup block.

The problem is shared state across released/new Slo, not OpenRouter runtime redesign. Preserve all prerequisite 86.a code. Do not introduce another store/catalog/resolver, change pool precedence, add automatic migration/cleanup, or alter publication/admission semantics.

## 1. Baseline reconciliation and concurrency

Preserve the complete directory:

`/root/Code/slo-openrouter-implementation/slo/docs/implementation/86b-model-catalog/20261004T014228Z-d4346f44/`

| Evidence | Result of this phase's read-only check |
|---|---|
| `baseline-manifest.json` | 817 entries; all current file hashes, modes, and links match |
| `baseline.tar.gz` | 817 members; every regular member hash matches its manifest and the live file |
| New untracked source/tests/config/docs/skills/environments outside excluded evidence | None |
| Manifest SHA-256 | `ba4cd8f2927443a96ebf054fe1acc5722dcc6fd32ef39748b4495b3034f93c1e` |
| Archive SHA-256 | `a6aa0e12cfe5ecb387f7efe25089afcfdb4fa136cb3c11e401ff98bc69ad46fa` |
| Released `v0.20.1^{commit}` | `f63df0a4958eedb4bc603f1946ba4591dd181fff` |
| Existing `recovery-plan.md` before writing | Absent |

The baseline is still valid. There are **zero reconciled implementation differences** since it was captured. Existing large HEAD-relative changes, untracked source/test files, old test roots, `.cache/`, and previous reports are prerequisite work, not 86.b work. The baseline intentionally excludes old implementation evidence, untracked scratch roots, and bytecode; do not claim those were exhaustively compared.

Repeat this comparison before each phase's first edit. Later differences must match earlier phase reports; stop on unexplained changes. Before every edit, reread the actual target and compare its hash with the phase-start reading. Review incremental changes against the archive/manifest, not just HEAD. Never extract the archive over the live checkout. New files absent from the manifest belong in the incremental inventory; preserve all unrelated files.

## 2. Required context loaded

Consulted the target's `AGENTS.md`, `SLO.md`, root `RESEARCH.md`, and `docs/RESEARCH.md`. No nested `AGENTS.md` was found under `src/` or `tests/`; no ancestor AGENTS/SLO files were found at the repository root or `/root/Code`.

Read fully from `/root/Code/specifications/projects/slo/specifications/86-openrouter-intergration/model-catalog/`:

- `overview.md`
- `86.b.1-isolate-test-slo-home.md`
- `86.b.2-separate-catalog-cache-file.md`
- `86.b.3-split-additional-provider-credentials.md`
- `86.b.4-resume-falls-back-on-unknown-model.md`
- `86.b.5-prove-mixed-version-compatibility.md`

Confirmed the vendored skill tree, installed tree `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`, and personal `/root/.slo/user_skills` exist. Personal listed skills are Go/TypeScript/presentation rather than this Python task. Consulted vendored workflow and conventions:

- `design-and-analysis/workflows/code-test-review.md`, `workflows/SKILL.md`
- `coding/code-test-loop`, `named-arguments-and-type-hints`, `declarative-method-structure`, `method-docstrings`, `test-verification-policy`
- `design-and-analysis/gather-feature-context`, `review-feature-code`, `is-the-feature-completed`
- `coding/setup-dependencies-and-tests`, `switch-environments-and-run-tests`, `test-domain-services`, `test-app-services`, `test-graphs-and-agents`
- `cli/build-cli-command-class`, `tui/build-textual-tuis`

This is a filesystem-backed Python harness, not a PostgreSQL application. Generic DB/Docker/bootstrap examples do not authorize installation, service changes, or migrations. Existing project owners and the specific 86.b contracts take precedence. Implementation children must reload the phase/layer skills applicable to the code they write (including `cli/build-typer-cli-apps`, persistence/auth conventions, and review's `coding/code-review-rules` hard-rules pass when applicable). No layer implementation was written here.

Consulted KB entries:

- `KB/slo/gotchas.md`: fail-closed credential redaction; actual tree store delegates to flat `events.jsonl`; state and CLI boundaries.
- `KB/slo/feature-86-openrouter-status.md`: prerequisite limitations are not new 86.b scope.
- `KB/slo/model-catalog-before-after-and-visualize-error.md`: incompatible file ownership; old validation happens before schema-version rejection.
- `Reinforcement/tests-insulated-by-ambient-environment.md`: test ancestry and hostile-environment verification.
- `Reinforcement/self-updater-runs-the-old-code-once.md`: cannot repair released behavior by changing only new reader assumptions.

No KB updates were made: this phase permits report/plan writes only.

## 3. Actual current owners and defects

Paths in this section are relative to the authoritative working directory.

| Area | Inspected owner / current behavior | Required change |
|---|---|---|
| Isolation | `tests/conftest.py` has only plugin-enable and terminal-spawn guards; no HOME/SLO_HOME isolation. `config/cfg.py:167` binds HOME/state once. | Add pre-import suite seam and per-test fixture, not production changes. |
| Import copies | AST read-only scan confirms exactly the 11 module-level bindings listed in b1, including OAuth lock owner `src/auth/credential_refresher.py`. | Keep one binding registry and AST guard. |
| HOME consumers | `src/auth/credential_resolver.py:45` fixes Claude path at import; `sessions/service.py:_load_plugins` uses `Path.home()/.slo/plugins/plugins`. | Isolate before imports as well as before each test. |
| Title test | `tests/tui/test_app.py:482` computes `Path.home()` in parametrization. | Use templates resolved inside test body after per-test HOME changes. |
| Catalog | `src/agents/model_catalog/store.py:33,38` names released `.json/.lock`; `load_provider_cache` logs `log_error` on corrupt input. | Only `.v2.json/.v2.lock`; one warning, no traceback. |
| Dead readers | Store `load_cache`, `is_cache_fresh`; service `_should_refresh_discovery` only references the obsolete freshness method. Source search found no active callers. | Delete these, TTL/import dependencies, and only their five obsolete tests. |
| Catalog lifecycle | `service.py:_load_snapshot` uses `load_provider_cache`; refresh owns write/lease; entry lookup raises ValueError for unresolved identity. | Preserve generation, credential provenance, lifecycle, overrides, and admission. |
| Credentials | `src/auth/credential_store.py` loads/writes one envelope; persist/remove rewrite `self._path`; DAO enum now includes OPENROUTER. | Same owner/signatures/DAO, provider-file routing and merged reads. |
| Redaction | Resolver `redact_openrouter_text` calls live resolve and refuses serialization when lookup fails without an admitted capture. | Do not turn corruption into absence or weaken redaction. |
| Resume | `src/cli/typer_dispatch.py:_build_session_config` unconditionally restores `resumed_model_name` after fallback; explicit model bypasses pool parsing. | Check saved direct model through catalog; keep OpenRouter pending path; unknown saved direct model uses existing default resolver plus notice/warning. |
| Startup display | `sessions/service.py:should_show_startup_notice` uses only history marker/in-memory flag. `src/tui/app.py:_maybe_render_startup_notice` already paints fallback/copyright/tip. | Session gate allows fallback notice; no new TUI branch. |
| History | `history/tree_store.py` wraps `FilesystemSessionHistoryStore`, physically `events.jsonl` plus `session.json`. | Use production store for compatibility; do not implement the stale `tree.json` description from orientation prose. |
| Observer | `TyperDispatch.visualize` builds visualizer config, enters interactive logging, mounts `HeadlessWorkflowVisualizer`. | Guard the real CLI path with audit hook and headless mount, not just loader. |
| CI | Repository-root `.gitlab-ci.yml` pytest job lacks full-history/tag variables. | b5 names two variables; see write-scope boundary below. |

These are static findings and expected red behaviors, **not newly executed failures**.

## 4. Safe command-level test environment

### Verified runtime and infrastructure

- Python: `/root/.pyenv/versions/3.11.7/envs/slo-harness/bin/python`, version **3.11.7**, prefix `/root/.pyenv/versions/3.11.7/envs/slo-harness`.
- Existing packages, read via metadata without importing application code: pytest 9.1.1, pytest-asyncio 1.4.0, Poetry 2.4.3, Black 26.5.1, mypy 1.20.2, Textual 8.2.8.
- Existing environment has a Poetry executable with that interpreter's shebang. Use its bin directory, not inherited pyenv shims.
- `tarfile.data_filter` exists in this interpreter; no compatibility package installation is needed.
- `environments/tests.env` is **absent**. `Makefile:test` therefore uses its existing synthetic fallback. It exports test mode, app/root paths, `gpt-5.4`, terminal dimensions, disabled auto-visualization, and a fake Anthropic key. No environment file needs creation.
- `poetry.toml` has `virtualenvs.create=false`.
- Tests use pytest asyncio auto mode; default marker excludes `e2e`. Installer/wheel/live-provider E2E files are marked out of the default gate. Do not enable them.
- Root fixture stubs `VisualizerLauncher._default_spawn`; TUI fixture injects fake credentials and clears renderer overrides. Keep these protections.
- Inherited variable **names only** were inspected. They include SLO_HOME, KB_DIR, SLO_KB_DIR, SLO_SKILLS_DIR and deploy-token settings. No values were printed. A small unset list alone is insufficient for the command boundary: use `env -i`.

### Invocation recipe (planned, not executed)

Before **each** test command, including b1's first red test, allocate a fresh command-owned temp root. No test may run with the invoking agent's HOME or inherited SLO variables. The implementation phase may use this inline pattern; do not add a shell script to the product:

```bash
cd /root/Code/slo-openrouter-implementation/slo && \
R=$(mktemp -d /tmp/slo-86b-b1-red-XXXXXXXX) && \
P=/root/.pyenv/versions/3.11.7/envs/slo-harness && \
"$P/bin/python" -I -B -c 'import pathlib,sys; r=pathlib.Path(sys.argv[1]); assert r.is_absolute() and r.resolve()==r and r.parent==pathlib.Path("/tmp"); assert not r.is_symlink(); [(r/name).mkdir() for name in ("home","slo","tmp","cache")]; print(r)' "$R" && \
env -i PATH="$P/bin:/usr/bin:/bin" VIRTUAL_ENV="$P" \
  HOME="$R/home" SLO_HOME="$R/slo" SLO_AUTH_FILE="$R/slo/global/authentication.json" \
  TMPDIR="$R/tmp" XDG_CONFIG_HOME="$R/home/.config" XDG_DATA_HOME="$R/home/.local/share" \
  XDG_CACHE_HOME="$R/cache" POETRY_CACHE_DIR="$R/cache/poetry" POETRY_VIRTUALENVS_CREATE=false \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/root/Code/slo-openrouter-implementation/slo \
  SLO_ENV=test SLO_ROOT_DIR=/root/Code/slo-openrouter-implementation/slo \
  SLO_APP_DIR=/root/Code/slo-openrouter-implementation/slo SLO_APP_NAME=slo SLO_LOG_FORMAT=text \
  SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 \
  SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked \
  COLUMNS=120 LINES=40 \
  "$P/bin/python" -B -m pytest -q -p no:cacheprovider --basetemp="$R/tmp/pytest" \
  -m 'not e2e' tests/test_slo_home_isolation.py >"$R/output.log" 2>&1
```

The phase must capture the command's real exit immediately, record the expanded argv/environment **without secrets**, and link `output.log` from its new report. Use a new `R` per gate; pytest owns and can clear only its fresh `R/tmp/pytest` basetemp. Keep basetemp **beneath TMPDIR**: b1's guard checks config paths against `tempfile.gettempdir()`, including after config reloads; sibling `$R/pytest` would falsely fail that guard. Retain failed output; never overwrite red logs. The setup proof precedes all fixture-root writes. For paths created by tests, assert resolved ancestry before mkdir/write/chmod/replace/unlink, including symlink targets, not afterwards. The spec contains examples that assert after mkdir; correct that ordering.

For full `make test`, use the same clean prefix and fresh R, add `PYTEST_ADDOPTS="-p no:cacheprovider --basetemp=$R/tmp/pytest --tb=short"`, then `/usr/bin/make test`. Preserve the Makefile's actual test contract; do not replace a failing `make test` result with a focused pass. First verify `poetry run python` resolves to the existing approved environment under this clean prefix. No Poetry install/env creation.

For static checks use the same prefix with `BLACK_CACHE_DIR=$R/cache/black` and `MYPY_CACHE_DIR=$R/cache/mypy`; run the project interpreter's `-m black --check --line-length 110 <changed files>` and `-m mypy src/ tests/`. These are checks, not a bulk formatter/refactor authorization.

For AC-I1, b1 must create **stand-in D inside its fresh command root**, populate synthetic sentinel files, and deliberately pass HOME/SLO_HOME/SLO_AUTH_FILE plus all listed overrides into D. Remove original inherited values first. Capture full path/type/hash inventory before and after, requiring exact equality. This deliberately hostile test is safe because D is owned, never the real HOME. Do not run the hostile full suite until the seam passes focused tests.

Overrides from the spec to verify at both isolation layers:

`SLO_WORKFLOW_ID`, `SLO_CAPTURE_DIR`, `SLO_CAPTURE_COMPLETION`, `SLO_PREFERENCES_FILE`, `SLO_SCHEDULES_DIR`, `SLO_CONNECTORS_DIR`, `SLO_MODEL_CATALOG_OVERRIDES_FILE`, `SLO_USER_SKILLS_DIR`, `SLO_USER_WORKFLOWS_DIR`, `SLO_KB_DIR`, `KB_DIR`.

Command-level `env -i` also removes credentials, SLO_SESSION_ID, SLO_MODEL_POOL, tool-root overrides, shell startup injection, proxies and Python import overrides. Tests may deliberately set synthetic values later.

### Suite hazards to retain in the handoff

- `tests/cli/test_install.py:FakeBin` uses regular executable wrappers, not host-binary symlinks. Its `write_regular_executable` verifies containment and refuses symlinks. Other launcher symlinks inspected point to synthetic files. Do not replace this with host links.
- The FakeBin passthrough list includes `python3` resolved on a fixed system search path. Before running that containing suite, verify any interpreter execution respects the user-required existing environment; if not, make only a justified test-harness safety adjustment under b1 or stop for direction. Do not silently run a system Python or install anything.
- `tests/agents/slo_agent/orchestrator/capture_test_safety.py` contains default-deny network/process/write guards and finite child cleanup; preserve them. It hard-codes `/root/.pyenv/versions/slo-harness/bin/python`. Read-only resolution shows that alias and the approved long interpreter path resolve to the same Python binary. Lexical `sys.executable` assertions may still differ; diagnose such failures, never weaken containment.
- `tests/cli/test_release_automation.py` includes `make -n` and invalid-version `make release` checks. Their invalid inputs currently fail before Git operations. Inspect any changed recipe before execution; never execute a valid release target.
- The existing integration `isolated_catalog` fixture blocks default sync/async HTTP transports and uses real stores with local MockTransport. Preserve this, use synthetic credentials, and never infer live authorization from a passing offline test.
- After any command-stubbing suite, run `cd /root/Code/slo-openrouter-implementation/slo && dpkg -V coreutils`; require empty stdout and exit 0, retaining its receipt. Stop on odd binary behavior. No host administration or process-tree killing.
- This preparation inspected key infrastructure and dangerous seams, not every one of the thousands of tests. b1 must finish the execution-specific safety audit before broad gates. **Only the bounded, reviewed b1 red-test path is cleared to start now.**

## 5. Sequential implementation units and acceptance map

User TEST FIRST overrides the workflow's generic code-first example. For each behavior: add a failing assertion, run and retain the intended failure, implement approximately one small method / at most ~50 implementation lines, run focused green and surrounding tests, then proceed. A missing test file/import is not adequate behavioral red evidence by itself. Do not implement an entire spec sample before running it.

### b1 — isolation foundation (AC1 / AC-I1–I4)

The AST-confirmed binding registry is:

| Module relative to `src/` | Binding |
|---|---|
| `agents/model_catalog/store.py` | `_CFG_SLO_HOME` |
| `agents/slo_agent/history/filesystem_store.py` | `_CFG_SLO_HOME` |
| `agents/slo_agent/history/migration/token_usage_backfiller.py` | `_CFG_SLO_HOME` |
| `agents/slo_agent/history/migration/tree_migrator.py` | `_CFG_SLO_HOME` |
| `agents/slo_agent/orchestrator/pool.py` | `SLO_HOME` |
| `agents/slo_agent/preferences/service.py` | `_CFG_SLO_HOME` |
| `auth/credential_refresher.py` | `_CFG_SLO_HOME` (also patch derived `_CREDENTIALS_LOCK_FILE`) |
| `cli/typer_dispatch.py` | `_CFG_SLO_HOME` |
| `integrations/connectors/store.py` | `_CFG_SLO_HOME` |
| `scheduling/os/logs.py` | `_CFG_SLO_HOME` |
| `scheduling/store.py` | `_CFG_SLO_HOME` |

Owners/files:

- New `tests/state_isolation.py`: pre-import suite seam; `SLO_HOME_BINDINGS`, `INHERITED_STATE_OVERRIDES`.
- `tests/conftest.py`: call seam before config/src imports; autouse `isolated_slo_home`; contained suite cleanup.
- New `tests/test_slo_home_isolation.py`.
- `tests/tui/test_app.py::TestCollapseHomeInPath`: body-time home templates.

Suggested units:

1. Under command-level isolation, write a behavior test/probe demonstrating imported config and Claude path do not move away from a synthetic hostile environment without the seam. Retain red. Add the small suite seam and rerun. No real state is required to demonstrate this failure.
2. Red test per-test HOME/auth/lock/all 11 bindings and removed overrides; implement fixture/registry. Existing root terminal/plugin fixtures remain intact. Ensure `config.cfg` reload tests cannot leak a previous test's path into a later writer.
3. Demonstrate AST completeness guard sensitivity using a temp-owned source specimen or bounded runtime injection, rather than editing unrelated production modules. Demonstrate override-removal sensitivity in an owned subprocess. Keep both expected negative exits.
4. Run title-bar cases to expose the collection-time HOME mismatch; fix parametrization only. Confirm unique per-test roots and suite-root teardown.
5. Focused + TUI surrounding, then safe full normal and hostile `make test`; D is unchanged. No production edits.

Tests/commands under the clean prefix: `-m pytest -q tests/test_slo_home_isolation.py tests/tui/test_app.py`; full `make test`; Black check on the four listed files. Full gate must pass for b1 readiness.

### b2 — catalog namespace (AC2 / AC-C1–C5)

Owners/files: `src/agents/model_catalog/store.py`, `service.py`; new `tests/catalog_cache_samples.py`, `tests/agents/model_catalog/test_cache_file_separation.py`; existing `test_model_catalog_store.py` and the 11 filename users below.

Units: default writer path red → two constants green; lease filename red → lease regression green; corrupt/other-version log behavior red → warning green; dead-reader absence assertion → removal; mechanical test filename updates with folder checks. Cache sample must be a truthful OpenRouter record (provider, canonical route, API ID agree), rather than blindly copying an OpenAI row without changing its provider.

Cover missing, valid schema-2, schema-1/schema-3, malformed JSON, validation failure and unreadable input. Verify seed survives, next write rebuilds, and released cache **and lock** bytes/mtime remain untouched; no adoption/repair. Use narrow injected read failure for unreadability because chmod alone does not make a file unreadable to root. Verify actual log records contain no traceback or secret/file content.

Mechanical users:

- `tests/agents/model_catalog/test_atomic_publication.py`
- `test_catalog_process_ordering.py`, `test_catalog_shutdown.py`
- `test_openrouter_budget_evidence.py`, `test_openrouter_lifecycle.py`
- `test_openrouter_real_store_recovery.py`, `test_openrouter_refresh_credential_contract.py`
- `test_status_admission_takeover.py`
- `tests/integration/test_openrouter_full_flow.py`
- `test_openrouter_repeated_page_retention.py`, `test_openrouter_scheduled_preparation.py`

Gates: focused separation/store; `tests/agents/model_catalog tests/integration tests/integrations`; full `make test`; changed-file Black. Static source search must find no quoted released cache/lock literal and no definitions/callers of `load_cache`, `is_cache_fresh`, `_should_refresh_discovery` (released test program text in b5 is intentionally distinct). AC-C5 closes in b5.

### b3 — credentials (AC3 / AC-K1–K6)

Owners/files: `src/auth/credential_dao.py`, `credential_store.py`, resolver **docstring only**; new `tests/auth/test_credential_file_split.py`; path-only updates in `tests/auth/test_openrouter_authentication.py`, `tests/integration/test_openrouter_full_flow.py`, `tests/integrations/openrouter/test_harness_contract.py`.

Units: additional-provider path/routing red → frozen released set + property; persist route/untouched sibling red → path-taking envelope/write helpers; merged/filtered load red → owned-row projection + warning; remove and error branches red → smallest handling change. Keep public signatures and atomic sibling-temp replacement; no new lock/store/DAO/migration.

Cover all three released providers, OpenRouter, both files absent, both present, constructor/env override sibling naming, overwrite/remove-present/remove-absent, modes 0600/0700, each direction of misfiled rows, warnings on every load, unchanged misfiled credential values on persist **and remove**, untouched non-owning file, corruption/schema/unknown-provider/unreadability and exact error path. Keep fail-closed history-redaction tests in surrounding coverage.

**Spec sample correction required:** `_parse_existing` sample catches JSONDecodeError/ValueError but not OSError, while AC-K5 explicitly requires `CredentialStoreCorruptError` for unreadability. Test this first with a targeted synthetic read error, then satisfy the written acceptance contract. Use explicit types rather than sample bare `dict`. No permissive unknown-provider redesign.

Do not claim byte-identical entire envelopes when an owning-file rewrite is permitted: assert untouched sibling bytes/mtime and unchanged semantic misfiled rows. Pre-fix OpenRouter rows in the released file are ignored and not redacted until manual cleanup; document, never automate cleanup.

Gates: focused split + existing credential store; `tests/auth tests/integration tests/integrations tests/agents/slo_agent/history`; full `make test`; changed-file Black. AC-K6 closes in b5.

### b4 — unknown saved model (AC4 / AC-R1–R4)

Owners/files: `src/cli/typer_dispatch.py:_build_session_config` + `_resumable_model_name`, `_is_catalog_model`, pure `_resume_fallback_notice`; `sessions/service.py:should_show_startup_notice`; extend existing `tests/cli/test_resume_route_precedence.py`, `tests/tui/test_startup_notice.py`.

Units: unknown direct and prefix-compatible saved names red → narrow existing-owner selection branch; default-notice composition red → pure helper; existing startup-marker suppresses fallback red → session gate. Keep TUI composition unchanged.

Cover flat/tree metadata, exact catalog names and aliases, unknown `retired-model-x` and `claude-retired-x`, saved OpenRouter pending route, explicit model clearing configured pool, existing configured-pool primary precedence, no resume, invalid preference notice composition, missing metadata, fallback with/without persisted startup marker, history-disabled branch. Assert one `session_resume_model_unavailable` warning for the fallback event (other existing default-resolver warnings may be separate). Mounted test must prove fallback/copyright/actual-active-model tip, and ordinary resume remains quiet. Use Faux, no live inference/manual configured-key smoke.

Boundary: this spec does not redesign an invalid configured default's own compatibility-prefix behavior. If a stronger input combination still fails in unchanged default resolution, retain evidence and surface the scope question rather than broadening model-admission work.

Gates: both changed test modules; `tests/cli tests/tui tests/agents/slo_agent`; full `make test`; changed-file Black. AC-R4 closes in b5.

### b5 — mixed-version proof and observer (AC5–7 / AC-X1–X5)

New files: `tests/compat/__init__.py`, `released_runner.py`, `conftest.py`, `released_scripts.py`, `test_catalog_cache_mixed_versions.py`, `test_credentials_mixed_versions.py`, `test_session_resume_mixed_versions.py`; `tests/cli/test_visualize_state_independence.py`.

Use one released-runner seam and the b2 cache sample. `git archive` runs against repository root `/root/Code/slo-openrouter-implementation`, tag `v0.20.1`, path `slo`; no fetch is needed. Archive only into a fresh fixture root, validate tar destinations before extraction with data filter, never over live source. A missing tag must fail with a useful error and never skip. Child environment is explicit/minimal, interpreter existing, CWD/HOME/state/log/temp roots owned by the same test. Prefer all writable children under one test root rather than unchecked siblings from the sample. Allow no real provider clients or credentials.

Real sequences:

1. Released writes its schema-1 cache; new writes `.v2`; released import/load is silent and sees its own seed/cache count; released bytes unchanged; new can still read its cache.
2. Released saves Anthropic; new saves OpenRouter without changing released bytes; released loads and saves OpenAI without changing additional bytes; new sees all three.
3. Released production tree store writes a complete turn with unknown saved model; new CLI config falls back, real session with Faux hydrates **contents**, continues one turn and rewrites metadata; released resumes and sees every old/new user/assistant entry in order. Avoid count-only proof of full history.
4. New production tree store writes OpenRouter route and private extension; released resumes and reads all history without understanding the extension. To satisfy the requested continuation-in-both-directions proof, add a released `FauxChatModel` continuation through the real released session/store, then reopen in new code and assert every entry's content/order including that released turn. The sub-spec's count-only released hydration sample alone does not establish rollback continuation. Keep extension/rewrite limitation explicit.
5. Observer subprocess installs audit hook before CLI imports, mounts real visualizer via `run_test`, dispatches `visualize --session observed --no-follow`, verifies selected session actually loaded, zero catalog/auth open/mutation hits, hostile bytes unchanged. Audit both source/destination arguments and resolve paths safely.

Compatibility guards may already pass after b2–b4. Do not fabricate red history. Demonstrate sensitivity with temp-owned copies/controlled in-process seams (or scoped test patches) restoring the old behavior, not destructive checkout/reset or uncontrolled source rewrites. Each expected failure must be causal and logged. Observe missing-tag failure explicitly. Do not label guard tests as new runtime fixes.

Gates: compat + visualize; catalog/auth/integration suites; resume/startup/app suites; full normal and hostile `make test`; changed-file Black, typing, static namespace/dead-reader checks; final incremental diff. No existing prerequisite static waiver applies to this task. If a static or behavioral baseline failure exists, provide exact baseline evidence and keep the gate failed rather than claiming completion or reformatting unrelated 86.a.

Documentation: `AGENTS.md`, `RESEARCH.md`, `docs/RESEARCH.md`, `CHANGELOG.md`: separate names, single owners, frozen released provider set, future file-name rules, fallback, shared history and compaction extension-loss limitation; manual pre-fix cleanup is prose only. Preserve historical reports; add a clearly dated current section instead of rewriting prior receipts.

**Write-scope boundary for the parent:** b5 names `/root/Code/slo-openrouter-implementation/.gitlab-ci.yml`, outside the user's literal “work ONLY .../slo” directory. Its pytest variables need `GIT_DEPTH: '0'` and `GIT_FETCH_EXTRA_FLAGS: '--tags'`. This preparation read it but did not change it. Parent must settle explicit write authorization before that edit; do not silently reinterpret the boundary. KB edits are also outside that boundary, and b5 calls them **after merge**, whereas merge is prohibited. Retain the proposed KB update as a report handoff, not a live external write or a false completed deliverable. These do not prevent beginning b1.

## 6. Gate and evidence contract

All test/static commands below mean **inside a newly allocated clean prefix from section 4**, never a bare invocation. Every shell tool call still begins with explicit target `cd`.

| Gate | Command tail | Required receipt |
|---|---|---|
| I | approved Python `-B -m pytest -q tests/test_slo_home_isolation.py tests/tui/test_app.py` | Behavioral red, green, unique roots/cleanup, mutation sensitivity |
| C | approved Python `-B -m pytest -q tests/agents/model_catalog/test_cache_file_separation.py tests/agents/model_catalog/test_model_catalog_store.py` | Paths, logs, released preservation, decision table |
| K | approved Python `-B -m pytest -q tests/auth/test_credential_file_split.py tests/auth/test_credential_store.py` | Ownership split/merge/error/modes/preservation |
| R | approved Python `-B -m pytest -q tests/cli/test_resume_route_precedence.py tests/tui/test_startup_notice.py` | Real build + mounted notice + precedence |
| X | approved Python `-B -m pytest -q tests/compat tests/cli/test_visualize_state_independence.py` | Real released subprocess/continuation/audit and sensitivity |
| Surrounding persistence | approved Python `-B -m pytest -q tests/agents/model_catalog tests/auth tests/integration tests/integrations tests/agents/slo_agent/history` | Complete output/exits/counts |
| Surrounding app | approved Python `-B -m pytest -q tests/cli tests/tui tests/agents/slo_agent` | Complete output/exits/counts |
| Full | `/usr/bin/make test` | Green on current files; retain failure output if not |
| Hostile full | same make tail; D overrides, sentinel comparison | Full green **and** D byte/path-identical |
| Formatting | approved Python `-B -m black --check --line-length 110 <incremental changed Python files>` | Actual result, no inherited waiver |
| Typing | approved Python `-B -m mypy src/ tests/` | Actual result; baseline failures stay failed |
| Namespace | search `src` for quoted `model_catalog_cache.json`/`.lock`; search definitions/callers of obsolete methods | No active source matches |
| Stub integrity | `dpkg -V coreutils` | Exit 0, empty output after stub suites |

Save each phase's report under this `86b-model-catalog/` directory with a new phase-specific name. Include commands with full expanded paths, actual exits, test counts, red output links, acceptance mapping, incremental file hashes/diff, remaining gaps and safety observations. Re-run affected gates after the last code edit; docs alone do not turn an older result into a fresh gate.

Independent review, when dispatched by the parent, must review the **baseline-relative** changes and trace all AC1–AC7; no delegation from this preparation agent. Completion phase independently checks final state and every required receipt. Green focused tests alone do not authorize feature completion, commits or publishing.

## 7. Observed evidence / commands run in this preparation

1. `cd /root/Code/slo-openrouter-implementation/slo && pwd && git branch --show-current && git status --short && /root/.pyenv/versions/3.11.7/envs/slo-harness/bin/python --version` — exit **0**, correct target/branch, extensive pre-existing work, Python 3.11.7.
2. Explicit-cd approved Python `-I -B -c` stdlib-only manifest/hash/mode/link comparison plus `git ls-files --others --exclude-standard -z`, tar member count and `git rev-parse v0.20.1^{commit}` — exit **0**, 817 entries/members, no differences, no additional relevant untracked files; hashes and commit recorded above. No archive extraction.
3. `cd /root/Code/slo-openrouter-implementation/slo && command -v poetry && command -v make` followed by approved Python `-I -B -c` stdlib/metadata probe — exit **0**. Inherited Poetry is a pyenv shim; explicit environment Poetry is present; packages, interpreter resolution and variable names recorded in section 4. Probe also confirmed no ancestor instructions and no pre-existing recovery-plan file.
4. A second explicit-cd approved Python `-I -B -c` read-only pass immediately before this report checked every archive regular-member hash against the manifest and live file, AST-discovered SLO_HOME bindings, and report absence — exit **0**, **817 checked / 0 errors / 11 bindings**. Thus no concurrent source drift was observed between the two comparisons.
5. File-tool reads/searches inspected the owners and infrastructure above. Expected missing paths: `environments/tests.env` (Make fallback confirmed), and a guessed `tests/integrations/openrouter/harness.py` (actual test/fixture locations found instead). No command malfunction.
6. **Tests executed: 0. Static gates executed: 0.** No red/green or current full-suite success is claimed.

Historical receipt inspected, not reused as a gate: `.f86-window-correction-tPhyAzET/full.log` ends with **5156 passed, 18 deselected, 196 warnings in 332.15s**; `full.exit` is **0**. Its `full-command.txt` uses the short interpreter alias and isolated worktree-local roots. This is preserved 86.a evidence, not proof that this new command environment or b1 passes. Scratch-copy failures in the specification likewise are not observed failures of this target checkout.

## Handoff

Begin b1 with bounded test-first isolation work under section 4. Keep all 86.a prerequisites untouched. Do not start b2 until b1's required gates pass. Future phase safety or baseline failures must be reported with their actual output; no skipped failures, softened assertions, retrospective red evidence, or unauthorized cleanup.
