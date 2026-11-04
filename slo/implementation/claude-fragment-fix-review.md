# Claude fragment fix — final independent review

> Commit excerpt: recorded phase evidence, not a new verification run.
> Superseded dispatch histories are omitted from this commit and preserved
> in the local working copies. References to historical sections or mappings
> "below" refer to those originals. The completion document contains the
> consolidated acceptance mapping; handoff verdicts describe their own phase.

## Current verdict: READY — independent re-review, turn 2 / dispatch 2

2026-11-03. Independent of implementation authorship. R4 and R5 are **CLOSED**; no remaining blocking finding identified in the original CF01–CF06 fragment contract. This is feature-scoped review acceptance, not whole-bridge certification, workflow completion, or merge authorization. Supplied turn/dispatch budgets are unlimited; no nested agents launched.

Reviewed the current handoff, prior findings, actual `sdk/response.py`, runtime publication path, raw transport guard, fragment and boundary tests, and injected SDK journey assembly. Guidance: vendored review-feature-code, engineering routing/ownership/review/testing, Python conventions/declarative structure and hard-rules checklist, and test-verification policy. Reused the earlier review's unchanged evidence and scope; did not restart unrelated audits. Only this review artifact was edited.

### Closure evidence and affected boundaries

| Finding | Current implementation and inspected assertions | Disposition |
|---|---|---|
| R4 — malformed falsey identity | `src/bridges/claude/sdk/response.py:251–255` validates supplied identity type before explicit None/empty-string fallback. False/zero/containers cannot reach response lookup or pending-echo admission. Eight official-parser cases reject non-string IDs; two positive cases preserve None/empty compatibility. Four pending-tool SDK/graph/history journeys reject false/zero/empty-list/empty-dict before message_stop publication. | CLOSED |
| R5 — nonfinite decoded delta JSON | `src/bridges/claude/sdk/response.py:64–68` calls strict `json_identity` on decoded arguments before constructing the call. `allow_nan=False` rejects nested NaN, both infinities and positive/negative exponent overflow; no assistant echo is required. Five direct cases assert the exact payload-free protocol error and empty calls; five no-echo SDK/graph/history journeys prohibit tool/result/success publication. Finite nested JSON still publishes successfully. | CLOSED |

The R5 check is inside the existing complete-call owner, so it also applies when tool blocks are compared against echoes. `_complete` constructs the entire candidate tuple and validates echoes before assigning `self.calls`; a failed call cannot publish a prefix. Runtime calls `publish_tool_batch` only after `consume` returns a validated boundary. R4 preserves identified old-response lookup and only applies fallback to the explicitly supported legacy cases. Neither repair adds output, changes portable event schemas, or moves execution into native callbacks.

The nine new negative journeys inspect both stdout and real temporary history: no `tool_call`, `tool_result`, or `run_completed`, one persisted `run_failed`, bounded protocol diagnostic, one native prompt and one transport close. Their nonfinite branch sends no assistant echo. These are observable failure-cutoff assertions, not just exception checks. Vendor transport/auth is substituted; SDK parsing, runtime, host graph and filesystem history remain real.

### Original acceptance contract reconciliation

| ID | Status | Current evidence |
|---|---|---|
| CF01 — early/blockwise fragments | Implemented | Early thinking/text/tool echoes are deferred until the complete boundary; calls remain empty before stop. Positive official-SDK journey passes. |
| CF02 — no duplicate text/tools | Implemented | Individual/cumulative/replayed fragments, ordered a/b calls, duplicate-content multiplicity, exact four persisted calls/results and assistant list `['Hello bridge']`. |
| CF03 — identity-aware late reconciliation | Implemented | Old-response snapshots corroborate without changing current output; changed late/missing-ID cases reject. R4 now rejects malformed supplied IDs while retaining legacy compatibility. |
| CF04 — reject malformed/conflicting/unfinished input | Implemented for the agreed fragment contract | R1 JSON-sensitive equality, R2 scope, R3 wire-bookkeeping guards, malformed delta/raw-block matrices and unfinished-boundary tests remain passing. R4/R5 close the identified safety gaps. |
| CF05 — validated execution boundary and host journey | Implemented with stated native limitation | Positive multi-round SDK/graph/tools/history journey and 33 negative boundary journeys pass, including all nine added R4/R5 journeys. No executable publication on rejected boundaries. |
| CF06 — bounded retention and compatibility | Implemented within documented budget contract | Multiple retained snapshots, distinct pending contents, UUID/thinking/signature budgets, production-limit failure and omitted session metadata regressions pass. No eviction or portable schema change. |

R1–R3 remain closed. The scoped Python hard-rules post-hook found no new blocking issue in these repairs: validation remains in the stateful boundary owner, new guards are flat, calls/signatures retain explicit contracts, errors are bounded, and no unrelated framework layers were introduced. The existing optional reconciliation-decomposition suggestion remains nonblocking; exact formatting/static conformance is not claimed. Test-first RED receipts in the handoff were inspected as author-reported history, not independently rerun or represented as fresh reviewer reproductions.

### Independently executed verification

CWD `/root/Code/claude-bridge/slo`:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest -q tests/bridges/claude tests/cli/test_claude_bridge.py
```

**Exit 0: 203 passed, 47 warnings, 8.21 seconds. No skips reported.** Warnings are pythonjsonlogger, LangGraph and Pydantic deprecations. This independently confirms the reported feature gate and reruns the prior 178 cases plus 25 additions. No other test, static, formatter, build or ad-hoc execution gate was run.

### Limitations and disposition

- **Full suite deferred explicitly by the user.** No full-suite or unrelated-feature acceptance is claimed; this approved limitation does not reopen the fragment review.
- **Live-native parity and original-session causality remain unverified.** Scripted official-SDK journeys prove parser/control/host wiring, not actual CLI version/order/account behavior or the exact cause of the original session failure.
- Late contradictions after an already valid published boundary cannot undo earlier execution. This unchanged causality limitation is not concealed by READY.
- Retention is a conservative serialized-input admission budget, including duplicates, not an exact heap bound; transient parsing allocations remain outside it.
- Supported vendor block metadata remains intentionally outside semantic corroboration. SDK internal transport compatibility requires reassessment on upgrades.
- No follow-up conversation support, unrelated dirty work, broader bridge lifecycle certification, commit, source/test edit, nested dispatch or external action is included.

Closure checklist: R4 repair verified; R5 repair verified; targeted regression and affected feature gate verified; independent affected-boundary review complete. Separate workflow completion reconciliation and the user-deferred broader gate remain outside this review.
