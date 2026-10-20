# T6 matrix rest 137 — INCOMPLETE

## Scope and accounting

Unfinished turn 1, started 1, completed 0, historical partial 1, dispatch 137,
retries 0; user unlimited turn/dispatch budget retained. No agents dispatched.
Only test code changed: `tests/integration/test_herdr_lifetime_matrix.py`.
No source, full_flow, harness, shared status, specification, other-worktree,
package, live Herdr, commit or external-system changes.

## Implemented evidence

32 canonical matrix IDs now execute: healthy/raising × queued_viewer,
queued_report, admitted_viewer, admitted_report × runtime_disable,
session_close, new, unmount. This adds 24 cases to the previous eight, not 56.
Verbose final receipt records every executed ID.

Real mounted config-backed session, Faux factory, restore publication,
reporter/sequence store, shared viewer transport and registered temp fake CLI
are retained. Queued phases hold the actual transport lock and observe a
waiter plus reserved/nonadmitted ticket for reports. Admitted phases hold
`_collect_result` after tracked process creation and await the actual fake CLI
capture before triggering the stop. Report case is an admitted metadata command:
blocked settlement follows metadata, rather than preceding it. Exactly one
admitted effect is permitted; queued cases permit none. No later ordinary report
or split is permitted. Reporter admitted ticket clears after terminal accounting.

Runtime disable uses reservation failure after activation. Other stops invoke
session close, actual new-session replacement and unmount. Diagnostics patch the
reporter's actual logger warning sink (healthy wrapper or raising side effect),
with call count asserted outside production catches. Close paths inject remote
withdrawal failure so this sink is necessarily exercised. They assert uncertain
remote outcome WITH drained local resources, sealed/drained transport, released
lease, no retired local owner and suppressed new integration. Runtime disable
retains the still-owned lease until normal teardown; it is not falsely treated
as completed shutdown. Save/reservation slots and viewer registry are checked.

This is **not yet strong complete all-owner acceptance**: persistent local
retention and the remaining phase families still need their matrix assertions.
G1 same-capture/newest-usage and G2 shared-lock viewer/A/B composed tests remain
separate obligations; they were not substituted or freshly verified here.
Unified journey remains a separate next family, untouched.

## Actual gates and failures

Receipts: `t6-matrix-rest-137-receipts/`.
Interpreter `/root/.pyenv/versions/slo-harness/bin/python` (3.11.7).
Explicit fallback environment: SLO_ENV=test, SLO_PROJECT_ROOT_DIR and
SLO_APP_ROOT_DIR=$PWD, SLO_APP_NAME=slo, SLO_LOG_FORMAT=text,
SLO_DEFAULT_MODEL=gpt-5.4, SLO_AUTO_VISUALIZE=0, SLO_HERDR_DISABLED=1,
synthetic SLO_ANTHROPIC_API_KEY, COLUMNS=120, LINES=40, PYTHONPATH=$PWD.
Root guards and native_factory supply isolated temporary state and synthetic
OpenAI credentials; no real providers/windows/Herdr.

- `queued.log`: first four viewer cases passed; next case hung until bash's
  1800-second timeout. Invalid test attention literal raised before its cleanup
  try while the test held the transport lock. Corrected literal to canonical
  `Authentication required` and moved phase setup inside try/finally. No pytest
  terminal exit was produced; this is not a completed gate or production RED.
- `queued-corrected.log`: 22 passed (16 matrix + 6 platform surrounds), exit 0.
- `admitted.log`: 14 failed, 24 passed. Test incorrectly equated spawn with
  captured effect; cancellation could reap before fake CLI capture. Also expected
  lifecycle before metadata on blocked settlement. Corrected actual-effect
  barrier and metadata expectation, without changing production.
- `admitted-corrected.log`: 38 passed, exit 0.
- Final post-Black `final.log`: **38 passed, 2 warnings in 43.10s**, exit 0.
  Command: `python -m pytest -m 'not e2e'
  tests/integration/test_herdr_lifetime_matrix.py
  tests/tui/test_herdr_platform_commit.py -vv`.
- Black check: one file unchanged. Scoped mypy `--follow-imports=silent`:
  success, one source file; `mypy.log`/`mypy.exit`.
- Scoped git diff --check exits 0, but owned test is untracked, so this is not
  tracked-diff coverage. Reviewed the edited test directly.
- `dpkg -V coreutils`: silent before/after; final empty `coreutils.log`, exit 0.
- No full make, full suite, integration-directory collection or two-process test.
  Global static baseline 281/58 remains user-reported and unwaived, not rerun.

## Exact remaining IDs

For `test_lifetime_cutoff_matrix`, all following IDs are unimplemented/unexecuted:

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
healthy-queued_capture-runtime_disable
healthy-queued_capture-session_close
healthy-queued_capture-new
healthy-queued_capture-unmount
raising-queued_capture-runtime_disable
raising-queued_capture-session_close
raising-queued_capture-new
raising-queued_capture-unmount
healthy-running_save-runtime_disable
healthy-running_save-session_close
healthy-running_save-new
healthy-running_save-unmount
raising-running_save-runtime_disable
raising-running_save-session_close
raising-running_save-new
raising-running_save-unmount
```

No skip/xfail was introduced. No production RED established. No arbitrary
per-call eight-case cap is asserted. This handoff is incomplete, not READY or
independent acceptance; the 32 passing cases must not be called full-64 proof.
