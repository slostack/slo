# T5 continuation 74 — INCOMPLETE rollback/timer family

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 74, retries 0. User turn/dispatch budgets unlimited. No agents,
commits, pushes, PRs, resets, clean, stash, canonical/global/live or other-worktree
edits. This is not a budget stop or an all-T5 readiness claim.

## Implemented and verified

Initialization now captures session AND owner before preparation and carries them
through failed setup and late acquire/inbox cleanup. Release captures its optional
fallback owner before awaiting the store. Rollback clears workflow references only
when session and owner still match. Duplicate initialization does not overwrite
existing timer handles. Existing failed-stop retention remains unchanged.

| Branch | Evidence / disposition |
|---|---|
| Owner changes during inbox setup, original record remains | Mounted actual temp inbox/store: RED orphan lease; GREEN removed |
| Owner changes and another owner's record replaces original | Mounted actual temp store: RED deleted foreign record; GREEN preserved |
| Duplicate initialization | Mounted RED replaced timer identities; GREEN same handles, delivery open |
| Lease timer / inbox timer / both stop failures × release success / false / error | Nine mounted cases, throwing notice sink; exact both-stop then release order, exact failed handles retained, later cleanup succeeds; existing code already correct, no RED claimed |
| Repeated public unmount cancellation during actual off-loop acquire | Real `_acquire_sync` thread barrier after real write; retained mount task identical, public waiter remains pending, eventual cancellation only after joined cleanup, no lease remains; existing ownership already correct |
| Returned acquisition identity mismatch | Previous 73 regressions retained and rerun; not newly implemented |
| Inbox / timer registration failure and closing cutoffs | Previous 72 regressions retained and rerun |
| Capture store/DAO and app timer/service references across successor changes | Still incomplete: store and timer slots are not fully capture-owned; owner-only guard does not prove successor matrix |
| Reconcile/acquire/inbox successor matrix and rollback-release barrier | Pending |
| Repeated cancellation during actual rollback release | Pending (acquire proof is not release proof) |
| Missing-store helper | Dedicated test pending |
| Canonical shared runtime phases / activation | Pending; no activation edits |

Known remaining risk: preparation checks session identity/closing but not owner
identity at every continuation. Rollback still stops current app timer slots; it
must not stop a successor's handles. Release helpers outside initialization still
use entry-time default owner capture. The replacement outer fallback still captures
current session at its catch. These are not closed by the narrow regressions above.

## Exact execution receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. All prefixes below are in this
directory with `.log` and `.exit`. Every pytest command begins:

`PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`

The helper adds 62 DAO/projection foundation tests, uses the approved Python 3.11.7
fallback and disabled Herdr/test environment. No new environment was created.

- `t5-74-red1`: `tests/tui/test_herdr_init_ownership.py`; exit 1,
  **2 failed, 64 passed**. Actual orphan/deleted-foreign-record assertions.
- `t5-74-green1`: ownership, rollback, initialization, app_shutdown,
  replacement, session_lifecycle, test_app and authentication (paths below);
  exit 0, **334 passed, 1 deselected**, 209.14s.
- `t5-74-timers`: `tests/tui/test_herdr_init_rollback.py`; exit 0,
  **76 passed**, 3.74s. Existing correct behavior, not test-first repair.
- `t5-74-cancel`: `tests/tui/test_herdr_init_ownership.py`; exit 0,
  **67 passed**, 2.14s. Existing retained-task behavior.
- `t5-74-red2`: same ownership file; exit 1, **1 failed, 67 passed**;
  duplicate initialization changes timer identity.
- `t5-74-green2`: same surrounding partition as green1; exit 0,
  **345 passed, 1 deselected**, 218.65s.
- `t5-74-final-focus`: ownership + rollback files after formatting; exit 0,
  **82 passed**, 5.45s.

Exact surrounding suffix:

```text
tests/tui/test_herdr_init_ownership.py tests/tui/test_herdr_init_rollback.py tests/tui/test_herdr_initialization.py tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_replacement.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_app.py tests/tui/authentication
```

Static receipts:
- `t5-74-black` and `t5-74-black-check`: `PYENV_VERSION=slo-harness poetry run black [--check] src/tui/app.py tests/tui/test_herdr_init_ownership.py tests/tui/test_herdr_init_rollback.py`; exit 0.
- `t5-74-lint`: `PYENV_VERSION=slo-harness make lint`; exit 2,
  **299 errors in 63 files (768 checked)**, unchanged reported baseline, UNWAIVED.
  No diagnostics for app.py or either changed test. No ignores added.
- `t5-74-diff`: `git diff --check`; exit 0, silent.
- `t5-74-coreutils`: `dpkg -V coreutils`; exit 0, silent.

No full make test: finite family remains open. No independent review/activation
or complete acceptance claim. Existing partial work preserved.

## Read closure limitation

Read continuation73, actual affected app/store/tests, root RESEARCH, frozen routing
and scope plan, KB Welcome/gotchas, shared routing/ownership/testing/coding rules,
Python conventions/declarative/Faux/style, workflow SKILL, and canonical C7.13–7.14
through the matrix. Supplied project instructions/docs RESEARCH were consulted.
Some combined reads truncated; Textual full read, actual project-file rereads,
C7.9–7.12, exact full T5 attachments and accepted reviews remain incomplete fresh
read closure. This receipt does not recycle prior read claims as fresh ingestion.
No external KB writes under current restriction.
