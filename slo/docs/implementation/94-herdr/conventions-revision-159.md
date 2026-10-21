# Conventions revision159 — bounded R158-2 READY (offline)

## Scope and accounting

Code+Test revision turn3, global159/current-turn dispatch1 parallel batch; inherited started3/completed0/historical stopped partial1, prior turns1/2 REVISE incomplete, retries0. Effective budgets UNLIMITED. This lane used no subagents and does not advance independent Review or Completion.

AGENTS read first. Branch `feature-94-herdr-integration`, origin `https://gitlab.com/core-27/slo.git`, merge-base `d0e3a756689f2675e5507034d43cd8b272d3c6b8` confirmed read-only. Existing dirty/untracked work preserved. No Git mutations, other-worktree/global/KB/shared-status changes. No edits to agent.py or usage regressions. Optional duplicate executor assertion left unchanged.

## Routing and bounded plan

Python3.11.7, pytest, Pydantic2/LangChain Faux model, asyncio transport and Textual test callbacks. Project instructions, CLAUDE, root RESEARCH, supplied docs/RESEARCH, Makefile, independent-review158, KB Welcome/slo README/gotchas consulted. Worktree Code-Test-Review/code-test-loop and shared engineering routing/ownership/testing, coding-rules/declarative structure, Python root/named arguments/types/docstrings/declarative guidance and Pydantic Field/test-graph guidance used. Specific finite annotation-only scope supersedes architecture expansion; no SQL/API/worker/CLI implementation needed.

Plan executed: inspect actual fixture/admission/result/lease/timer contracts; retain finite AST RED; annotate in three bounded batches with module tests before next batch; recheck broader new definitions, static checks, formatting, scoped diff and surrounding tests. No behavioral fix is claimed: the callback wrapper retains the same await → entered → resume → result sequence. Its ParamSpec Protocol preserves each concrete bound operation without getattr-based Any. The timer wrapper explicitly mirrors installed Textual set_interval arguments/defaults and TimerCallback. Guard ownership, cancellation/races, existing assertions and cardinality oracles are unchanged. One added non-null collaborator assertion establishes the existing initialized fixture precondition.

## Exact owned files

- `src/agents/providers/faux.py`: descriptions only for queue, chunk_queue, bound_tools; default factories unchanged.
- `tests/agents/slo_agent/herdr/test_cli_transport.py`
- `tests/agents/slo_agent/herdr/test_reporter.py`
- `tests/agents/slo_agent/herdr/test_reporter_compositions.py`
- `tests/agents/slo_agent/herdr/test_reporter_shutdown_closure.py`
- `tests/agents/slo_agent/herdr/test_restore_save.py`
- `tests/agents/slo_agent/herdr/test_t2_remaining.py`
- `tests/agents/slo_agent/herdr/test_transport_lifetime.py`
- `tests/tui/test_herdr_init_ownership.py`
- `tests/tui/test_herdr_init_rollback.py`

No Any/cast/ignore/config/exclusion suppression added. Existing unrelated casts and historical untyped Faux constructor passthrough are not rewritten.

## RED → GREEN evidence

Receipts: `conventions-revision-159-receipts/`. `red-inventory.txt` preserves review158's exact37 incomplete signatures. `before/` captures this lane's actual starting ten files, not base or another lane's edits. `owned.diff` is the reviewed before159→after159 scope. Static missing annotations suffice as authorized RED; no fabricated failing behavior test.

Every command is retained as `<label>.command`, output `.log`, exit `.exit`. All listed verification exits are0:

| Label | Command / result |
|---|---|
| batch1 | `python -m pytest -q` cli_transport, reporter, reporter_compositions, reporter_shutdown_closure, t2_remaining modules: **201 passed**,2 warnings |
| batch2 | `python -m pytest -q` reporter, restore_save, transport_lifetime, test_faux, cli_transport modules: **151 passed**,2 warnings |
| batch3 | `python -m pytest -q` init_ownership, init_rollback, initialization modules: **73 passed**,2 warnings |
| final-tests | `python -m pytest -q tests/agents/slo_agent/herdr tests/agents/providers/test_faux.py tests/tui/test_herdr_init_ownership.py tests/tui/test_herdr_init_rollback.py tests/tui/test_herdr_initialization.py`: **1504 passed**,125 warnings,142.40s |
| audit | `python docs/implementation/94-herdr/conventions-revision-159-receipts/audit.py`: **1339 owned/new definitions**, no incomplete signatures; three Field descriptions present |
| final-mypy | `python -m mypy` exact ten paths from files.txt: **no issues in10 source files** |
| final-black | `python -m black --check` exact ten paths: **10 unchanged** |
| diff-check | `git diff --check --` exact ten paths: silent |
| coreutils | `dpkg -V coreutils`: silent; also silent after each earlier batch |

`audit.py` checks all owned definitions, all untracked new src/tests Python definitions, and definitions newly added relative to base in tracked changed Python files, including nested/variadic/positional-only signatures. It does not certify every pre-existing signature or independent whole-feature convention coverage.

`run.sh` selects `/root/.pyenv/versions/slo-harness` through VIRTUAL_ENV/PATH/PYENV_VERSION and uses the tracked safe Makefile fallback values explicitly; `make test-env` returned fallback. No secrets/environment files sourced. Root Herdr146 and terminal guards unchanged; registered temp-owned fakes only. No actual provider/Herdr/pane operations.

## Handoff limits

Bounded **R158-2 READY offline**, not independent approval or whole-feature completion. Full non-E2E suite deliberately not run while the parallel lane writes. Integrated full/static gates, whole-feature independent Review (including R155-2), and fresh Completion remain later steps. Other-lane R158-1 closure is not assessed here. Live acceptance is **USER-DEFERRED; compatibility UNVERIFIED**.
