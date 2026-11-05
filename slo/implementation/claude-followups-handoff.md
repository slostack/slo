# Claude follow-ups — revision handoff (turn 2 / dispatch 1)

## Current verdict: READY for independent rereview

This revision addresses FR01 and FR02 from `implementation/claude-followups-review.md`. Author Step 1 readiness only: the prior REVISE review is not overwritten or claimed accepted. Unlimited user-authorized turn/dispatch budgets; this is turn 2 / dispatch 1, no nested dispatch and no completed workflow turn claimed.

### Revision mapping

| Finding | Change and evidence |
|---|---|
| FR01 / FU05–06 | `SloAgent._prepare_aborted_terminal` joins the retained bridge before trace persistence and publication. Both graph-read exception and normal available-item branches delegate to it; EOF with abort also goes through the barrier. Cleanup failure propagates as failure, not an aborted/completed success, retaining SDK ownership for explicit close retry. |
| FR01 exact-host-path regression | New `tests/bridges/claude/test_host_abort.py::test_available_tool_boundary_abort_joins_before_terminal[False,True]` enters real `SloAgentSession.invoke` → graph → bridge → real SDK/MCP, requests abort upon yielded `tool_call_start` with a pending native callback and graph updates still available, and holds transport close at an external barrier. Before release: no observable or persisted `run_aborted`, owner still live. Success: owner done/callbacks empty at terminal, exactly one persisted abort, no completion, no tool receipts, one query. Failure: unconfirmed-closure diagnostic, no abort/completion, same owner retained, admission refused, explicit cleanup retry joins, repeated close idempotent. Auth/native transport alone substituted; filesystem history is real under tmp_path. |
| FR02 | Scoped private operations in `bridge.py`: `_admit_response`, `_record_response_boundary`, `_record_tool_boundary`, `_record_terminal_context`, `_retain_unsent_audit_prefix`, shared detached `_record_live_context`, `_build_boundary_chunk`, `_finish_response_stream`. Stream retains async-generator/lifecycle ownership and delegates independent admission/history/conversion/cleanup policy. Fresh-message validation remains before the cleanup scope (invalid inputs do not newly seal admission). No wrapper class, SDK owner-task move, parser rewrite or unrelated refactor. |
| FU01–FU07 / E1–E4 preservation | Final feature gate reruns all prior 231 cases plus two FR01 journeys. Existing nine safe-retry cases (E1), history-off/compaction (E2), host-stop (E3), concurrent admission/auth closure (E4), native resume wiring/no replay, repeated/stale IDs, uncertain-write closure and parser repair remain passing. Prior detailed mapping below remains applicable; live-native transcript persistence is still unverified. |

### Exact revision receipts

CWD `/root/Code/claude-bridge/slo`. Commands use:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest ...
```

- RED before source fix: `-q tests/bridges/claude/test_host_abort.py --tb=short` — exit 1, **2 failed, 4 warnings, 2.20s**. Both failed because `terminal_observed` was set while cleanup was blocked. Assertion unwinding also produced a generator/context cleanup diagnostic; test now uses same-task `aclosing` to ensure clean teardown on assertion failure.
- GREEN after FR01: same command — exit 0, **2 passed, 5 warnings, 2.03s**.
- After FR02 extraction: `-q tests/bridges/claude tests/cli/test_claude_bridge.py --tb=short` — exit 0, **233 passed, 95 warnings, 12.07s**.
- Final gate after preserving pre-scope fresh validation and adding test generator teardown: same feature command — exit 0, **233 passed, 95 warnings, 10.76s**, no skips. Warnings are pythonjsonlogger/LangGraph/Pydantic deprecations.

### Scope, routing and review limits

Revalidated existing Python/asyncio/anyio/LangChain/LangGraph/official SDK routing; read checkout-vendored exact Code-Test-Review workflow, engineering routing/ownership/testing, coding rules/cadence/test policy, Python root and declarative/type/doc conventions. Existing host and SDK lifetime boundaries govern; no new app-service/HTTP/database/CLI architecture. Read README, local memory, KB entry and Slo index/gotchas, review and handoff. Plan: reproduce available-item abort → shared terminal barrier → scoped transitions → feature gate → source self-review and handoff.

Source self-review checked both abort publication sites, retained cleanup/error path, semantic prefix ordering and detached history, pre-admission validation placement, and test assertion/teardown boundaries. Changes this dispatch: `src/agents/slo_agent/agent.py`, `src/bridges/claude/bridge.py`, new `tests/bridges/claude/test_host_abort.py`, this handoff and durable local/KB notes. Existing unrelated dirty work preserved.

Only feature pytest was executed. No full suite, static/build tools, live external execution, commits, nested agents or detached workflows. Feature-only gate is the user's explicit authorization, not repository-wide regression certification. Actual native transcript persistence/resume and MCP parity remain unverified. Independent rereview and subsequent completion assessment are still required.

---

# Historical Step 1 acceptance handoff (turn 1 / dispatch 4)

## Current verdict: READY for independent final review

Dispatch 4 closes the four nondeferred evidence/source-review gaps below. This is author Step 1 readiness, NOT independent review, workflow completion, or live-native certification. User budgets are unlimited; accounting remains turn 1 / dispatch 4, with no new agent dispatch or completed workflow turn claimed.

### Dispatch 4 scope and result

No runtime behavior fix was necessary: the added cases passed existing safety guards. Updated obsolete `close_session`, `reset`, and response-lifetime contracts in `sdk/adapter.py` and `sdk/protocol.py`; reset refusal now explains transcript reset rather than falsely prohibiting another prompt. All prior parser code/tests remain unchanged. Other pre-existing dirty work was preserved.

Plan executed: later safe retry journey → stale-result and close/auth/startup/cleanup boundary evidence → scoped source/convention review → feature regression gate. Routing remains the Python/asyncio/anyio/official SDK/real host graph and filesystem record below, with checkout-vendored workflow, engineering/testing/ownership, coding cadence/policy, and Python conventions. No new layer or architecture introduced.

### Current acceptance mapping (supersedes dispatch 3 gaps)

| Item | Exact evidence / outcome |
|---|---|
| E1 / FU04 later safe retry | `test_proven_unsent_failure_allows_explicit_retry_without_replay`: nine cases; session auth, invoke auth and connect, each first/history-on, later/history-on, later/history-off. Later first turn completes, failed prompt never reaches wire, explicit retry alone sends, SDK constructions retain `native-test` resume identity (including failed connect), persisted failed input remains audit history or history stays absent. Typed error remains `ClaudeBridgeError`, preserves authentication code, bounds public text and excludes raw connect exception text. |
| FU03 stale prior invocation | `test_stale_invocation_results_cannot_release_resumed_waiters`: first tool turn completes; second parks real SDK/MCP callback with identical response/call IDs. Submission with first invocation ID is rejected; same waiter remains unresolved, no pending result reservation or extra wire receipt; current invocation then completes exactly once. |
| E4 close during invoke auth | `test_invocation_reserves_admission_across_authentication[adapter]`: close cancels/joins auth, reserved invoke fails, no prompt; competing admission still rejected. Existing session/none and session-start variants retained. |
| FU05–06 resumed lifetime | `test_close_resumed_work_retains_cleanup_owner_without_replay[cleanup_fails-stage]`: four combinations of blocked connect / blocked response and successful / once-failed cleanup. Prior owner done before replacement; failed cleanup retains same live owner; new admission denied; explicit close retry joins owner, empties callbacks, closes transport; repeated close does not retry settled cleanup. Blocked connect sends no second prompt; blocked response sends exactly one. |
| FU01–02, E2–3, FU05–07 preservation | Full feature gate reruns existing context/tool-memory, no-history, compaction, host-stop, foreign-result, uncertain-write, resumed-cancel and all fragment repair regressions. No parser changes. |

### Exact dispatch 4 receipts

CWD `/root/Code/claude-bridge/slo`; every pytest command prefixed with:
```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest ...
```

- `-q tests/bridges/claude/test_followups.py -k proven --tb=short`: exit 0, **9 passed, 4 deselected, 26 warnings, 3.39s**.
- `-q tests/bridges/claude/test_concurrent_admission.py tests/bridges/claude/test_resumed_lifecycle.py --tb=short`: initial collection error (incorrect event class import), then 2 fixture/oracle failures / 8 passed (closure spelling and missing second response drain after parked tool boundary). Corrected fixture to use `ClaudeResponseCompletedDAO`, accept closure diagnostic, and drain the final native result. These were NOT product RED findings. Final exit 0, **10 passed, 2 warnings, 1.94s**.
- Final `-q tests/bridges/claude tests/cli/test_claude_bridge.py --tb=short`: exit 0, **231 passed, 92 warnings, 11.73s**, no skips. Existing pythonjsonlogger/LangGraph/Pydantic deprecations. Includes strengthened typed-error assertions and final source wording changes.

### Source review and limitations

Read actual untracked bridge sources (ordinary git diff omits these), adapter admission/replacement/result correlation, runtime query-attempt marker and disconnect retry ownership, model consumed-prefix/unsent catch/terminal sealing, authentication fixed-message construction, and host follow-up history/compaction/finish-host-turn diffs. Reviewed test signatures, deterministic barriers, bounded waits, third-party-only substitutes, real SDK/MCP, real temporary history, and cleanup finally blocks. No remaining scoped correctness blocker identified. This is a self-review only, not Step 2.

Feature-only pytest is the explicitly authorized acceptance gate. Full suite, static/build tools and live external execution were not run; no commits, nested agents, or detached workflows. Real native transcript persistence/resume with MCP remains unverified and deferred under the explicit no-live constraint; scripted transport proves SDK wiring and isolation, not actual Claude memory. No host restore/replay support is claimed. Independent final review and subsequent completion assessment remain required.

Dispatch 4 files: `tests/bridges/claude/test_followups.py`, `test_concurrent_admission.py`, new `test_resumed_lifecycle.py`, `src/bridges/claude/sdk/{adapter,protocol}.py`, this handoff. Runtime parser and host behavior unchanged in this dispatch.

---

# Historical dispatch 3 hardening

## Dispatch 3 verdict: REVISE — concrete remaining evidence gaps

This section supersedes the historical runnable-milestone verdict below. User supplied the independent early-review blockers E1–E4. Unlimited workflow turns/dispatches; no phase cap. No new dispatch or completed workflow turn claimed. Only feature pytest was run; no full suite, live native execution, commits, nested agents or detached workflow.

### Implemented in dispatch 3

- **E1 / FU04:** `ClaudeSubmissionNotStartedError` is a typed safe outcome (preserves authentication error code). Runtime sets query-attempted immediately before awaited SDK query. Only failure before that point, with settled disconnect and no cancellation, qualifies for explicit retry. Adapter joins/replaces that runtime retaining prior resume identity. Model retains failed host input as consumed audit prefix, never sends it; removes one-shot failure flag and close_session-on-auth-failure. Uncertain write failures close model admission and tell the operator to start a new session without automatic replay.
- **E2 / FU01:** nonpersistent host obtains a deep-detached live message prefix from its retained bridge. It does not import external history. Automatic/preflight/forced compaction share the bridge guard in `_run_compaction_if_needed`; native transcript cannot be summarized by host compaction.
- **E3 / FU05–06:** host graph calls `finish_host_turn` before terminal publication. A native terminal keeps the conversation; a parked tool boundary cancels/joins and seals it. Test inspects completed SDK owner and empty pending-call registry at host completion, and repeated close is idempotent.
- **E4:** invocation reserves admission before auth await; competing invoke fails immediately; closure and reader state are revalidated after auth. start_session also revalidates session closure after auth.
- Later tool-bearing turns reuse native response/tool IDs across three prompts, each reads a changed real file with exactly one new receipt. Resumed cancellation, first/later uncertain query-write failure, and foreign resumed terminal identity have journey evidence.

### Current evidence map

| Requirement | Passing tests / limits |
|---|---|
| E1 / FU04 | `test_proven_unsent_failure_allows_explicit_retry_without_replay[session_auth,invoke_auth,connect]`: actual invoke failures, zero failed-attempt wire prompts, exactly one explicit retry, persisted failed/completed/user history. First-attempt coverage; later safe failure still needs equivalent proof. |
| E1 / FU05 | `test_query_write_failure_never_replays_and_requires_new_session[False,True]`: write recorded before error, actionable diagnostic, explicit resend refused, exact wire counts. |
| E2 | `test_followup_retains_native_tool_context_without_replay`: persistence on/off and threshold-crossing variants. Threshold test proves real checker returns true then shared compaction guard returns false, followed by successful next prompt and no summary. Existing unrelated/restored-history denials remain green. |
| E3 | `test_host_stop_joins_native_tools_before_terminal`: real graph/read/MCP, closed transport, finished owner, no waiter at run_completed, zero sent tool results, repeated close once. |
| E4 | `test_concurrent_admission.py`: four deterministic barrier cases for start_session closure and competing invoke/session closure during auth; zero late native prompts. Adapter-close-during-invoke-auth specifically still lacks its own case. |
| FU03 | `test_later_tool_turns_allow_repeated_call_ids`: three persisted tool calls/results/completions, changed file values, exact three prompts. `test_foreign_result_on_resumed_turn_is_not_completion`: only one completion, second failure, no replay. |
| FU05–06 | `test_cancel_resumed_turn_joins_before_host_terminal`: second query observed then abort; two exact prompts, joined close, idempotent close. Existing failed-cleanup and cancellation suite remains green. |
| FU07 | Feature gate includes all existing fragment repair regressions, unchanged parser source. |

### Dispatch 3 commands and receipts

Same CWD and environment prefix as below. All tests use controlled native auth/SDK Transport; no external Claude activity.

- `poetry run pytest -q tests/bridges/claude/test_concurrent_admission.py --tb=short`: RED 3 failed / 1 passed; GREEN 4 passed.
- `poetry run pytest -q tests/bridges/claude/test_followups.py --tb=short`: early-stop RED (transport still open), then GREEN; threshold first had invalid fixture event kind `usage` (corrected to audit event, not product RED), corrected RED reached incompatible compacter; no-history RED rejected missing prefix.
- `poetry run pytest -q tests/bridges/claude/test_followups.py -k proven --tb=short`: RED 3 failed; intermediate failure exposed persisted failed-user prefix (fixed rather than deleting history).
- `poetry run pytest -q tests/bridges/claude/test_followup_failures.py --tb=short`: uncertain explicit resend initially returned generic prefix error (RED), corrected by sealing model; resumed cancel and repeated IDs passed.
- Final exact gate: `SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest -q tests/bridges/claude tests/cli/test_claude_bridge.py --tb=short`: **exit 0, 219 passed, 74 warnings, 9.81s**. Warnings are existing pythonjsonlogger/LangGraph/Pydantic deprecations. Intermediate gate 213 passed/1 failed identified authentication exception compatibility; typed safe error now subclasses ClaudeBridgeError and preserves `authentication_required`.

### Remaining before acceptance-ready final review

1. Add later-turn auth/connect safe-failure recovery tests, including no-history failed-attempt prefix and preserved native resume identity. Current code supports these paths but first-attempt tests do not prove them.
2. Add stale prior-invocation tool-result submission during a new parked tool turn (repeated call IDs), checking no waiter release/no partial delivery. Foreign terminal result is covered, not this distinct boundary.
3. Complete deterministic adapter-close-during-invoke-auth case and resumed blocked-startup/cleanup-failure combinations; existing single-turn cleanup evidence is not full resumed-lifetime evidence.
4. Review `close_session`/`reset` obsolete descriptions and typed safe-error sanitization/compatibility, formatting and explicit test annotations. Read-only diff inspection performed for changed host paths, but final convention review is not complete.
5. Resume-per-turn remains accepted; **actual live native process transcript persistence and MCP parity are unverified**. No live execution is implied or authorized. Independent final review is still required after nondeferred gaps close.

Files changed this dispatch: `src/bridges/protocol.py`, `src/bridges/claude/bridge.py`, `sdk/{adapter,sdk_runtime,exceptions}.py`, host `agent.py` and `sessions/service.py`, `test_followups.py`, new `test_concurrent_admission.py`, new `test_followup_failures.py`, this handoff. No fragment parser or unrelated edits changed.

---

# Historical dispatch 1 runnable milestone

## Contract and scope

Source: current user request, second Claude bridge issue. Turn 1 / dispatch 1; unlimited workflow-turn/dispatch budgets, max three failed-task retries, never retry aborts. No commits, detached processes, nested agents, full-suite or unrelated tests. This dispatch stops at the runnable milestone for mandatory independent read-only early review, not final acceptance. Existing dirty changes (including completed fragment fix) are preserved.

| ID | Acceptance | Evidence plan |
|---|---|---|
| FU01 | Successive prompts in one live host session retain native context including tool results | Real session invoke → graph → official SDK → scripted native boundary → real history; second answer depends on first tool receipt |
| FU02 | Send only new prompt; never replay old prompts or rerun prior tools | Exact wire prompt list, tool receipts and persisted tool-call counts |
| FU03 | Fresh per-turn response assembly, pending tool set and completion; stable native conversation identity | New invocation runtime with SDK resume identity; repeated response IDs permitted across turns without stale completion |
| FU04 | Failed first attempt does not consume a one-message allowance | Bounded pre-submission failure/retry journey; uncertain post-send failure explicitly closes rather than silently resending |
| FU05 | Safe cancellation/failure and explicit recovery or closure when uncertain | Cancellation during active work, idle close, failed cleanup ownership, no replay; hardening after early review |
| FU06 | Real session end cleans resources | Session close + idempotent adapter cleanup, existing lifecycle regressions |
| FU07 | Preserve completed parser repair CF01–CF06 | Existing feature pytest gate |

## Routing / prerequisites

CWD `/root/Code/claude-bridge/slo`, branch `claude-bridge`. Python 3.11, LangChain core 0.3 / existing LangGraph, claude-agent-sdk 0.2.176, asyncio/anyio SDK lifetime, real disposable filesystem history. No new database, HTTP router, CLI verb, TUI widget or tool implementation.

Read project SLO instructions, README architecture/style/testing sections, local RESEARCH.md, KB Welcome.md + slo/README.md (no index.md) + gotchas.md, previous fragment handoff/review/completion. User explicitly names this handoff destination, overriding historical KB documentation-location guidance for this artifact.

Selected source tier: checkout-vendored skills under absolute prefix `/root/Code/claude-bridge/slo/skills/` (no matching personal override):
- `orchestration/workflows/code-test-review.md` (exact named workflow)
- `engineering/engineering-routing/SKILL.md`, `engineering-ownership/SKILL.md`, `engineering-testing/SKILL.md`
- `coding/coding-rules/SKILL.md`, `code-test-loop/SKILL.md`, `test-verification-policy/SKILL.md`, `declarative-method-structure/SKILL.md`
- `languages/python/python-conventions/SKILL.md`, `named-arguments-and-type-hints/SKILL.md`, `declarative-method-structure/SKILL.md`, `method-docstrings/SKILL.md`, `build-clients/SKILL.md`, `build-application-services/SKILL.md`

Order: project context → routing/testing/ownership → coding rules → Python root → scoped recipes → bounded implementation. Existing portable SDK ownership overrides illustrative HTTP client layouts/retries; no automatic prompt resend. Tests are application-entry journeys plus boundary/lifecycle regressions, not live-native E2E. External authentication and native transport alone are substituted; SDK parsing/control/MCP, host graph/tools/history remain real.

## Architecture and decision

Current host rejects another prompt before run admission; model rejects history and closes adapter after final response; adapter admits once; runtime owns one connect/query/result/disconnect. SDK `client.py:query` sends only a supplied prompt, `receive_response` ends at ResultMessage, and native options `resume` are passed as `--resume=<id>` by pinned subprocess transport. Native ResultMessage carries session_id. SDK anyio connection/disconnection must stay in the owner task.

Chosen minimal seam: retain native conversation ID after a successful, validated result AND settled disconnect, then use SDK `resume` for the next fresh per-turn runtime. Native transcript holds prior tools; do not serialize host history back to Claude. Each runtime retains its existing cleanup ownership, assembly and tool binding. Alternative: keep one connected client with a command mailbox; rejected for first slice because it expands idle cancellation/owner lifetime substantially. Restart/resume across host sessions remains out of scope and rejected. Native resume persistence/parity requires later live evidence; scripted transport can prove option wiring and exact prompt/result flow but not native disk durability.

Model validates the consumed semantic host prefix and accepts exactly one new HumanMessage suffix; tools use existing exact-set continuation validation. Host only admits history produced in this live session, not arbitrary restored history. Unknown post-send failures remain closed with explicit new-session guidance; pre-submission rejection must remain retryable (hardening).

## Exact pytest commands

Prefix for every command (CWD above):
```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
```

Runnable increment:
```bash
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest -q tests/bridges/claude/test_followups.py
```
Feature-only regression gate (includes fragment preservation):
```bash
SLO_ENV=test SLO_HERDR_DISABLED=1 PYTHONPATH="$PWD" poetry run pytest -q tests/bridges/claude tests/cli/test_claude_bridge.py
```

Full suite explicitly deferred by user until all separate problems are fixed. No static/build/live-native claims.

## Runnable milestone verdict: READY for early read-only review ONLY

Not Step 1 acceptance-ready, not final workflow completion. Independent review has NOT occurred in this dispatch; no nested agents launched. Next orchestrator action: dispatch the mandatory independent read-only early reviewer with this contract, code and tests; reviewer must not run tests. No completed workflow turn is claimed.

### Evidence receipts (2026-11-03)

All commands use the prefix/environment/CWD above.
- Baseline feature gate: exit 0, **203 passed, 47 warnings, 7.26s**.
- Initial new-test run: exit 1 due to incorrect pytest MonkeyPatch call signature (fixture defect, corrected; not a product RED claim).
- Corrected runnable test RED: exit 1, **1 failed**, host rejected second prompt at `sessions/service.py:_validate_fresh_bridge_prompt` with `Start a new session for another Claude bridge prompt.`
- Intermediate run exposed an additional lifetime restriction: `SloAgent._react_loop` closed bridge after successful turn. Removed only that successful-turn closure; explicit session close and abort closure remain.
- Runnable command with `--tb=short`: exit 0, **1 passed, 4 warnings, 1.93s**.
- First feature gate with `--tb=short`: exit 1, **202 passed, 2 failed, 51 warnings, 7.57s**. Both failures asserted the superseded one-prompt restriction after a successful auth retry. Updated those exact assertions to require successful follow-up; startup failure checks retained. This oracle change is directly required by FU01, not a baseline waiver.
- Final exact feature command above: exit 0, **204 passed, 51 warnings, 7.39s**. No skips. Deprecation warnings: pythonjsonlogger, LangGraph, Pydantic.

### Files changed in this dispatch

- `src/agents/slo_agent/sessions/service.py`: permit own live-session follow-up; retain external/restored-history rejection.
- `src/agents/slo_agent/agent.py`: successful run end no longer seals session-owned bridge.
- `src/bridges/claude/bridge.py`: remember terminal semantic prefix; validate exactly one new user suffix; retain adapter after successful boundary.
- `src/bridges/claude/sdk/adapter.py`: replace settled per-turn runtime with resume-bound runtime.
- `src/bridges/claude/sdk/sdk_runtime.py`: pass SDK resume, bind assembly to expected native identity, validate result scope, expose settled completion identity.
- `tests/bridges/claude/test_followups.py`: two-turn real session entry/SDK/MCP/graph/history journey.
- `tests/bridges/claude/test_admission.py`, `test_startup.py`: replace only obsolete post-success second-prompt rejection assertions.
- `README.md`: describe current live-session continuation and limitations.
- This handoff. Existing parser implementation/tests and unrelated changes untouched.

### Current requirement evidence

FU01/FU02: `test_followup_retains_native_tool_context_without_replay` reads orchid-73 using the real read tool, changes the source file, then asks a context-only follow-up. Native substitute answers only with prior receipt and expected resume identity; asserts exactly two wire prompts, one tool call/result, two persisted completions, exact distinct assistant answers. SDK itself is real. RecordingSDKClient subclasses the third-party class solely to observe options; native wire and auth are controlled substitutes. This does not prove actual Claude remembers persisted tool results.

FU03: same test reuses response-test across turns, proving fresh response assembly and no stale completion; second SDK options resume is native-test, not host ID. Each runtime has a fresh tool bridge. Later tool-bearing turns still need dedicated tests.

FU04: existing startup/auth rejection tests now prove corrected startup → successful prompt → successful follow-up. They fail during prepare_startup, NOT after host run history or after SDK query admission. Later pre-query failure retry is still unimplemented/untested.

FU05/FU06: existing cancellation and failed-disconnect tests pass unchanged. New journey closes two completed native runtimes and then explicitly closes host session. New multi-turn cancellation/failure combinations and concurrent admission need hardening.

FU07: complete existing feature gate remains green, including fragment-fix positive and negative journeys. No live-native certification follows.

### Required hardening after early review (not waived)

1. FU04: remove remaining one-shot/failure remnants (`_attempt_failed_before_submission`, close_session sealing, `_invocation_id` assignment before admission). Test auth failure during actual invoke, connect failure before send, and failed first host history; recover only with evidence of no send. Do not replay uncertain work.
2. FU05: explicit safe closed/recovery diagnostic after query failure/cancellation, cancellation between turns, blocked resumed startup, cleanup failure/retry; no new prompt while cleanup uncertain. Current failure closes adapter but generic closed error is not yet a complete operator recovery contract.
3. FU03: later turn requests tools with repeated call IDs, rejects foreign native result/session IDs, altered/missing host prefix, stale results; no-history host behavior and host compaction/trimming constraints. Concurrent invoke_adapter admission across auth awaits must be serialized/rechecked.
4. FU06: retained owner joins before replacement (currently successful cleanup_finished is required; inspect owner scheduling), idempotent real session end and closure during resumed work; custom stop-hook after tool boundary must not orphan parked tools now that unconditional graph-end close is removed.
5. Rename obsolete fresh/allowance identifiers only after ownership contract is settled; improve affected docstrings and bounded test typing/formatting. Review gate source diff explicitly (untracked bridge files do not appear in ordinary git diff).
6. SDK resume assumes native transcript persistence and model/session compatibility. Actual CLI resume with MCP tools and source transcript durability is unverified. No cross-process host restore, account mutation, or live-native execution was attempted.

No full suite, static/build/formatter command, commit, push, detached workflow or nested agent performed.
