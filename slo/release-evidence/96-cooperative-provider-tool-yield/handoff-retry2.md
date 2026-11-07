# 96.a.2 handoff — retry-2 settlement cutoff repair

## Verdict

**READY for the bounded ER-01/03/04 repair only.** Provider settlement failure is
terminal before generic retry/recovery/planner classification; malformed outer
call containers raise the fixed error; proof gaps are closed at the contract and
journey levels. Not a completion, not full A12, not a workflow-turn completion.

## Accounting

| Item | Value |
|---|---|
| Repo/branch | `/root/Code/slo-message-queue/slo` / `message-queue` |
| Baseline | `82c3f5c6de9345af34a673a3d975366ca8c1624c` |
| Workflow turns | turn 2 partial; turn 1 partial (7 calls); 60-turn limit |
| Dispatch | 3/20 this turn |
| Repair retry | 2 of 3; initial + retry-1 failed on generic non-quota `OpenRouterAPIError` |
| Prior retries | audit 1, provider-guard 1; no retry of an abort |
| Model | primary DeepSeek default reasoning; no fallback |
| Commit/push/merge/PR/nested agents | none |

## Changed files

- `src/agents/slo_agent/history/message_contract_reconciler.py` —
  `is_settlement_failure`, outer `tool_calls` container rejection.
- `src/agents/slo_agent/agent.py` — terminal cutoff in
  `_execute_iteration_with_retry` and `_decide_iteration_recovery`.
- `src/agents/slo_agent/sessions/service.py` — terminal cutoff in
  `_derive_next_attempt_plan`.
- `tests/agents/slo_agent/history/test_message_contract_reconciler.py` — detached
  snapshot proof, malformed outer-container decisions.
- `tests/agents/slo_agent/messaging/test_provider_settlement_guard.py` — completed
  both-mode recorder, agent permissive-policy bypass, planner bypass, real
  messaging client/session/SQLite/history journey.

## Evidence

| Gate | Command scope | Result |
|---|---|---|
| RED | 6 new decision tests with checks removed | **5 failed, 1 passed** |
| GREEN focused | reconciler + provider guard + graph | **67 passed**, 2.25s |
| Regression | delivery + agent recovery + agent + session wiring | **194 passed**, 73.66s |
| Black scoped | 5 changed files | unchanged |
| mypy scoped | reconciler | clean |
| mypy 3 sources | reconciler + agent + session | baseline PyYAML stub error, not introduced |
| Full `make test PYTEST_WORKERS=6` | — | **BLOCKED / UNRUN** |
| Full lint / Black | — | **UNRUN** |

The earlier session test (nonmessaging, history-disabled) is not durable evidence;
it was transient. The new journey uses `session.invoke` through the real local
client/scheduler with `enable_history=True`, and reads back both flat history and
the SQLite identity receipt.

## Remaining gates

1. Independent early review of this repair (`gpt-6.1-sol` high, read-only, no
   tests) is still required; this handoff does not claim it.
2. Independent final review and completion remain later, separate gates.
3. Full non-E2E suite is BLOCKED pending the named executable-fixture consent; no
   run, exclusion, waiver or substitute total was used.
4. Remaining A.2 yield/race/history/TUI work is untouched.

## Preservation

`slo/SLO.md`, `slo/docs/`, `routing.md`, `acceptance.md`,
`preflight-blocker.md`, prior reports and `current-handoff.md` were not modified.
`fake_herdr`, installer fixtures and system/package operations were not used.
