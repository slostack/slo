---
name: build-cli-modules
description: 'Coding standards for every Python module under a project''s cli/: stack
  library rules, argument patterns, @handle_cli_errors, two-console discipline, polling,
  retry, dry-run gate, structlog configuration, and test layers.'
when_to_use: Use when authoring or reviewing a CLI module's implementation; pair with
  build-cli-command-class for the command class itself.
group: cli
kind: skill
source_prompt: cli/build-cli-modules.md
---

# Building CLI Modules — Typer + Rich + async standards

## Skill summary

- **Name:** `build-cli-modules`
- **Description:** Coding standards for every Python module under a project's cli/: stack library rules, argument patterns, @handle_cli_errors, two-console discipline, polling, retry, dry-run gate, structlog configuration, and test layers.
- **When to use:** Use when authoring or reviewing a CLI module's implementation; pair with build-cli-command-class for the command class itself.
- **Group:** `cli`
- **Kind:** `skill`
- **Source prompt:** `cli/build-cli-modules.md`

## Examples

- The user asks: "Add or revise the cli modules for this feature."
- You want the canonical build pattern before touching cli modules.

## Guidance

Coding standards for every Python module under `<project>/cli/`. This
file covers the **Python module implementation**: stack library rules,
argument patterns, error handling, two-console discipline, polling,
retry, dry-run gate, structlog configuration, and test layers.

---

## Companion documents — read these alongside this file

| File | Scope |
|---|---|
| [`build-cli-command-class.md`](../build-cli-command-class/SKILL.md) | **Authoritative for Command class structure** — `Command` suffix, `__init__`/`build`/`execute` triad, `execute`-as-table-of-contents, Typer function naming (`verify-flow` → `verify_flow`), async helper naming (`_verify_flow_async`), `@handle_cli_errors` placement (on the async body, not the Typer function), `run_async` import source, file layout, anti-patterns, full pre-merge checklist. |
| [`build-cli-commands.md`](../build-cli-commands/SKILL.md) | Makefile shape, CLI → Router → AppService layering, CLI-endpoint auth model, polling + idempotency. |

---

## 1. Scope + stack — async-first, class-per-verb, envelope-only

| Concern | Library — no alternatives |
|---|---|
| Argument parsing + entry | **Typer 0.25+** (`async def` commands are NOT auto-wrapped by Typer — `run_async` from `cli/error_handler.py` calls `asyncio.run()` around the async body; `@handle_cli_errors` wraps the async body for error handling; see §6–7) |
| Terminal output, spinners, tables | **Rich** |
| HTTP requests | **`httpx.AsyncClient`** (never `httpx.Client`) |
| Diagnostic logging | **structlog** |
| Config + DAOs | **Pydantic v2** + **pydantic-settings** (never `@dataclass`) |
| Polling sleep | **`asyncio.sleep`** (never `time.sleep`) |
| Tests | **pytest-asyncio** + **pytest-httpx** + Typer's `CliRunner` |

The shape every module follows: every HTTP exchange goes through
`CLIClient` + `parse_envelope`; every async command body is wrapped by
`@handle_cli_errors`; two consoles (stdout for data, stderr for status);
polling is canonical via `poll_until_terminal()`; retry policy is a
Pydantic model; tests assert on `result.stdout` / `result.stderr`
independently. **For `Command` class structure** (naming, triad,
`execute()` discipline, file layout), see
[`build-cli-command-class.md`](../build-cli-command-class/SKILL.md).

Cross-references: [`build-cli-commands.md`](../build-cli-commands/SKILL.md),
[`build-cli-command-class.md`](../build-cli-command-class/SKILL.md),
``skills/coding/declarative-method-structure/SKILL.md`` plus ``skills/languages/python/declarative-method-structure/SKILL.md``,
``skills/languages/python/named-arguments-and-type-hints/SKILL.md``,
``skills/languages/python/method-docstrings/SKILL.md``,
``../../plans/cli-router/overview.md`` §2.1.

---

## 2. The full trace: operator keystroke → exit code

Read this before writing a single line. The chain for `make verify-flow`
(see [`build-cli-command-class.md`](../build-cli-command-class/SKILL.md) for the
authoritative naming chain and Command class detail):

```
1. Operator types:           make verify-flow ENV=local ARGS="--n 5"

2. Makefile recipe (≤4 lines, verifier/Makefile):
     verify-flow:
         $(call require_env)
         @loadenv environments/$(ENV).env && \
             python -m cli.verify_flow_dispatch --env $(ENV) $(ARGS)

3. cli/verify_flow_dispatch.py:
     - typer boots, main(ctx, env) reads $VERIFIER_DEPLOY_MODE
     - os.execvpe("python", ["python", "-m", "cli.verify_run", "verify_flow",
                             "--env", env, *ctx.args], env=os.environ)
     - REPLACES the current process — same PID, same TTY; SIGINT
       propagates cleanly to the child.

4. cli/verify_run.py::verify_flow():
     @app.command()
     def verify_flow(env, n, ...) -> None:    # sync; name = snake_case of Make target
         run_async(_verify_flow_async)(...)    # run_async imported from cli/error_handler.py

     @handle_cli_errors                        # <- THE try/except is on the ASYNC body
     async def _verify_flow_async(env, n, ...) -> None:
         command = await VerifyFlowCommand.build(env=env, n=n, ...)
         try:
             await command.execute()
         finally:
             await command.aclose()

     Note: @handle_cli_errors goes on the async body (_verify_flow_async),
     NOT on the Typer function (verify_flow). The Typer function is sync;
     run_async() calls asyncio.run() around the async body internally.
     See build-cli-command-class.md Rule 6 + Rule 7 for the full rationale.

5. VerifyFlowCommand.execute() — the table of contents:
     async def execute(self) -> None:
         await self._trigger()                # POST /verify-flow
         await self._poll_until_terminal()    # loop GET /runs/<id>
         await self._print_dashboard()        # GET /runs/<id>/dashboard

6. Each helper: await client.{post,get} → parse_envelope; the poll
   helper additionally does `await asyncio.sleep(interval)` between
   calls. parse_envelope raises CLI*Error on any failure envelope.

7a. Happy path:   execute() returns → @handle_cli_errors no-ops → exit 0.

7b. Ctrl-C during poll:
     KeyboardInterrupt → @handle_cli_errors catches → CLIInterruptHandler
     renders resume hint ("python -m cli.verify_run poll --run-id ...")
     to stderr → raise typer.Exit(code=130).

7c. Failure envelope from server:
     parse_envelope raises CLIAuthError(exit_code=3) → @handle_cli_errors
     catches → CLIErrorRenderer prints "✗ <user_message>" red on stderr
     → raise typer.Exit(code=3) from err.
```

Every other CLI command follows the **identical** shape. §3 shows the
module-level boilerplate; for Command class internals see
[`build-cli-command-class.md`](../build-cli-command-class/SKILL.md).

---

## 3. The canonical module shape — module-level boilerplate

This section covers the **module-level** structure: imports, `app`
declaration, `log`, and the Typer verb wiring. For Command class
internals (`__init__`, `build`, `execute`, naming, file layout), see
[`build-cli-command-class.md`](../build-cli-command-class/SKILL.md).

```python
"""Multi-verb CLI for verification runs: flow, trigger, poll, dashboard."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import uuid4

import structlog
import typer
from rich.console import Console
from rich.table import Table

from cli.client import CLIClient
from cli.config import CLIConfig, load_config
from cli.envelope import parse_envelope
from cli.error_handler import handle_cli_errors, run_async
from cli.errors import CLITimeoutError
from cli.polling import PollResult, poll_until_terminal

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
    help="Verification run commands: flow, trigger, poll, dashboard.",
)

log = structlog.get_logger("cli.verify_run")


# ---------- verb commands (thin sync wrappers; delegate to async bodies) ----------
# Naming rule: Typer function name = snake_case of Make target name.
# See build-cli-command-class.md Rule 5.

@app.command()
def verify_flow(
    env:            Annotated[str,        typer.Option(envvar="ENV")],
    n:              Annotated[int,        typer.Option(min=1, max=200)] = 10,
    baselines:      Annotated[bool,       typer.Option("--baselines/--no-baselines")] = False,
    correlation_id: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Trigger a verification run, poll to terminal, print the dashboard."""
    run_async(_verify_flow_async)(
        env=env, n=n, baselines=baselines,
        correlation_id=correlation_id or str(uuid4()),
    )


@app.command()
def trigger(
    env:            Annotated[str,        typer.Option(envvar="ENV")],
    n:              Annotated[int,        typer.Option(min=1, max=200)] = 10,
    baselines:      Annotated[bool,       typer.Option("--baselines/--no-baselines")] = False,
    correlation_id: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Trigger only; print run_id to stdout; do not poll."""
    run_async(_trigger_async)(
        env=env, n=n, baselines=baselines,
        correlation_id=correlation_id or str(uuid4()),
    )


@app.command()
def poll(
    env:    Annotated[str, typer.Option(envvar="ENV")],
    run_id: Annotated[str, typer.Option()],
) -> None:
    """Resume polling an existing run after a Ctrl-C."""
    run_async(_poll_async)(env=env, run_id=run_id)


@app.command()
def dashboard(
    env:    Annotated[str, typer.Option(envvar="ENV")],
    run_id: Annotated[str, typer.Option()],
) -> None:
    """Print the dashboard for a finished run."""
    run_async(_dashboard_async)(env=env, run_id=run_id)


# ---------- async bodies (@handle_cli_errors goes here, NOT on the Typer function) ----------
# See build-cli-command-class.md Rule 6.

@handle_cli_errors
async def _verify_flow_async(*, env: str, n: int, baselines: bool, correlation_id: str) -> None:
    """Async body for the verify_flow command."""
    command: VerifyFlowCommand = await VerifyFlowCommand.build(
        env=env, n=n, baselines=baselines, correlation_id=correlation_id,
    )
    try:
        await command.execute()
    finally:
        await command.aclose()


@handle_cli_errors
async def _trigger_async(*, env: str, n: int, baselines: bool, correlation_id: str) -> None:
    """Async body for the trigger command."""
    command: VerifyTriggerCommand = await VerifyTriggerCommand.build(
        env=env, n=n, baselines=baselines, correlation_id=correlation_id,
    )
    try:
        await command.execute()
    finally:
        await command.aclose()


@handle_cli_errors
async def _poll_async(*, env: str, run_id: str) -> None:
    """Async body for the poll command."""
    command: VerifyPollCommand = await VerifyPollCommand.build(env=env, run_id=run_id)
    try:
        await command.execute()
    finally:
        await command.aclose()


@handle_cli_errors
async def _dashboard_async(*, env: str, run_id: str) -> None:
    """Async body for the dashboard command."""
    command: VerifyDashboardCommand = await VerifyDashboardCommand.build(env=env, run_id=run_id)
    try:
        await command.execute()
    finally:
        await command.aclose()


# ---------- Command classes ----------
# Structure, naming rules, and full examples live in build-cli-command-class.md.
# Every Command class has: __init__ (keyword-only, typed, no I/O), build (@classmethod
# async, factory only), execute (table of contents, 5-10 lines), aclose (closes client).

class VerifyFlowCommand:
    """One verify-flow execution: trigger → poll → dashboard."""
    # Full implementation: see build-cli-command-class.md §Rule 2 + canonical example.
    ...


class VerifyTriggerCommand:
    """Trigger-only — POST + print run_id, no poll."""
    ...


class VerifyPollCommand:
    """Poll-only — resume an existing run by run_id."""
    ...


class VerifyDashboardCommand:
    """Dashboard-only — GET + render."""
    ...


if __name__ == "__main__":
    app()
```

Single-verb modules collapse to one `@app.command()`, one async body,
and one Command class — the shape is identical.

**Key module-level rules captured here (not in `build-cli-command-class.md`):**
- `run_async` imported from `cli/error_handler.py` — never copy-pasted.
- `@handle_cli_errors` on the **async body** (`_verify_flow_async`), not on the Typer function.
- Typer functions are **sync** (`def`, not `async def`).
- `app` and `if __name__ == "__main__": app()` in the same file as the Command classes.

---

## 4. Argument acceptance — one canonical pattern

Every input goes through `Annotated[T, typer.Option(...)]`. No
`sys.argv`, no `argparse`, no positional unless the natural English
reading is `verb thing`.

**The full pattern, every knob shown:**

```python
from typing import Annotated
import typer
from cli.error_handler import handle_cli_errors, run_async

# Typer function: sync; name = snake_case of Make target; delegates to async body via run_async.
@app.command()
def verify_flow(
    # required: no default; Typer enforces presence
    env:            Annotated[str,        typer.Option(envvar="ENV", help="Deployment env: local|staging|production")],

    # bounded int: Typer rejects out-of-range; envvar fallback
    n:              Annotated[int,        typer.Option(min=1, max=200, envvar="VERIFIER_N",
                                                       help="Number of questions to verify")] = 10,

    # explicit toggle: ALWAYS --flag/--no-flag
    baselines:      Annotated[bool,       typer.Option("--baselines/--no-baselines",
                                                       help="Include baseline runs")] = False,

    # optional string: T | None = None, never bare = None
    correlation_id: Annotated[str | None, typer.Option(help="Idempotency key; auto-uuid4 if omitted")] = None,

    # multi-value: list[T]; flag repeats
    dimensions:     Annotated[list[str],  typer.Option("--dimension", help="Restrict to dimension (repeatable)")] = [],
) -> None:
    """One-line summary; appears in --help."""
    run_async(_verify_flow_async)(
        env=env, n=n, baselines=baselines,
        correlation_id=correlation_id or str(uuid4()),
        dimensions=dimensions,
    )


# @handle_cli_errors goes on the ASYNC body, not the Typer function.
# See build-cli-command-class.md Rule 6.
@handle_cli_errors
async def _verify_flow_async(
    *, env: str, n: int, baselines: bool,
    correlation_id: str, dimensions: list[str],
) -> None:
    """Async body for the verify_flow command."""
    command = await VerifyFlowCommand.build(
        env=env, n=n, baselines=baselines,
        correlation_id=correlation_id, dimensions=dimensions,
    )
    try:
        await command.execute()
    finally:
        await command.aclose()
```

**Rules:**

| Concern | Pattern |
|---|---|
| Required arg | No default; type is `T` (not `T \| None`) |
| Optional scalar | `T \| None = None`; body handles the `None` case |
| Boolean | `--flag/--no-flag` always; never bare `--flag` |
| Bounded number | `typer.Option(min=N, max=M)`; Typer renders the rejection |
| Multi-value | `list[T]` with `typer.Option("--singular-name")` |
| Env-var fallback | `typer.Option(envvar="UPPER_CASE")` |
| Subcommands | `@app.command()` per verb; module has 2+ verbs |
| Unknown-arg passthrough | `ctx: typer.Context` first param + `ctx.args` (dispatch shims only) |

Help text on **every** option — operators read `--help` before the
source.

---

## 5. The Command class pattern — see `build-cli-command-class.md`

**Why classes, not functions:** an async verb owns state — a client,
two consoles, a `run_id` that's `None` until trigger succeeds, a poll
result that's `None` until polling completes. A function passes that
state through every helper or stashes it in module globals. A class
makes it explicit and the helpers small. Tests instantiate the class
with a mocked client and assert per-method.

The mandatory structure (naming rules, `__init__`/`build`/`execute`
triad, `execute()` discipline, `aclose`, file layout, anti-patterns,
and full pre-merge checklist) is authoritatively documented in
[`build-cli-command-class.md`](../build-cli-command-class/SKILL.md). Read that
file before writing any Command class.

The canonical reference implementation is
`verifier/cli/verify_run.py` — `VerifyFlowCommand`, `TriggerCommand`,
`PollCommand`, `DashboardCommand`, and their shared base
`_BaseVerifyCommand`.

---

## 6. The `@handle_cli_errors` decorator — one place owns try/except

Every procedural try/except in every `main()` across the codebase is
**replaced** by this decorator. It owns:

- `CLIError` → red message to stderr → `typer.Exit(err.exit_code)`
- `KeyboardInterrupt` (Ctrl-C) → resume hint → `typer.Exit(130)`
- Anything else → propagates (Typer prints a tidy traceback)

**Placement rule:** `@handle_cli_errors` goes on the **async body**
(`_verify_flow_async`), NOT on the Typer function (`verify_flow`). The
Typer function is synchronous — `run_async()` calls `asyncio.run()` around
the async body internally. See [`build-cli-command-class.md` Rule 6](../build-cli-command-class/SKILL.md)
and Rule 7 for the full rationale and `run_async` import source.

**Full implementation (`cli/error_handler.py`):**

```python
"""@handle_cli_errors decorator + the two renderer classes."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

import typer
from rich.console import Console

from cli.errors import CLIError


def handle_cli_errors(fn: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
    """Convert CLIError → typer.Exit(err.exit_code); SIGINT → typer.Exit(130) + resume hint.

    THE single place catching operator-facing errors. Wraps any async Typer command body.
    """
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            await fn(*args, **kwargs)
        except KeyboardInterrupt:
            CLIInterruptHandler.from_context().render(console=Console(stderr=True))
            raise typer.Exit(code=130)
        except CLIError as err:
            CLIErrorRenderer(err=err).render(console=Console(stderr=True))
            raise typer.Exit(code=err.exit_code) from err
    return wrapper


class CLIErrorRenderer:
    """Renders one CLIError to stderr in red. One responsibility."""

    def __init__(self, *, err: CLIError) -> None:
        self.err: CLIError = err

    def render(self, *, console: Console) -> None:
        console.print(f"[bold red]✗ {self.err.user_message}[/bold red]")
        if self.err.envelope is not None:
            console.print_json(data=self.err.envelope)


class CLIInterruptHandler:
    """Renders the SIGINT 'Cancelled. Resume with …' message."""

    def __init__(self, *, env: str | None = None, run_id: str | None = None) -> None:
        self.env:    str | None = env
        self.run_id: str | None = run_id

    @classmethod
    def from_context(cls) -> "CLIInterruptHandler":
        """Build from contextvars set by the Command class __init__."""
        from cli.context import current_env, current_run_id
        return cls(env=current_env.get(default=None), run_id=current_run_id.get(default=None))

    def render(self, *, console: Console) -> None:
        console.print("\n[yellow]⚠ Cancelled.[/yellow]")
        if self.run_id and self.env:
            console.print(
                f"  Resume with: [cyan]python -m cli.verify_run poll "
                f"--env {self.env} --run-id {self.run_id}[/cyan]"
            )
```

**When to apply:** every async body paired with an `@app.command()`
function. No exceptions. A command that doesn't need it (e.g. a
pure-stdout `--version` echo) isn't doing real work yet.

`current_env` and `current_run_id` are `contextvars.ContextVar`s the
Command class sets in `__init__` so the decorator can pull them
without a parameter dance.

---

## 7. Async patterns — when, where, how to wait

**Typer command functions are sync; their async bodies are separate.**
Typer 0.25 does NOT auto-wrap async commands. The pattern is:
`@app.command() def verify_flow(...) → run_async(_verify_flow_async)(...)`.
`run_async` (imported from `cli/error_handler.py`) calls
`asyncio.run()` internally. `@handle_cli_errors` wraps the async body.
Never register a bare `async def` with `@app.command()` (it'll become a
never-awaited coroutine); never call `asyncio.run()` manually at the
top of `__main__`. See [`build-cli-command-class.md`](../build-cli-command-class/SKILL.md)
Rules 6–7 for the full naming chain.

**Polling loop (the canonical case):**

```python
async def _poll_loop(self, *, deadline: float) -> dict:
    """Single async loop; sleeps via asyncio.sleep — never time.sleep."""
    while True:
        response = await self.client.get(path=self.poll_path)
        data: dict = parse_envelope(response=response)
        if data["status"] in TERMINAL_STATES:
            return data
        if asyncio.get_event_loop().time() > deadline:
            raise CLITimeoutError(run_id=self.run_id, timeout=self.timeout)
        await asyncio.sleep(self.interval_seconds)
```

**Concurrent fan-out (rare but supported) — `asyncio.gather`:**

```python
async def _fetch_all(self) -> list[dict]:
    """Fetch N dashboards concurrently; gather preserves order + raises first error."""
    responses = await asyncio.gather(
        *[self.client.get(path=f"/api/v1/cli/runs/{rid}/dashboard") for rid in self.run_ids]
    )
    return [parse_envelope(response=r) for r in responses]
```

**Subprocess (sops, make, ssh) — `asyncio.create_subprocess_exec`:**

```python
async def run_make_targets(*, env: str, targets: list[str]) -> None:
    """Run `make <target> ENV=<env>` sequentially; raise on first non-zero exit."""
    for target in targets:
        proc = await asyncio.create_subprocess_exec(
            "make", target, f"ENV={env}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise CLISubprocessError(target=target, returncode=proc.returncode, stderr=stderr.decode())
```

**Cancellation:** `asyncio.CancelledError` propagates naturally through
`await` points. Don't catch it in helpers; `@handle_cli_errors` catches
`KeyboardInterrupt` at the top — that's the only SIGINT handling needed.

Forbidden in async code: `time.sleep`, `httpx.Client`,
`subprocess.run` (for anything beyond a one-shot fast call), and
manual `asyncio.run(main())` inside a command body (`@handle_cli_errors`
already calls `asyncio.run()` around the wrapped function).

---

## 8. State objects: Pydantic v2 — never `@dataclass`

Two flavours, no third option. **Env-driven config** uses
`pydantic_settings.BaseSettings` (auto-loads `VERIFIER_*` env vars).
**Everything else** (RetryPolicy, PollResult, request/response DAOs)
uses `pydantic.BaseModel` with `ConfigDict(frozen=True)`.

**Why never `@dataclass`:** no validation, no JSON round-trip, no
`model_dump()`, no `frozen=True` at runtime. Pydantic v2 is faster for
our workload and gives serialisation for free.

```python
# cli/config.py — env-driven
from pydantic_settings import BaseSettings, SettingsConfigDict

class CLIConfig(BaseSettings):
    """Operator-side CLI configuration. Loaded from VERIFIER_* env vars."""
    model_config = SettingsConfigDict(env_prefix="VERIFIER_", case_sensitive=False, extra="ignore")
    api_url:                   str
    cli_token:                 str
    tls_verify:                bool = True
    cli_poll_interval_seconds: int  = 5
    cli_poll_timeout_seconds:  int  = 1800
    log_level:                 str  = "INFO"

def load_config(*, env: str) -> CLIConfig:
    """Resolve token from $VERIFIER_CLI_TOKEN or ~/.orders/<env>/cli-token; raise CLITokenMissingError if neither."""
    token: str = os.environ.get("VERIFIER_CLI_TOKEN") or read_token_file(env=env)
    return CLIConfig(cli_token=token)


# cli/retry.py + cli/polling.py — immutable state
from pydantic import BaseModel, ConfigDict

class RetryPolicy(BaseModel):
    """How CLIClient retries transient failures. Frozen; instances are constants."""
    model_config = ConfigDict(frozen=True)
    max_attempts:            int      = 3
    initial_backoff_seconds: float    = 1.0
    max_backoff_seconds:     float    = 8.0
    multiplier:              float    = 2.0
    retry_on_status_codes:   set[int] = {500, 502, 503, 504}

DEFAULT_RETRY: RetryPolicy = RetryPolicy()

class PollResult(BaseModel):
    """Returned by poll_until_terminal on terminal state."""
    model_config = ConfigDict(frozen=True)
    status:          str
    final_envelope:  dict
    elapsed_seconds: int
```

Request/response DAOs are also `BaseModel` — one file per route family
under `cli/dao/`.

---

## 9. Two consoles, three output formats

Output is split. **Data → stdout** (`console`). **Status, progress,
errors → stderr** (`err_console`). The split is what makes
`make verify-flow ENV=local | jq` work; mixing them breaks every shell
pipeline.

```python
self.console     = Console()              # stdout — data
self.err_console = Console(stderr=True)   # stderr — progress, status, errors
```

| What | Where | Tool |
|---|---|---|
| Final envelope (JSON-parseable) | `console` | `console.print_json(data=envelope)` |
| Dashboard table | `console` | `console.print(table)` |
| Progress spinner | `err_console` | `Progress(..., console=err_console, transient=True)` |
| One-line status updates | `err_console` | `err_console.print(...)` |
| Error message | `err_console` | `CLIErrorRenderer.render` |

The `--output` flag switches **what lands on stdout**:

| `--output` | stdout content |
|---|---|
| `human` (default) | Rich tables, panels, syntax-highlit JSON |
| `json` | Raw envelope, single-line or pretty (machine-readable) |
| `yaml` | Same envelope, YAML-rendered |

Helper:

```python
from cli.output import OutputFormat, render_envelope

render_envelope(envelope=envelope, fmt=output, console=self.console)
```

stderr content is **identical** across the three modes. `--output`
only affects the final result.

`print()` and `sys.stdout.write()` are rejected in code review. Always
use a `Console`.

---

## 10. Polling — the canonical pattern

Every long-running command uses `cli.polling.poll_until_terminal()`.
Never roll your own loop.

**The contract:** the pollable resource exposes
`GET /api/v1/cli/<resource>/<id>` returning the canonical envelope.
`data` carries:

```json
{
  "status":          "queued" | "running" | "succeeded" | "failed" | "cancelled",
  "progress_done":   <int>,
  "progress_total":  <int>,
  "progress_label":  "<phase>"
}
```

`status in {"succeeded", "failed", "cancelled"}` is **terminal**.

**The helper signature:**

```python
async def poll_until_terminal(
    *,
    client:               CLIClient,
    path:                 str,
    interval_seconds:     int,
    timeout_seconds:      int,
    progress_console:     Console,
    progress_description: str,
) -> PollResult:
    """Loop GET <path> until status is terminal or budget exhausted.

    Opens a Rich Progress (transient=True) on progress_console; loops
    `await client.get(path)` → parse_envelope → check status; updates
    the spinner label each iteration; retries transient failures per §11;
    awaits asyncio.sleep(interval_seconds) between polls; raises
    CLITimeoutError when elapsed > timeout_seconds.
    """
```

**Resume after Ctrl-C:** every long-op verb pairs with a `poll`
subcommand that runs ONLY step 2 onwards (see `VerifyPollCommand` in
§3).

---

## 11. Retry + backoff for transient failures

`CLIClient` and `poll_until_terminal` both honour `cli.retry.DEFAULT_RETRY`.

**Rules:**

| Condition | Behaviour |
|---|---|
| HTTP 5xx (server) | Retry up to `max_attempts`, exponential backoff |
| HTTP 4xx | **Never retry.** Request is wrong; retrying won't fix it. |
| `httpx.ConnectError` / `ReadTimeout` / `RemoteProtocolError` / `PoolTimeout` | Retry — transport issue |
| Anything else | Propagate |

**The helper (`cli/retry.py`):**

```python
async def with_retry(
    *,
    fn:     Callable[[], Awaitable[httpx.Response]],
    policy: RetryPolicy = DEFAULT_RETRY,
    log:    structlog.BoundLogger,
) -> httpx.Response:
    """Retry fn() on 5xx + transport errors; raise CLIServerError / CLINetworkError after max_attempts."""
    backoff: float = policy.initial_backoff_seconds
    for attempt in range(1, policy.max_attempts + 1):
        try:
            response = await fn()
            if response.status_code not in policy.retry_on_status_codes:
                return response
            if attempt == policy.max_attempts:
                raise CLIServerError(status=response.status_code, body=response.text)
            log.warning("retrying on 5xx", attempt=attempt, status=response.status_code, sleep=backoff)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.PoolTimeout) as exc:
            if attempt == policy.max_attempts:
                raise CLINetworkError(cause=exc) from exc
            log.warning("retrying on transport error", attempt=attempt, error=str(exc), sleep=backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * policy.multiplier, policy.max_backoff_seconds)
    raise RuntimeError("unreachable")
```

The user sees **one** final error, not three. Diagnostic detail goes
to structlog at WARNING.

---

## 12. Cancellation — Ctrl-C is a first-class state

`@handle_cli_errors` is the only place SIGINT is caught. Three things
happen on `KeyboardInterrupt`:

1. **No traceback.** The decorator catches before Typer's
   `pretty_exceptions` would print one.
2. **Resume hint** via `CLIInterruptHandler.from_context()` — reads
   `current_run_id` + `current_env` from contextvars set by the
   Command's `__init__`, prints the exact `python -m cli.<module>
   poll --env <env> --run-id <id>` invocation to stderr.
3. **Exit 130** — the Unix SIGINT convention.

**The `run_id` is printed to stderr as soon as `_trigger()` succeeds**,
before the poll loop starts. Even an immediate Ctrl-C leaves a
re-poll handle on screen.

`asyncio.CancelledError` propagates through `await` points naturally;
do not catch it in helpers.

---

## 13. Dry-run + destructive ops — `DryRunGate` + `require_confirmation`

Both are async because they call other async helpers.

```python
# cli/dry_run.py
class DryRunGate:
    """Gates every side effect on --dry-run. Read-only ops run regardless."""

    def __init__(self, *, dry_run: bool, console: Console) -> None:
        self.dry_run: bool    = dry_run
        self.console: Console = console
        self.skipped: int     = 0

    async def run(self, *, description: str, action: Callable[[], Awaitable[None]]) -> None:
        if self.dry_run:
            self.console.print(f"[dim]would: {description}[/dim]")
            self.skipped += 1
            return
        await action()

    def finish(self) -> None:
        if self.dry_run:
            from rich.panel import Panel
            self.console.print(Panel.fit(f"Dry-run complete; {self.skipped} skipped.", style="yellow"))


# cli/confirm.py
async def require_confirmation(*, prompt: str, yes_flag: bool, console: Console) -> None:
    """Block until operator confirms; --yes skips; non-TTY without --yes raises CLIConfirmationDeclinedError."""
    if yes_flag:
        return
    if not sys.stdin.isatty():
        raise CLIConfirmationDeclinedError(message="Destructive command requires --yes in non-interactive mode.")
    from rich.prompt import Confirm
    if not Confirm.ask(prompt, console=console):
        raise CLIConfirmationDeclinedError(message="Operator declined.")
```

Never auto-confirm. Never `input(...)`. Never bypass on missing TTY.

---

## 13.5 `<project>/cli/__init__.py` MUST configure structlog to write to stderr

Default `structlog.PrintLoggerFactory()` writes to **`sys.stdout`**. Without explicit configuration, any `log.debug(...)` / `log.info(...)` call inside a CLI command pollutes the operator's stdout pipe — breaking the stdout-clean-on-failure invariant (§4) that lets `make cli-token-show | jq` work cleanly. Tests that assert `result.stdout.strip() == ""` on the failure path will fail for reasons unrelated to the failure path itself.

The fix is one declarative function in `<project>/cli/__init__.py` that runs once on package import. Canonical shape (mirror this in every new `cli/` package):

```python
# verifier/cli/__init__.py  (and deployment/cli/__init__.py — identical)

from __future__ import annotations
import os
import sys

try:
    import structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), os.environ.get("LOG_LEVEL", "WARNING").upper(), 30),
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),  # ← load-bearing
        cache_logger_on_first_use=True,
    )
except ModuleNotFoundError:  # operator-host fallback for hosts without structlog
    pass
```

**Why:** every `log.debug(...)` call across every CLI module lands on stderr by default. The operator's `make cli-token-show ENV=local | jq '.data.api_key'` works regardless of `LOG_LEVEL`. Tests asserting stdout cleanliness pass for the right reason.

**How to apply:** every new `cli/` package's `__init__.py` MUST include this block before any other `cli.*` module is imported. The `try/except ModuleNotFoundError` lets the package import even on operator hosts that don't have structlog installed yet (`cli_token_show` etc. degrade to silent logging in that case).

---

## 14. Forbidden imports

| Don't | Use instead |
|---|---|
| `argparse` | `typer` |
| `print()` | `console.print()` / `err_console.print()` |
| `requests` | `httpx.AsyncClient` |
| `httpx.Client` (blocking) | `httpx.AsyncClient` |
| `click` directly | `typer` (which wraps Click) |
| `time.sleep(...)` | `await asyncio.sleep(...)` |
| `asyncio.run(main())` inside a command | Nothing — `@handle_cli_errors` already calls `asyncio.run()` around the wrapped `async def` (Typer 0.25 itself does NOT auto-wrap) |
| `@dataclass` for config / state | `BaseSettings` (env) or `BaseModel` (state) |
| `subprocess.run(...)` for long-running | `asyncio.create_subprocess_exec` |
| `tabulate` | `rich.table.Table` |
| `tqdm` | `rich.progress.Progress` |
| `colorama` | Rich auto-detects ANSI capability |
| `json.dumps` for output | `console.print_json(data=...)` (syntax-highlighted) |
| `sys.exit(N)` | `raise typer.Exit(code=N)` |
| `input(...)` | `Confirm.ask(...)` (TTY-aware) |
| `response.json()` directly | `parse_envelope(response=...)` |

---

## 15. Tests — pytest-asyncio + pytest-httpx + CliRunner

`tests/cli/test_<module>.py` covers every Command class and every
verb. HTTP via `pytest-httpx`. Subprocess via `unittest.mock.patch`.
Filesystem via `tmp_path`.

**Why `CliRunner`:** in-process invocation, captures stdout + stderr
separately, asserts exit code. Click 8.2+ splits the streams by
default — **do not pass `mix_stderr`** (the kwarg was removed).

**Three test layers per module — each layer exists; concrete examples:**

```python
import json
import pytest
from typer.testing import CliRunner
from cli.verify_run import app, VerifyFlowCommand

runner = CliRunner()  # NOTE: no mix_stderr kwarg — removed in Click 8.2+

# Layer 1: per-Command class, async, mocked client
class TestVerifyFlowCommandTrigger:
    @pytest.mark.asyncio
    async def test_trigger_records_run_id_on_envelope_success(self, httpx_mock):
        httpx_mock.add_response(
            method="POST", url="http://leader:8001/api/v1/cli/verify-flow",
            json={"data": {"run_id": "abc-123", "was_existing": False},
                  "api_version": "1.0", "errors": {"msg": [], "code": None}},
        )
        cmd = VerifyFlowCommand(env="local", n=1, baselines=False, correlation_id="x")
        await cmd._trigger()
        assert cmd.run_id == "abc-123"

# Layer 2: per-verb, end-to-end, exit code asserted
class TestFlowVerbExitCodes:
    def test_flow_exit_3_on_auth_error(self, httpx_mock):
        httpx_mock.add_response(
            method="POST", status_code=401,
            json={"data": None, "api_version": "1.0",
                  "errors": {"msg": ["bad token"], "code": "CLI_AUTH_TOKEN_MISMATCH"}},
        )
        result = runner.invoke(app, ["flow", "--env", "local"])
        assert result.exit_code == 3
        assert "Authentication failed" in result.stderr

# Layer 3: --output=json parseability + SIGINT
class TestFlowOutputAndSignals:
    def test_trigger_json_output_is_parseable(self, httpx_mock):
        # arrange the trigger response, then:
        result = runner.invoke(app, ["trigger", "--env", "local", "--n", "1"])
        envelope = json.loads(result.stdout)
        assert set(envelope.keys()) == {"data", "api_version", "errors"}

    def test_flow_sigint_exits_130_with_resume_hint(self, httpx_mock):
        # Use os.kill(os.getpid(), signal.SIGINT) inside an httpx_mock callback
        result = runner.invoke(app, ["flow", "--env", "local"])
        assert result.exit_code == 130
        assert "python -m cli.verify_run poll" in result.stderr
```

**Mandatory coverage matrix per module:** happy path; every `CLIError`
subclass; `--dry-run`; `--yes` skip + decline; SIGINT; `--output=json`
parseability.

---

## 16. Companion modules `<project>/cli/` must ship

Each helper is its own file, ≤ 200 lines, unit-tested. Command modules
import; never reimplement.

```
cli/
  __init__.py
  client.py           — CLIClient(httpx.AsyncClient + Bearer header); from_config(config=...) factory
  config.py           — CLIConfig (BaseSettings); load_config(env=...)
  context.py          — contextvars: current_env, current_run_id (read by CLIInterruptHandler)
  dao/                — Pydantic BaseModels for request + response payloads (one file per route family)
  decorators.py       — @common_options (env, output, dry_run, yes, log_level)
  dry_run.py          — DryRunGate (async)
  confirm.py          — require_confirmation (async, TTY-aware)
  envelope.py         — parse_envelope(response=...) → data | raises CLI*Error
  error_handler.py    — @handle_cli_errors + CLIErrorRenderer + CLIInterruptHandler
  errors.py           — CLIError hierarchy + exit_code attribute
  output.py           — OutputFormat enum + render_envelope(envelope=, fmt=, console=)
  polling.py          — poll_until_terminal(client=, path=, ...) + PollResult (BaseModel, frozen)
  retry.py            — RetryPolicy + DEFAULT_RETRY + with_retry(...)
  token_loader.py     — read_token_file(env=...) → str
  sops_loader.py      — async sops decrypt/encrypt helpers (operator-side only)
```

Once structlog is added to `pyproject.toml`, helpers obtain loggers
via `structlog.get_logger("cli.<module>")` directly — there is no
`cli/_log.py` indirection.

---

## 17. Makefile delegation — recipe ≤ 4 lines, natural Make vars only

The Make target is a thin shim. The recipe validates env, loads env
vars, exports the operator's Make-var knobs as env vars, and invokes
Python. **The operator never types a Typer flag name** — they use
natural Make vars (`N=`, `GRADE=`, `BASELINES=`, `ENV_PROFILE_ID=`,
`DRY_RUN=`). The dispatch shim translates env vars to Typer flags.

**The canonical recipe shape:**

```make
.PHONY: verify-flow
verify-flow:
	$(call require_env)
	@set -a; . $(ENV_FILE); set +a; \
	  INCLUDE_BASELINES=$(or $(BASELINES),false) \
	  QUESTION_LIMIT=$(N) \
	  QUESTION_DIFFICULTIES=$(GRADE) \
	  VERIFIER_ENV_PROFILE_ID=$(ENV_PROFILE_ID) \
	  VERIFIER_DRY_RUN=$(DRY_RUN) \
	  PYTHONPATH=$(CURDIR) \
	  python3 -m cli.verify_flow_dispatch --env $(ENV)
```

**Operator-facing invocation:**

```bash
make verify-flow ENV=local GRADE=hard N=4
make verify-flow ENV=local GRADE=hard,medium,easy N=20 BASELINES=true
make verify-flow ENV=local GRADE=hard N=4 ENV_PROFILE_ID=<uuid>
make verify-flow ENV=local DRY_RUN=true
```

The operator never sees `--question-limit`, `--question-difficulty`,
`--baselines`, `--env-profile-id`, or `--dry-run` — those are Typer
internals exposed only when an explicit `ARGS="..."` escape hatch is
needed (e.g. CI passing a `--correlation-id` for a rerun).

**Rules:**

| Concern | Rule |
|---|---|
| Recipe length | ≤ 4 substantive lines including `$(call require_env)` |
| Env loading | `set -a; . $(ENV_FILE); set +a` (or `loadenv` if in an interactive-shell context) |
| Operator knobs | **Natural Make vars only** — `N=`, `GRADE=`, `BASELINES=`, etc. Never expose Typer flag names. |
| Env var naming | Match the bash runner's existing env-var names so dev mode keeps working without translation (`QUESTION_LIMIT`, `QUESTION_DIFFICULTIES`, `INCLUDE_BASELINES`) |
| Python invocation | Always `python -m cli.<module>`; never bare script path |
| `ARGS=` | Optional hidden escape hatch only — never the operator-facing UX |
| Subcommand selection | After `python -m cli.<module>`, the next positional is the verb (e.g. `flow`, `trigger`, `poll`) |
| Loops / conditionals in recipe | **None.** If you need them, the destination is `cli/<command>.py`. See [`build-cli-commands.md` §2](../build-cli-commands/SKILL.md). |

**Dispatch shims** (one verb that re-execs another) are themselves
Python — never bash. They MUST translate env vars to Typer flags so
the operator never sees Typer syntax. Boolean env vars accept
``true``/``1``/``yes`` (case-insensitive). Comma-separated lists
(`GRADE=hard,medium`) translate to repeated `--<flag> <value>` pairs.
Unset/blank env vars are dropped silently so the downstream command's
default applies.

**Skeleton (`cli/verify_flow_dispatch.py`):**

```python
"""Dispatch make verify-flow to dev (bash) or swarm (python CLI) by $VERIFIER_DEPLOY_MODE."""

from __future__ import annotations

import os
import sys
from typing import Annotated

import typer

app = typer.Typer(add_completion=False, no_args_is_help=False)

_TRUTHY = frozenset({"true", "1", "yes"})


def _build_swarm_argv(*, env: str, env_dict: dict[str, str]) -> list[str]:
    """Translate Make-var env vars to `cli.verify_run flow` flags."""
    argv: list[str] = [sys.executable, "-m", "cli.verify_run", "flow", "--env", env]

    n = env_dict.get("QUESTION_LIMIT", "").strip()
    if n:
        argv += ["--n", n]

    for grade in env_dict.get("QUESTION_DIFFICULTIES", "").split(","):
        grade = grade.strip()
        if grade:
            argv += ["--question-difficulty", grade]

    raw = env_dict.get("INCLUDE_BASELINES", "false").strip().lower()
    argv += ["--baselines" if raw in _TRUTHY else "--no-baselines"]

    profile_id = env_dict.get("VERIFIER_ENV_PROFILE_ID", "").strip()
    if profile_id:
        argv += ["--env-profile-id", profile_id]

    if env_dict.get("VERIFIER_DRY_RUN", "").strip().lower() in _TRUTHY:
        argv += ["--dry-run"]

    return argv


def main(
    ctx: typer.Context,
    env: Annotated[str, typer.Option(envvar="ENV")],
) -> None:
    """Re-exec into the real entry point. ctx.args is the hidden escape hatch."""
    mode: str = os.environ.get("VERIFIER_DEPLOY_MODE", "dev")
    if mode == "dev":
        os.execvpe("bash", ["bash", "scripts/verify_flow.sh", *ctx.args], env=os.environ)
    if mode == "swarm":
        argv = _build_swarm_argv(env=env, env_dict=dict(os.environ))
        argv.extend(ctx.args)
        os.execvpe(sys.executable, argv, env=os.environ)
    raise typer.Exit(code=1)


# allow_extra_args + ignore_unknown_options keeps the ARGS escape hatch alive
app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})(main)


if __name__ == "__main__":
    app()
```

`os.execvpe` replaces the current process — same PID, same TTY, same
signals. The operator's Ctrl-C reaches the real verb cleanly.

**Auto-resolution of required-but-resolvable IDs:** when a Typer flag
(e.g. `--env-profile-id`) is required by the downstream command but
resolvable from the API in the common case, make it OPTIONAL on the
Typer command and resolve it inside the Command class's `execute()`
BEFORE the first side effect. See
`cli/env_profile_resolver.py` for the canonical pattern (one method,
typed errors for zero / multiple matches). The operator can still
override via `<ID_VAR>=<uuid>` on the Make invocation.

---

## 18. Conventions checklist

Before opening a PR:

**Command class structure** (naming, `__init__`/`build`/`execute` triad,
`execute()` discipline, Typer function naming, async helper naming, file
layout, `run_async` import): **see [`build-cli-command-class.md` checklist](../build-cli-command-class/SKILL.md).**

**Module-level and implementation checks (this file):**

- [ ] `app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode="rich", pretty_exceptions_enable=False)`
- [ ] Every `@app.command()` function is sync (`def`, not `async def`); one line: `run_async(_verb_async)(...)`
- [ ] `@handle_cli_errors` on the **async body** (`_verb_async`), not on the Typer function
- [ ] `run_async` imported from `cli/error_handler.py`; never reimplemented
- [ ] `KeyboardInterrupt` not caught in helpers — propagates to the decorator
- [ ] `httpx.AsyncClient` everywhere; `await asyncio.sleep`; no manual `asyncio.run()`
- [ ] Config is `BaseSettings` (CLIConfig); state is `BaseModel(frozen=True)`; no `@dataclass`
- [ ] All HTTP via `CLIClient.from_config(...)`; all responses via `parse_envelope(...)`
- [ ] Long-running ops use `poll_until_terminal()`; paired `poll` subcommand for resume
- [ ] `RetryPolicy` honoured; budget → `CLITimeoutError`
- [ ] Two consoles: `Console()` for data, `Console(stderr=True)` for status; no `print()`
- [ ] `--output=human/json/yaml` honoured via `render_envelope()`; token never in either stream
- [ ] `--dry-run` gates every side effect via `DryRunGate.run()`; `--yes` on destructive ops; non-TTY without `--yes` fails closed
- [ ] `correlation_id` body field on every mutating POST (see [`build-cli-commands.md` §18](../build-cli-commands/SKILL.md))
- [ ] Make recipe ≤ 4 lines, `loadenv` first, `python -m cli.<module> <verb> --env $(ENV) $(ARGS)`; no loops or conditionals in the recipe
- [ ] `tests/cli/test_<module>.py` covers: happy path, every `CLIError` subclass, `--dry-run`, `--yes` decline, SIGINT, `--output=json` parseability
- [ ] `CliRunner()` with no `mix_stderr` kwarg; HTTP mocked via `pytest-httpx`; per-Command tests use `@pytest.mark.asyncio`
