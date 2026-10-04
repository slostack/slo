# 86.b.5 — Scope-corrected readiness for Step 2

## Verdict

**READY for independent Step 2 review.** All required local b5 acceptance gates pass on the current, unchanged source. This is a readiness assessment, not independent review, whole-feature completion, release approval, or remote CI evidence.

The earlier `b5-takeover-report.md` incorrectly promoted the additional repository-wide typing diagnostic into a requirement to remove unrelated baseline debt. B5 sections 8.5/9 and overview sections 9/11.3 require compatibility/observer tests, the non-E2E suite, isolation and the listed targeted checks. Changed-file formatting and **no new type errors** are also required by the task. Those gates pass. Full `mypy src/ tests/` remains **exit 1: 296 errors in 59 files**, identical to the original pre-86.b baseline. It is not green, suppressed, or waived; its baseline-only failure does not block this scoped handoff.

All prior reports, failures, archives and receipts remain unchanged. No production code, tests, CI, existing documentation, KB or live state was modified in this assessment. Only this new report was written.

## Assessment method and preservation

Worked in `/root/Code/slo-openrouter-implementation/slo`, branch `feature-86-openrouter-implementation`. Verified the existing interpreter reports Python 3.11.7 and local `v0.20.1^{commit}` is `f63df0a4958eedb4bc603f1946ba4591dd181fff`. No fetch, installation, Git mutation, child agent, provider call or test rerun occurred.

Read the actual target AGENTS/SLO and both RESEARCH files, full 86.b overview and b5 sub-spec, named workflow, phase/always-on and applicable testing conventions. Confirmed vendored, installed and personal skill libraries. Consulted the OpenRouter KB status and shared-state reinforcement note. Read the complete b5 compatibility runner, archive fixture, released programs, compatibility tests, actual visualize guard, root CI pytest job, Makefile, isolation seam and safe gate runner.

Verification was performed against actual bytes, not the predecessor's verdict:

- **831 current repository hashes** match `b5-receipts/final-hashes.json`, including CI and test/tool configuration. Every current Python file under `src`, `tests` and `config` is inventoried; no unlisted Python source appeared.
- **33 historical b5 log hashes** and **8 takeover log hashes** match their receipts. Takeover index entries also match their individual original command receipts; all recorded summary lines exist in the actual logs.
- All **817 original baseline files** match both their archived hashes and the actual temporary extraction used for the baseline typing run. The archive SHA-256 remains `a6aa0e12cfe5ecb387f7efe25089afcfdb4fa136cb3c11e401ff98bc69ad46fa`.
- Independently recomputed the cumulative baseline-relative Python changes: exactly the **40 files** supplied to the passing Black gate. Attribution does not use the large HEAD diff or assign pre-existing 86.a work to 86.b.
- The actual hostile stand-in inventory still matches its recorded before/after state: **36 entries unchanged**, inner make exit 0.
- All eight takeover `coreutils.log` files are empty, with recorded integrity exit 0. No command-stubbing suite was run in this assessment.
- Source searches find zero quoted released-cache filenames or obsolete reader/caller matches. Four external KB deliverables retain their handoff hashes.
- Repeated all 831 current-hash checks immediately before writing this report: no source drift.

The read-only retained-evidence verifier ran with exit 0:

```text
cd /root/Code/slo-openrouter-implementation/slo && /root/.pyenv/versions/3.11.7/envs/slo-harness/bin/python -I -B /root/Code/slo-openrouter-implementation/slo/docs/implementation/86b-model-catalog/b5-final-attempt-verify.py
```

Its historical explanatory `reason` string is not adopted as a gate definition. Additional independent read-only comparisons checked complete error **and note** signatures, extracted baseline bytes, current-file coverage, takeover receipts and hostile contents as described above. No evidence defect or source drift justified rerunning unchanged suites.

## Actual acceptance map

All test paths below are relative to the target inner `slo` directory.

| Criterion | Actual inspected proof | Status |
|---|---|---|
| **AC-X1** | `tests/compat/test_catalog_cache_mixed_versions.py`: real released schema-1 write, new provider-cache write, real released CLI import/load; equal released entry counts, unchanged released bytes, new cache reload equality, no catalog failure or traceback in either output stream. | PASS |
| **AC-X2** | `tests/compat/test_credentials_mixed_versions.py`: released Anthropic save → new OpenRouter save → released load/OpenAI save → new merged load. Exact three synthetic credentials and unchanged non-owning sibling bytes are asserted. | PASS |
| **AC-X3** | `tests/compat/test_session_resume_mixed_versions.py`: both default tree and explicit flat stores. Unknown released model falls back to `gpt-5.4`; real Faux-backed invocation continues history and rewrites model/startup metadata; released code hydrates and continues; new code rereads exact ordered contents. New OpenRouter history with private extensions also survives released continuation. | PASS |
| **AC-X4** | `tests/cli/test_visualize_state_independence.py`: actual `src.cli.main` parses `visualize --session observed --no-follow`, dispatches and mounts the actual app with Textual `run_test`. Only the terminal driver is replaced. Pre-import audit examines every path argument; observed session loads, zero catalog/credential hits, hostile bytes unchanged. | PASS |
| **AC-X5** | Actual frozen-source fixture extraction succeeds locally. On archive failure the fixture calls `pytest.fail`, never skips. Retained missing-tag experiment fails with the actual invalid-object diagnostic. Root CI pytest job sets `GIT_DEPTH: '0'` and `GIT_FETCH_EXTRA_FLAGS: '--tags'`; the default suite includes compat and the CI contract test passes. | PASS locally; remote CI not executed |

The current compatibility/observer gate is **11 passed, exit 0**, including the four tree/flat session cases and runner/CI checks. The released runner imports the archived code through an explicit minimal environment, restricts extra input to `COMPAT_*`, and confines writable HOME/workdir/TMPDIR beneath the per-test root. Inference uses Faux, not a live provider. The visualize proof opens no real terminal window.

The required documentation is present: two credential files and future-provider constraint; separate provider-cache filenames; unknown-model fallback; shared history and released compaction limitation; no action needed for released users; manual-only pre-fix cleanup. Existing b5 documentation/KB and CI changes remain preserved. Nothing cleaned up real developer state.

## Verified command receipts and results

**Exact expanded commands, complete clean environments, exits, log paths and SHA-256s:** [b5-takeover-index.json](b5-takeover-index.json). Individual originals: `b3-receipts/b5-takeover-*.json`. The table shows command tails for identification, not standalone safe execution recipes. All were run through the inspected command-owned environment runner; inherited state overrides were not passed through.

| Receipt / command tail | Exit | Actual result |
|---|---:|---|
| `b5-takeover-isolation`: `poetry run pytest -q tests/test_slo_home_isolation.py` | 0 | 12 passed, 2 warnings; 6.93s |
| `b5-takeover-persistence`: `poetry run pytest -q tests/agents/model_catalog tests/auth tests/integration tests/integrations` | 0 | 728 passed, 3 deselected, 17 warnings; 19.01s |
| `b5-takeover-resume`: `poetry run pytest -q tests/cli/test_resume_route_precedence.py tests/tui/test_startup_notice.py tests/tui/test_app.py` | 0 | 215 passed, 30 warnings; 173.90s |
| `b5-takeover-compat`: `poetry run pytest -q tests/compat tests/cli/test_visualize_state_independence.py` | 0 | 11 passed, 4 warnings; 19.01s |
| `b5-takeover-full`: `/usr/bin/make test` | 0 | **5299 passed, 18 deselected, 203 warnings; 387.10s** |
| `b5-takeover-hostile`: `python -B .../b5-receipts/hostile_gate.py` → `/usr/bin/make test` | 0 | **5299 passed, 18 deselected, 203 warnings; 388.78s**; 36 stand-in entries unchanged |
| `b5-takeover-black`: `poetry run black --check -l 110` with the 40 listed cumulative 86.b files | 0 | 40 files unchanged |
| `b5-takeover-scoped-types`: `poetry run mypy --cache-dir="$TMPDIR/mypy" --follow-imports=silent tests/compat tests/cli/test_visualize_state_independence.py tests/agents/model_catalog/test_cache_file_separation.py tests/auth/test_credential_file_split.py` | 0 | 11 source files clean; **scoped**, not repository-wide |

Actual full-suite logs were inspected, including their final summaries:

- Normal: `/tmp/slo-86b-b3-b5-takeover-full-4i99pvjz/output.log`, SHA-256 `a8f6cef86f2f6db0c051a238131c37c2cac72d23b5f8296e1d1e2cdbd89fb4f0`.
- Hostile: `/tmp/slo-86b-b3-b5-takeover-hostile-o36l643g/output.log`, SHA-256 `19577448114d03b35d402327cb802503ca946303117e9a303a77b3643ab8f952`.
- Compatibility/observer: `/tmp/slo-86b-b3-b5-takeover-compat-4t8spmxt/output.log`, SHA-256 `5db6f3d1a1b43ea70f70535a1c2d3ac33e0e70e82f2654bc1fde522e2d621ec0`.

The 18 deselections are the unchanged non-E2E contract. Warnings remain reported, not hidden. No assertion, marker or timeout changed in this assessment.

Retained sensitivity evidence was hash-verified in `b5-receipts/index.json`: catalog old-name failure **exit 1 / 1 failed**; single-file credential failure **exit 1 / 1 failed**; old resume selection **exit 1 / 2 failed**; injected observer read **exit 1 / 1 failed**; missing tag **exit 1 / 1 setup error**; CI pre-change **exit 1 / 1 failed**, then **exit 0 / 20 passed**. These failures are expected proof, not successful test runs. The missing-tag log explicitly reports `fatal: not a valid object name: v0.0.0-86b-intentionally-absent` and no skip.

## Complete typing comparison — baseline debt remains red

Compared actual complete logs, not just the totals:

| Run | Actual command scope | Result | SHA-256 of full output |
|---|---|---|---|
| Current `b5-final-types` | `mypy src/ tests/` | Exit 1; 296 errors in 59 files; 654 source files checked | `1920ec72b0f1be92197d279b60c2f508b79a7276ca5297b1da4d04f91c4122f3` |
| Original `b5-types-original-baseline` | Same `mypy src/ tests/`, existing interpreter, archived pre-86.b source | Exit 1; 296 errors in 59 files; 640 source files checked | `1600a6b05617d6006391f9cfcd2b357b1a9d2be76983c96636c0ad45a7315c69` |

Paths:

- `/tmp/slo-86b-b3-b5-final-types-a8dquyms/output.log`
- `/tmp/slo-86b-b3-b5-types-original-baseline-nfqxr9gb/output.log`

Method: parse every `: error:` and `: note:` line; normalize only numeric source locations before the severity; compare **Counters**, retaining file paths, complete messages, error codes and duplicate multiplicity. Both logs contain **720 diagnostic lines: 296 errors and 424 notes**. Their normalized diagnostic multisets are identical: **zero added or removed error/note signatures**. Verified all 817 files in the actual baseline extraction against the original manifest; inspected `check_baseline_types.py` to confirm it runs the existing interpreter on that extraction without suppression changes. Current source/config hashes still match the post-gate freeze.

Examples of the outstanding debt are missing PyYAML stubs, existing FauxChatModel override typing and FakeHost protocol mismatches. They remain failures. No stubs were installed, ignores added, configuration weakened, or unrelated remediation performed. No-new-diagnostics is proved; repository-wide typing success is not claimed.

## Formatting and verification corrections

The explicitly authorized b2/b3 formatting changes are not scope violations. Independently checked AST equivalence for the four b2 files at the formatting boundary and for the b3 harness against its pre-format snapshot. Existing failing Black receipts remain retained.

One initial read-only AST comparison exited 1 because it compared b2's pre-format full-flow test directly with current source, which also contains b3's documented credential-path substitution. A second probe exited 1 because it assumed the targeted b3 snapshot contained every b2 file. Neither was a test or source drift. The corrected comparison uses the b3 phase-start bytes for that later-modified file (matching the recorded b2 post-format hash), current bytes for unchanged files, and checks exact before/after hashes plus AST identity. It exits 0 for all five authorized formatting files. This prevents misattributing a later approved behavior change to formatting.

## Handoff

No actual b5 acceptance blocker remains. Carry forward the current hashes, original baseline, exact receipts, AC-X1–5 map and explicit baseline-only typing failure to the parent-owned independent Step 2 review. Step 2/Step 3, remote CI, merge and deployment are **not** claimed complete. Released compaction's known private-extension loss on rewritten events and manual pre-fix credential cleanup remain documented limitations, not newly introduced failures.
