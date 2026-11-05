# Claude fragment fix — final independent review

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

---

## Historical review — REVISE (superseded by the re-review above)

2026-11-03. Independent of implementation authorship; read-only source/test review, with only this documentation artifact written. Turn 1 / dispatch 7 as supplied; unlimited workflow turn/dispatch budgets; no nested agents or retries. This is Step 2, not workflow completion.

Contract: the user's original early/blockwise native AssistantMessage repair and CF01–CF06 in `claude-fragment-fix-handoff.md`, including its final closure. No follow-up support or unrelated bridge feature acceptance. Reviewed actual response assembly, runtime, raw transport guard, downstream tool publication, official installed SDK parser, feature tests and supporting journey transport. Read repository README/RESEARCH, KB entry/slo README/gotchas and vendored review/workflow, engineering, Python and testing guidance. Broader dirty work is not approved by this review.

## Executed verification

CWD `/root/Code/claude-bridge/slo`:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest -q tests/bridges/claude tests/cli/test_claude_bridge.py
```

Exit 0: **178 passed, 38 warnings, 7.21 seconds**, no skips reported. Warnings are pythonjsonlogger, LangGraph and Pydantic deprecations. This independently confirms the author's count, not completeness of the acceptance contract. Findings below are source-derived paths missing from that gate, not claimed newly executed reproductions.

## Requirement / evidence map

| ID | Assessment | Inspected and rerun evidence |
|---|---|---|
| CF01 early fragments | Implemented for supported valid messages | `reconcile_echo` defers open-response semantic comparison; `_complete` validates before assigning calls. Early-fragment test asserts empty calls before stop; official SDK multi-round journey passes. |
| CF02 no duplicate text/tools | Implemented for covered individual/cumulative/replay shapes | Stream is sole output source. Tests assert ordered a/b calls, exact persisted assistant list `['Hello bridge']`, four calls/results, one completion, one native prompt and one transport close. |
| CF03 identity-aware old-response reconciliation | Partial | Retained snapshots validate identified late echoes without changing current text/calls; changed late/missing-ID tests pass. Malformed falsey identity bypass remains R4. |
| CF04 strict malformed/conflict/unfinished rejection | Partial | 24 negative boundary journeys assert no tool/result/success events in both stdout and real history, one persisted failure and close. JSON boolean, scope, wire bookkeeping, unknown raw blocks and malformed deltas are covered. Decoded nonfinite JSON remains R5. |
| CF05 validated execution boundary / real host journey | Implemented for covered shapes | Transport → official SDK parser → runtime → assembly → tool bridge publication → production graph/tools → filesystem history is exercised, with vendor wire/auth substituted. R5 leaves a malformed-input boundary gap. |
| CF06 bounded retention / compatibility | Implemented within documented admission-budget contract | Both completed snapshots fit before later admission fails; distinct pending contents without UUID fit before third fails; production-limit journey rejects before tools publish. No eviction; missing metadata does not clear native session scope. Not an exact heap or transient-allocation bound. |

## Prior findings

- **R1 CLOSED for fragment equality:** canonical serialized JSON comparisons distinguish nested booleans/numbers for content and UUID replay; both direct and negative SDK journey assertions pass. R5 is a separate decoding path, not a claim that these equality tests failed.
- **R2 CLOSED:** native session binding is distinct from host session, omissions do not reset it, supplied parent scope rejects before stream/echo processing. Four negative journeys exercise both envelope types.
- **R3 CLOSED:** raw streamed block starts reject assembly-owned `stopped` and `partial_json` before model construction. Both negative journeys prohibit publication.
- Raw unknown-block closure is sound: the transport rejects unsupported kinds before the SDK can silently discard them; supported extra metadata remains intentionally outside semantic corroboration.

## Blocking findings

### R4 — Medium: malformed falsey response IDs silently select the current response

**Requirement:** CF03/CF04, identity-aware reconciliation and strict malformed/unknown-identity rejection.

**Where:** `src/bridges/claude/sdk/response.py:248–250`; raw guard in `sdk/transport.py:43–51` does not validate identity types.

**Evidence:** `identity = message.message_id or self.response_id` conflates absent/legacy empty-string metadata with JSON `false`, `0`, `[]` and `{}`. The official SDK parser passes `data['message'].get('id')` directly to its dataclass without type validation. Thus an assistant envelope with `message.id: false` and otherwise matching content is bound to the active response, admitted, and can corroborate at message_stop rather than being rejected. This is not the explicitly supported absent/empty-string compatibility case.

**Repair:** Validate supplied identity type before fallback. Preserve the documented None/empty-string compatibility behavior, but reject non-string supplied identities; use explicit absence handling rather than general truthiness. Keep the validation in the existing response/transport boundary owner.

**Closure:** Add feature regression cases for false/zero/empty-container IDs through official parsing and at least one real negative SDK journey with a pending valid tool. Assert bounded protocol failure, no executable publication or successful completion, and retain positive missing-ID and late-ID tests.

### R5 — High: nonfinite JSON hidden inside input_json_delta reaches executable calls

**Requirement:** CF04/CF05, strict malformed JSON rejection before the validated execution boundary; handoff R1 also explicitly claims nonfinite values fail.

**Where:** `src/bridges/claude/sdk/response.py:58–68`, `:213–224`.

**Evidence:** `_admit` validates the event as JSON, but `partial_json` is a string there. `complete_call` uses default `json.loads`, which accepts `NaN`/`Infinity` and can turn an overflowing exponent such as `1e400` into infinity. Its result is passed directly into `ClaudeToolCallDAO.arguments` (`dict[str, JsonValue]`, without a finite-number validator). If there is no assistant echo, `_complete` never calls `json_identity` on the decoded arguments before assigning `calls`. The downstream publication path uses default `json.dumps` for its size check, not strict finite-number validation. A complete tool response containing `{"value":NaN}` in delta text therefore bypasses the strict serialization check on decoded values. Echoes are optional, so safety cannot depend on their arrival.

**Repair:** Validate the decoded argument object with the same strict JSON policy before constructing/publishing the executable call, including overflow-created nonfinite values. Keep the error bounded and payload-free. Do not rely only on parse_constant, which does not address exponent overflow.

**Closure:** Add direct assembly cases and a no-echo SDK/graph/history negative journey for nonfinite delta JSON; assert protocol failure and zero tool/result/success publication. Include representative finite JSON success to preserve valid argument handling. Rerun the authorized feature gate.

## Assertion quality and conventions

The tests meaningfully inspect forbidden effects and persisted outcomes rather than just exit codes. Retention closure fixes the previously weak first-response-only and repeated-identical-content evidence. The positive journey proves exact final assistant content and tool counts; its four-call count alone is supplemented by the direct ordered-call test and existing feature journeys. No native-process parity claim follows from these assertions.

The hard-rules pass was scoped to the changed Python boundary and tests, not unrelated CLI/TUI/graph code. Stateful SDK ownership and thin transport delegation are appropriate; no database/router layers are applicable. The language-specific decomposition guidance treats length as a signal rather than a mechanical quota. `reconcile_echo` could profitably separate replay registration from pending-fragment admission, but this is not an additional correctness blocker. Static/formatter conformance was not tested and is not claimed.

## Limitations / completion disposition

- Full suite and unrelated tests explicitly excluded by user; this is an authorized gate limitation, not a newly invented blocker.
- No static, formatter, build, mutation or new ad-hoc execution was run; only the existing feature pytest command above.
- Live native parity and exact original-session causality remain **unverified**. Official SDK scripted journeys establish parser/control/host wiring, not actual CLI version/order/account behavior.
- Late contradictions after a valid published boundary cannot undo earlier execution; this documented limitation is unchanged.
- Retention is a conservative serialized-input admission budget that also charges duplicates, not an exact Python heap bound; transient parsing allocations remain outside it.
- No follow-up conversation support reviewed or requested.

### Finite closure checklist

- [ ] R4: reject supplied malformed identity types without breaking legacy omission compatibility.
- [ ] R5: reject nonfinite decoded delta arguments before calls are published.
- [ ] Add the targeted feature regressions and rerun the authorized 178-test feature gate plus new cases.
- [ ] Independent affected-boundary re-review, then workflow completion reconciliation.

No external action, commit, source edit, test edit or nested dispatch was performed.
