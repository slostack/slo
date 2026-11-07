# 96.a.2 — early RH1–RH4 repair rereview

**Verdict: REVISE — one remaining source defect (RH2), plus a bounded RH4 safety-proof gap.** Independent read-only early feedback **inside Step 1**, not final review, acceptance, completion, or a completed workflow turn. A.2 and the urgent runnable milestone remain incomplete.

## Scope / authority

Reviewed original `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md` §§6.1–6.3 (A8/A12), `early-review-raw-history.md`, all four `repair-{result-status,raw-order,summary-guard,rewrite-snapshot}.md` reports, `current-handoff.md`, `routing.md`, `acceptance.md`, actual baseline diff, current tests and retained logs. Branch `message-queue`, HEAD/baseline **82c3f5c6de9345af34a673a3d975366ca8c1624c**, verified read-only.

README read first, including history/style/testing contracts; KB Welcome → slo/README, gotchas, codebase-index and operational-reference consulted. Root RESEARCH.md is absent; its external project-memory replacement was consulted, not recreated. Both live `SLO_SKILL_DIR` and `SLO_SKILLS_DIR` equal `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`. Read installed INDEX/available manifest, exact `orchestration/workflows/code-test-review.md` **early integration feedback** checklist and workflow rules; shared engineering routing/ownership/review/testing; overarching solution-design/coding-rules/naming/test-verification/declarative; Python root, typed-keyword, docstring, declarative, service/agent and review guidance. No skills edited, no framework migration. Owner-delegated validation and typed keyword interfaces are retained; findings concern required behavior and proof, not mechanical decomposition.

**No tests, collection, static checks, product/model execution or nested agents run.** Only this new report is intentionally written. Existing source, tests, SLO.md, docs, preflight and prior reports are not edited.

## Requirement-to-source / evidence disposition

| Finding | Current disposition | Source and actual proof scope |
|---|---|---|
| **RH1 — real result status** | **Source repair verified; bounded round-trip coverage present** | `history/projector.py:743–755` reads validated `tool_result_status`; unmarked legacy omits status and retains the prior default. `test_projector_tool_groups.py:525–611` checks both-adapter error status/name/ID/content and exact message types/count, success, and legacy default. Retained-compaction test currently uses success only: retained **error** status is not directly asserted. No claim that this missing assertion was executed. |
| **RH2 — opening/result + anchor/disposition order, no truth healing** | **Partially repaired; remains open** | `projector.py:174–180` requires each result's own earlier opening; `:219–224` requires anchor before disposition. Ordinary-append tests `test_projector_tool_groups.py:326–404` cover the original one-call result-before-opening counterexample, anchor-after-marker rejection, and valid partial siblings. They miss the surviving sibling-before-anchor result path below. |
| **RH3 — summary cutoff / no-start exclusion / original source** | **Bounded source repair verified** | `compaction/compacter.py:173–205` validates before cut/cap/render/provider. Only rendering filters proven excluded opening IDs; cut, cap, token counts and result IDs use the **original** raw events (`:178–198,212–220`). No-start marker is skipped by the existing renderer. Manual guard in `sessions/service.py:3611–3626`; automatic path reaches the guarded compacter before activation. `test_compaction_summary_guard.py` exercises real manual and automatic session entries, both stores and injected external provider capture: unresolved → zero requests/log writes; disposed → no tool arguments in request, unrelated content retained, successful activation over raw identities. This is not deferred §6.4.5 interruption coverage. |
| **RH4 — current-active validation + exact snapshot before rewrite effects** | **Source repair verified; safety proof incomplete** | Both sync rewrite entries call `_require_current_active_snapshot_sync` first (`filesystem_store.py:1625,1693`). It reads current active events, validates groups, compares the full ordered serialized snapshot digest (`:1714–1742`; digest `:864–873`) before candidate/archive/new activation/metadata work. Both public entry locks and tree delegation reach that same owner. Tests cover stale source after a **settled** late group on both APIs/adapters, compatibility success/pinning, and direct unresolved refusal. They do not exercise compatibility unresolved refusal/current-active validation independently of digest mismatch. |
| **A.1 coverage preserved** | **No source regression identified in this bounded review; not full acceptance** | `_select_message_compaction_sync:884–910` validates original active evidence, requires exact digest, computes the same pinned retain boundary, and includes only messaging IDs with `sequence < boundary`. Session activation still supplies original raw `events`, not the summary-visible list. Existing `test_history_application.py:62–114` asserts exact removed membership, stale/missing-cut refusal, tagged activation and retained suffix; unchanged against baseline, included in RH4 regression receipts. No mixed marked-group + moved-pin + A.1-ID assertion exists in the new tests; do not upgrade these receipts into that proof. |

## Finite revisions / closure

### RH2 — High: a sibling result before the projection anchor still loses real truth

**Source:** `src/agents/slo_agent/history/projector.py:151–180,226–227,732–737`, `history/message_contract_reconciler.py:276–289,313–335`.

For declared ordered calls `(a,b)`, ordinary raw append can contain:

```text
user → opening(b, full [a,b]) → result(b, actual output/status)
     → opening(a, full [a,b]) → result(a, actual output/status) → terminal
```

Every result has its own prior opening; membership sets are complete; the current raw validator accepts it. But **only opening(a)** projects the AIMessage (`:736–737`). Result(b) is consequently projected before any declaration, dropped as an orphan, then replaced by a historical interrupted/error placeholder. An actual successful result becomes an invented error; an actual error loses its real content. This is a source-established counterexample, **not an executed reproduction**. RH1 status conversion alone cannot prevent it. It violates §§6.1, 6.2.1 and 6.3.1–2.

**Required repair/closure:** enforce the complete projection anchor before any result can be admitted as settled raw evidence (or an equivalent owner-local design that preserves exact real results without historical repair). Preserve canonical valid source order and partial-sibling no-start semantics. Add failing-first **both-adapter, ordinary-append** tests for the sequence above; prove rejection by `validate_tool_groups`, `context_events` and `build_message_history`, including selection that would hide the turn. Retain a positive multi-call round trip with exact real IDs/content/status and no fabricated result. Re-review only this ordering/projection boundary and affected regressions.

### RH4 — Medium: current-active validation's critical branch is not independently proved on both rewrite APIs

**Source/test:** `filesystem_store.py:1735–1742`; `tests/agents/slo_agent/history/test_compaction_tool_groups.py:330–371,374–425`.

The new late-group test appends **opening + result** and expects `MessageStoreError`. It detects removal of the snapshot-match guard, but would still pass if raw-group validation were removed while digest checking remained. Existing unresolved tests exercise direct compaction with a matching unresolved source, **not compatibility truncation**. Thus the report's source claim is plausible and inspected, but the required current-active-unresolved refusal across both public rewrite entries lacks complete behavioral evidence.

**Finite closure:** parameterize the existing real-store rewrite proof across both APIs/adapters for (1) stale valid source followed by an unresolved opening, and (2) matching current unresolved source. Require `UnsettledToolGroupError`, byte-identical active log/metadata, no candidate/archive, opening still present. Preserve the existing settled-late-group mismatch test and compatibility success/pinning test. Capture focused sensitivity/green receipts; do not broaden into infrastructure or full-gate execution without consent.

## Receipts, identities and honest limits

- **RH1:** prose reports RED 2 failed/24 passed, GREEN 26 passed, projector regression 44 passed. No separate RH1 raw log is named/present under `logs/*rh1*`; treat those counts as author-reported, not independently reproduced. Later RH2/RH3 runs include the current projector tests.
- **RH2 raw logs inspected:** RED **4 failed/38 passed**, focused GREEN **42 passed**, audited chain **142 passed**, with recorded EXIT 1/0/0. These prove the named one-call/marker cases, not the surviving counterexample.
- **RH3 raw logs inspected:** **8 failed → 8 passed**; scoped regression **592 passed**. Exit statuses are supplied by the repair report; logs inspected end with pytest summaries. That regression predates RH4, not a final-tree full-suite receipt.
- **RH4 raw logs inspected:** **4 failed/10 passed → 14 passed**, final other-module regression **123 passed**; 14+123 is two scoped commands, not a full-suite total. The report describes RED by temporarily removing the two call sites: this is **sensitivity evidence, not proof of original test-first chronology**.
- Receipt discrepancy: `repair-rewrite-snapshot.md` describes `turn7-rh4-regression-first-attempt.log` as **1 failed/136 passed**. The actual named file contains **137 passed**, no failure. The claimed earlier failure/repair history is not established by that receipt; preserve it as an evidence limitation, not a reason to rerun unsafe gates.
- Scoped RH4 mypy log is **failing**, two `BaseMessage` attribute errors at test lines 253–254. “Unchanged prior assertions” does **not** reproduce a baseline; these are current errors with baseline attribution **unestablished**, not a verified exemption. YAML-stub baseline likewise **UNESTABLISHED**. Do not turn baseline archaeology into this repair's side quest.
- Current SHA-256 matches final reports: projector `fb169a38…`, projector tests `c5a337b6…`; compacter `93cb28cd…`, session `7ba507fc…`, summary tests `025eb02f…`; filesystem store `22ffee41…`, compaction-group tests `ec39ee64…`. RH1's older hashes were superseded by RH2. Preflight remains `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`.
- Duplicate-opening test uses a random event ID and can fail deterministic-ID admission before duplicate membership; it is not evidence specifically exercising that membership branch. Retained error replay, additional raw duplicate/conflict branches, mixed A.1 pin coverage and immediate failed-start lease cleanup remain narrower coverage limits, not newly expanded early blockers.

## Stop boundary / ledger

Only the two finite closures above are requested before bounded rereview. Prior append acceptance is not reopened. Deferred interrupted-context §6.4.5, producer activation, T2/T3/T4 and final coverage/gates are **not** additional demands against this slice.

`make test PYTEST_WORKERS=6` remains **BLOCKED by other fixture consent**, with no exclusions/substitutes/mode evasion; full static **UNRUN**. No executable mutation, including the sole consented existing deploy-worker temp `bin/curl` fixture (not run); no installer/herdr/package/system/infrastructure, git-write/publish or nested-agent operation. Exact DeepSeek primary/default/no-fallback instruction preserved; no model fallback used or runtime-model identity attested by this report. Requested review route is `gpt-6.1-sol` high; independent final review and completion remain mandatory and pending.

Preserve supplied counters: **turn 7, dispatch 6/20**, prior partial **7/4/4/8/8/11**, ceiling **60 turns**, **12 execution retries**, **no abort**. No execution retry or phase progression claimed. Historical counters/status paragraphs in the handoff do not override this supplied ledger or this REVISE advisory.
