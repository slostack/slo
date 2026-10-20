# T5 continuation 70 — mount initialization INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 70, retries 0; effective turn and dispatch limits unlimited. No agents
launched. No commits, push, PR, reset, clean, stash, global, live, canonical spec
or other-worktree changes.

## Actual increment

`src/tui/app.py` now retains `_mount_runtime_task`, runs mount delivery under the
submission gate, joins it before shutdown takes that gate, and checks closing and
captured session after reconcile/acquire/inbox awaits. Public mount cancellation
joins through HerdrTaskJoin. This is a partial increment, NOT the complete
transactional initializer or activation protocol. Existing 69 independent final
owner attempts were preserved.

`tests/tui/test_herdr_initialization.py` adds an actual Textual mount barrier after
real temporary lease acquisition and before its return. It proves shutdown waits
for the retained initializer and leaves no timers/lease after cutoff. It does NOT
exercise Faux inference or enabled fake-executable Herdr activation.

## Finite branch map

| Branch | Evidence/status |
|---|---|
| Mount retained while acquired lease return is pending; shutdown joins outside gate | new mounted test, passing |
| Cutoff after acquire; no timers, lease removed | same test, passing |
| Reconcile/inbox late return guards | implemented but independent branch tests pending |
| Captured ID AND owner across all awaits; returned lease validation | pending |
| Reconcile/acquire/inbox exceptions transactional rollback | pending |
| First/second timer registration failure/cutoff, failed stop retains actual handle | pending complete matrix (existing stop helper preserved) |
| Cancellation with real off-loop work and repeated cancellation | pending |
| Shared replacement identity/initialization protocol | pending |
| Ready-only enabled activation after initialization; old release before successor claim | pending |
| Throwing notice cannot starve each rollback owner | pending initialization matrix |

No prompt registration/inbox delivery implementation was attempted.

## Commands and results

CWD: `/root/Code/slo-94-herdr-integration/slo`.
All pytest runs use `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh`
with the listed test arguments; helper adds 62 foundation cases and safe fallback env.
Logs are adjacent. Completed commands have exit files.

- `t5-70-red1`: `tests/tui/test_herdr_initialization.py`: exit 1,
  **1 failed, 62 passed**; assertion missing retained mount task.
- `t5-70-focused1`: initialization + shutdown: exit 0,
  **72 passed**, 2 warnings, 3.10s.
- `t5-70-green1`: initialization, shutdown, replacement, lifecycle, app,
  authentication: tool timeout **900s**, no exit receipt, NOT green.
- `t5-70-surround-isolation`: replacement + lifecycle `-vv`: tool timeout
  **120s**. Last entered case is
  `test_herdr_replacement.py::test_retired_owner_final_drain_is_joined`.
  No terminal receipt; this is localization, not a proven root cause or waiver.
- `t5-70-app-surround`: app + authentication + initialization + shutdown:
  tool timeout **600s**, no terminal exit receipt, NOT green.
- `t5-70-format`: scoped Black on app.py/new initialization test, exit 0.
- `t5-70-diff`: git diff --check, silent, exit 0.
- `t5-70-coreutils`: dpkg -V coreutils, silent, exit 0.

The chained Black check after app-surround was not reached before tool timeout;
no passing check claimed. No fresh full make test was run because the family is
not closed and surrounding tests are not green. Existing 299 errors/63 files
static baseline remains unwaived; no ignores added.

## Reading and limitations

Read supplied AGENTS/CLAUDE/docs RESEARCH, frozen routing/scope plan, actual app
shutdown/initialization/replacement code, shutdown tests, canonical C initializer
and mount/shutdown sample, shared ownership/testing/routing and coding cadence/
declarative/Python gateways. Combined additional skill/KB reads truncated; complete
requested read closure (exact T5 samples, accepted reviews, B/D lifetime and full
Python style/Faux prerequisites) is NOT claimed. No 69 prose receipt was found;
68 receipt and actual 69 focused log were inspected.

Next work must first resolve the surrounding hang without weakening assertions
or changing owner policy, complete required reads, then continue red/green units
for the pending rows. Do not promote this partial mount task into READY or all-T5
acceptance. **Verdict: INCOMPLETE initialization family.**
