# 96.a.2 — ER3 cooperative admission owner repair

**Status:** ER3 (mandatory class-owner extraction) is closed at the focused and
audited-chain level. This is a behavior-preserving ownership refactor, not a new
behavior change. ER1/ER2 remain fixed as recorded in
`repair-certification-order.md` (preserved unchanged). No final review,
milestone acceptance, completion, or broader A.2 claim is made.

- Repo: `/root/Code/slo-message-queue/slo`; branch `message-queue`; baseline
  `82c3f5c6de9345af34a673a3d975366ca8c1624c`.
- Authority: original spec
  `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md`
  §§4.3 and 6.2, plus `early-review-append-repairs.md` ER3 and `README.md`
  §Style rules.
- Scope: ER3 only. No raw-group/startup/context/compaction barriers, producers,
  consumers, T2 provider control/race/cleanup, tools policy, or TUI work.

## Defect and correction

ER3 found that `validate_cooperative_history_event` and its marked-tool,
opening-array, diagnostic and no-start helpers were free functions in
`history/dao.py`, contrary to the repository class-owner convention, which
reserves free functions for tool bridges, LangGraph nodes and test helpers.

The cohesive admission policy now lives behind one class owner in
`src/agents/slo_agent/history/dao.py`:

```python
class CooperativeHistoryEventValidator:
    @classmethod
    def validate(cls, *, event: SessionHistoryEventDAO) -> None: ...

    @classmethod
    def _validate_run_retrying_event(cls, *, event: SessionHistoryEventDAO) -> None: ...

    @classmethod
    def _validate_marked_tool_event(cls, *, event: SessionHistoryEventDAO) -> None: ...

    @classmethod
    def _validate_opening_call_array(
        cls, *, event: SessionHistoryEventDAO, group: ToolGroupMetadataDAO
    ) -> None: ...

    @classmethod
    def _validate_diagnostic_event(cls, *, event: SessionHistoryEventDAO) -> None: ...

    @classmethod
    def _validate_no_start_event(cls, *, event: SessionHistoryEventDAO) -> None: ...
```

- One class, not one class per check and not a framework.
- Public entry is the requested typed keyword classmethod
  `CooperativeHistoryEventValidator.validate(event=event)`.
- Private validation steps are typed classmethods with explicit keyword calls.
- Guards, validation order, error strings and accepted/rejected event shapes are
  unchanged.
- The marker/kind discrimination remains in the same flow; `run_retrying`
  dispatch was extracted to a named private step without changing conditions.
- `dao.__all__` exports the class instead of the removed free function.
- `filesystem_store.py` imports the class and calls it at the single existing
  cooperative append entry point. The flat and tree adapters continue to reach
  the same owner; no tree enrichment or second path was added.
- A repository grep found no test that imports the removed function by name.
  Existing both-adapter admission proofs exercise it through the store caller,
  so no test source needed an import edit. No test was deleted, skipped, xfailed
  or weakened.

## Test-first and reuse

This is a behavior-preserving refactor with no new observable behavior, so a
fabricated RED was not created. The existing passing admission/certification/
application proofs were reused unchanged and rerun after the owner move (their
pre-refactor GREEN receipt is `logs/turn6-r2-certification-green.log`); the
audited-chain selection was rerun as well.

Focused retained set (certification + all cooperative append + application):

```text
57 passed, 2 warnings in 2.98s
EXIT=0
```

Audited chain (focused set plus delivery, reconciler, projector, provider
settlement guard, tool-group metadata and cooperative-yield metadata):

```text
253 passed, 320 warnings in 68.82s
EXIT=0
```

Raw logs:

- `logs/turn6-er3-admission-owner-green.log`
- `logs/turn6-er3-admission-owner-audited-chain.log`

Both raw logs carry UTC, cwd, expanded argv, Python 3.11.7, the
Poetry-resolved interpreter, the synthetic environment, final source/test
SHA-256 values, the pytest output and exit status.

## Static evidence

```text
Black (dao.py, filesystem_store.py): 2 files would be left unchanged; BLACK_EXIT=0
mypy (dao.py, filesystem_store.py, tree_store.py): Success: no issues found in 3 source files; MYPY_EXIT=0
```

Raw log: `logs/turn6-er3-admission-owner-static.log` with exact argv, cwd, env,
source hashes and both exit statuses.

Changed source SHA-256:

- `src/agents/slo_agent/history/dao.py`
  `4419e9f2bc662d25155700181c5f9739db107a7d4db9e682cee947171f8baefd`
- `src/agents/slo_agent/history/filesystem_store.py`
  `0902af51738411f89741976b090149105a1ad127a0755737bef929b4b9f1cd97`
- `src/agents/slo_agent/history/tree_store.py` unchanged
  `01d05bc725c4518612fc03b729985edcc8092c2c04ad714af87ef1b33a2b52d3`

## Safety and limits

- No binary or executable creation/mutation, no installer/package/system/
  infrastructure/herdr/script changes, and no fixture installation. The sole
  consented deploy-worker temp `bin/curl` fixture was not run.
- No commit, push, merge, PR, or nested agents.
- `make test PYTEST_WORKERS=6` remains **BLOCKED** by other executable-fixture
  consent; no exclusion, skip/xfail, substitute total, or model/mode evasion was
  used. Full static is **UNRUN**; the YAML-stub baseline remains
  **UNESTABLISHED**.
- Preflight SHA-256 remains
  `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`.
- Independent `gpt-6.1-sol` high final review and completion remain pending.
  Model remained the exact DeepSeek primary default; no fallback was used.
- Ledger: turn 6, dispatch 4/20; prior partial turns 7/4/4/8/8; 60-turn ceiling;
  ten prior execution retries (audit 1, provider 1, repair 2, proof 1, append 2,
  fsync 1, certification-order 2), none in this task; no abort was retried.
