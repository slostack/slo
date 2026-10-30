# T6 matrix 138 — INCOMPLETE (48/64 executed)

## Scope and accounting

Owned change: `tests/integration/test_herdr_lifetime_matrix.py` only, plus this receipt and `t6-matrix-complete-138-receipts/`. Existing 32 report/viewer cases preserved. No production, full_flow, harness, shared status, specs, other worktrees or global edits. No agents, full suite, integration-directory collection, two-process tests, provider calls, real Herdr/windows, commits or external actions.

User unlimited workflow budgets retained: unfinished turn 1, started 1, completed 0, historical partial 1, dispatch label 138, retries 0. This is not workflow completion or independent acceptance.

## Implemented increment

Added eight running_save and eight queued_capture canonical IDs (each four stops × healthy/raising diagnostics). Real mounted config-backed session, existing Faux factory, registered fake executable, real reporter/store/transport and actual session close/new/unmount retained. No fake lifecycle owner.

Running save pauses the actual store call in the reporter-owned filesystem thread, then delegates to real immutable save. Tests prove save task retained while blocked, close not done before release, completed write, exact load equality, unchanged previously saved bytes, no adoption/advertisement of the post-cutoff reference, cleared save/reservation slots, and drained closed transport for close/new/unmount. Runtime disable truthfully retains the integration until normal context teardown. A later attention fact is submitted after cutoff without renewing admission.

Queued capture means pending private policy, NOT queued user input. The actual reporter worker waits on the actual shared transport lock with an older report; a committed reasoning change places a distinct immutable capture in its pending slot. Stop occurs before save begins. Tests prove zero save calls/new files, zero later ordinary report effects, no admitted ticket, and drained close paths. Runtime disable can retain the pending pointer in memory, but its worker terminates without consuming it; no claim that the pointer is cleared.

Every new raising case calls the real warning sink (patched to raise), with call count checked outside production exception isolation. Close paths inject withdrawal refusal to require that diagnostic. No production RED established.

## Actual gates

Interpreter: `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7.
Explicit fallback: SLO_ENV=test; SLO_PROJECT_ROOT_DIR/SLO_APP_ROOT_DIR/PYTHONPATH=$PWD; SLO_APP_NAME=slo; SLO_LOG_FORMAT=text; SLO_DEFAULT_MODEL=gpt-5.4; SLO_AUTO_VISUALIZE=0; SLO_HERDR_DISABLED=1; synthetic SLO_ANTHROPIC_API_KEY; COLUMNS=120; LINES=40. Existing root guards/native_factory handle synthetic OpenAI and isolated temp capabilities.

- Initial `running-save.log`: 8 failed / 32 deselected, bounded barrier timeouts. Fixture already used high reasoning; requesting high did not change capture. Test corrected to select a different supported level and assert changed capture. Not a production failure or unbounded hang; no blind 1800-second retry.
- `save-isolation.log`: 1 passed / 39 deselected.
- `save-corrected.log`: 8 passed / 32 deselected, exit 0.
- `queued-capture.log`: 8 passed / 40 deselected, exit 0.
- Final post-format command: `python -m pytest tests/integration/test_herdr_lifetime_matrix.py tests/tui/test_herdr_platform_commit.py -vv -o faulthandler_timeout=40`.
- `final.log`: **54 passed, 2 warnings in 73.93s**, exit 0. Exactly **48 matrix IDs + 6 existing platform surrounds**, NOT 64 matrix IDs.
- Black check: 1 file unchanged. Scoped mypy `--follow-imports=silent`: success, 1 file. Initial two annotation errors corrected; final receipt green.
- Scoped git diff --check passed, but owned file is untracked, so not tracked-diff coverage; edited test inspected directly.
- `dpkg -V coreutils`: silent before and after; final empty coreutils.log, exit 0.
- Global static baseline 281 errors/58 files remains user-reported, unwaived and not rerun.

## Remaining exact canonical IDs

```text
healthy-precommit_platform-runtime_disable
healthy-precommit_platform-session_close
healthy-precommit_platform-new
healthy-precommit_platform-unmount
raising-precommit_platform-runtime_disable
raising-precommit_platform-session_close
raising-precommit_platform-new
raising-precommit_platform-unmount
healthy-committed_platform-runtime_disable
healthy-committed_platform-session_close
healthy-committed_platform-new
healthy-committed_platform-unmount
raising-committed_platform-runtime_disable
raising-committed_platform-session_close
raising-committed_platform-new
raising-committed_platform-unmount
```

Platform families were not implemented in this pass. Existing six real guarded platform continuation tests pass but do not replace the 16 canonical IDs, especially diagnostic and independent platform-path semantics. Canonical C says independently selected outside/disabled platform work follows app lifetime; reporter disable/session integration close must never be faked by converting an enabled Herdr destination to platform.

## G1/G2 and acceptance gaps

Distinct existing mappings (inspected, NOT freshly run):
- G1: `tests/agents/slo_agent/herdr/test_session_publication_compositions.py::test_real_session_save_barrier_latest_publication[usage_rename]` (reasoning variant tests supersession separately).
- G2: `tests/agents/slo_agent/herdr/test_reporter.py::test_viewer_lock_waiter_superseded_report_never_spawns` (generation × cutoff parameters).

New matrix assertions cover pending-capture refusal, immutable orphan/nonadoption and local save join; they do not replace G1 newest-usage or G2 viewer/A/B behavior. Their fresh execution and stronger full-owner/late-ack assertions remain open. No all-64 or complete all-owner proof claimed. Unified journey remains separate next work. Required skill/spec review was only partially completed during this pass; no blanket convention-compliance claim.
