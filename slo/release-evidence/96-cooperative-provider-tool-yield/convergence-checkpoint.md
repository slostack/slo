# Convergence checkpoint — watchdog plan narrowed

2026-11-04 · read-only analysis plus the two explicitly requested evidence documents. No code/test changes, test/collection/static execution, runtime/model probes, nested agents or dispatches. **A.2 PARTIAL / INCOMPLETE; no workflow acceptance or completion claim.**

## Ledger and stalled attempts

Carry the operator's current ledger, not the older bottom stanza of `current-handoff.md`:

- Current turn **8**, dispatch **8/20**; prior partial-turn dispatch counts **7/4/4/8/8/11/6**.
- Effective ceiling **60 turns**; **12 execution retries** retained; **no abort**. No new retry or completed workflow turn inferred from this analysis.
- Last **two DeepSeek watchdog-race author attempts**: normal output-limit termination, **no completion artifact** (operator-supplied execution history). They are stalled/incomplete author attempts, not execution-error retries, aborts, passing phases, or completed Code-Test-Review cycles. This analysis does not invent dispatch IDs, token counts, provider quota errors or transport receipts for them.
- No generic/output-limit fallback. Code+Test primary stays exactly `openrouter:deepseek/deepseek-v4.1-flash-1017`, default reasoning; `gpt-6.1-sol` medium only after concrete recorded OpenRouter token/quota exhaustion. Current GPT contribution is analysis only. No implementation-model substitution occurred or is authorized by this checkpoint.

## Closed acceptance portion retained

Do not reopen completed prerequisite design merely because the broad race assignment stalled:

| Portion | Retained status and evidence | Not certified |
|---|---|---|
| Control-only phase/high-water owner | Bounded delivered portion closed per handoff: `implementation-control-state.md`, dispatch4 receipts (4 new / 47 focused regression reported). Current control source still has reservation and phase-exit wait. | No executor binding, cancellation policy, active watchdog race or urgent journey. |
| Closed outcome DAO + sole legacy caller migration | Bounded delivered portion closed per handoff: `implementation-watchdog-outcome.md`, dispatch5 receipts (19 focused / 190 regression reported; scoped static reported). Current watchdog/agent source matches the carrier/caller shape. | No yield consumer/activation. DAO None representation is proved by prior tests, but actual watchdog None-item discrimination is NOT: read helpers still conflate None with exhaustion. Track that narrow gap in the whole read-path migration. |
| Earlier history/strict-settlement/raw/compaction subsets | Retain prior accepted scope and artifacts unchanged. No new review of all history claims made here. | Not live interrupted-provider settlement or overall T1/T2 acceptance. |

These are retained prior author/review receipts, not tests rerun by this analyst. Acceptance portion closed means bounded prerequisite progress only, not A1/A10 or whole-feature completion.

## Changed plan — one exact small seam

Stop reassigning the entire watchdog race unchanged. Next author assignment is only `WatchDogTimer._cancel_and_join_owned_read`, in `src/agents/slo_agent/watchdog_timer.py`, plus lifecycle tests in existing `tests/agents/slo_agent/test_watchdog_timer.py`, **<100 added production lines**. Detailed named inputs/output, cancel-once/repeated-cancellation ownership contract, terminal-truth matrix, future commands, non-edits and closure are in [watchdog-next-seam.md](watchdog-next-seam.md).

It accepts the already-owned reader and signal waiter tasks, cancels once, drains all under one retained shielded cleanup task despite repeated caller cancellation, returns whether caller cancellation occurred, and leaves joined terminal truth inspectable for the eventual race owner. No stream close, control settlement, queue claim or outcome classification. The live reader/public invoke and unsafe-yet yield consumer remain unchanged. This deliberately finite prerequisite resolves the existing source comment's lifecycle hazard before moving `anext` into a task; it is not another parallel consumer or an activated partial race.

The plan changes the scope, not the required model, safety rules, retry history or acceptance bar. Save a compact author artifact before final prose; if this coherent helper cannot fit the bound, report the blocker, do not expand it into a broad race implementation or new harness. No author launched here.

**After this seam, prioritize the actual urgent journey**, not another succession of disconnected helpers: real local client/session/queue/SQLite + existing graph + complete phase-aware race + joined read/close/history/context settlement + one urgent boundary/application before next provider request. Proposed original test `tests/integration/test_messaging_yield.py::test_silent_provider_urgent_delivery` remains future work; both real history adapters, first/next token gates, abort/failure cutoffs and A10 lifecycle matrix required. Yield producer and consumer settlement must be connected cohesively before activation. Do not widen composer beyond its current normal-only binding.

## Preservation and outstanding gates

Baseline/HEAD verified `82c3f5c6de9345af34a673a3d975366ca8c1624c`. Source identities inspected before documentation:

- watchdog `d00df1408354aefb25313a9a42f286ca3ab6c2eebd66dc665c1b548590d55ef3`
- control `ce0c669954e4a1d14b7d35ddcb63385d543c5c8064107ca4c56031fc17089c06`
- SLO.md `e12590429f885d639c57b40599973e24a97a1de5363275eb736527af135c1830`
- immutable preflight `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`

Both actual skill env roots resolve to the installed root named in `routing.md`; actual workflow/shared/overarching/Python rules read, not replaced with similarly named cadence guidance. Source-only findings above are not executed reproductions. Existing source/tests, SLO.md, docs/, preflight and prior reports preserved; only `watchdog-next-seam.md` and this checkpoint intentionally created.

No binary/executable/bin mutation directly or indirectly, installers/herdr fixtures/system/packages/infrastructure, commit/push/merge/PR or nested agents. Existing deploy-worker verified tmp-root bin/curl0755 child-PATH exception **not run**; no other fixture consent inferred.

Required full `make test PYTEST_WORKERS=6` remains **BLOCKED** by other specific consent, without exclusions, alternative totals or model/mode evasion. Full static **UNRUN**; mypy baseline **UNESTABLISHED**. Actual urgent journey, independent early actual-urgent review, independent final review and independent completion remain **mandatory, pending**. This checkpoint is a changed bounded plan, not a READY implementation verdict.
