# Cohesive Step 1 takeover — Call 2 of 4 — 2026-10-03

**REVISE.** This is implementation/evidence reconciliation, not formal review or completion. Model identity is unavailable in this session; no model name is inferred. HEAD remains `f63df0a4958eedb4bc603f1946ba4591dd181fff`, branch `feature-86-openrouter-implementation`, with all pre-existing tracked/untracked work preserved. This call modifies only the auth service, its tests, and the documentation named below. No spec/Git publication/system/environment changes or live provider requests.

## Actual repair: F86-02/20/26/32

Immutable overview §7.2: “If the environment changed meanwhile, discard the verification result and report ‘Credential changed; retry authentication.’”

`OpenRouterAuthenticationService._persist_verified_candidate` previously returned immediately for every environment capture. If A became B or disappeared while GET `/key` completed, the service exposed A through `verified_credential()`, set `key_verified=True`, and invoked catalog refresh. The new `_validate_environment_capture` uses the existing source-bearing resolver immediately after verification and before success/handoff. It rejects changed source/key, preserves stored bytes, exposes no verified credential and performs no refresh. No new credential precedence or owner.

The two new cases use the real resolver, real temp store and GET client with `httpx.MockTransport`; the response handler rotates/removes the environment variable before returning. Temp ancestry is asserted before persistence. MonkeyPatch restores environment and store injection. No subprocess or external HTTP is used in this unit.

## Finite requirement-to-assertion reconciliation

Paths below are under `tests/`; assertions were inspected, and the complete current suite passed. “Covered” applies to the named observable, not automatic closure of an entire F86 ID.

| ID / exact immutable sentence | Production owner | Existing assertion | Disposition |
|---|---|---|---|
| F86-02, overview §7.2: “On 401/403/malformed response/timeout/cancel, preserve existing stored credential byte-for-byte” | auth service / CredentialStore | `auth/test_openrouter_authentication.py::test_verification_failure_preserves_bytes` covers all five outcomes, unchanged bytes and no refresh | Covered; not a missing generic cancellation case |
| F86-02, a.5 §7.2: “Cancel after persistence may leave verified key saved and must state that.” | auth service | `test_refresh_failure_keeps_verified_key[cancel]` asserts saved token, verified/saved flags and saved-state message | Covered at service boundary |
| F86-02/26, overview §7.2 environment-change sentence above | auth service | existing `test_environment_appearing_before_commit_discards_candidate` preserves old bytes/no refresh; new `test_environment_changes_during_verification_discard_verified_capture` covers environment A→B and A→store | Candidate race already covered; captured-env race fixed red→green |
| F86-02, a.5 §7.3: “Back/Cancel/unmount invalidates token, cancels and awaits the task” | AuthenticationScreen | `tui/authentication/test_openrouter_authentication.py::test_openrouter_modal_delegates_and_cancels` observes cancellation, one submission, no file across three navigation cases | Covered with injected service; real mounted post-save cancellation/saved-state paint is not yet demonstrated by this assertion |
| F86-23/26, a.2 §7.4: “Recompute effective fingerprint before save and before publish; mismatch discards the candidate.” | ModelCatalogService | `agents/model_catalog/test_openrouter_refresh_credential_contract.py::test_refresh_when_auth_supplies_fresh_matching_capture_rechecks_effective_identity_before_publication` asserts credential_changed, zero key GET, one models GET, no cache, cleared verification | Covered named publication race, not generic missing cross-context race |
| F86-24, a.4 §7.2: “Same-fingerprint stale entry remains usable on transient discovery failure” | catalog admission | `agents/model_catalog/test_openrouter_admission_security.py::test_prepare_models_when_same_key_listing_is_stale_and_refresh_fails_admits_cached_route` asserts admitted route after failed refresh | Covered admission; a.6 composed restart/resume path remains distinct |
| F86-25/27, a.6 §7.1: “complete refresh removes active model while a prompt is in flight: old run retains old snapshot; next admission fails with refresh guidance; history remains readable” | catalog + session + history | `agents/slo_agent/test_prompt_catalog_admission.py` asserts pinned old snapshot, next metadata adoption, removed admission refusal; its prepare/load are substituted and history is disabled. `cli/test_resume_route_precedence.py` asserts tree/flat identity precedence separately | **Missing exact composition:** real complete removal publication during admitted run → next prepared resume refusal → readable existing history. Existing component assertions are not that composed case |
| F86-06, a.4 §7.4: “reacquire/check lock because a prompt may have started” | session selection | `agents/slo_agent/test_catalog_generation.py::TestOpenRouterSessionSelection::test_prepare_model_selection_when_prompt_starts_during_preparation_preserves_current_state` asserts busy rejection and unchanged route | Covered named race; no invented cross-context combinations |
| F86-22/37, a.4 §7.6: “existing drain/status/notify lifecycle” | capture writer, existing isolated reporter, WorkflowHandleStore | `agents/slo_agent/orchestrator/test_capture_contained_lifetime.py::test_reaped_launcher_late_capture_failure_requires_durable_health` asserts live unchanged PID/PGID/state, fresh health/status, both populated redacted captures, shipped-source/native-I/O/EBADF/reporter receipts | Covered bounded lifecycle. Instrumented shipped bodies, not native startup. No repeat experiment or argv-equality requirement |
| F86-03/35, a.6 §7.2: “Generate one sentinel secret and one raw error/body marker. Search captured ... headless stdout/stderr and status/fleet/capture files” | normalizer → child pumps/status/fleet; headless notifier | `agents/slo_agent/orchestrator/test_openrouter_capture_secrecy.py::test_child_artifacts_preserve_admitted_redaction_after_rotation_or_resolver_failure` creates raw marker only at normalizer, then asserts positive ordinary/safe content and absent A/B/body across populated child files and relay/log/lifecycle; preparation failure test populates status/notifier. These are separate compositions | Child artifacts covered, including resolver failure. **Remaining precise integration evidence:** normalized body-marker failure reaching populated headless status + terminal notifier/inbox with positive controls in the same operation; do not feed arbitrary body text to FD redactor |
| F86-11, a.3 §7.4: “preserve unknown detail keys/encrypted strings/order exactly” | codec / history projector | `integration/test_openrouter_scheduled_preparation.py::test_active_schedule_inbox_drives_mounted_prepared_openrouter_session` asserts one exact private history extension, second same-route SDK reasoning_details and tool result, clean public transcript/events | Covered; no anchor edits or duplicate private-anchor tests needed |
| F86-38–40, a.6 acceptance: “Scoped tests, formatting, type check, and full non-e2e suite pass before completion is claimed” | existing verification gates | fresh full 5017 passed; scoped Black 154 clean; scoped mypy three unchanged baseline diagnostics; global static historical non-green | **Undisposed gate**, no waiver inferred |

The exact remaining behavior work is therefore the three bounded composed cases above: mounted post-save cancellation/saved-state presentation; complete removal/in-flight pinning/next prepared resume/readable history; normalized headless failure/status/notifier positive-artifact secrecy. They were not implemented this call. Do not expand these into arbitrary FD, native-startup, quota, platform or context matrices. The new auth defect is closed, but these composed assertions prevent whole-Step-1 readiness.

## Commands and results

All commands ran in this checkout using exactly `/root/.pyenv/versions/slo-harness/bin/python` **3.11.7**, `PYTHONDONTWRITEBYTECODE=1`, `-B`; pytest timeout was **1200 seconds**. Fresh owned logs/temps are `.f86-takeover-call2/`; no prior artifact was deleted.

Common pytest invocation:

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=.f86-takeover-call2/BASE NODES --tb=short
```

| BASE / complete log | NODES | Result |
|---|---|---|
| red / red.log | `tests/auth/test_openrouter_authentication.py -k environment_changes` | 2 failed, 11 deselected; obsolete environment-active/key-verified message instead of credential-changed |
| green / green.log | `tests/auth/test_openrouter_authentication.py` | 13 passed, 1 warning |
| surrounding / surrounding.log | previous module + `tests/tui/authentication/test_openrouter_authentication.py tests/integration/test_openrouter_full_flow.py tests/agents/model_catalog/test_openrouter_refresh_credential_contract.py` | 37 passed, 5 warnings, 27.14s |
| full / full.log | `-m 'not e2e' tests` | **5017 passed, 15 deselected, 199 warnings, 338.24s** |

After final code edits: `python -B -m black --check --no-cache src/auth/openrouter_authentication.py tests/auth/test_openrouter_authentication.py`: 2 unchanged. `python -B -m mypy --follow-imports=silent --cache-dir=.f86-takeover-call2/mypy` on those files: clean. Full suite ran once. `git diff --check` and `dpkg -V coreutils`: no output.

Current manifest `.f86-takeover-call2/retained-paths.txt`: **154** actual changed/untracked Python source/test files from `git diff --name-only HEAD -- src config tests` and `git ls-files --others --exclude-standard -- src config tests`, normalized relative to checkout. Same generated-artifact exclusion principle as existing provenance: baseline copies and fixture scratch outside actual source roots are not production/test owners. No unknown artifact deletion. Full retained-path Black: 154 unchanged; mypy: exactly three errors below. Logs `retained-black.log`, `retained-mypy.log` retain full output.

## Static decision — approval required, not granted

`test_process.py` diff adds only `TestSubAgentProcessChildCredentialRedaction`; these diagnostics belong to unchanged baseline tests, not the changed Feature 86 contract:

```text
tests/agents/slo_agent/orchestrator/test_process.py:939: error: Unsupported left operand type for / ("MonkeyPatch")  [operator]
tests/agents/slo_agent/orchestrator/test_process.py:1041: error: Item "None" of "_Call | None" has no attribute "kwargs"  [union-attr]
tests/agents/slo_agent/orchestrator/test_process.py:1066: error: Item "None" of "_Call | None" has no attribute "kwargs"  [union-attr]
```

Required approval: narrowly repair baseline `tmp_path: pytest.MonkeyPatch` to `Path` and assert each `create_process.await_args is not None` before accessing kwargs (no cast/ignore/assertion weakening), **or** explicitly accept retained static debt. Conditional permission for already-changed Feature 86 contracts does not authorize unrelated baseline edits.

Global Black historical five paths: `config/timeout_resolver.py`, `tests/agents/providers/test_openai_codex.py`, `tests/agents/slo_agent/orchestrator/test_spawn_tool.py`, `tests/cli/test_release_automation.py`, `tests/cli/test_install.py`. Do not format them without approval.

Global mypy retained log `.f86-step1-static-idys9mho/global-mypy.log`: 274 errors / 46 files / 631 checked, not rerun here. Categories: arg-type 124, union-attr 43, attr-defined 30, assignment 20, method-assign 18, call-arg 12, misc 6, operator 6, index 5, override 3, import-untyped 2, dict-item 2, valid-type/return-value/name-defined 1 each. Exact file list is retained in `takeover-call2-static-files.txt` adjacent to this report. Governing a.6 §9 requires passing type/format gates; baseline attribution is not acceptance. Explicit remediation authorization or formal gate-debt acceptance remains required. No global-green claim.

## Limits and safety disclosure

No new actual child or live/native-startup experiment. Full suite reused existing finite capture guards and fixture isolation repaired in the prior owner; complete log includes their tests. Existing command-stub tests passed; coreutils integrity check was empty afterward. No skips/xfail/ignored diagnostics added. Initial oversized skill read generated a tool-managed `/tmp/slo-bash-2y6rp800.txt` spill; not modified/deleted. Later reads were bounded. KB consulted read-only because work is restricted to this checkout; its full-suite failure claim is stale and must eventually be reconciled by an authorized KB writer.
