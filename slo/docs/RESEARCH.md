# Slo — Codebase Index

Reference for navigating the source tree. Updated through spec 20 (session lifecycle naming, resume-by-name, prompt-history recall, and transcript surface parity). 847 tests pass.

---

## Top-level layout

```
slo/
├── config/               # env config, model table, logger
├── connectors/           # async SQLAlchemy session helpers
├── db/                   # Alembic migrations
├── docker/               # docker-compose for dev/test Postgres+Redis
├── environments/         # development.env, tests.env
├── scripts/              # refresh_skills.py, build_skill_index.py
├── skills/               # 100+ vendored SKILL.md files (10 groups)
├── specifications/       # symlink → ../specifications (specs 01–18)
├── src/                  # all Python application code
│   ├── agents/           # agent loop, LLM factory, tools, providers, auth
│   ├── cli/              # Typer CLI entry point
│   ├── exceptions.py     # typed ApiException hierarchy
│   ├── main.py           # FastAPI entry (healthz only)
│   ├── middleware/       # DbMiddleware, RequestCtxMiddleware
│   ├── routers/          # health_controller, base_controller
│   ├── scheduling/       # scheduler DAOs, store, runtime executor, OS integration
│   ├── tui/              # Textual TUI, slash system, widgets
│   └── web_app.py        # FastAPI initializer (middleware + routers)
└── tests/                # pytest suite (faux-model only)
```

---

## `src/agents/slo_agent/` — agent core

| File | Purpose |
|---|---|
| `agent.py` | `SloAgent` class — owns compiled graph, steering/follow-up queues, abort signal; consumes LangGraph dual-stream and emits `AgentStreamEventDAO` events |
| `graph.py` | `SloAgentStateDAO`, `build_slo_agent()` → `SloAgentBuildResult` (NamedTuple: graph + tools + supports_explicit_caching); fixes tools=None bug by returning resolved tool list |
| `session.py` | `SloAgentSession` — in-process wrapper; rate-limit retry + cooldown via `rate_limit_policy`; subscriber fan-out; `prompt_streaming()` persists `assistant_delta` events; owns runtime session naming via `rename_session()` + `session_name` |
| `session_dao.py` | `SessionConfigDAO`, `SubmitResultDAO`, `AgentEventSubscriber` type alias; carries `history_root` / `enable_history` for replacement sessions |
| `dao.py` | `StreamRequestDAO`, `QueryDAO`, `ProgressEventDAO` |
| `stream_event_dao.py` | `AgentStreamEventDAO` + `StreamEventKind` — in-process interactive stream contract |
| `runtime_event_dao.py` | `AgentRuntimeEventDAO` — full-fidelity event emitted by `react_streaming(runtime_handler=...)` |
| `rate_limit_policy.py` | `ModelRateLimitPolicyDAO`, `RateLimitRetryPlanDAO`, `policy_for_model()`, `retry_plan_from_error()` |
| `session_usage_dao.py` | `SessionUsageSnapshotDAO`, `TokenUsageTotalsDAO` (with `cache_creation_input_tokens` / `cache_read_input_tokens`) |
| `skills_loader.py` | `SkillsLoader.load()` + `SkillEntryDAO` — scans skills tree, parses YAML frontmatter, returns invocation-eligible entries for `<available_skills>` XML block |
| `project_context.py` | `ContextFileEntryDAO`, `ProjectContextDiscovery.invoke()` — walk-to-root (SLO.md / AGENTS.md / CLAUDE.md) + `~/.slo/` global tier; returns global-first, deepest-project-first |
| `message_text.py` | Utility: extract plain text from `BaseMessage` |
| `assistant_chunk_normalizer.py` | Stateful `AIMessageChunk` → `AgentStreamEventDAO` normalizer with block start/end semantics |
| `graph_stream_parser.py` | Version-safe parser for LangGraph dual-stream items → `ParsedGraphStreamItemDAO` |
| `turn_stream_accumulator.py` | Completed-state helper for one outer-loop turn |
| `prompts/system_prompt.py` | `SystemPromptBuilder.invoke()` — assembles tools block, `<available_skills>` XML (via `SkillsLoader`), project context, cwd, custom prompt |
| `history/dao.py` | `SessionHistoryEventDAO`, `SessionHistoryMetadataDAO`; `assistant_delta` canonical event kind; metadata includes `session_name` + `session_name_key` |
| `history/filesystem_store.py` | Append-only JSONL store under `~/.slo/sessions/history/<session_id>/`; atomic rewrites; `0700`/`0600` permissions; `normalize_session_name_key()`, `rename_session()`, and `resolve_session_reference()` for resume-by-name |
| `history/projector.py` | Projects canonical events → `list[BaseMessage]` for next-turn context |
| `history/transcript.py` | `ReplayEntryProjector` + `TranscriptEntryDAO`; replay entries for TUI mounting + `transcript.md` export |
| `tool_execution/` | Sub-package for tool execution helpers |

---

## `src/tui/` — Textual TUI

| File | Purpose |
|---|---|
| `app.py` | `SloTUI` (Textual app) + `PromptInput` (TextArea with custom `Submitted` message); owns in-flight task guard, `^C` interrupt, title-bar refresh, `/new` replacement, `/rename`, and prompt-history recall |
| `prompt_history.py` | `PromptHistoryNavigator` — in-process `Up`/`Down` recall for submitted non-slash prompts |
| `slash_router.py` | `SlashRouter.dispatch()` + `SlashCommandResultDAO`; handles `/help`, `/clear`, `/exit`, `/cwd`, `/abort`, `/steer`, `/model`, `/reasoning`, `/new`, and `/rename` |
| `slash_command_registry.py` | `SlashCommandRegistry`, `SlashCommandSpecDAO`, `build_default_registry()` — canonical metadata for all slash commands (name, description, aliases, argument_mode, usage), including `/new` and `/rename` |
| `slash_suggestion_engine.py` | `SlashSuggestionEngine` — pure suggestion logic; `SlashSuggestionRowDAO`, `SlashSuggestionStateDAO` |
| `event_renderer.py` | Tool-line formatting helpers; legacy `ProgressEventDAO` renderer |
| `transcript_projector.py` | Stateful transcript projector for live `AgentStreamEventDAO`s and replay `TranscriptEntryDAO`s |
| `model_catalog.py` | `ModelSuggestionEntryDAO`, `model_suggestion_entries()` — model list for `/model` autocomplete |
| `thinking_spinner.py` | Spinner widget shown during LLM reasoning |
| `authentication/` | Sub-package for OAuth flow widgets |
| `app.tcss` | Textual CSS styles |
| `widgets/__init__.py` | Widget re-exports |
| `widgets/user_message_block.py` | Dedicated user-turn widget; padded markdown; panel-style surface treatment |
| `widgets/assistant_stream_block.py` | Streaming assistant-turn widget; reasoning summary first, answer second; distinct reasoning/answer surfaces |
| `widgets/tool_execution_block.py` | Live-updating tool call + result widget; Claude-Code-style rows with shared panel rhythm |
| `widgets/slash_suggestion_menu.py` | Floating suggestion menu that appears when `/` is typed |
| `widgets/usage_status_bar.py` | Status bar showing per-turn and session token totals + rate state |

---

## `src/agents/tools/` — tool catalog

9 tools bound to the agent; all follow `*SchemaDAO` args + `XxxTool` class + `@tool` bridge pattern.

| Tool | Module | Description |
|---|---|---|
| `read` | `read.py` | Text + image multimodal; offset/limit line slicing; blocking work via `_blocking` |
| `write` | `write.py` | Full-file write; auto-creates parent dirs |
| `edit` | `edit.py` | Exact-text replacement; uniqueness + overlap detection |
| `bash` | `bash.py` | `/bin/bash -c` subprocess; timeout; tail-truncation + spill to tmp |
| `grep` | `grep.py` | Regex/literal pattern search; .gitignore filtering; per-line truncation |
| `find` | `find.py` | Glob-walk; .gitignore filtering; sorted relative paths |
| `ls` | `ls.py` | Sorted directory listing; `/` suffix on subdirs |
| `read_pdf` | `read_pdf.py` | pypdf text extraction; 1-indexed page-range slicing |
| `now` | `now.py` | Current UTC ISO 8601 timestamp |

Supporting modules: `_truncate.py` (head/tail/line limits), `_gitignore.py` (walk-to-root filter), `_image_content.py` (Pillow sniff + base64), `_blocking.py` (bounded `asyncio.to_thread` semaphore), `bundles.py` (`create_coding_tools()`, `create_all_tools()`, etc.), `prompt_snippets.py` (`TOOL_PROMPT_SNIPPETS` registry), `a2a_peer.py` (outbound A2A peer delegation).

---

## `src/agents/providers/` — LLM providers

| File | Purpose |
|---|---|
| `faux.py` | `FauxChatModel` — deterministic queue-based model for tests |
| `anthropic_claude_code.py` | `build_claude_code_backed_chat_anthropic()`, `anthropic_thinking_payload()` |
| `openai_codex.py` | `build_chatgpt_backed_chat_openai()` (ChatGPT subscription lane), `openai_reasoning_payload()` |

`src/agents/base.py` owns `LLMFactory.create()` dispatch and the `LLMBuildResult` dataclass (`llm` + `supports_explicit_caching`). Anthropic builds set `supports_explicit_caching=True`; OpenAI/Faux leave it `False`. The agent annotates `SystemMessage` with `cache_control` only when `supports_explicit_caching` is true.

---

## `src/auth/` — credential chain

| File | Purpose |
|---|---|
| `credential_dao.py` | `CredentialDAO`, `AuthType`, `ProviderName` |
| `credential_resolver.py` | `CredentialResolver.require()` — env > store > legacy-Claude precedence |
| `credential_refresher.py` | `refresh_if_stale()` — proactive OAuth refresh + persist; module-level lock |
| `credential_store.py` | Read/write `~/.slo/.credentials.json` |
| `oauth_flow.py`, `oauth_provider.py`, `pkce.py` | PKCE OAuth flow |
| `provider_for_model.py` | Model name → provider name mapping |
| `provider_factory.py` | Auth provider factory |
| `providers/` | Per-provider OAuth sub-implementations |

---

## `skills/` — 100+ vendored skills

10 group directories; each skill is `skills/<group>/<slug>/SKILL.md` with YAML frontmatter (`name`, `description`, `when_to_use`, `group`, `kind`).

| Group | Contents |
|---|---|
| `design-and-analysis/` | Feature specs, code-test-review pipeline, breakdown, distill-learnings, specification-development, workflows |
| `coding/` | Build patterns: tools, services, routers, middleware, workers, etc. |
| `git-ops/` | Branch, commit, push, PR/MR, ship-feature lifecycle, worktrees |
| `cli/` | Typer CLI apps, command classes, modules |
| `tui/` | Textual TUI apps, plus `tui-scheduled-workflows` for scheduler-driven workflow supervision and `tui-scheduled-operations` for generic recurring/delayed TUI scheduling |
| `integration-tests/` | pytest-bdd scenarios, step definitions |
| `frontend-vue/` | Vue 3 + Pinia + TypeScript conventions |
| `orientation/` | Codebase orientation, KB navigation |

`INDEX.md` at the root of `skills/` is the generated manifest — regenerate with `make build-skill-index`. The system prompt inlines an `<available_skills>` XML block at startup (via `SkillsLoader`), not a pointer; the agent reads individual `SKILL.md` files on demand via the `read` tool.

---

## `tests/` — layout

```
tests/
├── agents/
│   ├── slo_agent/      # session, graph, agent, prompts, skills_loader, project_context,
│   │                   #   rate_limit_policy, session_usage, stream events, history, …
│   ├── providers/      # faux model, anthropic, openai
│   ├── hooks/          # ShouldStopAfterTurnHook
│   ├── skills/         # SkillRegistry
│   └── tools/          # per-tool unit tests
├── tui/                # app, slash router, slash registry, suggestion engine,
│   │                   #   suggestion menu, tool_execution_block, usage_status_bar,
│   │                   #   thinking_spinner, transcript_projector, replay/resume, …
│   └── authentication/ # OAuth flow TUI tests
├── auth/               # credential resolver, refresher, store
├── cli/                # Typer dispatch
├── config/             # cfg, ai_model_config
├── domains/            # SQLAlchemy domain tests
├── routers/            # healthz
├── services/           # application service tests
└── conftest.py         # shared fixtures (FauxChatModel session, tmp dirs, …)
```

All tests use `FauxChatModel`; `pytest -m "not e2e"` is the default gate (`make test` self-sources `tests.env`).

---

## Key DAOs / contracts

| DAO | Module | What it represents |
|---|---|---|
| `SloAgentBuildResult` | `graph.py` | NamedTuple: compiled graph + resolved tools + `supports_explicit_caching` |
| `LLMBuildResult` | `base.py` | Dataclass: `llm` + `supports_explicit_caching` flag |
| `AgentStreamEventDAO` | `stream_event_dao.py` | In-process interactive event (thinking_*, text_*, tool_call_*) |
| `ContextFileEntryDAO` | `project_context.py` | One discovered instruction file (path, content, tier) |
| `SkillEntryDAO` | `skills_loader.py` | Parsed skill metadata (name, description, file_path) |
| `ModelRateLimitPolicyDAO` | `rate_limit_policy.py` | Per-model rate window + retry config |
| `TokenUsageTotalsDAO` | `session_usage_dao.py` | Token counts incl. cache_creation + cache_read tokens |
| `SlashCommandSpecDAO` | `slash_command_registry.py` | Slash command metadata (name, description, aliases, argument_mode) |
| `SlashSuggestionStateDAO` | `slash_suggestion_engine.py` | Engine output for current prompt buffer |

---

## Not yet implemented

- 01.g persona templates (runtime system-prompt-builder is shipped; persona templates still pending).
- 01.k integration test suite (rescoped to test `SloAgentSession` flow; not yet written).
