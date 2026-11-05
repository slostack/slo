# Claude fragment fix — initial runnable milestone

## Current verdict: READY for independent re-review — revision turn 2 / dispatch 1

Current closure evidence (2026-11-03) is in **R4/R5 revision closure** below.
The independent review's REVISE verdict remains the last reviewer verdict; this
READY is author readiness only, not independent acceptance or workflow completion.

## R4/R5 revision closure

Scope: supplied turn 2 / dispatch 1, unlimited workflow budgets. No agents,
detached workflows, commits, full suite, static checks or unrelated gates.
Preserved existing dirty work and valid fragment behavior. Reused the handoff's
Python/SDK assembly and real graph/history routing; read governing vendored shared
ownership/testing, coding rules/cadence/test policy, declarative structure and
Python conventions, keyword/type/docstring and SDK-client guidance. README,
RESEARCH, KB entry/slo README/gotchas and independent review consulted.

### Repairs and coverage

- **R4 / CF03–04:** `NativeResponseAssembly.reconcile_echo` validates every supplied
  message ID as a string before explicitly falling back for None/empty string.
  Eight official-parser cases cover false, zero, empty/nonempty lists/dicts and
  true/one. None/empty compatibility has two positive cases; existing omitted-ID
  and identified late-fragment cases remain green. Four negative SDK journeys
  carry a pending valid tool and malformed falsey IDs.
- **R5 / CF04–05:** `NativeBlock.complete_call` validates decoded arguments with
  existing strict `json_identity` before constructing a call. This covers nested
  NaN, Infinity, -Infinity and positive/negative exponent overflow, regardless of
  whether any assistant echo arrives. Five direct cases and five no-echo SDK
  journeys cover these forms. A finite nested JSON success case preserves null,
  booleans, integer/floating values, large finite exponent, strings and objects.
- All nine added negative journeys traverse official SDK parsing, runtime,
  production graph and real temporary filesystem history. They assert no
  tool_call/tool_result/run_completed in stdout or persisted events, one persisted
  failure, bounded protocol error, one prompt and one transport close. Direct
  cases assert stream_protocol_failed and no assembly calls; nonfinite direct
  errors assert the exact payload-free diagnostic.

Changed in this revision: `src/bridges/claude/sdk/response.py`,
`tests/bridges/claude/test_fragments.py`,
`tests/bridges/claude/test_response_boundaries.py`, this handoff and local durable
memory. No transport/runtime/CLI implementation changes. Manual affected-source
review confirmed validation precedes executable publication and no echo dependency
remains; this is not independent review or a static-tool conformance claim.

### Exact evidence

CWD `/root/Code/claude-bridge/slo`, same command for RED and GREEN:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest -q tests/bridges/claude tests/cli/test_claude_bridge.py
```

1. Test-first RED: **20 failed, 183 passed, 56 warnings, 8.46s**.
   `/tmp/claude-r4-r5-red.txt`. Four falsey identity cases and five nonfinite
   cases DID NOT RAISE; nonempty containers leaked TypeError; all nine journeys
   failed forbidden-publication assertions. True/one already rejected. The shell
   wrapper returned 0 because it tailed the log after pytest; pytest was failing,
   not a green gate. No assertions were relaxed to obtain green.
2. After the two production repairs: pytest and wrapper **exit 0, 203 passed,
   47 warnings, 9.57s**, no skips. `/tmp/claude-r4-r5-green.txt`.
   Existing 178 cases plus 25 new cases. Warnings are the existing
   pythonjsonlogger/LangGraph/Pydantic deprecations.

Only the authorized feature pytest gate ran, twice. Existing isolated test home
and temporary history fixtures retained; no command stubs or system changes.
Full suite, static/formatter/build checks and live-native parity remain unrun by
scope. Independent affected-boundary re-review and workflow completion remain
pending. No follow-up conversation support or unrelated acceptance claimed.

---

Historical closure evidence (2026-11-03) is appended in **Final acceptance-gap closure** below.
Earlier REVISE verdicts and blocker lists are historical, superseded by that section.
This is not final independent review acceptance or workflow completion.

Not final Step 1 acceptance, final review, or workflow completion. Original contract: current user request for response-scoped native fragment reconciliation, no follow-up conversation support or unrelated fixes. Explicit current request authorizes this repository handoff path (overrides older KB documentation-location advice).

## Accounting and scope

- Branch: `claude-bridge`, HEAD `0995fd3d0c1cff27cd00fa2ed338b6b74f94a9fc`; not main.
- Workflow turn 1, dispatch 3; supplied failure retry 2/max 3. Two prior dispatch rejections were `pool sealed by abort`; no prior agent started. This slice launches no agents and retries no abort.
- User removes workflow turn/dispatch budgets; retry/abort policy still applies. No commits, detached workflows, or nested agents.
- Existing numerous modified files and untracked bridge implementation preserved. Only this slice's files below edited/created.
- Explicit approved gate deferral: ONLY feature-scoped pytest, NO full suite until all separate problems are fixed. No full-suite result claimed. Independent early review, final review and completion check remain required.

## Routing and prerequisites

Python 3.11 / pinned claude-agent-sdk 0.2.176; portable SDK boundary and pure parser/state machine, plus in-process headless/SDK/graph/tools/filesystem journey. No database, HTTP router, CLI verb, UI change or portable event schema change.

Project prerequisites read: README opening and maintainer/style/testing commands; SLO.md supplied context; root RESEARCH.md; KB Welcome.md, slo/README.md (index.md absent), slo/gotchas.md. No nested instructions found beneath src/bridges or tests/bridges.

Guidance source: repository vendored skills, rooted at `/root/Code/claude-bridge/slo/skills/` (no matching personal override in supplied manifest):
- orchestration/workflows/code-test-review.md (exact named workflow)
- engineering/engineering-routing, engineering-ownership, engineering-testing
- coding/coding-rules, code-test-loop, test-verification-policy, declarative-method-structure
- languages/python/python-conventions, named-arguments-and-type-hints, declarative-method-structure, method-docstrings, build-clients (SDK boundary guidance; retained existing portable configuration/lifecycle rather than introducing HTTP/config globals)

Tests replace vendor transport/auth observation only; production SDK parser, runtime, graph, executor and temporary filesystem store remain real. Tests use existing isolated SLO_HOME fixtures; tool target resolves under tmp_path. No native process/provider credentials used.

## Source findings and design

`AssistantMessage.message_id` is parsed from native `message.id`; `uuid` is delivery identity, not response identity. SDK also exposes parent_tool_use_id, session_id, error and stop_reason. StreamEvent carries event, uuid, session_id, parent_tool_use_id. Inspected installed types and parser with inspect.getsource in slo-harness.

`/tmp/pi-single-tool.jsonl` exists: individual thinking/tool/text AssistantMessages share response IDs and occur before stop boundaries. `/tmp/pi-bridge-reference/index.ts:1459–1500` explicitly treats later blocks of the same ID as continuation, not replacement. No fixture contents copied into production code.

Owner stays NativeResponseAssembly: preserve block kind and payload; record fragment delivery identity; defer comparison while response is open; validate each echo as an ordered subset of complete streamed blocks before assigning executable calls. Retain completed response snapshots to validate identified late fragments without attaching them to a newer response. Stream remains sole output source, so echoes never append text/tools. Reject duplicate tool IDs, unknown response IDs and conflicting UUID replays. Existing unidentified synthetic callers bind to current response only.

Rejected shortcut: simply ignoring echoes while open hides contradictions; flattening fragments remains incorrect. No portable events changed. message_stop remains executable boundary; terminal rejects unfinished stream. A conflict arriving after an already valid boundary cannot retroactively undo published execution; it fails subsequent processing.

## Files

- `src/bridges/claude/sdk/response.py`: block-aware, response-scoped reconciliation; deferred validation; thinking/signature accumulation; duplicate call-ID validation; initial text handling.
- `src/bridges/claude/sdk/sdk_runtime.py`: pass actual AssistantMessage to assembly instead of flattening.
- `tests/bridges/claude/test_fragments.py`: 6 cases including SDK/graph/history journey.
- This handoff.

Pre-edit copies for author diff inspection: `/tmp/claude-response-before.py`, `/tmp/claude-runtime-before.py` (bridge files were already untracked, so HEAD diff does not show incremental changes).

## Stable acceptance IDs and evidence

| ID | Required outcome | Current evidence / status |
|---|---|---|
| CF01 | Early thinking/text/tool fragments accepted without premature calls | `test_early_fragments_validate_once_at_complete_boundary`; checks calls remain empty before stop |
| CF02 | Multiple tool calls and duplicate fragments never duplicate output | same test: ordered a,b calls; CF05 persists exactly four calls/results |
| CF03 | Identified late fragments reconcile to original response | same test sends full old-response fragment after next start; current text/calls untouched |
| CF04 | Conflicts, malformed and unfinished streams reject | parameterized text/identity/uuid/unfinished tests; existing 10 response-boundary journey cases all pass |
| CF05 | Representative real SDK boundary journey | `test_early_fragments_cross_sdk_graph_tools_and_history`: one native query, three tool responses/four actual host tools, duplicate early fragments, final completion and real history readback |
| CF06 | Compatibility and bounded retention | portable event types unchanged; remaining hardening below; NOT acceptance-ready |

## Exact verification

CWD `/root/Code/claude-bridge/slo`. Every pytest command used this prefix:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest ...
```

1. `-q tests/bridges/claude/test_fragments.py`: RED, exit 1, 5 failed/2 warnings (new message argument unsupported before implementation). This is interface-sensitive RED, not a recorded end-to-end pre-fix failure.
2. `-q tests/bridges/claude/test_fragments.py tests/bridges/claude/test_response_boundaries.py tests/cli/test_claude_bridge.py`: GREEN, exit 0, 21 passed/17 warnings (before adding new journey).
3. Same command after journey: exit 0, 22 passed/18 warnings, 3.70s.
4. Same command after formatting/type annotation cleanup: exit 0, **22 passed/18 warnings, 4.42s**.

Warnings: existing pythonjsonlogger, LangGraph and Pydantic deprecations. Formatting only: `poetry run black src/bridges/claude/sdk/response.py src/bridges/claude/sdk/sdk_runtime.py tests/bridges/claude/test_fragments.py`, exit 0. No broader tests/static suite run.

Initial unactivated `poetry run python` could not import claude_agent_sdk. Correct existing environment selected explicitly, no installation or system change. Subsequent SDK inspection and pytest used slo-harness successfully.

## Remaining hardening / reviewer closure targets

1. CF06: bound aggregate retained snapshots, fragment UUIDs, pending echoes and thinking/signature bytes; existing response-ID cap alone is not a sufficient aggregate bound. Add limit regressions before final acceptance.
2. CF04: expand direct conflict matrix to tool args/name, thinking/signature, changed late fragment and malformed native delta shapes; add negative fragment journey asserting no persisted tool publication before rejected boundary.
3. CF03/06: review missing-ID fallback ambiguity and native session/parent scope checks. Current compatibility fallback is deliberately only current response, not heuristic matching across old responses.
4. CF02: strengthen journey text assertions (currently parser text and exact persisted tool counts, not full persisted assistant-text equality). Review identical content blocks and partial/cumulative ordering cases.
5. SDK silently skips some unknown raw block kinds: typed reconciliation cannot reject raw fields discarded by upstream parser. Determine necessary narrow transport-boundary validation without changing portable event types.
6. Live native parity not executed; scripted transport proves official SDK parsing/control and host behavior, not native process/version ordering beyond inspected recording.
7. Obtain independent early read-only review now; continue hardening afterward, then independent final review/completion and user-authorized full gate when separate issues are fixed.

## Continuation — early review R1–R3 repairs

Accounting: supplied early feedback remains Step 1 / turn 1 / dispatch 5;
no dispatch or agent launched here. Workflow budgets unlimited by user, maximum
three failure retries and no abort retries retained. Test-first RED runs below
are development evidence, not restarted workflow tasks. No commits/full suite.

Changed only response.py, sdk_runtime.py, test_fragments.py,
test_response_boundaries.py and this handoff during this continuation.

- CF04/R1: canonical JSON serialization replaces Python/Pydantic equality for
  tool payloads, UUID replay and pending deduplication. Object keys are sorted,
  arrays ordered; true/1 and false/0 differ at every depth. Numeric lexical
  representations (1 versus 1.0) deliberately remain distinct. Nonfinite or
  unserializable values fail with the bounded protocol error.
- CF06/R2: assembly binds the first supplied **native** session, not host session.
  Both StreamEvent envelopes and AssistantMessages check scope before publication.
  A supplied parent (even empty string) rejects; absent/None parent means root.
  Missing session metadata is backward-compatible: neither sets nor clears the
  binding. Missing response ID binds only current response, never guesses an old
  one. Positive scripted journey uses native-test versus host fragments and
  missing assistant session metadata. Four negative scoped journeys assert zero
  tool events in both stdout and persisted history.
- CF04/R3: raw content_block_start rejects stopped and partial_json, even if
  false/empty; those names are assembly bookkeeping, not wire input. Two negative
  journeys prove zero publication, including self-marked complete.
- CF06: conservative 32 MiB invocation admission budget, charged before retaining
  each event/echo: 256 bytes plus four times serialized UTF-8 length. Includes
  duplicate deliveries and all response IDs, snapshots, pending fragments, UUID
  keys, thinking and signatures. No eviction that could erase late-conflict
  evidence. It is not an exact Python heap bound and rejects sufficiently long
  otherwise valid conversations; this scope is one invocation, not follow-ups.
  Five small-budget regressions pass. Existing per-input and response-ID caps
  remain. Transient SDK parsing/serialization allocations are not bounded here.
- CF02/03/04: conflict matrix covers tool name/args, thinking/signature, order,
  repeated identical block multiplicity, changed late fragments and missing-ID
  misbinding. Individual plus cumulative echoes corroborate the same stream.
  Conflicts after a valid published boundary cannot undo earlier execution.
- CF05: exact persisted assistant content list is ['Hello bridge']; tool-only
  responses have no assistant_message entry. Four tool calls/results remain exact.

### Verification receipts

Same environment prefix as above; only feature-scoped pytest used:

1. `-q tests/bridges/claude/test_fragments.py -k 'json_boolean or bookkeeping'`:
   RED 6 failed (all DID NOT RAISE), 6 deselected, 2 warnings.
2. `-q tests/bridges/claude/test_fragments.py`: GREEN 12 passed, 3 warnings.
3. `-q tests/bridges/claude/test_response_boundaries.py`: RED 3 failed / 15 passed;
   stream-session, stream-parent, echo-session actually published tool events.
4. Three-file gate (below): GREEN 36 passed / 26 warnings after scope repair.
5. `-q tests/bridges/claude/test_fragments.py -k 'retention or missing_metadata'`:
   RED 5 failed unsupported constructor parameter / 1 passed / 12 deselected.
6. Three-file gate after budget: 1 failed / 41 passed, because newly written
   exact-history expectation incorrectly included empty tool-only assistant
   entries. Corrected test to actual established persistence contract, no
   production history change.
7. Final command:
   `-q tests/bridges/claude/test_fragments.py tests/bridges/claude/test_response_boundaries.py tests/cli/test_claude_bridge.py`
   **50 passed, 26 warnings, exit 0, 4.31s**. Deprecations as above.

### Remaining acceptance blockers (do not advance to Step 2 yet)

- Final convention/format and incremental source review not completed in this
  continuation; new code includes long lines needing cleanup. No static checks
  or formatter executed (user authorized feature-scoped pytest only).
- CF06 limit evidence needs strengthening: current tiny-budget snapshot test can
  exhaust during the first response, and pending test repeats identical content;
  they prove admission rejection but not independently accumulated multi-response
  snapshots/distinct pending retention. Add separated, accurately sized scenarios
  and an SDK journey for limit rejection before publication.
- Malformed delta-shape matrix and SDK-discarded unknown raw assistant block
  handling remain unclosed from original handoff. Do not claim the typed parser
  can validate fields discarded by the vendor parser.
- Live native parity still unexecuted; scripted official SDK/graph/filesystem
  tests prove wiring, not actual native CLI ordering/version behavior. Full suite
  explicitly excluded by user; final independent review/completion pending.

## Final acceptance-gap closure (2026-11-03)

**READY for final independent review (Step 1 author verdict only).** Effective
accounting supplied by user: turn 1 / dispatch 6; unlimited turn/dispatch budgets;
local hardening is not a new turn; zero task failure retries used. No agents,
commits, detached runs, full suite or unrelated tests. Earlier retry counts in
this historical document are superseded by the current user accounting.

### Scope and source review

Revalidated the existing Python / SDK / pure assembly / real graph and file-store
routing record. Read the named code-test-review workflow, shared routing,
ownership/testing, coding rules/cadence/test policy, declarative structure,
Python conventions/named arguments/docstrings/client guidance and engineering
review/Python review rules from this checkout's vendored skills. No new CLI,
TUI, database, follow-up conversation or portable event contract introduced.
Read README, RESEARCH and KB entry/slo README/gotchas; branch remains claude-bridge.

This slice changes `sdk/response.py`, `sdk/sdk_runtime.py`, adds `sdk/transport.py`,
updates `test_fragments.py`, `test_response_boundaries.py`, README and this handoff.
Paths abbreviated under `src/bridges/claude/` and `tests/bridges/claude/`.
Existing unrelated dirty work is preserved.

Author source review traced transport → official SDK Query/parser → runtime →
assembly → existing tool bridge → graph executor → history. The raw guard is a
Transport decorator, not a replacement parser/process supervisor: SDK owns
connect/control/read cancellation/disconnect; cleanup still reaches the underlying
transport once in journeys. Supported text/thinking/tool_use blocks pass; unknown
block kinds and malformed content containers reject before lossy SDK parsing.
Extra fields on supported blocks are vendor metadata, intentionally not semantic
corroboration. The positive multi-tool journey now includes such metadata.
Pinned SDK `parse_message`, `Query._read_messages`, `receive_messages` and
`ClaudeSDKClient.receive_response` inspected directly: unknown blocks were dropped,
and Query preserves typed transport exceptions. No vendor monkeypatching used.

Malformed delta containers now produce `stream_protocol_failed`, not AttributeError;
message_delta requires a string stop_reason. Omission of message_delta entirely
retains the existing text-only compatibility path. Assembly remains sole owner of
retention, response identity, scope and semantic comparisons. No retained evidence
is evicted; a post-boundary conflict cannot undo prior valid execution.

Manual convention check: typed signatures, documented state/transport ownership,
keyword calls (SDK overrides retain their required signatures), bounded payload-free
errors, portable imports, focused helpers and no internal test patching. Long lines
from previous hardening were wrapped manually. Heterogeneous JSON Any at vendor
boundaries is documented. No formatter/static/type checker was run, per pytest-only
instruction; exact Black conformance is not asserted. Stateful parser/runtime
ownership is preserved rather than converting it into stateless classmethod services.
This is an author check, not an independent review.

### Current requirement/evidence map

| ID | Current closure evidence |
|---|---|
| CF01 | Early fragment test proves no calls before complete boundary; real multi-round SDK journey remains green. |
| CF02 | Individual/cumulative/duplicate fragments, ordered duplicate-content multiplicity, exact four tool calls/results and exact persisted assistant list `['Hello bridge']`. |
| CF03 | Identified late fragments reconcile to retained original snapshots; changed late/missing-ID fragments reject; current output stays untouched. |
| CF04 | R1 JSON-sensitive equality and R3 wire injection retained. Added 8 malformed block delta cases and 5 message delta cases. Four raw policy journeys cover unknown-only, mixed supported/unknown, malformed content container and malformed block. All assert zero tool/result/success publication in stdout and real persisted history, one failure and one transport close. |
| CF05 | Official SDK/control/parser + production runtime/graph/tools/filesystem positive journey and 24 negative boundary journeys pass. Native process not involved. |
| CF06 | R2 scope and existing per-input/UUID/thinking/signature bounds retained. New `test_completed_snapshots_share_budget_across_responses` explicitly completes two responses under 6000 bytes and corroborates the first before next echo rejects; no first-response-only false positive. `test_distinct_pending_fragments_share_budget_without_uuid` admits two different contents with empty UUID then rejects a third under 4000 bytes. `retention-limit` journey exercises production 32 MiB admission using an oversized signature after a pending tool, asserting the reconciliation-limit failure text and zero publication. |

Retention tests were green when first added (coverage strengthening, not invented
RED). Malformed matrix was RED 7 failures / 8 passes before fix. Unknown-block
journeys were RED with actual forbidden tool publication before guard, then green.
Conservative budget includes repeated inputs; not an exact heap bound, and transient
SDK parsing/serialization allocation is outside it. It intentionally rejects long
otherwise valid invocations. Scope remains one native invocation, not follow-ups.

### Exact commands and receipts

CWD `/root/Code/claude-bridge/slo`, for each command:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest <arguments>
```

1. `-q tests/bridges/claude/test_fragments.py -k 'snapshots_share or distinct_pending or malformed'`
   RED exit 1: 7 failed, 8 passed, 26 deselected, 2 warnings; then GREEN exit 0:
   15 passed, 26 deselected, 2 warnings (1.61s).
2. `-q tests/bridges/claude/test_response_boundaries.py -k 'retention-limit or malformed-delta or raw-block'`
   RED exit 1: 2 failed, 2 passed, 18 deselected, 8 warnings; after guard GREEN
   exit 0: 4 passed, 18 deselected, 6 warnings (2.04s).
3. `-q tests/bridges/claude/test_fragments.py tests/bridges/claude/test_response_boundaries.py tests/cli/test_claude_bridge.py`
   First attempt exit 2, three collection errors from two missing colons during
   manual line wrapping; repaired immediately. Rerun exit 0: **71 passed,
   32 warnings, 4.96s**. Local edit/test correction, not workflow failure retry.
4. `-q tests/bridges/claude tests/cli/test_claude_bridge.py`
   Affected feature gate expanded because the transport wrapper touches all SDK
   consumers: exit 0, **178 passed, 38 warnings, 6.36s**.
5. Same affected gate after adding supported metadata compatibility assertion and
   final source comments: exit 0, **178 passed, 38 warnings, 6.30s**. No skips.

Warnings remain pythonjsonlogger/LangGraph/Pydantic deprecations. Tests use the
existing isolated SLO_HOME fixture and real temporary history. No command stubs
or system binary changes were introduced.

### Explicit limitations / next gate

- Final independent review and completion check are pending; no self-review is
  represented as independent. No authorized nested agents launched.
- User explicitly excludes full suite and unrelated tests; only affected feature
  pytest ran. Static/formatter/build and live-native tests were not run.
- Original session causality and live native parity are **not proven**. Scripted
  official SDK journeys do not establish actual CLI version/order/account behavior.
- Raw block kinds are guarded; arbitrary vendor metadata fields are intentionally
  ignored, not claimed validated. SDK transport API is pinned/internal and needs
  reassessment on SDK upgrades.
- No further nondeferred fragment acceptance blocker identified by this author.
  Independent reviewer should assess this finite CF01–CF06 contract, not unrelated
  bridge lifecycle/features or deferred native parity as if implemented here.
