# 86.b.2 — Catalog cache namespace implementation

Date: 2026-10-04

## Verdict

**Implementation and behavioral gates pass; phase readiness withheld for the broader changed-file formatting gate.** No independent review or whole-feature completion is claimed.

- Final isolated `make test`: **5183 passed, 18 deselected, 194 warnings; exit 0**.
- Catalog/integration surrounding partition plus removal probe: **450 passed, 3 deselected; exit 0**.
- Final focused separation/store/isolation tests plus removal probe: **45 passed; exit 0**.
- Black on the sub-spec's four named files, the edited store-test module and the retained removal probe: **6 files clean; exit 0**.
- Broader changed-file Black: **four prerequisite test files still fail**, with the same failure reproduced on their phase-start bytes. This is not waived or called green.
- Namespace/dead-reader searches: **no prohibited source literals or obsolete readers/callers**.
- Final `dpkg -V coreutils`: **empty output, exit 0**; suite-owned state root removed.

### Remaining blocker

The recovery plan calls for changed-file Black, but b2 section 7.4 expressly permits **filename replacements only** in its eleven existing test modules. Four of those files already fail Black:

1. `tests/agents/model_catalog/test_openrouter_budget_evidence.py`
2. `tests/agents/model_catalog/test_openrouter_real_store_recovery.py`
3. `tests/integration/test_openrouter_full_flow.py`
4. `tests/integration/test_openrouter_repeated_page_retention.py`

Their b2 changes are proven to be exactly the prescribed filename substitutions. No unrelated 86.a reformatting was performed. The parent needs authorization for a narrowly scoped formatting-only follow-up, or an explicit resolution of the gate/scope conflict. Historical waivers were not used. Reformatting these files would exceed the mechanical-only instruction, so this agent returns `ready=false` despite green behavioral gates.

Formatting evidence:

- `/tmp/slo-86b-b2-final-black-8Z3QoqMv/baseline-command.txt`, `baseline.log`, `baseline.exit`: original phase-start copies, **exit 1; four files need formatting**.
- Same directory: `mechanical-command.txt`, `mechanical.log`, `mechanical.exit`: current mechanical-only files, **exit 1; same four files**.
- `/tmp/slo-86b-b2-final-full-sHkSeqhg/black-command.txt`, `black.log`, `black.exit`: all non-mechanical b2 Python files and probe, **exit 0**.

## Scope and preservation

Only `/root/Code/slo-openrouter-implementation/slo`, branch `feature-86-openrouter-implementation`, was used for work. Every shell command explicitly changed to that directory. No delegation, staging, commits, branch changes, installation, external publication, live inference, real terminal windows or user-state cleanup occurred. Auth/resume production code is untouched.

Before implementation, all **817 original baseline entries** were reconciled with b1's seven recorded changes. No unexplained drift was found. A new phase-start snapshot preserves the post-b1 state:

- `b2-phase-start.json`
- `b2-phase-start.tar.gz`

The original `20261004T014228Z-d4346f44/` baseline and all b1 evidence remain unchanged. Incremental review uses the phase-start archive, **not HEAD**:

- [b2-incremental.diff](b2-incremental.diff)
- [b2-changed-files.json](b2-changed-files.json): **17 incremental source/test/research files**, before/after hashes, no unexplained changes.
- [b2-evidence-index.json](b2-evidence-index.json): **13 primary command receipts**, exact expanded commands, actual exits/counts and output hashes.
- [b2-static-checks.json](b2-static-checks.json): namespace checks, tag identity and suite-root cleanup.

All eleven mechanical test updates were additionally compared byte-for-byte against `phase_start.replace(old_filename, new_filename)` for both names. No other changes survived in those files.

## Incremental changed files

| File | b2 change |
|---|---|
| `src/agents/model_catalog/store.py` | Cache/lease constants use `.v2`; safe warning instead of error/traceback; explanatory docstring/comment; remove dead `load_cache`, `is_cache_fresh`, TTL and unused imports. |
| `src/agents/model_catalog/service.py` | Delete only dead `_should_refresh_discovery`. |
| `tests/catalog_cache_samples.py` (new) | Shared synthetic provider-cache sample for b2/b5. Provider, exact canonical route and API ID agree. |
| `tests/agents/model_catalog/test_cache_file_separation.py` (new) | Twenty cases covering default paths, full cold-load decision table, released-file preservation, real offline refresh and reload. |
| `tests/agents/model_catalog/test_model_catalog_store.py` | Remove the five specified obsolete tests and unused imports; remove resulting trailing blank line. Active store/lease/override tests retained. |
| `tests/agents/model_catalog/test_atomic_publication.py` | Filename substitutions only. |
| `tests/agents/model_catalog/test_catalog_process_ordering.py` | Cache/lease filename substitutions only. |
| `tests/agents/model_catalog/test_catalog_shutdown.py` | Filename substitution only. |
| `tests/agents/model_catalog/test_openrouter_budget_evidence.py` | Filename substitution only. |
| `tests/agents/model_catalog/test_openrouter_lifecycle.py` | Filename substitutions only. |
| `tests/agents/model_catalog/test_openrouter_real_store_recovery.py` | Filename substitutions only. |
| `tests/agents/model_catalog/test_openrouter_refresh_credential_contract.py` | Filename substitutions only. |
| `tests/agents/model_catalog/test_status_admission_takeover.py` | Filename substitution only. |
| `tests/integration/test_openrouter_full_flow.py` | Filename substitution only. |
| `tests/integration/test_openrouter_repeated_page_retention.py` | Filename substitution only. |
| `tests/integration/test_openrouter_scheduled_preparation.py` | Filename substitution only. |
| `RESEARCH.md` | Add durable filename-ownership/schema-evolution note; preserve prior history. |

Evidence-only `b2_dead_reader_probe.py` is retained in this report directory. It is explicitly invoked, not part of normal test discovery, and checks API removal without reintroducing obsolete names into `src/` or `tests/`.

## Test-first sequence and retained failures

Each receipt root contains `command.txt`, `output.log` and `exit.txt`. All commands ran in the authoritative working directory. The evidence index contains the full clean environment and argv, not a reconstructed command.

| Step | Receipt root under `/tmp/` | Actual result |
|---|---|---|
| Default writer and lease names red | `slo-86b-b2-red-paths-ME6lR2Et` | **2 failed, 15 passed; exit 1**. `.v2.json` and `.v2.lock` were not created. |
| Two constants changed; focused + store green | `slo-86b-b2-green-paths-inGJkz1b` | **17 passed; exit 0**. |
| Actual corrupt/unreadable log-record behavior red | `slo-86b-b2-red-logs-dberqsW2` | **4 failed, 20 passed; exit 1**. Logger emitted ERROR (40), not WARNING (30), and retained tracebacks. |
| Warning import/call and docstring changed | `slo-86b-b2-green-logs-1LpRp1eA` | **24 passed; exit 0**. |
| Removal assertions + surrounding filename consumers red | `slo-86b-b2-red-readers-surrounding-81O5G3Kw` | **22 failed, 422 passed, 3 deselected; exit 1**. Three obsolete APIs still existed; nineteen tests still expected old default filenames. |
| Dead readers and their five tests removed | `slo-86b-b2-green-readers-KrMR7i9l` | **22 passed; exit 0**. |
| Mechanical filename edits, first surrounding attempt | `slo-86b-b2-green-surrounding-kHUWNoka` | **10 collection errors; exit 2**. Agent-introduced stray replacement text in five files; not a product failure or valid red evidence. |
| Correct replacement text; exact baseline-substitution and AST verification | `slo-86b-b2-green-surrounding-retry-pOpt9xPr` | **450 passed, 3 deselected, 17 warnings; exit 0**. |
| Initial expanded Black check | `slo-86b-b2-black-G2NrCaJJ` | **Exit 1**, six files needed formatting. Two b2-owned files corrected; four prerequisite failures preserved and separately reproduced. |
| Complete non-E2E gate | `slo-86b-b2-full-73QbxfbB` | **5183 passed, 18 deselected, 196 warnings; exit 0**. |
| Owned-file Black + original/current four-file diagnosis | `slo-86b-b2-final-black-8Z3QoqMv` | Owned files **exit 0**; original/current mechanical files each **exit 1**. |
| Final focused, after explicit released schema-1 specimen correction | `slo-86b-b2-final-focused-Y7YXkAqM` | **45 passed, 2 warnings; exit 0**. |
| **Final complete gate after all source/test/research edits** | **`slo-86b-b2-final-full-sHkSeqhg`** | **5183 passed, 18 deselected, 194 warnings in 377.92s; exit 0**. Black owned files **exit 0**; coreutils **exit 0**, empty output. |

The preserved collection-error log is acknowledged as an editing mistake. The fix restores exactly the intended substitutions; no test assertions were weakened. For future mechanical changes, verify the complete baseline-relative replacement and parse affected files before invoking pytest.

Behavior changes were made in small units: two constants; then one logging call/import; then dead-code removal. New preservation/rebuild coverage extends existing behavior after those original red tests; it is not presented as additional fabricated pre-fix failures.

## Acceptance map

| Criterion | Implementation / proof | Result |
|---|---|---|
| AC-C1 | Default writer creates only `model_catalog_cache.v2.json`; real lease creates only `model_catalog_cache.v2.lock`; round-trip equality. | PASS |
| AC-C2 | Three released-cache states: schema-1 envelope, pre-fix schema-2 envelope, garbage. Cold load + real lease + write preserve both released cache and lock bytes and nanosecond mtime; directory has exactly the four expected files. | PASS |
| AC-C3 | Missing file: seed, no log, no mkdir. Valid schema 2: seed + exact slice, no log, unchanged bytes/mtime. Versions 1/3 and non-object JSON: seed + one info record. Malformed JSON, invalid slice schema, invalid encoding and injected read refusal: seed + exactly one warning, no exception/stack info and no sentinel leakage. Real service/client/local transport refresh replaces missing/corrupt/other-version/invalid/valid provider files and cold reload sees the newly discovered route. Transient read refusal also permits subsequent write/round-trip. | PASS |
| AC-C4 | Searches for single/double-quoted released names in `src/`: zero. Dead-reader search across `src/` and `tests/`: zero. Three explicit API-removal probes pass. Released-name test references exist only in the separation test module. | PASS |
| AC-C5 | Actual released executable after new write. Owned by b5; not run or claimed here. Local tag remains `f63df0a4958eedb4bc603f1946ba4591dd181fff`. | b5 |
| Focused/surrounding/full tests | Receipts above; full final gate includes surrounding catalog/integration cases after the last test edit. | PASS |
| Sub-spec four-file Black | Final Black covers those four plus store-test module and probe. | PASS |
| Recovery-plan all-changed-file Black | Four mechanically touched prerequisite modules still fail; originals fail too. | BLOCKED, not waived |

Actual grep-tool checks used these patterns:

```text
["']model_catalog_cache\.(json|lock)["']     under src/             -> no matches
load_cache\(|is_cache_fresh|_should_refresh_discovery  under src/  -> no matches
load_cache\(|is_cache_fresh|_should_refresh_discovery  under tests/ -> no matches
model_catalog_cache\.(json|lock)          under tests/           -> separation tests only
```

No catalog service, DAO, resolver, lock protocol, migration, admission or generation mechanism was added. Operator overrides and auth/resume behavior remain unchanged. New code never adopts or repairs pre-fix developer files.

## Safety, conventions and remaining boundaries

- Read the target's AGENTS/SLO/RESEARCH documents, overview and complete b2 sub-spec, recovery plan and b1 report. Confirmed vendored, installed and personal skill libraries; loaded workflow/code-test-loop, named arguments/types, declarative structure, docstrings, verification, domain-persistence testing, environment execution, naming, KB discovery and review hard rules.
- Consulted catalog architecture/compatibility KB research and ambient-environment reinforcement. Filesystem persistence was tested with real contained files, not a substitute mocked store or unrelated database setup.
- Every test command, including initial reds, used `env -i` and newly allocated HOME/SLO_HOME/TMPDIR. No inherited state overrides or credentials reached pytest. B1's pre-import/per-test fixture was retained; final focused gate includes its isolation guards.
- New fixture targets are resolved and checked below their per-test root **before** writes. Unreadability is a synthetic read error, not an ineffective root chmod test. All metadata HTTP is `MockTransport`; no live provider inference is claimed.
- Existing terminal-spawn and command-stub guards remain unchanged. `make test` used the inspected Makefile's synthetic fallback; `environments/tests.env` is absent. Clean-prefix Poetry verified the approved interpreter; no package/environment installation occurred.
- Full-suite source prerequisites were unchanged except the listed b2 changes; b1's audited safety changes remain in place. Both complete runs were followed by silent `dpkg -V coreutils` checks. Final suite temporary root cleanup is recorded in `b2-static-checks.json`.
- Full repository mypy, b3–b5 implementation, mixed-version executable proof and independent review remain with the parent workflow; no such pass is claimed by this leaf phase.
- No KB or Reinforcement file was changed outside the authorized working directory. Proposed durable KB addition: incompatible cache shapes need separate filenames because old readers may validate before checking schema; retain one persistence owner and remove obsolete readers after renaming. Proposed reinforcement: after exact multi-file replacement, prove the baseline-relative change is purely mechanical and AST-parse before testing; never mistake introduced collection errors for intended behavioral red evidence.

The implementation can be inspected and used by later phases, but the parent must resolve the explicit formatting scope/gate conflict before treating b2 as fully ready.
