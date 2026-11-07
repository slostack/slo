# Repair Marker — R3 only

**Status:** R3 repaired and focused-verified. A.2 remains PARTIAL/INCOMPLETE.
R1 (fsync) and R2 (full raw-array validation) remain OPEN. No class extraction,
no R1/R2 work, no completion claim.

## Finding addressed

R3: cooperative marker discrimination was asymmetric. `tool_call`/`tool_result`
inspected only `tool_group_v1`, so a misplaced or conflicting
`cooperative_yield_v1` (including `null` or schema 2) passed. The no-start
`run_retrying` fixture carried no canonical outer `reason`.

## Test-first chronology

1. Updated the positive no-start fixture to the existing payload shape:
   `payload.metadata = {"tool_group_v1": {... "disposition": "not_started"}, "reason": "cooperative_yield"}`.
2. Added `test_cooperative_append_once_rejects_misplaced_and_conflicting_markers`
   (both adapters). It rejects:
   - `tool_call` + `cooperative_yield_v1=None`
   - `tool_result` + `cooperative_yield_v1={"schema_version": 2}`
   - no-start `run_retrying` + `cooperative_yield_v1=None` second marker
   - no-start without `metadata["reason"]`
   - no-start with `metadata["reason"] != "cooperative_yield"`
   Each refusal must add no raw line; a following valid event must become
   sequence 2 (no cursor advance).
3. RED: `logs/turn5-r3-append-red.log` — exit 1, 4 failed / 12 passed.
4. Implemented the smallest owner-local change in
   `history/dao.py::validate_cooperative_history_event` /
   `_validate_marked_tool_event` / `_validate_no_start_event`.
5. GREEN: `logs/turn5-r3-append-green.log` — exit 0, 16 passed / 0 failed.

## Exact focused command

```bash
cd /root/Code/slo-message-queue/slo
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' \
  tests/agents/slo_agent/messaging/test_history_cooperative_append.py -q
```

Interpreter: `slo-harness` 3.11.7 and Poetry resolve to the same CPython
3.11.7 binary. Fixture chain remains temp-root only; no executable created or
mutated. `make test PYTEST_WORKERS=6`, full static, lint and Black remain
**BLOCKED/unestablished** and were not run or substituted.

## Changed files

- `src/agents/slo_agent/history/dao.py` — reject any known second marker on
  marked tool events; centralize known-marker/kind discrimination; require
  `payload.metadata["reason"] == "cooperative_yield"` for no-start.
- `tests/agents/slo_agent/messaging/test_history_cooperative_append.py` —
  positive no-start fixture shape plus both-adapter rejection/readback proof.

Final source hashes are recorded in `logs/turn5-r3-append-green.log`.
