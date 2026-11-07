# Implementation — control-only provider/tool phase owner

**Scope:** `src/agents/slo_agent/tool_execution/yield_policy.py` plus focused
tests. A.2 remains **PARTIAL / INCOMPLETE**; this is one bounded slice.

## Implemented

`ToolExecutionControl` now owns one loop-bound phase machine:
`idle/provider/tools/settling/yielding/settled/closed`.

| Operation | Current behavior |
|---|---|
| constructor | Binds source and deferred sink; creates one provider-exit Event; starts no tasks |
| `enter_provider` | Requires canonical attempt UUID, nonnegative iteration and idle/settled phase; captures cached delivery/high-water; retry from settled requires identical boundary and high-water; resets provider-exit |
| `reserve_provider_yield` | Compare-and-transitions provider → yielding only when `source.yield_is_requested(after_sequence=snapshot)`; false when tools/settling already won |
| `enter_tools` | Raises private `CooperativeProviderYield` while the exact reservation is active, before mutation/effects; validates distinct bounded IDs; sets provider-exit before any awaited effect |
| `enter_settling` | Tools → settling only |
| `settle_attempt` | Provider/yielding/settling → settled exactly once |
| `close` | Idempotent terminal close; never claims, clears or cancels queue state |
| `wait_for_yield` | Delegates to the source Condition with the captured high-water snapshot |
| `wait_for_provider_exit` | Returns once phase is no longer provider |
| `before_dispatch` | Pure decision over current group membership plus newer urgency; never claims input |

Cross-loop calls, invalid phases, duplicate settlement, invalid retry identity,
unknown/duplicate call IDs and closed reuse raise the fixed
`ToolYieldCapabilityError('tool_yield_capability_invalid')`.

## Deliberately missing (no claim)

- `ToolYieldPolicy`, `ToolCancellationPort`, invocation/registration/outcome
  DAOs, `mode_for`, `cancel_and_join`, cancellation acknowledgement matrix.
- `defer`, `CooperativeYieldMetadataDAO` emission/`on_deferred` use,
  `complete_provider_response`, `require_reserved_no_start`.
- Watchdog race/deadline reuse, executor guards, tool-node entry, agent/session
  binding, graph compilation, settlement/history integration, TUI activation.

## Test-first evidence

Path: `tests/agents/slo_agent/tool_execution/test_yield_control.py`.

The test uses a **typed recording source** implementing `AgentMessageSource`
(not a mock), injected through the constructor. It records high-water reads and
waits and refuses `take_one`/`commit_applied`, proving control observes urgency
without claims.

RED command (before production module):

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  /root/.pyenv/versions/slo-harness/bin/python -m pytest -p no:cacheprovider -q \
  tests/agents/slo_agent/tool_execution/test_yield_control.py
```

- RED: exit **2**, **1 collection error** (`ModuleNotFoundError` for the new
  module), 0 passed. Log `logs/turn8-dispatch4-control-red.log`.
- GREEN after implementation: exit **0**, **4 passed**, 2 warnings. Log
  `logs/turn8-dispatch4-control-green.log`.
- Focused tool-execution regression: exit **0**, **47 passed**, 5 warnings. Log
  `logs/turn8-dispatch4-control-regression.log`.
- Scoped Black check: exit **0** on both changed files.
- `git diff --check`: exit **0**.

## Gates / limitations

- Full non-E2E suite: **BLOCKED / UNRUN** — no exclusion, substitute or model
  evasion; no gate claimed.
- Full static gate: **UNRUN**. Mypy baseline is unestablished; no scoped mypy
  claim is made here.
- No executable fixtures, system/installer/package/infrastructure/git writes.
- Real `SessionMessageQueue` source injection was not used in this slice; the
  typed recording source is the approved injected-double form. A later journey
  slice must bind the control to the real session source.
