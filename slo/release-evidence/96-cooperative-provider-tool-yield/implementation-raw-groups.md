# Implementation — T1 raw marked tool-group validation (first slice)

**Status:** bounded first slice implemented and focused-green. **A.2 remains PARTIAL / INCOMPLETE.**
No producer activation, startup-readiness wiring, compaction barrier, provider race, tools
policy, TUI activation, final review or completion is claimed.

Baseline `82c3f5c6de9345af34a673a3d975366ca8c1624c`, repo `message-queue`,
application root `/root/Code/slo-message-queue/slo`.

## Scope delivered

Spec `96.a.2` §§6.1/6.3 and acceptance A8/A9/A12 raw-history obligations:

- `SessionHistoryProjector.validate_tool_groups(*, events) -> list[SessionHistoryEventDAO]`
  exists with the exact public signature and is called at the head of
  `_context_event_slice`, so both `context_events` and `build_message_history`
  validate raw active marked groups before completed-turn, excluded-turn,
  compaction-summary selection or historical healing.
- Validation is delegated to the existing `CooperativeHistoryEventValidator` for
  per-record admission shape: marker discrimination, known schema version,
  deterministic UUID5 event identity, turn/iteration/group correlation, ordered
  opening call array and selected call agreement.
- A private `_RawToolGroupState` accumulates each `tool_group_v1` group across
  raw pages and owns cross-record invariants:
  - identical attempt/iteration/group identity and `opened_at` across all records;
  - one complete ordered opening per declared call, agreeing arguments and
    assistant content across openings;
  - exactly one actual result per declared call with retained core status;
  - no duplicate opening/result/marker and no undeclared/extra result;
  - no marker together with any actual result;
  - marker requires the first declared call's full opening anchor and must follow
    that opening; partial sibling openings are otherwise allowed;
  - without a marker, every declared call needs both opening and result, so a
    missing member or marker-without-anchor fails closed.
- Proven no-start groups return the same event list minus exactly that group's
  opening/private-anchor events. Other messages and other groups in the attempt
  remain. The marker itself remains an audit `run_retrying` event and projects to
  `None`.
- Unmarked legacy `tool_call`/`tool_result` events are untouched and still use the
  existing historical `MessageContractReconciler` healing path. No fake
  `ToolMessage` is created for a marked unresolved group: validation raises
  `UnsettledToolGroupError` before projection/healing.

## Test-first chronology

1. New file `tests/agents/slo_agent/history/test_projector_tool_groups.py` was
   written first and run against the baseline method absence:
   **RED exit 1, 19 failed**, `logs/turn7-raw-groups-red.log`.
2. Implementation added; first focused GREEN 19 passed.
3. A refinement proof for a no-start marker with only a secondary (non-anchor)
   opening was added and failed first:
   **RED exit 1, 2 failed**, `logs/turn7-raw-groups-anchor-red.log`.
4. Anchor requirement added; final focused + affected regression run:
   **GREEN exit 0, 136 passed**, `logs/turn7-raw-groups-green.log`.
   That total is 21 new cases plus 115 existing projector/reconciler/transcript/
   metadata cases. It is not a suite total.
5. Additional affected store regression (cooperative append, message application,
   flat store, tree store, flat compaction, compaction transaction):
   **exit 0, 100 passed**, `logs/turn7-raw-groups-store-regression.log`.

Both real adapters are exercised by the new proofs. Settled, no-start, missing
result, marker-with-result, marker-without-anchor, conflicting-array, extra-result,
unknown-version and legacy-healing cases write/read real temporary JSONL through
`FilesystemSessionHistoryStore` and `TreeBasedFilesystemSessionHistoryStore`, using
`application_evidence` pages of size 1, 2 and 256 for the settled case. No private
method patching, no mocks, no harness.

## Evidence

| Item | Value |
|---|---|
| RED command | `PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' -q tests/agents/slo_agent/history/test_projector_tool_groups.py` |
| RED result | exit 1, 19 failed, 0 passed, 2 warnings |
| Anchor RED | exit 1, 2 failed, 19 deselected |
| GREEN command | same runner over the new file + `test_projector.py`, `test_projector_compaction.py`, `test_projector_recovery.py`, `test_message_contract_reconciler.py`, `test_transcript.py`, `test_cooperative_yield_metadata.py` |
| GREEN result | exit 0, 136 passed, 2 warnings; additional store regression exit 0, 100 passed |
| Static | scoped Black `--check` exit 0; mypy on `projector.py` exit 0 |
| Raw logs | `logs/turn7-raw-groups-{red,anchor-red,green,store-regression,static,receipts}.log` |
| Source hash | `3ca5d773eb8dae4ddb9f812fd9e584e7c60f33a86ec779cf3ecd988f43eb5a9f` |
| Test hash | `51f4bf66cfee0acf208addefce6c89f2b8979991e4bd4ddead242dde58dff415` |

Environment for every run: `SLO_ENV=test`, `SLO_ROOT_DIR=$PWD`, `SLO_APP_DIR=$PWD`,
`SLO_APP_NAME=slo`, `SLO_LOG_FORMAT=text`, `SLO_DEFAULT_MODEL_NAME=gpt-5.4`,
`SLO_AUTO_VISUALIZE=0`, `SLO_HERDR_DISABLED=1`,
`SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked`, `COLUMNS=120`,
`LINES=40`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=$PWD`, cwd application root.

## Still open

- Startup/readiness must read every `application_evidence` page under the
  ownership/history barrier and call this validator once over the assembled raw
  events before readiness. That wiring is **not** done in this slice.
- Compaction validation before select/write/remove is **not** wired; the shared
  context slice protects projection but not the compaction writer.
- Interrupted provider-context exclusion (§6.4.5) is **not** in this slice.
- Producers, T2 provider control/race/cleanup, tools policy, TUI activation,
  full A1–A14, final review and completion remain pending.
- `make test PYTEST_WORKERS=6` remains **BLOCKED** by executable-fixture consent;
  full static is **UNRUN**; YAML-stub baseline remains **UNESTABLISHED**.
- Counters preserved: turn 7, this dispatch 1/20 (prior partial calls
  7/4/4/8/8), 60-turn ceiling, ten prior execution retries, no abort retried.
  No commit, push, merge, PR, nested agent, package, system, installer or
  executable mutation.
