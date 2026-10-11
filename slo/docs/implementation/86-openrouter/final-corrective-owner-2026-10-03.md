# Final Step-1 corrective owner — 2026-10-03

**Bounded repair COMPLETE; Feature 86 Step 1 REVISE.** No formal review or completion workflow ran. Model identity is not exposed by this session; no model name is inferred. Call ID: `F86-final-corrective-owner-20261003`; requirement scope: F86-03/22/37 (containment, terminal identity/security), F86-38/39 verification gates. This is not whole-feature acceptance.

## Corrections and evidence

All changes are test-only. Existing dirty/untracked work was preserved.

- `tests/agents/slo_agent/orchestrator/capture_test_safety.py`: reporter bootstrap now requires the caller's MonkeyPatch owner and patches `os.devnull` through that same owner. Previously it created an unowned MonkeyPatch in the pytest interpreter, leaving network and async process guards installed after its qualification test. Finite writer children explicitly supply their process-lifetime owner. All default-deny admission checks remain.
- `test_capture_contained_lifetime.py`: the reporter qualification test supplies its pytest-owned patch lifetime.
- New `test_capture_guard_lifetime.py`: two repeated uses, normal and exceptional teardown, prove restoration of Popen, async exec, all three socket guards and devnull; prohibited process/network operations still fail before side effects inside each scope. Initial RED was the missing explicit lifetime argument; the original full gate separately proves the behavioral leak.
- `test_capture_control_protocol.py`: destination-open failure closes six pipe FDs **plus the append lease**. The test now supplies a fake lease FD and asserts all seven closes. Previously its global `os.close` recorder swallowed closure of a real lease FD and omitted it from the expectation. Production cleanup is unchanged.
- `test_project_context.py`: a module-local fixture hides instruction-file existence outside the resolved per-test root. The real walk and fixture-created ancestor/global/workspace files remain exercised, including discovery above `.git`. No production discovery change and no basetemp outside the checkout.
- `test_openrouter_preparation.py`: absent credentials are modeled as `None`, not an invalid MagicMock credential. Assert two resolver calls for failed admission, one when catalog load fails first. Source contract: `ModelCatalogService._prepare_openrouter_admission` resolves admission identity; `WorkflowNotifier._safe_enqueue` independently calls `CredentialResolver.redact_openrouter_text` before serialization. Keeping that second lookup protects terminal output. Single session identity, exactly one terminal status/notification, no factory/invoke, safe populated artifacts remain asserted.

## Exact command recipe and retained outputs

Working directory `/root/Code/slo-openrouter-implementation/slo`.
Python `/root/.pyenv/versions/slo-harness/bin/python`, verified **3.11.7**.
Every pytest command below used this prefix and suffix, with tool timeout **1200 seconds**:

```bash
PYTHONDONTWRITEBYTECODE=1 /root/.pyenv/versions/slo-harness/bin/python -B -m pytest \
  -q -p no:cacheprovider --basetemp=.f86-final-correction/BASE NODES --tb=short
```

`O=tests/agents/slo_agent/orchestrator` below is path abbreviation only. Outputs retained under `.f86-final-correction/`; every BASE was fresh, never reused or cleaned.

| BASE / log | NODES | Result |
|---|---|---|
| a-red / a-red.log | `O/test_capture_guard_lifetime.py` | 2 failed: missing monkeypatch parameter |
| a-green / a-green.log | `O/test_capture_guard_lifetime.py O/test_capture_contained_lifetime.py O/test_capture_writer.py O/test_detached_fd_capture.py tests/agents/slo_agent/plugins/test_installer.py tests/auth/test_oauth_flow.py` | 123 passed, 2 warnings, 25.64s |
| b-red / b-red.log | `O/test_capture_control_protocol.py::test_destination_open_failure_closes_all_six_fds` | 1 failed: extra closed append FD |
| b-green / b-green.log | `O/test_capture_control_protocol.py O/test_capture_ack_cleanup.py` | 35 passed, 1 warning, 0.25s |
| c-red / c-red.log | `tests/agents/slo_agent/test_project_context.py` | 3 failed, 14 passed; exact nodes below |
| c-green / c-green.log | `tests/agents/slo_agent/test_project_context.py tests/agents/slo_agent/test_prompts.py` | 60 passed, 2 warnings, 1.20s |
| d-red / d-red.log | `tests/cli/test_openrouter_preparation.py -k failure_has_one_identity` | 2 failed, 7 deselected; both boolean cases |
| d-green / d-green.log | `tests/cli/test_openrouter_preparation.py tests/cli/test_headless.py O/test_notifier.py O/test_openrouter_capture_secrecy.py` | 71 passed, 2 warnings, 2.20s |
| full / full-non-e2e.log | `-m 'not e2e' tests` | 5015 passed, 15 deselected, 194 warnings, 334.48s |
| full-final / full-final.log | `-m 'not e2e' tests` | **5015 passed, 15 deselected, 194 warnings, 334.32s**, after formatting |

Project-context RED nodes:
- `TestProjectContextDiscovery::test_no_files_returns_empty`
- `TestProjectContextDiscoveryWorkspace::test_workspace_folder_contributes_workspace_tier_entries`
- `TestProjectContextDiscoveryWorkspace::test_workspace_folder_dedupes_against_cwd_walk`

Static path set is exactly the six Python files named above, including full paths for the abbreviated orchestrator files. Commands:

```bash
PYTHONDONTWRITEBYTECODE=1 /root/.pyenv/versions/slo-harness/bin/python -B -m black --check --no-cache PATHS
PYTHONDONTWRITEBYTECODE=1 /root/.pyenv/versions/slo-harness/bin/python -B -m black --no-cache tests/agents/slo_agent/orchestrator/test_capture_guard_lifetime.py tests/cli/test_openrouter_preparation.py tests/agents/slo_agent/test_project_context.py
PYTHONDONTWRITEBYTECODE=1 /root/.pyenv/versions/slo-harness/bin/python -B -m mypy --follow-imports=silent --cache-dir=.f86-final-correction/mypy PATHS
git diff --check
dpkg -V coreutils
```

Initial Black: three would reformat; final Black: six unchanged. Mypy: no issues in six files. Final diff check and coreutils verification produce no output. No host tools replaced. No Git publication/mutation, spec edits, external network or live provider credential use. Local fixture loopback traffic is exercised. No global static rerun or baseline-debt correction is claimed.

## Remaining blockers

- No failing tests remain in the final complete non-E2E run. Warnings remain (194), including unawaited AsyncMock warnings.
- Last retained corrected Feature-86 static scope: 150 paths, Black clean, mypy three baseline-attributed errors in `tests/agents/slo_agent/orchestrator/test_process.py`. This call's six-file pass does not supersede that scope.
- Last retained global gates: Black five existing failing paths (`config/timeout_resolver.py`, `tests/agents/providers/test_openai_codex.py`, `tests/agents/slo_agent/orchestrator/test_spawn_tool.py`, `tests/cli/test_release_automation.py`, `tests/cli/test_install.py`); mypy 274 errors in 46 files / 631 checked. Historical, not freshly rerun here.
- Broader capture/security and adverse auth/catalog/resume acceptance remain open. Bounded append ordering/refusal, independent-process admission, append-wait cancellation and instrumented shipped-body/native-I/O EBADF proof are retained; not native interpreter-startup equivalence, full cleanup/security certification, or a new argv-equality requirement.

Process deviation: one oversized pre-read produced tool-managed `/tmp/slo-bash-__1ajjtf.txt` output spill outside the requested checkout. It was not modified or removed. Subsequent output was bounded. KB was consulted read-only; no KB writes because this task restricts writes to the checkout.
