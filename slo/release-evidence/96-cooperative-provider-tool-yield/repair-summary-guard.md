# RH3 — compaction validates raw before the summary provider

**Scope:** 96.a.2 §6.3.1/3/5, A8/A12. A.2 remains **PARTIAL / INCOMPLETE**.

## Repair

- `compaction/compacter.py` — `compact()` now calls
  `SessionHistoryProjector.validate_tool_groups(events=events)` **first**, before
  `_find_cut_point`, capping, rendering or `_invoke_llm_summary`. Unresolved,
  duplicated or conflicting raw groups raise `UnsettledToolGroupError` with zero
  summary-provider requests. The summary model context is rendered from the
  validated list (proven no-start openings/private anchors removed), while the
  cut, `first_kept_entry_id`, `cut_point_entry_id` and token accounting stay
  pinned to the **original raw snapshot** handed to activation.
- `compaction/compacter.py` — `has_viable_cut_point()` returns `False` for raw
  evidence that fails group validation (fail closed, no selection).
- `sessions/service.py` — manual entry `_compact_context_locked()` validates raw
  groups before viability selection and returns `status="failed"` with
  `session history has an unresolved tool group; nothing was compacted`
  (logged `manual_compaction_unresolved_tool_group`). Automatic pre-startup
  path (`_run_compaction_if_needed`) propagates the error to its existing
  handler; no summary write or provider request occurs.

Disposed-group content cannot return through the summary: the opening events
carrying `tool_input` and the no-start marker are omitted from the request text,
while the user/assistant and settled-turn content remain. Group-atomic
truncation is unchanged.

## Test-first evidence (real session entries, real flat/tree adapters, injected provider capture)

New `tests/agents/slo_agent/history/test_compaction_summary_guard.py` composes a
real `SloAgentSession` over a real `FilesystemSessionHistoryStore` or
`TreeBasedFilesystemSessionHistoryStore` and an injected
`CapturingSummaryProvider` (external summary-provider double). No store is
mocked, no private collaborator patched.

| Journey | Assertion |
|---|---|
| manual `compact_context()` over unresolved opening | `failed`; 0 provider requests; active log byte-identical; opening retained; no `compaction_summary` |
| automatic `_run_compaction_if_needed(force=False)` threshold crossing over unresolved opening | raises `UnsettledToolGroupError`; 0 requests; log byte-identical |
| manual compaction over proven no-start group in the prefix | `compacted`; exactly 1 request; no `disposed-a.txt` / `tool_call [read]` in request; user + assistant settled content present; group removed whole; `first_kept_entry_id` is a raw id; retained turn reaches model context |
| `Compacter.compact` direct | raises before cut selection; 0 requests; `has_viable_cut_point` is `False` |

Commands (cwd `/root/Code/slo-message-queue/slo`, `PYTHONDONTWRITEBYTECODE=1`,
Poetry env Python 3.11.7):

- RED (`logs/turn7-rh3-red.log`): `pytest tests/agents/slo_agent/history/test_compaction_summary_guard.py -p no:randomly -q` → **exit 1, 8 failed, 0 passed**.
- GREEN (`logs/turn7-rh3-green.log`): same → **exit 0, 8 passed**.
- Focused regression (`logs/turn7-rh3-regression.log`): `pytest tests/agents/slo_agent/compaction tests/agents/slo_agent/test_session_compaction_integration.py tests/agents/slo_agent/test_session_history.py tests/agents/slo_agent/history tests/agents/slo_agent/messaging/test_startup_raw_tool_groups.py tests/agents/slo_agent/messaging/test_history_cooperative_append.py -p no:randomly -q` → **exit 0, 592 passed**.
- `black --check` on both changed source files and the new test: clean after formatting; `mypy src/agents/slo_agent/compaction/compacter.py` → `Success`; `git diff --check` → exit 0.

Hashes at GREEN: compacter `93cb28cd3afa3e371774f3cd43998bf62dcb250d076dd13b0e761351579ce012`,
session service `7ba507fc250e6a9da3d4b721827bc047f7ff953485585ea2bee7182ad62c90e2`,
new test `025eb02fddfe5ecc0bd9a237e72e778c6693349fba5253b34d5beb4b8ede977f`.

## Not done

RH4 direct/compatibility rewrite validation remains **open** and is the next
task (`filesystem_store.py` direct `compact_to_boundary` without
`messaging_compaction_id` and `truncate_to_compaction_boundary`,
`tree_store.py` delegation, unchecked session nonmessaging branch). T2 provider
race/control/cleanup, §6.4.5 interrupted context, full acceptance, independent
final review and completion are untouched. `make test PYTEST_WORKERS=6` remains
BLOCKED; full static and YAML baseline unchanged.
