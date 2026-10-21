# CI repair — integrated Code+Test gates

## Verdict and accounting

**Code+Test acceptance-ready, offline.** All required local gates pass after the final code/test edits. Independent final Review and Completion remain required; this is not their approval, an exact-SHA CI result, or live Herdr certification. Live acceptance remains explicitly user-deferred and compatibility unverified.

Recovery continuation **dispatch 5, failed-task retry 1/3**, using the explicitly selected available GPT model. Prior session `9b769697-876a-4ed7-971a-753f851dad55` failed with exit 1 / five-hour 429 quota, **not aborted**. All its edits and scope A/B/C edits were preserved. No subagents, commits, pushes, installs, real providers, terminal launches or user-process kills were performed. Turn/dispatch budgets remain user-unlimited. Historical accounting is unchanged: verified 184 dispatches through accepted turn 6; aborted merge continuation began turn 7 with two completed children, exact aggregate still unreconciled. No historical count is reset or invented.

Baseline HEAD: `4ab10b02727d433779233cd758e35875b09acd78`. Cwd for every command below: `/root/Code/slo-94-herdr-integration/slo`.

## Recovered evidence and scope

Read current coordination plan, all three repair receipts, independent early feedback, project/root research, KB Welcome/Slo README/gotchas, actual shared engineering/ownership/testing rules, Python conventions, coding/test loop and test-verification rules, debugging and Textual guidance, and the named Code-Test-Review workflow. This is its Code+Test fan-in only. No database or live-provider stack applies.

Preserved prior full run: `/tmp/ci-repair-full-1.log`, `/tmp/ci-repair-full-1.exit`: **30 failed, 10478 passed, 19 deselected, 827 warnings**, 1437.88 s, make exit failure. It was not erased or treated as acceptance. Original CI trace remains `/tmp/herdr-ci-4ab10b0.log` (pipeline 2970613678 / job 17338411077): 11 failed, 10490 passed, 1 skipped, 19 deselected. Exact CI command in `../.gitlab-ci.yml` is `poetry run pytest -q --junitxml=../report.xml`; CI supplies `SLO_DEFAULT_MODEL_NAME=gpt-5.4`, synthetic Anthropic auth, COLUMNS=120/LINES=40. Existing local tests.env supplies `gpt-6.1-sol` and no such width/auth guarantees. Neither operator settings nor CI configuration were edited.

### Closure map

| Failure family | Cause / correction | Evidence |
|---|---|---|
| Seven original headless child-control failures; ER-04 | Incomplete `_DispatchingSession` reporting protocol. Retained A's explicit None activation and typed safe/drained outcomes plus normal/cancel await assertions; no runner relaxation. | Full gate passes; focused A receipt retained. |
| Three original observation lifecycle failures; ER-01/02 | Duplicate mount binding; service reference dropped before canonical close; unbound close resetting panel; rollback orphaning published owner. Retained B's owner-preserving teardown, guarded re-entry and captured rollback, exact existing assertions and additive regressions. | Full gate passes; B receipt and early review preserved. |
| Original 20-child viewport failure; ER-03 | Deferred content and delayed scrollbar availability made an apparent restore drop x. Retained C's measurable-content/range guards and scrollbar watcher; narrow content still restores reachable y; navigation invalidates pending intent. | Full gate passes including all six journey variants and convergence regressions. |
| Reported three ordering-dependent progress failures | No progress test or product change was made by this recovery. Same combined modules pass under both the initially inherited Poetry base interpreter and the explicitly selected approved interpreter. Earlier report supplies no concrete failing nodes/trace from which to establish a causal repair. | 150 passed twice; approved-interpreter full suite also passes. **Not described as a proved causal fix.** |
| Ten of prior local full run's 30 failures | Preserved prior child's scoped default-model pins and synthetic selection-credential stubs in five test modules. Default-model/capacity and auth assumptions differed from tests.env. | Initial recovery focused run: 214 passed / 20 failed; those ten are closed. |
| Local RPM preflight assertion | 30 requests do not saturate every model's RPM policy. The scenario now explicitly uses the existing gpt-5.4 single-model helper (30 RPM), not the operator default. | Prior full RED plus focused RED; final focused green. |
| Invalid-default resume notice | Test asserted gpt-5.4 fallback without selecting that default. Pin the dynamically resolved `DEFAULT_MODEL_NAME` inside this test. | Prior/focused RED → green, exact notice assertions retained. |
| Picker first-window assertion | Active model is promoted into the first window. Test asserted gpt-5.4 was there while ambient active model was gpt-6.1-sol. Pin this input inside this test. | Prior/focused RED → green; all bounded-window assertions retained. |
| 17 restore CLI safe-message assertions | Rich wraps the 81-character message at host default width; raw contiguous substring no longer exists. Independent width-only run at CI's 120 columns passes all 33 cases. Add module-scoped autouse monkeypatch of COLUMNS=120, undone after each case; preserve exact privacy/message/no-build assertions. | Focused RED; width-only 33 passed; final local/CI-model focused green. |
| Full mypy failure | `test_subagent_event_routing.py` annotated a typed outcome as str and compared it to `"ignored"` (vacuous). Use `HandleAdvanceOutcomeDAO`, assert exact workflow ID and launch effect. | Initial lint: 1 error / 852 files. Correction initially used nonexistent `kind`, immediately failed focused test; fixed to actual `effect` field. Module 35 passed; final full lint green. |

No assertions weakened, skips added, exclusions added, sleeps added, or timeout increases. The only new recovery edits are narrowly scoped test-fixture inputs and the typed outcome assertion. Existing production A/B/C changes remain intact. Formatting preserved the prior child's partial work.

## Exact environment and commands

Approved command prefix, scoped only to each tool shell:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
set -a; source environments/tests.env; set +a
export SLO_HERDR_DISABLED=1 SLO_AUTO_VISUALIZE=0 PYTHONPATH="$PWD"
```

Verified `poetry run python` then reports `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7, matching sys.prefix. Merely `pyenv which python` was insufficient: the initial inherited Poetry invocation selected `/root/.pyenv/versions/3.11.7/bin/python`. Its 150-pass result is supplemental only; all acceptance gates use the explicit prefix above. No interpreter installation or environment-file edit occurred.

Let `TARGETS` denote the exact nine-module argument list (shell expansion only, no collection exclusions):

```bash
TARGETS='tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_compaction_advisory.py tests/agents/slo_agent/test_session_usage.py tests/agents/test_ai_model_config.py tests/tui/test_context_window_commands.py tests/agents/slo_agent/test_session_rate_limits.py tests/cli/test_herdr_restore.py tests/cli/test_resume_route_precedence.py tests/tui/test_slash_suggestions_app.py'
```

All log paths in the following table are under `/tmp/`, prefixed `ci-repair-recovery-`:

| Command after prefix | Result / exit | Log suffix |
|---|---|---|
| `poetry run pytest -q tests/tui/test_visualizer_launcher.py tests/tui/test_headless_workflow_visualizer.py tests/tui/workflows/test_session_progress_screen.py` | 150 passed, 2 warnings / 0 | `order-harness.log` |
| `poetry run pytest -q $TARGETS` before recovery edits | 20 failed, 214 passed, 13 warnings / 1 | `targets-red.log` |
| `COLUMNS=120 poetry run pytest -q tests/cli/test_herdr_restore.py` before width fixture | 33 passed, 2 warnings / 0 | `width-proof.log` |
| `poetry run pytest -q $TARGETS` after recovery edits | 234 passed, 13 warnings / 0 | `targets-green.log` |
| `SLO_DEFAULT_MODEL_NAME=gpt-5.4 poetry run pytest -q $TARGETS` | 234 passed, 13 warnings / 0 | `ci-model.log` |
| `poetry run pytest -q tests/tui/test_subagent_event_routing.py` | 35 passed, 2 warnings / 0 | `routing-green.log` |
| `PYTEST_ADDOPTS='--junitxml=/tmp/ci-repair-recovery-full.xml' make test` | **10508 passed, 19 deselected, 826 warnings**, 1474.03 s / **0** | `full.log`, `full.xml`, `full.exit`, `full-command.txt` |
| `make smoke` | **296 passed**, 2 warnings / **0** | `smoke.log`, `smoke.exit` |
| `make lint` | **852 source files, no issues** / **0** | `lint-final.log`, `lint-final.exit` |
| `git diff --name-only --relative -- '*.py' > /tmp/ci-repair-recovery-python-files.txt; xargs poetry run black --check < /tmp/ci-repair-recovery-python-files.txt` | **17 files unchanged** / **0** | `black.log`, `black.exit`, `python-files.txt` |
| `git diff --check` | no output / **0** | `diffcheck.log`, `diffcheck.exit` |
| `dpkg -V coreutils` | no output / **0** | `coreutils.log`, `coreutils.exit` |

Exactly **one full suite** was run in this recovery, after all production/test edits and formatting. The previous failed child's full run is historical. `make test` sources the existing tests.env again, then forces Herdr disabled; AUTO_VISUALIZE=0 remains inherited. The 19 deselections are the existing non-E2E marker contract, not new exclusions; JUnit has no failed or skipped executed tests. No full CI-default-model suite is claimed: the CI-model proof is the nine-module affected partition.

The full log retains 826 warnings, principally dependency deprecations and some existing unawaited AsyncMock coroutine warnings; passing gates are **not a warning-free claim**. No warning filter or exception observer was disabled.

## Freeze, review and handoff

Before the full run, saved the complete tracked diff to `/tmp/ci-repair-recovery-prefull.patch`. After smoke/lint/Black/system-integrity gates, `git diff --binary | cmp /tmp/ci-repair-recovery-prefull.patch -` exited 0: no code/test edits changed during or after full verification. Subsequent edits are this receipt, coordination/status and durable learning documentation only. Reviewed all 17 changed Python files across the recovery diff, including original A/B/C ownership/viewport boundaries and all prior child edits. This self-review does not replace independent review.

There is no remaining failing local gate or outstanding repair required by this fan-in result. Next: independent final Review of the combined diff and ER-01–04 closure (including the limited earlier ordering-failure evidence), then independent Completion. Exact-SHA CI requires a separately authorized commit/push; none occurred. Live Herdr remains deferred. `/tmp` artifacts are local evidence, not durable CI artifacts; preserve them for the independent reviewers.
