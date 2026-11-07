# 96.a.2 R2 repair — complete opening call array

**Status:** R2 repair complete for the restricted append-once port. R1 remains OPEN and was not changed. R3 code/tests were left as found. No class extraction and no fsync work in this dispatch.

- Checkout: `/root/Code/slo-message-queue/slo`; branch `message-queue`; HEAD `82c3f5c6de9345af34a673a3d975366ca8c1624c` (worktree stays dirty from prior work).
- Scope authority: `early-review-append.md` R2 only; spec §§4.3 and 6.2. No other report, doc or unrelated dirty file was edited.
- Ledger recorded as supplied: turn 5, this dispatch 5/20; prior partial-turn calls 7/4/4/8; 60-turn ceiling; 7 prior execution retries; no abort.

## Test-first evidence

Focused environment for every command below:

```bash
cd /root/Code/slo-message-queue/slo
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD" /root/.pyenv/versions/slo-harness/bin/python -m pytest -p no:cacheprovider -m 'not e2e' -q <files>
```

- Baseline before edits: `test_history_cooperative_append.py` — exit 0, **16 passed**, 1.71s.
- RED after adding the new parameterized case: exit 1, **2 failed / 16 passed**, 2.06s. Both adapters (`[False]`, `[True]`) failed at the new test because an opening with no `tool_calls` array was accepted and persisted.
- GREEN after implementation: same file — exit 0, **18 passed**, 1.79s.
- Focused pair (`…test_history_cooperative_append.py`, `history/test_settlement_failure.py`): exit 0, **21 passed**, 1.86s.
- Scoped regression (append, settlement, cooperative-yield metadata, reconciler, transcript, projector, tool-group metadata, provider settlement guard): exit 0, **137 passed**, 2.28s.
- Full non-e2e suite remains **BLOCKED** by the existing executable-fixture consent boundary. No exclusions, skips, xfails, substitutes or model substitution were used. No full static gate was run; a read-only `black --check` on the two touched files is clean for `dao.py` and reports only pre-existing formatting in the untracked test file (`_with_metadata_key` lines), not the added blocks.

## Fixture-chain audit

- `tests/conftest.py` autouse fixtures only redirect `SLO_HOME`/`HOME`/config into a pytest-owned temp root and stubs terminal/transport spawn; the `fake_herdr` fixture is not requested by this module and writes no executable.
- `tests/state_isolation.py` is imported at collection; no `chmod`, `bin/` creation, subprocess or fake executable runs for this module.
- The new test uses only real files under `tmp_path`, including the existing empty `events.jsonl`; it creates no executable, symlink, child PATH or subprocess. The sole consented deploy-worker temp `bin/curl` fixture was not exercised. No system path, package or infrastructure was touched.

## Implementation

`src/agents/slo_agent/history/dao.py` — `_validate_marked_tool_event` now calls `_validate_opening_call_array` for `tool_call` only. Admission requires:

1. non-empty `payload.tool_calls`;
2. ordered call IDs exactly equal to `group.tool_call_ids`;
3. every call carries a non-empty string `name` and a mapping `args`;
4. the selected call's `tool_name` and `tool_input` agree with its array entry.

Failures raise `ValueError`, translated by the existing port to `CooperativeYieldSettlementError`, so no raw line is appended. Result and `run_retrying` handling is unchanged. Sibling/cross-record completeness remains the planned raw-group owner (§6.3), not implemented here.

`tests/agents/slo_agent/messaging/test_history_cooperative_append.py` — positive fixture now builds the complete ordered array and selected `tool_input`; the success test asserts them. New two-adapter negative test covers missing, empty, reordered, truncated, malformed (missing name, non-mapping args), empty name, missing/mismatched `tool_input` and mismatched `tool_name`, then proves a complete opening still persists as sequence 1.

## Source identity / changed files

- `src/agents/slo_agent/history/dao.py` SHA-256 `86e72efc04db2730ba223d3d294f77596324bee8002f4d62d0e1d633b883a8f3`
- `tests/agents/slo_agent/messaging/test_history_cooperative_append.py` SHA-256 `82047139e18b9ce4bdd078243e43e6f731b2b97bc0af285ce37b1c489d767749`
- This report added. No commit, push, merge or PR.

## Remaining

- R1 (post-fsync re-certification) is still open; no fsync behavior was changed or claimed.
- §6.3 raw group validation, sibling agreement and cross-record completeness remain future work before producers activate.
- Independent final review and completion remain pending.
