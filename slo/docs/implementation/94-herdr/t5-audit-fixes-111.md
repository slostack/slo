# T5 audit fixes 111 — INCOMPLETE acceptance; three source corrections landed

2026-10-19. Author Code/Test continuation only. Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 111, retries 0. Effective turn/dispatch budgets unlimited. No agents launched. No independent review or acceptance claimed.

## Finding → correction → evidence

1. **F1: app viewer cleanup failure skipped later owners.** `src/tui/app.py` now contains ordinary viewer-helper failures at shutdown and replacement, outside the submission gate. Replacement permanently disables successor delivery and emits the existing best-effort fixed lifecycle notice before continuing irreversible close/adoption. The registry attempts every captured worker join/completion even when a completion helper throws, retains handles on failure, and raises the first ordinary failure after all attempts. Shutdown additionally joins any retained registry workers after the independent session/delivery drains; failed helper completion is not evidence of freed resources. Exception catches do not catch `CancelledError`; existing public retained-task join/result semantics remain unchanged.
   - `test_shutdown_attempts_each_owner[viewer]`: RED 1 failed / 4 passed; GREEN whole shutdown + registry 76 passed.
   - `test_viewer_cleanup_error_still_commits`: RED 1 failed; GREEN replacement/viewer/shutdown modules 98 passed. Real session reporter close task is terminal, real old lease removed, candidate selected/subscribed, successor delivery disabled. Notice throws alongside original fault.
   - `test_drain_attempts_all_workers_after_completion_fault`: RED 1 failed; GREEN four lifecycle modules 102 passed. Both completion attempts occur and retained handles survive.
   - `test_viewer_helper_fault_retains_shutdown_until_worker_terminal`: RED 1 failed; GREEN four lifecycle modules 103 passed. Real reporting and delivery cleanup progresses while retained viewer prevents public shutdown completion; caller cancellation surfaces after fixture worker ends.
   - Existing repeated cancellation / gate-owning viewer / actual platform-thread replacement tests remain passing in these modules.
2. **F2: scheduler removed non-prefix lookalikes.** `src/scheduling/runtime/subprocess_runner.py` now removes exactly case-insensitive `HERDR_`. Actual fresh/resume child tests explicitly remove `HERDR_OTHER` and lowercase `herdr_future`, preserve `HERDR`, `HERDRFOO`, `herdrFuture`, unrelated synthetic SLO/provider values, and assert parent environment equality. RED 2 failed; GREEN complete scheduling directory + helper defaults 124 passed.
3. **F3: reused-pane copy overstated certainty and lacked recovery.** `src/tui/workflows/renderer.py` remains the single formatter for both completion paths. Reuse says previously attempted, includes `if still present`, known pane, and manual `slo visualize --session <captured-parent> --follow` recovery. No focus/query/retry behavior added. Renderer guard still schedules once on reuse. Attached completion asserts parent rather than selected-session identity and absence of temp/private path. RED both reused cases fail; GREEN workflows/attached/composed/receive-path/real adapter tests 191 passed.

## Receipts and commands

Cwd: `/root/Code/slo-94-herdr-integration/slo`. Approved interpreter verified `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. All pytest commands used `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <tests>` (safe test fallback, auto-window off, Herdr disabled, existing independent fake capability and terminal guards). The helper adds DAO/projection tests unless `-k` filters them.

Each receipt stem below has `.log` and `.exit`:

| Stem | Result |
|---|---|
| `t5-111-f1-red` | exit 1, 1 failed / 4 passed / 68 deselected |
| `t5-111-f1a-green` | exit 0, 76 passed |
| `t5-111-f1b-red` | exit 1, 1 failed / 73 deselected |
| `t5-111-f1b-green` | exit 0, 98 passed |
| `t5-111-f1c-red` | exit 1, 1 failed / 65 deselected |
| `t5-111-f1c-green` | exit 0, 102 passed |
| `t5-111-f2-red` | exit 1, 2 failed / 70 deselected |
| `t5-111-f2-green` | exit 0, 124 passed |
| `t5-111-f3-red` | exit 1, 2 failed / 85 deselected |
| `t5-111-f3-green` | exit 0, 191 passed |
| `t5-111-f1d-red` | exit 1, 1 failed / 73 deselected |
| `t5-111-f1d-green` | exit 0, 103 passed |
| `t5-111-final-focused` | exit 0, 319 passed, 16 warnings, 28.58s |

Final focused arguments:

```text
tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_viewer_registry.py
tests/tui/test_herdr_viewer_replacement.py tests/tui/test_herdr_replacement.py
tests/tui/test_herdr_inbox_disposition.py tests/tui/test_herdr_inbox_cutoffs.py
tests/tui/test_herdr_attached.py tests/tui/test_herdr_attached_composed.py
tests/tui/workflows tests/tui/test_workflow_receive_path.py
tests/tui/test_visualizer_launcher.py tests/scheduling
```

Fresh `PYENV_VERSION=slo-harness make lint`: initial 298 errors included three new test annotation errors; corrected without ignores. Final `t5-111-lint-final.log/.exit`: **295 errors / 60 files, exit 2**, unwaived. `t5-111-lint-comparison.log` compares all error rows against 109, normalizing only line/column locations: 295/295, zero additions/removals. Not static green.

Black check: nine touched Python files unchanged, exit 0 (`t5-111-black`). `git diff --check`: silent exit 0 (`t5-111-diff`). `dpkg -V coreutils`: silent exit 0 after child-stubbing suites and final gate (`t5-111-coreutils`, `t5-111-coreutils-final`). Existing worktree changes preserved; no reset/clean/stash/commit/push/PR/global/live/spec/KB/other-worktree edits.

## Limits and remaining proof — do not promote to READY

- The broad command including `tests/tui/test_herdr_*.py`, app, session lifetime and headless modules exceeded the **tool invocation's 240-second timeout**. `t5-111-surrounding.log` contains progress through 71% but no terminal summary; no `.exit` was produced. It is not passing evidence. The smaller explicit final focused command above completed; it does not replace that broader requested gate. This is not a workflow budget or retry limit.
- Complete combined real-retired-child/T5 author audit closure and T6 remain future. No fresh full `make test` ran here; the user places it after combined T5 closure. Prior 109 full-suite evidence is historical only.
- Read audit 110, actual affected source/tests, root RESEARCH, routing, canonical C7.2/C7.9 cleanup excerpt and D6 manual reuse excerpt, KB Welcome/Slo README/gotchas, engineering routing/ownership/testing, Python root/style, coding rules/cadence/declarative, Textual/Faux, workflow definitions. Actual AGENTS/CLAUDE/docs RESEARCH were supplied in context; a combined disk read was truncated. This continuation does **not** claim fresh exhaustive canonical lifetime/T5 samples/accepted-review/build-rule read closure. That requested prerequisite is not fully satisfied by targeted citations or prior author's assertions.
- Additional strengthening still appropriate before READY: replacement helper failure with a genuinely unresolved retained viewer plus real enabled reporter/transport; current replacement fault test proves real null-reporter close and actual lease transfer, not enabled reporter process cleanup. The shutdown retention test supplies unresolved app-worker ownership separately. No claim of combined real-retired-child proof.

Canonical contracts remain read-only: `94.b.2-session-publication-and-native-restore.md` C7.2 (line 228 exact prefix), C7.9 (980–1060 independent cleanup/adoption), C7.11/C7.14 audit-required lifetime cases; `94.c.1-herdr-workflow-visualizer-and-acceptance.md` D6 (128–142 conditional reuse/manual command). The three fixes have concrete red/green proof, but the outstanding combined/read/broader gates prevent a complete requested acceptance claim.
