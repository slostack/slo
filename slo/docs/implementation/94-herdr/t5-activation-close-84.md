# T5 activation close 84 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 84, retries 0. Effective turn/dispatch budgets unlimited. No agents launched. INITREADY82 preserved. No production changes, commits, external actions, global/spec/other-worktree edits or inbox/viewer implementation.

## Bounded result

Added `test_mounted_contender_refuses_real_lease_without_commands` in `tests/tui/test_herdr_activation_composed.py`. A real config-backed owner activates using the registered fake CLI, actual sequence lease and native store. Its ordinary admission is then revoked without releasing its lease. A second config-backed session mounts in Textual and is refused by the actual lease. Assertions cover no further command capture, unavailable destination, no reporting adoption, uncertain/drained close, a third actual lock probe still refused, and slash `/new` successor suppression. Final owner cleanup permits the probe to acquire/release. Faux factory is installed before construction; no injected session agent replaces the production assembly.

This was existing-correct behavior, not a production RED repair. Initial execution failed on a test typo (`_lock` instead of actual `_command_lock`); corrected test passed without production edits. No uncertainty flag was changed or cleared.

## Finite remaining map (not a completed acceptance ledger)

| 82/83 obligation | Current evidence / status |
|---|---|
| Native mount/save/display and safe replacement | Retained 83 regression; passes in fresh surrounding run |
| Disabled/outside parity | Retained composed cases; pass |
| Assembly/start cancellation and no late claim | Retained composed cases; pass |
| Mounted contender with actual lease | New 84 test passes; closes this bounded gap |
| Persistent unlock retention and repeated successor suppression | Retained composed test; passes |
| Drained remote/cleanup uncertainty and collectability | Retained 83 contrasts pass; not full wire ambiguity coverage |
| Remaining probe/claim/close activation faults | OPEN; no new complete branch mapping/evidence |
| Every runtime await plus throwing diagnostic cutoff | OPEN; no new complete branch mapping/evidence |
| Complete finite REMOTE ambiguity/release contrasts | OPEN; no new complete branch mapping/evidence |
| Final canonical B/C/app-scope closure read | OPEN; cannot claim READY |

C7.14's separate T6 64-case integration matrix is not added to this activation task. Inbox is next only after activation readiness; no TUI viewer work started.

## Execution receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. All pytest calls use `PYENV_VERSION=slo-harness bash docs/implementation/94-herdr/t1-dao-check.sh <arguments>`, including its 62 DAO/projection cases. Existing HERDR stripping, test-owned home, regular-file identity/containment spawn guard and terminal guard remain unchanged.

| Receipt prefix | Arguments / action | Actual result |
|---|---|---|
| t5-84-contender | composed activation file | 1 failed, 70 passed; exit 1; test lock-name typo |
| t5-84-contender-corrected | composed activation + herdr/test_session_lifetime.py | 130 passed, 4 warnings; exit 0 |
| t5-84-surrounding | arguments below | 1724 passed, 163 warnings in 318.25s; exit 0 |
| t5-84-black | Black check composed activation | exit 1, formatting needed |
| t5-84-format | Black composed activation | exit 0 |
| t5-84-black-final | Black check composed activation | exit 0 |
| t5-84-final-focus | both activation files + herdr/test_session_lifetime.py, after formatting | 131 passed, 4 warnings; exit 0 |
| t5-84-diff | git diff --check | silent exit 0 |
| t5-84-coreutils / t5-84-coreutils-final | dpkg -V coreutils after suites | silent exit 0 |

Surrounding arguments:
```
tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/tui/test_herdr*.py tests/tui/test_app.py tests/tui/test_queued_prompt_block.py tests/tui/test_openrouter_startup.py
```
Each receipt has sibling `.log` and `.exit`. Full make test/smoke/lint were not run because family readiness was not reached. Historical 299 errors/63 files remains unwaived and not freshly compared. No new ignore/skip/xfail.

## Read limitations and handoff

Read actual 82/83 receipts, activation tests, fixture safety, reporter activation and B activation/close transaction excerpt, C7.11 and C7.14. Loaded engineering routing/testing/ownership, Python root/style/declarative, shared coding/declarative/cadence, Textual, Faux and workflow skill. KB entry/README/gotchas consulted. A combined actual AGENTS/CLAUDE/research/routing/scope read was output-truncated; supplied project context is not a substitute for claiming that full actual read completed. Full C7.9–7.14, exact T5 samples, accepted reviews, DAO/application-service build rules and final affected B/C/app closure audit remain unfinished. This is a prerequisite and coverage shortfall, not a budget stop or discovered production blocker.

Verdict: **INCOMPLETE activation family**. Do not treat the new contender proof or 1724-pass surroundings as finite-family closure, full T5 acceptance, or permission to advance to inbox.
