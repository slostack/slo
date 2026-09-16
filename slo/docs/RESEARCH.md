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

## Authentication (spec 78, fix 78.b.1)

- `src/tui/authentication/auth_screen.py` drives the modal. An `OAuthFlowFactory()` instance (`src/auth/provider_factory.py`, `__call__`) builds `OAuthFlow` (browser authorization) or `DeviceAuthorizationFlow` (device authorization). The factory must be an instance: the class object is not callable with the protocol keywords, and that failure was hidden inside a fire-and-forget task until `_on_begin_oauth_done` was added.
- **OpenAI device start wire contract** (live `POST https://auth.openai.com/api/accounts/deviceauth/usercode`, checked 2026-09-14): HTTP 200 `{device_auth_id: str, user_code: str, interval: "5", expires_at: str}`. `interval` is **decimal text**, not a JSON number. `OpenAICodexOAuthProvider._interval_as_int` accepts an int or trimmed decimal text and rejects bool, negative, float, `"5.5"`, null and missing. `expires_at` is ignored; Slo keeps `SLO_OAUTH_DEVICE_TIMEOUT_SECONDS`. Fixtures must copy this live shape.
- **Link rendering decision:** `AuthorizationLink` (`src/tui/authentication/widgets/authorization_link.py`) is a thin subclass of Textual 8.2.8 `textual.widgets.Link`, shared by browser and device presentations. `show(url=...)` paints `Content.styled(text=url, style=Style(link=url))`, so segments carry an OSC 8 target and `[`/`]` are never parsed as markup. `DEFAULT_CSS` sets `width: 1fr; text-wrap: wrap` because `Link` defaults to `width: auto` and clips long URLs. TCSS `link-*` properties do not apply to it (Textual applies them only to `@click` markup). The loopback redirect URI stays a plain `Static`.
- **Browser opening:** `BrowserHost` (`src/auth/browser_host.py`) returns False on non-macOS/Windows hosts without `DISPLAY`, `WAYLAND_DISPLAY` or `BROWSER`, because CPython `webbrowser` then runs console browsers that `wait()` on the TUI terminal. `OAuthFlow` opens through `asyncio.to_thread` concurrently with the code race; `SloTUI.open_url` opens in a thread worker.
- Tests assert **painted** compositor output through `tests/tui/authentication/_painted_output.py`. The device E2E (`tests/tui/authentication/test_authentication_device_e2e.py`) runs the real screen, factory, flow and provider against a local aiohttp server; its `@pytest.mark.e2e` live smoke hits the real usercode endpoint and cancels before approval (`pytest -m e2e <file>`).

## Rate-limit preflight and provider signals (spec 77)

- `SloAgentSession` creates one immutable `PreflightDecisionDAO` for each successful local
  preflight. Its history-aware estimate is reused unchanged for local accounting and redacted
  provider observations. A local preflight exception is advisory degradation: no local accounting
  is recorded and the provider lane remains open.
- Local TPM is never a gate. An empty token window whose estimate exceeds the configured hint
  emits one durable/live `preflight_bypassed` audit and sends the request; the TUI prints the fixed
  tool-result line without changing spinner state. `preflight_bypassed` and
  `provider_limit_observed` are excluded from model replay.
- `ProviderErrorClassifier.inspect()` is the sole provider/context recognition seam. It reads
  response headers before exception headers and retains only finite positive decimal `Retry-After`
  seconds (ceil to at least one) and positive decimal request/token limits; invalid or sensitive
  headers are discarded. Each rejected lane produces at most one redacted `provider_limit_observed`
  record. For a confirmed initial context overflow with no committed output, the session retries
  once only after `compact_to_boundary()` commits; a no-op, failed, second, visible-output, or HTTP
  413 / `REQUEST_BODY_TOO_LARGE` failure is terminal and never replays, switches pool lanes, invokes
  LLM recovery, retries, or forces compaction.
- `CompactionChecker` resolves canonical, alias, and discovered models through
  `ModelCatalogService`, and triggers at `floor(context_window * 0.70)`; unknown models retain the
  conservative default capacity.

## Kimi K3 reasoning

- The model catalog owns K3's canonical `low`, `high`, and `xhigh` reasoning
  profile; `xhigh` resolves to K3 provider effort `max`. K3 always reasons, so
  `off`/`minimal` clamp to `low` and `medium` clamps to `high`.
- `LLMFactory._build_kimi_for_coding_chat_openai()` is the only Kimi native
  request boundary. It sends top-level `reasoning_effort` only for enabled K3
  resolved reasoning; K2 coding models remain off-only and never receive
  `thinking` or OpenAI Responses fields.

## Verification owners

- Plugin tests: `tests/agents/slo_agent/plugins/`.
- Streaming executor/bridge/history tests: `tests/agents/slo_agent/tool_execution/`.
- Bash streaming tests: `tests/agents/tools/test_bash_streaming.py`.
- TUI tests: `tests/tui/test_tool_block_partial.py`, `tests/tui/test_event_renderer_overrides.py`, `tests/tui/test_plugins_slash_command.py`, and `tests/tui/test_usage_status_bar_plugins.py`.
- Bundled-plugin contract: `tests/plugins/test_bash_live_output_plugin.py`.
- CLI lifecycle surface: `tests/cli/test_plugin_cli.py`.

## Slotui specification recovery (spec 79; planned, not implemented)

`/root/Code/specifications/projects/slo/specifications/79-tui-v2/` contains
the proposed Slotui extraction, not current runtime architecture. Its
cross-file contracts were independently reconciled in
`verification-report-round4.md`: the generic session remains an
async-generator single-flight gateway, generic history activation is only
`apply_rewrite(rewrite=...) -> None`, and the terminal renderer exposes a
fixture-only capture API for conformance. Before implementation, treat that
report and `tasks.md` as the dependency order and rerun the named executable
gates; do not infer that Slotui modules already exist in this repository.
