# 96.a.2 repair cutoff — ER-01/03/04 (retry 2)

**Status:** bounded repair READY. Not a completion, not full A12, not an early/final
review substitute. Full `make test PYTEST_WORKERS=6` remains **BLOCKED/UNRUN**;
full static baseline remains **UNRUN**. No commit, push, merge, PR or nested agent.

- Repo/cwd: `/root/Code/slo-message-queue/slo`; branch `message-queue`;
  baseline `82c3f5c6de9345af34a673a3d975366ca8c1624c` unchanged.
- Counter state: turn 2 partial; dispatch 3/20 this turn; turn 1 had 7 calls;
  60-turn limit. Repair retry **2 of 3** (initial + retry-1 both ended in generic
  non-quota `OpenRouterAPIError`); previous audit retry 1, provider-guard retry 1.
  No abort was retried.
- Model: primary assigned DeepSeek at default reasoning; no fallback invoked.

## Repairs

### ER-01 — terminal settlement failure before generic classification

One predicate, `is_settlement_failure(*, exc)`, now lives in
`history/message_contract_reconciler.py` beside `UnsettledToolGroupError`. Future
`CooperativeYieldSettlementError` joins that predicate when introduced.

- `agent.py::_execute_iteration_with_retry` re-raises a settlement failure before
  stream recovery, rate retry, partial-output checks or provider classification.
- `agent.py::_decide_iteration_recovery` returns `RecoveryClass.FATAL` before the
  OpenRouter partial-output branch and before any injected recovery policy.
- `sessions/service.py::_derive_next_attempt_plan` returns `None` before reconnect,
  continuation and overflow-compaction planners.

Legitimate provider recovery, retry budgets and compaction are unchanged. A
permissive injected retry/recovery policy is never asked about settlement.

### ER-03 — proof hardening

- Reconciler non-mutation now compares detached JSON snapshots across success and
  rejection, covering result `status` and call arguments.
- Provider double counts both external entry modes (`_agenerate`, `_astream`) and
  the positive settled-pool case; the mode test now has a positive request assertion.
- New real messaging journey: plugin-injected orphan result → real
  `LocalSessionMessagingClient` route → real scheduler/agent/graph guard → real
  SQLite and flat history. Public stream and readback prove one `run_started`,
  one `run_failed`, no recovery/reconnect/compaction event, one applied identity,
  zero provider calls and exactly one before-agent iteration.
- The earlier session test was nonmessaging and history-disabled; it was transient
  first-path evidence only. The durable claim is now backed by this new journey.

### ER-04 — malformed outer call container

`_open_live_group` rejects a non-list `tool_calls` container with
`UnsettledToolGroupError` before iteration. `None` remains the supported empty
case; `{}`, `0`, and truthy non-iterables no longer collapse or leak `TypeError`.

## Exact RED receipt (checks temporarily removed, then restored)

Command: focused six tests, same env as GREEN, `-m 'not e2e'`.

Result: **5 failed, 1 passed**. Failed: both malformed-outer-container tests,
agent permissive retry/recovery bypass, session planner bypass, real messaging
journey. The detached-snapshot regression test passed pre-fix (it guards mutation,
not the missing decision) and is deliberately not counted as a RED decision.

## Exact GREEN receipts

Environment for every run (same binary as Poetry):

```bash
cd /root/Code/slo-message-queue/slo
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo \
  SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 \
  SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked \
  COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
```

| Gate | Scope | Result |
|---|---|---|
| Focused GREEN | reconciler + provider guard + graph | **67 passed**, 2.25s |
| Regression | delivery + agent recovery + agent + session wiring | **194 passed**, 73.66s |
| Black scoped | 3 sources + 2 test files | 5 files unchanged |
| mypy scoped | `message_contract_reconciler.py` | success, no issues |
| mypy 3 sources | reconciler + agent + session | baseline `PyYAML` stub error in `skills/service.py`, not introduced by this diff |
| Full `make test PYTEST_WORKERS=6` | — | **BLOCKED / UNRUN** |
| Full `make lint` / full Black | — | **UNRUN** |

## Fixture / safety audit

The new journey writes only a regular Python plugin source, an iteration counter,
SQLite and flat history below `tmp_path`. No chmod, subprocess, PATH mutation,
executable fixture, `fake_herdr`, system path or package change. Other executed
modules are the previously audited delivery/agent/history suites. The only
authorized executable exception remains `tests/cli/test_deploy_install_worker.py`
and was not run or broadened here.

## Preservation

Pre-existing dirty `slo/SLO.md`, untracked `slo/docs/`, routing/acceptance,
`preflight-blocker.md` and prior evidence were not modified. No `RESEARCH.md` was
created (read-only absence noted).
