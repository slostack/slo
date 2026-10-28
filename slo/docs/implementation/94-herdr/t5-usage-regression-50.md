# USAGE-OWNER regression 50 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 50, retries 0. User limits unlimited turns AND dispatches; old numeric limits void. No agents dispatched, no workflow acceptance.

## Scope and current result

Added only `tests/agents/slo_agent/test_agent_usage_commit_regressions.py`; Black also collapsed the existing multiline equality guard in `src/agents/slo_agent/agent.py`. No production semantic change in this continuation. Session service, Herdr attention tests, shared status, specs, other worktrees and globals untouched. No git lifecycle actions. Prior partial work preserved.

**Family cannot be called READY.** The final test exposes a concrete unresolved boundary: two distinct completed assistant messages (different IDs, each 3 tokens) in one graph update yield session total **3, expected 6**. Receipt `t5-usage-regression-50-distinct-red.log/.exit`: **1 failed, 74 passed**, exit 1 (includes helper-added DAO/projection tests). The assertion remains enabled. No next implementation chunk was started after red.

Causal source inspection: `_capture_completed_usage` deduplicates by totals plus iteration, not completed-message identity. `_process_updates_mode_chunk` captures all messages before returning its list of public events. The session commits only the latest capture/version on an event boundary. Merely making message IDs distinct in dedup would therefore still lose an earlier eventless capture; merely summing the latest turn would risk changing latest-turn semantics or re-adding earlier captures. A fix must preserve the existing latest-turn/version/session commit contract, not add Herdr-owned accounting. This is a parser-supported synthetic update, **not proof that the shipped one-model-call graph naturally emits multiple assistant completions per iteration**. Its reachability/contract and safe fix remain open.

## Finite contract map

| Boundary | Evidence / status |
|---|---|
| Same totals across submissions; reset identity, monotonic version; repeated/per-event UI refresh | New 2-case test passes. Latest 15; cumulative 15 then 30; versions 1 then 2. |
| Incremental chunks plus completed aggregate | New real Faux/graph/session test passes: two 3-token deltas, one capture, total 6. |
| Failure/cancellation before completed update | New parser-boundary tests pass: no capture, no completed run; original exception identity preserved. This characterizes current completion-only behavior, **not historical partial-stream accounting compatibility**. |
| Failure/cancellation after eventless completed update | New agent-boundary tests pass: one capture retained at 3. Session persistence/final usage under interruption not yet proven by these tests. |
| Pre-output retry versus recovery | New two-case graph wrapper fails once then delegates to real Faux graph. Exactly 2 attempts, 1 usage capture, total 3, expected retry/recovery-start event, successful terminal, no failure event. |
| Equal totals across tool iterations | New real local tool/Faux/session success/error cases pass: one tool result, two captures, cumulative 6. Tool error is executor-translated, not an escaped provider failure. |
| Empty completed response / known zero | New real graph/session test passes: one capture and available total 0. |
| Multiple distinct completed messages in one update | **RED**, 3 instead of 6. |
| Graceful abort; interrupted history and session totals; committed-output retry refusal with usage; recovery after a completed charged response | **OPEN** for explicit usage/history assertions. Existing surrounding tests retained, not overstated as this proof. |
| Cache extraction, missing metadata | Existing `test_cache_control.py` and `test_session_usage.py` pass; no claim of new exhaustive malformed/cache decision coverage. |

No full-module branch closure claim. No provider accounting redesign, no new usage/history/public event kind.

## Execution receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. Approved existing Python 3.11.7/Poetry fallback, no venv creation. All pytest invocations used `bash docs/implementation/94-herdr/t1-dao-check.sh <paths>`; helper adds `herdr/test_daos.py` and `herdr/test_projection.py`, isolated test state, HERDR disable and terminal/fake spawn guards. Only Faux, local in-memory tool and graph-boundary injected faults; no actual providers/Herdr/windows.

Receipt prefix is `t5-usage-regression-50-`; logs and exits are beside this report.

- `initial`: new first 3 cases + `test_agent.py`, `test_session_usage.py`: **141 passed**, exit 0.
- `boundary`: preceding partition + four interruption cases: **145 passed**, exit 0.
- `retry`: new module + `test_agent_recovery.py`, `test_session_rate_limits.py`: **98 passed**, exit 0.
- `tools`: new module + `test_agent.py`, `test_session_usage.py`: **150 passed**, exit 0.
- `surrounding`: new module; `test_agent.py`, `test_agent_recovery.py`, `test_agent_streaming_dual_mode.py`, `test_session_usage.py`, `test_session.py`, `test_session_rate_limits.py`, `test_session_manual_compaction.py`, `test_session_compaction_integration.py`, `test_cache_control.py`: **355 passed, 71 warnings**, exit 0. This precedes the final red test; **not a final green receipt**.
- `distinct-red`: new module including the unresolved test: **1 failed, 74 passed, 14 warnings**, exit 1. Exact failure: `assert 3 == 6` at session cumulative total assertion.
- `mypy`: initial test wrapper had 7 own forwarding-signature errors; replaced generic forwarding with the exact graph mode call. `mypy-final` and `mypy-last`: **9 errors / 6 imported files**, exit 1, **none in agent.py or new test file**. Errors remain unwaived: yaml stubs, transcript projector, Faux, normalizer and provider adapters. Not a full lint replacement; supplied full baseline 299/63 remains unwaived.
- `black-last`: `poetry run black --check src/agents/slo_agent/agent.py tests/agents/slo_agent/test_agent_usage_commit_regressions.py`, exit 0.
- `diff-last`: `git diff --check`, silent, exit 0.
- `coreutils` and `coreutils-last`: `dpkg -V coreutils`, silent. Earlier paired exit 0; final command also returned success.

Tests were added in small increments and each passed with surrounding coverage before the next. They characterize already-fixed behavior, not new red/green causal repairs. The final boundary test is genuinely red; no disabled assertion or manufactured baseline proof. Full make test/smoke intentionally deferred until integration, not repeated in parallel.

## Read coverage and remaining ingestion

Read current routing/scope plan, root RESEARCH and supplied AGENTS/CLAUDE/docs RESEARCH; shared routing/testing/ownership, coding rules/code-test-loop, Python/declarative/Faux recipes, workflow SKILL, named arguments/docstrings; KB Welcome/slo README/gotchas; current agent usage/update/retry/recovery code, session commit/event bridge, usage DAO, Faux, test isolation and existing usage/cache/agent/recovery tests. Canonical B 7.6 and C publication/final-usage/operation-owner prose and examples read directly, read-only. One combined skill read truncated its early shared declarative material; coding rules and cadence were reread separately. **Complete requested normative/build-rule/agent-module ingestion is not claimed.** Relevant T5 sample attachment reread and full usage transport/history traversal remain open alongside the behavioral gaps above.

Next work: settle the multi-completion supported contract and preserve sole session usage ownership; add failing usage/history boundary tests before any correction; then rerun the full finite partition, static own-error check and safety checks. No family READY until those explicit gaps are closed.
