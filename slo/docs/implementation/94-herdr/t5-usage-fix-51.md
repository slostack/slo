# Usage fix 51 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 51, retries 0. Unlimited turns AND dispatches; no numeric budget stop. No agents dispatched or acceptance claimed.

## Result and causal boundary

The original enabled regression was reproduced unchanged: `red.log/.exit` reports **1 failed, 74 passed**, exit 1, `3 == 6` for two completed messages in one update. `parse_graph_stream_item` accepts updates dictionaries; `SloAgent._chunk_message_delta` explicitly returns the node's new message list; `TurnStreamAccumulator.absorb_messages` retains every completed message. This boundary is supported by the adapter, though it is not evidence that the shipped single-model-call graph naturally returns two responses in one node.

Minimal agent-only correction aggregates provider-supplied fields across a completed node delta into one capture/version. It removes numeric-equality deduplication and the redundant finalization capture. Messages-mode chunks remain uncharged; their usage can be incremental OR cumulative. Unknown fields remain unknown through existing TokenUsageTotalsDAO.add; no estimates or manufactured counts. No parser or production session edit. The private single-message capture helper is preserved for existing cache tests.

**This is not a complete solution.** A further enabled test proves two separate eventless completed updates still lose the first capture: **3 instead of 6**. `separate-red.log/.exit`: **1 failed, 84 passed**, exit 1. The session consumes only the last version/value at an event boundary; no public event exists between these updates. Aggregating each update fixes the requested original case but does not close the supported family. No next implementation chunk was begun after this red.

Do not solve this by summing a whole iteration into latest-turn on every capture: an intervening public event may already have committed the earlier value. Likewise, ID deduplication alone cannot fix the loss. A correct continuation needs an explicit capture-delivery boundary preserving latest-turn semantics and the session's sole cumulative ownership. Whether that can remain agent-only without adding an observable event or changing the session consumption interface remains unresolved. No claim that the boundary is unsupported; both tests remain enabled.

## Finite coverage map

| Path | Evidence |
|---|---|
| Equal usage across submissions, repeated refresh | Existing new regression retained green |
| Equal usage across local-tool iterations, success and translated tool failure | Retained green |
| Incremental stream chunks plus completed aggregate | Retained green, total 6 once |
| Cumulative messages-mode metadata plus authoritative completion | New test green, total 6 not 12/18 |
| Multiple completions in one update | Original regression now green; one atomic node-delta capture |
| Separate eventless completed updates | **RED**, 3 vs 6; family blocker |
| Empty completion / known zero / missing metadata and cache | Existing zero and surrounding usage/cache tests green |
| Failure/cancel/abort before or after eventless completion | Six new actual session.invoke + real temporary history cases green; exactly one persisted failed/aborted terminal, completion count 0/1, totals None/3, repeated refresh stable |
| Pre-output retry versus recovery | Existing agent two-case test retained green |
| Actual session recovery before/after charged completion | Two new real-session/history cases green: two attempts, one recovery, one terminal completed, 1/2 assistant records and captures, totals 3/6 |
| Committed-output retry refusal with explicit usage/history | **OPEN**; surrounding tests are not substituted for explicit usage proof |
| Full module decision-path closure | Not claimed |

The initial interruption fixture expected failure to be returned rather than re-raised; corrected to catch and assert actual session exception semantics. It then used a recoverable ValueError and observed three actual completions. Changed this *fatal-path fixture* to the existing classifier's credential ValueError sentinel, not production behavior; separate real recovery tests prove recovery accounting. No weakened totals/history assertions.

## Receipts

All prefixes below are `docs/implementation/94-herdr/t5-usage-fix-51-`; pytest uses `bash docs/implementation/94-herdr/t1-dao-check.sh <paths>` with its DAO/projection additions, isolated test state, stripped HERDR/disabled integration and terminal/fake guards. CWD is this checkout. Verified approved `/root/.pyenv/versions/slo-harness/bin/python`, Python 3.11.7. No venv creation or live provider/Herdr call.

- `red`: original regression, 1 failed / 74 passed.
- `green`: original + agent + session_usage + cache_control, 1 failed / 160 passed: private helper signature regression. Fixed by retaining the existing single-message helper, not editing the cache test.
- `green2`: same partition, **161 passed**, exit 0.
- `interrupted`: new module + session_usage, 2 failed / 83 passed (fixture exception expectation).
- `interrupted2`: 1 failed / 84 passed (recoverable fixture actually recovered).
- `interrupted3`: **85 passed**, exit 0.
- `recovery`: new module + agent_recovery + session_rate_limits, **110 passed**, exit 0.
- `cumulative`: new module + dual-mode + parser, **99 passed**, exit 0.
- `surrounding`: new module, agent, agent_recovery, dual-mode, parser, session_usage, session, session_rate_limits, session_manual_compaction, session_compaction_integration, cache_control: **375 passed, 73 warnings**, exit 0. This precedes the final enabled red test and is NOT a final green family receipt.
- `separate-red`: **1 failed, 84 passed, 16 warnings**, exit 1. Failure remains enabled after formatting.
- `mypy`: 10 errors / 7 files, including one own method-assignment test error; corrected with monkeypatch.
- `mypy-final`: imported errors remain; inspect full log, no errors in either owned file. Not a green static gate. Supplied full baseline 299/63 remains unwaived; no full make lint rerun.
- `black-check`: changed files pass, exit 0.
- `diff-final` and `coreutils-final`: silent, exit 0.

Full make test/smoke deferred to integration after lanes as requested. No global/coreutils/system mutation, git lifecycle, specification, shared status, other worktree or session-service edits. Changes only agent.py, the owned regression test module and this report/receipts. A temporary concatenated skills reading file was written under /tmp, not a repository artifact.

## Routing and ingestion qualification

Read supplied AGENTS/CLAUDE/docs RESEARCH and actual root RESEARCH; actual routing/scope plan, reports 49/50, Makefile and approved helper; committed engineering routing/testing/ownership, coding rules/cadence/shared declarative, Python root/declarative/Faux recipe, workflow SKILL. Read KB Welcome, actual slo README (index.md absent) and gotchas. Read actual parser/accumulator/usage DAO, relevant agent capture/update/finalization/retry and session commit/history/interruption paths, existing usage/cache tests and test isolation/terminal guards. Canonical B7.6 and C publication/final-usage contracts read directly read-only. No CLI/TUI/DB recipe implementation is in scope. Existing session snapshot remains sole presentation/accounting owner.

Complete requested build/style/agent-module and normative attachment ingestion is **not** claimed: named-argument/docstring skills and full agent/Faux sources were not reread in entirety in this continuation. No independent review or full family acceptance. The next continuation must close these ingestion gaps, the separate-update red, and the explicit committed-output refusal matrix before READY.
