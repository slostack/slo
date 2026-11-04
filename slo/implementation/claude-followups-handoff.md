# Claude follow-ups — revision handoff (turn 2 / dispatch 1)

> Commit excerpt: recorded phase evidence, not a new verification run.
> Superseded dispatch histories are omitted from this commit and preserved
> in the local working copies. References to historical sections or mappings
> "below" refer to those originals. The completion document contains the
> consolidated acceptance mapping; handoff verdicts describe their own phase.

## Current verdict: READY for independent rereview

This revision addresses FR01 and FR02 from `implementation/claude-followups-review.md`. Author Step 1 readiness only: the prior REVISE review is not overwritten or claimed accepted. Unlimited user-authorized turn/dispatch budgets; this is turn 2 / dispatch 1, no nested dispatch and no completed workflow turn claimed.

### Revision mapping

| Finding | Change and evidence |
|---|---|
| FR01 / FU05–06 | `SloAgent._prepare_aborted_terminal` joins the retained bridge before trace persistence and publication. Both graph-read exception and normal available-item branches delegate to it; EOF with abort also goes through the barrier. Cleanup failure propagates as failure, not an aborted/completed success, retaining SDK ownership for explicit close retry. |
| FR01 exact-host-path regression | New `tests/bridges/claude/test_host_abort.py::test_available_tool_boundary_abort_joins_before_terminal[False,True]` enters real `SloAgentSession.invoke` → graph → bridge → real SDK/MCP, requests abort upon yielded `tool_call_start` with a pending native callback and graph updates still available, and holds transport close at an external barrier. Before release: no observable or persisted `run_aborted`, owner still live. Success: owner done/callbacks empty at terminal, exactly one persisted abort, no completion, no tool receipts, one query. Failure: unconfirmed-closure diagnostic, no abort/completion, same owner retained, admission refused, explicit cleanup retry joins, repeated close idempotent. Auth/native transport alone substituted; filesystem history is real under tmp_path. |
| FR02 | Scoped private operations in `bridge.py`: `_admit_response`, `_record_response_boundary`, `_record_tool_boundary`, `_record_terminal_context`, `_retain_unsent_audit_prefix`, shared detached `_record_live_context`, `_build_boundary_chunk`, `_finish_response_stream`. Stream retains async-generator/lifecycle ownership and delegates independent admission/history/conversion/cleanup policy. Fresh-message validation remains before the cleanup scope (invalid inputs do not newly seal admission). No wrapper class, SDK owner-task move, parser rewrite or unrelated refactor. |
| FU01–FU07 / E1–E4 preservation | Final feature gate reruns all prior 231 cases plus two FR01 journeys. Existing nine safe-retry cases (E1), history-off/compaction (E2), host-stop (E3), concurrent admission/auth closure (E4), native resume wiring/no replay, repeated/stale IDs, uncertain-write closure and parser repair remain passing. Prior detailed mapping below remains applicable; live-native transcript persistence is still unverified. |

### Exact revision receipts

CWD `/root/Code/claude-bridge/slo`. Commands use:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest ...
```

- RED before source fix: `-q tests/bridges/claude/test_host_abort.py --tb=short` — exit 1, **2 failed, 4 warnings, 2.20s**. Both failed because `terminal_observed` was set while cleanup was blocked. Assertion unwinding also produced a generator/context cleanup diagnostic; test now uses same-task `aclosing` to ensure clean teardown on assertion failure.
- GREEN after FR01: same command — exit 0, **2 passed, 5 warnings, 2.03s**.
- After FR02 extraction: `-q tests/bridges/claude tests/cli/test_claude_bridge.py --tb=short` — exit 0, **233 passed, 95 warnings, 12.07s**.
- Final gate after preserving pre-scope fresh validation and adding test generator teardown: same feature command — exit 0, **233 passed, 95 warnings, 10.76s**, no skips. Warnings are pythonjsonlogger/LangGraph/Pydantic deprecations.

### Scope, routing and review limits

Revalidated existing Python/asyncio/anyio/LangChain/LangGraph/official SDK routing; read checkout-vendored exact Code-Test-Review workflow, engineering routing/ownership/testing, coding rules/cadence/test policy, Python root and declarative/type/doc conventions. Existing host and SDK lifetime boundaries govern; no new app-service/HTTP/database/CLI architecture. Read README, local memory, KB entry and Slo index/gotchas, review and handoff. Plan: reproduce available-item abort → shared terminal barrier → scoped transitions → feature gate → source self-review and handoff.

Source self-review checked both abort publication sites, retained cleanup/error path, semantic prefix ordering and detached history, pre-admission validation placement, and test assertion/teardown boundaries. Changes this dispatch: `src/agents/slo_agent/agent.py`, `src/bridges/claude/bridge.py`, new `tests/bridges/claude/test_host_abort.py`, this handoff and durable local/KB notes. Existing unrelated dirty work preserved.

Only feature pytest was executed. No full suite, static/build tools, live external execution, commits, nested agents or detached workflows. Feature-only gate is the user's explicit authorization, not repository-wide regression certification. Actual native transcript persistence/resume and MCP parity remain unverified. Independent rereview and subsequent completion assessment are still required.
