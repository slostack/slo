# T5 continuation 72 — INCOMPLETE transactional initialization family

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 72, retries 0; effective turn/dispatch limits unlimited. No agents,
commits, pushes, PRs, resets, cleans, stashes, canonical-spec, global/live or
other-worktree changes. Prior work preserved.

## Recovery and bounded implementation

Provider API interruption occurred after the new test file was written and before
its first execution. Recovery used that saved file; no reset or fabricated receipt.

Two production increments (each below approximately 50 added production lines):

1. Mounted inbox/timer registration exceptions now run a shared rollback which
   quiesces delivery, disables further initialization, attempts timer stop and
   captured-session release, and clears workflow service/renderer in finally.
   Replacement's outer failure path delegates to that rollback rather than
   duplicating it. Its old unconditional successful-return reopening was removed.
2. Timer publication checks captured lifetime before registration and after each
   synchronous registration. Cutoff triggers the same rollback, never reopening.

New `tests/tui/test_herdr_init_rollback.py` mounts actual SloTUI with temporary
history/inbox/lease storage and patches the actual factory to Faux. Cases cover
inbox failure after real creation, first/second timer failure, synchronous closing
at first/second registration. No real provider/Herdr/windows; default suite guards
remain. No TCSS or ordinary queue policy changes.

## Finite branch map

| Branch | Evidence / remaining work |
|---|---|
| Inbox creation fails after acquisition | Mounted regression passing |
| First/second timer registration throws | Mounted regressions passing |
| Closing injected at timer1/timer2 registration | Mounted regressions passing |
| Replacement outer initializer failure | Existing regression passing; initial surrounding failure exposed missing quiescence and was fixed |
| Retained mount acquire barrier | Existing continuation70 regression passing |
| Captured lease ID/owner validation and successor preservation | NOT implemented/proved in this continuation |
| Reconcile/acquire/inbox cutoff independent matrix | NOT complete |
| Failed timer.stop retains handles and later attempt | Existing helper preserved; new mounted matrix pending |
| Repeated cancellation joining real off-loop initializer work | Pending |
| Throwing notices and every rollback failure combination | Pending |
| Shared mount/replacement canonical runtime phase order | Pending; only delivery rollback is shared |
| Enabled reporting activation after current initialization | Explicitly pending next activation work; no readiness claim |
| Duplicate timer/reinitialization prevention | Pending complete proof |

## Commands, logs, exits

CWD `/root/Code/slo-94-herdr-integration/slo`. Every pytest command used
`PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`
(the approved fallback; adds 62 foundation tests). Each prefix below has `.log`
and `.exit` under this directory.

- `t5-72-red1`: `tests/tui/test_herdr_init_rollback.py`: exit 1,
  **3 failed, 62 passed** (inbox/timer exceptions escaped mount).
- `t5-72-green1`: new rollback file, initialization, app_shutdown, replacement,
  session_lifecycle, test_app.py, authentication: exit 1, **1 failed, 327 passed,
  1 deselected**. Existing replacement rollback expected quiescence but observed
  False. No assertion weakened.
- `t5-72-green1b`: identical arguments after shared rollback correction: exit 0,
  **328 passed, 1 deselected**, 193.08s.
- `t5-72-red2`: rollback file: exit 1, **2 failed, 65 passed** (timer cutoffs).
- `t5-72-green2`: identical surrounding arguments to green1b: exit 0,
  **330 passed, 1 deselected**, 192.25s.
- `t5-72-final-focus`: rollback + initialization after formatting: exit 0,
  **68 passed**, 2.22s.
- `t5-72-black`: scoped format app.py and new test: exit 0.
- `t5-72-black-check`: same files, `black --check`: exit 0.
- `t5-72-diff`: `git diff --check`: exit 0, silent.
- `t5-72-coreutils`: `dpkg -V coreutils`: exit 0, zero bytes.

Surrounding exact arguments:
`tests/tui/test_herdr_init_rollback.py tests/tui/test_herdr_initialization.py tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_replacement.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_app.py tests/tui/authentication`.

No full make run: family not closed. Prior 299 errors/63 files static baseline
remains unwaived; no new ignores. No new lint comparison claimed.

## Read closure and limits

Read supplied project instructions/research, root RESEARCH entry, routing,
scope-plan opening, continuation70/71, actual initialization/replacement/lease
code, helper and tests; routing/ownership/testing/coding-rules/cadence/Python
root/style/Faux/Textual guidance; KB Welcome and relevant gotchas. Read exact
canonical T5 samples 2401–3720 and C's actual initializer correction. The mistaken
`C94...` path was resolved to actual `94.b.2...` without editing canonical files.
Full remaining requested skill, scope-plan, KB index and B/D/accepted-review
read closure is NOT claimed. No external KB edits under user's scope restriction.

Verdict: **INCOMPLETE initialization family**. These two bounded units are green,
not full mount transaction acceptance, activation acceptance or T5 completion.
