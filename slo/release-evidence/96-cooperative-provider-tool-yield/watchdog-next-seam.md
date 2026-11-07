# Watchdog next seam — bounded design, not implementation

2026-11-04. Repository `/root/Code/slo-message-queue/slo`, branch `message-queue`, HEAD/baseline `82c3f5c6de9345af34a673a3d975366ca8c1624c`. This assignment read source and wrote only the two requested Markdown artifacts. No tests, collection, static tools, application/model probes or agents ran. A.2 remains **PARTIAL / INCOMPLETE**.

## Current journey and diagnosis

Sources: original `/root/Code/specifications/projects/slo/specifications/96-agent-message-queue/96.a.2-cooperative-provider-and-tool-yield.md` §§5.2–5.3, 9/A1/A10; `routing.md`, `current-handoff.md`, `implementation-control-state.md`, `implementation-watchdog-outcome.md`, `acceptance.md`, `safety-audit.md` in this directory. Current source, not old routing line numbers, governs the following facts.

- `src/agents/slo_agent/watchdog_timer.py::WatchDogTimer.invoke` accepts only `graph_stream`. `_read_graph_item_with_provider_deadline` runs `anext` in the caller under `asyncio.timeout`; the explicit comment warns that a separate reader can survive cancellation and collide with `aclose`. No retained reader, signal waiter, abort race or phase-aware pending-read deadline exists.
- `GraphReadOutcomeDAO` is already strict/frozen/forbid and supports item/end/yield with explicit settled-item presence. **Narrow unclosed defect:** `_read_graph_item_*` return `None` both for a real framework None item and StopAsyncIteration; `invoke` maps both to end. `test_graph_read_outcome.py` proves the DAO can represent None, not that the watchdog preserves it. Preserve the prior carrier/caller work; do not call watchdog-level None discrimination certified. Close this in the later whole read-path migration, not by reopening the DAO design.
- `tool_execution/yield_policy.py::ToolExecutionControl` owns phase/high-water and synchronous reservation. `wait_for_provider_exit` already exists, but no watchdog consumes it. `wait_for_yield` can return on source seal/failure and requires predicate recheck; reservation refuses tools/settling. Control has no task lifecycle to clean up and must not acquire one here.
- `agent.py::SloAgent._stream_graph_turn` is the sole direct caller: end returns, anything other than item raises `graph_read_outcome_invalid`; finally drains tool output then calls `_close_graph_stream`. Enabling yield now would enter an intentionally unsupported consumer. Graph tool entry is not yet connected to the control. Observed tool chunks cannot protect a transition occurring inside an already pending `anext`.
- Current five watchdog tests cover first/idle timeout, observed two-tool suspension, end, ordinary error. Four control tests cover reservation/high-water, transitions and cross-loop rejection. They do not establish reader joins, repeated cancellation, simultaneous phase/deadline arbitration or actual urgent delivery. Prior receipts are retained, not rerun here.
- `src/tui/app.py:1144` still restricts composer priorities to normal. Leave it so.

## Exact next author assignment: owned-reader cleanup only

**Owner/model:** original Code+Test author, exactly `openrouter:deepseek/deepseek-v4.1-flash-1017`, supported default reasoning. GPT is analysis-only here. `gpt-6.1-sol` medium fallback only after a recorded concrete OpenRouter token/quota exhaustion error; output-limit, unknown-model and generic errors never authorize substitution.

**Module/seam:** one private lifecycle helper on existing `WatchDogTimer`, proposed name `_cancel_and_join_owned_read`. It hides cancel-once and repeated-cancellation-resistant joins, not urgency arbitration. Keep it local to `watchdog_timer.py`; no new module, generic task library or runtime owner. This is an explicitly dormant prerequisite until the complete race and consumer settlement can be connected safely.

**Allowed future edits:** `src/agents/slo_agent/watchdog_timer.py` and `tests/agents/slo_agent/test_watchdog_timer.py` only, plus a new task-local author receipt. Maximum **99 added production lines total**, counting any drain coroutine/docstrings/imports. Prefer one cohesive helper with one tiny drain coroutine only if needed for `create_task`'s coroutine contract. This is a size bound, not permission for compressed code or mechanical fragmentation. If the contract cannot fit clearly, report a bounded design blocker instead of expanding into the full race.

**Proposed private interface (prose, not implementation):** async `_cancel_and_join_owned_read`, keyword-only `reader: asyncio.Task[object]`, `signal_waiters: tuple[asyncio.Task[None], ...]`, returns `bool` indicating caller cancellation observed while joining. Preconditions: unique handles, none is the calling task; the watchdog has already selected cleanup and has not separately cancelled these handles. Ownership transfers for cleanup only. The helper does not create the reader, close its stream, settle control/history, advance input or decide whether a yield won.

Promises:

1. Cancel each still-pending signal waiter and the reader at most once. Do not cancel a completed reader. Retrieve every terminal result/exception, including already-done handles.
2. Retain one owner-held cleanup task that drains all handles; shield that task while joining. Repeated caller cancellation is recorded and cannot abandon it or repeatedly cancel the reader. One shield await is insufficient. No polling, detached cleanup, timeout escape or `uncancel` trick that loses cancellation.
3. Return only after all handles terminate. Return the cancellation-observed flag; do not invent a GraphReadOutcome or swallow truth into success. Joined original task handles retain their actual value, StopAsyncIteration, cancellation or error for the later race owner to classify. Test that the flag is true after repeated caller cancellation. The later caller must propagate cancellation after extracting cleanup/audit truth, never resume normal continuation on true.
4. Cancellation-suppressed reader returning None/value remains inspectable as a normal result. CooperativeProviderYield and arbitrary errors remain inspectable; this helper does not translate them, because only the race owner knows whether its exact reservation succeeded. Joined waiter errors must also remain inspectable, not silently treated as an urgency signal.
5. Never call `aclose`; joining is the barrier that permits the existing agent close later. If a child refuses to terminate, retain ownership and stay pending. Do not claim bounded delivery or successful cleanup.

**Deliberate non-edits:** do not alter public `invoke`/`build`, existing deadline/read branches, `GraphReadOutcomeDAO`, control, agent, graph, executors, sessions, histories or TUI. Do not start using a separate reader in production yet. That would require all §5.3 decisions and settlement consumer together; a cleanup helper alone is not sufficient. No activation or additional feature flag.

**Why this rather than phase-wait first:** phase waiting is already provided by control; extracting another waiter adds little. Cancellation ownership is the concrete risk named in the current reader comment and required by §5.3.7–8. A private helper is a genuine lifecycle test seam, not a second consumer. A prerequisite may remain dormant, but must have a finite closure and must not be counted as a runnable urgent milestone. Do not keep accumulating dormant helper layers afterward.

## Author test-first closure (future, NOT executed)

Use ordinary pytest/asyncio Events and typed test-owned tasks in the existing watchdog module; no patch of internal collaborators, test DSL, subprocess or executable fixture. Direct testing of this private helper is justified by its cancellation/join contract; it does not establish application wiring.

First add failing tests, then the helper. Proposed test names/required outcomes:

- `test_owned_read_cleanup_cancels_once_and_joins_before_close`: held reader and signal waiter expose entry/finally Events; cleanup remains pending until finally releases, then test may close stream without concurrent anext/aclose. Signal waiter is joined. One cancellation recorded per pending task.
- `test_owned_read_cleanup_survives_repeated_caller_cancellation`: cancel cleanup caller at two event-controlled points while reader-finally is held; caller cannot finish/release handles before gate opens, then returns cancellation-observed true. Assert one reader cancellation, no abandoned task.
- Parameterized `test_owned_read_cleanup_preserves_terminal_truth`: already-completed item, normal None, StopAsyncIteration, ordinary exception; pending reader suppressing cancellation and returning item/None; cancellation; cooperative reservation exception. Join retrieves but does not rewrite each task's terminal truth. Include a signal waiter failure; original exception remains retrievable.

All test-created tasks must be released/joined in test teardown even on failed assertions, with bounded outer waits. No persistent output outside verified test-owned temp roots; preferably these lifecycle tests need no files at all.

Future focused command, after author audits selected modules and transitive fixtures, from this application root; environment matches `routing.md` Makefile fallback (if a readable tests.env appears, revalidate rather than silently replace it):

```bash
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40 PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD" poetry run pytest -p no:cacheprovider -m 'not e2e' -q \
  tests/agents/slo_agent/test_watchdog_timer.py \
  tests/agents/slo_agent/test_graph_read_outcome.py \
  tests/agents/slo_agent/tool_execution/test_yield_control.py
poetry run black --check src/agents/slo_agent/watchdog_timer.py tests/agents/slo_agent/test_watchdog_timer.py
poetry run mypy src/agents/slo_agent/watchdog_timer.py tests/agents/slo_agent/test_watchdog_timer.py
git diff --check
```

Record exact RED/GREEN commands, cwd/env, exits/counts and source hashes in an artifact before a compact final response. These are scoped gates, not full-suite substitutes. All remain UNRUN by this analyst. Review closure: helper promises proved, existing watchdog/control/outcome tests preserved, <100 production lines, production path unchanged, no leaked task and no claim of urgent delivery. Otherwise REVISE; no automatic retry dispatch here.

## Required next runnable journey — not satisfied by this helper

After helper closure, the next coherent implementation assignment must connect the whole race/consumer settlement barrier, not enable yield at one side first:

`LocalSessionMessagingClient.submit(priority=urgent)` → real session queue/SQLite admission → newer-than-captured high-water → one watchdog reader with phase/abort/deadline/urgency precedence → reserve/cancel/join → agent close exactly once → durable interruption/no-start proof where required, interrupted-context exclusion and strict settlement → abort/stop-hook gate → one boundary advance/application/receipt → next provider request.

Use original proposed `tests/integration/test_messaging_yield.py::test_silent_provider_urgent_delivery`, reusing real composition in `tests/agents/slo_agent/messaging/test_delivery.py` (`RecordingModel`, `RealAgentFactory`) and existing integration receipt readback. Hold external first/next token with Events; admit urgent without releasing token; assert joined/closed reader before request two, one urgent application/SQLite receipt, raw history on flat and tree adapters, no interrupted/private continuation context in request two, and no extra claim/request on settlement failure or abort. Actual provider boundary alone may be scripted. Do not mock session, graph, queue, SQLite or history. This proposed file/test does not yet exist as evidence.

Complete §5.3 matrix remains required: abort > done reader > active provider deadline > urgency; phase transition inside pending read beats deadline, same-reader drain when tools win, sealed source disarmed without spinning, cancellation-suppressed None/value retained, reader/close failures terminal rather than retryable. Correct None-versus-end extraction during this migration. Safe consumer handles yield and joined truth before any runtime caller passes control/abort. Host remains normal-only until full A.2 activation requirements are met. Independent early actual-urgent review, final review and completion are mandatory and pending.

## Rules, safety and provenance

Both actual `SLO_SKILL_DIR` and `SLO_SKILLS_DIR` equal `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`; used that installed root, not checkout skills. Read its INDEX and exact workflow/shared rules, engineering routing/ownership/testing, overarching solution-design/coding-rules/code-design-principles/naming/test-verification/declarative structure, Python root/type-keyword/docstring/declarative rules. Continuation author must read applicable implementation/graph recipes from `routing.md` when that scope resumes. Tell-don't-ask, declarative structure, typed keyword interfaces, test-first and no regressions remain mandatory. No new harness or framework. README, canonical local project memory and KB Welcome/slo README/gotchas consulted; root RESEARCH.md absent and not created under this read-only scope. Explicit current artifact destinations specialize historical KB-only advice; no other docs or KB edits authorized here.

Preserve SLO.md, docs/, preflight and all prior artifacts. No executable/bin mutation directly or indirectly, installer/herdr fixture, packages/system/infrastructure or git writes/publication. Sole existing deploy-worker tmp bin/curl 0755 child-only PATH verified-root exception was NOT exercised and authorizes nothing else. `make test PYTEST_WORKERS=6` remains **BLOCKED** by other specific consent; no deselection/substitute/model or mode evasion. Full static **UNRUN**; mypy baseline **UNESTABLISHED**. This design grants no execution or dispatch authority.
