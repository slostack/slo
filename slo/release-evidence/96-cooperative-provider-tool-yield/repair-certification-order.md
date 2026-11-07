# 96.a.2 — certification-order repair (ER1/ER2), retry 2

**Status:** ER1 and ER2 closed at the focused real-boundary level in this retry.
ER3 (class owner) is deliberately **not** started, per the bounded task. No
broader A.2 feature, final review, completion, or family approval is claimed.
Independent `gpt-6.1-sol` high review remains pending.

- Repo: `/root/Code/slo-message-queue/slo`; branch `message-queue`; baseline
  `82c3f5c6de9345af34a673a3d975366ca8c1624c`; worktree remains dirty from prior
  turns.
- Authority: original spec
  `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md`
  §6.2, plus `early-review-append-repairs.md` ER1/ER2.
- Ledger: turn 6, dispatch 3/20; prior partial turns 7/4/4/8/8; 60-turn limit;
  this is retry 2 of 3; eight prior retries; no abort retried. Model was the
  exact DeepSeek primary default; no fallback was used.

## ER1 — certification test seam and assertions

The retained untracked file
`tests/agents/slo_agent/history/test_history_file_certification.py` in this
worktree already matches the required one-method seam; no delete, skip, xfail,
or weakening was applied:

- Both adapters are constructed with `file_certification=certifier`, the actual
  constructor keyword accepted by `FilesystemSessionHistoryStore` and forwarded
  by `TreeBasedFilesystemSessionHistoryStore`.
- `_ScriptedCertifier.certify(self, *, path: Path)` implements the real
  `FileCertification.certify(path)` contract. It fails only its bounded budget,
  then calls `super().certify(path=path)`, which opens the exact file read-only
  and performs the real `os.fsync`.
- The stale-metadata test finishes with real assertions: after the first failed
  append and after the failed retry certification, metadata stays `0`; the
  successful retry advances metadata to `1`; the event keeps the same ID,
  sequence `1`, `recorded_at`, and `application_sha256`; raw lines remain one;
  all three certifications target `events.jsonl`.
- The equal-event and lost-reply tests retain their exact one-line, exact
  ID/sequence/time/digest assertions for both flat and tree adapters.

Actual file SHA-256:
`5994998489608f8fced71f56261a69e7bf1cf7c658b4aae06da47edc5dd380bf`.

## ER2 — existing-event certification before metadata rewrite

Defect: in `FilesystemSessionHistoryStore._append_once_sync`, the equal existing
event path repaired `metadata.latest_sequence` and fsynced `session.json`
*before* certifying `events.jsonl`. A failed retry therefore advanced the
durable high-water marker before the raw line was certified.

Repair: the existing-event branch now certifies the exact `events.jsonl` first.
Only after successful certification does it write repaired metadata and return
the persisted event. The new-append branch and the application-specific
validation/error translation are unchanged; application high-water repair still
happens before a new append.

Changed source:
`src/agents/slo_agent/history/filesystem_store.py`
SHA-256 `5596908174bbb7b50c2d811e4f786b1afe41f243fca762703d782eaa403c316f`.

## Test-first evidence

RED before the source repair, both adapters:

```text
tests/agents/slo_agent/history/test_history_file_certification.py::test_equal_event_retry_repairs_stale_metadata_only_after_certification[False] FAILED
tests/...::test_equal_event_retry_repairs_stale_metadata_only_after_certification[True] FAILED
2 failed, 2 warnings in 1.72s
exit 1
```

The failure was exactly `assert 1 == 0` for `latest_sequence` after the failed
retry certification, on both adapters. Raw log:
`logs/turn6-r2-certification-red.log`.

GREEN after the repair, exact retained run set:

```text
tests/agents/slo_agent/history/test_history_file_certification.py
tests/agents/slo_agent/messaging/test_history_cooperative_append.py
tests/agents/slo_agent/messaging/test_history_application.py
57 passed, 2 warnings in 2.83s
exit 0
```

Per-file counts: certification `6 passed`, cooperative append `22 passed`,
application `29 passed`. Raw logs:
`logs/turn6-r2-certification-green.log`,
`logs/turn6-r2-perfile-counts.log`.

Broader safe/audited fixture chain (the retained certification file plus the
prior eight-file real-boundary regression set):

```text
253 passed, 320 warnings in 71.20s
exit 0
```

Raw log: `logs/turn6-r2-safety-audited-chain.log`. That set is application,
delivery, reconciler, projector, provider settlement guard, tool-group metadata
and cooperative-yield metadata over real `tmp_path` files/SQLite only; it
creates no executable fixture and the consented deploy-worker `bin/curl`
fixture was not run.

## Exact run metadata

- cwd: `/root/Code/slo-message-queue/slo`
- interpreter: `/root/.pyenv/versions/slo-harness/bin/python` (CPython 3.11.7);
  `poetry run python` resolves to `/root/.pyenv/versions/3.11.7/bin/python`.
- argv: `/root/.pyenv/versions/slo-harness/bin/python -m pytest
  -p no:cacheprovider -m 'not e2e' -q <retained files>`
- synthetic environment exported before every run:
  `SLO_ENV=test`, `SLO_ROOT_DIR=$PWD`, `SLO_APP_DIR=$PWD`, `SLO_APP_NAME=slo`,
  `SLO_LOG_FORMAT=text`, `SLO_DEFAULT_MODEL_NAME=gpt-5.4`,
  `SLO_AUTO_VISUALIZE=0`, `SLO_HERDR_DISABLED=1`,
  `SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked`, `COLUMNS=120`,
  `LINES=40`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=$PWD`.
- source/test hashes are recorded in both raw logs and above; tree
  `01d05bc725c4518612fc03b729985edcc8092c2c04ad714af87ef1b33a2b52d3`, dao
  `86e72efc04db2730ba223d3d294f77596324bee8002f4d62d0e1d633b883a8f3`,
  cooperative append
  `4cfafdbad080585fba751acb50fcc02a1ec91a4ba7db5c6e1565851d5e5f2065`,
  application
  `7de0653702fef3240f28991c0fb7f487dd6eba39b0f7361761060fad38ca7c06`.

## Safety and limits

- The run set creates no executable fixture: it uses real `tmp_path` files and
  real SQLite/JSONL only. The consented deploy-worker `tmp_path/bin/curl` fixture
  was not run.
- No system/package/installer/herdr/script/infrastructure change; no binary or
  executable mutation; no commit, push, merge, PR, or nested agents.
- ER3 (free-function class extraction) remains open by instruction.
- `make test PYTEST_WORKERS=6` remains **BLOCKED** by other executable-fixture
  consent; no exclusion, skip/xfail, substitute total, or model/mode evasion
  was used. Full static is **UNRUN**; YAML-stub baseline remains
  **UNESTABLISHED**.
- Preflight SHA-256 remains
  `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`.
- Independent final/completion review is pending; author receipts are not a
  substitute.
