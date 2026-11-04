# Claude fragment fix — independent completion check

> Commit excerpt: recorded phase evidence, not a new verification run.
> Superseded dispatch histories are omitted from this commit and preserved
> in the local working copies. References to historical sections or mappings
> "below" refer to those originals. The completion document contains the
> consolidated acceptance mapping; handoff verdicts describe their own phase.

## Verdict: COMPLETE / READY (feature-scoped)

2026-11-03 — Code-Test-Review Step 3, supplied turn 2 / dispatch 3. Workflow turn/dispatch budgets unlimited by explicit user instruction; no nested dispatches, source/test changes, commits or unrelated gates performed.

**All six nondeferred acceptance items CF01–CF06 are verified; all five findings R1–R5 are closed.** No remaining blocker identified in the agreed fragment repair. This is completion of the tested parser/reconciliation fix, **not confirmation that the original production session is resolved**, whole-bridge acceptance, native compatibility certification, or merge/deployment authorization.

## Sources and method

Contract: `implementation/claude-fragment-fix-handoff.md`, including its original stable CF01–CF06 table and subsequent finite hardening/repair requirements. Final independent review: `implementation/claude-fragment-fix-review.md`, current turn-2 READY section; historical REVISE findings were reconciled rather than treated as current blockers or discarded.

Read actual implementation and test assertions, not just author/reviewer verdicts: `src/bridges/claude/sdk/response.py`, `sdk_runtime.py`, `transport.py`; `tests/bridges/claude/test_fragments.py`, `test_response_boundaries.py`; the official-SDK scripted transport and adapter injection in `tests/cli/test_claude_bridge.py`, and shared isolation fixtures. Independently reran the authorized feature gate below on the current working tree. Existing unrelated dirty work was not assessed or changed.

Reused the handoff routing: Python 3.11, pinned Claude SDK boundary, pure response state machine and in-process SDK/graph/filesystem journeys. Consulted README, local RESEARCH, KB Welcome/slo README/gotchas, vendored completion skill, exact code-test-review workflow, engineering routing/ownership/testing, coding rules, test-verification policy and Python conventions. No database, new CLI verb, TUI or follow-up feature was added to this acceptance contract. The user's explicit artifact destination overrides historical KB advice against repository documentation additions.

## Acceptance reconciliation

Implementation paths below are relative to `src/bridges/claude/sdk/`; tests are relative to `tests/bridges/claude/`. Every listed test is included in the fresh passing feature gate.

| ID | Required behavior / boundary | Status | Inspected implementation and executable evidence | Remaining blocker |
|---|---|---|---|---|
| CF01 | Valid early/blockwise thinking, text and tool fragments; no premature calls | Done | `response.py:reconcile_echo` stores open-response echoes; `_complete` checks them before assigning calls. `test_early_fragments_validate_once_at_complete_boundary` asserts empty calls before each block stop, ordered calls only at message_stop; positive SDK journey also supplies early duplicate echoes. | None |
| CF02 | Multiple calls, individual/cumulative/replayed fragments, no duplicated output | Done | Echoes never append text or publish calls. UUID replay uses response identity plus canonical payload; pending semantic duplicates do not add output. Early-fragment and conflict-matrix tests cover ordered calls and duplicate-content multiplicity; `test_early_fragments_cross_sdk_graph_tools_and_history` reads back exactly four calls, four results, one completion, assistant content exactly `['Hello bridge']`, and four native result receipts. | None |
| CF03 | Response correlation and identified late fragments | Done | Retained snapshots are keyed by native response ID, independently of delivery UUID. Early-fragment test corroborates an old response after a new start without changing new text/calls. Conflict matrix rejects changed late and missing-ID misbinding. R4 tests reject supplied non-string IDs while None/empty string retain current-response-only compatibility. | None |
| CF04 | Strict conflicts, malformed input and unfinished streams reject | Done for agreed fragment contract | Canonical JSON distinguishes booleans/numbers; block order, multiplicity, names/arguments, thinking/signatures and UUID contradictions reject. Scope, raw bookkeeping and malformed delta guards execute before publication. `transport.py` rejects unsupported/malformed raw assistant block containers before lossy SDK parsing. Direct conflict/delta matrices plus 33 negative SDK journeys exercise failures, including R4/R5, invalid JSON, duplicate IDs, forbidden mixed calls and unfinished boundaries. | None |
| CF05 | Validated, nonduplicated executable publication through real host wiring | Done | `_complete` constructs the full candidate tuple and validates all echoes before assigning `calls`; runtime publishes a batch only after `consume` returns a validated boundary. Positive journey traverses HeadlessRunner → production session/SDK/runtime → graph/tools → real temporary history. Negative journeys assert no tool_call/tool_result/run_completed in both stdout and history, one persisted failure, one prompt and one transport close. | None within scripted SDK scope |
| CF06 | Bounded retained reconciliation state and compatibility | Done within documented admission-budget contract | `_admit` charges every event/echo, including duplicates, against one invocation budget; no evidence eviction. Tests cover UUID, thinking/signature, pending data and snapshots; strengthened tests admit two complete responses before later admission fails and two distinct UUID-less pending fragments before the third fails. Production-limit journey rejects before pending tool publication. Missing metadata does not clear native session binding; supported vendor metadata is accepted; portable event shapes remain unchanged in this repair. | None |

The direct parser/state-machine tests prove detailed decisions; the official-SDK journeys prove the actual host wiring and persisted outcomes. Vendor transport/auth observation is substituted. SDK parsing/control, response assembly, runtime, graph execution and filesystem history are real. These are not live-native process tests.

## R1–R5 closure check

| Finding | Independently inspected closure | Status |
|---|---|---|
| R1 — Python equality conflates JSON booleans and numbers | `json_identity` uses sorted canonical serialization with `allow_nan=False`; semantic tool comparison and fragment replay/dedup use it. Nested true/1 and false/0 direct cases plus negative journeys reject before publication. | Closed |
| R2 — native session/parent scope | Runtime validates StreamEvent scope before consume; echoes validate scope before reconciliation. First supplied native session binds independently of host session; omitted metadata does not reset it; any supplied parent rejects. Four negative scope journeys and omission regression pass. | Closed |
| R3 — wire injection of internal bookkeeping | `_start_block` rejects presence of `stopped` or `partial_json` before model construction. Direct regressions and two negative journeys prohibit fabricated completion/publication. | Closed |
| R4 — malformed falsey identity fallback | `reconcile_echo` validates supplied message ID type before explicitly selecting None/empty-string fallback. Eight official-parser malformed-ID cases, two compatible fallback cases and four negative pending-tool journeys pass. | Closed |
| R5 — nonfinite JSON decoded from deltas without an echo | `complete_call` validates decoded arguments with strict `json_identity` before constructing a call. Five direct and five no-echo journeys reject NaN, both infinities and positive/negative exponent overflow; finite nested JSON publishes successfully. Errors are payload-free and bounded in the inspected assertions. | Closed |

The current independent final review is accepted. Its closure claims agree with current source and assertions and are corroborated by this completion check's fresh execution. Historical author RED receipts are not represented as newly reproduced RED evidence.

## Executed verification

CWD: `/root/Code/claude-bridge/slo`.

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest -q tests/bridges/claude tests/cli/test_claude_bridge.py
```

**Exit 0 — 203 passed, 47 warnings, 8.52 seconds. No skips reported.** Warnings are pythonjsonlogger, LangGraph and Pydantic deprecations. This is fresh completion-phase evidence, consistent with the reviewer's separate 203-pass/47-warning run. No other test/static/build/formatter gate was executed.

## Exceptions and limitations

- **Full non-e2e suite: Deferred by explicit current user instruction until all separate problems are fixed.** Only feature pytest was authorized. No full-suite pass or absence of unrelated regressions is claimed. Closure of this deferred gate requires later user authorization and execution after the separate repairs.
- **Live-native parity and original-session causality: Unverified.** The tested repair accepts the specified early/blockwise fragments and rejects covered invalid streams. It does not establish native CLI version/order/account behavior or prove that this defect caused, or now resolves, the original session failure. Those claims require separate authorized native reproduction/parity evidence.
- Static, formatter, type/build and live-native checks were not executed under the pytest-only scope; exact formatting/static conformance is not claimed.
- The 32 MiB retention policy is a conservative serialized-input admission budget, not an exact Python heap bound. Duplicates consume budget; sufficiently long valid invocations intentionally fail. Transient SDK parsing/serialization allocations are outside that bound.
- A contradiction arriving after an already validated and published boundary cannot undo earlier execution. The no-publication guarantee concerns rejection before that boundary, not retroactive rollback.
- Supported vendor metadata is intentionally ignored for semantic corroboration. The SDK internal transport interface is pinned and requires reassessment on SDK upgrades.
- No follow-up conversation support, whole-bridge lifecycle certification, unrelated dirty-work acceptance, commit or external action is included.

**Disposition:** No implementation revision requested for CF01–CF06. The scoped Code-Test-Review completion gate is READY with the explicit broader-suite deferral and native/causality limitations above.
