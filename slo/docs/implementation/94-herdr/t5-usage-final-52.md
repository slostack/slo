# Usage continuation 52 — INCOMPLETE

Same unfinished turn 1: started 1, completed 0, historical partial 1, supplied dispatch 52, retries 0. User grants unlimited turns and dispatches; no agents dispatched. No budget stop, independent review or feature acceptance claimed.

## Implemented bounded handoff

The existing enabled separate-eventless-update RED reproduced: **1 failed, 88 passed**, `3 == 6`. `agent.py` now retains one fixed-size `TokenUsageTotalsDAO` of undelivered completed usage. `consume_completed_usage()` transfers and clears that aggregate synchronously. `sessions/service.py::_sync_usage_snapshot_commit` drains it into the existing sole session cumulative owner instead of consuming only the latest version/value. Removed the obsolete session version cursor. Latest-update display and monotonic capture version remain separate. No Herdr accounting, extra event, queue, callback, lifecycle redesign, or provider change.

The production increment was under 50 lines. Pending usage survives run reset until consumed; partial messages-mode chunks remain uncharged; authoritative completed updates charge once, including numerically equal updates/iterations. Existing unknown/zero/cache arithmetic is unchanged. Session final refresh drains interruption leftovers. Single-consumer, same-loop synchronous ownership is documented on the handoff; sharing one agent between independently accounting sessions is not a supported contract.

## Executed evidence

CWD: `/root/Code/slo-94-herdr-integration/slo`. Commands used `PYENV_VERSION=slo-harness` (approved Python 3.11.7), existing Poetry environment, no venv creation. Focused gates use `bash docs/implementation/94-herdr/t1-dao-check.sh <paths>` including its DAO/projection additions. Existing pre-import/per-test state isolation, HERDR stripping/disable, terminal guard and fake-only spawn guard retained. No real provider or Herdr invocation.

All receipt names below have prefix `docs/implementation/94-herdr/t5-usage-final-52-`; each test gate has `.log` and `.exit`:

- `red`: owned regression module + session_usage; **1 failed, 88 passed**, exit 1.
- `green`: same + agent + cache_control; **171 passed**, exit 0.
- `closure`: added interrupted transport-refusal fixture had an incorrect assumption; **2 failed, 91 passed**. Actual session code supports committed-stream continuation (not blind replay), up to five attempts. Production behavior was not altered. This failed receipt is retained.
- `closure2`: refusal fixture now uses a concrete OpenAI RateLimitError after visible output, before/after completion, exercising actual no-retry policy and real temporary history; **93 passed**, exit 0. Explicit typed exception, one attempt, no recovery/retry/completion, one persisted failure, completed usage only. New reset/drain alias test and refresh-between-updates cases pass.
- `surrounding`: `test_agent*.py`, `test_session*.py`, cache_control and then-present `herdr/test_*attention*.py`; **528 passed, 160 warnings**, exit 0. Includes actual invoke interruption/history cases retained from 51, recovery, compaction and attention baseline. Concurrent attention lane added/changed tests later; this is not a claim that the later entire lane was green at that snapshot.
- `full`: **one `make test`**, **6 failed, 7705 passed, 19 deselected, 517 warnings**, make exit 2. Not green.
- `full-failures-focused`: helper with `herdr/test_attention_execution_composed.py` and `integration/test_feature89_model_flows.py`: **4 failed, 146 passed, 163 warnings**, exit 1. The attention lane's two earlier failures no longer reproduce after its concurrent test-only work; no attention files edited here.
- `smoke`: `make smoke`, **288 passed**, exit 0.
- `black`: `poetry run black --check` on agent.py, sessions/service.py, owned regression module: all three unchanged, exit 0. Only the owned test module was formatted (`format.log`).
- `mypy`: same three paths: **9 errors in 6 imported files**, exit 1; no errors in the three owned files. Existing errors name langchain/client/DAO/Faux/normalizer/provider dependencies; full supplied baseline **299/63 remains unwaived**. No full make lint rerun or green-static claim.
- `diff`: `git diff --check`, silent, exit 0.
- `coreutils` and `coreutils-final`: `dpkg -V coreutils`, silent, exit 0.
- `before-full.sha256` and `final.sha256`: all three owned files identical across full gate and focused rerun (verified with `sha256sum -c`). Concurrent non-owned files are not frozen by this receipt.

## Remaining integration blocker — no assertion weakened

All four combinations of `tests/integration/test_feature89_model_flows.py::test_prepared_mixed_pool_tool_fallback` fail at line 413:

```text
assert (totals.input_tokens, totals.output_tokens, totals.total_tokens) == (10, 4, 14)
E assert (20, 8, 28) == (10, 4, 14)
```

The fixture makes **two successful provider requests**, tool and answer; its own order assertion requires `[other, other]` after fallback. `jev_frames` includes `(10,4,14)` in each response, with distinct tool/answer IDs. Counting both completions is required by the current user contract, and the old numeric-equality deduplication counted only one. This strongly indicates a stale integration expectation rather than permission to restore numeric deduplication. The direct Responses fixture also needs its exact per-response payload validated before changing that expectation. This file is outside the authorized write set: **not edited**, not skipped, no totals weakened. Need scoped authorization/owner correction and a fresh green integrated gate before READY.

The full run's two attention failures were `KeyError: 'turn'` at the then-current line 148 despite correctly asserted session total 8. The subsequent focused attention module passes; attributed to the concurrent lane only as an observation, not an independently verified causal fix.

## Scope and ingestion qualification

Read supplied AGENTS/CLAUDE/docs RESEARCH and actual root RESEARCH, actual scope-plan/routing, 51 report, Makefile/helper, isolation guards, existing usage DAO/tests and relevant capture/stream/retry/session finalization paths. Loaded committed shared engineering routing/testing/ownership, coding rules/cadence/declarative, Python root/declarative/Faux recipe/named arguments/docstrings and workflow SKILL. KB Welcome, slo README and gotchas consulted; oversized concatenated output was truncated, so exhaustive KB/source/skill-ingestion is not claimed. Canonical Herdr B 7.6 projection/sole accounting and C publication/final-refresh contracts inspected read-only. No new graph, CLI, TUI, persistence schema or database component.

Only production agent.py and the session usage consumer, owned regression test module, and this report/receipts changed by this continuation. Existing unrelated session changes preserved. No shared status, attention tests, specification, KB/global/system/other-worktree edits; no commit/push/PR/reset/clean/stash. Full finite READY is withheld: remaining integration failures, unwaived static baseline, and incomplete exhaustive ingestion/review prevent acceptance. The eventless handoff itself and bounded surrounding tests are green.
