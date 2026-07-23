# Slo — Agent Reference

This file is loaded into every agent session by `ProjectContextDiscovery` and is the
authoritative reference for anyone (human or AI) working on this codebase. Update it
whenever you make a significant architectural change, add a new component, rename a module,
or alter the runtime chain or system prompt assembly.

---

## 1. Project Overview

Slo is a **Python ReAct coding-agent harness** modelled on [pi.dev](https://pi.dev) — a
mature TypeScript reference agent. We borrow pi's design ideas and re-implement them in
Python under our own conventions: LangGraph for the state machine, LangChain for the LLM
layer, Textual for the TUI, and A2A for peer delegation.

One-line framing: *pi is the teacher; Slo is the student we own.*

**What Slo does:**
- Runs an unbounded ReAct loop (reason → act → observe → repeat) over a cloud LLM
  with 9 file/shell tools bound at session start.
- Streams progress to the Textual TUI via `AgentStreamEventDAO` events.
- Persists a full-fidelity JSONL event log per session under `~/.slo/sessions/history/`.
- Loads project instruction files (`SLO.md` / `AGENTS.md` / `CLAUDE.md`) from the
  working directory tree into the system prompt automatically.
- Keeps 100+ vendored convention skills (`skills/`) readable on demand via the `read` tool.
- Delegates to remote A2A peers via `a2a_peer_tool` (outbound only).

---

## 2. Environment

- **Python 3.11.7 via a pyenv virtualenv named `slo`** — mandatory; `pyproject.toml`
  requires `>=3.11,<3.12`. Never use system Python (macOS default is 3.9).
- One-time setup: `pyenv virtualenv 3.11.7 slo && (cd slo && pyenv local slo)`.
  The `.python-version` file auto-activates on `cd`.
- Install with `poetry install` (not `--no-root`) while the virtualenv is active.
  `poetry.toml` has `virtualenvs.create=false` so Poetry installs into the pyenv env.
- **In non-interactive tool shells:** `pyenv activate` hooks may not fire. Verify
  `which python` resolves to `~/.pyenv/versions/slo/bin/python` before running anything.

| Command | What it does |
|---|---|
| `make test` | Self-sources `tests.env`; runs `pytest -m "not e2e"` |
| `make smoke` | Same as test |
| `make lint` | `poetry run mypy src/` |
| `make format` | `poetry run black src/ tests/` (line length 110) |
| `make build-skill-index` | Regenerate `skills/INDEX.md` from committed `SKILL.md` files |
| `make install` | `install.sh` → pipx install to `~/.slo/` |
| `make dev-up` | Docker: Postgres (5437) + Redis (6379) |
| `make migrate` | `alembic upgrade head` |
| `make run` | uvicorn on :7700 (currently `/healthz` only) |

---

## 3. Repository Layout

```
slo/
├── src/
│   ├── agents/
│   │   ├── base.py                    # LLMFactory.create — the ONLY LLM construction point
│   │   ├── hooks/                     # ShouldStopAfterTurnHook, Hook
│   │   ├── providers/
│   │   │   ├── anthropic_claude_code.py     # Claude OAuth / thinking payload builder
│   │   │   ├── openai_codex.py              # ChatGPT / reasoning payload builder
│   │   │   ├── credit_exhaustion_policy.py  # CreditExhaustionPolicy — classify errors by provider
│   │   │   ├── model_pool.py                # ModelPool — priority-ordered BaseChatModel router
│   │   │   └── faux.py                      # FauxChatModel — queue-based deterministic mock
│   │   ├── slo_agent/
│   │   │   ├── agent.py               # SloAgent — multi-turn invoke loop
│   │   │   ├── graph/
│   │   │   │   ├── dao.py             # SloAgentBuildResult, SloAgentStateDAO
│   │   │   │   └── service.py         # build_slo_agent, LangGraph nodes, adapt_chatgpt_backend_request
│   │   │   ├── sessions/
│   │   │   │   ├── dao.py             # SessionConfigDAO, AgentEventSubscriber
│   │   │   │   ├── usage.py           # TokenUsageTotalsDAO, SessionUsageSnapshotDAO
│   │   │   │   └── service.py         # SloAgentSession — process-level wrapper, subscribers, naming
│   │   │   ├── events/
│   │   │   │   ├── stream.py          # AgentStreamEventDAO, StreamEventKind
│   │   │   │   └── runtime.py         # AgentRuntimeEventDAO, AgentRuntimeHandler, TraceEventKind
│   │   │   ├── rate_limit/
│   │   │   │   ├── dao.py             # ModelRateLimitPolicyDAO, RateLimitRetryPlanDAO
│   │   │   │   └── service.py         # policy_for_model, retry_plan_from_error, IterationRetryPolicy, int_or_none
│   │   │   ├── workspace/
│   │   │   │   ├── dao.py             # WorkspaceFolderDAO, WorkspaceFileParseError
│   │   │   │   └── service.py         # VscodeWorkspaceLoader
│   │   │   ├── preferences/
│   │   │   │   ├── dao.py             # UserPreferencesDAO, UserPreferencesStoreCorruptError
│   │   │   │   └── service.py         # UserPreferencesStore
│   │   │   ├── project_context/
│   │   │   │   ├── dao.py             # ContextFileEntryDAO
│   │   │   │   └── service.py         # ProjectContextDiscovery — walk up for SLO/AGENTS/CLAUDE.md
│   │   │   ├── skills/
│   │   │   │   ├── dao.py             # SkillEntryDAO
│   │   │   │   └── service.py         # SkillsLoader
│   │   │   ├── prompts/
│   │   │   │   ├── __init__.py        # SystemPromptBuilder — assembles runtime system prompt
│   │   │   │   └── system_prompt.py   # All static string constants (ROLE_LINE, KB_BLOCK, …)
│   │   │   ├── dao.py                 # SloAgentConfigDAO and related
│   │   │   ├── history/
│   │   │   │   ├── dao.py             # HistoryEventKind, SessionHistoryEventDAO, metadata incl. session_name/session_name_key
│   │   │   │   ├── filesystem_store.py # FilesystemSessionHistoryStore — JSONL writer + resume-by-name resolution
│   │   │   │   ├── projector.py       # SessionHistoryProjector → list[BaseMessage]
│   │   │   │   └── transcript.py      # TranscriptEntryDAO, ReplayEntryProjector
│   │   │   ├── tool_execution/
│   │   │   │   ├── service.py         # plan_tool_batch — parallel vs sequential planning
│   │   │   │   ├── dao.py             # ToolExecutionPlanDAO
│   │   │   │   └── executors.py       # SequentialToolExecutor, ConcurrentToolExecutor
│   │   │   ├── compaction/            # Compacter, CompactionChecker, CompactionResult
│   │   │   ├── turn_stream_accumulator.py
│   │   │   ├── assistant_chunk_normalizer.py
│   │   │   ├── graph_stream_parser.py
│   │   │   └── message_text.py
│   │   ├── model_catalog/             # canonical model catalog — identity, defaults, reasoning, aliases, discovery
│   │   │   ├── dao.py                 # ModelCatalogEntryDAO, ModelRuntimeProfileDAO, ModelReasoningProfileDAO, …
│   │   │   ├── seed.py                # committed first-class entries, family templates, aliases
│   │   │   ├── discovery.py           # ProviderModelDiscoveryService, ModelCatalogOverrideService
│   │   │   ├── service.py             # ModelCatalogService.load() — merged snapshot + projections
│   │   │   ├── store.py               # cache and override file persistence
│   │   │   └── prompt_clause.py       # append_kimi_for_coding_clause exact-match helper
│   │   ├── skills/
│   │   │   └── registry.py            # SkillRegistry — parses skills/<name>/SKILL.md
│   │   ├── tools/
│   │   │   ├── bundles.py             # create_extended_tools() and the three pi-parity bundles
│   │   │   ├── read.py / write.py / edit.py / bash.py
│   │   │   ├── grep.py / find.py / ls.py
│   │   │   ├── read_pdf.py / now.py
│   │   │   ├── a2a_peer.py            # outbound A2A peer delegation (not in default bundle)
│   │   │   ├── echo.py                # demo/test tool
│   │   │   ├── prompt_snippets.py     # TOOL_PROMPT_SNIPPETS dict → system prompt tool lines
│   │   │   └── _blocking.py / _truncate.py / _gitignore.py / _image_content.py
│   │   └── reasoning_capabilities.py  # compatibility projection over ModelCatalogService reasoning profiles
│   ├── auth/
│   │   ├── credential_resolver.py     # CredentialResolver — env → store → legacy Claude
│   │   ├── credential_store.py        # CredentialStore — ~/.slo/global/authentication.json
│   │   ├── credential_dao.py          # CredentialDAO, ProviderName, AuthType
│   │   ├── oauth_flow.py / oauth_provider.py / pkce.py
│   │   └── providers/
│   │       ├── anthropic_provider.py
│   │       └── openai_codex_provider.py
│   ├── cli/
│   │   ├── app.py                     # Typer app — bare `slo` opens TUI; `--resume` accepts session id or name
│   │   ├── typer_dispatch.py          # TyperDispatch — routes CLI subcommands + resolves session references
│   │   ├── update.py                  # `slo update` self-updater
│   │   └── __main__.py
│   ├── tui/
│   │   ├── app.py                     # SloTUI (Textual App) + PromptInput + /new,/rename + prompt-history recall
│   │   ├── prompt_history.py          # PromptHistoryNavigator — in-process Up/Down prompt recall
│   │   ├── transcript_projector.py    # TranscriptProjector — events → widgets
│   │   ├── event_renderer.py          # tool-call line formatting helpers
│   │   ├── slash_router.py            # SlashRouter — dispatches /commands
│   │   ├── slash_command_registry.py  # SlashCommandRegistry + SlashCommandSpecDAO
│   │   ├── slash_suggestion_engine.py # SlashSuggestionEngine — prefix-match autocomplete
│   │   ├── thinking_spinner.py        # ThinkingSpinner widget
│   │   ├── headless_workflow_visualizer.py # `slo visualize` TUI — resizable panes, summary bar, markdown transcript
│   │   ├── workflow_visualizer_loader.py   # WorkflowVisualizerLoader — reads parent/child session captures
│   │   ├── visualizer_launcher.py     # VisualizerLauncher — opens `slo visualize` in a new OS terminal window
│   │   ├── model_catalog.py           # supported_models_by_provider()
│   │   ├── authentication/            # AuthenticationScreen + widgets (api_key, oauth, …)
│   │   └── widgets/
│   │       ├── user_message_block.py     # UserMessageBlock — one user turn with panel surface styling
│   │       ├── assistant_stream_block.py # AssistantStreamBlock — one assistant turn; reasoning/answer split surfaces
│   │       ├── tool_execution_block.py   # ToolExecutionBlock — one tool call+result with panel surface styling
│   │       ├── usage_status_bar.py       # UsageStatusBar — token/rate display
│   │       └── slash_suggestion_menu.py  # SlashSuggestionMenu — autocomplete dropdown
│   ├── main.py / web_app.py           # FastAPI app, /healthz, lifespan
│   ├── routers/ / middleware/ / models/ / domains/ / services/
│   └── exceptions.py
├── tests/
│   ├── agents/
│   │   └── slo_agent/                 # unit tests: agent loop, session, rate limits, usage
│   ├── tui/                           # TUI tests: app, replay, slash, status bar, tool blocks
│   └── integration/                   # cross-component (future)
├── skills/                            # 100+ vendored SKILL.md files + INDEX.md
│   ├── INDEX.md                       # regenerated by `make build-skill-index`
│   ├── orientation/
│   ├── design-and-analysis/
│   ├── coding/
│   ├── git-ops/
│   ├── cli/
│   ├── tui/
│   ├── integration-tests/
│   └── frontend-vue/
├── specifications -> ../specifications  # canonical spec root is /Users/siddharth/Code/Pi/slo/specifications/
├── pyproject.toml
├── AGENTS.md  ← this file
├── docs/
│   ├── INSTALL.md
│   ├── RESEARCH.md
│   ├── SLO_HEADLESS_README.md
│   └── SLO_SCHEDULER_README.md
└── CLAUDE.md  (loads AGENTS.md on every session)
```

### Feature-request and specification artifacts

- **Incoming feature requests:** `/Users/siddharth/Code/Pi/slo/feature-requests/`
- **Canonical specification root:** `/Users/siddharth/Code/Pi/slo/specifications/`
- **Repo-local spec path:** `specifications/` is a symlink to that canonical root.
- **Rule:** when asked to write a new feature spec, create one numbered folder per feature under the canonical specification root rather than scattering spec files inside `src/` or ad hoc repo folders.
- **Spec file naming convention:**
  - The primary spec document inside the folder is always `overview.md`.
  - Sub-specs follow `<spec-number>.<letter>.<index>-<title>.md` (e.g., `28.a.1-moonshot-credential-lane.md`).
  - Never name a spec file `request.md` — this was an earlier, incorrect convention that has been superseded.
- **Output format:** Specifications are written as Markdown (`.md`) files.

---

## 4. Runtime Chain

```
slo (console script → src/cli/__main__.py)
  └── TyperDispatch (src/cli/typer_dispatch.py)
        └── SloTUI.run() (src/tui/app.py)               # Textual app, interactive path
              └── SloAgentSession (src/agents/slo_agent/sessions/service.py)
                    └── SloAgent (src/agents/slo_agent/agent.py)
                          └── build_slo_agent() (src/agents/slo_agent/graph/service.py)
                                └── LangGraph StateGraph
                                      ├── [agent node]  — llm.ainvoke(messages)
                                      └── [tools node]  — sequential tool execution
```

**Layer responsibilities:**

- `TyperDispatch` — parses CLI flags, resolves model/provider plus `--resume` session
  references and optional `--workspace <file.code-workspace>`, launches the TUI or the FastAPI server.
- `SloTUI` — Textual app. Owns the layout (header, scroll container, `UsageStatusBar`,
  `PromptInput`, footer), mounts transcript widgets, dispatches slash commands, owns
  `/new` session replacement + `/rename`, manages in-process prompt-history recall, and
  subscribes to the session's event stream.
- `SloAgentSession` — process-level wrapper. Holds one `SloAgent`, enforces one in-flight
  prompt at a time, owns the subscriber list for render events, persists the JSONL history
  trace via `FilesystemSessionHistoryStore`, exposes runtime naming (`rename_session`,
  `session_name`), and exposes slash methods (`abort`, `steer`, …).
- `SloAgent` — multi-turn ReAct loop. Calls `graph.astream()` in a loop until the model
  emits no tool calls, `abort()` fires, or the `should_stop_after_turn_hook` returns True.
  Emits normalized `AgentStreamEventDAO` events on every chunk.
- **LangGraph one-shot turn** — each `ainvoke`/`astream` is exactly one agent turn: one LLM
  call followed by sequential execution of whatever tool calls it returned.

---

## 5. System Prompt Assembly

`SloAgent.__init__` calls `ProjectContextDiscovery.invoke(cwd=self._cwd, workspace_folders=...)`
to collect `SLO.md` / `AGENTS.md` / `CLAUDE.md` files. The cwd lineage is always walked from
`cwd` to the filesystem root, and when `--workspace <file.code-workspace>` is active Slo first
loads the workspace file via `VscodeWorkspaceLoader.invoke(workspace_file=...)` and then walks
from each declared workspace folder to the filesystem root as an additive tier. The deepest
copy of each filename wins within the cwd walk; workspace-folder walks contribute additional
unique absolute paths after the cwd-derived entries. The collected `ContextFileEntryDAO` objects
are forwarded to `SystemPromptBuilder.invoke()`.

`SystemPromptBuilder.invoke()` (`src/agents/slo_agent/prompts/__init__.py`) assembles the
prompt in this section order:

1. Role line (`ROLE_LINE`)
2. Available tools block — one `- <name>: <snippet>` line per tool that has a
   `TOOL_PROMPT_SNIPPETS` entry (`src/agents/tools/prompt_snippets.py`)
3. Custom tools note
4. Guidelines block (adapts based on whether bash + native explorers are both present)
5. Skills block — path to `skills/INDEX.md` interpolated from `SKILLS_DIR`
6. Knowledge base block (`KB_BLOCK`)
7. Optional append block (`append_system_prompt`)
8. Project context block — each discovered file wrapped in `<project_instructions path=…>`
9. Current date line
10. Current working directory line
11. Optional `Current workspace folders:` block listing each resolved workspace folder when a workspace file is active

**Known issue (B1 — tools block):** `SloAgent.__init__` does not currently pass `tools=`
to `SystemPromptBuilder.invoke()`. `build_slo_agent()` resolves the 9-tool extended bundle
internally, but `_resolve_system_prompt` receives `tools=None` (the raw constructor
argument, which defaults to `None`). The builder therefore renders the tools block as
`(none)`. The agent still executes tools correctly — the graph has them bound — but the
system prompt does not list them. Fix: pass the resolved tool list from the graph into the
prompt builder.

---

## 6. Tool Bundle

The default bundle is `create_extended_tools()` from `src/agents/tools/bundles.py`:

| Tool | File | What it does |
|---|---|---|
| `read` | `tools/read.py` | Read a UTF-8 text file or image attachment; rejects PDFs/binary files |
| `write` | `tools/write.py` | Write/overwrite a file |
| `edit` | `tools/edit.py` | Exact-string find-and-replace in a file |
| `bash` | `tools/bash.py` | Run a bash command (semaphore-guarded async) |
| `grep` | `tools/grep.py` | Regex search across files |
| `find` | `tools/find.py` | Find files by name/pattern |
| `ls` | `tools/ls.py` | List directory contents |
| `read_pdf` | `tools/read_pdf.py` | Extract text from a PDF |
| `now` | `tools/now.py` | Return the current datetime |

Three pi-parity sub-bundles also exist: `create_coding_tools()` (read/bash/edit/write),
`create_read_only_tools()` (read/grep/find/ls), `create_all_tools()` (all seven pi tools).

`a2a_peer_tool` (`tools/a2a_peer.py`) is **not** in the default bundle. It is available for
sessions that need outbound A2A peer delegation but must be added explicitly.

Blocking leaf work (file I/O, PDF extraction) is offloaded via `asyncio.to_thread` behind a
per-event-loop semaphore in `tools/_blocking.py` so read-heavy batches do not stall Textual.

---

## 7. Skills System

Skills are vendored convention prompts that the agent reads on demand.

- **Location:** `skills/<group>/<slug>/SKILL.md` — 100+ skills across 10 groups:
  `orientation/`, `design-and-analysis/`, `coding/`, `git-ops/`, `cli/`, `tui/`,
  `integration-tests/`, `frontend-vue/`, `presentation/`, and `user-content/`.
- **Runtime access:** The system prompt points the agent at `skills/INDEX.md`
  (absolute path via `SKILLS_DIR`). The agent reads the index with the `read` tool,
  identifies the matching skill, then reads the full `SKILL.md`.
- **Index format:** Each entry has `name`, `description`, `when_to_use`, and a relative
  `Path:` field. YAML frontmatter in each `SKILL.md` carries the same fields plus `group`
  and `kind`.
- **Regeneration:** `make build-skill-index` or `make refresh-skills` rewrites
  `skills/INDEX.md` from the committed `SKILL.md` tree.
- **Known gap vs pi:** pi injects the `<available_skills>` manifest inline into the system
  prompt at startup. Slo uses a static path pointer only. There is no runtime injection of
  skill names into the prompt in v1.

`SkillRegistry` (`src/agents/skills/registry.py`) parses individual `SKILL.md` files but
is not yet wired into the session boot path.

### Workflows vs Skills — Critical Routing Rule

The skills directory contains **two distinct kinds of artifacts**:

| Kind | Location pattern | Purpose |
|---|---|---|
| **Individual skill** | `skills/<group>/<slug>/SKILL.md` | Single-concern convention for one task type |
| **Formal workflow** | `skills/design-and-analysis/workflows/<name>.md` | Multi-step pipeline sequencing several skills |

**When the user mentions "workflow" or names one explicitly, load from `skills/design-and-analysis/workflows/` — not from a skill with a similar name.**

Named workflows:

| Workflow | File to read |
|---|---|
| Code-Test-Review | `skills/design-and-analysis/workflows/code-test-review.md` |
| Specification Development | `skills/design-and-analysis/workflows/specification-development.md` |

**Anti-pattern:** user says "use the code-test-review workflow" → agent loads `skills/coding/code-test-loop/SKILL.md`. This is wrong. `code-test-loop` is the coding cadence that forms Step 1 *inside* the Code-Test-Review workflow. Loading it instead of the workflow silently skips Step 2 (Code Review) and Step 3 (Completion Check). Always load the workflow `.md` from the `workflows/` folder when a workflow is requested.

**Dynamic workflows shorthand:** when the user says **"dynamic workflows"** or the common misspelling **"dyanmic workflows"**, treat that as an explicit request to execute the named workflow **in the current session** (sync dynamic workflow): the orchestrator decomposes phases and dispatches them with `spawn_sub_agents`, blocking until the synthesis is returned in the same turn. To **detach** the workflow as a headless orchestrator process (headless dynamic workflow), the user must add an explicit detach qualifier — the word **"headless"**, **"detached"**, or **"independent"** applied to the request (e.g., **"headless dynamic workflows"**, **"detached dynamic workflows"**, **"independent dynamic workflows"**) — or detach wording such as **"in the background"** / **"without blocking"**. A detach-qualified request routes to exactly one `launch_workflow` call; a detached orchestrator never calls `launch_workflow`.

**TUI scheduler supervision:** when the user wants a dynamic workflow launched from a
TUI session and also wants recurring monitoring, background follow-up, or progress
checks posted back into that same session, load
`skills/tui/tui-scheduled-workflows/SKILL.md`. That skill governs how to create
continuous schedules, use session-inbox delivery, recover stalled orchestrators,
and clean up the monitor schedule when the workflow completes or is aborted.

**Generic TUI scheduled operations:** when the user wants a non-workflow-specific
scheduled behavior from the TUI, such as repeated reminders, periodic checks, or
"print the time every 5 seconds until I ask you to stop", load
`skills/tui/tui-scheduled-operations/SKILL.md`. That skill governs interval,
cron, and one-shot schedules, including how to target the live TUI session and how
to stop and clean them up on request.

---

## 8. Knowledge Base

- **Path:** controlled by the `SLO_KB_DIR` environment variable.
- **Workspace files:** when `slo --workspace <file.code-workspace>` is used, the workspace file itself is not treated as a project-instruction file; instead its declared folders seed additional `ProjectContextDiscovery` walks.
- **In-prompt:** `KB_BLOCK` in `system_prompt.py` instructs the agent to consult the KB
  when it exists. The block includes the path resolved from `SLO_KB_DIR` at build time.
- **Conditional availability:** if `SLO_KB_DIR` is unset or the path does not exist, the
  KB block still appears in the prompt but the agent will find nothing at the path. Set
  `SLO_KB_DIR=/Users/sidravic/Code/KnowledgeBase/KB` in `environments/development.env`.

---

## 9. TUI

**`SloTUI`** (`src/tui/app.py`) is the Textual `App` for the interactive path.

**Per-component transcript model:** every conversational entry is a dedicated Textual widget:
- `UserMessageBlock` — one user turn, rendered with `Rich.Markdown`.
- `AssistantStreamBlock` — one assistant turn; reasoning and answer text stream into it in
  real time. One block per outer-loop iteration.
- `ToolExecutionBlock` — one tool call + result pair; updates as the tool executes.

Non-conversational notices (system messages, slash-command echoes) remain flat `Static`
lines. **Both the live path and the replay path use the same widgets** — resumed sessions
render identically to live.

**Session replay:** `ReplayEntryProjector.build_entries()` reads the on-disk JSONL and
emits `TranscriptEntryDAO` objects. `TranscriptProjector.project_replay_entry()` mounts the
same widget types. `TranscriptProjector` (`src/tui/transcript_projector.py`) owns the live
streaming path too.

**Slash commands** are dispatched by `SlashRouter` (`src/tui/slash_router.py`).
`SlashCommandRegistry` (`src/tui/slash_command_registry.py`) holds the metadata
(`SlashCommandSpecDAO`). `SlashSuggestionEngine` (`src/tui/slash_suggestion_engine.py`)
does prefix-match autocomplete; `SlashSuggestionMenu` renders the dropdown.

Available slash commands include: `/help`, `/new [session name]`, `/rename <session name>`,
`/model <name>`, `/reasoning <level>`, `/abort`, `/steer <text>`, `/clear`, `/auth`,
`/quit` (and aliases).

**`UsageStatusBar`** (`src/tui/widgets/usage_status_bar.py`) is a `Static` widget fixed
above the footer. It is updated via `session.usage_snapshot` whenever `SloAgentSession`
emits a `SessionUsageSnapshotDAO`.

**Prompt-history recall** is owned by `PromptHistoryNavigator` (`src/tui/prompt_history.py`).
`PromptInput` only emits semantic older/newer history messages; the app records submitted
non-slash prompts, gives slash suggestions precedence, and restores the preserved draft when
history navigation exits.

**`ThinkingSpinner`** (`src/tui/thinking_spinner.py`) is mounted above `PromptInput` while
the agent is running.

**Workflow visualizer auto-launch:** when a TUI session is promoted to orchestrator mode and
the first sub-agent is spawned, `SloTUI._maybe_launch_visualizer` opens a separate terminal
window running `slo visualize --session <parent_session_id> --follow` via `VisualizerLauncher`
(`src/tui/visualizer_launcher.py`). It fires once per run (guarded by
`_visualizer_launched_for_run`, reset in `_cleanup_sub_agent_state`). The launch is
best-effort: macOS drives Terminal.app/iTerm through `osascript`, Linux probes common
terminal emulators, and any other platform (or a failed spawn) falls back to writing the
manual `slo visualize` command into the transcript. Only a non-secret `SLO_*` allowlist is
forwarded into the new window. Disable with `SLO_AUTO_VISUALIZE=0`; pick the emulator with
`SLO_VISUALIZER_TERMINAL_APP`. The visualizer TUI itself
(`headless_workflow_visualizer.py`) has a workflow-summary bar, status-coloured sub-agent
list, markdown transcript rendering matching the main TUI, and keyboard-resizable panes
(`ctrl+←/→` for the sub-agent list width, `ctrl+↑/↓` for the diagnostics height).

---

## 10. Auth

**`CredentialResolver`** (`src/auth/credential_resolver.py`) is stateless. Precedence:
1. Environment variable for the provider (`SLO_ANTHROPIC_API_KEY`, `SLO_OPENAI_API_KEY`, or `SLO_KIMI_FOR_CODING_API_KEY`).
2. `~/.slo/global/authentication.json` via `CredentialStore`.
3. `~/.claude/.credentials.json` (Anthropic only — legacy Claude Code credentials).

`LLMFactory.create` calls `CredentialResolver.require(provider=...)` once per build.
The first-run / sign-in UI lives in `src/tui/authentication/`. `SloTUI.on_mount` pushes
`AuthenticationScreen` when `CredentialResolver.resolve` returns `None` for the active
model's provider. Users re-open the modal with `/auth`.

### Kimi For Coding

Provider enum value: `ProviderName.KIMI_FOR_CODING`. Credential env var: `SLO_KIMI_FOR_CODING_API_KEY`.
Supported model names are defined by the canonical model catalog in
`src/agents/model_catalog/seed.py`; current first-class examples include
`kimi-for-coding`, `kimi-k3`, and `kimi-for-coding-highspeed`. Older `moonshot-*`
aliases continue to resolve for backward compatibility but are not advertised as
preferred names.

`LLMFactory._build_kimi_for_coding_chat_openai` constructs a `ChatOpenAI` with:
- `base_url="https://api.kimi.com/coding/v1"` (OpenAI-compatible endpoint)
- `max_retries=0` — `ModelPool` handles fallback; errors must surface immediately
- `supports_explicit_caching=False` — Kimi For Coding does not support prompt caching

### ModelPool (LLM Router)

`ModelPool` (`src/agents/providers/model_pool.py`) is a drop-in `BaseChatModel` subclass
that routes calls across a priority-ordered list of models with cooldown-based fallback.

**Key types:**
- `ModelPoolEntryDAO` — `model_name`, `provider`, `priority`, `cooldown_seconds` (default 300s),
  `rate_limit_cooldown_seconds` (default 60s; used for rate-limit + transient-server failures)
- `ModelPoolDAO` — `entries: List[ModelPoolEntryDAO]` with `min_length=2`
- `ModelPool` — async/streaming **switchable** `BaseChatModel`: overrides `_generate` /
  `_agenerate` / `_astream`, `bind_tools`, and exposes the introspection surface
  `llm` (→ self), `active_llm`, `active_provider`, `supports_explicit_caching`,
  `active_model_name`, plus a route-switch audit log (`drain_route_switch_log()`).
- `RouteSwitchRecordDAO` — one audit record (`from_model_name`, `to_model_name`, `kind`, `error_text`).

**Fallback behaviour (spec 37):**
1. `_select_model()` picks the lowest-priority entry that is not cooled.
2. On a **switchable** error (`should_switch(kind)` → `CREDIT_EXHAUSTED` / `RATE_LIMITED` /
   `TRANSIENT_PROVIDER_FAILURE`), the failing entry is cooled (long `cooldown_seconds` for
   credit; short `rate_limit_cooldown_seconds` for rate-limit/transient), the switch is
   recorded, and the next available entry replays the **same** request. `_astream` switches
   only **before the first streamed chunk** (a mid-stream failure propagates).
3. On `OTHER` (e.g. a 400 bad request), the error re-raises immediately — no fallback.
4. If all entries are cooled, `AllModelsExhaustedError` is raised to the caller (and surfaces
   on screen via the iteration-retry composition below).

**Creation:** `LLMFactory.create_pool(pool_dao=..., <all build knobs>)` builds a pool from a
`ModelPoolDAO`, forwarding `temperature`/`streaming`/`max_retries`/`max_tokens`/`model_kwargs`/
`session_id`/`reasoning_level` to every member and injecting
`adapt_chatgpt_backend_request` as the per-member request adapter. `build_slo_agent(model_pool_dao=...)`
takes the pool branch; both single-model `LLMBuildResult` and `ModelPool` satisfy the
`LLMBuildProduct` protocol (`.llm` / `.supports_explicit_caching`). Local imports avoid cycles.

**Session integration:** `SloAgentSession._resolve_active_model_name()` uses
`hasattr(llm, "active_model_name")` to detect a pool — no `isinstance` check, no import
of `ModelPool` in session.py. Pool config is parsed by
`config/model_pool_config.py::parse_model_pool_config` from `SLO_MODEL_POOL` or the
`UserPreferencesDAO.default_model_pool` preference, and threaded via
`SessionConfigDAO.model_pool_dao`. Usage/title/rate-policy and persisted run events read the
**routed** member; `_refresh_oauth_credential_if_needed` warms **every** pool provider.

**Credit exhaustion policy** (`src/agents/providers/credit_exhaustion_policy.py`):
- `CreditExhaustionPolicy.classify(error, provider)` → `ProviderErrorKind`
- `should_switch(kind)` is the single switch-vs-propagate predicate (`OTHER` ⇒ propagate).
- Anthropic: 402 or "credit balance"/"billing" → `CREDIT_EXHAUSTED`; 429 → `RATE_LIMITED`; 529 → `TRANSIENT_PROVIDER_FAILURE`
- Kimi For Coding: 402 → `CREDIT_EXHAUSTED`; 429 → `RATE_LIMITED`; 500/502/503/529 → `TRANSIENT_PROVIDER_FAILURE`
- Anthropic: 402 or "credit balance"/"billing" → `CREDIT_EXHAUSTED`; 429 → `RATE_LIMITED`; 529 → `TRANSIENT_PROVIDER_FAILURE`
- OpenAI: `code in {"insufficient_quota", "billing_hard_limit_reached"}` → `CREDIT_EXHAUSTED`; 429 → `RATE_LIMITED`; 500/502/503 → `TRANSIENT_PROVIDER_FAILURE`

---

## 11. History / Persistence

**Default store:** `TreeBasedFileSystemSessionHistoryStore` (`history/tree_store.py`).
Laid out under `~/.slo/sessions/history/<session_id>/`:
```
session.json    # SessionHistoryMetadataDAO — atomic temp+rename on update; includes session_name/session_name_key
tree.json       # SessionTreeDAO — turn-grouped event tree (new default)
transcript.md   # derived; not authoritative
```

The legacy flat store (`FilesystemSessionHistoryStore`) uses `events.jsonl` instead of
`tree.json`. Both stores satisfy `SessionHistoryStoreProtocol` (`history/store_protocol.py`).
Pass a `FilesystemSessionHistoryStore` explicitly to `SloAgentSession` to opt back into
the flat layout.

**Tree layout (`tree.json`):**
- `preamble_events` — envelope events with no `turn_id` (e.g. `session_started`).
- `turns` — ordered `TurnNodeDAO` list; each node holds all events for one turn.
  Tool-call events and their corresponding tool-result events are always in the
  same `TurnNodeDAO` (shared `turn_id`), making whole-turn compaction safe.
- `token_usage` per `TurnNodeDAO` — running sum of event-level estimates (stamped
  at append time by `TokenUsageEstimator`).

**Token usage estimation (`history/token_estimator.py`):**
`TokenUsageEstimator.estimate(event)` applies `ceil(chars / 4)` where "chars"
measures the substantive text of the event (content, thinking, serialised tool args,
tool output, delta). Lifecycle events (`run_started`, `run_completed`, etc.) return 0.

**`HistoryEventKind`** values: `session_started`, `run_started`, `user_message`,
`steering_message`, `assistant_message`, `assistant_delta`, `tool_call`, `tool_result`,
`run_retrying`, `route_switched`, `run_completed`, `run_aborted`, `run_failed`,
`slash_command` (plus orchestrator/sub-agent lifecycle kinds). `run_retrying` (a
wait-and-retry decision) and `route_switched` (a ModelPool route switch) are
diagnostic/audit events added in spec 37 — both are excluded from
`SessionHistoryProjector.build_message_history` so audit volume never inflates model context.

Each accepted prompt in `SloAgentSession`:
1. ensures the session directory exists,
2. loads prior history via `SessionHistoryProjector` → `list[BaseMessage]`,
3. persists `run_started` and `user_message` before the agent runs,
4. forwards full-fidelity trace events to `FilesystemSessionHistoryStore`,
5. appends the terminal event (`run_completed` / `run_aborted` / `run_failed`).

**`SessionHistoryProjector`** (`history/projector.py`) converts events to LangChain
`BaseMessage` objects for next-turn context. Incomplete turns (no terminal event) are
excluded from model context but remain visible in replay.

**Session naming / resume-by-name:** the session directory remains rooted by `session_id`.
Human-readable naming is additive metadata in `session.json` via `session_name` and
`session_name_key`. `FilesystemSessionHistoryStore.resolve_session_reference()` resolves
`--resume` input in this order: exact `session_id`, then normalized `session_name_key`.

---

## 12. Rate Limiting

`ModelRateLimitPolicyDAO` (`src/agents/slo_agent/rate_limit/dao.py`) holds per-model
`requests_per_minute`, `tokens_per_minute`, `automatic_retry_attempts`, and
`local_retry_wait_cap_seconds` sourced from the canonical model catalog via
`MODEL_DEFAULTS` in `config/ai_model_config.py`.

`retry_plan_from_error()` (`src/agents/slo_agent/rate_limit/service.py`) parses a caught
rate-limit error and returns a `RateLimitRetryPlanDAO` with a `wait_seconds` value and a
`retryable` flag.

**Three-layer rate-limit defense (spec 37):**
1. **Preflight (session)** — `estimate_request_tokens` is **history-aware** (counts replayed
   `message_history`, including tool outputs), so a resumed session waits before it would 429.
2. **In-call route switch (ModelPool)** — a switchable error on the active member switches to
   the next member inside one provider call (see Section 10).
3. **Iteration-scoped retry (agent)** — `SloAgent.invoke(iteration_retry_policy=...)`
   retries a failed ReAct iteration **only when it emitted no visible output**, replaying the
   unchanged `accumulated_messages` (no duplicate transcript). `AllModelsExhaustedError` is
   retryable within the attempt budget; when spent, a terminal `run_failed` naming the cooled
   members reaches the screen. With no injected policy, legacy no-retry behavior is preserved.
   The session injects the policy via `_build_iteration_retry_policy` and relays/persists the
   agent's `run_retrying` events. **Overflow backstop (spec 46.a.2):** when a provider explicitly
   rejects a request for context overflow on the initial attempt, `_derive_next_attempt_plan`
   (not `_finalize_failed_attempt`) performs a forced compaction pass, emits four compaction
   lifecycle `AgentStreamEventDAO` kinds (`compaction_started`, `compaction_completed`,
   `compaction_failed`, `compaction_retrying`), persists a `run_retrying` audit event anchored
   to the failed turn, and returns a one-shot `overflow_retry` attempt plan. The retry plan
   sets `persist_user_message=False` (no duplicate history record), `excluded_turn_ids` to
   filter the failed turn from immediate replay context, and `preflight_compaction_mode="skip"`.
   If compaction itself fails, `_derive_next_attempt_plan` returns `None` and the original
   overflow error surfaces unchanged. A second overflow on the retry attempt is terminal (the
   `attempt_kind == "overflow_retry"` budget guard prevents looping).

`SessionUsageSnapshotDAO` accumulates `TokenUsageTotalsDAO` across turns and feeds
`UsageStatusBar` so the user can see token spend and rate state without leaving the TUI.

---

## 13. Style Rules

- **Google-style docstrings** on every public function and method.
- **Named arguments** at every call site with 2+ args: `foo(bar=baz, qux=quux)`.
- **Explicit type hints** on every parameter and return value.
  `Optional[T]` with `= None` for nullable params; specific containers (`list[str]`).
- **Black** formatting, line length 110: `black src/ tests/`.
- **No bare `Any`** — prefer `BaseChatModel`, `BaseTool`, `BaseMessage`, etc.
- **Declarative method structure** — one decision per method; orchestrators read like a
  table of contents; no nested conditionals past 2 levels.
- **Class convention** — core logic lives in a class with `@classmethod` methods; public
  entry is `invoke` (or `build` / `load` / `create`). Free functions are reserved for
  `@tool` bridges, LangGraph nodes, FastAPI handlers, and test helpers.

---

## 14. Testing

- **Never real keys** in the default gate. All tests use `FauxChatModel`
  (`src/agents/providers/faux.py`) — a queue-based deterministic mock that returns
  scripted `AIMessage` objects.
- **Default gate:** `pytest -m "not e2e"` (set in `pyproject.toml` `addopts`).
  Use `pytest -m e2e` only when real provider credentials are intentionally in scope.
- **Test env:** `make test` self-sources `environments/tests.env`; never the dev DB.
- **Never real terminal windows.** `VisualizerLauncher.launch()` opens a real
  Terminal/iTerm window running `slo visualize --follow` that outlives the suite. Any
  test path that reaches it (a `sub_agent_spawned` event or a `launch_workflow` tool
  result through `SloTUI._render_event`) must patch `VisualizerLauncher.launch` or
  inject `spawn=`. Two suite-wide guards back this up: `environments/tests.env` sets
  `SLO_AUTO_VISUALIZE=0` (covers `make test`) and the autouse
  `_never_spawn_real_terminals` fixture in `tests/conftest.py` stubs
  `VisualizerLauncher._default_spawn` (covers bare `pytest` runs). Regression tests:
  `tests/tui/test_visualizer_launcher.py::TestSuiteNeverSpawnsRealTerminals`. During
  **manual smoke** runs, explicitly close every visualizer terminal you open (quit the
  `slo visualize` process and its window) — detached windows accumulate on the
  operator's machine otherwise.
- **Layout:**
  - `tests/agents/slo_agent/` — unit tests for agent loop, session, rate limits, usage.
  - `tests/tui/` — TUI tests (app, replay, slash commands, status bar, tool blocks).
  - `tests/integration/` — cross-component (sparse; planned for sub-spec 01.k).
- `asyncio_mode = "auto"` is set in `pyproject.toml` so all async tests run without
  explicit `@pytest.mark.asyncio`.

---

## 15. Commit / Branch Conventions

- **One feature per branch** from `main`. Branch name: `feature-<detail_in_snake_case>`
  or a JIRA ID in lowercase.
- **Commit title:** `<JIRA-ID or topic> <one-line description>` ≤72 chars.
- **Commit body:** list core changes and files modified.
- **`Co-Authored-By:`** footer when pairing with an AI assistant.
- For the operational sub-steps (sync main, branch, commit+push, PR, review fix), use the
  matching skills in `skills/git-ops/`.

---

## 16. AGENTS.md Maintenance Rule

**Update this file whenever you:**
- Add a new component, module, or package.
- Rename or move a module.
- Change the runtime chain (CLI → TUI → Session → Agent → Graph).
- Alter the system prompt assembly order or add/remove a section.
- Change the default tool bundle or add a new tool.
- Resolve known bug B1 (tools block rendering as "(none)").
- Add a new slash command, change prompt-history semantics, or change auth flow.
- Change the history event schema or persistence layout.
- Add a new provider or change credential resolution precedence.
- Add the `--workspace` flag to the CLI surface or change workspace-context discovery semantics.
- Change the canonical feature-request root (`/Users/siddharth/Code/Pi/slo/feature-requests/`) or specification root (`/Users/siddharth/Code/Pi/slo/specifications/`).

Keep **Section 5** (System Prompt Assembly) and **Section 6** (Tool Bundle) accurate — they
directly affect what every agent session sees and does.
