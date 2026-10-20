# T5 continuation 75 — INITOWNERSHIP INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 75 (user-supplied), retries 0. Unlimited turn/dispatch budgets;
no agents dispatched. No commit/push/PR/reset/clean/stash, canonical, global,
live or other-worktree edits. This is not an all-T5 readiness claim.

## Changes actually made

1. `_stop_delivery_timers` clears a successfully stopped slot only if the slot
   still holds that exact timer. Mounted real Textual timer regression replaces
   the slot synchronously during stop: RED then GREEN.
2. Initialization builds inert collaborators through `_build_session_delivery`
   before its first await and captures the lease store for exception rollback.
   `_rollback_session_delivery` and `_release_replaced_session_lease` accept that
   captured store. Mounted real temporary inbox/lease test swaps the app store
   during inbox setup: original lease removed, successor-store record preserved.
   RED then GREEN. This is only exception rollback store capture, not complete
   initialization reference capture.

## Finite whole INITOWNERSHIP map

| Boundary | Current evidence / remaining work |
|---|---|
| Session + owner captured before initialization | Prior 74 retained; 75 surrounding rerun |
| Returned acquisition session/owner mismatch | Prior ownership tests rerun |
| Duplicate initialization preserves handles | Prior test rerun |
| Stop success cannot clear replacement handle | New 75 mounted RED/GREEN |
| Stop failures retained; both stops attempted despite release false/error and throwing notices | Prior nine-case matrix rerun |
| Exception rollback uses acquired store after app store swap | New 75 mounted RED/GREEN |
| Reconcile/acquire/inbox continuation captures | OPEN: preparation still reads mutable slots after awaits; owner identity not checked at every continuation |
| Early closing/identity-change release uses captured store | OPEN: early-return cleanup in preparation still uses current store |
| Successor timer/service/renderer references | OPEN: rollback stops current slots, not initialization-owned handles; session/owner-only service guard insufficient |
| Failed handle retained if successor owns current slots | OPEN: new identity-clear fix alone does not establish displaced failed-handle ownership |
| Rollback release repeated cancellation | OPEN: no new actual release-thread barrier proof or retained rollback-release gateway |
| Missing-store helper | OPEN: dedicated regression not added |
| Shared mount/replacement canonical phase order | OPEN: inert construction extracted, but full canonical sequence not implemented/proved |
| Affected required read closure | OPEN, bounded details below |

Actual activation is the next family after INITOWNERSHIP, followed by inbox and
viewers. None is folded into this finite readiness verdict.

## Execution receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Every pytest command used
`PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`.
The existing approved helper adds 62 foundation tests; no venv created.
All prefixes below live beside this document with `.log` and `.exit`:

- `t5-75-red1`: rollback file; exit 1, **1 failed, 76 passed**.
- `t5-75-green1`: surrounding partition below; exit 0,
  **346 passed, 1 deselected**, 202.69 seconds.
- `t5-75-red2`: ownership file; exit 1, **1 failed, 68 passed**.
- `t5-75-green2`: surrounding partition; exit 0,
  **347 passed, 1 deselected**, 207.85 seconds.
- `t5-75-final-focus`: both ownership and rollback files after Black;
  exit 0, **84 passed**, 5.60 seconds.

Surrounding suffix (unchanged for both green runs):

```text
tests/tui/test_herdr_init_ownership.py tests/tui/test_herdr_init_rollback.py tests/tui/test_herdr_initialization.py tests/tui/test_herdr_app_shutdown.py tests/tui/test_herdr_replacement.py tests/tui/test_herdr_session_lifecycle.py tests/tui/test_app.py tests/tui/authentication
```

- `t5-75-black`, `t5-75-black-check`: `PYENV_VERSION=slo-harness poetry run black [--check] src/tui/app.py tests/tui/test_herdr_init_ownership.py tests/tui/test_herdr_init_rollback.py`; exit 0.
- `t5-75-diff`: `git diff --check`; exit 0, silent.
- `t5-75-coreutils`: `dpkg -V coreutils`; exit 0, silent. Also silent after each surrounding run and final focus.

No fresh lint or full make test/smoke executed: family not READY. The prior
299-errors/63-files baseline remains UNWAIVED and is not asserted unchanged by
this continuation. No added ignores or weakened assertions.

## Actual bounded read coverage

Fresh complete reads: 74 handoff; root RESEARCH; scope-plan; shared engineering
routing/testing/ownership and coding-rules/code-test-loop; Python conventions,
Python declarative, named arguments and docstrings; Textual skill 1–918 in two
chunks; Faux testing skill 1–589; workflow SKILL; canonical C 1674–2175 (C7.13,
C7.14 and final tests/acceptance); KB Welcome and slo/gotchas; actual lease store
1–end; ownership and rollback test files; affected app initialization/acquire,
stop/release sections. Current code-test opening read before updating.

AGENTS, CLAUDE and docs/RESEARCH supplied project context was consulted, but
fresh on-disk rereads were not completed. Routing combined output was truncated;
full routing reread remains needed. Shared declarative combined output lost its
first four metadata lines, not body. KB slo/index.md absent; README fallback
not read. Canonical C7.9–7.12, exact tasks.md T5 samples 2401–3720 and accepted
review attachments were not freshly ingested here. These are explicit remaining
read-closure items, not claims that every file remains unread. Full surrounding
app/test source read closure remains outstanding beyond the sections above.

No external KB writes under the user's restriction.
