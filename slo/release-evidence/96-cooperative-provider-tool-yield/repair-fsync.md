# 96.a.2 R1 repair — re-fsync existing append-once events

**Status:** R1 repair complete for the restricted append-once port, both adapters.
R2/R3 repairs and application validator/error translation are preserved.
No producer, raw-group validator, T2, full suite or full static gate was run.

- Checkout: `/root/Code/slo-message-queue/slo`; branch `message-queue`;
  HEAD `82c3f5c6de9345af34a673a3d975366ca8c1624c`; worktree remains dirty
  from prior turns.
- Scope authority: `early-review-append.md` R1 and spec §2.4/§6.2.2/.5/§9 A8.
  No other evidence report, doc, `SLO.md` or prior log was edited.
- Ledger as supplied: retry 1 of 3 for this dispatch; prior partial-turn calls
  7/4/4/8; 60-turn ceiling; seven prior execution retries; no abort retried.

## Defect fixed

A matching raw event plus equal canonical digest was reported `existing`
successfully after rewriting only `session.json`. Fsyncing metadata does not
certify the `events.jsonl` bytes left by a failed first append. A later exact
retry could therefore succeed without ever confirming the event bytes durable.

`_append_once_sync` now certifies `events.jsonl` through a successful fsync
while still inside the shielded writer under the store lock, before returning
the existing event. Failure escapes through the existing wrapper as
`CooperativeYieldSettlementError` (application path keeps `MessageStoreError`),
adds no line, reconstructs nothing and schedules no live retry.

## Minimal injected collaborator

`FileCertification` (`history/filesystem_store.py`) is a one-method public seam;
its default `certify()` opens the exact path and calls real `os.fsync`.
`FilesystemSessionHistoryStore(..., file_certification=...)` accepts it and
`TreeBasedFilesystemSessionHistoryStore(..., file_certification=...)` forwards
it to the flat owner. `_append_event_line` writes and flushes the complete line,
then certifies that same file; a certification failure leaves readable complete
bytes for the exact retry. No module-global `os.fsync`/`open`/`Path` patch, no
private-method patch and no `tree._flat = ...` assignment was used.

## Test-first evidence

Environment for every command:

```bash
cd /root/Code/slo-message-queue/slo
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD" /root/.pyenv/versions/slo-harness/bin/python -m pytest \
  -p no:cacheprovider -m 'not e2e' -q <files>
```

Interpreter: `slo-harness` 3.11.7; Poetry resolves to the same CPython binary.
`make test PYTEST_WORKERS=6` remains BLOCKED by the executable-fixture consent
boundary; no skip/xfail/subset/model substitution was used.

- Baseline focused file before edits: exit 0, **18 passed**.
- GREEN focused file after repair: exit 0, **22 passed**, 2 warnings, 1.92s.
  `logs/turn5-r1-fsync-green-focused-final.log`.
- RED detection proof: the existing-event certification call was temporarily
  removed and the two new parameterized cases were rerun. Exit 1,
  **2 failed / 0 passed**, `[False]` and `[True]` both fail. Log:
  `logs/turn5-r1-fsync-red-revert-probe.log`. This is an explicitly labelled
  post-fix revert probe, not retroactively claimed as original test-first RED.
- Scoped regression, eight real-boundary files (append, application, delivery,
  reconciler, projector, provider guard, tool-group metadata, cooperative
  metadata): exit 0, **247 passed**, 320 warnings, 69.10s.
  `logs/turn5-r1-fsync-regression-app.log`.
- Scoped mypy on the two changed source files: exit 0,
  `Success: no issues found in 2 source files`.
  `logs/turn5-r1-fsync-mypy.log`.
- Black check on both changed source files: exit 0, unchanged.
  `logs/turn5-r1-fsync-black-final.log`. The untracked test file retains the
  pre-existing `_with_metadata_key` wrapping noted by earlier review; no
  unrelated reformat was applied.

## Coverage mapping

| Required case | Proof |
|---|---|
| Both adapters, first line complete bytes / fsync fail | parameterized `[False]`/`[True]`; one readable JSON line survives first failure |
| Failed retry certification still raises | second call raises, still one line |
| Later real certification returns same ID/seq/time/digest, one line | third call succeeds; exact event/digest/`recorded_at`/sequence asserted |
| Stale metadata | first failure leaves `latest_sequence=0`; success repairs it to 1 |
| Unknown reply after successful certification | `_LostReplyFlatStore` / `_LostReplyTreeStore` public-port subclasses persist then drop one reply; retry returns the certified one-line event |

Real files under pytest `tmp_path` only. No executable creation or mutation; the
sole consented deploy-worker `bin/curl` fixture was not exercised.

## Final source identity

- `src/agents/slo_agent/history/filesystem_store.py`
  SHA-256 `ca0e2b70e4f891b45e8c9b9a9eff615f76a5e85c261e2a644a38e69756b07582`
- `src/agents/slo_agent/history/tree_store.py`
  SHA-256 `01d05bc725c4518612fc03b729985edcc8092c2c04ad714af87ef1b33a2b52d3`
- `tests/agents/slo_agent/messaging/test_history_cooperative_append.py`
  SHA-256 `4cfafdbad080585fba751acb50fcc02a1ec91a4ba7db5c6e1565851d5e5f2065`

Preflight hash `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`
remains unchanged. No commit, push, merge, PR, package, infrastructure or system
mutation.

## Remaining

- §6.3 raw group/startup/context/compaction validation, producers, T2 provider
  race/tools/TUI remain unfinished and were not touched.
- Full `make test PYTEST_WORKERS=6`, full static/lint and YAML-stub baseline
  remain BLOCKED/unestablished.
- Independent final review and completion are not claimed.
