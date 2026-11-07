# Implementation — watchdog closed read outcome (96.A.2)

## Slice

Turn 8 / dispatch 5/20. Bounded `GraphReadOutcomeDAO` + legacy consumer
migration only. A.2 remains **PARTIAL / INCOMPLETE**.

## Changes

- `src/agents/slo_agent/watchdog_timer.py`
  - Added strict/frozen/`extra='forbid'` Pydantic `GraphReadOutcomeDAO` with
    `kind: Literal['item','end','yield']`, `item: Optional[object]`,
    `settled_item: Optional[object]`, `has_settled_item: bool=False`.
  - Validator raises `graph_read_outcome_invalid` for: payload on end/yield,
    settled item/flag on item/end, and a settled item without the presence flag.
    `kind='item', item=None` remains a valid framework item, distinct from end.
  - `WatchDogTimer.invoke` now returns the closed outcome: `item` for a graph
    item, `end` for `StopAsyncIteration`/normal exhaustion. First-progress,
    idle and local-tool deadline semantics are unchanged.
  - Public `invoke` signature is unchanged; no optional control/abort argument
    and no yield race were added in this slice.
- `src/agents/slo_agent/agent.py`
  - `_stream_graph_turn` consumes `outcome.kind` explicitly: `end` returns,
    non-item/non-end is rejected as `graph_read_outcome_invalid`, and `item`
    payloads continue through the existing parser/abort/tool-output path.
    No raw `None` sentinel branch remains.
- Tests
  - New `tests/agents/slo_agent/test_graph_read_outcome.py`: framework-None item,
    normal end, yield with settled None/value, seven invalid combinations,
    unknown kind, extra field and frozen mutation.
  - Migrated `tests/agents/slo_agent/test_watchdog_timer.py` to assert
    `kind`/`item`/`end`; all prior timeout and tool-suspension assertions kept.
  - No existing parser signature changed and no parser test needed migration;
    the agent is the sole direct watchdog caller.

Not implemented / not claimed: yield activation, control/abort parameters,
watchdog urgency race, cancellation acknowledgement, executor/tool-node guards,
history settlement, TUI or any other A.2 subset.

## Evidence

Cwd `/root/Code/slo-message-queue/slo`; baseline
`82c3f5c6de9345af34a673a3d975366ca8c1624c`;
`PYTHONDONTWRITEBYTECODE=1 SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD"`;
runner `poetry run pytest ... -p no:cacheprovider`.

| Gate | Command (paths abbreviated to changed files) | Exit | Result |
|---|---|---|---|
| RED | `pytest -q tests/agents/slo_agent/test_graph_read_outcome.py` | 2 | 1 collection ImportError, 0 passed |
| GREEN | `pytest -q test_graph_read_outcome.py test_watchdog_timer.py` | 0 | 19 passed |
| Regression | `pytest -q` outcome + watchdog + parser + graph + agent/recovery/runtime/streaming/usage/image tests | 0 | 190 passed |
| Black | `black --check` watchdog, agent, both watchdog tests | 0 | 4 unchanged |
| mypy | `mypy` the same 4 files | 0 | Success, no issues |
| Diff | `git diff --check` | 0 | clean |

Raw logs: `logs/turn8-dispatch5-outcome-{red,green,green2,regression,regression2,black,black2,mypy,mypy2,diffcheck}.log`.

Final hashes: watchdog `d00df140…`, agent `6c4f74f8…`, new outcome test
`08b1d1b6…`, migrated watchdog test `877ba939…`.

## Limits

Full `make test PYTEST_WORKERS=6` remains **BLOCKED** (other fixture consent);
no execution, exclusion or substitute is claimed. Full static remains **UNRUN**
and the mypy baseline is unestablished; only scoped mypy is claimed. No
executable/system/worker/fixture/package/infrastructure or git write occurred.
Independent early urgent review, final review and completion remain pending.
