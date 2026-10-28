# Usage revision159 — bounded R158-1 READY; integrated gates pending

Code+Test author handoff only. R158-1's completed-node trace boundary is corrected; this does not close full independent Review or authorize Completion/delivery. Turn3/global159/current-turn dispatch1 parallel batch; started3/completed0/historical stopped partial1; prior turns1/2 incomplete REVISE; retries0; effective budgets UNLIMITED. No subagents launched.

## Scope and correction

Branch/origin/base inspected and matched feature-94-herdr-integration, GitLab core-27/slo and d0e3a756689f2675e5507034d43cd8b272d3c6b8. All pre-existing work retained. Only production edit in this lane: in `src/agents/slo_agent/agent.py::_process_updates_mode_chunk`, move the existing synchronous `_capture_completed_update_usage(messages=delta_messages)` from after the trace loop to immediately after `turn.absorb_messages`, with a one-line cancellation rationale. No new accounting owner, chunk sum, equal-total deduplication, error handling, history format or Herdr logic.

Completed graph node delta → synchronous usage handoff → awaited trace/history → existing session final refresh/drain. The provider has completed independently of whether its observer persists successfully. Cancellation and ordinary trace exceptions retain their original behavior; the single-consumer pending usage survives both.

New permanent file: `tests/agents/slo_agent/test_usage_trace_cancellation.py` (five parameterized cases). It proves:
- External task cancellation while actual Faux graph assistant trace is pending: last usage3, one capture, pending drain3 then unknown, cancellation propagates.
- Public session external cancellation before real assistant append and after real append: totals3 on repeated refresh, exact assistant count0/1, one user/run_started/run_aborted, no run_completed/run_failed, no retry/recovery. Session's existing cancellation-to-aborted semantics remain intact.
- Ordinary first trace failure with one/two eventless completed messages in a single node delta: same exception object propagates, exactly one graph entry and failed trace terminal, all usage3/6 retained, drain exactly once.

Existing `test_agent_usage_commit_regressions.py` was not edited. Its partial-chunk exclusion, equal totals, incremental/cumulative metadata, eventless/separate updates, tools, recovery and committed-output no-retry coverage remains green. No new test interprets 'no replay' as deleting aborted history: current projector deliberately includes terminal aborted turns. Assertions prohibit automatic re-execution within the interrupted invocation.

## Routing and prerequisite scope

Consumed supplied AGENTS/CLAUDE/docs RESEARCH; actual AGENTS first, root RESEARCH, Makefile, routing.md, scope-plan, profile156, author closure157, independent158 and retained probe. Consulted KB Welcome/slo README/gotchas read-only. Loaded authoritative worktree Code-Test-Review, code-test-loop, engineering routing/ownership/testing, coding-rules/shared declarative, Python root/types/docstrings/declarative/application-services/graph-gateway/Faux test guidance. No CLI/DAO/SQL/UI redesign is implicated by moving this existing call; project instance-owned invoke/dual-stream topology remains authoritative over generic example graphs.

Canonical selected scope: overview; tasks normative T5/T6 and common verification; C7.1 (169–205), C8–10 (2122–2175). Actual graph node, agent delta/trace/capture/drain, session trace/store/final-refresh, filesystem append and history projector inspected. Full-feature reread/review is not claimed. Selected reads preceded writes. Tests use real Faux graph and public session plus deterministic observer/store barriers; synthetic node delta is reserved for multi-message/eventless failure coverage.

## Exact evidence

Receipts: `usage-revision-159-receipts/`. `run.sh` records commands, complete logs, exit codes and post-command coreutils checks. Explicit `/root/.pyenv/versions/slo-harness`, Python3.11.7, VIRTUAL_ENV/PATH/PYENV_VERSION; tracked Makefile fallback exported, no secrets sourced; `make test-env` reports fallback. Root146 fake/window guards remain unchanged; new history writes are under an asserted temp-owned root. No live provider/Herdr/panes/global/Git mutations.

| Receipt | Result |
|---|---|
| agent-red |1 failed,3 warnings, exit1 before production edit; capture version0 instead of1 at externally cancelled trace|
| agent-green |32 passed,20 warnings, exit0|
| session-green |34 passed,22 warnings, exit0|
| trace-green |36 passed,22 warnings, exit0|
| retained-probe |unchanged independent158 probe:2 passed,4 warnings, exit0 (its historical RED remains in158 receipts)|
| broad |1 failed,1834 passed,220 warnings, exit1 — not a green integrated gate|
| herdr-isolated |1419 passed,125 warnings, exit0|
| agent-session-isolated |416 passed,98 warnings, exit0|
| lint |2 scoped files clean, exit0|
| black |2 files unchanged, exit0|
| diff |git diff --check silent, exit0|

All recorded coreutils checks are silent. Formatting changed only the new test. Scoped production diff reviewed: capture precedes the first observer await, remains once per delta and retains early empty-delta return. No Any/cast/ignore or assertion weakening introduced.

### Unresolved combined-run evidence

The combined broad selection failed `herdr/test_test_isolation.py::test_actual_guard_refuses_activation_inside_runtime[headless]` at `assert await runner.invoke(prompt="offline") == 0`, actual1. Captured output: `No OpenAI credentials found. Run /auth in the TUI or set SLO_OPENAI_API_KEY.` The runner built a different session instead of the test's patched injected session. Entire Herdr selection subsequently passes alone; entire agent/graph/session selection passes alone. This suggests order-sensitive class/import identity or concurrent-input interaction, but root cause and baseline attribution are NOT proved here. No extra credential was supplied, no guard/assertion changed, and no unrelated production/test file edited. Preserve broad.log for integrated owner investigation; separate greens do not erase it.

No full suite ran during parallel writes, as instructed. Full integrated static/test gates remain later work, followed by independent entire-feature Review and fresh Completion. Parallel R158-2 lane/shared status files were untouched. Live installed launcher/native restart/version/wire/TTL/wait/release/panes/paint remains USER-DEFERRED; compatibility UNVERIFIED. No full-review resolution or user-delivery approval claimed.
