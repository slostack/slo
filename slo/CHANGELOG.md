# Changelog

All notable changes to **slo** are documented here. This project adheres to
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may carry
breaking changes).

## [0.14.11] — 2026-07-22

**Explicit orchestrator routing (spec 56) + non-blocking dynamic workflows (spec 57).**

**Spec 56** restores "dynamic workflows" to sync in-session execution and introduces the detach qualifier as the only route to `launch_workflow`. An unqualified "dynamic workflows" request now blocks the TUI and runs the workflow phases in the current session via `spawn_sub_agents`; only a request carrying an explicit detach qualifier — the word "headless", "detached", or "independent" applied to the dynamic-workflows request or to a named workflow ("headless dynamic workflows", "detached dynamic workflows", "independent dynamic workflows", or detach wording "in the background" / "without blocking") — routes to a single `launch_workflow` call. Detached orchestrators no longer receive `launch_workflow` (structural guard) and refuse recursion via `SLO_WORKFLOW_ID` (depth guard), closing the three-level cascade observed in session `7222023f-db7a-4d68-98b6-013551e101c6`.

**Spec 57** built the headless-workflow machinery: the `launch_workflow` tool, the workflow handle registry, the `WorkflowNotifier`, the TUI receive path, and the `/workflows` slash command — all described below.

### Refactored

- **Detached-workflow TUI receive path** — split the previously app-local lifecycle logic into `src/tui/workflows/`:
  - `dao.py` validates lifecycle payloads and `launch_workflow` results into typed data and UI effects without Textual, filesystem, or launcher side effects;
  - `service.py` (`DetachedWorkflowAppService`) reconciles and advances durable workflow handles, maintains the live-workflow cache used by resume hints, and returns typed effects;
  - `renderer.py` (`DetachedWorkflowRenderer`) owns visualizer launch de-duplication, launcher calls, and success/fallback transcript notices through narrow Protocol ports.
  `SloTUI` now composes these collaborators and routes events rather than parsing workflow JSON, changing handles, or launching detached visualizers itself.
- **Receive-path resilience and regression coverage** — malformed/error launch JSON, malformed lifecycle payloads, missing handles, illegal transitions, and handle-store failures are safe no-effect paths that do not interrupt inbox delivery. Terminal lifecycle events reset only the visualizer launch guard, allowing later workflow runs to launch a fresh window without opening one at terminal delivery.
- **Operator-facing lifecycle documentation** — clarified that inbox delivery requires enabled filesystem-backed session history because detached processes write the cross-process inbox; expanded `SessionOwnershipLeaseStore` documentation to explain acquire/renew/release, expiry, and TUI hand-off behavior.

### Added

- **`launch_workflow` tool** (`orchestrator/launch_tool.py`) — detached spawn
  with `start_new_session=True`, non-secret `SLO_*` env allowlist,
  handle-file-before-spawn crash safety, live-workflow cap
  (`SLO_MAX_DETACHED_WORKFLOWS`, default 2), and error-JSON-never-raise
  semantics on every failure path (capture files, spawn, handle writes). An
  operator abort landing mid-spawn is honoured by reaping the fresh process
  group. Depth guard: refuses (error JSON, no spawn) when `SLO_WORKFLOW_ID` is
  present in the process environment.
- **Workflow handle registry** (`orchestrator/workflow_registry.py`) —
  `WorkflowHandleDAO` + `WorkflowHandleStore` (atomic 0600/0700 writes,
  legal-transition table, pid-liveness `reconcile` with a 30 s launch grace
  window, path-safe workflow ids) and the read-only `workflow_status` tool.
- **`WorkflowNotifier` + `slo run --notify-session <sid>`**
  (`orchestrator/notifier.py`, `cli/headless.py`) — the headless runner taps
  its own event stream and enqueues durable inbox messages: `workflow_started`
  and per-phase `workflow_phase_update` as `context_note`, terminal
  `workflow_completed`/`workflow_failed` as `chat_turn`. Enqueue failures are
  swallowed; without the flag, headless behaviour is byte-identical.
- **`context_note` delivery mode + `workflow_update` history events** — claimed
  notes render a `⊛` line AND persist a synthetic completed turn (idempotent on
  inbox `message_id`) that `SessionHistoryProjector` includes in model context
  as `[workflow update] …`, in true chronological position, surviving
  `--resume` (resume context is golden-equal to live context). New session API
  `SloAgentSession.record_workflow_update`.
- **TUI receive path** (`tui/app.py`) — visualizer retargeted to the
  orchestrator's session id from the `launch_workflow` tool result (fallback:
  the `workflow_started` note on resume), one window per orchestrator session;
  claimed notes advance the durable handle state; mount-time reconcile; the
  exit hint lists live workflows; `^C`/`/abort` keep today's
  current-turn-only meaning.
- **`/workflows` slash command** (`/wf`) — reconciled list, `abort <id>`
  (SIGTERM to the process group, SIGKILL escalation after 5 s), `dismiss <id>`
  for stalled workflows. `WorkflowCommandService` refuses non-positive pids so
  a never-patched handle can never signal the TUI's own process group.
- **Kill switch** `SLO_DETACHED_WORKFLOWS=0` keeps all dynamic-workflow
  requests in-session via `spawn_sub_agents`.

### Changed

- `SloAgentSession.attach_sub_agent_pool` accepts a `spawn_tools` list;
  `OrchestratorSessionBootstrap.attach` gains `headless: bool = False`; when
  `headless=True` (the `HeadlessRunner --orchestrator` path) `_build_workflow_tools`
  returns `[]` so detached orchestrators structurally cannot call `launch_workflow`
  or `workflow_status`; TUI call site is unchanged and keeps all three tools.
- Orchestrator prompts rewritten (spec 56): unqualified "dynamic workflows" runs
  in-session via `spawn_sub_agents`; only a detach-qualified request routes to
  `launch_workflow`; routing documented across `spawn_tool.py`,
  `launch_tool.py`, `AGENTS.md`, `CLAUDE.md`, `skills/INDEX.md`,
  headless-orchestration / workflows / orchestrator `SKILL.md` files, and
  `docs/SLO_HEADLESS_README.md`.
- Test harness safety: `environments/tests.env` sets `SLO_AUTO_VISUALIZE=0`
  and an autouse fixture in `tests/conftest.py` stubs
  `VisualizerLauncher._default_spawn`, so no test run can ever open real
  terminal windows on the developer's machine (regression-tested).

### Tests

- ~130 new tests across the handle store, launch tool, notifier, headless tap,
  context delivery/projection/replay, TUI receive path, and `/workflows`
  service + router; full suite 2801 passing.

## [0.14.10] — 2026-07-19

**Longer inactivity timeouts for slow, large-context model calls.** The two
inactivity watchdogs that guard against genuinely hung streams were raised so
that legitimately slow turns — big prompts, slow time-to-first-token, long
tool/model lanes — are no longer misclassified as hangs and killed mid-turn.

### Changed

- **`STREAM_INACTIVITY_TIMEOUT_SECONDS` default raised `2400` → `4800`** (40 → 80
  minutes). This is the orchestrator's / main agent's own LLM-stream inactivity
  guard. Overridable via `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS`. Updated in
  `config/cfg.py` and the `_DEFAULT_STREAM_INACTIVITY_TIMEOUT_SECONDS` fallback
  in `src/agents/slo_agent/sessions/service.py`.
- **`SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` default raised `1800` → `3600`** (30 → 60
  minutes). This is the child sub-agent stdout inactivity guard
  (`CHILD_INACTIVITY_TIMEOUT_SECONDS`). Overridable via
  `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` (alias
  `SLO_SUBAGENT_INACTIVITY_TIMEOUT`). Updated in `config/cfg.py` and
  `src/agents/slo_agent/orchestrator/process.py`.
- Both values remain env-overridable; only the shipped defaults changed.
- Synced the shipped-default documentation to the new values: the orchestrator
  runtime prompt (`orchestrator/spawn_tool.py`), `README.md`,
  `docs/SLO_HEADLESS_README.md`, the `headless-orchestration` skill, and
  `scripts/validate_recovery.py`.

### Tests

- Updated the shipped-default assertions in `tests/config/test_cfg.py`,
  `tests/agents/slo_agent/orchestrator/test_process.py`, and
  `tests/agents/slo_agent/test_session.py` to expect `4800.0` / `3600.0`.

## [0.14.9] — 2026-07-19

**Automatic live visualization + a richer, resizable workflow visualizer.** When
an orchestrator-backed TUI session spawns its first sub-agent, Slo now opens
`slo visualize` in a separate terminal window automatically and keeps it following
the run — operators no longer have to notice a workflow went headless and open the
viewer by hand. The visualizer UI itself was reworked from an MVP into a themed,
keyboard-resizable, markdown-rendering surface that mirrors the main TUI.

### Added

- **Auto-launch of the workflow visualizer** (`src/tui/visualizer_launcher.py`):
  - New `VisualizerLauncher` opens `slo visualize --session <parent_session_id> --follow`
    in a fresh OS terminal window. macOS drives Terminal.app / iTerm via `osascript`;
    Linux probes common terminal emulators (`gnome-terminal`, `konsole`, `xterm`, …);
    unsupported platforms and spawn failures fall back gracefully.
  - `SloTUI._maybe_launch_visualizer` fires the launch exactly once per run on the
    first `sub_agent_spawned` event, guarded by `_visualizer_launched_for_run` and
    reset in `_cleanup_sub_agent_state`. On failure it writes the manual
    `slo visualize` command into the transcript instead.
  - Only a **non-secret `SLO_*` allowlist** (`SLO_HOME`, `SLO_ENV`, `PYTHONPATH`, …)
    is forwarded into the new window; provider keys and deploy tokens are never
    placed in the world-readable argv.
- **New config flags** (`config/cfg.py`): `SLO_AUTO_VISUALIZE` (default on; set `0`
  to opt out) and `SLO_VISUALIZER_TERMINAL_APP` (choose `Terminal` / `iTerm` on
  macOS or a terminal-emulator executable on Linux).
- **Workflow-summary bar** in the visualizer showing run state and a colour-coded
  tally of sub-agents by status (running / completed / failed).
- **Test coverage**: `tests/tui/test_visualizer_launcher.py`,
  `tests/tui/test_visualizer_ui_enhancements.py`, and new auto-launch cases in
  `tests/tui/test_subagent_event_routing.py`.

### Changed

- **Visualizer UI redesign** (`src/tui/headless_workflow_visualizer.py`):
  - **Keyboard-resizable panes** — `ctrl+←/→` widen/narrow the sub-agent list,
    `ctrl+↑/↓` grow/shrink the diagnostics pane (clamped, applied live). This
    directly addresses the inability to resize the sub-agent (phase) panel.
  - **Themed styling** aligned with the main TUI theme variables
    (`$surface` / `$accent` / `$panel` / `$boost`).
  - **Markdown transcript rendering** — assistant answers and user messages render
    through `rich.markdown.Markdown`, matching the main TUI; sub-agent list entries
    are colour-coded by status.
  - Status bar now reports the current pane sizes.

### Fixed

- The visualizer no longer has to be launched and discovered manually for
  orchestrator (dynamic) workflows started from the TUI.

### Notes

- Version bumped to `0.14.9` in `pyproject.toml`; `AGENTS.md` documents the
  auto-launch behavior and the new resize / rich-rendering surface.

## [0.14.8] — 2026-07-18

Unified model-catalog **latest-model support**: Slo now defines model support once in a canonical `src/agents/model_catalog` package and projects that truth into config, reasoning, provider routing, TUI model surfaces, startup fallback notices, and orchestrator child prompt wiring. This release adds the latest first-class OpenAI, Anthropic, and Kimi lineup while preserving compatibility aliases and keeping the non-e2e suite green.

### Added

- **Canonical model catalog package** (`src/agents/model_catalog/`):
  - `dao.py` — typed catalog, runtime-profile, reasoning-profile, alias, template, discovery, and override DAOs.
  - `seed.py` — committed first-class catalog entries for `gpt-5.5`, `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`, `claude-fable`, `claude-mythos`, `kimi-k3`, and `kimi-for-coding-highspeed`, plus retained existing production models.
  - `service.py` — memoized seed/cache/discovery/override load path and canonical entry resolution.
  - `store.py` — cache and override persistence under `~/.slo/global/`.
  - `discovery.py` — best-effort provider discovery merge surface and override application helpers.
  - `prompt_clause.py` — exact-match Kimi task-prompt suffix injection for `kimi-for-coding` only.
- **User-visible invalid-model fallback notice** plumbed from config/session startup into the TUI so a bad saved model preference falls back safely and tells the operator what happened.
- **Catalog-focused regression coverage** across seed data, discovery/override behavior, provider routing, Kimi prompt-clause wiring, startup notices, and TUI `/model` projections.

### Changed

- **Legacy model-support surfaces are now catalog-backed projections**:
  - `config/ai_model_config.py`
  - `src/agents/reasoning_capabilities.py`
  - `src/auth/provider_for_model.py`
  - `src/tui/model_catalog.py`
  - `src/tui/slash_router.py`
- **Session startup and CLI config construction** now preserve and render fallback-notice metadata when a requested model is invalid or compatibility-only.
- **Orchestrator child prompt assembly** now appends the terse Kimi clause only for the exact model name `kimi-for-coding`, not for `kimi-k3` or `kimi-for-coding-highspeed`.
- **Prompt-critical docs** (`AGENTS.md`, `README.md`, `docs/RESEARCH.md`, `docs/SLO_HEADLESS_README.md`) now describe the canonical catalog architecture instead of the older split-table model story.

### Fixed

- **Kimi family temperature handling** now sets `temperature=1` for every canonical `ProviderName.KIMI_FOR_CODING` model, fixing runtime 400s for `kimi-k3` and `kimi-for-coding-highspeed` (`invalid temperature: only 1 is allowed for this model`).
- **Full-suite gate regression** in `skills/presentation/present-as-pdf-book/SKILL.md` by restoring the required `## Guidance` section so the repo default test gate remains green.

### Notes

- `claude-mythos` remains hidden by default and capped at `high` reasoning until availability is confirmed by discovery or operator override.
- Kimi family models remain `off`-only for user-configurable reasoning because the provider does not expose controllable reasoning levels.
- Verification for this release: targeted catalog/tests green, touched-surface mypy green, full non-e2e suite green (`2590 passed, 4 deselected`).

## [0.10.2] — 2026-06-27

Provider **message-contract reconciliation** — fixes a crash where a session
whose model emitted an empty final assistant turn replayed an empty `assistant`
message and the provider rejected the turn with `400 invalid_request_error`
(*"the message at position N with role 'assistant' must not be empty"*).
Independent of compaction. No schema change; backward-compatible.

### Fixed

- **No empty assistant message is replayed.** A turn that ends with an
  `assistant_message` carrying no text and no tool calls (the model produced an
  empty final response after its tool results) no longer projects to an empty
  `AIMessage`. The reconciler drops it, keeping the surrounding tool pair and
  the next user message intact.

### Changed

- **`ToolCallReconciler` → `MessageContractReconciler`** (renamed/broadened from
  0.10.1). It is now the single enforcer of every provider message-contract rule
  on the projected history: drop orphan/id-less tool results, heal dangling tool
  calls, **and** drop empty assistant messages. `_event_to_message` stays a pure
  event→message map; provider legality lives in one place. New provider rules
  are added here.

### Notes

- 6 new/renamed unit tests + 1 projector regression test; full suite green;
  mypy clean on the touched modules. Implements
  `specifications/42-message-contract-reconciliation`.

## [0.10.1] — 2026-06-27

Compaction **cut integrity** — fixes a crash where a compacted session could
replay an orphaned `tool_result` and the provider rejected the turn with
`400 invalid_request_error` (`tool_call_id is not found` on the OpenAI/Kimi
lane). No schema change; backward-compatible with 0.10.0 sessions.

### Fixed

- **The compaction cut never splits a tool span.** `Compacter._find_cut_point`
  replaced its adjacency-only guard (which assumed a `tool_call` and its
  `tool_result` are neighbours) with a span-based **clean-cut** algorithm. When
  the token-driven candidate would compact a `tool_call` while retaining its
  `tool_result` — including a parallel tool-call batch or a `spawn_sub_agents`
  group with interleaved `assistant_delta` / sub-agent lifecycle events — the
  cut moves **up** (compacting slightly more) until each tool group is whole on
  one side. The returned cut is asserted clean via `_is_clean_cut`.

### Added

- **`ToolCallReconciler`** (`history/tool_call_reconciler.py`) — the single
  abstraction that enforces the provider's tool-call/tool-result pairing
  contract on a projected message list, in both directions: it drops orphan or
  id-less tool results (a result whose call was compacted away) and heals
  dangling tool calls (a call with no result). `SessionHistoryProjector`
  delegates to it. Sessions already compacted with a bad cut (pre-0.10.1) now
  load cleanly.

### Notes

- ~12 new/revised unit tests; full suite green; mypy clean on the touched
  modules. Implements `specifications/41-compaction-cut-integrity`.

## [0.10.0] — 2026-06-27

Conversation-tree **auto-compaction**: long sessions now summarise their oldest
history into a `compaction_summary` event when the running token total nears the
model's context window, keeping future turns inside the window instead of
crashing with a provider context-overflow error.

### ⚠️ BREAKING — session event logs are not backward-readable after compaction

This release adds a new persisted history event kind, **`compaction_summary`**,
to `HistoryEventKind`. Once a session is compacted, its
`~/.slo/sessions/history/<id>/events.jsonl` contains a `compaction_summary`
line.

`SessionHistoryEventDAO.kind` is a strict Pydantic `Literal`, so **any slo build
older than 0.10.0 cannot parse a compacted session** — `load_events()` raises a
`pydantic` `literal_error` on the unknown kind and the TUI surfaces it as
`(configuration error: …)`, failing the load of the **entire** session (not just
the one line).

Compatibility is **forward-only**:

- 0.10.0 reads logs written by older builds fine.
- Older builds **cannot** read logs that 0.10.0 has compacted.

**Migration / operator guidance:**

- Upgrade **every** slo install (pipx, dev checkouts) to ≥ 0.10.0 before opening
  any session that may be compacted. A common failure is running a stale global
  `pipx` `slo` against a session a newer dev build already compacted.
- Do **not** downgrade below 0.10.0 after compaction has run on a session.
- A loader-hardening follow-up (skip-and-warn on unknown event kinds, so older
  readers degrade gracefully instead of hard-failing) is tracked separately and
  is **not** included here.

### Added

- **Compaction pipeline** (`src/agents/slo_agent/compaction/`):
  - `CompactionChecker.should_compact()` — pure, local trigger decision.
  - `Compacter` + `CompactionResult` — newest-to-oldest cut-point search
    (never splits a tool_call/tool_result pair; never compacts the first user
    message), LLM summarisation of the compacted slice.
  - `CompactedSessionUpdater` — persists the `compaction_summary` event.
  - `constants.py` — `RESERVED_TOKEN_LIMIT` (16,384), `KEEP_RECENT_TOKENS`
    (20,000).
- **Projector compaction boundary** (`history/projector.py`) — emits the summary
  as a `[Previous conversation summary]` header and replays the retained tail,
  resolving the boundary from `first_kept_entry_id` so the append-only store
  layout keeps the recent context it was meant to.
- **Session wiring** (`session.py`) — `_run_compaction_if_needed()` runs after
  every completed turn and inside the context-overflow error handler
  (`_is_context_overflow_error()`).
- **Migration utilities** (`history/migration/`) — `TokenUsageBackfiller`
  (back-fills `token_usage` on pre-existing events) and `TreeMigrator`
  (`+ MigrationResult`) to adopt flat sessions into the tree layout.
- **Per-model `context_window`** on `config.ai_model_config.MODEL_DEFAULTS` —
  the single source of truth for each model's input window.

### Changed

- `CompactionChecker` now sources context windows from `MODEL_DEFAULTS` instead
  of a hardcoded, Anthropic-only table. This corrects real mis-estimates: the
  default model `gpt-5.4` is **1,050,000** tokens (was treated as 200k),
  `kimi-for-coding` is 262,144 (was 200k → compacted ~62k early), and `gpt-4o`
  is 128,000 (was 200k → would have overflowed before compaction). Claude
  models remain at 200,000 (the 1M window needs the `context-1m` beta header,
  which slo does not yet send).
- `history/filesystem_store.py` imports `TokenEstimator` lazily to keep the
  `history → compaction` dependency one-directional.

### Notes

- ~110 new unit/integration tests; full suite green (1786 passed); mypy clean.
- Adding a value to a `Literal` discriminator is not forward-compatible for
  older readers — see the BREAKING section above.
