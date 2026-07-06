---
name: build-cli-command-class
description: 'Mandatory conventions for every Command class in a project''s cli/:
  class naming, the three required methods, execute() discipline, file layout, and
  the async-helper / Typer-function naming chain that ties everything together.'
when_to_use: Use when authoring or revising a single CLI command class; pair with
  build-cli-modules for the surrounding module shape.
group: cli
kind: skill
source_prompt: cli/build-cli-command-class.md
---

# CLI Command Classes — Structure, Lifecycle, and Naming

## Skill summary

- **Name:** `build-cli-command-class`
- **Description:** Mandatory conventions for every Command class in a project's cli/: class naming, the three required methods, execute() discipline, file layout, and the async-helper / Typer-function naming chain that ties everything together.
- **When to use:** Use when authoring or revising a single CLI command class; pair with build-cli-modules for the surrounding module shape.
- **Group:** `cli`
- **Kind:** `skill`
- **Source prompt:** `cli/build-cli-command-class.md`

## Examples

- The user asks: "Add or revise the cli command class for this feature."
- You want the canonical build pattern before touching cli command class.

## Guidance

Mandatory conventions for every `Command` class in `<project>/cli/`. This
document covers **the class itself**: naming, the three required methods,
`execute()` discipline, file layout, and the async helper / Typer function
naming chain that ties everything together.

Companion documents — read these; do not expect this file to duplicate them:

- [`build-cli-modules.md`](../build-cli-modules/SKILL.md) — full module shape, stack rules, `@handle_cli_errors`, argument patterns, two-console discipline, polling, retry, tests.
- [`build-cli-commands.md`](../build-cli-commands/SKILL.md) — Makefile shape, CLI → router → AppService layering, auth, idempotency.
- ``skills/coding/declarative-method-structure/SKILL.md`` — Tell-don't-ask, one decision per method, orchestrator = table of contents.
- ``skills/coding/named-arguments-and-type-hints/SKILL.md`` — every parameter typed, every call site named.
- ``skills/coding/method-docstrings/SKILL.md`` — Google-style docstrings on every public and protected method.

The canonical reference implementation is
`verifier/cli/verify_run.py` — `VerifyFlowCommand`, `TriggerCommand`,
`PollCommand`, `DashboardCommand`, and their shared base
`_BaseVerifyCommand`. Read that file before writing a new Command class.

---

## Rule 1 — The `Command` suffix is mandatory

Every CLI command class MUST be named `<ConceptInPascalCase>Command`.

| Good | Bad |
|---|---|
| `VerifyFlowCommand` | `VerifyFlow` |
| `TriggerCommand` | `Trigger` |
| `PollCommand` | `Poller` |
| `DashboardCommand` | `DashboardRunner` |
| `CLITokenRotateCommand` | `TokenRotator` |

**Why:** the `Command` suffix signals to any reader — immediately, without
reading the body — that this class is an operator-invokable entry point.
It is not a service, not a utility, not a DAO. Without the suffix, every
reader must inspect the class to determine its role. With it, the intent is
self-documenting.

---

## Rule 2 — Three required methods: `__init__`, `build`, `execute`

Every Command class implements exactly these three. No exceptions.

| Method | Role | Caller |
|---|---|---|
| `__init__` | Accept fully-resolved dependencies; assign typed `self.*` attributes | `build` (and tests that need to construct directly) |
| `build` | `@classmethod async def` — resolve config + client, then call `cls(...)` | The async command body (e.g. `_verify_flow_async`) |
| `execute` | The command entry point; reads like a table of contents; delegates to named helpers | `build` result + `try/finally: await command.aclose()` |

### `__init__` rules

- Keyword-only arguments (`*` before first arg).
- Every parameter type-hinted; every `self.*` assignment type-hinted.
- No I/O, no network calls, no `async` work. Pure assignment.
- Construct internal objects (e.g. `DryRunGate`, `Console`) here — they
  are dependencies, not resolvable asynchronously.

```python
def __init__(
    self,
    *,
    env: str,
    config: CLIConfig,
    client: CLIClient,
    env_profile_id: UUID | None,
    question_limit: int,
    correlation_id: str,
    output: OutputFormat,
    dry_run: bool,
) -> None:
    """Initialise with the full set of flow arguments."""
    super().__init__(env=env, config=config, client=client, output=output)
    self.env_profile_id: UUID | None = env_profile_id
    self.question_limit: int = question_limit
    self.correlation_id: str = correlation_id
    self.dry_run: bool = dry_run
    self.gate: DryRunGate = DryRunGate(dry_run=dry_run, console=self.err_console)
```

### `build` rules

- `@classmethod async def`.
- Keyword-only arguments (`*` before first arg).
- Exactly two responsibilities: (1) resolve config + client via `await
  load_config(env=env)` and `CLIClient.from_config(config=config)`; (2)
  call `cls(...)` with all resolved values.
- Must NOT perform any business logic. It is a factory only.
- Return type is the concrete Command class (quoted string for
  forward reference on Python ≤ 3.11).

```python
@classmethod
async def build(
    cls,
    *,
    env: str,
    env_profile_id: UUID | None,
    question_limit: int,
    correlation_id: str,
    output: OutputFormat,
    dry_run: bool,
) -> "VerifyFlowCommand":
    """Resolve config + client and instantiate the command."""
    config: CLIConfig = await load_config(env=env)
    client: CLIClient = CLIClient.from_config(config=config)
    return cls(
        env=env,
        config=config,
        client=client,
        env_profile_id=env_profile_id,
        question_limit=question_limit,
        correlation_id=correlation_id,
        output=output,
        dry_run=dry_run,
    )
```

### `execute` rules

- `async def execute(self) -> None`.
- Body is 5–10 lines of named method calls. Absolutely no inline logic.
- No conditionals deeper than one level. Every branch delegates to a named
  helper with a descriptive name.
- Reads like a table of contents: a new developer understands the entire
  command flow in under 30 seconds without reading helpers.
- **The word is `execute`.** Not `invoke`, `run`, `trigger`, `start`,
  `dispatch`. See Rule 10 for the full rationale.

```python
async def execute(self) -> None:
    """Resolve → trigger → poll → dashboard. Reads like a table of contents."""
    CLIInterruptHandler.set_context(env=self.env, run_id=None)
    await self._resolve_env_profile_id()
    assert self.env_profile_id is not None
    run_id: str | None = await self._trigger(
        env_profile_id=self.env_profile_id,
        question_limit=self.question_limit,
        correlation_id=self.correlation_id,
        gate=self.gate,
    )
    if run_id is None:
        self.gate.finish()
        return
    await self._poll_until_terminal(run_id=run_id)
    await self._print_dashboard(run_id=run_id)
```

### `aclose` — required when the class owns a client

If the Command class owns or inherits a `CLIClient`, it MUST expose an
async teardown:

```python
async def aclose(self) -> None:
    """Close the underlying async HTTP client."""
    await self.client.aclose()
```

Callers always close inside a `finally`:

```python
command: VerifyFlowCommand = await VerifyFlowCommand.build(...)
try:
    await command.execute()
finally:
    await command.aclose()
```

---

## Rule 3 — `execute` must read like a table of contents

This is a restatement of the
``skills/coding/declarative-method-structure/SKILL.md``
orchestrator rule applied specifically to CLI commands. It is repeated here
because it is the most commonly violated rule in this layer.

The test: can you describe what `execute` does in one sentence? If the
answer contains the word "and" more than twice, the method has too much
inline logic. Extract named steps.

**Bad — inline logic, three concerns tangled in one method:**

```python
async def execute(self) -> None:
    if self.env_profile_id is None:
        resolver = EnvProfileResolver(client=self.client)
        resolved = await resolver.resolve_single_active()
        self.env_profile_id = UUID(resolved)
    body = {
        "correlation_id": self.correlation_id,
        "environment_profile_id": str(self.env_profile_id),
        "question_limit": self.question_limit,
    }
    response = await self.client.post(path="/api/v1/cli/verify-flow", json=body)
    data = parse_envelope(response=response)
    run_id = data["run_id"]
    self.err_console.print(f"run_id={run_id}")
    # ... 20 more lines of polling and dashboard logic
```

**Good — five named steps, zero ambiguity:**

```python
async def execute(self) -> None:
    """Resolve → trigger → poll → dashboard. Reads like a table of contents."""
    await self._resolve_env_profile_id()
    run_id: str | None = await self._trigger(...)
    if run_id is None:
        self.gate.finish()
        return
    await self._poll_until_terminal(run_id=run_id)
    await self._print_dashboard(run_id=run_id)
```

**Rule of eight:** if a method body exceeds ~8 lines of substantive logic
(excluding docstring and blank lines), it is doing too much. Extract named
steps. This applies to `execute` and to every private helper.

---

## Rule 4 — File layout: one command per file; folder when a base class exists

### Simple command (no shared base class)

Everything in a single file: the Typer `app`, the `@app.command()`
function(s), the async body/bodies, and the Command class.

```
cli/
  verify_run.py          # app, verify_flow(), _verify_flow_async(), VerifyFlowCommand
```

### Multiple commands sharing a base class

Use a folder. The base class has its own file; each concrete Command class
lives in `command.py` alongside the Typer wiring.

```
cli/
  verify_run/
    __init__.py          # re-exports app for `python -m cli.verify_run`
    _base.py             # _BaseVerifyCommand (shared helpers + wiring)
    command.py           # VerifyFlowCommand, TriggerCommand, PollCommand,
                         # DashboardCommand, app, @app.command() verbs,
                         # _*_async bodies, if __name__ == "__main__": app()
```

The current state of `verifier/cli/verify_run.py` — all four Command
classes in one flat file — is acceptable while the surface is small. If a
fifth command is added, split into the folder layout. Do not wait for six.

### Shared CLI utilities

`run_async`, `handle_cli_errors`, `CLIClient`, `CLIConfig`, etc. live in
their own dedicated modules under `cli/` (see `build-cli-modules.md` §16).
Never inline shared utilities inside a command file.

---

## Rule 5 — Typer function name must mirror the Make target

The Typer function registered with `@app.command()` MUST be the snake_case
version of the Make target name. The Make target is the operator-facing
canonical name. The Python function derives from it.

| Make target | Typer function name | Bad names |
|---|---|---|
| `make verify-flow` | `verify_flow` | `flow`, `run`, `verify` |
| `make trigger` | `trigger` | `start`, `fire` |
| `make dashboard` | `dashboard` | `show`, `render` |
| `make cli-token-rotate` | `cli_token_rotate` | `rotate`, `token_rotate` |

**Bad:**

```python
@app.command()
def flow(env: ...) -> None:          # Make target is `verify-flow`; wrong name
    run_async(_flow_async)(...)
```

**Good:**

```python
@app.command()
def verify_flow(env: ...) -> None:   # snake_case of `verify-flow`
    run_async(_verify_flow_async)(...)
```

Note: Typer auto-converts Python function underscores to hyphens for the CLI
verb — `def verify_flow(...)` registers as the CLI command `verify-flow`, so
`runner.invoke(app, ["verify-flow", ...])` and the dispatch constant
`_SWARM_FLOW_VERB = "verify-flow"` both use the hyphenated form.

**Why:** operators reading the Python source must be able to trace from
`make verify-flow` to the Python function without a mental mapping step. A
drift between Make target and function name is a maintenance hazard —
especially when multiple targets share a module.

---

## Rule 6 — Async helper naming: `_<typer_function_name>_async`

The async implementation of a Typer command is a private function named
by the formula:

```
_<typer_function_name>_async
```

| Typer function | Async helper |
|---|---|
| `verify_flow` | `_verify_flow_async` |
| `trigger` | `_trigger_async` |
| `poll` | `_poll_async` |
| `dashboard` | `_dashboard_async` |
| `cli_token_rotate` | `_cli_token_rotate_async` |

**The current codebase has a known violation:** `verify_run.py` uses
`_flow_async` (matching the incorrect `flow` Typer function name) instead
of `_verify_flow_async`. Fix both together when the function is renamed.

**Bad:**

```python
@app.command()
def flow(...) -> None:
    run_async(_flow_async)(...)      # helper name doesn't derive from Make target
```

**Good:**

```python
@app.command()
def verify_flow(...) -> None:
    run_async(_verify_flow_async)(...) # helper name = _ + Typer function name + _async
```

**Why:** the three names form a traceable chain:

```
make verify-flow  →  verify_flow()  →  _verify_flow_async()  →  VerifyFlowCommand.build().execute()
```

Breaking the chain at any link forces a reader to grep rather than read.

### Async helper structure

The async helper is thin. It builds the Command and executes it. Nothing
else.

```python
@handle_cli_errors
async def _verify_flow_async(
    *,
    env: str,
    env_profile_id: UUID | None,
    question_limit: int,
    correlation_id: str | None,
    output: OutputFormat,
    dry_run: bool,
) -> None:
    """Async body for the ``verify_flow`` command."""
    command: VerifyFlowCommand = await VerifyFlowCommand.build(
        env=env,
        env_profile_id=env_profile_id,
        question_limit=question_limit,
        correlation_id=correlation_id or str(uuid4()),
        output=output,
        dry_run=dry_run,
    )
    try:
        await command.execute()
    finally:
        await command.aclose()
```

`@handle_cli_errors` goes on the **async body** (`_verify_flow_async`),
NOT on the Typer function (`verify_flow`). The Typer function is
synchronous — the decorator wraps an awaitable; applying it to a sync
function does nothing useful.

---

## Rule 7 — `run_async` is a shared utility; never copy-paste it

`run_async` (the thin wrapper that calls `asyncio.run()` around the async
body so Typer can invoke it as a sync callback) lives in one place:
`cli/error_handler.py` in the current codebase. Import it; never
reimplement it.

```python
from cli.error_handler import handle_cli_errors, run_async
```

When `cli/base.py` is introduced (the canonical long-term home), move
`run_async` there and update all imports. Until then, `error_handler.py`
is the source of truth.

**Never:**

```python
# Do NOT copy-paste this into a command file
def run_async(coro_fn):
    @functools.wraps(coro_fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_fn(*args, **kwargs))
    return wrapper
```

---

## Rule 8 — `app` and `__main__` block live in the same file as the command

Every command file ends with:

```python
app: typer.Typer = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
    help="One-line description of what this module's commands do.",
)


@app.command()
def verify_flow(...) -> None:
    """One-line summary for --help."""
    run_async(_verify_flow_async)(...)


if __name__ == "__main__":
    app()
```

The `app` object and `if __name__ == "__main__"` block are NOT split into a
separate file. A reader must be able to trace from the Typer registration to
the Command class without crossing files (except the shared base, if any).

---

## Rule 9 — Class docstring MUST explain purpose, invoker, side effects, and host workflow

**Stop writing useless class docstrings.** Restating the class name in
English (``"""Async HTTP client."""``) tells a reader nothing they did
not already know from the symbol. The class docstring is the *only*
place where a reader without prior context can answer the four questions
that determine whether this is the class they care about:

1. **Purpose** — what does this class *do*, in domain terms? Not
   "wraps httpx" — that's an implementation detail. "Issues the
   HTTP calls that drive the verifier's CLI dashboard" is purpose.
2. **Invoker** — who instantiates it / what triggers its creation?
   A Typer command body? A factory method on another Command class?
   An async helper? Name the call site.
3. **Launches** — what does ``execute()`` (or the equivalent verb)
   *actually do*? Which HTTP routes? Which subprocesses? Which
   Make targets does it `os.execvpe` into? Which DBOS jobs does it
   trigger? Name the side effects.
4. **Part of** — which bigger operator-facing workflow does this
   class participate in? ``make verify-flow``? ``make
   cli-token-rotate``? Name the operator command. A reader who lands
   on the class from a stack trace must be able to trace upward to
   the operator's keystroke without grepping.

The ``Attributes:`` block stays — it documents the typed instance
state. But the *body* of the docstring must answer the four questions
in plain prose.

### Bad — restates the symbol; tells the reader nothing

```python
class CLIClient:
    """Async HTTP client for ``/api/v1/cli/*`` routes.

    Attributes:
        base_url (str): The verifier API base URL.
        retry (RetryPolicy): The retry policy applied to every call.
    """
```

A new reader looking at this knows: nothing they could not infer from
the class name. Who builds one? Who calls ``.get()``? Which workflow
ends in this class? Silence.

### Good — answers the four questions

```python
class CLIClient:
    """Issues the HTTP calls that back every operator-facing verifier CLI verb.

    **Purpose:** thin async wrapper around ``httpx.AsyncClient`` that
    bakes the Bearer token, the retry policy, and the canonical
    error-translation rules into every request, so Command classes can
    say ``await self.client.post(...)`` without re-implementing auth
    or backoff each time.

    **Invoker:** built by :meth:`CLIClient.from_config` inside every
    ``Command.build`` factory in ``cli/verify_run/command.py`` and
    ``cli/cli_token.py``. Tests inject a pre-built ``httpx.AsyncClient``
    via the constructor's ``client`` parameter.

    **Launches:** issues ``GET`` / ``POST`` against
    ``{base_url}/api/v1/cli/*`` routes on the deployed verifier API.
    Every response is passed through :func:`cli.envelope.parse_envelope`
    by the caller, which raises a typed :class:`CLIError` subclass on
    any non-success envelope.

    **Part of:** ``make verify-flow`` (and the recovery siblings
    ``verify-trigger`` / ``verify-poll`` / ``verify-dashboard``); also
    ``make cli-token-rotate`` for the verifier-deploy step.

    Attributes:
        base_url (str): The verifier API base URL.
        retry (RetryPolicy): The retry policy applied to every call.
    """
```

Now a reader landing on ``CLIClient`` understands what it does, who
makes one, what it actually talks to over the network, and which
operator command pulls the trigger — without opening another file.

### Where this rule applies

- Every ``Command`` class.
- Every helper class invoked by a Command (``CLIClient``,
  ``EnvProfileResolver``, ``DryRunGate``, ``RetryPolicy``,
  ``PollResult``, ``CLIErrorRenderer``, ``CLIInterruptHandler``,
  ``CLIConfig``, ``CLISettings``).
- Every typed exception class. A ``CLIError`` subclass docstring must
  name (a) the failure mode that raises it, (b) the call site that
  detects it, and (c) the exit code the operator sees.

### When the four-block prose is overkill

For trivial structural classes — a Pydantic ``BaseModel`` that is a
pure data container with no behaviour — a single sentence stating its
role is enough, *provided* the role names the producer and the
consumer:

```python
class PollResult(BaseModel):
    """Frozen terminal-state envelope returned by :func:`poll_until_terminal`
    to the Command class's ``_poll_until_terminal`` helper.

    Attributes: ...
    """
```

This sentence tells you who builds it (``poll_until_terminal``) and
who reads it (the Command). That is enough for a pure DAO. The full
four-block prose is required the moment the class has behaviour
beyond storing fields.

---

## Rule 10 — `execute` is the canonical verb; no synonyms

The top-level command entry point is always named `execute`. It is never:

| Forbidden name | Why it's wrong |
|---|---|
| `invoke` | That is the Application Service lifecycle method. CLI commands use `execute` to distinguish the layer. |
| `run` | Ambiguous — Python's `threading.Thread` + `multiprocessing.Process` both use `run`. |
| `trigger` | That is a sub-operation verb used for private helpers that fire a POST. |
| `start` | Implies a long-running background process, not a command. |
| `dispatch` | Reserved for shim modules that re-exec into another command. |

**Exception — private helpers may and should use descriptive verbs:**

```python
async def execute(self) -> None:        # top-level entry point: always execute
    await self._resolve_env_profile_id() # private helper: named for the operation
    run_id = await self._trigger(...)    # private helper: named for what it does
    await self._poll_until_terminal(run_id=run_id)
    await self._print_dashboard(run_id=run_id)
```

Private helpers (`_trigger`, `_poll_until_terminal`, `_print_dashboard`,
`_resolve_env_profile_id`, `_confirm`, `_generate_token`, etc.) use the
most descriptive verb available. The restriction on synonyms applies only
to the public entry point `execute`.

---

## Anti-patterns

### Violation 1 — Typer function name doesn't match the Make target

**Bad (`make verify-flow` but function named `flow`):**

```python
# verifier/cli/verify_run.py — current known violation
@app.command()
def flow(env: ...) -> None:
    run_async(_flow_async)(...)
```

**Good:**

```python
@app.command()
def verify_flow(env: ...) -> None:
    run_async(_verify_flow_async)(...)
```

Fix: rename the function and the async helper together. The `app.command()`
decorator uses the function name as the CLI verb — changing this is a
breaking change for scripts that call `python -m cli.verify_run flow`
directly, so coordinate with any CI scripts before renaming.

---

### Violation 2 — Async helper name doesn't derive from Typer function

**Bad:**

```python
@app.command()
def verify_flow(...) -> None:
    run_async(_flow_async)(...)      # _flow_async ≠ _verify_flow_async
```

**Good:**

```python
@app.command()
def verify_flow(...) -> None:
    run_async(_verify_flow_async)(...) # name matches
```

---

### Violation 3 — Inline logic in `execute`

**Bad — resolver, body assembly, HTTP, and side effects all in `execute`:**

```python
async def execute(self) -> None:
    if self.env_profile_id is None:
        resolver = EnvProfileResolver(client=self.client)
        resolved = await resolver.resolve_single_active()
        self.env_profile_id = UUID(resolved)
    body = {
        "correlation_id": self.correlation_id,
        "environment_profile_id": str(self.env_profile_id),
    }
    self.err_console.print("Triggering…")
    response = await self.client.post(
        path="/api/v1/cli/verify-flow", json=body
    )
    data = parse_envelope(response=response)
    run_id = data["run_id"]
    self.run_id = run_id
    CLIInterruptHandler.set_context(env=self.env, run_id=run_id)
    while True:
        r = await self.client.get(path=f"/api/v1/cli/runs/{run_id}")
        d = parse_envelope(response=r)
        if d["status"] in {"succeeded", "failed", "cancelled"}:
            break
        await asyncio.sleep(self.config.cli_poll_interval_seconds)
    response2 = await self.client.get(
        path=f"/api/v1/cli/runs/{run_id}/dashboard"
    )
    render_envelope(envelope=parse_envelope(response=response2), ...)
```

**Good — each step named and extracted:**

```python
async def execute(self) -> None:
    """Resolve → trigger → poll → dashboard."""
    CLIInterruptHandler.set_context(env=self.env, run_id=None)
    await self._resolve_env_profile_id()
    assert self.env_profile_id is not None
    run_id: str | None = await self._trigger(
        env_profile_id=self.env_profile_id,
        question_limit=self.question_limit,
        correlation_id=self.correlation_id,
        gate=self.gate,
    )
    if run_id is None:
        self.gate.finish()
        return
    await self._poll_until_terminal(run_id=run_id)
    await self._print_dashboard(run_id=run_id)
```

---

### Violation 4 — Multiple unrelated Command classes in one file without a base

**Bad:** `PollCommand` and `VerifyFlowCommand` in the same file when they
share no base class and serve logically distinct verbs from separate Make
targets.

**Good:** if the commands share helpers, extract a `_Base<Name>Command`.
If they share no logic at all, give each its own file. The threshold: when
the file exceeds ~300 lines or adding a new command would push past that,
split into the folder layout described in Rule 4.

The current `verifier/cli/verify_run.py` is at the boundary: four Command
classes sharing `_BaseVerifyCommand`, all in one file. This is acceptable
now but marks the point at which the folder layout should be adopted for
any further additions.

---

### Violation 5 — Using `invoke` as the Command entry point

**Bad (carry-over from Application Services):**

```python
async def invoke(self) -> None:
    await self._trigger()
    await self._poll_until_terminal()
    await self._print_dashboard()
```

**Good:**

```python
async def execute(self) -> None:
    await self._trigger()
    await self._poll_until_terminal()
    await self._print_dashboard()
```

`invoke` is the Application Service lifecycle method (see
`skills/coding/build-application-services/SKILL.md`). CLI Command classes use `execute` so the
two layers are immediately distinguishable. Never import the verb from the
wrong layer.

---

## File structure: canonical example

For a `verify-run` command group with four verbs sharing a base:

```
verifier/cli/
  __init__.py                        # structlog → stderr (§13.5 of build-cli-modules.md)
  client.py
  config.py
  error_handler.py                   # run_async, @handle_cli_errors
  errors.py
  output.py
  polling.py
  ...
  verify_run.py                      # ← current: flat file with all 4 Command classes
                                     #   acceptable now; split to folder at 5th command
```

Future folder layout (when the fifth command is added):

```
verifier/cli/
  verify_run/
    __init__.py                      # re-exports: from cli.verify_run.command import app
    _base.py                         # _BaseVerifyCommand
    command.py                       # VerifyFlowCommand, TriggerCommand, PollCommand,
                                     # DashboardCommand, app, verbs, __main__
```

---

## The full naming chain — four links, no gaps

```
make verify-flow
    ↓
verify_flow()                        # @app.command(); snake_case of Make target
    ↓
run_async(_verify_flow_async)(...)   # _ + Typer function name + _async
    ↓
VerifyFlowCommand.build(...).execute()  # PascalCase of Make target + Command
```

Every link in this chain must be traceable by reading. If any name breaks
the pattern, a reader must grep. Greps are a sign that the naming
convention was not followed.

---

## Checklist — before merging a new CLI command

- [ ] Class name ends with `Command` and is PascalCase of the Make target name.
- [ ] `__init__` is keyword-only, all-typed, no I/O, no async work.
- [ ] `build` is `@classmethod async def`; resolves config + client only; calls `cls(...)`.
- [ ] `execute` body is 5–10 lines; delegates every decision to a named `_helper`; no inline logic; no conditionals deeper than one level.
- [ ] `aclose` closes the HTTP client; callers wrap in `try/finally`.
- [ ] Typer function name is the snake_case of the Make target (e.g. `verify-flow` → `verify_flow`).
- [ ] Async helper name is `_<typer_function_name>_async` (e.g. `_verify_flow_async`).
- [ ] `@handle_cli_errors` is on the async body, NOT on the Typer function.
- [ ] `run_async` is imported from `cli/error_handler.py`; not reimplemented.
- [ ] `app` and `if __name__ == "__main__": app()` live in the same file as the command class.
- [ ] No method named `invoke`, `run`, `trigger`, `start`, or `dispatch` at the public entry point.
- [ ] Private helper methods use descriptive verb names (`_trigger`, `_poll_until_terminal`, `_resolve_env_profile_id`, etc.).
- [ ] Class docstring answers all four questions: **Purpose / Invoker / Launches / Part of** (Rule 9). Restating the class name in English is a violation.
- [ ] Every method has a Google-style docstring (see ``skills/coding/method-docstrings/SKILL.md``).
- [ ] Every call site uses named arguments (see ``skills/coding/named-arguments-and-type-hints/SKILL.md``).
- [ ] Tests cover: happy path via `VerifyFlowCommand.build(...).execute()` (mocked client); each private helper individually; the Typer verb via `CliRunner`.
