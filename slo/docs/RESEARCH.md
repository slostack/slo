# Slo Codebase Index

This concise index points maintainers to the runtime owners most relevant to Feature 75 plugin extensions and the adjacent agent/TUI seams.

## Runtime path

```text
src/cli/app.py → src/cli/typer_dispatch.py → SloAgentSession
  → SloAgent → graph/service.py tool node → ToolExecutor → agent tools
  → AgentStreamEventDAO subscribers → TranscriptProjector → Textual widgets
```

- `src/cli/app.py` is the Typer parse surface. `src/cli/typer_dispatch.py` owns runtime assembly. `src/cli/plugin.py` provides the managed-plugin lifecycle sub-app.
- `src/agents/slo_agent/sessions/service.py` owns session construction, plugin loading/merging, event subscribers, durable history coordination, and the named `before_agent_turn` consumer seam.
- `src/agents/slo_agent/agent.py` owns the multi-turn ReAct loop, runs `before_agent_turn` plugin handlers before every outer iteration with the true iteration number, and drains graph-owned partial-output updates into its normalized event stream.
- `src/agents/slo_agent/graph/service.py` owns LangGraph construction, the tool node, executor selection, and the queue-to-stream bridge for `tool_output_update`.
- `src/agents/slo_agent/tool_execution/executors.py` is the tool-call chokepoint for sequential/concurrent execution, immutable per-invocation `RunnableConfig.configurable` output callback binding, and plugin tool interception.

## Feature 75 plugins

- `src/agents/slo_agent/plugins/dao.py` defines typed registrations, health records, and interception decisions.
- `api.py` is the recorder passed to `register(slo)`; it records registrations and can forward live status updates to the session-owned dispatcher map.
- `identity.py` validates GitHub/GitLab HTTPS sources and derives IDs, module names, tool names, command tokens, and status keys.
- `installer.py` is the only managed-directory writer. It validates manifests, copies declared payloads without executing source code, pins provenance, and rolls back swap-phase failures. It also exposes explicit bundled Bash renderer installation with `package:<version>` provenance.
- `trust.py` persists project trust decisions with `AtomicFileWriter`; unreadable state fails closed.
- `loader.py` discovers managed, trusted-project, and explicit `--plugin` paths; it imports each under a namespaced module and isolates load failures.
- `registry.py` merges registration views, refuses collisions, and cross-validates managed tool/command suffixes against manifest declarations.
- `dispatcher.py` isolates event handlers and interception hooks, enforces timeout policy, and owns the live status map.

Managed installed plugins live under `~/.slo/plugins/plugins/<plugin-id>/`; `~/.slo/plugins/registry.json` is the durable install registry. Development dogfooding uses the explicit tier:

```bash
slo --plugin plugins/bash_live_output/plugin.py
```

## Live Bash output

- `src/agents/tools/tool_output.py` defines the display-only `ToolOutputUpdateDAO` snapshot.
- `src/agents/tools/bash.py` incrementally reads merged output, extracts its optional callback from mapping-shaped `RunnableConfig.configurable`, retains terminal formatting/kill/reap behavior, and emits throttled snapshots when a callback exists.
- `tool_output_update` is a `StreamEventKind` in `src/agents/slo_agent/events/stream.py`. It is emitted on normal subscribers and headless stdout JSONL, and persisted when history is enabled; `history/projector.py` excludes it from model replay.
- `src/tui/transcript_projector.py` routes an update by `tool_call_id` to the existing `ToolExecutionBlock`; `src/tui/widgets/tool_execution_block.py` keeps partial output separate from terminal lifecycle truth.
- `src/tui/event_renderer.py` consults registered renderers before built-in summaries. `plugins/bash_live_output/` is the bundled consumer-only raw Bash renderer.

## Operator and TUI surfaces

- `slo plugin install <url> --yes`, `list`, `uninstall <id>`, and `upgrade <id>` delegate through `TyperDispatch.plugin` to `PluginInstallerService`.
- `/plugins`, `/plugins trust`, and `/plugins reload` are registered in `src/tui/slash_command_registry.py` and handled in `src/tui/slash_router.py`.
- `src/tui/widgets/usage_status_bar.py` renders a plugin status segment from the dispatcher’s live status map when the app provides updates.

## Verification owners

- Plugin tests: `tests/agents/slo_agent/plugins/`.
- Streaming executor/bridge/history tests: `tests/agents/slo_agent/tool_execution/`.
- Bash streaming tests: `tests/agents/tools/test_bash_streaming.py`.
- TUI tests: `tests/tui/test_tool_block_partial.py`, `tests/tui/test_event_renderer_overrides.py`, `tests/tui/test_plugins_slash_command.py`, and `tests/tui/test_usage_status_bar_plugins.py`.
- Bundled-plugin contract: `tests/plugins/test_bash_live_output_plugin.py`.
- CLI lifecycle surface: `tests/cli/test_plugin_cli.py`.
