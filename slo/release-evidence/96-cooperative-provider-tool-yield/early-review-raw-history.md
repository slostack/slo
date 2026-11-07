# 96.a.2 — early raw-history review

**Verdict: REVISE — four concrete blockers in the bounded reader/compaction increment.** Independent read-only early feedback inside Step 1 only. Not final review, milestone acceptance, completion, or a completed workflow turn. The urgent runnable milestone is **not done**.

## Scope and provenance

Repository `/root/Code/slo-message-queue/slo`, branch `message-queue`, HEAD/baseline `82c3f5c6de9345af34a673a3d975366ca8c1624c` verified read-only. Authority: exact `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md`, §§6.1–6.3 and §9 A8/A12. Read the three `implementation-{raw-groups,startup-raw,compaction-groups}.md` reports, `current-handoff.md`, `routing.md`, `acceptance.md`, accepted append review, actual source/diff, new tests and selected retained logs. Accepted append semantics are not reopened.

README read first, including maintained history/style rules; KB Welcome → slo/README/gotchas and canonical project RESEARCH consulted (repo-root RESEARCH absent; not created). Both live skill variables equal `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`. Consulted that installed INDEX/manifest and exact `orchestration/workflows/code-test-review.md` early-feedback checklist, workflow rules, engineering routing/ownership/review/testing, overarching solution-design/coding-rules/naming/test-verification/declarative guidance, Python root/keyword-types/docstrings/declarative and relevant service/agent guidance. No framework migration or final-review procedure substituted. Typed keyword APIs and owner-delegated validation are broadly preserved; the issues below concern observable contracts, not mechanical method-length refactors.

**No tests, collection, static checks, product/model execution or nested agents run.** Shell use was limited to environment display, git reads, source-line display and hashes. Only this new report written. Findings are source-established counterexamples, not claimed executed reproductions.

## Finite blockers and closure conditions

### RH1 — High: marked error results replay as success

- **Requirement:** §6.1, A12: retain actual core result status; legacy missing status retains prior behavior.
- **Source:** `src/agents/slo_agent/history/projector.py:733–738` constructs `ToolMessage` without `status`; `history/dao.py:318–320` requires marked result status but conversion never reads it. Installed LangChain `messages/tool.py:88` defaults status to `success`.
- **Concrete failure:** valid opening + marked result with `tool_result_status='error'` + terminal passes raw validation; `build_message_history` returns success. The new projector/store tests seed only success and assert types/IDs, not status, so they cannot detect this.
- **Closure:** projector consumes validated marked status, preserves unmarked legacy default. Failing-first real flat/tree round trips for success/error assert exact status, IDs/content and absence of fabricated results, including retained compaction replay.

### RH2 — High: membership sets accept results before their opening and permit historical healing to replace truth

- **Requirement:** §§6.1, 6.2.1, 6.3.2–3, A8/A12: opening before result publication; marked raw evidence must settle without repair.
- **Source:** `history/projector.py:153–172,195–219,398–420` records result membership without requiring an earlier opening. Final equality checks do not check ordering. No-start compares marker position to the **first observed sibling**, not the required first-call anchor (`:145–147,211–215`).
- **Concrete failure:** raw `[result(a, actual output), opening(a), terminal]`, with otherwise canonical metadata/IDs, is accepted. Projection emits the result first; `MessageContractReconciler._drop_orphan_tool_results` drops it (`history/message_contract_reconciler.py:276–288`) and `_heal_dangling_tool_calls` fabricates a placeholder (`:313–337`). Real persisted output is silently replaced. Also `[opening(b), marker, opening(a)]` for declared `(a,b)` passes the marker-position check although the anchor follows disposition.
- **Closure:** raw owner enforces opening/result and anchor/disposition ordering before selection/healing, while retaining valid first-full-anchor + partial-sibling no-start behavior. Add both-adapter malformed raw histories through ordinary append, then assert both `context_events` and `build_message_history` fail even for excluded/incomplete turns or a summary hiding them. Include duplicate opening/result/marker and conflicting content/identity cases; do not rely on the append-once port to erase duplicates before testing the raw reader.

### RH3 — High: summarization is an unguarded context consumer; no-start openings can leak into the durable summary

- **Requirement:** §6.3.1/3/5, A8/A12: validate before compaction selection; exclude proven no-start openings from model context.
- **Source:** `sessions/service.py:7879–7886` calls `Compacter.compact` **before** activation validation. `compaction/compacter.py:163–191` selects raw events and sends them to the model without the projector check. Its renderer skips `run_retrying` but emits every `tool_call` (`:479–502`).
- **Concrete failure:** manual/forced compaction over an unresolved marked opening can issue a summary-provider request before the store rejects activation. A valid disposed group entirely in the compacted prefix is rendered as a tool call with its arguments while its no-start marker is omitted. Its excluded content can return as `compaction_summary` and become future model context. Durable group-atomic truncation alone does not prevent this.
- **Closure:** use the shared raw validator before summary selection/provider invocation and omit exactly proven no-start model content while preserving original raw snapshot/cut/coverage identities for activation. Add real session manual/automatic compaction proofs with injected provider-boundary capture: unresolved ⇒ zero summary requests/writes; disposed ⇒ no disposed call/arguments in summary request; unrelated settled/user content remains. This is the existing no-start contract, **not** a demand to implement deferred interrupted-context §6.4.5 now.

### RH4 — High: direct and compatibility rewrites validate caller snapshots, not current active history

- **Requirement:** §6.3.5, A8/A12: no unresolved group removal or silent loss at any rewrite entry point.
- **Source:** `history/filesystem_store.py:1625–1633` rereads/compares active history only when `messaging_compaction_id` is provided. Without it, validation uses caller `events`. Compatibility truncation does likewise (`:1691–1708`). Tree delegates both paths (`history/tree_store.py:348–374,423–455`). Session nonmessaging activation uses the unchecked direct branch (`sessions/service.py:7922–7927`).
- **Concrete failure:** capture a valid snapshot, append a new marked opening, then call direct `compact_to_boundary` with the earlier snapshot and no messaging ID, or compatibility truncation. Validation sees no unresolved group; activation archives the current log and replaces it with a candidate omitting the new opening. Subsequent active-history startup can appear settled. An audit archive does not make this a safe refusal.
- **Closure:** under the same store serialization, validate current active raw evidence and require the supplied source to match it before candidate/archive/metadata effects, on both rewrite paths; preserve A.1 selection/coverage rules. Both-adapter tests append after snapshot, invoke each public rewrite, and assert refusal, byte-identical active log/metadata, no candidate/archive, and the opening still present. Include normal compatibility success and a cut through a marked group.

## Verified shape and evidence limits

| Area | Source/test inspection result |
|---|---|
| Raw identity/full arrays/content/duplicates | Shared admission checks schema, deterministic IDs, attempt/iteration, ordered full array and selected payload; `_RawToolGroupState` checks opening signatures, opened_at and duplicate memberships. Ordering/status defects above remain. New tests do not directly cover several duplicate/content/correlation branches. |
| Startup barrier | `sessions/service.py:936–982,1287–1303,1454–1485`: execution ownership → history barrier → all evidence pages assembled → one raw validation before compaction reconciliation/reset/projection/readiness. Failure unwinds store close then lease release (`:2492–2499`). New flat/tree tests cover incomplete/unknown rejection and one-event-page success. They call `close_messaging()` in finally **before** checking not-ready: they do not prove immediate failed-start lease cleanup. Strengthen with readiness/independent lease reacquisition before explicit close and unchanged claims/history. No additional source defect asserted here. |
| Context consumers | Both `build_message_history` and `context_events` share `_context_event_slice` validation before turn/exclusion/summary selection. Session load and context-window estimator reach these paths. Compacter is the bypass in RH3. |
| Compaction tail/coverage | Supplied-snapshot cuts pin to group start; summary `first_kept_entry_id` uses actual pin. A.1 removed IDs remain computed below that same boundary. New tests exercise real flat/tree settled/disposed retention, whole settled removal and unresolved refusal with byte/artifact checks. They do not exercise compatibility truncation, mixed A.1 coverage under a moved pin, or actual summary-model requests. Existing A.1 coverage and transaction-failure tests remain, not weakened. |

Retained logs inspected: `turn7-raw-groups-green.log` records **136 passed**; startup RED records **4 failed/4 passed**, startup final GREEN **8 passed**; compaction RED **6 failed/2 passed**, post-format regression **309 passed**, exit 0. These are author receipts, not reviewer executions, a combined suite total, or proof of missing assertions. Current source/test hashes match the three implementation reports (projector `c6219447…`, filesystem `d1b52a79…`, session `1d3ba140…`; tests `51f4bf66…`, `a0a54d53…`, `dbe190d1…`). Preflight SHA remains `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`.

## Stop boundary / ledger

Repair RH1–RH4 test-first with scoped evidence and bounded rereview. Interrupted-context §6.4.5, producer activation, T2 provider race/control/cleanup, T3/T4, full acceptance, independent final review and completion remain expected future work, not extra findings against this slice. Existing append acceptance remains unchanged.

`make test PYTEST_WORKERS=6` remains **BLOCKED** by other specific fixture consent; no exclusions/substitutes/mode evasion. Full static **UNRUN**; YAML-stub baseline **UNESTABLISHED**, not waived. Sole consented existing deploy-worker tmp `bin/curl` fixture was not run. No executable/package/installer/herdr/system/infrastructure or git-write operations; unrelated SLO.md/docs/prior reports preserved. Exact DeepSeek primary/default/no-fallback policy unchanged; requested reviewer route is gpt-6.1-sol high, with no independent runtime-model attestation claimed here.

Preserve supplied counters: **turn 6, dispatch 11/20**, prior partial **7/4/4/8/8**, ceiling **60 turns**, **12 execution retries** (audit1/provider1/repair2/proof1/append2/fsync1/certorder2/compaction2); never retry an abort. This review consumes no execution retry and establishes no phase progression.
