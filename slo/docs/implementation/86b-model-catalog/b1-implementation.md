# 86.b.1 — Code + test implementation

Date: 2026-10-04

## Verdict

**READY for the parent to advance beyond b1.** This is the assigned code/test phase only, not independent review or completion of Feature 86.b.

- Final isolated hostile **`make test`: 5168 passed, 18 deselected, 202 warnings; exit 0**.
- Normal isolated **`make test`: 5168 passed, 18 deselected, 196 warnings; exit 0**.
- Final focused/surrounding partition: **333 passed, 25 warnings; exit 0**.
- Black: **all five changed Python files clean; exit 0**.
- Hostile stand-in: **42 path/type entries, including 20 files, identical before/after**.
- Final `dpkg -V coreutils`: **exit 0, empty output**. No remaining suite root.
- No production files under `src/` or `config/` changed. No b2–b5 implementation started.

## Scope and preservation

All work used `/root/Code/slo-openrouter-implementation/slo` on the existing
`feature-86-openrouter-implementation` branch. No delegation, Git mutation,
installation, live provider inference, real terminal window, user-state cleanup,
or system-path write was performed.

The 817-entry predecessor baseline was reconciled before implementation. Final
baseline comparison found exactly the five existing-file changes below; all
other baseline regular-file hashes/modes remained unchanged. Two new test files
complete the seven-file incremental inventory. This is **baseline-relative**,
not a claim that the large HEAD diff belongs to b1.

Preserved baseline hashes:

- `baseline-manifest.json`: `ba4cd8f2927443a96ebf054fe1acc5722dcc6fd32ef39748b4495b3034f93c1e`
- `baseline.tar.gz`: `a6aa0e12cfe5ecb387f7efe25089afcfdb4fa136cb3c11e401ff98bc69ad46fa`

Reviewed incremental evidence:

- [b1-incremental.diff](b1-incremental.diff)
- [b1-changed-files.json](b1-changed-files.json) — baseline/current SHA-256 values
- [b1-evidence-index.json](b1-evidence-index.json) — 15 retained command receipts,
  expanded commands/environments, exits, summaries and log hashes

## Incremental files and behavior

| File | Change |
|---|---|
| `tests/state_isolation.py` (new) | Pre-import suite root; 11-entry SLO_HOME binding registry; inherited-state override registry. No application imports. |
| `tests/conftest.py` | Suite seam and cleanup; autouse `isolated_slo_home`; per-test HOME/auth/import bindings/OAuth lock/Claude path; reset cached config and user-content defaults. Existing plugin and terminal guards retained. |
| `tests/test_slo_home_isolation.py` (new) | 12 cases: hostile fresh-process import/fixture probes, negative override-removal sensitivity, default bindings, config aliases, source guards and their negative specimens, distinct roots, installer interpreter boundary. |
| `tests/tui/test_app.py` | Only the four title-bar parameter cases changed to resolve HOME in the test body. Original assertions retained. |
| `tests/cli/test_install.py` | Safety prerequisite: python3 passthrough wrapper uses pytest's `sys.executable`, not `/usr/bin/python3`; three local Black-only formatting changes. |
| `AGENTS.md` | Documents the test-only isolation seam and fixture. Historical receipts preserved. |
| `RESEARCH.md` | Records import-time/config-reload and collection-time HOME lessons. Historical receipts preserved. |

### Deliberate refinements to the specification sample

1. The sample leaves `config.cfg.SLO_HOME`, cached `__cfg__` values and Claude's
   class-bound path at suite/previous-test roots. The implementation rebinds these
   per test as well. Derived user skills/workflows and KB paths are rebound in
   config and their existing application import sites. No production resolver or
   parallel state owner was introduced.
2. The override list also removes `SLO_SKILLS_DIR`, `SLO_KB_SOURCE`,
   `SLO_TOOL_BASE_DIR` and `SLO_SESSION_ID`. The source guard inventories path-shaped
   setting literals, in addition to checking the active environment. `SLO_APP_DIR`
   is explicitly source location, not user state.
3. Safety inspection confirmed `FakeBin._add_passthrough_wrapper` selected system
   Python. Before any installer execution, a text-only regression failed on the
   wrapper's `/usr/bin/python3` target. The narrow test-harness fix was necessary
   to run the required full gate with the approved interpreter. No installer
   product behavior changed, and no system Python was executed by this red test.
4. Negative source specimens and a subprocess-local empty override registry prove
   sensitivity without changing unrelated application source. Expected child
   exits 1 are asserted, not skipped or mistaken for passing pytest invocations.

## Test-first sequence

Every row names a retained `/tmp` command-owned directory. The full expanded
command is at the start of `output.log`, except hostile runs, whose exact argv,
cwd and clean environment are in `command.json`. The index links every receipt.

| Unit / gate | Receipt root | Actual result |
|---|---|---|
| Red: suite import retained synthetic hostile SLO_HOME | `/tmp/slo-86b-b1-red-suite-DSbTNZJt` | 1 failed; exit 1 |
| Green: suite seam + config tests | `/tmp/slo-86b-b1-green-suite-dX8dtT2G` | 33 passed; exit 0 |
| Red: per-test root still belonged to suite | `/tmp/slo-86b-b1-red-pertest-OtSBLqwH` | 1 failed, 1 passed; exit 1 |
| Green: fixture + config/auth resolver surrounding tests | `/tmp/slo-86b-b1-green-pertest-AA3fKb7d` | 49 passed; exit 0 |
| Red: cached config fallback and two collection-HOME title cases | `/tmp/slo-86b-b1-red-derived-title-kVZ7lT8M` | 3 failed, 8 passed; exit 1 |
| Green: cached-default reset after config/auth reload tests | `/tmp/slo-86b-b1-green-derived-D1m2mIeE` | 50 passed; exit 0 |
| Green: body-time title paths + complete app module | `/tmp/slo-86b-b1-green-title-v8TmDFkM` | 175 passed; exit 0 |
| Red: installer wrapper text selected system Python | `/tmp/slo-86b-b1-red-interpreter-hqhQXdlJ` | 1 failed, 9 passed; exit 1 |
| Green: wrapper fix + full installer module | `/tmp/slo-86b-b1-green-installer-TDBabOhJ` | 112 passed; exit 0 |
| Initial Black check | `/tmp/slo-86b-b1-check-xcZ5GEMU` | 2 files needed formatting; exit 1; corrected |
| Full normal `make test` | `/tmp/slo-86b-b1-full-normal-txBIc4Be` | 5168 passed, 18 deselected; exit 0 |
| Full hostile `make test` | `/tmp/slo-86b-b1-full-hostile-4y6okkit` | 5168 passed, 18 deselected; exit 0; stand-in unchanged |
| Final focused/surrounding after receipt/doc edits | `/tmp/slo-86b-b1-final-focused-vJkpSgLv` | 333 passed; exit 0 |
| Final Black check | `/tmp/slo-86b-b1-final-black-Q6F4qmXJ` | 5 files unchanged; exit 0 |
| **Final full hostile `make test` after all code/doc edits** | **`/tmp/slo-86b-b1-final-hostile-ahlqmw2p`** | **5168 passed, 18 deselected, 202 warnings in 362.46s; exit 0** |

Final focused command tail:

```text
/root/.pyenv/versions/3.11.7/envs/slo-harness/bin/python -B -m pytest -q
-p no:cacheprovider --basetemp=<fresh-root>/tmp/pytest
 tests/test_slo_home_isolation.py tests/tui/test_app.py tests/config/test_cfg.py
 tests/auth/test_credential_resolver.py tests/cli/test_install.py
```

Final formatting command tail:

```text
/root/.pyenv/versions/3.11.7/envs/slo-harness/bin/python -B -m black --check
--line-length 110 tests/conftest.py tests/state_isolation.py
 tests/test_slo_home_isolation.py tests/tui/test_app.py tests/cli/test_install.py
```

Every invocation, including each original red test, used disposable command-level
HOME/SLO_HOME and an empty inherited environment rebuilt with explicit safe
values. TMPDIR and pytest basetemp stayed inside the command's owned root.
The full Makefile fallback was inspected and used unchanged; `tests.env` is absent.
A clean-prefix `poetry run python` verified the existing approved 3.11.7 environment.
No dependency installation or environment creation occurred. Existing 18 default
E2E/live exclusions were retained; no new skip or disabled assertion was added.

## Acceptance map

| Criterion | Evidence | Status |
|---|---|---|
| AC-I1: hostile HOME/SLO_HOME/auth/all inherited overrides leave stand-in unchanged | Final `command.json` names every override. `hostile-before.json` equals `hostile-after.json` (42 entries / 20 files); `hostile-unchanged.txt` is `True`. | PASS |
| AC-I2: complete binding registry and sensitive guard | Live AST inventory equals all 11 registry entries; a temp-owned new alias specimen is discovered and rejected. The setting-literal guard likewise rejects `SLO_NEW_STATE_DIR`. | PASS |
| AC-I3: distinct per-test roots, HOME, overrides and teardown | Default/import/config/lock/Claude assertions, two distinct-root cases, fresh-process probes for both isolation layers; `suite-cleanup.json` is `[]`. | PASS |
| AC-I4: full `make test` green with only b1 applied | Three complete Make runs passed; final post-edit gate above. No b2–b5 production changes. | PASS |

### Negative sensitivity receipts

Under the final gate's `tmp/pytest/`:

- `test_isolate_suite_slo_home_wh0`: suite positive probe, exit **0**.
- `test_isolate_suite_slo_home_wh1`: disabled suite override removal, exit **1**,
  `AssertionError: override-removal-disabled`.
- `test_isolate_suite_slo_home_wh2`: per-test positive probe, exit **0**.
- `test_isolate_suite_slo_home_wh3`: disabled per-test override removal, exit **1**,
  same causal assertion.

Each owns `probe-command.json`, `probe-output.log` and `probe-exit.txt`. The negative
registry is mutated only in that disposable subprocess; production files remain
untouched. The original red logs above separately preserve real pre-fix failures.

## Safety and remaining boundaries

- Real HOME, credentials, catalogs, captures and KB state were not used as test
  fixtures. Hostile values point exclusively at synthetic owned directories.
- Existing installer stubs remain regular files; no real binary symlink was added.
  `dpkg -V coreutils` was checked after stubbing suites and is empty in the final
  `coreutils.log` with exit 0 in `coreutils.exit`.
- Capture containment helpers, local transports and terminal guards were retained.
  No process-tree kill or machine administration was performed.
- These are test infrastructure boundaries, not a runtime sandbox for arbitrary
  new code that deliberately opens an absolute external path. The source guards
  cover direct module-level SLO_HOME imports and path-shaped setting literals;
  new differently named state mechanisms still require engineering review.
- This phase's required static gate is the b1 changed-file Black check. Full
  repository typing, b2–b5 acceptance, independent review and completion assessment
  remain with the parent workflow; none is claimed here. Historical waived checks
  were not treated as passes.
- No KB file was edited outside the authorized target. Suggested later reinforcement:
  **Trigger:** tests reload configuration or change HOME after collection.
  **Failure mode:** cached aliases and parametrized paths retain the previous root.
  **Practice:** isolate before imports, rebind cached defaults per test, and resolve
  HOME-dependent parameters inside the test body.
  **Verification:** fresh-process hostile probes, source-registry sensitivity,
  and byte/path-identical sentinel comparison after a full suite.

No b1 blockers remain. The parent can consume `isolated_slo_home` for the following
phases while continuing the command-level clean-environment safety procedure.
