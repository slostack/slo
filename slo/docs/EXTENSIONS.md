# Slo plugin extensions

Slo plugins are **trusted Python extensions for a Slo coding session**. A plugin is a
Python entry file with a `register(slo)` function. When Slo starts a session, it loads
the plugin, calls `register`, validates its contributions, and attaches the accepted
contributions to that session.

Plugins extend the existing coding-agent experience. They do **not** currently create
a new agent type, own arbitrary TUI screens or modals, receive external messages, or
provide an account/authentication framework.

## Extension model

```text
Plugin source
  │
  ├─ managed installation: `slo plugin install <GitHub-or-GitLab-HTTPS-URL> --yes`
  ├─ trusted project file: `<project>/.slo/plugins/<name>.py`
  └─ development file:    `slo --plugin /path/to/plugin.py`
  │
  ▼
Slo session startup
  │
  ├─ discover → trust gate → import → call `register(slo)`
  ├─ validate names and merge accepted contributions
  └─ run normal Slo coding-agent session
       │
       ├─ event observers receive the live session stream
       ├─ interceptors run at their named lifecycle boundaries
       ├─ plugin tools become available to the model
       ├─ plugin commands become available to the operator
       └─ plugin renderers/statuses contribute to the TUI
```

The plugin entry point may be synchronous or asynchronous:

```python
from typing import Any


def register(slo: Any) -> None:
    """Declare this plugin's contributions during session startup."""
    slo.on(event_kind="run_completed", handler=on_run_completed)
```

`register` is a declaration phase: its `PluginAPI` records what the plugin requests.
Slo performs the actual merge and runtime wiring after registration completes.

---

## Available interfaces

A `PluginAPI` exposes five contribution interfaces and three interception interfaces.
Event handlers and interceptors may be normal functions or `async` functions.

### 1. Observe the normalized event stream — `slo.on`

```python
slo.on(event_kind="tool_output_update", handler=on_output)

async def on_output(event: Any) -> None:
    print(event.content)
```

Use `on` to observe the same normalized `AgentStreamEventDAO` stream used by Slo's
TUI and session subscribers. The handler receives one event and has no return value.

Available event kinds include:

| Stage | Events |
|---|---|
| Thinking | `thinking_start`, `thinking_delta`, `thinking_end` |
| Assistant text | `text_start`, `text_delta`, `text_end` |
| Tool calls | `tool_call_start`, `tool_call_delta`, `tool_call_end` |
| Tool output | `tool_output_update`, `tool_result` |
| Run state | `run_retrying`, `stream_reconnecting`, `run_completed`, `run_aborted`, `run_failed` |
| Context compaction | `compaction_started`, `compaction_completed`, `compaction_failed`, `compaction_retrying` |
| Recovery | `recovery_started`, `recovery_succeeded`, `recovery_exhausted` |
| Sub-agents | `sub_agent_spawned`, `sub_agent_completed`, `sub_agent_failed`, `sub_agent_aborted`, `sub_agent_reaped` |

Important fields on an event include `kind`, `iteration`, `delta`, `content`,
`tool_name`, `tool_call_id`, `tool_input`, `metadata`, `sub_agent_id`, and `task_id`.
Which fields are populated depends on the event kind.

`tool_output_update` is a display-only snapshot for tools that support live output
(currently Bash is the built-in reference implementation). It does not add partial
output to model context; the model receives the terminal `tool_result` only.

### 2. Add a model tool — `slo.register_tool`

```python
slo.register_tool(tool=my_tool)
```

Register a LangChain `BaseTool` to make a new capability available to the model during
the session. The tool must have a unique name and cannot shadow a built-in Slo tool or
another accepted plugin tool.

For a managed plugin, declare every tool-name suffix in `slo-plugin.json`; Slo rejects
a managed tool whose suffix is not declared in the manifest. Managed tool names use
the plugin namespace, for example `acme_deploy__status`.

### 3. Add an operator slash command — `slo.register_command`

```python
slo.register_command(name="acme-deploy:status", handler=show_status)
```

Register a command handled through Slo's existing slash-command system. The command
name is the token without the leading slash; the user invokes the example as
`/acme-deploy:status`.

A command name must be unique. For managed plugins, declare its suffix in the
manifest's `command_suffixes` list. Managed commands conventionally use the plugin
namespace, such as `acme-deploy:status`.

### 4. Render a tool's output — `slo.register_tool_renderer`

```python
slo.register_tool_renderer(tool_name="bash", render=render_bash)


def render_bash(output: str) -> str:
    return output
```

Register a function that maps raw tool output to a display summary. It is a
presentation extension: it changes what Slo displays for that tool output, not the
model-visible tool result. Only one plugin renderer may be accepted for a tool name.

The bundled `bash_live_output` plugin is the reference example. It subscribes to
`tool_output_update` and registers a renderer for `bash`; core Slo still owns Bash
process execution, output streaming, and event delivery.

### 5. Show footer status — `slo.set_status`

```python
slo.set_status(key="acme-deploy:ci", text="CI: passing")
# Clear it later:
slo.set_status(key="acme-deploy:ci", text="")
```

Set a small plugin-owned status segment in Slo's footer. A non-empty value sets or
updates the segment; an empty value removes it. A status can be declared during
`register` and can also be updated later from a plugin handler.

### 6. Intercept a tool call — `slo.on_before_tool_call`

```python
from src.agents.slo_agent.plugins.dao import BeforeToolCallDecisionDAO


def guard_bash(decision: BeforeToolCallDecisionDAO, tool_input: dict) -> BeforeToolCallDecisionDAO:
    command = str(tool_input.get("command", ""))
    if "rm -rf /" in command:
        return BeforeToolCallDecisionDAO(block=True, reason="Refusing destructive command")
    return BeforeToolCallDecisionDAO()


slo.on_before_tool_call(handler=guard_bash)
```

This hook runs after Slo knows a tool's input and before it invokes the tool. It
receives the current decision and current input, and returns a
`BeforeToolCallDecisionDAO`:

| Field | Meaning |
|---|---|
| `block` | Stop the tool call when `True`. |
| `reason` | Reason recorded for a blocked call. |
| `mutated_input` | Replacement input dictionary. Later interceptors see the replacement. |

Interceptors run in registration order. The first handler that blocks stops the chain.

### 7. Intercept a terminal tool result — `slo.on_after_tool_result`

```python
from src.agents.slo_agent.plugins.dao import AfterToolResultPatchDAO


def redact_result(content: str, is_error: bool) -> AfterToolResultPatchDAO:
    return AfterToolResultPatchDAO(content=content.replace("SECRET", "[redacted]"))


slo.on_after_tool_result(handler=redact_result)
```

This hook runs after a tool finishes but before Slo creates the terminal result passed
to the model. It receives the current `content` and `is_error` values and returns an
`AfterToolResultPatchDAO`:

| Field | Meaning |
|---|---|
| `content` | Replacement terminal content; omit it to keep the current value. |
| `is_error` | Replacement error flag; omit it to keep the current value. |

Handlers run in order, and each handler receives the values produced by previous
handlers.

### 8. Add context before an agent iteration — `slo.on_before_agent_turn`

```python
from langchain_core.messages import SystemMessage
from src.agents.slo_agent.plugins.dao import BeforeAgentTurnDecisionDAO


def add_policy(iteration: int) -> BeforeAgentTurnDecisionDAO:
    return BeforeAgentTurnDecisionDAO(
        inject_messages=[SystemMessage(content="Follow the repository release policy.")]
    )


slo.on_before_agent_turn(handler=add_policy)
```

This hook runs immediately before each outer agent/model iteration. It receives the
upcoming iteration number and returns `BeforeAgentTurnDecisionDAO`. Its
`inject_messages` list is appended to the context for that model call. Contributions
from handlers are collected in registration order.

---

## Invocation lifecycle

The following diagram shows when each interface is invoked during a normal run.

```text
1. Session startup
   │
   ├─ discover managed, trusted-project, and explicit plugins
   ├─ import each entry module
   ├─ call `register(slo)`
   │    ├─ `on(...)`
   │    ├─ `register_tool(...)`
   │    ├─ `register_command(...)`
   │    ├─ `register_tool_renderer(...)`
   │    ├─ `set_status(...)`
   │    ├─ `on_before_tool_call(...)`
   │    ├─ `on_after_tool_result(...)`
   │    └─ `on_before_agent_turn(...)`
   └─ validate/merge accepted contributions

2. Each coding-agent iteration
   │
   ├─ `on_before_agent_turn(handler)`
   ├─ model runs
   ├─ `on(event_kind, handler)` for thinking/text/tool-call stream events
   │
   ├─ if the model requests a tool:
   │    ├─ `on_before_tool_call(handler)`
   │    ├─ core invokes the tool
   │    ├─ `on("tool_output_update", handler)` while supported tools stream
   │    ├─ `on_after_tool_result(handler)` when the tool settles
   │    └─ `on("tool_result", handler)` when Slo emits the final event
   │
   └─ continue until `run_completed`, `run_aborted`, or `run_failed`
        └─ `on(event_kind, handler)` observes the terminal event
```

## Runtime guarantees and limits

- Plugins are **trusted code**. A managed plugin requires an explicit install
  confirmation; a project plugin only loads after the project is trusted; an explicit
  `--plugin` path is trusted by definition.
- Slo loads plugins in this order: managed plugins, trusted project plugins, then
  explicit `--plugin` paths.
- Set `SLO_PLUGINS_DISABLED=1` to disable every plugin tier for a run.
- Plugin load failures, event-handler exceptions, and interception failures are
  isolated from the coding-agent run and recorded in plugin health.
- Interceptors have a per-handler timeout (five seconds by default; configurable with
  `SLO_PLUGIN_INTERCEPTION_TIMEOUT_SECONDS`). A timeout or exception is treated as no
  opinion.
- Slo rejects tool, command, and renderer collisions rather than silently replacing
  an existing contribution. Built-in tools cannot be shadowed.
- Use `/plugins` to inspect plugin health in the TUI; `/plugins trust` trusts the
  current project for project-local plugins, and `/plugins reload` reloads plugins.
- Plugins do not currently receive APIs for arbitrary screens/modals, external service
  authentication, durable plugin state, arbitrary background workers, or inbound
  message delivery.

---

## Write a plugin

This section is the developer reference for the complete current plugin API. Start
with an explicit file while developing:

```bash
slo --plugin /absolute/path/to/my_plugin.py
```

A plugin module must export one callable named `register`. Its single argument is a
`PluginAPI`. `register` may be synchronous or async. It runs once during session
startup, before Slo processes the first prompt.

```python
from typing import Any


def register(slo: Any) -> None:
    # Declare all subscriptions and contributions here.
    ...
```

`PluginAPI` is intentionally a recording API. Calling a method in `register` declares
a contribution; it does not immediately invoke a tool, render a widget, or run a
command. Slo validates and wires accepted declarations after registration.

### Practical example: release safety policy

This plugin solves a concrete problem: it adds a lightweight release safeguard to a
coding session. It:

- blocks obviously destructive shell commands before they execute;
- redacts values that look like private keys or access tokens from terminal tool
  results before the model can reuse them;
- adds the repository's release rule before every model iteration;
- exposes `/acme-release-safety:check` so an operator can see the active policy; and
- sets a footer value during startup.

The example deliberately uses only the current public plugin interfaces. It does not
create its own UI, run a background service, or intercept provider traffic.

```python
# release_safety.py
from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import SystemMessage

from src.agents.slo_agent.plugins.dao import (
    AfterToolResultPatchDAO,
    BeforeAgentTurnDecisionDAO,
    BeforeToolCallDecisionDAO,
)

# Patterns intentionally narrow enough to avoid rewriting ordinary output. Add the
# secret formats used by your organization, and test every added pattern.
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    flags=re.DOTALL,
)
_GITHUB_TOKEN = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")

# These checks apply when a tool input has a `command` field (such as Bash input).
# The current before-tool API does not pass a separate tool-name parameter.
_FORBIDDEN_COMMANDS = (
    "rm -rf /",
    "rm -rf ~",
    "git push --force origin main",
)


def register(slo: Any) -> None:
    """Register the release policy when Slo builds a coding session."""
    slo.set_status(key="acme-release-safety:state", text="Release guard: active")
    slo.register_command(name="acme-release-safety:check", handler=check_policy)
    slo.on_before_agent_turn(handler=add_release_policy)
    slo.on_before_tool_call(handler=block_dangerous_command)
    slo.on_after_tool_result(handler=redact_terminal_result)


def check_policy(*, rest: str, session: Any) -> str:
    """Render `/acme-release-safety:check [arguments]` for the local operator."""
    del session
    detail = f" Requested check: {rest}." if rest else ""
    return (
        "Release safety is active: destructive Bash commands are blocked; "
        "private-key and GitHub-token patterns are redacted from terminal tool results."
        f"{detail}"
    )


def add_release_policy(iteration: int) -> BeforeAgentTurnDecisionDAO:
    """Add an explicit release constraint before every model iteration."""
    return BeforeAgentTurnDecisionDAO(
        inject_messages=[
            SystemMessage(
                content=(
                    "Release safety policy: never force-push main, never run destructive "
                    "recursive deletion commands, and ask the operator before a production release."
                )
            )
        ]
    )


def block_dangerous_command(
    decision: BeforeToolCallDecisionDAO,
    tool_input: dict[str, Any],
) -> BeforeToolCallDecisionDAO:
    """Deny known-dangerous command input before Slo invokes the tool."""
    # `decision` includes input mutations made by earlier plugins. This plugin does
    # not change the input, but receives the current decision as part of the contract.
    del decision
    command = str(tool_input.get("command", "")).strip().lower()
    if any(forbidden in command for forbidden in _FORBIDDEN_COMMANDS):
        return BeforeToolCallDecisionDAO(
            block=True,
            reason="Blocked by acme-release-safety: destructive release command.",
        )
    return BeforeToolCallDecisionDAO()


def redact_terminal_result(content: str, is_error: bool) -> AfterToolResultPatchDAO:
    """Remove sensitive values before the terminal result enters model context."""
    del is_error
    redacted = _PRIVATE_KEY.sub("[redacted private key]", content)
    redacted = _GITHUB_TOKEN.sub("[redacted GitHub token]", redacted)
    if redacted == content:
        return AfterToolResultPatchDAO()
    return AfterToolResultPatchDAO(content=redacted)
```

For a managed repository installed from
`https://github.com/acme/release-safety`, the manifest must declare the command
suffix used above:

```json
{
  "schema_version": 1,
  "entry_point": "release_safety.py",
  "payload": ["release_safety.py"],
  "tool_suffixes": [],
  "command_suffixes": ["check"]
}
```

The command becomes `/acme-release-safety:check`. This plugin has no model tool, so
`tool_suffixes` is empty.

> **Design note:** the release instruction is injected on every outer iteration because
> that is the actual scope of `on_before_agent_turn`. If a policy should apply only at
> the beginning of a run, check `iteration` and return an empty decision after the
> first invocation.

### Complete plugin skeleton

The following reference shows all current interfaces in one file. It is useful for
API discovery, but the release-safety plugin above is the recommended starting point
for a meaningful implementation.

```python
# my_plugin.py
from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.tools import StructuredTool

from src.agents.slo_agent.plugins.dao import (
    AfterToolResultPatchDAO,
    BeforeAgentTurnDecisionDAO,
    BeforeToolCallDecisionDAO,
)


def register(slo: Any) -> None:
    slo.on(event_kind="text_delta", handler=on_text_delta)
    slo.register_tool(
        tool=StructuredTool.from_function(
            func=deployment_status,
            name="acme_deploy_tools__status",
            description="Return the current deployment status for an environment.",
        )
    )
    slo.register_command(name="acme-deploy-tools:status", handler=command_status)
    slo.register_tool_renderer(tool_name="bash", render=lambda output: output[-2_000:])
    slo.set_status(key="acme-deploy-tools:state", text="Deploy: ready")
    slo.on_before_agent_turn(handler=before_agent_turn)
    slo.on_before_tool_call(handler=before_tool_call)
    slo.on_after_tool_result(handler=after_tool_result)


def on_text_delta(event: Any) -> None:
    pass


def deployment_status(environment: str = "production") -> str:
    return f"{environment}: healthy"


def command_status(*, rest: str, session: Any) -> str:
    del session
    return f"Deployment status: healthy ({rest or 'no environment specified'})"


def before_agent_turn(iteration: int) -> BeforeAgentTurnDecisionDAO:
    return BeforeAgentTurnDecisionDAO(
        inject_messages=[SystemMessage(content=f"Deployment policy applies (iteration {iteration}).")]
    )


def before_tool_call(
    decision: BeforeToolCallDecisionDAO, tool_input: dict[str, Any]
) -> BeforeToolCallDecisionDAO:
    del decision, tool_input
    return BeforeToolCallDecisionDAO()


def after_tool_result(content: str, is_error: bool) -> AfterToolResultPatchDAO:
    del content, is_error
    return AfterToolResultPatchDAO()
```

### API reference

### Callback signatures at a glance

| Registration | Sync callback signature | Async alternative | Return value |
|---|---|---|---|
| `on(event_kind, handler)` | `handler(event: AgentStreamEventDAO)` | `async def handler(event)` | Ignored (`None` recommended). |
| `register_tool(tool)` | A LangChain `BaseTool` | N/A | N/A — Slo invokes the tool through its normal tool runtime. |
| `register_command(name, handler)` | `handler(*, rest: str, session: SloAgentSession)` | `async def handler(*, rest, session)` | `str`, `SlashCommandResultDAO`, or `None`. |
| `register_tool_renderer(tool_name, render)` | `render(output: str) -> str` | Not supported/needed | Display summary string. |
| `on_before_agent_turn(handler)` | `handler(iteration: int)` | `async def handler(iteration)` | `BeforeAgentTurnDecisionDAO`. |
| `on_before_tool_call(handler)` | `handler(decision, tool_input)` | `async def handler(decision, tool_input)` | `BeforeToolCallDecisionDAO`. |
| `on_after_tool_result(handler)` | `handler(content: str, is_error: bool)` | `async def handler(content, is_error)` | `AfterToolResultPatchDAO`. |

`set_status(key, text)` is not a callback registration. Call it during `register` to
seed a footer value. In the current API, a handler that needs to change its status
later must retain a reference to the `slo` API object supplied to `register` (or use a
closure around it).

#### `slo.on(event_kind, handler)`

```python
slo.on(event_kind="text_delta", handler=handler)


def handler(event: AgentStreamEventDAO) -> None: ...
# or:
async def handler(event: AgentStreamEventDAO) -> None: ...
```

- Registers one observer for exactly one event kind. Register again for additional
  kinds or handlers.
- The handler's return value is ignored.
- The handler receives `AgentStreamEventDAO`; inspect `event.kind` and only fields
  applicable to that kind.
- Do not block the event loop or raise exceptions. Slo isolates exceptions and records
  them as plugin health failures, but a slow observer still delays stream fan-out.
- To react to live Bash output, subscribe to `tool_output_update`. Use `event.content`
  for the latest accumulated snapshot and `event.tool_call_id` to associate it with a
  tool invocation.

The accepted event kinds are listed in [Observe the normalized event stream](#1-observe-the-normalized-event-stream--sloon).

#### `slo.register_tool(tool)`

```python
slo.register_tool(tool=a_langchain_base_tool)
```

- `tool` must be a LangChain `BaseTool`; `StructuredTool.from_function(...)` is a
  convenient way to build one from a typed Python function.
- The `name` must be globally unique for the session. Slo refuses collisions with
  built-in tools or another accepted plugin tool.
- A tool is available to the model after startup validation; it is not a direct
  operator command.
- For a managed plugin installed from `https://github.com/acme/deploy-tools`, use the
  namespaced form `acme_deploy_tools__<suffix>`. Add `<suffix>` to the manifest's
  `tool_suffixes` list. Project-local and explicit development plugins do not have the
  manifest suffix check, but should still choose collision-resistant names.

#### `slo.register_command(name, handler)`

```python
slo.register_command(name="acme-deploy-tools:status", handler=handler)
```

- `name` is the slash-command token **without** `/`; Slo exposes the example as
  `/acme-deploy-tools:status`.
- Slo owns command parsing and invokes the handler as
  `handler(rest=<raw trailing text>, session=<active SloAgentSession>)`. Use either a
  synchronous or asynchronous handler with those keyword-only parameters.
- Command names must be unique; an accepted command cannot replace a built-in or
  already accepted command.
- Managed plugins should use `<plugin-namespace>:<suffix>` and must list `<suffix>`
  in `command_suffixes`.

#### `slo.register_tool_renderer(tool_name, render)`

```python
slo.register_tool_renderer(tool_name="bash", render=render)


def render(output: str) -> str: ...
```

- `render` maps raw terminal or partial tool output to its display summary.
- It does not modify model context or the terminal tool result.
- One accepted plugin renderer is allowed per tool name; collisions are refused.
- Keep it pure, fast, and defensive: it can run for partial live-output snapshots as
  well as final output.

#### `slo.set_status(key, text)`

```python
slo.set_status(key="acme-deploy-tools:state", text="Deploy: ready")
slo.set_status(key="acme-deploy-tools:state", text="")  # remove it
```

- Sets a plugin-owned footer segment at registration time or from a runtime callback.
- A non-empty `text` updates the value; empty text deletes it.
- Use a stable, namespaced key to avoid status collisions. Managed plugin keys should
  use `<plugin-namespace>:<suffix>`.

#### `slo.on_before_agent_turn(handler)`

```python
slo.on_before_agent_turn(handler=handler)


def handler(iteration: int) -> BeforeAgentTurnDecisionDAO: ...
# or:
async def handler(iteration: int) -> BeforeAgentTurnDecisionDAO: ...
```

- Invoked before every outer agent/model iteration.
- Return `BeforeAgentTurnDecisionDAO(inject_messages=[...])` to append LangChain
  `BaseMessage` instances ahead of that model call.
- Return an empty decision when the plugin has nothing to add.
- Multiple plugins run in registration order; injected message lists are aggregated in
  that order.

#### `slo.on_before_tool_call(handler)`

```python
slo.on_before_tool_call(handler=handler)


def handler(
    decision: BeforeToolCallDecisionDAO,
    tool_input: dict[str, Any],
) -> BeforeToolCallDecisionDAO: ...
```

- Invoked after Slo resolves a tool call and its arguments, immediately before the tool
  is called.
- Return `BeforeToolCallDecisionDAO(block=True, reason="...")` to deny the call.
- Return `BeforeToolCallDecisionDAO(mutated_input={...})` to replace its input.
- Interceptors execute in registration order. Every later interceptor receives the
  latest input; the first `block=True` stops the chain.
- Return an empty decision to allow the call unchanged.

#### `slo.on_after_tool_result(handler)`

```python
slo.on_after_tool_result(handler=handler)


def handler(content: str, is_error: bool) -> AfterToolResultPatchDAO: ...
```

- Invoked after the tool settles and before Slo builds the terminal result for the
  model.
- Return `AfterToolResultPatchDAO(content="...")` to replace output and/or
  `AfterToolResultPatchDAO(is_error=True)` to change the error state.
- Set only fields you intend to change; `None` retains the current value.
- Interceptors run in registration order, so every handler receives the previous
  handler's patched content and error state.

### Development workflow

1. Write the plugin file and launch with `slo --plugin /absolute/path/to/plugin.py`.
2. Inspect `/plugins` after startup. It shows loaded plugins, accepted contributions,
   load errors, and isolated handler failure counts.
3. Change the file, then restart Slo or run `/plugins reload`.
4. Use a focused test that creates `PluginRegistrationDAO` and calls `register` to
   verify declarations without starting a provider-backed Slo session. The bundled
   plugin test at `tests/plugins/test_bash_live_output_plugin.py` is a working example.
5. Before publishing, verify a managed installation from a clean test repository and
   ensure every declared tool/command suffix appears in `slo-plugin.json`.

### Project-local plugin

Place a Python file in the project:

```text
my-project/
└── .slo/
    └── plugins/
        └── my_plugin.py
```

Then start Slo in `my-project` and explicitly trust the project with `/plugins trust`.
Project plugins fail closed: Slo does not import them until that trust decision exists.

## Publish a managed plugin

Managed plugins are installable from a **GitHub or GitLab HTTPS repository URL**. Keep
the entry file and a `slo-plugin.json` manifest in the repository root (or include any
required files in the manifest payload).

```text
slo-my-plugin/
├── slo-plugin.json
└── plugin.py
```

### `slo-plugin.json`

```json
{
  "schema_version": 1,
  "entry_point": "plugin.py",
  "payload": ["plugin.py"],
  "tool_suffixes": [],
  "command_suffixes": []
}
```

Manifest fields:

| Field | Required | Purpose |
|---|---:|---|
| `schema_version` | yes | Must be `1`. |
| `entry_point` | yes | Python entry file relative to the payload root. |
| `payload` | yes | Files/directories copied into the managed installation. Include every runtime dependency stored in the repository. |
| `tool_suffixes` | yes | Local suffixes for model tools the plugin registers. |
| `command_suffixes` | yes | Local suffixes for slash commands the plugin registers. |

For a repository installed from `https://github.com/acme/deploy-tools`, Slo derives
the managed plugin identity `acme-deploy-tools`. If it contributes a tool named
`acme_deploy_tools__status` and command token `acme-deploy-tools:status`, the manifest
must declare them as follows:

```json
{
  "schema_version": 1,
  "entry_point": "plugin.py",
  "payload": ["plugin.py", "acme_deploy/"],
  "tool_suffixes": ["status"],
  "command_suffixes": ["status"]
}
```

Commit and push the repository. The installer clones a pinned revision, validates the
manifest, copies only the declared payload, and atomically installs it. It **does not
execute downloaded plugin code during installation**.

## Install, inspect, upgrade, and remove

```bash
# Install a new plugin. --yes confirms that you trust this source.
slo plugin install https://github.com/acme/deploy-tools --yes

# List installed plugin ids, pinned revisions, and source provenance.
slo plugin list

# Upgrade one plugin to a newly pinned revision.
slo plugin upgrade acme-deploy-tools

# Remove it and its managed install record.
slo plugin uninstall acme-deploy-tools
```

Managed plugins are installed under Slo's user-global plugin directory and load on
subsequent Slo sessions. Their source URL and pinned revision are retained as install
provenance. You can also install Slo's bundled live Bash output renderer with:

```bash
slo plugin install-bundled-bash-live-output
```

Before installing a third-party plugin, review its source and manifest. Plugins are
Python code that execute with the permissions of the local Slo process once they load.
