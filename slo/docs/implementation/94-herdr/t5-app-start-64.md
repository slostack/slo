# T5 continuation 64 — headless technical READY; app candidate INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, dispatch 64, retries 0. Effective turn and dispatch budgets unlimited. No agents dispatched. Author evidence only; no independent review or whole-T5 acceptance.

## Headless dependency handoff

Read `t5-headless-final-handoff-63.md` and `t5-headless-audit-62.md`. Audit62 completed the bounded headless required-read/exclusion audit; its explicit closure is inherited evidence, not a claim of new reads here. Continuation63's narrower reads do not revoke that unchanged accepted audit. Its corrected positive G2 and separate deadline case supersede the older viewer race. No functional headless gap was identified in this continuation.

Applied the specifically authorized formatting correction: removed exactly one excess blank line after imports in `tests/cli/test_headless_retained.py`. No production/test behavior changed. Fresh focused retained/viewer tests pass and all 98 paths in continuation63's changed-Python manifest pass Black. Therefore **HEADLESS/SCHEDULER technical dependency READY**. Global lint remains red and unwaived, and continues to block whole-feature final acceptance, not this technical dependency handoff.

Canonical unchanged behavioral baseline inherited from 63: full **7772 passed / 19 deselected**, smoke **288 passed**, lint **299 errors / 63 files**, exact diagnostic comparison added/removed empty. These full/smoke/lint gates were not rerun for a blank-line-only change; no claim of fresh full execution here.

## Fresh receipts

CWD `/root/Code/slo-94-herdr-integration/slo`; approved `PYENV_VERSION=slo-harness` fallback. No installation or environment-file changes.

| Receipt stem (in this directory) | Exact command | Result |
|---|---|---|
| t5-64-headless-focused | `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/cli/test_headless_retained.py tests/agents/slo_agent/herdr/test_visualizer_acceptance.py` | 84 passed, 4 warnings, exit 0 |
| t5-64-black | `PYENV_VERSION=slo-harness poetry run black --check $(cat docs/implementation/94-herdr/t5-63-changed-python.txt)` | 98 files unchanged, exit 0 |
| t5-64-diff | `git diff --check` | silent, exit 0 |
| t5-64-coreutils | `dpkg -V coreutils` | zero bytes, exit 0 |

Each stem has `.log` and `.exit`. Focused count includes the helper's 62 foundation tests; do not sum overlapping counts. Existing fake-only capability, HERDR stripping/disabled defaults and terminal guards were not altered. No real providers, Herdr or windows intentionally invoked; no system stubs added.

## App preparation start: actual source findings and finite unit map

Read actual `src/tui/app.py` lines 2005–2274, including `_start_new_session`, `_replace_idle_session_and_clear_queue`, `_attach_pool_to_session`, and `_build_replacement_session_config`. The current replacement cancels old preparation and unsubscribes the old session BEFORE candidate construction/attachment/rename. Candidate build or rename failure therefore cannot meet exact old-session preservation. Config passes `old_session.model_pool_dao` directly, leaving potential mutable aliasing rather than an explicit deep copy. These are source findings, not executed regression proof.

Next finite candidate-preparation family, retaining the existing owner:

1. Complete the required app-specific reads: canonical entire C and exact T5 attachments 2401–3720, accepted review decisions, relevant B ownership/G2 and D caller context; current session40 candidate disposal seams, actual config/build/rename flows, mounted app/queue/auth fixtures and safe Faux factory. Finish requested on-disk project/KB/build/skill coverage. Do not repeat audit62's entire headless family as a prerequisite.
2. Add `tests/tui/test_herdr_session_lifecycle.py` mounted config-backed Faux regressions for candidate build/attach/rename failure and cancellation. Snapshot old session identity/subscription, queue widget/text, transcript, preparation owner, inbox lease and pool identity; assert exact preservation and candidate-only disposal, never old pool drain.
3. Deep-copy mutable model-pool configuration; prove nested entry isolation and preserve the existing workspace/plugin/new-session policy. Test no-pool and pool branches plus requested-name/no-name behavior.
4. Implement preparation before destructive operations in at most approximately 50 production lines per test-first increment. Run GREEN and mounted app/session/queue/auth surroundings before another increment.
5. After a meaningful complete app family run full make gates and compare lint to unwaived 299/63; no new ignore. Irreversible shielded close/adopt is the NEXT family; monotonic shutdown/inbox/viewer integration later.

**APP CANDIDATE INCOMPLETE:** no new lifecycle test, RED, production edit, mounted app verification or preparation implementation was completed in this continuation. `src/tui/app.py` remains untouched. No claim that planning alone starts executable integration or satisfies candidate readiness.

## Read boundary and preservation

Fresh reads: both required handoffs, routing/scope-plan, current t5-code-test header/history, retained test import region, actual app replacement/config flow, engineering routing/testing/ownership and coding rules. A concatenated skills read was truncated; its missing prefix is NOT counted as complete. The requested complete app-specific canonical/KB/project/skills read closure remains incomplete, so no app edit was attempted. Supplied project context is not misrepresented as an on-disk reread.

No agents, commits, push, PR, reset, clean, stash, global/live/KB/specification/other-worktree edits. Prior work preserved. Changed only the authorized retained-test whitespace and continuation64 evidence/status documentation. Full T5, T6/live acceptance and independent review remain pending.
