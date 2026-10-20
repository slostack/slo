# Feature 94 Herdr — delivery record 184

Accounting: **turn6, global dispatch 184, delivery phase**. User explicitly
authorized commit/push/GitLab-MR update and CI monitoring. No merge, no force
push, no push to `main`, no history rewrite, no branch-protection or CI-policy
change was performed or attempted.

## Verdict: DELIVERED (pushed; MR updated in place; CI terminal and green for the exact pushed SHA)

## Commit / branch

- Branch: `feature-94-herdr-integration` (existing; normal push only).
- Delivery commit: **`687c1a7b2f25a30c82365ead49d2995b063349b9`**
  `fix(94): review-driven lifetime cutoffs, audit-sensitivity repair, and turn-6 evidence`
  — 399 files changed, 11431 insertions, 78 deletions.
- Prior published commits on the same branch (pushed by the concurrent
  workflow before this dispatch): `bc98b76` (DRAFT feature snapshot) and
  `c2f9e56` (publication-handoff correction).
- Push output: `c2f9e56..687c1a7 feature-94-herdr-integration -> feature-94-herdr-integration`.

## What the delivery commit contains

- `src/tui/app.py` — R178-1 post-summary scroll cutoff revalidation in
  `_hydrate_transcript_from_history`; R173-1 guards retained.
- `tests/tui/test_startup_notice_cutoff.py` — parametrized closing/displaced
  post-summary scroll rejection + open-path positive control.
- `tests/implementation_checks/test_conventions_audit_paths.py` — R178-2
  audit-sensitivity repair (single source-under-test seam, materialized-mutant
  separation, explicit-rejection oracles).
- Durable evidence: `turn6-code-test-176/177/179.md` (+receipts),
  `independent-review-wiring-178/180.md`, `independent-review-harness-static-181.md`,
  `independent-review-synthesis-182.md`, `completion-183.md` (+ receipt dirs).
- Secret scan of the staged payload before commit: **0 matches** for token /
  private-key / bcrypt-hash / bearer patterns.

## Pre-push verification on the exact committed tree (687c1a7)

Environment: `VIRTUAL_ENV=/root/.pyenv/versions/slo-harness`, its `bin` on
PATH, `PYENV_VERSION=slo-harness`, `PYTHONPATH=$PWD`, tracked fallback exports;
`make test-env` = `fallback`. No stash; the tree tested was the tree pushed.

| Gate | Result |
|---|---|
| `make smoke` | **288 passed**, 2 warnings, exit 0 |
| `make lint` (mypy, unmodified) | **816 source files clean**, exit 0 |
| Focused: `test_startup_notice_cutoff.py` + `test_conventions_audit_paths.py` | **22 passed**, exit 0 |
| `dpkg -V coreutils` after all runs | silent, exit 0 |

Author turn-6 gates (evidence committed with this delivery): full non-e2e
**8773 passed / 19 deselected**; smoke 288; lint 816 clean; chapter partitions
**B26 1531 / C31 1538 / D09 1748**.

## Merge request

- URL: **https://gitlab.com/core-27/slo/-/merge_requests/131**
- State: open **Draft**, source `feature-94-herdr-integration` → target `main`.
- This dispatch **updated the existing MR in place** (no duplicate MR):
  description now carries the feature summary, the review-driven static/lifetime
  fixes, the gate table, the independent-review evidence (core172 READY,
  wiring180 READY, harness-static181 READY, synthesis-182 READY,
  completion-183 COMPLETE 100% offline), and the explicit qualifications
  (live acceptance USER-DEFERRED, compatibility UNVERIFIED, security finding
  132 separate/open).

## CI for the exact pushed SHA 687c1a7b2f25a30c82365ead49d2995b063349b9

Both pipelines were created by the push and polled to a terminal state
(created ~19:00 UTC, terminal ~19:23 UTC, 2026-10-20):

| Pipeline | Ref / source | Status | Jobs | URL |
|---|---|---|---|---|
| 2967294077 | `feature-94-herdr-integration` (push) | **success** | pytest success (1341.6 s), secret_detection success (54.0 s) | https://gitlab.com/core-27/slo/-/pipelines/2967294077 |
| 2967294376 | `refs/merge-requests/131/head` (merge_request_event) | **success** | same two jobs | https://gitlab.com/core-27/slo/-/pipelines/2967294376 |

No job failed; no retry was needed; no credential, runner, or provider limit
was hit. Monitoring method: `glab api projects/core-27%2Fslo/pipelines?sha=687c1a7…`
and per-pipeline `jobs` polling at ~90–480 s intervals until both pipelines
reached the terminal `success` state.

## Blockers

None. DELIVERED stands for the offline delivery scope: branch pushed, MR !131
updated in place, CI green for the exact pushed SHA. Live Herdr acceptance
remains USER-DEFERRED; live compatibility UNVERIFIED; security finding 132 is
separate and open; this MR must not be merged without an explicit operator
decision (it remains Draft).
