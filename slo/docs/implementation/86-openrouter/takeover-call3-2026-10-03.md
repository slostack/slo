# Cohesive Step 1 takeover — Call 3 of 4 — 2026-10-03

**Verdict: REVISE.** This call continues Code-Test-Review Step 1 only; formal Steps 2 and 3 were not run. No model identity was supplied or inferred. The existing dirty branch and all pre-existing work were preserved. Only the mounted OpenRouter auth test and current Feature-86 reporting files changed. No specification, other-worktree, Git publication, external provider, credential, host, PATH, package, or system change occurred.

## Clause → owner → exact evidence reconciliation

| Required observable | Clause / production owner | Existing exact assertion | Call 3 disposition |
|---|---|---|---|
| Mounted post-save cancellation, including saved-state presentation | F86-02; 86.a.5 §7.2–7.3; `OpenRouterAuthenticationService` → `AuthenticationScreen` | `tests/auth/test_openrouter_authentication.py::test_refresh_failure_keeps_verified_key[cancel]` verifies service saved-state after cancellation. `tests/tui/authentication/test_openrouter_authentication.py::test_openrouter_modal_delegates_and_cancels` proves modal cancellation only with an injected non-persisting service. | **Closed.** New `test_mounted_post_save_cancellation_paints_saved_state` uses real local `/key`, store, service, mounted screen, blocked catalog refresh and Back cancellation. It asserts safe saved-state result, provider-selection return and retained store value. |
| Complete removal during an admitted run → next prepared resume rejection while old history remains readable | F86-25/27; 86.a.6 §7.1; catalog → session admission → history/resume | `test_prompt_catalog_admission.py::test_publication_during_prompt_is_pinned_until_next_admission` tests pinned old snapshot / later removal using substituted catalog and no history. `test_resume_route_precedence.py::test_resume_restores_persisted_route` tests flat/tree metadata precedence. | **Still missing as one required composition.** The two component cases must not be relabeled as a real removal-publication/history-backed resume test. |
| Normalized provider-body failure reaches populated headless status and terminal notifier/inbox with positive public-artifact controls in one operation | F86-03/35; 86.a.6 §7.2; normalizer → `HeadlessRunner` status → `WorkflowNotifier`/inbox | `test_openrouter_capture_secrecy.py::test_headless_preparation_failure_writes_terminal_status_and_notifies_with_safe_text` populates terminal status/notifier from a preparation failure. `::test_child_artifacts_preserve_admitted_redaction_after_rotation_or_resolver_failure` normalizes body content through child artifacts. | **Still missing as one required operation.** Neither test routes a normalized provider-body failure through populated headless terminal status and notifier/inbox together. |

The exact private same-route anchor is not altered. No generic historical-matrix label was treated as a gap. Native-startup / argv-equality claims were not recreated.

## TDD and verification

The new mounted test uses only test-owned `tmp_path` storage and `httpx.MockTransport`; it has no live network or credential. Its first draft failed before behavior execution because it lacked the client import. The corrected behavioral draft then failed because it expected a Textual notification to be compositor-painted after Back; the required safe saved-state renderer surface is the service result consumed by the screen. The final test asserts that state directly, while proving the mounted task lifecycle and persisted outcome.

All commands used exactly `/root/.pyenv/versions/slo-harness/bin/python` 3.11.7 with `-B`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH="$PWD"`, `-p no:cacheprovider`, and resolved checkout-owned `--basetemp` roots.

| Evidence | Command scope | Result |
|---|---|---|
| Focused red | new mounted cancellation node | First behavioral assertion failed before correction; retained at `.capture-call3-red-iwqnzytp/red2.log`. |
| Focused green | new mounted cancellation node | **1 passed, 2 warnings**; `.capture-call3-focused-b1aex9il/green.log`. |
| Affected modules | auth service/modal, headless/capture, prompt admission, resume, full flow | **60 passed, 9 warnings**; `.capture-call3-module-lr7t07kz/modules.log`. |
| Surrounding partition | TUI auth/app, notifier/capture, headless prep, session/catalog, resume, full-flow/scheduled integration | **244 passed, 1 deselected, 36 warnings, 181.47s**; `.capture-final-surrounding-nflcnbwg/surrounding.log`. |
| Static | Black and mypy on the changed auth test; `git diff --check` | Black: 2 unchanged; mypy: success; diff check: clean. |
| Complete non-E2E | `pytest -q -m 'not e2e' tests` after final edits | **5018 passed, 15 deselected, 194 warnings, 339.21s**; `.capture-final-green-q5pjyfgi/full.log`. |

No global static-green claim follows from that test result. The governing static approval is still absent: three baseline-attributed `tests/agents/slo_agent/orchestrator/test_process.py` mypy diagnostics require a narrow authorized repair or formal debt disposition. Whole-project Black still has five named baseline paths, and whole-project mypy retains 274 diagnostics across 46 files. No formatter or baseline repair was run.

## Changed paths

- `tests/tui/authentication/test_openrouter_authentication.py` — added the real mounted post-save cancellation regression.
- `docs/implementation/86-openrouter/takeover-call3-2026-10-03.md` — this detailed Call 3 report.
- `docs/implementation/86-openrouter/{remaining-requirements.md,current-status-2026-10-02.md,implementation-log.md}` — current finite requirement and evidence references only.

## Remaining Step 1 work

1. A single history-backed composition that complete-publishes route removal during an admitted run, then rejects the next prepared resume while existing history stays readable.
2. A single operation that carries a normalized provider-body failure into populated headless terminal status and terminal notifier/inbox, with positive ordinary/safe artifact controls and forbidden-marker absence checks.
3. Explicit operator approval/disposition for the three retained `test_process.py` mypy diagnostics and whole-project Black/mypy debt before any READY/global-static claim.
