# T5 attention composed continuation 50 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 50, retries 0. Unlimited turns and dispatches; no agents dispatched. No workflow acceptance or finite-family READY claim. This report does not update shared status.

## Changed scope

Added only `tests/agents/slo_agent/herdr/test_attention_compaction_composed.py` plus this report and its own receipts. No production changes, no agent.py or parallel usage-test changes, no shared-status/spec/global/live/other-worktree/git lifecycle changes. Existing partial changes retained.

The added three cases execute `compact_context` with a real FilesystemSessionHistoryStore, persisted viable input, actual SloAgent built with an explicit fully scripted FauxChatModel, and a failure/cancellation injected at FauxChatModel.ainvoke. They do not replace the manual pipeline or history owner. Reporter publish is intercepted: no real Herdr activation or terminal. Root test isolation/terminal/fake-Herdr capability guards remain in force.

Assertions cover:
- failure yields the established failed result and exactly one durable run_failed audit after the unchanged seeded events;
- cancellation preserves the original exception identity and seeded events without adding a failure audit;
- held-lock refusal never calls summary or usage and allocates no operation;
- accepted manual work allocates exactly one operation, remains working through actual shared refresh_usage_snapshot (spy delegates to original), publishes settled blocked/idle afterward, retires its token and releases its lock.

This is a persisted manual failure/cancellation/refusal proof, not a successful rewrite/rollback proof or native-restore proof. Injected agent eligibility is not claimed as restore eligibility. No separate accounting was added.

## Actual receipts

CWD: `/root/Code/slo-94-herdr-integration/slo`. Every pytest run uses approved `bash docs/implementation/94-herdr/t1-dao-check.sh <paths>` with its existing safe fallback and automatic DAO/projection partition. No venv creation. Prefix below is `docs/implementation/94-herdr/t5-attention-compose-50-`; matching .exit files retain real status.

| Receipt | Result | Meaning |
|---|---|---|
| manual.log | 2 failed, 63 passed; exit 1 | Fixture omitted enable_history=True. Not a product RED. |
| manual-green.log | 169 passed, 66 warnings; exit 0 | Corrected fixture plus attention and manual-compaction surrounding tests. |
| order.log | 2 failed, 167 passed; exit 1 | Stronger publication ordering probe used noncanonical identity; projector correctly refused it. Not a product RED. |
| order-green.log | 169 passed, 66 warnings; exit 0 | Canonical UUID threaded through persisted events and session; actual reporter handoff now observed. |
| surrounding.log | 1777 passed, 119 warnings; exit 0 | Post-format entire Herdr, session, usage, rate_limits, manual_compaction, agent and tests/auth. |
| black.log / black-check.log | exit 0 | Only added test formatted/checked. |
| diff-check.log | silent; exit 0 | Worktree diff whitespace check. |
| coreutils.log | silent; exit 0 | dpkg -V coreutils. |

Exact surrounding arguments:

```text
tests/agents/slo_agent/herdr tests/agents/slo_agent/test_session.py tests/agents/slo_agent/test_session_usage.py tests/agents/slo_agent/test_session_rate_limits.py tests/agents/slo_agent/test_session_manual_compaction.py tests/agents/slo_agent/test_agent.py tests/auth
```

No failing production behavior was established or changed in this continuation. Initial red fixtures are not represented as causal regression fixes. Existing 49 evidence remains historical; 1777 is a fresh surrounding receipt, not a complete-suite receipt or proof that the parallel usage lane is accepted.

## Finite branch map and remaining work

| Family | Status |
|---|---|
| Seven original failures / real tool-flow usage matrix | Prior 49 evidence retained; surrounding remains green. Parallel usage owner controls further accounting closure. |
| Actual persisted manual failure/cancel/busy refusal | Three new passing cases above; bounded closure for these outcomes and usage-before-settlement. |
| Authentication selection / preparation races / error audit | OPEN: no new composed proof here. Existing helper/startup coverage remains green, not substituted for end-to-end evidence. |
| Actual pool fallback / route observer forbidden-I/O and faults | OPEN: no new composed proof here. |
| Retry / recovery / passive cooldown / abort / cancellation continuity | OPEN: no new composed matrix here. |
| Partial-stream/eventless usage | Parallel lane, not owned or accepted by this report. |
| Required normative read closure | OPEN, details below. |
| Full make test / smoke / static integration | NOT RUN: both lanes' integration closure is not established. Prior 299 errors / 63 files remains unwaived; no new ignore added. |

## Read evidence and limits

Read current t5-attention-49.md and routing.md; actual manual pipeline, projector identity guard, Faux implementation, existing attention tests, manual tests and root isolation fixtures. Read canonical C7.10 directly. Project AGENTS/CLAUDE/docs RESEARCH were supplied in session context. Read shared engineering ownership/testing/routing, coding rules/code-test-loop, Python root/declarative and application-service guidance. Consulted KB Welcome, slo README and gotchas. One combined skills/KB tool output truncated its beginning; engineering-routing was subsequently read separately. No blanket read-closure claim is made.

Still required before family READY: full relevant C7.9/7.11/section 8, B snapshot contract, exact T5 tasks and accepted reviews; scope-plan/current status reconciliation; remaining routed build/declarative/DAO/workflow skill and root RESEARCH/build-file reads. The outstanding normative work and composed matrices prevent READY. There is no asserted dispatch/turn/unit limit and no independent review or completion verdict.
