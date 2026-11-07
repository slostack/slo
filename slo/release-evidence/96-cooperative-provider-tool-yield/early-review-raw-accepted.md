# 96.a.2 — bounded raw-history closure rereview

**READY — advisory acceptance of exactly the RH2 anchor and RH4 rewrite-proof closures.** No remaining concrete blocker found in these two closures. This is independent early feedback inside Step 1, **not** final review, feature acceptance, phase progression or a completed workflow turn. RH1 and RH3 remain accepted unchanged at their previously bounded scope.

## Scope and authority

Reviewed `early-review-raw-repairs.md`, `repair-anchor-rewrites.md`, current handoff, routing record, actual projector and both rewrite adapters, `test_projector_tool_groups.py`, `test_compaction_tool_groups.py`, and retained turn-8 logs against the original specification:
`/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md` §§6.1–6.3 (A8/A12).

Read README first; consulted KB Welcome → slo/README and gotchas. Root RESEARCH.md is absent; not created in this report-only assignment. Live `SLO_SKILL_DIR` and `SLO_SKILLS_DIR` both equal `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`. Consulted its INDEX, supplied available-skills manifest, engineering routing/review/ownership/testing, Python root/review/typed-keyword/declarative rules and testing policy. The actual installed `orchestration/workflows/code-test-review.md:181–195` governs this early checkpoint; workflow counting comes from `orchestration/workflows/SKILL.md`, not a similarly named cadence skill. No skill edits or new framework.

Read-only Git inspection confirms branch `message-queue`, HEAD/baseline `82c3f5c6de9345af34a673a3d975366ca8c1624c`.

## Requirement → actual source → behavioral evidence

| Closure | Source and actual test assertions | Disposition |
|---|---|---|
| **RH2: complete projection anchor before ANY real result** | `history/projector.py:151–190`: `add_result` now refuses `anchor_opening_index is None`, alongside declared membership, own earlier opening and duplicate-result guards. Anchor recording remains in `add_opening`; the invariant stays with the raw-group owner. `_context_event_slice:487` validates before completed/excluded-turn or compaction selection; both context APIs reach it before reconciliation. | **Closed.** No sorting, invented result or healing is used to settle malformed raw truth. |
| **RH2: surviving sibling counterexample rejected on both adapters** | `test_projector_tool_groups.py:366–404` ordinarily appends `opening(b) → result(b,success,b-real) → opening(a) → result(a,error,a-real)` and terminal. Both real adapters must raise `UnsettledToolGroupError` from raw validation, context, excluded-turn context and message-history build. | **Closed.** This targets the actual prior defect, not merely result-before-own-opening. |
| **RH2: valid exact replay/no healing and partial no-start preserved** | `test_projector_tool_groups.py:409–450` asserts exactly Human/AI/Tool/Tool, exact ordered calls and both real result ID/status/content triples (`a/success/a-real`, `b/error/b-real`). `:208–247` retains exact unaffected `z/success/ok` alongside disposed partial siblings; `:478–499` preserves full anchor plus marker with a missing sibling. | **Closed within this scope.** Exact shape and content exclude fabricated placeholders. |
| **RH4: both rewrite APIs/adapters validate current unresolved evidence before effects** | Flat sync entries `filesystem_store.py:1625,1693` first delegate to `_require_current_active_snapshot_sync:1714–1742`; it reads current active history, validates raw groups, then compares snapshot digest. Public entries serialize through the existing lock; tree entries delegate to this same owner (`tree_store.py:348–374,423–455`). | **Closed; source guard unchanged.** Validation precedes candidate construction, archive/activation and metadata mutation. |
| **RH4: stale AND matching-current unresolved sources fail by the required type** | `test_compaction_tool_groups.py:428–493`: 2 adapters × 2 public APIs × 2 source scenarios. Stale is a valid prior snapshot plus a newly appended unresolved opening; current includes that same opening. Each requires `UnsettledToolGroupError`, byte-identical active log/metadata, no checked candidate/archive artifacts and opening retained. Existing settled-late-group mismatch (`:374–425`) and compatibility success/pinning (`:498–530`) remain. | **Closed.** The stale case independently distinguishes raw validation from digest-only rejection. Source inspection establishes the before-effects ordering. |

The added production condition is a cohesive guard, not duplicated caller policy; signatures remain explicitly typed and meaningful multi-argument domain calls use keywords. No regression identified within these closures; this is not a full-tree no-regression certification.

## Retained receipts, not new execution

Actual logs inspected and SHA-256 matched `repair-anchor-rewrites.md`:

- `logs/turn8-rh2-red.log`: **2 failed / 36 passed**; both failures are the new sibling case, `DID NOT RAISE UnsettledToolGroupError` at raw validation. Together with the repair narrative this supports the reported failing-first sequence; retained output alone is not an independently witnessed edit timeline.
- `logs/turn8-rh2-green.log`: **38 passed**.
- `logs/turn8-rh4-green.log`: **22 passed**, including the eight new combinations. This is new coverage over an already guarded implementation; **no RH4 RED claimed**.
- `logs/turn8-regression.log`: **261 passed**, a focused regression command only, not full-suite evidence.
- Retained Black log: three files unchanged. Retained mypy log: **9 errors / 2 test files**, checking three files. Full static remains **UNRUN**. The handoff's “pre-existing” attribution is **not established**; test-mypy and YAML-stub baseline attribution remain **UNESTABLISHED**, with no exemption endorsed.

Live source hashes match the report: projector `0ddab926…`, projector tests `fd080a4e…`, compaction tests `2a12d61b…`, unchanged flat rewrite owner `22ffee41…`. Preflight remains `10fe2372f972374580d6071578c543edad98fd811a43ce2b0857cdb282183638`. Prior historical receipt limitations are not erased or upgraded by this rereview.

## Stop boundary and corrected ledger

**Turn 8 remains ongoing, dispatch 2/20; 0 completed workflow turns.** Prior partial dispatch counts **7/4/4/8/8/11/6**; ceiling **60 turns**; **12 execution retries**; **no abort**. The author's increment is not “turn 8 complete.” This advisory adds no execution retry or phase progression.

A.2 and the actual urgent runnable milestone remain **INCOMPLETE / unimplemented**. Independent `gpt-6.1-sol` high final review and completion remain pending. No new deferred scope is invented; existing producer/T2/T3/T4, interrupted-context and final-gate obligations are neither waived nor demanded as extra closure work here.

`make test PYTEST_WORKERS=6` remains **BLOCKED by other fixture consent**, with no exclusions, substitute or mode evasion. **No tests, collection or static checks executed in this rereview.** No product/model run, executable mutation, installer/package/system/infrastructure operation, commit/push/merge/PR or nested agent. The sole narrowly consented existing deploy-worker temp `bin/curl` fixture (0755, child PATH, verified root) was **not run**; no other fixture authority inferred.

Primary instruction remains **exact DeepSeek/default/no fallback**. Historical fallback permission in routing/repair prose does not override the current no-fallback instruction. No fallback used here and no runtime-model identity attested.

Only this new report was written; source/tests, SLO.md, docs, preflight, current handoff and prior evidence were preserved.
