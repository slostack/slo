# Dispatch 13 — full unexcluded gates

**Verdict: REVISE. Step 1 NOT READY.** Full default suite completed, not timed out or replaced by chunks. 19 unresolved failures block DC09.A6 and whole-feature regression acceptance. Independent final review/completion remain later; early feedback is not substituted.

Turn1 started1/completed0/partial1; dispatch13/20; zero execution retries; max60turns. Requested Code+Test assignment gpt-6.1-sol/medium; no runtime model attestation is claimed. Later independent assignment remains gpt-6-astra/medium. No agents/workflows launched, no commit/push/PR/merge, packages/host/watchdog/harness changes, source/test edits, docs/SLO/README edits or original specification edits this dispatch.

## Authority and bounded plan

Read actual README maintainer/testing guidance, SLO.md, Makefile, pyproject, four requested current artifacts, and original numbered specifications' §8 A rows. Ancestor AGENTS/SLO discovery found no additional files. RESEARCH.md remains absent; existing routing's explicit no-recreation decision preserved. Consulted KB Welcome, slo README/gotchas/environment guidance and guardian ROLE/README for safe execution. Installed shared Code-Test-Review workflow and engineering routing/testing/ownership, generic coding/design/naming/testing/cadence and Python root guidance apply; no new implementation layer or recipe is introduced. Existing real SQLite/history/Pilot/provider-double evidence map is retained, not replaced by counts.

Plan executed: launch exact full Make gate with direct durable output/exit receipt; run full lint and cumulative changed src/tests Black check; inspect failures without weakening assertions; verify integrity; return finite repair list when failures span multiple boundaries. No baseline exclusion or waiver.

## Exact commands and receipts

Cwd `/root/Code/slo-message-queue/slo`, branch `message-queue`. Every Poetry/Make invocation selects existing interpreter per command using:

```sh
VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
```

`make test-env` returned `fallback`, exit0. Full test used **Makefile recipe unchanged**, including its exact synthetic exports: SLO_ENV=test, SLO_ROOT_DIR=$PWD, SLO_APP_DIR=$PWD, SLO_APP_NAME=slo, SLO_LOG_FORMAT=text, SLO_DEFAULT_MODEL_NAME=gpt-5.4, SLO_AUTO_VISUALIZE=0, SLO_HERDR_DISABLED=1, synthetic SLO_ANTHROPIC_API_KEY placeholder, COLUMNS=120, LINES=40; recipe sets PYTHONPATH=$PWD. No development environment sourced.

| Command (prefix above where applicable) | Result | logs/ artifact |
|---|---|---|
| `make test PYTEST_WORKERS=6` | **make exit2 / pytest exit1**, 12246 passed, 19 failed, 1256 warnings, 0 reported skips; 12265 selected items, six workers; 587.22s | dispatch13-full-test.log, dispatch13-full-test.exit |
| `make lint` | exit0; 980 source files clean | dispatch13-lint.log, dispatch13-lint.exit |
| `poetry run black --check "${paths[@]}"` | exit0; all 51 cumulative changed Python paths unchanged | dispatch13-black.log, dispatch13-black.exit, dispatch13-black-paths.txt |
| `git diff --check` | exit0, no output | dispatch13-integrity.log |
| `dpkg -V coreutils` | exit0, no output, after full command-stubbing suite | dispatch13-integrity.log |
| `make test-env` | exit0, fallback | dispatch13-integrity.log |
| `PYTHONPATH="$PWD" poetry run pytest --collect-only -q -m 'not e2e'` with exact fallback exports above | exit0; **12265/12286 collected, 21 deselected**, 2 collection warnings | dispatch13-collection.log |

The xdist run does not print a deselected count; separate same-source/environment collection confirms the 21 project-marker exclusions. It is collection metadata, not substitute execution or an overlapping pass total. No file exclusions, baseline exemptions or additional markers. Full run timestamps 2026-11-03T06:10:54Z–06:20:43Z. Ordinary background receipt owner PID1059959 completed; nothing killed, no infrastructure built. Direct redirection then immediate `$?` capture (no tee pipeline) preserves the command's status. Black paths are sorted union of `git diff --name-only --relative -- 'src/**/*.py' 'tests/**/*.py'` and `git ls-files --others --exclude-standard` with those pathspecs: includes untracked implementation/tests, never docs.

Warnings are retained in full log: pythonjsonlogger deprecation, LangChain pending deprecation, LangChain input/model-parameter warnings and unawaited AsyncMock coroutine warnings. No warning-free claim. Failure index: dispatch13-failure-index.txt. Full traceback and exact 19 node IDs remain in full-test log.

## Finite failure/repair list (no fixes attempted)

Failures span four boundaries; this is not a single small regression. Do not accept existing focused green totals as closure.

1. **D13-F1 — 13 managed-child reasoning/lifecycle cases.** `tests/agents/slo_agent/orchestrator/test_managed_launch_reasoning.py`, `run_recorded_child` lines321–355: wrapper `initialize` does not accept `messaging_enabled`; production TyperDispatch now passes it. All 13 fail at `assert len(runners) == 1` (zero). Source inspection identifies a constructor-signature mismatch, but captured CliRunner exception is hidden by that assertion, so this is a diagnosis candidate, not a demonstrated sole cause. Repair: capture/inspect actual Result exception, adapt wrapper to forward/assert the real production flag without deleting lifecycle/model/reasoning assertions, rerun entire file. Then inspect any newly exposed real messaging/orchestrator failures.
2. **D13-F2 — four real two-process restore cells.** `tests/integration/test_herdr_two_process_restore.py::test_native_restore_in_independent_processes[model_changed-single/model_changed-pool/refused-single/refused-pool]`. `herdr_restore_process_entry.py:248–250` waits for `_operator_attention` and times out for changed-model cells; refused cells call `session.invoke` after failed messaging startup and receive `MessageAdmissionError: offline` at session service913 rather than credential ValueError. This is a real changed default/preparation boundary, not permission to replace assertions with generic refusal. Repair: trace actual startup/preparation/error-presentation ownership; preserve explicit capability/credential refusal, no provider/no replay/history/config/paint assertions through default messaging entry. Add failing real-boundary evidence before production correction; rerun full two-process suite and affected preparation/default-matrix suites.
3. **D13-F3 — transcript removed-candidate navigation.** `tests/tui/test_chat_transcript_navigation.py:441`, `test_removed_reading_candidate_uses_clamped_numeric_fallback`: numeric clamp assertion passes but painted output includes `SECOND-099` forbidden by next assertion. No baseline established; do not call preexisting or waive. Isolate same test with exact Make environment; inspect viewport/terminal-size and removed-widget anchor semantics, preserve both numeric and painted assertions, determine deterministic regression versus timing/environment before fix. Rerun complete navigation suite and changed transcript boundaries.
4. **D13-F4 — registration atomicity AST assertion.** `tests/tui/test_herdr_prompt_registration.py:30` unpacks four method statements, now five because `_register_prompt_task` has required messaging invariant guard before shutdown guard. Repair assertion to explicitly verify the invariant guard AND exact existing closing-check→create/assign→return no-await/callback atomicity, not drop static or mounted cutoff checks. Rerun entire prompt-registration file plus default invariant/legacy cutoff suites.

After bounded repairs, rerun **full exact `make test PYTEST_WORKERS=6`** and all static/integrity gates. No selected rerun can replace this failed full gate. No baseline failure is dispositioned as accepted.

## Original requirement → current evidence

| Original acceptance | Current evidence / disposition |
|---|---|
| DC01.A1–A8 | Existing real injected/mounted/ephemeral/lease/legacy tests from dispatch4/12 included in full run; no failures in named feature files. Default preparation compatibility now unresolved by F2; do not infer universal startup closure. |
| DC02.A1–A12 | All mapped composer, prerequisites, adapter/protocol/static tests included and no named failures; original ID/draft/capacity/eager/literal assertions retained. |
| DC03.A1–A11 | Identity/observation/history feature files included, no named failures; broader transcript compatibility blocked by F3. |
| DC04.A1–A8 | Retirement/handoff/cancellation feature files included, no named failures; no lifecycle assertions changed. |
| DC05.A1–A9 | Retained recovery/store/slash feature files included, no named failures. |
| DC06.A1–A7 | Messaging controls/new/clear/abort files included, no named failures; broader registration cutoff static acceptance blocked by F4. |
| DC07.A1–A11 | Finite/headless/steer mapped feature files included, no named failures; prior complementary A4/A8 rationale in dispatch12 retained for later independent assessment. Managed CLI compatibility blocked by F1. |
| DC08.A1–A11 + §5.6 | Bridge/legacy admission/Inbox/displacement files included, no named failures; dispatch12 exact mounted same-gateway limitations retained. |
| DC09.A1–A5 | Default matrix/root/rollback tests included, no named failures; F1/F2 expose additional default root compatibility failures, so cutover not accepted. |
| DC09.A6 / final gates | **FAIL** full suite19 failures. Lint980/Black51/diff/coreutils PASS. No nondeferred item waived; no Step1READY. |

Detailed original row reconciliation remains dispatch12-cutover.md and dispatch5–11 source maps; this current evidence adds a full execution, not an independent adequacy review. Independent review and completion must still occur after verified READY. Existing early review remains valid within its original boundary.
