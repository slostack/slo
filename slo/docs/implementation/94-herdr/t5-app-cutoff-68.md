# T5 continuation 68 — finite APP cutoff INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, dispatch 68,
retries 0. Effective turns AND dispatch budgets unlimited. No agents, commits,
external actions, canonical spec, global state or other-worktree edits.
Continuation 66 partial work preserved; 67 supplied as reads-only after API error.

## Substantive bounded increments

Changed `src/tui/app.py`; added `tests/tui/test_herdr_app_shutdown.py` (8 cases).
No session lifetime changes or new coordinator.

1. Irreversible `_app_closing` and quiescing prefix before first teardown await;
   synchronous selected-session revocation; retained shielded app shutdown task.
   Join retained replacement OUTSIDE submission gate, then resolve actual selected
   owner under gate. Candidate preparation completed after cutoff is disposed;
   already committed adoption remains irreversible, with suppressed candidate and
   no delivery reinitialization. This preserves C's committed adoption policy;
   committed assignment after cutoff is not new runtime admission.
2. Independent shutdown failure boundaries for preparation, selected close,
   unsubscribe/timer/lease cleanup and final drains. Best-effort fixed notices.
3. Captured identity/closing guards after mount hydration/notice/delivery/usage,
   replacement UI/usage and preparation continuations; preparation entry refuses
   after cutoff. No successor reporting activation added.

## Finite evidence map

| Branch | Mounted test |
|---|---|
| Replacement reporter close pending at unmount; retained commit; actual adopted owner closed/unsubscribed; no new lease/timers; later `/new` refused | `test_unmount_joins_replacement_outside_gate` |
| Preparation/unsubscribe/close/release ordinary faults plus throwing diagnostic; current and retired drain attempted | `test_shutdown_attempts_each_owner`, four cases |
| Hydration, replacement usage and preparation await resumed after shutdown; no notice/usage/initialization/subscription resurrection | `test_late_runtime_continuation_is_silent`, three cases |

These are actual mounted Textual, real config-backed session/null reporter and
real temp inbox/lease evidence, NOT enabled fake-executable Herdr resource proof.
New tests do not invoke Faux/model inference; surrounding candidate tests do.
No live providers, Herdr, terminal windows, system symlinks or binary changes.

## Executed commands and receipts

CWD `/root/Code/slo-94-herdr-integration/slo`; approved existing slo-harness environment.
F = `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh tests/tui/test_herdr_app_shutdown.py`
S = F followed by `tests/tui/test_herdr_session_lifecycle.py tests/tui/test_herdr_replacement.py tests/tui/test_app.py tests/tui/authentication`.
Helper adds 62 foundation tests. Every completed stem has `.log` and `.exit` here.

| Stem | Command | Result |
|---|---|---|
| t5-68-red1 | F | 1 failed/62 passed, exit 1; no closing flag |
| t5-68-surround1 / surround1b | S | Tool timeout at 240s, no terminal exit receipt; not passes |
| t5-68-surround1c | S | 315 passed/1 deselected, exit 0 |
| t5-68-red2 | F | 4 failed/63 passed, exit 1; ordinary owner errors escape |
| t5-68-surround2 | S | 319 passed/1 deselected, exit 0 |
| t5-68-red3 | F | 3 failed/67 passed, exit 1; late runtime callbacks repaint/reinitialize |
| t5-68-surround3 | S | 322 passed/1 deselected, exit 0 |
| t5-68-format | scoped Black app.py + new test | exit 0 |
| t5-68-full | `PYENV_VERSION=slo-harness make test` | 7808 passed/19 deselected/556 warnings, exit 0, 637.55s |
| t5-68-lint | `PYENV_VERSION=slo-harness make lint` | 299 errors/63 files, exit 2, unwaived |
| t5-68-black | scoped `black --check` same files | exit 0 |
| t5-68-diff | `git diff --check` | silent, exit 0 |
| t5-68-coreutils | `dpkg -V coreutils` | silent, exit 0 |
| t5-68-lint-comparison | sorted error-line diff against 66, line numbers normalized only | silent, exit 0 |

Timeout isolation: existing retired test patches the null reporter CLASS resource
getter for all sessions. Waiting for current drain before retired, or concurrently,
caches retained evidence on the null successor before the old barrier releases.
Sequential retired-first then current final drain lets that existing test resolve.
This is NOT proof of the required persistent-retention/all-owner guarantee; see below.
No assertions/skips/ignores changed to obtain green. Smoke not rerun.

## Remaining precise blockers — no READY claim

- Final drains are currently sequential retired-first. A permanently pending retired
  drain can prevent actual current final local drain; ordinary error containment can
  also report completed shutdown after a synthetic final-drain exception. Must retain
  both owners and start/attempt both safely before waiting indefinitely, without the
  class-wide fake getter cross-contaminating their resource evidence. Add deterministic
  per-owner (not class-global) retained barriers and cancellation/strong-retention tests.
- Mount initializer remains legacy, unretained and not gate-owned. Need captured-ID
  lease DAO validation, retained mount task, rollback of every await/timer failure and
  join outside gate. New top-level guards alone do NOT fix initialization resuming
  internally across cutoff. Identity guard after startup notice cannot undo that
  notice helper's own late side effects. Exact startup/render failure matrix pending.
- Inbox claim/advance/delivery/ack and final prompt task registration cutoffs remain
  unfinished; no claim of all work admissions sealed. Late auth/viewer guards pending.
- Replacement runtime transfer checks closing but lacks complete captured-identity
  initializer protocol. No enabled successor activation or real-resource quarantine
  proof, persistent failure/late reap, mounted Faux barrier invocation, full canonical
  T5 acceptance, or independent review.
- Complete fresh mandatory skill/read closure was not established: combined skill
  read truncated; shared ownership/testing, Python gateway/declarative, workflow,
  routing/scope and selected C sections were read, but all listed Python/Textual
  resources and exact T5 samples were not completely re-read. Supplied project
  AGENTS/CLAUDE/docs RESEARCH were available; root RESEARCH was only read by shell,
  not ingested into model output. Do not inherit a false complete-read claim.

Full green regression is evidence for this partial snapshot, not cutoff-family or
whole-T5 acceptance. Continue these named obligations without resetting counters or
inventing a turn/dispatch/unit budget. **Verdict: INCOMPLETE finite APP cutoff.**
