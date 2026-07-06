# Changelog

All notable changes to **slo** are documented here. This project adheres to
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may carry
breaking changes).

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
