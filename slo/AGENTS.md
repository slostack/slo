# Slo — Agent Reference

## Feature 89 worktree — implementation wired, approval pending

`providers/openai_platform.py` owns `OpenAIRequestPolicy` and the lifetime-pinned
`OpenAIPlatformChatOpenAI`. `LLMFactory` selects the adapter only for captured API-key credentials on
seed-owned `requires_responses_api` records. All three GPT-6 entries also support
the existing Codex OAuth builder, without Platform constructor/final sanitation; session validation precedes adoption and lazy OAuth refresh. Picker
auth types are captured only at lifecycle boundaries, and reasoning/startup use
the session snapshot. Both seed-owned policy flags remain in memory and are
excluded only by the existing schema-2 provider-cache writer. Jev null output
metadata uses the existing conservative cap and authenticated admission.

Real locked-SDK offline tools, mounted resume, mixed lanes and frozen readers
have executable coverage. This is not live entitlement or release evidence.
See `docs/implementation/89-gpt-6-support/recovery13-closure.md` for actual gates
and the AC map. Static baseline gates remain unwaived; independent review and
assessment remain pending. Earlier continuation receipts are historical.

## Latest Step-1 bounded window correction — 2026-10-03

The prior final gate is retained unchanged: `.f86-final-remediation-hldebc_g/full-final.log`
reports **1 failed, 5155 passed, 18 deselected, 196 warnings**, exit 1. The exact
bounded-model-window failure reproduced in isolation. Direct-provider summaries
incorrectly acquired the gateway `; provider default` suffix, expanding the normal
rows from two to three lines (five rather than eight rows). The existing suggestion
projection now preserves direct-provider summaries; OpenRouter evidence is unchanged.
A stronger eight-label/footer compositor assertion then exposed detail width exceeding
the inner menu width by four cells. The menu now uses the same inner width for both.
No count/window expectation was relaxed, no sleeps/skips added, and no R1/R3 changes.

Focused partition: 38 passed; intermediate strengthened-paint run: 1 failed/173 passed;
paint correction: 30 passed; final affected: **174 passed, 5 warnings**; additional
surrounding picker/status regressions: **48 passed, 2 warnings**. Full expanded
commands/logs/exits: `.f86-window-correction-tPhyAzET/`. The fresh complete gate
is `full.log`, `full-command.txt`, `full.exit` there, generated AFTER these final
documentation edits. Its actual exit/summary controls readiness; no anticipated pass.
Final source/test/current-doc manifest: `source-test-manifest.sha256`, digest in
`manifest.sha256`, generated after full gate and read-only checks; no edits thereafter.

R1 router truth, R2 two-size compositor/hidden-paint sensitivity and R3 real schema-2
public preparation/valid SDK no-budget proof remain retained. R4 points to this new
receipt, not a reconstructed missing directory. E1 removal still injects refresh
outcome (not all-real zero-HTTP removal). Historical selection offset has no claimed
causal repair. Auth sensitivity remains retained. Black/mypy waived, not green;
provider evidence remains offline synthetic, not live authorization or paid inference.
Independent sequential Step2/Step3 remain pending; readiness is not feature approval.
Earlier current/latest headings below are preserved historical receipts.

## Current sequential remediation — 2026-10-03 (R1–R4)

R1 control-aware `/reasoning`, R2 genuine two-size picker/router compositor proof,
and R3 real schema-2 public admission → valid SDK no-budget completion are corrected
with focused red/green evidence; affected partition: **460 passed, 5 warnings**.
Initial full gate found five picker status/context clipping regressions (5151 passed,
18 deselected); its full.log is retained. Corrected menu uses a separate reasoning
line only for explicit disable semantics, preserving status/context; two-line rows
retain original capacity and three-line rows use bounded capacity. This is a
narrow viewport adjustment to the original two-line plan, not weakened assertions.
Picker regressions now pass 32 tests. The new final gate receipt is `.f86-final-remediation-hldebc_g/full-final.log`, with exact
command in `full-final-command.txt` and result in `full-final.exit`. These artifacts are produced
**after this documentation is finalized**; consult their actual result, not an
anticipated pass. The missing `.f86-step1-1791030546-full` claim is not relied on.
See `docs/implementation/86-openrouter/sequential-r1-r4-remediation-2026-10-03.md`
for the finite matrix and source/test freeze contract. Prior headings below are
historical, not outstanding G1/G2 assertions or current gate pointers.

E1 remains qualified real-loader/stale-delivery/rotation proof: removal injects a
refresh outcome, not all-real zero-HTTP removal. Historical selection offset has
no claimed causal repair. Auth compositor/sensitivity evidence is retained.
Black/mypy remain waived, not green; 18 normal E2E/default-disabled exclusions
are expected (actual gate log controls). All provider evidence is offline synthetic,
not live authorization, availability or paid inference. Independent Step2/Step3
remain pending; no feature-completion or approval claim.


## Latest recovery receipt — 2026-10-03 final authorized Call 4: REVISE

Fresh complete post-edit non-E2E gate: **5136 passed, 18 deselected, 196 warnings
in 327.78s; exit 0**, `.f86-final-recovery-O3ZPKA/full-non-e2e.log`.
This supersedes earlier receipts as the latest execution, not as approval.
Budget evidence persistence, nullable-rate override restoration, actual default-effort
SDK wire assertion and bounded picker detail fixes landed. Remaining: unexplained
Call3 selection offset failure (passes isolated/full now, no causal repair), `/reasoning`
presentation and mounted two-size proof, prepared/no-budget evidence, and stronger
real-store admission proof (new removal test injects refresh outcome).
See `docs/implementation/86-openrouter/final-recovery-evidence-2026-10-03.md`.
**STEP1READY withheld.** Independent Step2/3 remain pending. Offline synthetic tests
are not live authorization/availability/inference evidence; 18 E2E/default-disabled
live/fixture cases were deselected. Black/mypy waived, not green. Earlier receipts
below remain historical; no final workflow approval.


This file is loaded into every agent session by `ProjectContextDiscovery` and is the
authoritative reference for anyone (human or AI) working on this codebase. Update it
whenever you make a significant architectural change, add a new component, rename a module,
or alter the runtime chain or system prompt assembly.

---

## 1. Project Overview

Slo is a **Python ReAct coding-agent harness** modelled on [pi.dev](https://pi.dev) — a
mature TypeScript reference agent. We borrow pi's design ideas and re-implement them in
Python under our own conventions: LangGraph for the state machine, LangChain for the LLM
layer, and Textual for the TUI.

One-line framing: *pi is the teacher; Slo is the student we own.*

**What Slo does:**
- Runs an unbounded ReAct loop (reason → act → observe → repeat) over a cloud LLM
  with 10 file/shell tools bound at session start.
- Streams progress to the Textual TUI via `AgentStreamEventDAO` events.
- Persists a full-fidelity JSONL event log per session under `~/.slo/sessions/history/`.
- Loads project instruction files (`SLO.md` / `AGENTS.md` / `CLAUDE.md`) from the
  working directory tree into the system prompt automatically.
- Keeps 117 vendored convention skills (`skills/`) readable on demand via the `read` tool.
- Spawns and supervises headless sub-agents via `spawn_sub_agents` when promoted to
  orchestrator mode.

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
| `make install` | `install.sh` → pipx install of the code, then finalise the managed shell environment file under `~/.slo/shell/` |

---

## 3. Repository Layout

```
slo/
├── src/
│   ├── agents/
│   │   ├── base.py                    # LLMFactory.create — the ONLY LLM construction point
│   │   ├── hooks/                     # ShouldStopAfterTurnHook, Hook
│   │   ├── providers/
│   │   │   ├── stream_recovery/             # typed provider stream disconnect classification + config
│   │   │   ├── anthropic_claude_code.py     # Claude OAuth / thinking payload builder
│   │   │   ├── openai_codex.py              # ChatGPT / reasoning payload builder
│   │   │   ├── credit_exhaustion_policy.py  # CreditExhaustionPolicy — classify errors by provider
│   │   │   ├── model_pool.py                # ModelPool — priority-ordered BaseChatModel router
│   │   │   └── faux.py                      # FauxChatModel — queue-based deterministic mock
│   │   ├── slo_agent/
│   │   │   ├── agent.py               # SloAgent — multi-turn invoke loop
│   │   │   ├── watchdog_timer.py      # WatchDogTimer — provider deadlines + local-tool suspension
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
│   │   │   │   └── system_prompt.py   # All static string constants (ROLE_LINE, KB_BLOCK_TEMPLATE, …)
│   │   │   ├── dao.py                 # SloAgentConfigDAO and related
│   │   │   ├── history/
│   │   │   │   ├── atomic_io.py       # AtomicFileWriter — shared temp+replace durable-state writer
│   │   │   │   ├── dao.py             # HistoryEventKind, SessionHistoryEventDAO, metadata incl. session_name/session_name_key
│   │   │   │   ├── filesystem_store.py # FilesystemSessionHistoryStore — JSONL writer + resume-by-name resolution
│   │   │   │   ├── projector.py       # SessionHistoryProjector → list[BaseMessage]
│   │   │   │   └── transcript.py      # TranscriptEntryDAO, ReplayEntryProjector
│   │   │   ├── orchestrator/
│   │   │   │   ├── dao.py              # Sub-agent DAOs and centralized terminal projections
│   │   │   │   ├── fleet_store.py       # FleetStore — durable ProcessRegistry projection to fleet.json
│   │   │   │   ├── status_store.py      # OrchestratorStatusStore — self-reported orchestrator.json owner
│   │   │   │   ├── layout.py           # OrchestrationLayout — canonical workflow/fleet/capture paths
│   │   │   │   ├── process_probe.py    # ProcessProbe — conservative shared PID liveness semantic
│   │   │   │   ├── spawn_env.py        # Shared allowlisted headless-child env and capture opener
│   │   │   │   ├── capture_writer.py   # Independent split-byte literal redacting FD writer for launch/relaunch
│   │   │   │   ├── process.py          # SubAgentProcess — child spawn, stream relay, captures
│   │   │   │   ├── pool.py             # SubAgentPool — bounded sub-agent dispatch
│   │   │   │   ├── launch_tool.py      # launch_workflow — detached orchestrator spawn
│   │   │   │   ├── relaunch.py          # WorkflowRelauncher — resume a dead detached workflow
│   │   │   │   └── workflow_registry.py # WorkflowHandleStore and workflow commands
│   │   │   ├── tool_execution/
│   │   │   │   ├── service.py         # plan_tool_batch — parallel vs sequential planning
│   │   │   │   ├── dao.py             # ToolExecutionPlanDAO
│   │   │   │   └── executors.py       # SequentialToolExecutor, ConcurrentToolExecutor
│   │   │   ├── plugins/               # Feature 75: typed plugin contract, trust/loader/registry/dispatcher, identity + managed installer
│   │   ├── runtime.py              # SloRuntimeContext — session-owned plugin/introspection seam
│   │   ├── compaction/            # Compacter, CompactionChecker, CompactionResult
│   │   │   ├── turn_stream_accumulator.py
│   │   │   ├── assistant_chunk_normalizer.py
│   │   │   ├── graph_stream_parser.py
│   │   │   └── message_text.py
│   │   ├── model_catalog/             # canonical model catalog — identity, defaults, reasoning, aliases, discovery
│   │   │   ├── dao.py                 # ModelCatalogEntryDAO, ModelRuntimeProfileDAO, ModelReasoningProfileDAO, …
│   │   │   ├── seed.py                # committed first-class entries, family templates, aliases
│   │   │   ├── discovery.py           # async compatibility delegation to ModelCatalogService; pure override/direct-template helpers
│   │   │   ├── service.py             # ModelCatalogService.load() — merged snapshot + projections
│   │   │   ├── store.py               # cache and override file persistence
│   │   │   └── prompt_clause.py       # append_kimi_for_coding_clause exact-match helper
│   │   ├── skills/
│   │   │   └── registry.py            # SkillRegistry — parses skills/<name>/SKILL.md
│   │   ├── tools/
│   │   │   ├── bundles.py             # create_extended_tools() and the three pi-parity bundles
│   │   │   ├── read.py / write.py / edit.py / bash.py / tool_output.py
│   │   │   ├── grep.py / find.py / ls.py
│   │   │   ├── read_pdf.py / now.py / show_git_diff.py
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
│   │   ├── plugin.py                  # `slo plugin install|list|uninstall|upgrade` parse surface
│   │   ├── update.py                  # `slo update` self-updater + installer launcher finalization + ShellEnvironmentDefaults
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
│   │   ├── slodiff/                   # Clean-room extractable diff model + Textual widget
│   │   ├── git_diff_content_service.py # Safe HEAD-versus-worktree content loader
│   │   ├── git_diff_screen.py          # Focused /diff screen and controls
│   │   ├── workflows/                 # Detached-workflow receive path (spec 57.a.5)
│   │   │   ├── dao.py                 # Parsed lifecycle/launch DTOs, DetachedWorkflowUiEffectDAO
│   │   │   ├── service.py             # DetachedWorkflowAppService — handles, state cache, typed effects
│   │   │   └── renderer.py            # DetachedWorkflowRenderer — launch guard, notices (no Textual)
│   │   ├── model_catalog.py           # supported_models_by_provider()
│   │   ├── authentication/            # AuthenticationScreen + widgets (api_key, oauth, …)
│   │   └── widgets/
│   │       ├── user_message_block.py     # UserMessageBlock — one user turn with panel surface styling
│   │       ├── assistant_stream_block.py # AssistantStreamBlock — one assistant answer turn (answer-only)
│   │       ├── assistant_stream_thinking_block.py # AssistantStreamThinkingBlock — one thinking segment per normalized block_id
│   │       ├── tool_execution_block.py   # ToolExecutionBlock — one tool call+result with panel surface styling
│   │       ├── queued_prompt_block.py    # QueuedPromptBlock — one visible latest-wins held ordinary prompt
│   │       ├── usage_status_bar.py       # UsageStatusBar — token/rate display
│   │       └── slash_suggestion_menu.py  # SlashSuggestionMenu — autocomplete dropdown
│   └── exceptions.py
├── tests/
│   ├── agents/
│   │   └── slo_agent/                 # unit tests: agent loop, session, rate limits, usage
│   ├── tui/                           # TUI tests: app, replay, slash, status bar, tool blocks
│   │   └── workflows/                 # receive-path dao/service/renderer unit tests
│   └── integration/                   # cross-component (future)
├── plugins/
│   └── bash_live_output/              # bundled Feature 75 consumer-only Bash live-output renderer
├── skills/                            # 117 vendored SKILL.md files + INDEX.md
│   ├── INDEX.md                       # regenerated by `make build-skill-index`
│   ├── orientation/
│   ├── design-and-analysis/
│   ├── coding/
│   ├── git-ops/
│   ├── cli/
│   ├── tui/
│   ├── integration-tests/
│   └── frontend-vue/
├── specifications -> ../specifications  # symlink to the canonical spec root
├── pyproject.toml
├── AGENTS.md  ← this file
├── docs/
│   ├── INSTALL.md
│   ├── RESEARCH.md
│   ├── SLO_HEADLESS_README.md
│   └── SLO_SCHEDULER_README.md
└── CLAUDE.md  (loads AGENTS.md on every session)
```

### Context Window Snapshot and manual compaction (spec 62)

`ContextWindowSnapshotService` (`src/agents/slo_agent/compaction/context_window.py`) is a pure
read model: it resolves routed-model capacity through the model catalog and sums only
`SessionHistoryProjector.context_events()` (selected, message-producing durable replay events).
It is intentionally distinct from cumulative provider `session_totals` and may be lower than the
automatic compaction check because `assistant_delta` and incomplete/audit events do not replay.
`SloAgentSession` owns history I/O and caches the snapshot in `SessionUsageSnapshotDAO`; the TUI
performs bounded refreshes only at mount, session/model transitions, `/context-window`, session-owned
manual compaction, and prompt cleanup, never on each streamed delta.

`SessionHistoryStoreProtocol.compact_to_boundary()` is the single durable rewrite seam used by
automatic, overflow, and manual compaction. The flat store writes+fsyncs a candidate, moves active
history to a collision-free deterministic archive, activates the candidate, then writes metadata.
Ordinary post-archive failures restore byte-identical active history and metadata;
`HistoryCompactionRecoveryError` names active/archive paths if restoration itself fails, and readers
restore the deterministic archive before loading. The tree store delegates this same transaction.

### Feature-request and specification artifacts

- **Incoming feature requests:** the repo-local `feature-requests/` directory.
- **Canonical specification root:** the operator-side specifications directory
  that `specifications/` points at. Resolve it with `readlink specifications`
  rather than hard-coding a machine path.
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
slo (pipx isolated wrapper → generated slo-entry → src/cli/__main__.py)
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
  references and optional `--workspace <file.code-workspace>`, launches the TUI or a headless run,
  and owns the async boundary for `slo plugin install|list|uninstall|upgrade`.
- `SloTUI` — Textual app. Owns the layout (header, scroll container, `UsageStatusBar`,
  `PromptInput`, footer), mounts transcript widgets, dispatches slash commands, owns
  `/new` session replacement + `/rename`, manages in-process prompt-history recall, and
  subscribes to the session's event stream.
- `SloAgentSession` — process-level wrapper. Holds one `SloAgent`, enforces one in-flight
  prompt at a time, owns the subscriber list for render events, discovers/merges trusted plugins
  and subscribes their dispatcher, persists the JSONL history
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
5. Skills block — the XML manifest plus a line naming `SKILLS_LOCATION` (path + source) when
   skills loaded; otherwise `SKILLS_BLOCK_TEMPLATE`: `<SKILLS_LOCATION.path>/INDEX.md`, its
   source, and OS-independent recovery steps (`$SLO_SKILLS_DIR` → `$SLO_HOME/skills` →
   `pipx runpip slo show slo` → `<Location>/skills`)
6. Knowledge base block (`KB_BLOCK_TEMPLATE`) — `KB_LOCATION` path + source and the
   `locate-knowledge-base` lookup order; a missing KB never blocks
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
| `ToolOutputUpdateDAO` | `tools/tool_output.py` | Typed display-only partial-output snapshot used by streaming-capable tools |
| `show_git_diff` | `tools/show_git_diff.py` | Return safe JSON HEAD-versus-worktree content for one repository-relative UTF-8 text file |

Three pi-parity sub-bundles also exist: `create_coding_tools()` (read/bash/edit/write),
`create_read_only_tools()` (read/grep/find/ls), `create_all_tools()` (all seven pi tools).

Blocking leaf work in the local tools (file I/O, PDF extraction) and bash post-processing
(`BashTool._format_result` — decode, exit-code framing, tail truncation, and optional
full-output spill after a subprocess completes) are offloaded via `run_blocking_tool_call`
in `tools/_blocking.py` (`asyncio.to_thread` behind a per-event-loop semaphore) so
read-heavy batches and large bash outputs do not stall Textual. Bash subprocess ownership
(`_spawn`, `_communicate_with_timeout`, `_terminate_process_group`) stays async on the
caller loop; only the synchronous formatting leaf crosses the gateway, and
`_spill_to_tempfile` remains a plain leaf called from `_format_result` (no nested offload).

---

## 7. Skills System

Skills are vendored convention prompts that the agent reads on demand.

- **Location:** `skills/<group>/<slug>/SKILL.md` — 117 skills across 10 groups:
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

**Orchestrator timeouts for projects with slow test suites:** `spawn_sub_agents` is a
**blocking** tool — while a child runs, the orchestrator's own LangGraph stream emits
nothing, so the parent guard `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` (default `10800`)
measures wall-clock silence for the child's entire runtime. A continuously busy child keeps
resetting its own `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` (default `7200`) and never trips
it, so the parent guard is the true ceiling on a single blocking phase. If a phase's gates
run long (e.g. a Go `go test -race ./...` suite), the orchestrator aborts a still-healthy run
with `TimeoutError: main agent stream produced no events for <N>s; treated as hung` and kills
the child mid-task. Before launching a dynamic/headless workflow against such a project,
export both guards (parent strictly greater than child) in the shell that starts the
orchestrator, or re-export them via a `bash` tool call before the first `spawn_sub_agents`:

```bash
export SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800   # orchestrator: 3h ceiling per blocking phase
export SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200  # child: 2h between stdout events
```

Also prefer splitting a phase so no single blocking `spawn_sub_agents` call runs longer than
the parent guard. See KB `slo/headless-workflow-orchestration.md` → "Long-running phases /
slow test suites".

---

## 8. Knowledge Base

- **Path:** `config.cfg.KB_LOCATION` — `SLO_KB_DIR`, else `KB_DIR` (fallback alias), else
  `$SLO_HOME/KnowledgeBase/KB`. A value pointing at a file resolves to its directory. The
  path may not exist; resolution never creates it.
- **Workspace files:** when `slo --workspace <file.code-workspace>` is used, the workspace file itself is not treated as a project-instruction file; instead its declared folders seed additional `ProjectContextDiscovery` walks.
- **In-prompt:** `KB_BLOCK_TEMPLATE` in `system_prompt.py` shows the resolved path and its
  source, the lookup order, and the entry points (`Welcome.md`, `index.md`, `Index.md`,
  `Home.md`). When no KB is found the agent tells the user, offers to create one
  (`locate-knowledge-base` skill), and continues.
- **Shell default:** the installer's managed `~/.slo/shell/environment.sh` sets
  `SLO_KB_DIR` (from `KB_DIR`, else `$SLO_HOME/KnowledgeBase/KB`) only when it is unset.

---

## 9. TUI

**`SloTUI`** (`src/tui/app.py`) is the Textual `App` for the interactive path.

**Per-component transcript model:** every conversational entry is a dedicated Textual widget:
- `UserMessageBlock` — one user turn, rendered with `Rich.Markdown`.
- `AssistantStreamThinkingBlock` — one normalized parent thinking segment, keyed by the
  normalizer's stable `block_id`; it is sealed by its content-bearing repair end or the
  terminal-run sweep (a contentless `thinking_end` leaves the segment open and live).
- `AssistantStreamBlock` — one answer-only assistant iteration; reasoning never renders here.
- `ToolExecutionBlock` — one tool call + result pair; updates as the tool executes.

Non-conversational notices (system messages, slash-command echoes) remain flat `Static`
lines. **Both the live path and the replay path use the same widgets** — resumed sessions
render identically to live.

**Pi design restyle (spec 72.a.5):** both `Theme.variables` mappings in `src/tui/theme.py`
define the same seven canonical Pi-derived semantic tokens — `user-msg-bg`,
`tool-pending-bg`, `tool-success-bg`, `tool-error-bg`, `thinking-text`, `md-heading`,
`border-muted` — and widget `DEFAULT_CSS` consumes them via `$<token>` references (no
hard-coded role colors). A user turn is a quiet `user-msg-bg` band; thinking segments and
answers stay bare on the canvas (thinking is muted italic `thinking-text`, answer headings
use warm `md-heading`); a `ToolExecutionBlock` paints pending/success/error fills and
gains the CSS-state hooks `-done` (added by `update_result()`) and `-error` (added by
`mark_incomplete()`) purely as styling seams — `_result_output`/`is_incomplete` remain the
lifecycle truth used by `_is_block_live`. The turn separator is a muted `─` rule
(`_TranscriptAdapter.TURN_SEPARATOR`, `border-muted`). `UsageStatusBar` renders Pi-style
compact token quantities (`6.0k`, `12k`, `1.0M`) for token values only — rpm, cooldown
seconds, and context percent keep their raw units. `SloTUI._refresh_title_bar()` collapses
the session workdir to `~`/`~/...` via `_collapse_home_in_path` (`Path.relative_to`
ancestry, so home-prefix lookalikes stay absolute); the usage bar owns no cwd display.

`TranscriptProjector` owns parent `block_id` routing and mounts replay reasoning as a
sealed thinking block immediately before its answer block (replay adjacency). `SloTUI`
owns child/sub-agent events: child thinking updates fleet activity only and never mounts
a foreground transcript block.

**Queued prompt (spec 72.a.4 + input-adjacent anchoring):** an ordinary (non-slash) prompt
submitted while a run is active is held in a one-deep, latest-wins app-owned slot
(`_queued_prompt_text` plus its mounted `QueuedPromptBlock`, rendered as `⏳ Queued: <text>`);
a newer busy submission replaces the held text in place rather than FIFO-appending. The
visible block mounts into `#chat-shell` directly before `PromptInput` — anchored immediately
above the bottom input area, outside the scroll region — so it stays visible while the
transcript scrolls; it is never a transcript child, so transcript window eviction cannot
reach it and `_is_block_live` carries no `QueuedPromptBlock` branch. There is still exactly
one `session.invoke()` task at all times — `_prompt_submission_lock` serializes acceptance
with the run-completion handoff (`_finish_prompt_run` → `_start_queued_prompt_if_idle`),
which removes the anchored block before echoing and starting the held turn through the
standard transcript path. `/abort` (and Ctrl+C) preserve the held prompt and write a
single survival notice; `/clear` and an allowed `/new` replacement discard it (clear
explicitly removes the anchored block). Slash commands and inbox `chat_turn` items never
enter the user queue.

**Transcript copy and output padding (specs 72.a.3 and 81):** there is no
card-local copy control on any transcript block. Copy runs through `SloTUI` only —
the focus chord (`ctrl+shift+c` / `meta+c` → `action_copy_visible_text` → the
focused block's `get_copyable_text()`) and mouse drag selection (`on_text_selected`)
both funnel into `copy_to_clipboard` (pyperclip → OSC 52). All four message widgets
(`UserMessageBlock`, `AssistantStreamThinkingBlock`, `AssistantStreamBlock`,
`ToolExecutionBlock`) retain the uniform `TRANSCRIPT_OUTPUT_PAD` convention: CSS
`padding: 0 1`; the `#transcript-content` outer-frame padding is unchanged.
Terminal-native copy remains flattened selection plus these existing clipboard paths:
OSC 133 prompt-zone markers are deferred pending a Textual-supported terminal-output
seam that preserves raw zero-cell controls end-to-end.

**Granular Markdown selection on textual message bodies (spec 81.c.1):**
`MarkdownContentCompiler` (`src/tui/widgets/markdown_content_compiler.py`) is the one
app-free markdown-it AST-to-visible-text owner for `AssistantAnswerBody`,
`AssistantThinkingBody`, and `UserMessageBody`. Its single append-only writer produces
`MarkdownContentDAO(raw_markdown, visible_text, spans)`: raw Markdown remains owned by the
message block, while `Content` renders and native drag selection extracts only the readable
visible buffer. Role-name spans resolve through the active Slo theme only at mounted body
boundaries; Pygments adds spans, never display text, for exact case-insensitive trim-only fence aliases (Python, shell, data, diff/patch, JS/TS, TOML/INI/XML/HTML/CSS/SQL/Dockerfile/Markdown). Every fenced and indented code block retains `markdown-code`; unknown, attribute-bearing, unlabeled, resolver-failed, lexer-failed, and reconstruction-failed fences remain generic-only. Diff/patch adds additive `markdown-code-diff-added`, `markdown-code-diff-removed`, `markdown-code-diff-hunk`, and `markdown-code-diff-file` line roles defined in both themes.
There is no offset mapper, Rich visual, custom selection paint, second clipboard path, or
scroll-time selection clearing. Standard focused copy returns the complete visible buffer;
`ctrl+shift+m` / `meta+shift+m` resolves the nearest focused transcript-block owner and uses
the same `copy_to_clipboard()` funnel to copy its complete raw Markdown. Both themes retain
native `screen-selection-background` / `screen-selection-foreground` ownership. Tests in
`test_markdown_content_compiler.py`, `test_user_message_block.py`,
`test_selection_scroll_highlight.py`, `test_selection_copy.py`, and
`test_selection_copy_e2e.py` cover compiler output, themes, raw/visible copy, native drags,
paint, scrolling, and replay.

**Session replay:** `ReplayEntryProjector.build_entries()` reads the on-disk JSONL and
emits `TranscriptEntryDAO` objects. `TranscriptProjector.project_replay_entry()` mounts the
same widget types. `TranscriptProjector` (`src/tui/transcript_projector.py`) owns the live
streaming path too.

**Slash commands** are dispatched by `SlashRouter` (`src/tui/slash_router.py`).
`SlashCommandRegistry` (`src/tui/slash_command_registry.py`) holds the metadata
(`SlashCommandSpecDAO`). `SlashSuggestionEngine` (`src/tui/slash_suggestion_engine.py`)
does prefix-match autocomplete; `SlashSuggestionMenu` renders the dropdown.

Available slash commands include: `/help`, `/diff <repository-relative-path>`, `/new [session name]`, `/rename <session name>`,
`/model <name>`, `/reasoning <level>`, `/context-window`, `/compact`, `/abort`, `/steer <text>`,
`/clear`, `/auth`, `/quit` (and aliases), and `/workflows [abort|dismiss|resume] <workflow-id>`.
`/context-window` reports the routed model's capacity
and projector-faithful durable replay estimate; `/compact` requests one lock-safe, transactional
manual compaction and rejects while a prompt owns the session lock.

**`UsageStatusBar`** (`src/tui/widgets/usage_status_bar.py`) is a `Static` widget fixed
above the footer. It is updated via `session.usage_snapshot` whenever `SloAgentSession`
emits a `SessionUsageSnapshotDAO`.

**Prompt-history recall** is owned by `PromptHistoryNavigator` (`src/tui/prompt_history.py`).
`PromptInput` only emits semantic older/newer history messages; the app records submitted
non-slash prompts, gives slash suggestions precedence, and restores the preserved draft when
history navigation exits.

**`ThinkingSpinner`** (`src/tui/thinking_spinner.py`) is mounted above `PromptInput` while
the agent is running or while a slash command whose `SlashCommandSpecDAO.shows_activity`
flag is true is dispatching (`/compact` is the first consumer). It is a `Horizontal` with
two child `Static`s: an accent braille activity glyph rotating every 0.08 s
(`_BRAILLE_FRAMES`) and a muted italic text surface that rotates verbs every
`interval_seconds` (default 1.5 s) or carries a retry/compaction override via
`set_override_status(text=...)` — overrides never stop the glyph. Slash dispatch only
unmounts a spinner it mounted itself, so it cannot remove an active run spinner.

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

**Headless heartbeat and failure envelope (specs 70/71):** `HeadlessRunner` emits a stderr-only
`headless_status` heartbeat from a watchdog thread every `SLO_HEADLESS_HEARTBEAT_SECONDS` (15 by
default). A recognized same-session heartbeat is advisory liveness telemetry (`healthy`, `degraded`, or
`silent`); it never cancels a child or shortens the sole stdout-inactivity authority,
`SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS`. `SubAgentResultDAO` carries additive, redacted
`failure_code`, `partial_output_committed`, `attempts`, and `safe_message` fields; cancellation remains
SIGTERM → grace → SIGKILL → reap with one cached terminal result.

**Detached workflow supervision:** workflow handles live at
`<owner_session>/workflows/wf-*.json` (TUI-owned); each orchestrator session also has
`orchestrator.json` (HeadlessRunner self-report), `fleet.json` (pool projection),
`abort_request.json` (TUI durable abort channel), and each child has `status.json` (terminal result).
`/workflows resume <workflow-id>` relaunches a `stalled` or `failed` handle against its original
orchestrator session with `--resume`; the dedicated flock-protected store transition returns it to
`launching`, and fresh self-reported evidence advances it to `running`.

**Detached-workflow receive path** (`src/tui/workflows/`, spec 57.a.5) — the strict
delegation chain for headless-orchestrator lifecycle data:

```
SloTUI ── raw kind/payload ──> DetachedWorkflowAppService ── typed HandleAdvanceOutcomeDAO ──> SloTUI
                                     │                                                    │
                                     │ durable handle advance + live-state cache           ▼
                                     │                                          DetachedWorkflowRenderer
                                     │                                          (apply_effects only)
                                     └──────── typed DetachedWorkflowUiEffectDAO ─────────┘
```

- `dao.py` owns the only parsing/validation seams (`parse_workflow_lifecycle_message`,
  `parse_launch_workflow_result`) and the typed effect vocabulary
  (`launch_visualizer`, `reset_launch_guard`). No Textual, no filesystem.
- `DetachedWorkflowAppService` (`service.py`) owns `WorkflowHandleStore` reconcile/update,
  the legal durable transitions, and the `workflow_id → state` cache that backs the
  resume/exit hint. Terminal advances emit **reset-only** effects — never a launch effect.
- `DetachedWorkflowRenderer` (`renderer.py`) owns the one-window-per-orchestrator-session
  launch guard, `VisualizerLauncher` calls, and transcript notices via the
  `DetachedWorkflowNoticeSink` protocol. Guard reset happens only through a typed
  `reset_launch_guard` effect — the app never branches on terminal fields.
- **Strict app boundary:** `SloTUI` passes raw inbox kind/payload (or the raw
  `launch_workflow` tool-result text) to the service exactly once, then only executes the
  typed effects the service returned. The app never parses workflow payloads itself.

---

## 10. Auth

**`CredentialResolver`** (`src/auth/credential_resolver.py`) is stateless. Precedence:
1. Environment variable for the provider (`SLO_ANTHROPIC_API_KEY`, `SLO_OPENAI_API_KEY`, or `SLO_KIMI_FOR_CODING_API_KEY`).
2. `CredentialStore` merges two files under `$SLO_HOME/global`: `authentication.json`
   holds only `anthropic` / `openai` / `kimi_for_coding`; every other provider known
   to this version (OpenRouter today) uses `authentication.additional-providers.json`.
   Both use the same DAO. `SLO_AUTH_FILE` moves the released file and its sibling
   together. Future versions must put providers unknown to this version in a new
   sibling file, never in this version's closed-enum additional-provider file.
3. `~/.claude/.credentials.json` (Anthropic only — legacy Claude Code credentials).

`LLMFactory.create` calls `CredentialResolver.require(provider=...)` once per build.
The first-run / sign-in UI lives in `src/tui/authentication/`. `SloTUI.on_mount` pushes
`AuthenticationScreen` when `CredentialResolver.resolve` returns `None` for the active
model's provider. Users re-open the modal with `/auth`. Subscription OAuth declares interaction capability through
`OAuthLoginMethod` (`BROWSER_AUTHORIZATION` / `DEVICE_AUTHORIZATION`):
`DeviceAuthorizationFlow` owns generic device polling while `OAuthFlow` owns browser/manual
handoff. An `OAuthFlowFactory()` instance is the factory seam: its `__call__` takes
(`provider`, `login_method`, browser/device presentation callbacks, and optional authorization-response
receiver), and the modal injects faux flows through it in tests. Browser opening is guarded by
`BrowserHost` (`src/auth/browser_host.py`): on any host other than macOS/Windows with `DISPLAY`,
`WAYLAND_DISPLAY` and `BROWSER` unset, neither `OAuthFlow` nor `SloTUI.open_url` calls `webbrowser` (it would
run a console browser on the TUI terminal); elsewhere they open off the event loop, and `OAuthFlow` opens
concurrently with the callback/paste race. Tests inject `browser_host=` instead of patching the
environment. The callback, browser/manual attempt,
and device attempt deadlines are configured by `SLO_OAUTH_TIMEOUT_SECONDS`,
`SLO_OAUTH_MANUAL_TIMEOUT_SECONDS`, and `SLO_OAUTH_DEVICE_TIMEOUT_SECONDS` respectively.

### OpenRouter current delivery (Feature 86 — partial, not complete)

Canonical OpenRouter identity is `'openrouter:<exact-remote-id>'` and always maps to
`ProviderName.OPENROUTER`, regardless of the remote ID's author segment. Credential
precedence is `SLO_OPENROUTER_API_KEY` then the OpenRouter credential-store row; there
is no OpenRouter legacy fallback, empty is absent, and whitespace-only environment
values fail before HTTP. `OpenRouterAuthenticationService` owns candidate-before-
persist verification through the existing resolver, store, GET client, and catalog
refresh evidence seam. Its public result is secret-free; an environment key wins over
a pasted replacement and is never overwritten by it. Factory capabilities select the
API-key-only OpenRouter screen, and `AuthenticationScreen` tracks cancellation.

Authenticated `/key` and `/models/user` discovery feed the canonical catalog. Offline
`load()` remains I/O-free; `/model refresh` delegates to the session/catalog gateway.
The bounded picker searches cached canonical ID/display rows and exact selection
prepares the route. Selection precedence is exactly: explicit model → configured
pool → resumed route → saved default → cfg default. An explicit `--model` or
`/model <route>` clears a configured pool. A resumed routed pool member is a single
route, not a reconstructed pool.

`TyperDispatch.tui` opts into pending-capable session construction; strict headless
and programmatic paths prepare before inference. `preparation_status` is transient,
pending usage has unknown limits, and the mounted app owns one tracked
`prepare_startup()` task with retry after `/auth` or `/model refresh` and cancellation
on unmount. Successful adoption updates the same session's snapshot/reasoning/usage;
pending prompts and selection cannot run. Scheduled runs pass their stored model into
the ordinary headless path. Trusted children receive the explicit
`SLO_OPENROUTER_API_KEY` exception; other secret-shaped settings remain filtered.

The adapter's opaque reasoning/route continuation metadata is private runtime/history
state for same-route replay only. Public stream events, headless JSONL, and safe
operator diagnostics must not expose it or raw provider bodies. Current local tests
cover meaningful auth/catalog/picker/session/SDK/history slices, but do not prove
live provider availability, credential authorization, network reachability, paid
inference, or Feature 86 completion. The retained **pre-correction** Step 1 gate is
**5115 passed, 18 E2E-marked deselected, 196 warnings in 373.69s; exit 0** at
`.f86-integration-retry-ucwY1o/full-non-e2e.log`. The 18 deselections include the
default-disabled live/fixture harness tests; executed OpenRouter tests are offline
local/mock transport tests. Black/mypy are waived only as static gates, not green.
Independent review and completion remain **REVISE** while source corrections are
concurrent; do not treat this as a final post-correction gate or approval. Bounded
evidence includes append ordering/refusal, independent OS-process resume admission,
cancellation while an append lease waits, and a reaped-launcher kernel EBADF case
through instrumented shipped writer/reporter bodies with native I/O. That is not
native interpreter-startup equivalence and does not imply an argv-equality product
requirement. See
`docs/implementation/86-openrouter/independent-full-rereview-2026-10-03.md` for
current findings and `current-status-2026-10-02.md` for preserved dated history.

### OpenRouter private continuation diagnostics (bounded 86.a.3)

`OpenRouterChatOpenAI` scopes SDK request-option protection with ContextVar depth
and per-scope filters, preserving nested/concurrent request lifetimes. Known SDK
transport-exception records retain fixed labels without raw tracebacks. Private
runtime traces and replay-bearing history intentionally retain the typed extension;
public stream events and headless JSONL do not. Local composed tests in
`tests/agents/providers/test_openrouter_channels.py` cover the real SDK/tool/session,
filesystem anchor, headless emitter, and TUI replay paint. Full status/fleet/capture
and pool-audit sentinel proof remains incomplete.

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

`kimi-k3` supports the canonical reasoning levels `low`, `high`, and
`xhigh`. It always reasons: `off` and `minimal` clamp to `low`, and
`medium` clamps to `high`; `xhigh` maps to K3 API provider effort `max`.
Only enabled K3 resolved reasoning adds the top-level `reasoning_effort`
field. `kimi-for-coding` and `kimi-for-coding-highspeed` remain off-only.
The Kimi builder never emits `thinking`, OpenAI `reasoning`,
`use_responses_api`, or `output_version`.

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

**Provider-error classifier** (`src/agents/providers/credit_exhaustion_policy.py`):
- `ProviderErrorClassifier.classify(error, provider)` → `ProviderErrorKind` is the **one shared
  classifier** consumed by all three failure paths: `ModelPool` route-switching, `RecoveryPolicy`,
  and `SloAgentSession`'s single-model iteration retry. `CreditExhaustionPolicy` remains as a
  backward-compatible alias for the old name.
- `should_switch(kind)` is the single switch-vs-propagate predicate (`OTHER` ⇒ propagate).
- Anthropic: 402 or "credit balance"/"billing" → `CREDIT_EXHAUSTED`; 429 → `RATE_LIMITED`; 529 → `TRANSIENT_PROVIDER_FAILURE`
- Kimi For Coding: 402 → `CREDIT_EXHAUSTED`; 429 → `RATE_LIMITED`; 500/502/503/529 → `TRANSIENT_PROVIDER_FAILURE`
- OpenAI: `code in {"insufficient_quota", "billing_hard_limit_reached"}` → `CREDIT_EXHAUSTED`; 429 → `RATE_LIMITED`; 500/502/503 → `TRANSIENT_PROVIDER_FAILURE`; the status-less overload message ("our servers are currently overloaded") → `TRANSIENT_PROVIDER_FAILURE`.
- **Provider stream disconnection (spec 70):** `stream_recovery/StreamRecoveryService` is the sole
  concrete `httpx`/`httpcore` transport-family registry. It never inspects model identity. A known
  pre-commit failure classifies as `STREAM_DISCONNECTED`; ModelPool may switch only before its first
  chunk and records `provider_stream_disconnected` rather than raw error text. After committed output,
  the typed decision is `DO_NOT_REPLAY`; no automatic replay or mid-stream switch occurs.
- **Shared message-text fallback:** when no HTTP status settles the kind, `"rate limit"`/`"429"`
  in the message text → `RATE_LIMITED`. This preserves the former provider-agnostic session
  heuristic so a text-only rate limit still waits and retries under the unified classifier.

---

### Installed-command isolation (spec 82.a)

The installed user-facing pipx `slo` command is finalized by `install.sh` into a
POSIX wrapper that executes the validated venv interpreter as `python -I` against
its generated `slo-entry` trampoline. `install.sh` is the only wrapper writer;
`Updater` invokes its packaged `--finalize-launcher` mode after pipx regeneration
and before conditional shell finalization. Direct pipx mutations bypass this
contract and recover by re-running the matching tagged public installer. `-I`
protects initial CLI import resolution while preserving ordinary environment values.
Headless source/module spawns remain sanitized-environment paths without `-I`, and
the visualizer source fallback is trusted-source-only with no forwarded `PYTHONPATH`.

### Mixed-version state compatibility (86.b)

`ModelCatalogStore` owns only `model_catalog_cache.v2.json` / `.v2.lock`.
New code never opens, adopts, rewrites or removes released
`model_catalog_cache.json` / `.lock`. An incompatible shared-file shape needs a
new filename; an internal version field cannot protect a validating older reader.
`CredentialStore` remains the sole owner of both credential files. Misfiled rows
are ignored with a warning on each lookup, preserved on owning writes, and never
migrated automatically. Either corrupt file fails lookups and history redaction
closed. Move pre-fix rows manually before using the new build (README rollout).

Unknown saved direct models resume on the existing preferred/default model with a
notice in the existing startup block. Explicit models, configured pool primaries,
known aliases and OpenRouter pending preparation retain their precedence.
History is shared: the production `TreeBasedFilesystemSessionHistoryStore`
decorates the flat store and physically writes `events.jsonl` plus `session.json`,
not a separate tree.json format. Released compaction drops unknown
`provider_message_extension` fields from rewritten events; the pre-compaction
archive retains them. Ordinary append/resume preserves prior events.

`tests/compat` extracts real tag `v0.20.1` via `git archive` and runs it in a
minimal-environment subprocess on the same per-test synthetic SLO_HOME as new code.
It proves catalog silence, alternating credentials, and continuation in both
versions through default tree and explicit flat stores. Missing tags fail, never
skip. The real CLI visualize guard mounts the actual app headlessly and audits
catalog/credential access. See `docs/implementation/86b-model-catalog/b5-implementation.md`
for current gate results; historical 86.a waivers do not apply to 86.b.

## 11. History / Persistence

**Default store:** `TreeBasedFilesystemSessionHistoryStore` (`history/tree_store.py`).
Laid out under `~/.slo/sessions/history/<session_id>/`:
```
session.json    # SessionHistoryMetadataDAO — atomic temp+rename on update; includes session_name/session_name_key
events.jsonl    # canonical events; tree links live in payload.metadata
transcript.md   # derived; not authoritative
orchestrator.json # detached-orchestrator self-report when applicable
fleet.json        # durable child fleet projection when applicable
abort_request.json # TUI-to-orchestrator abort channel when applicable
children/<child_session_id>/status.json # child terminal result when applicable
```

The tree store delegates persistence to `FilesystemSessionHistoryStore`; both
satisfy `SessionHistoryStoreProtocol` (`history/store_protocol.py`) and use the
same physical layout. Passing an explicit flat store omits the tree decorator.
The decorator adds `entry_id` / `parent_entry_id` to `payload.metadata`, including
linking each tool result to its opening tool call. Released readers tolerate these
metadata fields. Do not infer a separate `tree.json` format from the class name.

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

Feature 75 plugin runtime: `SloAgentSession` loads managed plugins from
`~/.slo/plugins/plugins/<plugin-id>/`, trusted project plugins from
`.slo/plugins/`, and explicit `--plugin` paths in that order. `PluginLoader` imports
under isolated `slo_plugin_<namespace>` names; `PluginRegistry` validates collisions
and managed-manifest suffix declarations; `PluginDispatcher` is one isolated event
subscriber and owns the interception chains. `SLO_PLUGINS_DISABLED=1` disables all
plugin tiers. `slo plugin` lifecycle commands use `PluginInstallerService` as the
single managed-directory writer; the installer never executes installation-source
Python. The bundled `plugins/bash_live_output/` renderer can be dog-fooded with
`--plugin plugins/bash_live_output/plugin.py`.

**Feature 75 streaming:** `BashTool` may publish accumulated, throttled
`ToolOutputUpdateDAO` snapshots. The executor places them on the graph-owned queue;
`SloAgent` drains this into `AgentStreamEventDAO(kind="tool_output_update")`. The
TUI updates the existing `ToolExecutionBlock` by `tool_call_id`; partials are emitted
on headless stdout JSONL, persisted when history is enabled, and excluded from replay
model context. The terminal `ToolMessage` remains the sole model-visible tool result.

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

**Provider stream recovery and transport-progress policy (spec 70):** `StreamRecoveryService` supplies a
redacted `RETRY_FRESH_CONNECTION` / `DO_NOT_REPLAY` decision from exception family plus the agent-owned
commit boundary. The optional `SLO_PROVIDER_STREAM_FIRST_PROGRESS_TIMEOUT_SECONDS` (300),
`SLO_PROVIDER_STREAM_IDLE_TIMEOUT_SECONDS` (300), and `SLO_PROVIDER_STREAM_RECONNECT_DELAY_SECONDS` (1.0)
form the configurable fast transport policy beneath the unchanged outer watchdogs. `stream_reconnecting`
is diagnostic-only history and is excluded from replay context.

**Three-layer rate-limit defense (spec 37):**
1. **Preflight (session)** — `PreflightDecisionDAO` owns one history-aware estimate per
   provider attempt. RPM smoothing may wait, while a local TPM hint is advisory only: an
   empty-window oversized request emits `preflight_bypassed` and still reaches the provider.
   Degraded local preflight records no local attempt. The decision's exact estimate is reused
   for any escaped-provider or pool failed-lane observation; it is never re-estimated or read
   from a later deque entry.
2. **In-call route switch (ModelPool)** — a switchable error on the active member switches to
   the next member inside one provider call (see Section 10).
3. **Iteration-scoped retry (agent)** — `SloAgent.invoke(iteration_retry_policy=...)`
   retries a failed ReAct iteration **only when it emitted no visible output**, replaying the
   unchanged `accumulated_messages` (no duplicate transcript). Retryability is decided by
   `SloAgentSession._is_iteration_retryable_error`, which resolves the active provider
   (`_resolve_active_provider` → pool `active_provider`, else `provider_for_model`) and consults
   the shared `ProviderErrorClassifier`: only `RATE_LIMITED` and `TRANSIENT_PROVIDER_FAILURE`
   wait-and-retry, so the status-less OpenAI overload message now takes a bounded delayed retry
   (`run_retrying`) instead of an immediate same-model LLM recovery observation (`run_recovering`).
   `AllModelsExhaustedError` is retryable within the attempt budget; when spent, a terminal
   `run_failed` naming the cooled members reaches the screen. With no injected policy, legacy no-retry behavior is preserved.
   The session injects the policy via `_build_iteration_retry_policy` and relays/persists the
   agent's `run_retrying` events. **Overflow backstop (spec 46.a.2):** when a provider explicitly
   rejects an initial request for confirmed context overflow before any committed visible output,
   `_derive_next_attempt_plan` (not `_finalize_failed_attempt`) performs a forced compaction pass, emits four compaction
   lifecycle `AgentStreamEventDAO` kinds (`compaction_started`, `compaction_completed`,
   `compaction_failed`, `compaction_retrying`), persists a `run_retrying` audit event anchored
   to the failed turn, and returns a one-shot `overflow_retry` attempt plan. The retry plan
   sets `persist_user_message=False` (no duplicate history record), `excluded_turn_ids` to
   filter the failed turn from immediate replay context, and `preflight_compaction_mode="skip"`.
   If compaction returns `False` or raises, `_derive_next_attempt_plan` returns `None` and the original
   overflow error surfaces unchanged. Any committed output, a second overflow on the retry attempt,
   and an HTTP 413 / `REQUEST_BODY_TOO_LARGE` rejection are terminal (no replay, pool switch,
   iteration retry, LLM recovery, or forced compaction).

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
  `@tool` bridges, LangGraph nodes, and test helpers.

---

## 14. Testing

- **Test state isolation (86.b.1):** `tests/state_isolation.py` runs before application
  imports; `tests/conftest.py::isolated_slo_home` supplies a fresh HOME/SLO_HOME per
  test and rebinds cached state paths. Request the fixture for default-path tests.
  Its SLO_HOME import registry and inherited-state override list have source guards
  in `tests/test_slo_home_isolation.py`. Build HOME-dependent test parameters at
  test time, not collection time. Subprocess fixtures must keep their own temp roots.
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
- Change plugin discovery, managed installation, plugin dispatch/interception, or tool-output streaming.
- Change the history event schema or persistence layout.
- Add a new provider or change credential resolution precedence.
- Add the `--workspace` flag to the CLI surface or change workspace-context discovery semantics.
- Change the canonical feature-request root (`feature-requests/`) or the specification root that `specifications/` points at.

Keep **Section 5** (System Prompt Assembly) and **Section 6** (Tool Bundle) accurate — they
directly affect what every agent session sees and does.

## Feature 86 R2/R3/R4 remediation boundary

The headless stream task's ContextVar does not propagate back to its parent.
`HeadlessRunner` retains only the admitted operation capture observed at the event
subscriber, sanitizes public events before retaining/emitting them, binds the capture
around post-stream terminal notifier persistence, and releases it in `invoke` finally.
No capture is persisted or attached to a public DTO; private continuation is unchanged.
The fixed GET client rejects full pages adding no unique records before catalog
publication. Failed refresh retains the last-good provider slice.
`src/tui/model_catalog.py::ModelPickerRowDAO` is presentation-only;
`src/agents/model_catalog/dao.py::ModelCatalogEntryDAO` remains canonical.
See `docs/implementation/86-openrouter/remediation-r2-r3-r4-2026-10-03.md` for
historical 5045-pass non-E2E evidence and limitations. The later independent Step 2
rereview is **REVISE**; use
`docs/implementation/86-openrouter/independent-full-rereview-2026-10-03.md` for its
current findings.
