# T4 acceptance continuation 28 — INCOMPLETE

## Scope and accounting

Same unfinished turn 1: started 1, completed 0, historical partial 1,
dispatch 28, retries 0. User override: unlimited turns AND dispatches.
No agents dispatched. No production changes in this continuation; only new
`tests/agents/slo_agent/herdr/test_visualizer_acceptance.py` and T4 receipts.
Other workers' partials preserved. No T5 assembly, commit, push, external/spec,
global-state or other-worktree changes. Independent feature Review/Completion
and supported-release/live paint remain later gates.

## New evidence (initial passes, not RED/GREEN cycles)

All commands ran from `/root/Code/slo-94-herdr-integration/slo` through
`bash docs/implementation/94-herdr/t1-dao-check.sh` (P), approved isolated fallback;
`pyenv which python` resolved `/root/.pyenv/versions/slo-harness/bin/python`.
No development env sourced. Registered fixture executable, capture and barrier
were revalidated before writes; real transport retains the suite spawn guard.
No real Herdr, terminal or provider execution.

| Receipt prefix | Arguments after P | Actual result |
|---|---|---|
| t4-28-01 | tests/agents/slo_agent/herdr/test_visualizer_acceptance.py tests/agents/slo_agent/herdr/test_visualizer_lifecycle.py tests/agents/slo_agent/herdr/test_visualizer.py | 124 passed, 2 warnings, exit 0 |
| t4-28-02 | same three files | 125 passed, 2 warnings, exit 0 |
| t4-28-03 | same three files | 128 passed, 2 warnings, exit 0 |
| t4-28-04 | same three files | 130 passed, 2 warnings, exit 0 |
| t4-28-package | tests/agents/slo_agent/herdr tests/agents/slo_agent/orchestrator/test_context_reader.py tests/tui/test_workflow_visualizer_loader.py | 928 passed, 4 warnings, exit 0, 55.40s |

Each prefix has `.log` and `.exit` in this directory. Package count includes
concurrent disjoint lane additions; do not attribute the entire increase to T4.
Scoped Black formatting affected only the new acceptance file. Black check:
`poetry run black --check src/agents/slo_agent/herdr/visualizer.py tests/agents/slo_agent/herdr/test_visualizer*.py`.
`git diff --check` and `dpkg -V coreutils` receipts are t4-28-diff and
t4-28-coreutils respectively. Coreutils output was empty, exit 0.
No fresh lint or full make gate: baseline 301 errors/64 files remains unwaived.
Full integrated make follows all lanes, not inferred from this package gate.

## Finite T4 remaining ledger

| Required row | Current evidence / status |
|---|---|
| Actual public viewer → durable queued A → B, same and changed generation | NEW PASS: `test_operational_viewer_supersedes_queued_report`; public invoke executes split/rename/run, A actually waits on shared lock, real store reload proves reserved sequence, executable records only B with higher sequence |
| G2 close/cancel/timeout variants with operational viewer | Still missing; historical reporter test uses RecordingAdmission viewer command, not public viewer |
| Already-admitted stale A accounting | Existing `test_reporter_compositions.py::test_already_admitted_a_accounts_without_followup`; not newly composed with public viewer here |
| Real sequence write failure/fsync warning/overflow revokes queued split/rename/run | Still missing; lifecycle matrix changes authority facts, not actual reservation failure |
| New versus already-admitted authority-loss matrix | Still missing complete composition; existing queued 21-case matrix retained |
| Shared waiter cancellation | NEW PASS: cancelled public waiter (two cancel calls) leaves shared launch and second waiter intact, one executable entry |
| Done-callback identity/error/cancelled result | NEW PASS: old completion does not remove replacement, error retrieved, matching completion removes entry |
| Repeated close cancellation with delayed real cleanup; all pending parents | Still missing |
| Public success/rejection/oversized split and retained reuse | NEW PASS: success, rename nonzero (continues run), run nonzero, split nonzero, split >16KiB; repeat invoke adds zero commands |
| Split timeout/cancellation/malformed full public composition | Still incomplete: prior malformed core/shared invocation evidence exists; complete matrix not proved |
| Rename ordinary exception versus rejected result | Rejected result NEW PASS; ordinary exception still missing |
| Run timeout and known-pane cancellation in rename/run | Still missing |
| Reader/loader | Existing tests pass in fresh package gate; no edits |
| Complete prerequisite ingestion | Improved but NOT complete; see below |

No new production regression was established. Do not invent a RED result or
modify working code merely to manufacture one. T4 technical READY is withheld.

## Read audit

Read actual routing/scope, t4-code-test and t4-lifecycle-27, root RESEARCH,
KB Welcome/slo README/gotchas, full D (1–711) and exact tasks 2109–2400,
accepted independent review turn4, B 316–655 and 1950–2221 (including 7.13),
C 1340–1669 (activation/retained close). Inspected actual viewer, lifecycle tests,
authority tests, fixture guard, reporter helpers/composition, sequence store and
transport excerpts. Supplied AGENTS/CLAUDE/docs RESEARCH were available in context;
this continuation did not reread all of their actual disk bytes.

Loaded shared routing/testing/ownership, coding rules, exact workflow and shared
workflow SKILL, Python root/declarative, full generic declarative (1–657), full
DAO recipe (1–1525) and service recipe (1–503), named-arguments and docstring
excerpts, code-test-loop excerpt. Thus prior DAO/service/generic-declarative
truncation gaps are recovered. Still required before complete-ingestion claim:
remaining style/cadence tails, full Textual recipe, actual build rules and full
requested actual instruction/docs reads; overview/legacy publication contracts
and remaining relevant C retained-drain sections. No complete B/C ingestion claim.
Two malformed parallel read batches failed validation and read nothing; corrected
individual calls followed. These were tool-call errors, not workflow retries.
