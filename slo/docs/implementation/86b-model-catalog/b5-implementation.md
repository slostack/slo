# 86.b.5 — Released-version proof, observer guard and rollout documentation

Date: 2026-10-04

## Verdict

**Implementation and behavioral gates pass; assigned-phase readiness is withheld because the required repository-wide typing gate fails.** No old waiver is inherited.

- Normal `make test`: **5299 passed, 18 deselected**, exit 0.
- Hostile stand-in `make test`: **5299 passed, 18 deselected**, exit 0; all **36 stand-in path/type/hash entries unchanged**.
- Actual released-source compatibility + real CLI observer: **11 passed**, exit 0.
- Black: **all 40 baseline-relative 86.b Python files pass**, exit 0.
- Incremental b5 plus corrected b2/b3 tests: mypy **11 source files clean** with imported dependencies followed silently; exit 0. This is a scoped check, not a repository-wide pass.
- Full `mypy src/ tests/`: **296 errors in 59 files**, exit 1. The original pre-86.b archive independently produces the **same 296 errors**, identical by file/error text after removing line numbers. These include missing PyYAML stubs and unrelated pre-existing source/test typing errors. No package installation or broad 86.a remediation was performed.
- Every gate's `dpkg -V coreutils`: exit 0, empty output.

The concrete remaining conflict is the full-green typing requirement versus the prohibition on installation and unrelated remediation. This report does not soften that failed gate into success. Independent review and final workflow completion remain parent-owned; no merge, release, live-provider validation or whole-Feature-86 approval is claimed.

## Attribution and preservation

Authoritative checkout: `/root/Code/slo-openrouter-implementation/slo`, branch `feature-86-openrouter-implementation`. Every shell call explicitly entered it. The separate main checkout was not modified.

Before edits, **822 predecessor hashes** matched `b4-receipts/final-hashes.json`. Existing documents, root CI and the two subsequently corrected test files were checked again and saved in `b5-receipts/before.tar.gz`. Final reconciliation permits exactly eight modified existing repository files plus nine new Python files. All original baseline modes and **68 historical evidence hashes** remain unchanged. The original baseline archive remains the attribution source for cumulative 86.b, not HEAD's large prerequisite 86.a diff.

Frozen release: `v0.20.1^{commit}` = `f63df0a4958eedb4bc603f1946ba4591dd181fff`. No fetch was needed or performed. Extraction occurs only inside an owned pytest root; traversal, links and devices are refused before extraction, with tar's data filter also enabled. No Git worktree, staging, commit, reset, stash, clean, branch switch, push, PR, deploy or install occurred.

### Incremental changed files

| Path | b5 change |
|---|---|
| `tests/compat/__init__.py` | Empty package marker. |
| `tests/compat/released_runner.py` | Single released subprocess seam and frozen result DAO; explicit minimal environment, test-owned HOME/workdir/TMPDIR beneath shared SLO_HOME, script-only extra inputs, timeout/reap and retained diagnostics. |
| `tests/compat/conftest.py` | Only the session-scoped real `git archive v0.20.1 slo` fixture; missing tag fails rather than skips. |
| `tests/compat/released_scripts.py` | Programs importing frozen modules for catalog, credential and real session/history operations. |
| `tests/compat/test_catalog_cache_mixed_versions.py` | Released schema-1 write → new provider write → released CLI import/load; unchanged released bytes, equal released counts, no catalog error/traceback in either output stream. |
| `tests/compat/test_credentials_mixed_versions.py` | Released Anthropic → new OpenRouter → released load/OpenAI save → new merged lookup; sibling-byte preservation and exact synthetic credential values. |
| `tests/compat/test_session_resume_mixed_versions.py` | Both default tree and explicit flat paths; released → new continuation/metadata rewrite → released continuation → new reread; new OpenRouter history with private extensions → released continuation → new reread. Exact ordered contents, not count-only assertions. |
| `tests/compat/test_released_runner.py` | Actual frozen import identity/closed enum, hostile ambient override removal, refusal of non-script env overrides, child failure retention, CI tag contract. |
| `tests/cli/test_visualize_state_independence.py` | Real `src.cli.main` command `slo visualize --session observed --no-follow`, actual visualizer mount via `run_test`, audit hook before CLI imports, zero auth/catalog file hits, unchanged hostile bytes. |
| `tests/agents/model_catalog/test_cache_file_separation.py` | Three log-extra assertions use `LogRecord.__dict__["path"]`, preserving exact assertions while fixing b2-introduced type errors. |
| `tests/auth/test_credential_file_split.py` | Two corresponding log-extra accesses use `__dict__`; same warning/path/provider assertions, plus Black formatting. |
| `/root/Code/slo-openrouter-implementation/.gitlab-ci.yml` | Pytest job gets `GIT_DEPTH: '0'` and `GIT_FETCH_EXTRA_FLAGS: '--tags'`. No remote CI job was launched. |
| `README.md` | User rollback contract, new filenames, future-provider constraint and manual-only pre-fix cleanup. |
| `AGENTS.md` | Two credential files, mixed-version boundary, tests; corrects the stale tree.json description to actual shared events.jsonl storage. |
| `RESEARCH.md`, `docs/RESEARCH.md` | Shared-state inventory and cache/credential edge tables, superseded ignore-schema clause, durable limitations. |
| `CHANGELOG.md` | Unreleased filenames and “no action needed for released users.” |

Explicitly authorized external documentation updates:

- `/root/Code/KnowledgeBase/KB/slo/feature-86-openrouter-status.md`
- `/root/Code/KnowledgeBase/KB/slo/model-catalog-before-after-and-visualize-error.md` — resolution pointer only; historical analysis preserved.
- `/root/Code/KnowledgeBase/KB/slo/gotchas.md`
- `/root/Code/KnowledgeBase/Reinforcement/shared-state-files-need-version-separated-names.md`

These notes identify implementation, not merge/release. No operational KB cleanup or user-state cleanup ran. Report/evidence additions are confined to the requested implementation directory; command logs are in owned `/tmp` roots linked below.

## Test-first / sensitivity record

B2–b4 already implement the production behavior. B5 does not fabricate a second production fix or revert live source to obtain red tests. After adding each compatibility test, an evidence-only pytest plugin restores the relevant old behavior **in that process only**, then the unchanged production implementation runs green. No negative plugin participates in the ordinary suite.

| Evidence label | Actual failure / green result |
|---|---|
| `b5-runner` | Scaffolding validated against actual archived source: 3 passed. No claimed product red/fix. |
| `b5-catalog-negative` | Exit 1, one failure: pre-b2 filename causes actual released `model_catalog_cache_load_failed` and traceback. |
| `b5-catalog-green` | 4 passed, exit 0. |
| `b5-credentials-negative` | Exit 1, one failure: pre-b3 single-file routing changes released credential bytes. |
| `b5-credentials-green` | 5 passed, exit 0. |
| `b5-resume-negative` | Exit 1, two failures: pre-b4 saved-model acceptance keeps `retired-model-x`, not fallback, in tree and flat cases. |
| `b5-resume-green` | **Failed**, 2 failed / 5 passed: test author used nonexistent `startup_notice_shown`; actual field is `startup_notice_shown_at`. Label is not a pass claim. |
| `b5-resume-corrected` | 7 passed, exit 0, with timestamp and model rewrite asserted. |
| `b5-rollback` | **Failed**, 2 failed / 7 passed: released assistant events legitimately omit payload.role; using raw role was the wrong transcript projection. |
| `b5-rollback-corrected` | 9 passed, exit 0; actual `ReplayEntryProjector` proves exact kinds/content and prior canonical events remain equal. No product behavior changed. |
| `b5-observer` | 10 passed, exit 0; guard already works, no runtime change claimed. |
| `b5-observer-negative` | Exit 1: injected synthetic forbidden read produces exactly `open / model_catalog_cache.v2.json`; actual observed session still mounts. |
| `b5-missing-tag` | Exit 1, setup error with actual git invalid-object diagnostic; no skip. Only fixture tag variable changed, never Git refs. |
| `b5-ci-red` | Exit 1, absent full-history variable assertion. |
| `b5-ci-green` | 20 passed including release automation tests, exit 0, after two CI variables added. |
| `b5-type-full` | Exit 1: 307 errors. Six new test inference errors and five b2/b3 log-extra errors corrected; the other 296 independently match baseline. |
| `b5-log-types-green` | Scoped typing: 11 files clean; both corrected modules: 90 passed; exit 0. |
| `b5-black-red`, `b5-black-finalcheck` | Failing Black output retained before formatting: seven new files, then one corrected log test. |
| `b5-format`, `b5-log-format` | Formatting-only transformations verified by AST equivalence. CI test addition is accounted separately in the proof. |

Failures, commands, environments and outputs are retained, including test-authoring errors. No assertion was weakened, no skip/xfail added, no timeout increased, and no prerequisite production file changed in b5. The scoped type correction was prompted by a real failing gate, not unrelated refactoring.

## Final verification receipts

The unchanged inspected `b3-receipts/run_gate.py` was reused with unique `b5-*` names. Each call creates disposable command-level HOME/SLO_HOME/TMPDIR/caches and supplies an explicit environment (equivalent to `env -i`), removing inherited state, credentials, proxies and shell/Python injection. Pytest cache is disabled and basetemp is under that command's TMPDIR. B1 then applies suite/per-test isolation. Project Poetry/pytest uses the approved existing 3.11.7 environment, with the lexical interpreter spelling required by existing capture guards.

Exact expanded commands, actual exits, full output locations and SHA-256s are in **[b5-receipts/index.json](b5-receipts/index.json)**. Each linked root also has `command.json`, `output.log`, and `coreutils.log`. Command tails below are descriptions, not safe standalone recipes.

| Gate / command tail | Actual result | Output root |
|---|---|---|
| `poetry run pytest -q tests/test_slo_home_isolation.py` | 12 passed, exit 0 | `/tmp/slo-86b-b3-b5-final-isolation-ve6u61di` |
| `poetry run pytest -q tests/agents/model_catalog tests/auth tests/integration tests/integrations tests/agents/slo_agent/history` | 961 passed, 3 deselected, exit 0 | `/tmp/slo-86b-b3-b5-final-persistence-s0649yvv` |
| `poetry run pytest -q tests/cli/test_resume_route_precedence.py tests/tui/test_startup_notice.py tests/tui/test_app.py` | 215 passed, exit 0 | `/tmp/slo-86b-b3-b5-final-resume-_mp2gv8z` |
| `poetry run pytest -q tests/compat tests/cli/test_visualize_state_independence.py` | 11 passed, exit 0 | `/tmp/slo-86b-b3-b5-final-compat-q8a_iqj_` |
| `poetry run pytest -q tests/cli tests/tui tests/agents/slo_agent` | 3392 passed, 15 deselected, exit 0 | `/tmp/slo-86b-b3-b5-final-surrounding-app-79984k8q` |
| `/usr/bin/make test` | **5299 passed, 18 deselected, 203 warnings**, exit 0, 382.83s | `/tmp/slo-86b-b3-b5-final-full-x5aj_cx9` |
| Hostile stand-in `/usr/bin/make test` | **5299 passed, 18 deselected, 203 warnings**, exit 0, 381.79s; 36 entries unchanged | `/tmp/slo-86b-b3-b5-final-hostile-t0dv0l8u` |
| `black --check -l 110` on b5's 11 Python files | 11 unchanged, exit 0 | `/tmp/slo-86b-b3-b5-final-black-p111o2wj` |
| `black --check -l 110` on all cumulative 86.b Python files | **40 unchanged**, exit 0 | `/tmp/slo-86b-b3-b5-all-black-bs897gs1` |
| `mypy --follow-imports=silent` on b5 + two corrected tests | 11 files clean, exit 0 | `/tmp/slo-86b-b3-b5-log-types-green-7ozlyl5w` |
| Full `mypy src/ tests/` after corrections | **296 errors in 59 files**, exit 1 | `/tmp/slo-86b-b3-b5-final-types-a8dquyms` |
| Same full typing command on original archive extracted to owned temp | **296 errors in 59 files**, exit 1 | `/tmp/slo-86b-b3-b5-types-original-baseline-nfqxr9gb` |
| Quoted released cache names + dead reader/caller search in `src` | Zero matches | `b5-receipts/post-gate-check.json` |

The hostile wrapper records its exact inner environment/argv and before/after inventory at:
`/tmp/slo-86b-b3-b5-final-hostile-t0dv0l8u/tmp/hostile-inventory.json`.
Every inherited-state variable is replaced with a synthetic stand-in below the command root before running make. This is not an inspection of real HOME. All normal E2E exclusions are unchanged.

Full-suite logs cover the required focused/containing suites; the persistence command includes history in addition to the overview's requested paths. Both complete make gates and the app surrounding gate ran after the final source/test/document edits. Later writes are evidence/report artifacts only.

## Acceptance map

| Criterion | Implementation / observation | Status |
|---|---|---|
| AC-X1 / AC-C5 | Actual released schema-1 writer and CLI import/load, new default provider writer; equal released count, both output streams free of errors/tracebacks, original bytes unchanged and new cache reload equal | PASS |
| AC-X2 / AC-K6 | Actual released loads only Anthropic after new OpenRouter save; released OpenAI save preserves additional-file bytes; new load returns exact three synthetic values | PASS |
| AC-X3 / AC-R4 | Real tree-default and flat owners, fallback config from released metadata, exact old text hydration, new invoke + startup metadata rewrite, released hydrate + invoke, new reread; new OpenRouter history with extensions also continues in released | PASS |
| AC-X4 | Actual CLI parse → dispatch → logging → actual visualizer run_test mount/load; observer ID is observed; zero audited opens/mutations and hostile bytes unchanged; sensitivity read fails | PASS |
| AC-X5 | Root CI fetch variables present and tested; actual archive fixture fails for absent tag; normal full suite includes compat; local released tag verified | PASS locally; remote CI not run |
| Isolation / AC-I1 | Clean command boundary + b1 fixtures + explicit subprocess environments; full hostile stand-in inventory unchanged | PASS |
| Current normal non-E2E suite / AC7 | 5299 passed, 18 unchanged deselections | PASS |
| Formatting | All 40 cumulative 86.b Python files clean, AST-preserving formatting receipts | PASS |
| Required repository-wide typing | 296 original baseline errors remain, no new error signatures | **FAIL — blocks full-green readiness** |
| Docs/CI/KB deliverables | Files listed above; manual cleanup and future-provider constraint documented, historical records preserved | Implemented; no cleanup/merge/deploy |

## Design refinements and known limits

- Released subprocess HOME/workdir/temp live **under** each test's shared isolated SLO_HOME, rather than unchecked siblings in the sample. Environment inputs cannot override HOME, PYTHONPATH or SLO state names.
- Every result retains complete stdout as well as stderr. Released logging can use stdout; the catalog guard checks both, not stderr alone.
- Session tests strengthen the sample's counts with complete ordered user/assistant content, actual rollback continuation and new reread. Both tree/default and explicit flat boundaries are covered; the tree decorator uses the same physical JSONL format.
- Only the visualizer's terminal driver is replaced. CLI dispatch, real Textual mount, history loading and selected-session validation all run. The audit examines every path argument, including rename source/destination, and resolves symlinks. It does not substitute a loader shortcut.
- All inference uses Faux; no actual provider inference, key verification or availability claim. Shared fixtures use synthetic keys only. No real terminal window is opened.
- Released compaction's loss of unknown provider-message-extension fields remains the documented limitation; archives retain the original. These tests prove append/resume continuation, not an invented fix to frozen compaction.
- Closed-enum future-provider constraints remain binding. Misfiled pre-fix keys are ignored by new reads and unavailable to redaction until manual cleanup. Neither this task nor its tests perform that cleanup.

## Evidence inventory and handoff

Under `b5-receipts/`:

- `start-hashes.json`, `before.tar.gz`, `incremental.diff`, `changed-files.json`, `final-hashes.json`: attribution against predecessor state and the original archive, not HEAD.
- `index.json`: every b5 gate, exact command/environment/exit/log hash and count (including all failures).
- `pre-format.tar.gz`, `log-pre-format.json`, `formatting-and-preservation-proof.json`: AST-equivalent formatter transformations and 68 unchanged historical evidence hashes.
- `post-gate-check.json`: 822 predecessor checks, original modes, zero forbidden source references, verified tag/branch, identical 296 baseline/current type-error signatures.
- `all-86b-python.json`: the exact 40-file cumulative Black input.
- Five negative plugins, `hostile_gate.py`, `check_baseline_types.py`, `final_audit.py`: evidence-only reproduction helpers, never imported by the default test suite.

Read target AGENTS/SLO, both RESEARCH files, complete overview/b5 sub-spec, recovery/predecessor reports, workflow and code/test conventions, always-on rules, relevant persistence/agent/CLI/Textual testing skills and KB entries. Both installed and vendored skill libraries and the personal library were confirmed. Existing safety infrastructure and safe runner were reused. Reviewed the actual final tests/scripts and incremental changes; no runtime owner, duplicate resolver or broad refactoring was introduced.

**Parent action:** perform independent b5/86.b review using this incremental evidence. Keep full typing red until the pre-existing 296-error conflict receives an authorized disposition; do not repeatedly rerun it unchanged or misreport the scoped clean check as a full pass. All other assigned deliverables and gates are implemented and evidenced. No code commit or external publication is authorized by this report.
