# T5 activation handoff 87 — INCOMPLETE reconciliation

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 87, retries 0. Effective turns and dispatches unlimited. No agents launched. No commit, push, reset, clean, stash, canonical specification, global, live or other-worktree edits.

## Auth defect repaired

The actual `_push_auth_modal` registered bare `_on_auth_dismissed`, which looked up the current session at dismissal. Both successful and cancelled callbacks captured before public `/new` refreshed authentication for the replacement. `tests/tui/test_herdr_auth_capture.py` first reproduced this: **2 failed, 64 passed**, exit 1 (wrapper includes 62 DAO/projection cases).

`src/tui/app.py` now captures the session and newly allocated Authentication-required token at screen push. Its synchronous callback rejects closing/displaced owners before credential checks, attention clearing, projection refresh, preparation or model changes. Matching-token clear delegates to the existing session owner. Cancel without credentials retains attention; cancel with credentials clears the matching request. Successful auth cannot clear newer attention. Existing `_prepare_mounted_session(session=...)` already captures the asynchronous preparation owner and checks identity/closing at continuation; no new asynchronous callback or session/reporter owner was introduced.

Eight new mounted cases exercise actual registered callbacks: replacement/unmount × success/cancel, plus success/cancel-missing/cancel-present/newer-token. They use the actual factory Faux boundary and temporary session infrastructure; no real provider, Herdr executable or terminal is enabled by these tests.

## Verification

CWD `/root/Code/slo-94-herdr-integration/slo`; approved `PYENV_VERSION=slo-harness`, Python 3.11.7; no venv created. Targeted tests use `bash docs/implementation/94-herdr/t1-dao-check.sh`. Existing fake-only and terminal guards remain unchanged.

Receipts are sibling `t5-87-*.log` / `.exit`:

| Prefix | Command scope | Result |
|---|---|---|
| auth-red | new callback tests | 2 failed, 64 passed; exit 1 |
| auth-green | callback, notices, OpenRouter startup, authentication | 134 passed, 1 deselected; exit 0 |
| surrounding | callback, session lifetime, all `tests/tui/test_herdr*.py`, test_app, OpenRouter startup | 490 passed; exit 0 |
| full | `make test` | 7961 passed, 19 deselected, 570 warnings; exit 0 |
| smoke | `make smoke` | 288 passed; exit 0 |
| lint | `make lint` | 307 errors/64 files; exit 2 |
| static-repair-tests | composed activation and callback tests | 79 passed; exit 0 |
| lint-final | `make lint` | 298 errors/63 files; exit 2 |
| black | check app.py, new callback tests, composed activation tests | exit 0 |
| diff | `git diff --check` | silent exit 0 |
| coreutils | `dpkg -V coreutils` | silent exit 0 |

Full lint identified nine existing activation-composed test typing errors absent from the frozen baseline. Corrected them without ignores: explicit non-None assertions on real leases/tasks/visualizer and an AbstractContextManager annotation for the two patch variants. These strengthen assertions; no runtime production change. The 79-test receipt is after this repair. **The full suite receipt precedes these assertion/type-only edits**, so it is not a final unchanged-snapshot gate.

` t5-87-lint-baseline-final.diff` (filename without leading space) compares normalized file/message/code rows against baseline-lint.log. No added diagnostic rows remain; three baseline rows are absent (one duplicate yaml stub diagnostic and two CLI overrides). Mypy summary counts differ from diagnostic row counts; do not reinterpret the original **299/63 unwaived baseline** as green. Fresh final summary is 298/63, still failing and unwaived.

## Finite closed / next-family partition

- **Closed in this continuation:** captured-session auth push/dismissal, token matching, post-public-replacement and post-public-unmount refusal. Existing direct handler behavior retained; no asynchronous auth continuation added.
- **Retained green evidence, not independently re-audited here:** activation-fault86 remote failure/spawn contrasts and stale restore; cutoff86 mount/preparation boundaries; INIT82; session-lifetime59; app-shutdown71; T2/T4 remote accounting/capability tests. Full suite executed these current tests, but execution alone does not establish the requested clause-by-clause reconciliation.
- **Still required before activation technical READY:** finish the bounded B/C affected read-tail and accepted-review/task-sample audit; identify exact existing persistent-local-retention, capability/diagnostic-cutoff and stale RELEASE composition assertions. Add a real stale release composition only if that finite audit finds it absent. No new exhaustive Cartesian matrix is prescribed.
- **Next T5 family, explicitly not an activation technical blocker:** F4 viewer callback registry/drain integration and D platform/viewer continuations. Inbox final admission/ack integration follows activation. Neither has been started here.
- **Final gates:** rerun full test after the composed-test typing repairs, preserve static baseline comparison, and review exact final diff.

## Read boundary

Read both 86 handoffs, frozen routing/scope plan (combined output truncated at its last safety lines), root RESEARCH, KB Welcome/slo README/gotchas; supplied AGENTS/CLAUDE/docs RESEARCH were available in context. Read actual auth and preparation methods and attention owner, composed tests, notices tests, Makefile/wrapper; canonical C 605–794 plus targeted auth/attention/cutoff excerpts. Loaded engineering routing/ownership/testing, coding rules/cadence, Python root/declarative, shared declarative, complete Textual and Faux skills; workflow SKILL through line 200. This is **not** the requested full actual-file/read-tail closure or all-previous-test audit. No false complete-ingestion claim.

Verdict: **INCOMPLETE activation reconciliation**, with auth defect fixed and tested. No whole-T5, independent-review, live compatibility or activation READY claim. Viewer work is partitioned, not used as the reason to withhold activation READY.
