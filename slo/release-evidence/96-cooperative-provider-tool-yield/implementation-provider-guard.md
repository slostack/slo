# 96.a.2 — provider settlement guard + strict live-guard corrections (bounded)

**Status:** READY for this bounded increment only. Not a completion, not a full
A12 claim, and not the whole feature. Full gate remains BLOCKED.
Retry 1 after a non-quota `OpenRouterAPIError`; no model fallback.
Baseline `message-queue` / `82c3f5c6de9345af34a673a3d975366ca8c1624c`.
Cwd for every command: `/root/Code/slo-message-queue/slo`.

## Scope delivered

- `src/agents/slo_agent/graph/service.py`: `_make_agent_node` now calls the
  existing `MessageContractReconciler.require_settled_live(messages=...)`
  immediately before **both** the direct and pool-bound provider calls. The
  call site is inside the provider node, after `SloAgent._inject_before_agent_turn_messages`
  has appended plugin context and before the first request.
- `src/agents/slo_agent/history/message_contract_reconciler.py`:
  - `_live_tool_call_id` now requires a mapping entry, nonblank `id`/`name`,
    and `args` that is a `Mapping`; partial or malformed argument structures
    are rejected.
  - `_settle_pending_result` now implements spec §6.1 literally: a result with
    a currently pending ID removes that ID once. Any blank/orphan/already
    settled ID is rejected.
- `tests/agents/slo_agent/history/test_message_contract_reconciler.py`: added
  the strict live-guard decision tests (from the prior RED state) and made the
  two malformed-argument tests isolate the structure check by supplying a
  matching result.
- `tests/agents/slo_agent/messaging/test_provider_settlement_guard.py` (new):
  real graph and real `SloAgentSession` journeys with an injected external
  provider double. The session test injects an orphan `ToolMessage` through a
  real `before_agent_turn` plugin and proves zero provider requests.

Out of scope and not claimed: yield policy/race, cancellation ports, watchdog
changes, history metadata, A12 capability identity/duplicate registration,
marked-group compaction, TUI activation, full A12.

## Source-backed decision: out-of-source-order results (spec §6.1)

Spec §6.1: "Track seen IDs across this provider context and pending IDs for
current group. `ToolMessage` requires nonblank pending ID and removes it once."
It does not require the result to be the first pending ID. §5.4/§9.1 put
source-ordered pairing of actual executor output under the executor/group
settlement owner (A3).

Decision: accept any result whose ID is pending; remove that ID once. Still
reject blank, orphan, duplicate/already-settled, interleaved and missing
results. The pre-existing RED test
`test_live_guard_accepts_result_order_not_matching_call_order` already encoded
this reading; no assertion was weakened. Executor source ordering remains an
executor obligation.

## RED/GREEN receipts

### RED 1 (before production changes)

```bash
cd /root/Code/slo-message-queue/slo
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo \
  SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 \
  SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked \
  COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' \
  tests/agents/slo_agent/history/test_message_contract_reconciler.py \
  tests/agents/slo_agent/messaging/test_provider_settlement_guard.py \
  tests/agents/slo_agent/test_graph.py
```

Result: **3 failed, 56 passed**. Failures: out-of-order acceptance, graph
provider block, session plugin provider block.

The `non_mapping_args` test passed for the wrong reason (the open group had no
result, so the end-of-list check fired). It was strengthened with a matching
`ToolMessage`; RED 2 then exposed the real failure.

### RED 2 (isolating the malformed-args check)

Same environment and command, reconciler + new provider-guard tests only:
**4 failed, 26 passed**.

### GREEN (focused)

Same environment and command as RED 1, after implementation:
**59 passed, 11 warnings** in 2.12s.

### Normal real journey regression

```bash
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' \
  tests/agents/slo_agent/messaging/test_delivery.py \
  tests/agents/slo_agent/history/test_projector.py
```

Result: **122 passed, 315 warnings**, 66.97s. This is the real normal
tool/client/session/SQLite/history journey and projector, not a substitute for
the blocked full gate.

### Agent / recovery / plugin wiring regression

```bash
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' \
  tests/agents/slo_agent/test_agent.py \
  tests/agents/slo_agent/test_agent_recovery.py \
  tests/agents/slo_agent/plugins/test_session_wiring_e2e.py
```

Result: **90 passed, 51 warnings**, 7.66s.

An earlier attempt at this command hit a **collection error** caused by a
module-level import of the history package from `graph/service.py`
(`graph → history → compaction → graph`). The import was moved into
`_make_agent_node` (executed after the graph package is initialized), with a
comment explaining the cycle. The command above is the post-fix run.

### Static (scoped)

```bash
poetry run black --check \
  src/agents/slo_agent/history/message_contract_reconciler.py \
  src/agents/slo_agent/graph/service.py \
  tests/agents/slo_agent/history/test_message_contract_reconciler.py \
  tests/agents/slo_agent/messaging/test_provider_settlement_guard.py
# 4 files would be left unchanged

poetry run mypy \
  src/agents/slo_agent/history/message_contract_reconciler.py \
  src/agents/slo_agent/graph/service.py
# Success: no issues found in 2 source files
```

Full `make test PYTEST_WORKERS=6`, `make lint`, and full Black are **BLOCKED /
UNVERIFIED** by the documented executable-fixture consent gap. No exclusion,
re-mark, or focused total is offered as a substitute.

## Fixture/safety audit for tests actually run

- `tests/agents/slo_agent/history/test_message_contract_reconciler.py`: pure
  in-memory messages; no writes, subprocess, chmod, or executable.
- `tests/agents/slo_agent/messaging/test_provider_settlement_guard.py`: writes
  one regular Python plugin source below `tmp_path`; no executable, chmod,
  subprocess, or PATH mutation. Provider double subclasses `FauxChatModel`;
  no private method patching.
- `tests/agents/slo_agent/test_graph.py`: in-memory graphs plus `tmp_path`
  writes for tool-output tests; audited grep found no executable fixtures.
- `tests/agents/slo_agent/messaging/test_delivery.py`: `tmp_path` history/
  SQLite only; no executable fixture (previously audited, rechecked).
- `tests/agents/slo_agent/history/test_projector.py`: same audit.
- `tests/agents/slo_agent/test_agent.py`,
  `tests/agents/slo_agent/test_agent_recovery.py`,
  `tests/agents/slo_agent/plugins/test_session_wiring_e2e.py`: audited grep
  found no executable fixtures. The e2e test writes only Python plugin sources
  below `tmp_path`.
- Autouse `isolated_slo_home` writes only pytest temp directories; `fake_herdr`
  is opt-in and was not requested.

No executable artifact was created or modified. No system path was touched.

## A12 disposition

Closed by this increment only:

- provider-node integration of the strict live guard for direct and pool paths,
  after before-agent plugin messages;
- malformed/non-mapping `args` and partial tool-call structures rejected;
- matching pending results removed once, independent of source order.

Still open (not claimed): capability identity by original tool object/exact
invocation task, duplicate registration/illegal transition errors, result-status
retention through replay metadata, marked-group compaction atomicity, and the
full A12 matrix.

## Accounting

- Workflow turn 1 started, 0 completed; 60-turn limit.
- This is dispatch 6 of 20.
- Provider-guard execution: initial attempt failed on a non-quota
  `OpenRouterAPIError`; this is retry 1 of 3. No abort was retried.
- Separate prior audit/handoff retry: 1 (not counted here).
- Model: primary DeepSeek; no fallback. No nested agents, commit, push, merge,
  or PR.

## Remaining before acceptance

1. Independent read-only **early review** (`gpt-6.1-sol` high) after this
   increment; not performed in this dispatch and not replaced by author checks.
2. Later independent **final review** and **completion** (`gpt-6.1-sol` high).
3. Full non-E2E suite remains BLOCKED pending executable-fixture consent.
4. Full static baseline remains unverified.
5. Remaining A12 and the rest of A.2 (yield policy/race, history metadata,
   TUI) are not implemented.

## Preservation

- Pre-existing dirty `slo/SLO.md`, untracked `slo/docs/`, and prior
  durable-composer evidence untouched.
- `preflight-blocker.md` byte-preserved:
  `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`.
- `routing.md` and `acceptance.md` unchanged.
