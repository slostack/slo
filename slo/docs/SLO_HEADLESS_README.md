# Slo Headless Cookbook

*A practical guide to running Slo without the TUI — for pipelines, scripts, orchestration, and the kind of engineer who thinks a blinking cursor is a moral failing.*

---

> "The TUI is where you go to think. The headless runner is where you go to work."  
> — something nobody has said, but should have.

---

## Preface: Why Run Headless?

The Textual TUI is genuinely lovely. It has panes and spinners and a tree view that lights up like a dashboard when the agent is deep in thought. It is the kind of thing that makes you feel like a scientist in a film from the 1980s.

But the TUI is a *display*. It consumes a terminal, it blocks your shell, and it cannot be embedded in a CI pipeline without tricks that would make a sane person weep. When you need Slo to run inside a bash script, a GitHub Actions step, a cron job, or as a child process under an orchestrator, you want none of that. You want bytes on stdout, a clean exit code, and the ability to pipe the whole thing through `jq` without redesigning your career.

That is what `slo run` is for. And now that we have orchestrator mode and the workflow visualizer, there is a complete story here: you can start an orchestrator that fans out work to dozens of headless sub-agents, watch the whole thing live in a read-only TUI, and have a machine-readable audit trail of every event from every worker.

This cookbook covers all of it — every flag, every environment variable, every observable behaviour — and builds toward a single culminating example: a real code-test-review workflow running as a headless orchestration.

Read the whole thing, or jump straight to the [quick reference](#quick-reference-all-settings-at-a-glance). Either way, by the end you should know exactly what every knob does and why it exists.

---

## Table of Contents

1. [Quick reference: all settings at a glance](#quick-reference-all-settings-at-a-glance)
2. [Your first headless run](#your-first-headless-run)
3. [The `slo run` command reference](#the-slo-run-command-reference)
4. [The `slo visualize` command reference](#the-slo-visualize-command-reference)
5. [Streaming output: JSONL event structure](#streaming-output-jsonl-event-structure)
6. [Capturing stdout and stderr](#capturing-stdout-and-stderr)
7. [Exit codes](#exit-codes)
8. [Enabling and using history](#enabling-and-using-history)
9. [Resuming sessions](#resuming-sessions)
10. [Working directory scoping](#working-directory-scoping)
11. [Model and reasoning overrides](#model-and-reasoning-overrides)
12. [System prompt overrides](#system-prompt-overrides)
13. [Orchestrator mode and sub-agents](#orchestrator-mode-and-sub-agents)
14. [Default orchestrator prompt](#default-orchestrator-prompt)
15. [Timeouts and retry behavior](#timeouts-and-retry-behavior)
16. [Model pool configuration](#model-pool-configuration)
17. [Visualizing running and completed workflows](#visualizing-running-and-completed-workflows)
18. [Environment variable reference](#environment-variable-reference)
19. [Recipes: simple to complex](#recipes-simple-to-complex)
20. [The culminating example: code-test-review orchestration](#the-culminating-example-code-test-review-orchestration)
21. [Troubleshooting](#troubleshooting)

---

## Quick Reference: All Settings at a Glance

This is the full settings surface. Every flag, every environment variable, every default. Keep this section bookmarked.

### `slo run` — all flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--prompt` | `-p` | **required** | The prompt to execute. |
| `--json` | | `False` | Accepted for compatibility; currently a no-op. Stdout is always JSONL regardless of this flag — every line is a validated `AgentStreamEventDAO`. |
| `--model` | | `None` | Override the model for this run (e.g. `claude-sonnet-4-6`). Falls back to user preferences, then `cfg("DEFAULT_MODEL_NAME")`. |
| `--reasoning` | | `None` | Override the reasoning level: `off`, `minimal`, `low`, `medium`, `high`, `xhigh`. Clamped to the model's supported range. |
| `--cwd` | | `None` | Working directory. Defaults to `$PWD`. The agent uses this for all filesystem tools. |
| `--enable-history` | | `False` | Persist history to disk. Required for `--resume` to have anything to find. |
| `--resume` | | `None` | Resume a session by id or unique name. Implies `--enable-history`. |
| `--session-id` | | `None` | Explicit session id for this run (UUID4 or `[A-Za-z0-9._-]+` slug). Takes precedence over `SLO_SESSION_ID`. |
| `--workspace` | | `None` | Path to a VSCode `.code-workspace` file. Every declared folder contributes its `SLO.md` / `AGENTS.md` / `CLAUDE.md` to the system prompt. |
| `--system-prompt-file` | | `None` | Path to a file whose content **replaces** the default system prompt entirely. Use with care. |
| `--append-system-prompt-file` | | `None` | Path to a file whose content is **appended** to the default system prompt. Use for per-job injections. |
| `--orchestrator` / `--no-orchestrator` | | `False` | Attach a sub-agent pool before running. Enables the `spawn_sub_agents` tool. Also injects the default orchestrator system prompt when no custom `--system-prompt-file` is set. |
| `--system-prompt-b64` | | `None` | Base64-encoded system prompt override. Equivalent to `--system-prompt-file` but safe for multi-line text passed across a subprocess boundary. Decodes and replaces the session system prompt. |
| `--notify-session` | | `None` | Session id whose durable inbox receives workflow lifecycle notifications (`workflow_started`, per-phase updates, terminal synthesis). Set by `launch_workflow` when a TUI session detaches an orchestrator; without it, headless behaviour is byte-identical to before (no notifier, no inbox writes). |

### `slo visualize` — all flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--session` | `-s` | **required** | Session id or unique session name to inspect. |
| `--follow` / `--no-follow` | | `True` | Poll for live updates while the workflow is running. |
| `--refresh-seconds` | | `1.0` | Polling cadence in seconds. Lower for more responsive live view; raise for CI-attached monitoring. |
| `--tree-format` | | `textual` | Detail pane format: `textual`, `markdown`, `html`. |

### Session id resolution order for `slo run`

When a run starts, the session id is resolved in this order (first non-`None` wins):

1. `--resume <ref>` — resolved through the history store to a canonical UUID.
2. `--session-id <val>` — explicit literal value, validated.
3. `SLO_SESSION_ID` environment variable — validated on read.
4. Fresh `uuid4()` generated inside `SloAgentSession.build()`.

### Environment variables (complete list)

| Variable | Default | Description |
|----------|---------|-------------|
| `SLO_SESSION_ID` | — | Explicit session id, used when `--session-id` and `--resume` are both absent. |
| `SLO_HOME` | `~/.slo` | Root of all Slo data: history, preferences, logs, captures. |
| `SLO_MODEL_POOL` | — | JSON array of model pool entries. See [Model pool configuration](#model-pool-configuration). |
| `SLO_BASH_DEFAULT_TIMEOUT_SECONDS` | `1800` | Default bash tool timeout. Set to `0` to disable. |
| `SLO_BASH_TEARDOWN_GRACE_SECONDS` | `5` | Grace period to reap a killed process group. |
| `SLO_SUBAGENT_MAX_CONCURRENCY` | `4` | Maximum number of child sub-agent processes running simultaneously in a pool. |
| `SLO_SUBAGENT_MAX_TASKS` | `8` | Maximum tasks accepted per single `spawn_sub_agents` call. |
| `SLO_VISUALIZER_REFRESH_SECONDS` | `1.0` | Default polling cadence for `slo visualize`. Overridden by `--refresh-seconds`. |
| `SLO_OAUTH_TIMEOUT_SECONDS` | `60` | OAuth callback server timeout (loopback callback deadline; the attempt deadline is SLO_OAUTH_MANUAL_TIMEOUT_SECONDS). |
| `SLO_OAUTH_MANUAL_TIMEOUT_SECONDS` | `900` | Whole browser-authorization attempt deadline, including a pasted manual response. |
| `SLO_OAUTH_DEVICE_TIMEOUT_SECONDS` | `900` | Slo-owned OpenAI device-authorization attempt deadline. |
| `SLO_PROVIDER_STREAM_FIRST_PROGRESS_TIMEOUT_SECONDS` | `300` | Maximum wait for first provider-stream progress before one reconnect may be considered. |
| `SLO_PROVIDER_STREAM_IDLE_TIMEOUT_SECONDS` | `300` | Maximum gap between provider-stream progress events. |
| `SLO_PROVIDER_STREAM_RECONNECT_DELAY_SECONDS` | `1.0` | Base jittered delay for the single fresh-connection stream reconnect. |
| `SLO_PROVIDER_STREAM_CONTINUATION_MAX_ATTEMPTS` | `5` | Total TUI/headless submission attempts after a committed stream interruption. |
| `SLO_HEADLESS_HEARTBEAT_SECONDS` | `15` | Stderr-only `headless_status` cadence while a headless run is active. |
| `DEFAULT_MODEL_NAME` | provider default | Fallback model when no preference and no `--model`. |
| `ANTHROPIC_API_KEY` | — | Anthropic credential. |
| `KIMI_FOR_CODING_API_KEY` | — | Kimi For Coding credential. |
| `SLO_MODEL_CATALOG_OVERRIDES_FILE` | — | Optional operator overrides for the canonical model catalog. |

---

## Provider Stream Recovery and Heartbeats

A provider stream disconnection before **committed output** can receive one bounded
fresh-connection reconnect. A reconnect is a **new provider request**, not a
resumption of the broken HTTP stream. After text/thinking output or a tool call has
been committed, Slo does not automatically replay or switch provider mid-stream.
Instead, the session starts a new continuation turn, up to
`SLO_PROVIDER_STREAM_CONTINUATION_MAX_ATTEMPTS` total attempts. The continuation
instructs the agent to inspect the worktree and task artifacts before continuing,
so it does not blindly repeat a completed side effect. This common session path
applies to both the TUI and spawned headless sub-agents. A final terminal result
still carries a redacted failure envelope when available: `failure_code`,
`partial_output_committed`, `attempts`, and `safe_message`.

During a headless run, `HeadlessRunner` emits `headless_status` records from a
watchdog thread to stderr every `SLO_HEADLESS_HEARTBEAT_SECONDS`. Their payload
contains only `phase`, `last_event_age_seconds`, and `attempt`; never prompt
text, answers, headers, bodies, tokens, URLs, or raw transport errors. A valid
same-session heartbeat is advisory liveness telemetry: `healthy`, `degraded`,
and `silent` describe what operators can observe, but heartbeat age never
cancels a child. Ordinary stderr is diagnostic output, not a health signal.

### Durable workflow supervision files

A detached workflow keeps its durable evidence under
`$SLO_HOME/sessions/history/`. The TUI owns the workflow handle; each other
file has one dedicated writer:

```text
<owner-session>/workflows/wf-xxxx.json       # TUI-owned workflow handle
<orchestrator-session>/orchestrator.json     # HeadlessRunner status heartbeat
<orchestrator-session>/fleet.json            # SubAgentPool fleet snapshot
<orchestrator-session>/abort_request.json    # TUI abort request
<orchestrator-session>/children/<child>/status.json  # child terminal result
```

`SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` is the sole child-cancellation
authority. It measures child stdout inactivity; advisory heartbeat state never
shortens that budget. Cooperative abort and terminal cleanup use SIGTERM,
grace, SIGKILL, and reap, leaving no live child behind.

From the TUI, use `/workflows resume <workflow-id>` to relaunch a `stalled` or
`failed` workflow with its original orchestrator session history. The handle
immediately returns to `launching` with the new pid and becomes `running` after
the first fresh status heartbeat.

## Your First Headless Run

Install Slo from the public source (installation itself requires no `SLO_USERNAME`,
`SLO_TOKEN`, or other credentials):

```bash
curl -fsSL https://get-slo.sh/install.sh | bash
```

With `SLO_VERSION` unset, the installer uses the hosted/published `SLO_REF`.
`SLO_VERSION=dev` uses `main`; any other nonempty value is the ref to install
(tag or branch). Provider authentication is a separate runtime requirement.

Prerequisites:

- `slo` is on your `$PATH`.
- A credential is configured for the active provider. Check `~/.slo/global/authentication.json` or the relevant `*_API_KEY` environment variable.

Fire off a prompt:

```bash
slo run -p "What is the current date?"
```

That works. You will see something happen on stdout. But if you want to *use* that output in code, add `--json`:

```bash
slo run -p "What is the current date?" --json
```

Stdout is always JSONL. Every line is a validated `AgentStreamEventDAO` and the schema is the contract. `--json` is accepted for compatibility but is currently a no-op — the output format does not change with or without it.

Example output (abridged):

```jsonl
{"kind":"text_start","iteration":0,"block_id":"blk-0","delta":null}
{"kind":"text_delta","iteration":0,"block_id":"blk-0","delta":"The current date is "}
{"kind":"text_delta","iteration":0,"block_id":"blk-0","delta":"2026-07-02."}
{"kind":"text_end","iteration":0,"block_id":"blk-0","content":"The current date is 2026-07-02."}
{"kind":"run_completed","iteration":0,"content":"The current date is 2026-07-02."}
```

The last line is always a terminal event. `run_completed` means success. See [Exit codes](#exit-codes) for what the others mean.

---

## The `slo run` Command Reference

```text
slo run [OPTIONS]
```

### `--prompt` / `-p` (required)

The prompt text. There is no other way to pass a prompt to a headless run. If your prompt contains newlines or special characters, quote it properly:

```bash
slo run -p "Refactor the function in src/utils.py:45.
Keep the signature, improve the body, add a docstring." --json
```

For long prompts, read from a file:

```bash
slo run -p "$(cat my_prompt.txt)" --json
```

Or use a heredoc:

```bash
slo run -p "$(cat <<'EOF'
Read the test file at tests/unit/test_parser.py.
Identify every failing assertion and explain why it fails.
Do not fix anything — just diagnose.
EOF
)" --json
```

### `--json`

Accepted for backward compatibility; currently a no-op. Stdout is always a newline-delimited stream of `AgentStreamEventDAO` JSON objects — one per line, machine-parseable, pipeable through `jq`, stable across patch versions. The flag does not change the output format.

### `--model`

Override the model for this run. Accepts any model name that Slo knows about:

```bash
# Use Anthropic's most capable model
slo run -p "Design a database schema" --model claude-opus-4-7 --json

# Use a faster, cheaper model for simple tasks
slo run -p "Count the Python files" --model claude-sonnet-4-6 --json
```

The fallback chain when `--model` is absent:
1. `UserPreferencesStore` saved value (`~/.slo/global/preferences.json`)
2. `cfg("DEFAULT_MODEL_NAME")` — the `DEFAULT_MODEL_NAME` env var or the compile-time default

### `--reasoning`

Override the reasoning (extended thinking) level. The supported levels are:

| Level | What it does |
|-------|-------------|
| `off` | No extended thinking. Fastest and cheapest. |
| `minimal` | A brief internal planning pass. |
| `low` | Light reasoning. Good for simple code tasks. |
| `medium` | Balanced. Default for most models that support it. |
| `high` | Extended reasoning. Good for design, architecture, debugging. |
| `xhigh` | Maximum reasoning budget. Use sparingly — expensive. |

```bash
# Quick code task — no reasoning needed
slo run -p "Add a type hint to this function" --reasoning off --json

# Architecture work — use reasoning
slo run -p "Design the data model for a multi-tenant SaaS" --reasoning high --json
```

Reasoning level is clamped to the model's supported range. If you pass `xhigh` to a model that only supports up to `medium`, it runs at `medium` and logs a warning. `kimi-k3` is always-on reasoning: it supports `low`, `high`, and `xhigh`, mapping them to provider effort `low`, `high`, and `max`; `off` and `minimal` clamp to `low`, while `medium` clamps to `high`. The K2 coding models remain off-only.

### `--cwd`

Set the agent's working directory. Defaults to `$PWD`. The agent uses this for every filesystem tool: `read`, `write`, `edit`, `bash`, `grep`, `find`, `ls`.

```bash
# Run against a different project
slo run -p "Summarize the architecture" \
  --cwd ~/projects/my-api \
  --json > arch.jsonl
```

This is the headless equivalent of `slo ~/projects/my-api` in the TUI. The agent will read and write files relative to this path.

### `--enable-history`

Headless runs do not persist history by default. This is a deliberate choice: most headless invocations are stateless sub-agents that produce a result, exit, and have nothing useful to resume. Storing history for all of them would fill your disk with ephemera.

Pass `--enable-history` when you need:
- A permanent audit trail (CI, compliance, post-mortems).
- The ability to resume the session later with `--resume`.
- Consistent session metadata for an orchestrated multi-step workflow.

```bash
slo run -p "Analyze the codebase" \
  --enable-history \
  --json
```

History is stored at `$SLO_HOME/sessions/history/<session_id>/` by the default
`TreeBasedFileSystemSessionHistoryStore`:

```
~/.slo/sessions/history/<session_id>/
├── session.json       # metadata: id, name, model, workdir, timestamps
├── tree.json          # authoritative turn-grouped event history
└── transcript.md      # human-readable derived transcript
```

The legacy `FilesystemSessionHistoryStore` uses `events.jsonl` instead of
`tree.json` only when it is explicitly selected.

### `--resume`

Resume a previously persisted session. Accepts a session UUID or a unique session name:

```bash
slo run -p "Continue the refactoring" --resume a1b2c3d4 --json
slo run -p "Continue the refactoring" --resume "my-session-name" --json
```

`--resume` automatically implies `--enable-history`. You do not need to pass both.

The resume reference is resolved through `FilesystemSessionHistoryStore.resolve_session_reference()`, which handles both exact UUIDs and unique session names. If the name is ambiguous (more than one session matches), you get an error and should use the full UUID.

### `--session-id`

Assign an explicit session id to this run. Accepts a UUID4 or a slug matching `[A-Za-z0-9._-]+`:

```bash
# Use a human-readable slug
slo run -p "Compile the project" \
  --session-id "build-phase-1" \
  --enable-history \
  --json

# Use a generated UUID
slo run -p "Run the tests" \
  --session-id "$(uuidgen | tr '[:upper:]' '[:lower:]')" \
  --enable-history \
  --json
```

This is the explicit form. The environment-variable form `SLO_SESSION_ID` works identically but is set in the environment rather than per-command. Both are validated on read; an invalid value is an error, not a silent fallback.

`--session-id` takes precedence over `SLO_SESSION_ID`.

### `--workspace`

Path to a VSCode `.code-workspace` file. When provided, every folder declared in the workspace contributes its `SLO.md`, `AGENTS.md`, and `CLAUDE.md` files to the system prompt as additional context:

```bash
slo run -p "What components does this project have?" \
  --workspace ~/projects/my-monorepo.code-workspace \
  --json
```

This is the same workspace resolution as the TUI. For monorepos with multiple sub-packages, each package can maintain its own `AGENTS.md` that describes its conventions, and all of them will be visible to the agent.

### `--system-prompt-file`

Completely replace the default system prompt with the contents of a file:

```bash
slo run -p "Summarize this codebase" \
  --system-prompt-file custom_prompt.txt \
  --json
```

The default system prompt is the large, carefully-crafted instruction set that tells Slo how to behave as a coding agent — the coding conventions, the tool descriptions, the safety rules. Replacing it means you are on your own. The agent will still have its tools, but none of the default guidance.

Use this when:
- You are building a specialized agent with entirely different instructions.
- You are testing the base model behaviour without Slo's opinions.
- You know exactly what you are doing.

Do not use this for minor tweaks. Use `--append-system-prompt-file` instead.

### `--append-system-prompt-file`

Append text to the default system prompt without replacing it:

```bash
slo run -p "Review the API changes" \
  --append-system-prompt-file project_context.txt \
  --json
```

The appended text is added *after* the full default system prompt. This is the right tool for:
- Per-job context injection (e.g., "this run is part of PR #123, the target branch is `main`").
- Project-specific conventions that are not in `AGENTS.md`.
- Temporary overrides during a specific phase of work.

The `--system-prompt-file` and `--append-system-prompt-file` flags are mutually exclusive in their effect: you can pass both, but the file contents are applied as described — replace first, then append to whatever is current.

### `--orchestrator` / `--no-orchestrator`

Boot the agent with a sub-agent pool attached. This injects the `spawn_sub_agents` tool into the agent's tool bundle, allowing the agent to delegate tasks to child processes.

Without this flag, `spawn_sub_agents` is not available, and any prompt that tries to use it will either fail or simply not trigger the tool.

```bash
# Run as an orchestrator that can spawn sub-agents
slo run -p "Fan out: review every file in src/, one agent per file." \
  --orchestrator \
  --enable-history \
  --json
```

See [Orchestrator mode and sub-agents](#orchestrator-mode-and-sub-agents) for the full picture.

---

## The `slo visualize` Command Reference

```text
slo visualize [OPTIONS]
```

`slo visualize` is a read-only Textual TUI for inspecting a headless orchestrator workflow — live or after the fact. It shows you the child (sub-agent) sessions spawned by an orchestrator run, their lifecycle state, and the transcript of whichever child you select.

It does not interfere with the running workflow. It reads from the history store and child capture files. You can open it while the orchestrator is still running, watch it update in real time, and close it without affecting anything.

### `--session` / `-s` (required)

The session id or unique session name of the **parent orchestrator session** to inspect:

```bash
slo visualize --session a1b2c3d4
slo visualize -s "my-orchestration-run"
```

### `--follow` / `--no-follow`

When `--follow` (the default), the visualizer polls for new data at the `--refresh-seconds` cadence and updates both panes. Polling stops automatically when the parent session reaches a terminal state (`run_completed`, `run_failed`, `run_aborted`).

When `--no-follow`, the visualizer loads the current state once and does not refresh:

```bash
# Inspect a completed workflow (no polling needed)
slo visualize --session a1b2c3d4 --no-follow

# Watch a running workflow live
slo visualize --session a1b2c3d4 --follow
```

### `--refresh-seconds`

How often to reload the workflow data when `--follow` is active. Default is `1.0` second. For a long-running orchestration you might raise this to 5 or 10 seconds to reduce file I/O:

```bash
slo visualize --session a1b2c3d4 --refresh-seconds 5.0
```

You can also set the default globally with `SLO_VISUALIZER_REFRESH_SECONDS`:

```bash
export SLO_VISUALIZER_REFRESH_SECONDS=5.0
slo visualize --session a1b2c3d4
```

### `--tree-format`

Controls the right-pane detail view. Three formats are available:

| Value | Description |
|-------|-------------|
| `textual` | (default) Inline transcript rendering with Rich markup. Readable in the TUI. |
| `markdown` | Transcript rendered as markdown. Useful if you want to copy-paste the output. |
| `html` | HTML rendering. Currently identical layout; useful for future export. |

```bash
slo visualize --session a1b2c3d4 --tree-format markdown
```

### Keyboard bindings in the visualizer

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate the sub-agent list. |
| `Enter` | Select a sub-agent and load its transcript. |
| `r` | Force an immediate refresh. |
| `f` | Toggle follow mode on/off. |
| `q` | Quit. |

### What the visualizer shows

The left pane lists every discovered sub-agent session. Each row shows:
- A status icon: `⏳` running, `✓` completed, `✗` failed, `⊘` aborted, `◌` pending.
- The first 8 characters of the child session id.
- The pool task id (first 8 chars) if one is known.

The right pane shows the selected child's canonical history: user messages,
assistant answers, tool calls, tool results, and reasoning. Pool-spawned
children always receive the pool-assigned `--session-id` and `--enable-history`,
so this projection always has durable child history. Their appended
`stdout.jsonl` capture remains diagnostic evidence for live tailing and
post-mortem inspection; it is not the normal substitute for pool-child history.

The status bar at the bottom shows:
- Parent session id (first 8 chars)
- Workflow state (`running` or `complete`)
- Child count
- Follow mode
- Last refresh timestamp

---

## Streaming Output: JSONL Event Structure

When `--json` is used, every stdout line is a single JSON object conforming to `AgentStreamEventDAO` (`src/agents/slo_agent/events/stream.py`).

### Common fields

| Field | Type | Meaning |
|-------|------|---------|
| `kind` | `string` | The event discriminator. Exhaustive list below. |
| `iteration` | `int` | Outer ReAct iteration number (starts at 0). |
| `block_id` | `string\|null` | Stable identifier for a text/thinking/tool-call block. Delta events for the same block share the same `block_id`. |
| `content_index` | `int` | Provider content-block index within the response chunk. |
| `delta` | `string\|null` | Incremental text for `*_delta` events. |
| `content` | `string\|null` | Full or terminal content for `*_end` and `run_*` events. |
| `tool_name` | `string\|null` | Tool name for `tool_call_*` and `tool_result` events. |
| `tool_call_id` | `string\|null` | Stable tool call identifier. |
| `tool_input` | `object\|null` | Best-effort parsed tool arguments for finalized tool-call events. |
| `tool_arguments_delta` | `string\|null` | Partial JSON argument fragment for streaming tool-call events. |
| `redacted` | `bool` | True when the provider surfaced only a redacted reasoning marker. |
| `metadata` | `object` | Small debug metadata. `metadata.wait_seconds` is set on `run_retrying`. |

### Event kinds: what you will see

#### Thinking blocks
These are the model's internal reasoning. They appear when `reasoning` is not `off`.

| Kind | Meaning |
|------|---------|
| `thinking_start` | Reasoning block opened. |
| `thinking_delta` | Chunk of reasoning text. |
| `thinking_end` | Reasoning block closed; `content` has the full text. |

#### Text blocks
These are the model's visible answer.

| Kind | Meaning |
|------|---------|
| `text_start` | Answer text block opened. |
| `text_delta` | Chunk of answer text. |
| `text_end` | Text block closed; `content` has the full text. |

#### Tool calls
These are the model's requests to run a tool.

| Kind | Meaning |
|------|---------|
| `tool_call_start` | Model started constructing a tool call. `tool_name` is set. |
| `tool_call_delta` | Partial tool-call argument JSON fragment. |
| `tool_call_end` | Tool call finalized. `tool_input` has the parsed arguments. |
| `tool_result` | The tool returned. `content` has the result. |

#### Terminal events
Every run ends with exactly one of these.

| Kind | Meaning |
|------|---------|
| `run_completed` | Success. |
| `run_aborted` | Aborted (SIGINT, orchestrator cancel, etc.). |
| `run_failed` | Failure. `content` may have the reason. |

#### Lifecycle and audit events

| Kind | Meaning |
|------|---------|
| `run_retrying` | Rate-limit or transient error; `metadata.wait_seconds` has the backoff. |
| `steering_applied` | A queued `/steer` message was drained into model context. |
| `compaction_started` | Forced context compaction began. |
| `compaction_completed` | Compaction succeeded. |
| `compaction_failed` | Compaction failed; the original error will follow. |
| `compaction_retrying` | Compaction succeeded; the original prompt is being retried. |
| `compaction_advised` | Snapshot crossed the 256k advisory threshold; display-only, asks the user to run `/compact`. |
| `recovery_started` | LLM-driven error recovery began (feature 50). |
| `recovery_succeeded` | A recovery iteration produced a completed turn. |
| `recovery_exhausted` | Recovery budget exhausted; `run_failed` follows. |

#### Sub-agent lifecycle events (orchestrator runs)

| Kind | Meaning |
|------|---------|
| `sub_agent_spawned` | The pool created a child agent process. |
| `sub_agent_completed` | A child finished with exit 0. |
| `sub_agent_failed` | A child failed, aborted, or crashed. |

---

## Capturing stdout and stderr

### Simple capture

```bash
slo run -p "List the Python files in src/" --json > output.jsonl
```

The final line of `output.jsonl` is always the terminal event.

### Separate stdout and stderr

```bash
slo run -p "Refactor utils.py" --json > output.jsonl 2> run.log
```

Stderr carries structured lifecycle JSONL (`HeadlessLifecycleEventDAO`) — one JSON object per line with fields `kind`, `session_id`, `message`, `payload`, and `timestamp_utc`. Lifecycle kinds: `headless_session_started`, `headless_session_resolved`, `headless_orchestrator_attached`, `headless_run_completed`, `headless_run_failed`, `headless_run_aborted`, `headless_child_stderr`. The stdout JSONL stream (`AgentStreamEventDAO`) and the stderr lifecycle stream are therefore both structured and independently parseable.

### Process the stream live in Python

```python
import json
import subprocess

proc = subprocess.Popen(
    ["slo", "run", "-p", "Analyze src/", "--json"],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
)

answer_parts = []

for line in proc.stdout:
    event = json.loads(line.strip())
    if event["kind"] == "text_delta" and event.get("delta"):
        print(event["delta"], end="", flush=True)
        answer_parts.append(event["delta"])
    elif event["kind"] == "tool_call_end":
        print(f"\n[tool: {event['tool_name']}({event.get('tool_input')})]\n")
    elif event["kind"] in {"run_completed", "run_aborted", "run_failed"}:
        print(f"\n\nTerminal: {event['kind']}")

proc.wait()
full_answer = "".join(answer_parts)
print(f"\nExit code: {proc.returncode}")
```

### Extract the final answer with jq

```bash
slo run -p "What is the capital of France?" --json \
  | jq -r 'select(.kind == "run_completed") | .content'
```

### Stream deltas to a terminal in real time

```bash
slo run -p "Write a haiku about Python" --json \
  | jq -j 'select(.kind == "text_delta") | .delta'
```

### Count tool calls by name

```bash
slo run -p "Refactor utils.py" --json \
  | jq -r 'select(.kind == "tool_call_end") | .tool_name' \
  | sort | uniq -c | sort -rn
```

---

## Exit Codes

`slo run` maps the terminal event to a POSIX exit code:

| Terminal event | Exit code | Meaning |
|----------------|-----------|---------|
| `run_completed` | `0` | Success. |
| `run_aborted` | `2` | Aborted (SIGINT, `timeout`, orchestrator cancel). |
| `run_failed` | `1` | Failure or any other terminal state. |

```bash
slo run -p "Run the linter" --json > lint.jsonl
case $? in
  0) echo "Linter passed." ;;
  1) echo "Linter failed or agent errored." ;;
  2) echo "Run was aborted." ;;
esac
```

---

## Enabling and Using History

This is where things get interesting. Headless runs without history are fire-and-forget — fast, cheap, leave no trace. Headless runs *with* history are persistent actors: they accumulate a conversation, can be resumed, and can be inspected after the fact.

### Persist a run to disk

```bash
slo run -p "Analyze the codebase" --enable-history --json
```

The session id appears in stderr at startup:

```
{"msg": "session_built", "session_id": "a1b2c3d4-...", "workdir": "/home/user/project"}
```

History is stored at `$SLO_HOME/sessions/history/<session_id>/` by the default
`TreeBasedFileSystemSessionHistoryStore`:

```
~/.slo/sessions/history/a1b2c3d4-1234-5678-abcd-ef0123456789/
├── session.json       # metadata: id, name, model, workdir, created_at, updated_at
├── tree.json          # authoritative turn-grouped event history
└── transcript.md      # human-readable derived transcript (generated on demand)
```

The legacy `FilesystemSessionHistoryStore` uses `events.jsonl` in place of
`tree.json` only when explicitly selected.

### Inspect the history directly

```bash
# List all sessions
ls ~/.slo/sessions/history/

# View session metadata
cat ~/.slo/sessions/history/<session_id>/session.json

# View the default authoritative turn-grouped history
jq . ~/.slo/sessions/history/<session_id>/tree.json

# Legacy flat-history stores expose events.jsonl when explicitly selected
jq -r '.kind' ~/.slo/sessions/history/<session_id>/events.jsonl | sort | uniq -c
```

### Why enable history?

You should enable history when:
- You want to resume the same conversation in a later step.
- You want a permanent audit trail for a CI job (useful for post-mortems).
- You are running as an orchestrator (the visualizer reads from this store).
- You want to inspect what the agent actually did, step by step.

You should skip history when:
- This is a stateless sub-agent that fires and forgets (the default for orchestrator children).
- You are running many parallel agents and do not want the I/O overhead.
- The result is captured on stdout and that is all you need.

---

## Resuming Sessions

Two mechanisms. Both work the same way under the hood.

### `--resume` flag

Pass a session id (UUID) or unique session name to resume:

```bash
# First run — save the session id from stderr
slo run -p "Read the README and identify the tech stack" \
  --enable-history \
  --json > step1.jsonl

# Resume with the session id
slo run -p "Now look at the test suite and describe the testing strategy" \
  --resume a1b2c3d4 \
  --json > step2.jsonl
```

The resumed session has the full conversation history from the previous invocations. The agent can reference what it said and did before. This is the same history threading as the TUI — the only difference is that input comes from `--prompt` rather than from a text box.

### `SLO_SESSION_ID` environment variable

This is the CI-friendly form. Set it once and every subsequent `slo run` in the same shell (or CI step) shares the same session:

```bash
export SLO_SESSION_ID="analysis-$(git rev-parse --short HEAD)"

slo run -p "What does this branch change?" --enable-history --json > changes.jsonl
slo run -p "Are there any obvious bugs in the changes?" --enable-history --json > bugs.jsonl
slo run -p "Write a PR description based on the changes and the bug analysis." --enable-history --json > pr_desc.jsonl
```

### The resolution order matters

| Priority | Source | Notes |
|----------|--------|-------|
| 1 (highest) | `--resume <ref>` | Resolved to UUID via the history store. |
| 2 | `--session-id <val>` | Explicit literal, validated. |
| 3 | `SLO_SESSION_ID` env var | Validated on read. |
| 4 (lowest) | Fresh `uuid4()` | Generated inside `SloAgentSession.build()` if everything else is absent. |

If you pass `--resume` and also have `SLO_SESSION_ID` set, `--resume` wins. If you pass `--session-id` and also have `SLO_SESSION_ID` set, `--session-id` wins. There is no ambiguity.

### Important notes on session continuity

- `--enable-history` must be set on every invocation you want to persist. There is no "always-on" mode.
- `--resume` implies `--enable-history`. You do not need to pass both.
- If you resume a session that does not exist (e.g., the history directory was deleted), you get an error.
- Session names are assigned by the agent during the first run and stored in `session.json`. They are human-readable but not guaranteed to be unique — use the UUID for programmatic resume.

---

## Working Directory Scoping

The agent operates relative to a working directory. Everything it reads, writes, edits, or executes is under this root. Getting this wrong is the leading cause of an agent confidently doing nothing useful.

```bash
# Defaults to $PWD
slo run -p "List the files in src/" --json

# Explicit path
slo run -p "List the files in src/" \
  --cwd /home/user/my-project \
  --json

# Relative path is resolved to absolute before the run starts
slo run -p "List the files in src/" \
  --cwd ../my-project \
  --json
```

### Working directories and orchestrated sub-agents

In an orchestrated workflow, the orchestrator session has a working directory. Sub-agents inherit their working directory from the task definition — the orchestrator sets `cwd` per task, so different agents can operate on different parts of a monorepo simultaneously.

This is intentional: an orchestrator reviewing a frontend and a backend in parallel should not have both agents tripping over the same relative paths.

---

## Model and Reasoning Overrides

### Override the model for one run

```bash
slo run -p "Refactor this function" --model claude-sonnet-4-6 --json
slo run -p "Count the imports"      --model gpt-5.4 --json
```

Models that Slo knows about are defined in the canonical model catalog
(`src/agents/model_catalog/`), projected through `config/ai_model_config.py`
and `src/auth/provider_for_model.py`. The first-class lineup includes
Anthropic Claude variants, OpenAI GPT-5.x and Codex variants, and Kimi For
Coding models. Legacy `moonshot-*` aliases continue to resolve for backward
compatibility. A model name that Slo does not recognize will fail at session
build time.

### Override the reasoning level

```bash
# Turn reasoning off for simple, fast tasks
slo run -p "Format this JSON" --reasoning off --json

# Maximum reasoning for complex design work
slo run -p "Design the caching strategy for this system" --reasoning xhigh --json
```

Reasoning profiles determine the active level per model. `kimi-k3` always reasons: `off` and `minimal` clamp to `low`, `medium` clamps to `high`, and canonical `xhigh` maps to provider effort `max`. `kimi-for-coding` and `kimi-for-coding-highspeed` remain off-only; they do not receive a provider reasoning field.

### Using the model pool

The `SLO_MODEL_POOL` environment variable configures a multi-model fallback pool. When a pool is active, the session builds a `ModelPool` instead of a single model. On a provider error (credit exhaustion, rate limit, 5xx), the pool cools the failed entry and retries the same request on the next available entry.

```bash
export SLO_MODEL_POOL='[
  {
    "model_name": "claude-sonnet-4-6",
    "provider": "anthropic",
    "priority": 1,
    "cooldown_seconds": 300,
    "rate_limit_cooldown_seconds": 30
  },
  {
    "model_name": "kimi-for-coding",
    "provider": "kimi_for_coding",
    "priority": 2,
    "cooldown_seconds": 600,
    "rate_limit_cooldown_seconds": 60
  }
]'
```

---

## System Prompt Overrides

This is for the specialist case, not the common case. The default Slo system prompt is large, opinionated, and covers the majority of coding workflows. Touch these flags when you know you need to.

### Replacing the system prompt entirely

```bash
slo run -p "Translate this text to French." \
  --system-prompt-file prompts/translation_agent.txt \
  --json
```

`translation_agent.txt` becomes the entire system prompt. Slo's default coding instructions are gone. The agent still has its tools; it just has different instructions for how to use them.

### Appending context without replacing

This is the more common and safer operation. Use it to inject per-run context:

```bash
# Create a context file for this CI run
cat > /tmp/ci_context.txt << EOF
This run is part of pull request #456 by @alice.
Target branch: main. Source branch: feature/oauth-rewrite.
Focus on security implications of the auth changes.
EOF

slo run -p "Review the changes in this pull request" \
  --append-system-prompt-file /tmp/ci_context.txt \
  --cwd ~/projects/my-api \
  --json > review.jsonl
```

The appended text sits after the full default system prompt. The agent gets all of its default guidance plus your additions.

---

## Orchestrator Mode and Sub-Agents

This is the interesting part. Skip to it if you have been patient enough with the basics.

### What orchestrator mode is

When you pass `--orchestrator`, Slo does two things before the run starts:

1. Builds a normal `SloAgentSession`.
2. Attaches a `SubAgentPool` to it, which injects the `spawn_sub_agents` tool.

With `spawn_sub_agents` available, the agent can issue structured requests to fan out work to child processes. Each child is a fresh `slo run` invocation — a separate process, a separate session, a separate model call — running in parallel up to the pool's concurrency limit (`SLO_SUBAGENT_MAX_CONCURRENCY`, default `4`).

### What the orchestrator sees

The orchestrator receives `sub_agent_spawned`, `sub_agent_completed`, `sub_agent_failed`, and `sub_agent_aborted` events as its children progress. These appear in the orchestrator's own stdout JSONL stream:

```jsonl
{"kind":"sub_agent_spawned","iteration":0,"sub_agent_id":"child-uuid","task_id":"task-1","content":"Do step 1.","delta":null}
{"kind":"sub_agent_spawned","iteration":0,"sub_agent_id":"child-uuid2","task_id":"task-2","content":"Do step 2.","delta":null}
{"kind":"sub_agent_completed","iteration":0,"sub_agent_id":"child-uuid","task_id":"task-1","content":null,"delta":null}
```

Note: the event fields are top-level (`sub_agent_id`, `task_id`, `content`) — not nested under `metadata`.

### What the child captures

Each child's stdout is captured to:

```
$SLO_HOME/sessions/history/<parent_session_id>/children/<child_session_id>/stdout.jsonl
```

And stderr to:

```
$SLO_HOME/sessions/history/<parent_session_id>/children/<child_session_id>/stderr.jsonl
```

Pool-spawned children always have their own canonical history entry. The
captures persist as diagnostic evidence and can be inspected directly.

### Pool configuration via environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `SLO_SUBAGENT_MAX_CONCURRENCY` | `4` | Maximum number of sub-agents running simultaneously. |
| `SLO_SUBAGENT_MAX_TASKS` | `8` | Maximum tasks accepted per single `spawn_sub_agents` call. |

```bash
# Run up to 8 sub-agents in parallel
SLO_SUBAGENT_MAX_CONCURRENCY=8 \
  slo run -p "Review every file in src/ independently" \
  --orchestrator --enable-history --json
```

### The canonical orchestrator pattern

An orchestrator prompt typically looks like this:

```
You have access to the spawn_sub_agents tool.

Your job is to:
1. Identify the N units of work to do in parallel.
2. Spawn one sub-agent per unit with a precise, self-contained prompt.
3. Wait for all sub-agents to complete.
4. Synthesize the results into a final answer.

The units of work for this run are: [...]
```

The orchestrator does not do the work itself — it designs and delegates. The sub-agents do the work and return results through the `spawn_sub_agents` tool's response. The orchestrator then synthesizes.

---

## Default Orchestrator Prompt

When you launch a headless orchestrator with `--orchestrator` and do **not** supply a `--system-prompt-file`, Slo automatically injects `DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT` into the session. This is a built-in, fully-specified identity prompt that turns a blank coding agent into a capable orchestration agent without requiring you to explain the role yourself.

### What the default prompt covers

The injected prompt gives the orchestrator:

| Capability | What it tells the orchestrator |
|------------|-------------------------------|
| **Role identity** | You are an orchestrator. You decompose, delegate, and synthesize — you do not do the bulk work yourself. |
| **When to spawn** | Only when the user explicitly asks for parallel/concurrent execution. Treat `dynamic workflows` / `dyanmic workflows` (no detach qualifier) as that same explicit request — runs in-session via spawn_sub_agents (sync dynamic workflow). A detach-qualified request ("headless dynamic workflows", "detached dynamic workflows", "independent dynamic workflows", or detach wording "in the background" / "without blocking") routes to launch_workflow instead. A detached orchestrator never calls launch_workflow. Never spawns on its own initiative. |
| **Task decomposition** | How to break a request into self-contained sub-tasks. Each sub-task prompt must be stand-alone: no pronouns, no references to "the previous step", no assumed context. |
| **Chain mode** | For sequential chains, the `{previous}` placeholder substitutes the previous sub-agent's answer into the next prompt. |
| **Retry policy** | If a sub-agent fails or is aborted, retry once with corrected parameters (e.g., relaxed timeout, narrower scope). |
| **Result synthesis** | After all tasks complete, collect every `answer` field, merge into a single coherent response, and never dump raw JSON at the user. |
| **Named Slo workflows** | When the user mentions a workflow (e.g., "use the code-test-review workflow"), read the workflow file from `skills/design-and-analysis/workflows/<name>.md`, enumerate its phases, build self-contained per-phase prompts, and dispatch them in the correct order. |
| **Oversight** | The orchestrator is the oversight layer. If a phase aborts or crashes unexpectedly, retry it once with updated configuration. |

### What this means in practice

Before this prompt existed, you had to write a large orchestrator brief in your prompt — describing the role, the phases, how to decompose work, what to do with results. Now you do not. The orchestrator already knows all of that.

**Old approach** — manually instruct the orchestrator:

```bash
slo run -p "$(cat <<'EOF'
You are an orchestration agent. Your job is to fan out work to sub-agents.
When given a task, identify independent units, spawn one sub-agent per unit,
wait for all of them, and synthesize the results into a final answer.

Today's task: review every Python file in src/ for code quality issues.
Spawn one sub-agent per file, each with the prompt:
  "Review <file> for code quality: naming, complexity, docstrings, type hints."
When all complete, write a summary table with one row per file.
EOF
)" \
  --orchestrator --enable-history --json
```

**New approach** — just describe the task:

```bash
slo run -p "Review every Python file in src/ for code quality. Use one sub-agent per file. Produce a summary table when done." \
  --orchestrator --enable-history --json
```

The orchestrator understands its own role. Your prompt describes the *task*, not the *procedure*.

### Invoking a named Slo workflow

The most powerful application of the default prompt is driving named Slo workflows. The orchestrator knows the workflow protocol: read the workflow file, extract your context, construct self-contained per-phase prompts, dispatch phases in order, handle verdicts, synthesize. The phrases `dynamic workflows` and `dyanmic workflows` **without a detach qualifier** are treated as an explicit request to run the workflow in the current session via `spawn_sub_agents` (sync dynamic workflow). To detach the workflow as a headless orchestrator process, add a detach qualifier — the word "headless", "detached", or "independent" applied to the request (e.g., "headless dynamic workflows", "detached dynamic workflows"), or detach wording such as "in the background" or "without blocking". Only a detach-qualified request routes to `launch_workflow`; a detached orchestrator never calls `launch_workflow`.

```bash
# Choose a human-readable session id
SESSION="feat-42-$(date +%Y%m%d-%H%M%S)"

# Write the user context to a file for clarity
cat > /tmp/feat42_context.txt << 'EOF'
Use the code-test-review workflow to implement the feature described in:
  /Users/siddharth/Code/myproject/specs/42-user-notifications/overview.md

Repository root: /Users/siddharth/Code/myproject/src
Current branch: feature/42-user-notifications (already checked out)
Git user email: you@example.com

When all phases are done, output:
WORKFLOW COMPLETE.
Branch: feature/42-user-notifications
Tests: all passing
EOF

# Start the orchestrator — no custom system prompt needed
python -m src.cli run \
  -p "$(cat /tmp/feat42_context.txt)" \
  --orchestrator \
  --enable-history \
  --session-id "$SESSION" \
  --cwd /Users/siddharth/Code/myproject/src \
  --model claude-sonnet-4-6 \
  --json > "$SESSION.jsonl" 2> "$SESSION.err" &

echo "Orchestrator PID: $!"
echo "Session: $SESSION"
echo ""
echo "Watch live with:"
echo "  python -m src.cli visualize --session $SESSION --follow"
```

In a second terminal, watch the sub-agents appear:

```bash
python -m src.cli visualize --session "$SESSION" --follow --refresh-seconds 2
```

Wait for completion and extract the synthesis:

```bash
wait
jq -r 'select(.kind == "run_completed") | .content' "$SESSION.jsonl"
```

### Avoiding the main-stream inactivity timeout

The orchestrator's own LLM stream (not its sub-agents) is guarded by a 10800-second inactivity timeout. If the orchestrator makes a long LLM call while reading workflow files, running git commands, or synthesizing results, this can still fire when operators override it downward.

For complex workflows, raise it before starting the orchestrator:

```bash
export SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800  # shipped default; 3 hours
```

The sub-agent child processes have their own separate guard, `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS`, which defaults to 7200 seconds. The two are independent:

| Variable | Default | Guards |
|----------|---------|--------|
| `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` | `10800` | The orchestrator's **own** LLM event stream. |
| `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` | `7200` | Each **child sub-agent** process's stdout pipe. |

Typical production invocation for a long workflow:

```bash
SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800 \
SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS=7200 \
SLO_SUBAGENT_MAX_CONCURRENCY=6 \
python -m src.cli run \
  -p "$(cat /tmp/workflow_prompt.txt)" \
  --orchestrator \
  --enable-history \
  --session-id "$(date +%Y%m%d-%H%M%S)-my-workflow" \
  --cwd /path/to/project \
  --json > workflow.jsonl 2> workflow.err
```

### Overriding the default prompt

To replace the default orchestrator identity with your own:

```bash
python -m src.cli run \
  -p "Your task prompt here." \
  --orchestrator \
  --system-prompt-file /path/to/custom_orchestrator.txt \
  --json
```

To append project-specific context on top of the default identity:

```bash
python -m src.cli run \
  -p "Your task prompt here." \
  --orchestrator \
  --append-system-prompt-file /path/to/project_context.txt \
  --json
```

The `--system-prompt-file` flag replaces the default entirely. The `--append-system-prompt-file` flag keeps it and adds more.

### Passing a system prompt across a subprocess boundary

Sub-agents spawned by the orchestrator can receive their own system prompt. The orchestrator encodes it as base64 and passes `--system-prompt-b64` to the child `slo run` invocation. You can also use this flag directly from the shell when the prompt contains newlines or special characters that would break shell quoting:

```bash
PROMPT=$(cat /path/to/custom_prompt.txt | base64)

python -m src.cli run \
  -p "Analyze the codebase." \
  --system-prompt-b64 "$PROMPT" \
  --json
```

---

## Timeouts and Retry Behavior

Everything that can block, can be bounded. Here is the complete picture.

### Bash tool timeout

The `bash` tool defaults to a **600-second** (10-minute) timeout per command. A command that exceeds this is sent `SIGKILL` and the tool returns an error message.

```bash
# Raise the default ceiling
export SLO_BASH_DEFAULT_TIMEOUT_SECONDS=1200

# Disable the ceiling entirely (dangerous — commands can run forever)
export SLO_BASH_DEFAULT_TIMEOUT_SECONDS=0

# Lower the ceiling (good for untrusted code review tasks)
export SLO_BASH_DEFAULT_TIMEOUT_SECONDS=30
```

The grace period for reaping the killed process group:

```bash
export SLO_BASH_TEARDOWN_GRACE_SECONDS=10  # default is 5
```

The model can also pass an explicit `timeout` argument to the `bash` tool for a single invocation. This overrides the default ceiling for that call only.

### Wall-clock timeout via `timeout`

For a hard limit around the entire `slo run` invocation:

```bash
timeout 300 slo run -p "Long analysis task" --json > output.jsonl
```

On `SIGTERM`, Slo aborts the current iteration and exits with `run_aborted` (exit code `2`). Add `-k 15` to send `SIGKILL` 15 seconds after `SIGTERM` if the process does not exit cleanly:

```bash
timeout -k 15 300 slo run -p "Very long task" --json > output.jsonl
```

### SDK-level retries

`LLMFactory.create` passes `max_retries=3` to the underlying LangChain provider. This handles transient network failures. For Kimi For Coding, `max_retries=0` so that rate-limit errors surface immediately to the model pool.

These are not configurable via environment variable. Edit `src/agents/base.py` if you need to change the default; use a `ModelPool` if you need provider-level fallback without touching code.

---

## Model Pool Configuration

The model pool is the production-grade answer to provider flakiness. It is overkill for simple scripts and essential for long-running orchestrations.

### Basic configuration

`SLO_MODEL_POOL` is a JSON array. Each entry is a model pool entry:

```json
[
  {
    "model_name": "claude-sonnet-4-6",
    "provider": "anthropic",
    "priority": 1,
    "cooldown_seconds": 300,
    "rate_limit_cooldown_seconds": 30
  },
  {
    "model_name": "kimi-for-coding",
    "provider": "kimi_for_coding",
    "priority": 2,
    "cooldown_seconds": 600,
    "rate_limit_cooldown_seconds": 60
  }
]
```

### Pool entry fields

| Field | Default | Meaning |
|-------|---------|---------|
| `model_name` | *required* | Model identifier, must be recognized by the canonical model catalog. |
| `provider` | *required* | Provider key (`anthropic`, `openai`, `kimi_for_coding`). |
| `priority` | `0` | Routing order; lower values are tried first. |
| `cooldown_seconds` | `300` | Ban duration after credit exhaustion or a non-rate-limit switchable error. |
| `rate_limit_cooldown_seconds` | `60` | Shorter ban after a 429, 500, 502, 503, or 529. |

### How the pool behaves

1. The request goes to the highest-priority non-cooled entry.
2. If it fails with a switchable error (credit exhaustion, rate limit, 5xx), that entry is cooled for the configured duration.
3. The request is immediately retried on the next available entry.
4. If all entries are cooled, the pool waits for the shortest cooldown to expire and retries.
5. `run_retrying` events are emitted on every retry; `metadata.wait_seconds` is set.

### Setting the pool via user preferences

If you do not want to export `SLO_MODEL_POOL` on every shell, you can set the pool as a user preference. Run the TUI, open preferences, and set `default_model_pool`. It is stored in `~/.slo/global/preferences.json`.

---

## Visualizing Running and Completed Workflows

You have started an orchestrator run. It is spawning sub-agents. You want to watch.

### Launch the visualizer against a running session

```bash
# In terminal 1: start the orchestrator
slo run -p "Fan out: review every module in src/" \
  --orchestrator \
  --enable-history \
  --session-id "review-2026-07-02" \
  --json > orchestrator.jsonl &

# In terminal 2: open the visualizer immediately
slo visualize --session "review-2026-07-02" --follow
```

The visualizer polls the history store and child capture directories. As sub-agents are spawned, their entries appear in the left pane. Select one with the arrow keys to see its transcript on the right. The status bar updates on every refresh.

### Watch a completed workflow after the fact

```bash
# The run already finished — no polling needed
slo visualize --session "review-2026-07-02" --no-follow
```

### Child session discovery

The visualizer discovers children two ways:
1. From `sub_agent_spawned` events in the parent's `events.jsonl`.
2. By scanning `$SLO_HOME/sessions/history/<parent_id>/children/` for subdirectories.

The second method provides resilience: if the parent's history was written but a spawning event was missed, the child's capture directory still makes it visible. Both sources are merged and deduplicated.

### Transcripts: canonical history and diagnostic captures

Pool-spawned children always receive the pool-assigned `--session-id` and
`--enable-history`. The visualizer projects their canonical `tree.json`
history, including user messages, assistant turns, tool calls, tool results,
and reasoning blocks.

`stdout.jsonl` is an appended diagnostic capture for live tailing and
post-mortem inspection. It is not the normal substitute for pool-child history.

### Reading child stderr

The visualizer shows a **Diagnostics** pane (bottom-right) with the selected child's stderr capture. Press `d` to toggle it. You can also read the raw file directly:

```bash
cat "$HOME/.slo/sessions/history/<parent_id>/children/<child_id>/stderr.jsonl"
```

---

## Environment Variable Reference

A clean, complete list of every environment variable Slo reads in headless and orchestrator mode.

### Session and identity

| Variable | Default | Description |
|----------|---------|-------------|
| `SLO_SESSION_ID` | — | Explicit session id for `slo run`. Validated as UUID4 or `[A-Za-z0-9._-]+` slug. |
| `SLO_HOME` | `~/.slo` | Root of all Slo data. Move this to a shared volume for multi-machine workflows. |

### Model and reasoning

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_MODEL_NAME` | provider default | Fallback model name when no preference and no `--model`. |
| `SLO_MODEL_POOL` | — | JSON array of model pool entries. See [Model pool configuration](#model-pool-configuration). |

### Tool timeouts

| Variable | Default | Description |
|----------|---------|-------------|
| `SLO_BASH_DEFAULT_TIMEOUT_SECONDS` | `1800` | Bash tool timeout in seconds. `0` disables. |
| `SLO_BASH_TEARDOWN_GRACE_SECONDS` | `5` | Grace period to reap a killed process group. |

### Orchestrator and pool

| Variable | Default | Description |
|----------|---------|-------------|
| `SLO_SUBAGENT_MAX_CONCURRENCY` | `4` | Maximum concurrent sub-agent processes in a pool. |
| `SLO_SUBAGENT_MAX_TASKS` | `8` | Maximum tasks accepted per `spawn_sub_agents` call. |
| `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` | `10800` | Seconds the orchestrator's **own** LLM stream may be silent before the run is treated as hung. This is the shipped default; do not lower it for complex workflows. |
| `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` | `7200` | Seconds a **child sub-agent** process may produce no stdout before being killed. Alias: `SLO_SUBAGENT_INACTIVITY_TIMEOUT`. |

### Visualizer

| Variable | Default | Description |
|----------|---------|-------------|
| `SLO_VISUALIZER_REFRESH_SECONDS` | `1.0` | Default polling cadence for `slo visualize`. Overridden by `--refresh-seconds`. |

### Auth

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic credential. |
| `KIMI_FOR_CODING_API_KEY` | Kimi For Coding credential. |

### Miscellaneous

| Variable | Default | Description |
|----------|---------|-------------|
| `SLO_OAUTH_TIMEOUT_SECONDS` | `60` | OAuth callback timeout (loopback callback deadline; the attempt deadline is SLO_OAUTH_MANUAL_TIMEOUT_SECONDS). |
| `SLO_OAUTH_MANUAL_TIMEOUT_SECONDS` | `900` | Whole browser-authorization attempt deadline, including a pasted manual response. |
| `SLO_OAUTH_DEVICE_TIMEOUT_SECONDS` | `900` | Slo-owned OpenAI device-authorization attempt deadline. |

---

## Recipes: Simple to Complex

Each recipe teaches one piece of the system. They build toward the culminating example.

### Recipe 1: Extract the final answer

```bash
slo run -p "What is the capital of France?" --json \
  | jq -r 'select(.kind == "run_completed") | .content'
```

### Recipe 2: Run inside a specific project

```bash
slo run -p "List every file with a TODO comment" \
  --cwd ~/projects/my-api \
  --json \
  | jq -r 'select(.kind == "tool_result") | .content' \
  | head -40
```

### Recipe 3: A multi-step session with shared context

The `SLO_SESSION_ID` approach — pin all steps to one session id and watch the agent carry context forward:

```bash
SESSION="pr-review-$(git rev-parse --short HEAD)"

# Step 1: understand the diff
SLO_SESSION_ID="$SESSION" \
  slo run -p "Read git diff HEAD~1..HEAD and summarize every change." \
  --enable-history --json > step1.jsonl

# Step 2: find problems (agent knows the diff from step 1)
SLO_SESSION_ID="$SESSION" \
  slo run -p "Based on the diff you just summarized, are there any obvious bugs or missing test coverage?" \
  --enable-history --json > step2.jsonl

# Step 3: write the PR description (agent knows everything)
SLO_SESSION_ID="$SESSION" \
  slo run -p "Write a concise PR description. Include a summary, motivation, and a test plan." \
  --enable-history --json \
  | jq -r 'select(.kind == "run_completed") | .content' > pr_description.md
```

### Recipe 4: Per-job context injection

Inject per-run metadata without polluting your `AGENTS.md`:

```bash
cat > /tmp/job_context.txt << EOF
PR: #789. Author: @bob. Target: main. Branch: fix/null-pointer-in-auth.
This run's focus: security review of the auth module changes only.
EOF

slo run -p "Review the changed files for security issues." \
  --append-system-prompt-file /tmp/job_context.txt \
  --cwd ~/projects/my-api \
  --json > security_review.jsonl
```

### Recipe 5: Reliable run with a fallback model pool and wall-clock timeout

```bash
export SLO_MODEL_POOL='[
  {"model_name":"claude-sonnet-4-6","provider":"anthropic","priority":1},
  {"model_name":"kimi-for-coding","provider":"kimi_for_coding","priority":2}
]'

timeout 600 slo run -p "Generate a migration plan for the schema changes" \
  --reasoning high \
  --enable-history \
  --json > migration_plan.jsonl

case $? in
  0) echo "Done." ;;
  1) echo "Agent failed." ;;
  2) echo "Timed out." ;;
esac
```

### Recipe 6: Parallel runs with independent sessions

When you need parallel work but do not want the overhead of an orchestrator:

```bash
# Fire three independent agents in parallel
slo run -p "Review src/auth/"  --cwd ~/project --json > auth_review.jsonl &
slo run -p "Review src/db/"    --cwd ~/project --json > db_review.jsonl &
slo run -p "Review src/api/"   --cwd ~/project --json > api_review.jsonl &

# Wait for all three
wait

# Extract answers
for f in auth_review db_review api_review; do
  echo "=== $f ==="
  jq -r 'select(.kind == "run_completed") | .content' "$f.jsonl"
done
```

This is the manual version of what the orchestrator does automatically. Use the orchestrator when you want a synthesizing parent; use direct parallel invocations when you just want results fast and do not need synthesis.

---

## The Culminating Example: Code-Test-Review Orchestration

This is the whole picture. A headless orchestrator runs a full code-test-review workflow against a feature spec, fans out to three specialist sub-agents, and synthesizes a verdict — with a live visualizer watching from the side.

Since Slo 0.13.0 the `--orchestrator` flag injects a built-in identity prompt that already knows the workflow protocol. You do not need to explain orchestrator mechanics in your prompt — just describe the task and name the workflow.

The workflow is:
1. **Code agent** (`skills/design-and-analysis/workflows/code-test-review.md`, Phase 1): Implement the feature.
2. **Review agent** (Phase 2): Review code and tests, return a verdict.

The orchestrator reads the workflow file, builds self-contained per-phase prompts from your context, dispatches them sequentially, handles REVISE/FAILED verdicts, and synthesizes a final answer.

### Prerequisites

- A project with a checked-out feature branch.
- A feature spec at e.g. `~/projects/my-feature/specs/42-widget/overview.md`.
- Slo source cloned to `~/projects/slo` (use `python -m src.cli` to run from source; the pip-installed `slo` binary may be an older version without `--orchestrator`).
- A valid API credential (`ANTHROPIC_API_KEY` or similar).
- At least two terminal windows.

### Step 1: Write the task context

The prompt is now just *context* — what to build and where. The orchestrator already knows how to drive the workflow.

Create `workflow_task.txt`:

```
Use the code-test-review workflow to implement the feature described in:
  /path/to/my-feature/specs/42-widget/overview.md

Repository root: /path/to/my-feature
Current branch: feature/42-widget (already checked out)
Git user email: you@example.com
Workflow file: skills/design-and-analysis/workflows/code-test-review.md

When all phases are done, output exactly:
WORKFLOW COMPLETE.
Branch: feature/42-widget
Tests: all passing
```

That is the entire prompt. The orchestrator reads the workflow file itself, identifies the phases (Code+Test as Phase 1, Review as Phase 2), constructs self-contained sub-agent prompts from your context, and dispatches them.

### Step 2: Set up the session

Choose a session id that is human-readable and traceable:

```bash
export WORKFLOW_SESSION="code-test-review-$(git -C ~/projects/my-feature rev-parse --short HEAD)-$(date +%Y%m%d)"
echo "Session: $WORKFLOW_SESSION"
```

### Step 3: Start the orchestrator

In terminal 1:

```bash
# Raise the main-stream inactivity timeout — the orchestrator reads workflow files
# and synthesizes results, which can take far longer than a short timeout on large contexts.
export SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS=10800

python -m src.cli run \
  -p "$(cat workflow_task.txt)" \
  --orchestrator \
  --enable-history \
  --session-id "$WORKFLOW_SESSION" \
  --cwd /path/to/my-feature \
  --model claude-sonnet-4-6 \
  --json > "$WORKFLOW_SESSION.jsonl" 2> "$WORKFLOW_SESSION.err" &

echo "Orchestrator PID: $!"
echo "Session: $WORKFLOW_SESSION"
```

The orchestrator starts, reads the workflow file, extracts your context, builds Phase 1 and Phase 2 sub-agent prompts, and dispatches Phase 1. No custom system prompt is needed — `DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT` is injected automatically because you passed `--orchestrator` and no `--system-prompt-file`.

### Step 4: Watch it live

In terminal 2, open the visualizer immediately:

```bash
python -m src.cli visualize \
  --session "$WORKFLOW_SESSION" \
  --follow \
  --refresh-seconds 2.0
```

You will see the left pane populate as sub-agents are spawned: first the Phase 1 coding agent (status `⏳`), then after Phase 1 completes the Phase 2 review agent. Select each one to see its live transcript on the right. The status bar shows the parent session state and last refresh time.

Press `r` to force an immediate refresh. Press `f` to toggle polling. Press `q` to exit — the orchestrator keeps running regardless.

### Step 5: Wait for completion

Back in terminal 1, wait for the orchestrator to finish:

```bash
wait  # or wait $PID if you saved it

case $? in
  0) echo "Workflow completed successfully." ;;
  1) echo "Workflow failed — check $WORKFLOW_SESSION.err and $WORKFLOW_SESSION.jsonl." ;;
  2) echo "Workflow was aborted." ;;
esac
```

### Step 6: Extract the synthesis

The orchestrator's final message is the synthesis: a verdict on whether the code matches the spec, the test coverage is adequate, and whether it can be merged.

```bash
jq -r 'select(.kind == "run_completed") | .content' "$WORKFLOW_SESSION.jsonl"
```

Or inspect the full event log to see every decision the orchestrator made:

```bash
jq -r 'select(.kind | test("^(text_delta|tool_call_end|sub_agent_spawned|sub_agent_completed)$")) | "\(.kind) \(.tool_name // .delta // .metadata.sub_agent_id // "")"' \
  "$WORKFLOW_SESSION.jsonl" | head -50
```

### Step 7: Inspect individual agents

Each sub-agent's output is captured under the parent session:

```bash
# List all child capture directories
ls ~/.slo/sessions/history/$WORKFLOW_SESSION/children/

# Read the code agent's full output
CHILD_ID=$(ls ~/.slo/sessions/history/$WORKFLOW_SESSION/children/ | head -1)
cat ~/.slo/sessions/history/$WORKFLOW_SESSION/children/$CHILD_ID/stdout.jsonl \
  | jq -r 'select(.kind == "text_delta") | .delta' \
  | cat

# Read the test agent's stderr (framework warnings, if any)
ls ~/.slo/sessions/history/$WORKFLOW_SESSION/children/
```

Or open the visualizer again after the run to browse all transcripts interactively:

```bash
slo visualize --session "$WORKFLOW_SESSION" --no-follow
```

### The complete script, assembled

```bash
#!/usr/bin/env bash
# code_test_review.sh — run a code-test-review workflow as a headless orchestration.
#
# Usage:
#   code_test_review.sh <project_root> <spec_path> [branch_name]
#
# Example:
#   code_test_review.sh ~/projects/my-feature \
#     ~/projects/my-feature/specs/42-widget/overview.md \
#     feature/42-widget
#
# Requires: python -m src.cli (Slo 0.13.0+), ANTHROPIC_API_KEY, jq
set -euo pipefail

PROJECT="${1:?Usage: code_test_review.sh <project_root> <spec_path> [branch]}"
SPEC_PATH="${2:?Provide the absolute path to the spec overview.md}"
BRANCH="${3:-$(git -C "$PROJECT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'main')}"
GIT_EMAIL="${GIT_EMAIL:-you@example.com}"

# Slo source root — adjust if your layout differs
SLO_SRC="${SLO_SRC:-$HOME/Code/slo/slo}"

WORKFLOW_SESSION="ctr-$(git -C "$PROJECT" rev-parse --short HEAD 2>/dev/null || echo 'local')-$(date +%Y%m%d-%H%M%S)"
JSONL_OUT="$WORKFLOW_SESSION.jsonl"
ERR_OUT="$WORKFLOW_SESSION.err"

echo "Starting code-test-review workflow."
echo "Project:  $PROJECT"
echo "Spec:     $SPEC_PATH"
echo "Branch:   $BRANCH"
echo "Session:  $WORKFLOW_SESSION"
echo ""
echo "Watch live with:"
echo "  cd $SLO_SRC && python -m src.cli visualize --session $WORKFLOW_SESSION --follow"
echo ""

# ── Inactivity timeouts ────────────────────────────────────────────────────────
# The orchestrator's own LLM stream (reads workflow file, synthesizes results)
# can be silent for several minutes on large contexts. Keep the shipped 10800s
# default so it is not killed before finishing.
export SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS="${SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS:-10800}"

# Each sub-agent child already defaults to 7200s; raise further for slow models.
export SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS="${SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS:-7200}"

# ── Concurrency ───────────────────────────────────────────────────────────────
export SLO_SUBAGENT_MAX_CONCURRENCY="${SLO_SUBAGENT_MAX_CONCURRENCY:-4}"

# ── Model pool (optional — remove if you only have one provider) ──────────────
# export SLO_MODEL_POOL='[
#   {"model_name":"claude-sonnet-4-6","provider":"anthropic","priority":1},
#   {"model_name":"kimi-for-coding","provider":"kimi_for_coding","priority":2}
# ]'

# ── Build the task prompt ─────────────────────────────────────────────────────
# This is just context — the orchestrator already knows the workflow protocol
# from DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT.  No need to describe orchestrator
# mechanics.
TASK_PROMPT="$(cat <<EOF
Use the code-test-review workflow to implement the feature described in:
  $SPEC_PATH

Repository root: $PROJECT
Current branch: $BRANCH (already checked out)
Git user email: $GIT_EMAIL
Workflow file: skills/design-and-analysis/workflows/code-test-review.md

When all phases are complete, output exactly:
WORKFLOW COMPLETE.
Branch: $BRANCH
Tests: all passing
EOF
)"

# ── Start the orchestrator ────────────────────────────────────────────────────
# --orchestrator injects DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT automatically
# because no --system-prompt-file is supplied.
cd "$SLO_SRC"
python -m src.cli run \
  -p "$TASK_PROMPT" \
  --orchestrator \
  --enable-history \
  --session-id "$WORKFLOW_SESSION" \
  --cwd "$PROJECT" \
  --model claude-sonnet-4-6 \
  --json > "$JSONL_OUT" 2> "$ERR_OUT"

STATUS=$?
echo ""
echo "Workflow finished with exit code: $STATUS"
echo ""

if [ "$STATUS" -eq 0 ]; then
  echo "=== Synthesis ==="
  jq -r 'select(.kind == "run_completed") | .content' "$JSONL_OUT"
  echo ""
  echo "=== Sub-agent summary ==="
  jq -r 'select(.kind == "sub_agent_completed" or .kind == "sub_agent_failed") |
    "\(.kind): task=\(.task_id // "?"[0:8]) agent=\(.sub_agent_id // "?"[0:8])"' \
    "$JSONL_OUT"
else
  echo "Run failed or was aborted."
  echo "Stdout tail:"
  tail -5 "$JSONL_OUT"
  echo ""
  echo "Stderr tail:"
  tail -20 "$ERR_OUT"
fi

echo ""
echo "Post-run inspection:"
echo "  python -m src.cli visualize --session $WORKFLOW_SESSION --no-follow"
```

Run it:

```bash
chmod +x code_test_review.sh
./code_test_review.sh \
  ~/projects/my-feature \
  ~/projects/my-feature/specs/42-widget/overview.md \
  feature/42-widget
```

While it runs in a second terminal:

```bash
# Open the live visualizer from the Slo source directory
cd ~/Code/slo/slo
python -m src.cli visualize \
  --session "$WORKFLOW_SESSION" \
  --follow \
  --refresh-seconds 2
```

---

## Troubleshooting

### No output at all

- Confirm `--json` is set.
- Confirm the prompt is not empty: `echo "$PROMPT"`.
- Check credentials: `ls ~/.slo/global/authentication.json`.

### `run_failed` on the first event

- The agent failed before doing anything. Read stderr: `slo run ... 2> err.log && cat err.log`.
- The model name may not be recognized. Check `config/ai_model_config.py` for the supported model list.

### History not shared across invocations

- Confirm `--enable-history` is set on every invocation that should persist.
- Confirm `SLO_SESSION_ID` is the same across steps: `echo $SLO_SESSION_ID`.
- Check that the session directory exists: `ls ~/.slo/sessions/history/`.

### `slo visualize` shows "No sub-agents found"

- The orchestrator session was not started with `--enable-history`. The visualizer reads from the history store; without history, there is nothing to read.
- The parent session id is wrong. Verify: `ls ~/.slo/sessions/history/`.
- The orchestrator has not spawned any children yet. Wait a moment and press `r` to refresh.

### Sub-agents appear in the visualizer but their transcripts are empty

- Pool-spawned children always have history enabled. Check that the child
  session directory exists and that its `tree.json` is readable.
- Check the diagnostic capture for an early process failure:
  `cat ~/.slo/sessions/history/<parent_id>/children/<child_id>/stdout.jsonl`.

### Exit code 2 from a timed-out run

- A `timeout` command killed the process.
- Raise the timeout or lower the task scope.
- The partial output is still in the JSONL file; read it to see how far the agent got.

### Model pool not switching

- Verify `SLO_MODEL_POOL` is valid JSON: `echo "$SLO_MODEL_POOL" | jq .`.
- Check that the priority values are distinct. Two entries with the same priority resolve in list order.
- Look for `run_retrying` events: `jq 'select(.kind == "run_retrying")' output.jsonl`.

### The orchestrator spawned children but never finished

- One child may have hung. The inactivity timeout is built in to the pool process pump; check `SLO_SUBAGENT_MAX_CONCURRENCY` — if it is set too low, remaining children queue behind the stuck one.
- Use the visualizer to see which child is still running (`⏳`) and inspect its transcript.
- Look at the child's stderr: `cat ~/.slo/sessions/history/<parent_id>/children/<child_id>/stderr.jsonl`.

---

## See Also

- `slo --help` and `slo run --help` for the live CLI help text.
- `slo visualize --help` for the visualizer flag reference.
- `src/cli/headless.py` — `HeadlessRunner` implementation.
- `src/cli/typer_dispatch.py` — `TyperDispatch` classmethods; the authoritative name-mapping table, including `_apply_system_prompt_b64_override`.
- `src/agents/slo_agent/orchestrator/spawn_tool.py` — `DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT` constant and `SpawnSubAgentsTool`.
- `src/agents/slo_agent/sessions/service.py` — `attach_sub_agent_pool()` injection point; `_DEFAULT_STREAM_INACTIVITY_TIMEOUT_SECONDS`.
- `src/agents/slo_agent/orchestrator/dao.py` — `SubAgentTaskDAO` including the optional `system_prompt` field.
- `src/agents/slo_agent/orchestrator/process.py` — `SubAgentProcess._build_argv()` and `CHILD_INACTIVITY_TIMEOUT_SECONDS`.
- `src/agents/slo_agent/events/stream.py` — `AgentStreamEventDAO` contract.
- `src/agents/slo_agent/sessions/dao.py` — `SessionConfigDAO` and history flags.
- `src/tui/workflow_visualizer_loader.py` — `WorkflowVisualizerLoader` data service.
- `src/tui/headless_workflow_visualizer.py` — `HeadlessWorkflowVisualizer` Textual app.
- The main `README.md` for TUI, auth setup, and the full agent loop narrative.
