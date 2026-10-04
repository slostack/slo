# Final cohesive Step 1 owner — Call 4/4 — 2026-10-03

**Terminal verdict: REVISE. No further dispatch; no formal Step 2/3.** Model identity is not exposed by this session and is not inferred. HEAD remains `f63df0a4958eedb4bc603f1946ba4591dd181fff` with accumulated dirty work preserved. No staging, commit, publication, spec edit, unknown-artifact removal, other-worktree or shared environment change.

## Finite clause → owner → observation reconciliation

| Case / immutable clause | Existing evidence and its limit | Final exact evidence |
|---|---|---|
| A: F86-25/27/37; 86.a.6 §7.1(4): “complete refresh removes active model while a prompt is in flight: old run retains old snapshot; next admission fails with refresh guidance; history remains readable”; 86.a.4 §§7.3/7.5 | `test_prompt_catalog_admission.py::test_publication_during_prompt_is_pinned_until_next_admission` substitutes catalog/load preparation and disables history. `test_resume_route_precedence.py::test_resume_restores_persisted_route` proves metadata precedence separately. These did not close the composition. | **Closed** by `tests/integration/test_openrouter_final_compositions.py::test_complete_removal_during_run_rejects_prepared_resume_with_readable_history`. Real resolver/store/GET client/converter/catalog publication/session/factory/SDK/history. Event barrier holds actual admitted inference; complete empty authenticated list publishes removal; session retains admitted snapshot; response finishes and persists. A new `SloAgentSession.prepare` using the same persisted identity/route rejects with refresh guidance; history is byte-identical and production projector still returns the answer. Exactly one inference request. No catalog/session internal substitution. |
| B: F86-03/35/37/39; 86.a.3 §§7.5–7.7 and 86.a.6 §7.2: raw provider body excluded from public headless/status/capture output; 86.a.4 §7.6 existing terminal reporting | `test_openrouter_capture_secrecy.py::test_child_artifacts_preserve_admitted_redaction_after_rotation_or_resolver_failure` normalizes provider body into child artifacts; `::test_headless_preparation_failure_writes_terminal_status_and_notifies_with_safe_text` populates status/notifier from unrelated preparation failure. Separate operations did not close B. | **Closed** by `test_openrouter_final_compositions.py::test_normalized_provider_failure_populates_headless_status_and_terminal_inbox[False]`: one actual SDK HTTP400 body with synthetic credential and distinct body marker traverses real normalizer/session/HeadlessRunner/status/WorkflowNotifier/inbox. Positive controls require one safe `run_failed`, failed status/exit1/same session identity, exactly one terminal inbox message containing safe failure copy, ordinary prompt in started inbox, and terminal stderr lifecycle. Populated history/status/inbox, stdout/stderr and logs exclude both markers. `[True]` additionally covers only the repaired runner's fallback decision when SDK raises before session event emission. |

No private-anchor changes: retained same-route encrypted continuation tests remain unchanged. No arbitrary FD-body filtering, native startup/argv-equality requirement, framework, archive, or credential-order change.

## Minimal production correction

B initially reproduced **two `run_failed` events**. The session already emits its terminal event and then propagates the normalized exception; `HeadlessRunner.invoke` unconditionally emitted another. `src/cli/headless.py` now tracks whether a parent terminal event was received and emits fallback failure only when none was received. Child terminal events do not set this flag. The new B parameter covers the fallback branch using the real SDK normalizer but replacing the stream-drain boundary; the False case remains the complete production flow. No exception is hidden from status/notifier. This is a single-run runner flag, not a new lifecycle owner.

## Commands and complete evidence

Only `/root/.pyenv/versions/slo-harness/bin/python -B` was used. Common pytest prefix:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" /root/.pyenv/versions/slo-harness/bin/python -B -m pytest -q -p no:cacheprovider --basetemp=.f86-final-call4/BASE NODES --tb=short
```

All pytest tool timeouts: 1200 seconds. Logs and fresh temp roots retained under `.f86-final-call4/`; none reused/deleted.

| BASE / log | NODES | Result |
|---|---|---|
| a-red / a-red.log | new composition module (A only) | 1 failed: test used nonexistent `root_dir` constructor keyword. This is fixture/API red, **not** a production behavior defect. |
| a-green / a-green.log | same | 1 passed, 3 warnings; corrected to existing `root=` and added projector assertion. |
| a-surrounding / a-surrounding.log | `tests/integration/test_openrouter_full_flow.py tests/agents/slo_agent/test_prompt_catalog_admission.py tests/cli/test_resume_route_precedence.py tests/integration/test_openrouter_final_compositions.py` | 20 passed, 10 warnings, 26.40s |
| b-first / b-first.log | new module (A+B) | 1 failed, 1 passed: `assert len(failures) == 1`, actual 2. Genuine runner duplicate emission. |
| b-green / b-green.log | same after owner correction | 2 passed, 4 warnings |
| b-surrounding / b-surrounding.log | `tests/cli/test_headless.py tests/cli/test_openrouter_preparation.py tests/agents/slo_agent/orchestrator/test_notifier.py tests/agents/slo_agent/orchestrator/test_openrouter_capture_secrecy.py tests/integration/test_openrouter_final_compositions.py` | 73 passed, 4 warnings |
| final-surrounding / final-surrounding.log | preceding five paths + `tests/integration/test_openrouter_full_flow.py tests/agents/slo_agent/test_prompt_catalog_admission.py tests/cli/test_resume_route_precedence.py` | 93 passed, 11 warnings, 27.85s; both B paths |
| full / full.log | `-m 'not e2e' tests` | **1 failed, 5020 passed, 15 deselected, 201 warnings, 340.18s; exit 1**. Exactly one full run after final code/test modifications. |
| selection-isolation / selection-isolation.log | `tests/tui/test_selection_scroll_highlight.py::TestPilotVisibleSelection::test_selection_paint_and_scroll_remain_native_for_every_visible_body_and_theme[slo-default-thinking]` | 1 passed, 2 warnings, 2.94s; does not supersede full failure. |

Full failure inspected:

```text
tests/tui/test_selection_scroll_highlight.py:159:
    start = _location_for_offset(app=app, body=body, target=Offset(x=6, y=0))
tests/tui/test_selection_scroll_highlight.py:54:
    raise AssertionError(f"offset {target} was not visible")
E AssertionError: offset Offset(x=6, y=0) was not visible
```

The helper searches compositor hit-test offsets after a fixed one-second mount/follow-pin/layout wait. The isolated pass is evidence of differing execution conditions, **not** baseline attribution, root cause, waiver, or proof that the full suite is green. No assertion weakening, additional sleeps, skip, or unrelated selection repair. Required handoff: isolate the full-order visibility/layout failure and establish a valid green governing gate under new authorization; no further dispatch is available in this call.

Affected static commands:

```text
python -B -m black --no-cache src/cli/headless.py tests/integration/test_openrouter_final_compositions.py
python -B -m black --check --no-cache src/cli/headless.py tests/integration/test_openrouter_final_compositions.py
python -B -m mypy --follow-imports=silent --cache-dir=.f86-final-call4/mypy src/cli/headless.py tests/integration/test_openrouter_final_compositions.py
git diff --check
dpkg -V coreutils
```

Here `python` denotes only the absolute interpreter above, never PATH Python. Formatter changed only the new test. Final check: two unchanged (`black.log`); mypy: success for two files (`mypy.log`). Diff/coreutils checks empty. The new source/test diff was inspected; broader dirty work was not reset or reformatted.

## Remaining governing gates / exact approval

A and B's finite observations are closed. READY remains forbidden:

1. The **current full non-E2E gate fails** at the exact selection node above. Call 3's 5018-pass result is historical after this call's source/test change.
2. Retained static `tests/agents/slo_agent/orchestrator/test_process.py`: authorize only `tmp_path: Path` correction and explicit non-None narrowing before the two `await_args.kwargs` accesses, **or explicitly accept retained debt**. File was not changed here.
3. Separately authorize remediation or governing retained-debt disposition for global Black's five paths: `config/timeout_resolver.py`, `tests/agents/providers/test_openai_codex.py`, `tests/agents/slo_agent/orchestrator/test_spawn_tool.py`, `tests/cli/test_release_automation.py`, `tests/cli/test_install.py`.
4. Separately authorize remediation or governing retained-debt disposition for global mypy **274 diagnostics / 46 files** (specific list in `takeover-call2-static-files.txt`). Historical counts, not rerun or green. No approval inferred.

Existing generated exclusion provenance remains unchanged; no new exclusion or source-manifest green claim. New actual source test is `tests/integration/test_openrouter_final_compositions.py`.

## Safety and reading boundaries

Tests reuse the existing resolved-temp audit fixture (`contained_writes`): write/rename/chmod/remove targets must resolve inside their own temp root; subprocess/system/socket-connect are denied. Fixture audit becomes inert in finally. The existing isolated catalog fixture blocks default sync/async HTTP transports and redirects credential/catalog/preferences persistence. Synthetic MockTransport only; no real credentials/provider, subprocess or tool execution in the new cases.

Repo instructions and supplied research context, immutable overview/dependency index/a.2–a.6, workflow/mandatory coding skills and relevant application/agent testing guidance were consulted. Historical implementation-log/current-status/remaining files were read selectively rather than fully; CLI module skill was only partially read. This is a disclosed process limitation, not a claim of complete prerequisite compliance. One oversized initial combined KB/skill read generated tool-managed `/tmp/slo-bash-g_g7iaq6.txt`; it was not edited/deleted. Subsequent reads were bounded. KB was read-only due to checkout-only restriction; its stale 67-failure current-status claim still needs an authorized external KB writer. No native/live-provider availability claim.
