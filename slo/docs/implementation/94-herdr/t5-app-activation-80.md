# T5 continuation 80 — INCOMPLETE, ordering regression captured

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 80 (user supplied), retries 0. Unlimited turn/dispatch budgets.
No agents, commits, pushes, resets, cleanup, external/spec/global edits.

## Separate verdicts

- **INITREADY: INCOMPLETE audit.** Continuation 79 ownership evidence is retained,
  not invalidated or presented as a requirement to complete all T5. The missing
  absent-history/inert-construction and ready/pending exact test map is not closed.
- **Activation: INCOMPLETE.** Added one orchestration regression test, confirmed
  RED. No production implementation changed in this continuation. The test is
  deliberately retained failing, not skipped. This is not delivery or readiness.
- Inbox/viewers and T6 remain future families.

## Exact finding

`src/tui/app.py:2518-2540`, `_finish_replacement_runtime`, currently executes
`delivery -> title -> context -> usage`; it never calls reporting activation.
Canonical `94.b.2-session-publication-and-native-restore.md:925-948` requires
`delivery -> start_external_reporting(interactive=True) -> context -> title -> usage`
with captured-session/cutoff checks and pending preparation afterward.
The new `tests/tui/test_herdr_activation.py::test_shared_runtime_activates_before_context_and_title`
records that shared seam and fails at index 1 (`title` versus `reporting`).
It is orchestration evidence only: no mounted real-reporter/native-capture claim.

## Actual reads

Read continuation 79 in full; accepted independent-review-turn4 tail from 181;
full workflow code-test-review, Python named-arguments/type-hints and docstrings;
complete tests test_herdr_initialization, test_herdr_app_shutdown,
test_herdr_replacement and test_herdr_session_lifecycle. Read app mount/preparation
and shared runtime ranges, and searched canonical affected activation citations.
Did not complete all requested canonical C7.9–7.14/sample reads or the finite
exact branch map. Prior routing history was not restarted. No claim prerequisite
read closure was achieved. An attempted parallel read call had missing parameters;
subsequent individual reads succeeded.

## Commands and evidence

All paths below are relative to docs/implementation/94-herdr.

- `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/test_herdr_activation.py`
  -> `t5-80-order-red.log`, `.exit`: **1 failed, 62 passed, exit 1**.
- `git diff --check` -> `t5-80-diff.log`, `.exit`: silent, exit 0.
- `dpkg -V coreutils` -> `t5-80-coreutils.log`, `.exit`: silent, exit 0.

No GREEN, surrounding, Black, lint, smoke or full make test executed here.
Prior lint 299 errors/63 files remains historical and UNWAIVED, not a fresh check.
Continuation 79 selection visibility failure remains retained without a causal fix
claim; no selection code or assertions changed.

## Remaining finite activation work

1. Finish the exact INIT audit citations and affected canonical sample reads.
2. Implement the small shared runtime ordering/activation unit; run RED-to-GREEN
   and surrounding before another production increment.
3. Prove mounted registered-fake-Herdr/Faux activation and disabled zero-I/O parity,
   truthful original-session native eligibility, predecessor release-before-claim,
   sticky suppression across successors, pending/cancellation/throwing notices,
   and monotonic cutoff plus retained close/join ownership after every await.
4. Run focus and app queue/auth/replacement/shutdown surroundings, Black/diff/
   coreutils, fresh lint comparison and full gates if claiming family closure.

No session-service API gap has been established; no session-service edit made.
