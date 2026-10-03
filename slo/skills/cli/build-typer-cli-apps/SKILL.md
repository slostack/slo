---
name: build-typer-cli-apps
description: Building user-facing Python CLIs under src/cli with Typer + Rich, including
  detailed delegation patterns, examples, and implementation walkthroughs for default
  TUI launch and subcommands.
when_to_use: Use when building or revising a user-facing Typer CLI under `src/cli/`,
  especially when it launches a TUI or delegates through `TyperDispatch`.
group: cli
kind: skill
source_prompt: cli/build-typer-cli-apps.md
---

# Build Typer + Rich Application CLIs

## Skill summary

- **Name:** `build-typer-cli-apps`
- **Description:** Building user-facing Python CLIs under src/cli with Typer + Rich, including detailed delegation patterns, examples, and implementation walkthroughs for default TUI launch and subcommands.
- **When to use:** Use when building or revising a user-facing Typer CLI under `src/cli/`, especially when it launches a TUI or delegates through `TyperDispatch`.
- **Group:** `cli`
- **Kind:** `skill`
- **Source prompt:** `cli/build-typer-cli-apps.md`

## Examples

- The user asks: "Add or revise the typer cli apps for this feature."
- You want the canonical build pattern before touching typer cli apps.

## Guidance

This document defines the conventions for **application-facing Python CLIs** built under `src/cli/` with **Typer** as the parse surface and **Rich** as the output layer.

These rules are derived from Slo's `src/cli/` design:

- `src/cli/app.py`
- `src/cli/typer_dispatch.py`
- `src/cli/version.py`
- `src/cli/update.py`
- `tests/cli/test_app.py`
- `tests/cli/test_typer_dispatch.py`

> Use this file for **product CLIs** — commands the end user runs directly, especially when bare invocation opens a Textual TUI. For operator / deployment CLIs (`make ...`, control-plane verbs, `Command` classes), read `build-cli-commands.md`, `build-cli-modules.md`, and `build-cli-command-class.md` instead.

---

## 1. Core idea

A good app CLI separates **parsing** from **runtime assembly** from **feature logic**.

It should be possible to answer these three questions in three different files:

1. **What did the user type?**
   - `src/cli/app.py`
2. **What runtime objects do we need?**
   - `src/cli/typer_dispatch.py`
3. **What actually happens?**
   - `src/cli/version.py`, `src/cli/update.py`, `src/tui/app.py`, app services, etc.

That split is the main pattern.

---

## 2. Golden architecture

```text
console script / python -m
-> src/cli/__main__.py
-> src/cli/__init__.py:main
-> src/cli/app.py                # Typer declarations only
-> src/cli/typer_dispatch.py     # path/config/session/runtime assembly
-> helper / service / TUI module # actual behavior
```

### Responsibility map

| Layer | Canonical file | Responsibility |
|---|---|---|
| Entry point | `src/cli/__main__.py` | `SystemExit(main())` handoff for `python -m` |
| Export | `src/cli/__init__.py` | expose the single `main()` used by packaging and tests |
| Parse surface | `src/cli/app.py` | Typer app, callback, options, subcommands, tiny wrappers |
| Dispatch | `src/cli/typer_dispatch.py` | resolve paths/env/config, construct runtime objects, call downstream code |
| Feature helpers | `src/cli/version.py`, `src/cli/update.py`, `src/cli/<feature>.py` | isolated logic with narrow concerns |

### Why this is worth the ceremony

Without this split, every new command turns `app.py` into a dumping ground:

- help/version become slow
- tests need full app boot just to assert routing
- TUI startup leaks logs into the terminal
- path/env defaults get reimplemented in every command
- session creation gets copy-pasted across subcommands

With this split:

- `--help` and shell completion stay cheap
- TUI launch is predictable
- `CliRunner` tests stay surface-level
- runtime assembly is unit-testable below Typer

---

## 3. Canonical folder layout

```text
src/cli/
├── __init__.py
├── __main__.py
├── app.py
├── typer_dispatch.py
├── version.py
└── <feature>.py

tests/cli/
├── test_app.py
├── test_typer_dispatch.py
└── test_<feature>.py
```

### Rules

| Rule | Detail |
|---|---|
| `__main__.py` stays tiny | Import `main`, then `raise SystemExit(main())` |
| `__init__.py` exports `main` | both console-script and `python -m` paths converge |
| `app.py` owns Typer only | no sessions, services, clients, or large conditionals |
| dispatch sits next to the app | runtime assembly should be easy to find |
| helper modules stay narrow | version/update/bootstrap constraints get dedicated files |

---

## 4. Exact standards for `app.py`

`src/cli/app.py` is the **parse surface**.

### `app.py` may contain

- `typer.Typer(...)`
- `@app.callback(...)`
- `@app.command(...)`
- a custom `TyperGroup` if parse disambiguation is unavoidable
- tiny wrappers that call dispatch helpers
- very small early-exit flows like `--version`

### `app.py` may **not** contain

- session construction
- API client construction
- log context setup
- `asyncio` task orchestration
- uvicorn launch details
- Rich table/panel rendering
- large decision trees about runtime behavior

### Bad

```python
@app.command()
def run(workdir: Path | None = None) -> None:
    resolved_workdir = (workdir or Path.cwd()).resolve()
    config = SessionConfigDAO(workdir=resolved_workdir)
    session = SloAgentSession.build(config=config)
    with interactive_logging(...):
        SloTUI(session=session).run()
```

Why it is bad:

- parsing and path resolution are mixed
- config creation is mixed in
- logging policy is mixed in
- TUI boot is mixed in
- the command surface cannot be tested without knowing runtime details

### Good

```python
@app.command(name="serve")
def _serve(
    port: int = typer.Option(7700, "--port"),
) -> None:
    """Run the health app."""
    TyperDispatch.serve(port=port)
```

### Also good

```python
@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    workdir: Path | None = typer.Argument(None),
    version: bool = typer.Option(False, "--version", is_eager=True),
) -> None:
    if version:
        typer.echo(message=resolve_version())
        raise typer.Exit(code=0)
    if ctx.invoked_subcommand is not None:
        return
    TyperDispatch.tui(workdir=workdir)
```

This keeps the root flow readable without embedding runtime assembly.

---

## 5. Exact standards for `typer_dispatch.py`

`src/cli/typer_dispatch.py` owns **runtime assembly**.

### Dispatch methods should do things like

- resolve `Path.cwd()` defaults
- normalize user input into concrete paths
- read env/config
- construct DTOs / config objects
- build sessions / services
- enter log-isolation contexts
- call TUI `.run()`
- invoke uvicorn or helper modules

### Dispatch methods should not do things like

- duplicate Typer parsing logic
- know about help text
- hard-code terminal copy intended for Typer help
- become giant feature modules themselves

### Canonical shape

```python
class TyperDispatch:
    @classmethod
    def tui(cls, *, workdir: Path | None) -> None:
        resolved_workdir: Path = (workdir or Path.cwd()).resolve()
        with interactive_logging(...):
            config: SessionConfigDAO = cls._build_session_config(
                workdir=resolved_workdir,
            )
            session: SloAgentSession = SloAgentSession.build(config=config)
            SloTUI(session=session).run()
```

### Rules

| Rule | Detail |
|---|---|
| methods are keyword-only | `def tui(cls, *, workdir: Path | None)` |
| methods are fully typed | no guessing about inputs/outputs |
| defaults are resolved here | cwd/env/config fallback belongs here |
| builders are fine | `_build_session_config(...)` is a healthy extraction |
| side-effect boundaries are explicit | `interactive_logging`, `uvicorn.run`, `.run()` should be visually obvious |

---

## 6. Walkthrough — add a new subcommand the right way

Use this as the default implementation recipe.

### Goal

Add:

```bash
slo serve --port 7700
```

that launches a small FastAPI app.

### Step 1 — add a thin Typer wrapper in `src/cli/app.py`

```python
@app.command(name="serve")
def _serve(
    port: int = typer.Option(7700, "--port", help="Port to bind."),
) -> None:
    """Run the health app."""
    TyperDispatch.serve(port=port)
```

What this function is allowed to do:

- define the option
- carry a docstring/help message
- delegate to dispatch

What it is not allowed to do:

- import uvicorn and call it directly
- build settings objects
- probe the filesystem

### Step 2 — add runtime assembly in `src/cli/typer_dispatch.py`

```python
class TyperDispatch:
    @classmethod
    def serve(cls, *, port: int) -> None:
        uvicorn.run(
            app="src.main:app",
            host="127.0.0.1",
            port=port,
            reload=False,
        )
```

If runtime assembly grows, extract helpers:

```python
class TyperDispatch:
    @classmethod
    def serve(cls, *, port: int) -> None:
        app_target: str = cls._resolve_health_app_target()
        uvicorn.run(app=app_target, host="127.0.0.1", port=port, reload=False)
```

### Step 3 — test the CLI surface in `tests/cli/test_app.py`

```python
def test_serve_command_delegates(mocker: MockerFixture) -> None:
    dispatch_spy = mocker.patch.object(TyperDispatch, "serve")

    result = CliRunner().invoke(app, ["serve", "--port", "8800"])

    assert result.exit_code == 0
    dispatch_spy.assert_called_once_with(port=8800)
```

### Step 4 — test runtime assembly in `tests/cli/test_typer_dispatch.py`

```python
def test_serve_runs_uvicorn(mocker: MockerFixture) -> None:
    run_spy = mocker.patch("src.cli.typer_dispatch.uvicorn.run")

    TyperDispatch.serve(port=8800)

    run_spy.assert_called_once_with(
        app="src.main:app",
        host="127.0.0.1",
        port=8800,
        reload=False,
    )
```

That is the expected split.

---

## 7. Walkthrough — implement bare invocation that opens the TUI

This is Slo's main product pattern.

### Goal

Support all of these:

```bash
slo
slo /some/workdir
slo --version
slo serve --port 8800
```

### Step 1 — put the default behavior in the callback

```python
@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    workdir: Path | None = typer.Argument(None),
    version: bool = typer.Option(False, "--version", is_eager=True),
) -> None:
    if version:
        typer.echo(message=resolve_version())
        raise typer.Exit(code=0)

    if ctx.invoked_subcommand is not None:
        return

    TyperDispatch.tui(workdir=workdir)
```

### Step 2 — move TUI boot into dispatch

```python
class TyperDispatch:
    @classmethod
    def tui(cls, *, workdir: Path | None) -> None:
        resolved_workdir: Path = (workdir or Path.cwd()).resolve()
        with interactive_logging(...):
            config: SessionConfigDAO = cls._build_session_config(
                workdir=resolved_workdir,
            )
            session: SloAgentSession = SloAgentSession.build(config=config)
            SloTUI(session=session).run()
```

### Step 3 — test the branches in `test_app.py`

You need separate tests for:

- bare invocation delegates to `TyperDispatch.tui(workdir=None)`
- positional workdir delegates with the parsed `Path`
- `--version` prints and exits without calling dispatch
- `serve` does not launch the TUI

### Step 4 — test the runtime details in `test_typer_dispatch.py`

Assert:

- cwd fallback is resolved correctly
- `interactive_logging(...)` is entered
- `SloAgentSession.build(...)` receives the expected config
- `SloTUI(session=session).run()` is called

---

## 8. Positional argument vs. subcommand ambiguity

This is one of the few places where a custom `TyperGroup` is justified.

### The ambiguity

If the root command accepts an optional positional workdir:

```bash
slo /tmp/project
```

and also has subcommands:

```bash
slo serve --port 7700
```

then the first token could be:

- a workdir
- a subcommand name

### Rule

Use a custom group **only** to disambiguate that parser edge.
Do not turn it into a second runtime layer.

### Good custom-group scope

- recognize whether token 1 is a known command name
- if yes, let Typer/Click handle it normally
- if no, treat it as the root positional argument

### Bad custom-group scope

- manually parsing options
- executing command logic
- resolving files/env
- calling services/TUI directly

### Required comment quality

If you use a custom group, add a comment/docstring explaining:

1. which command shapes conflict
2. why standard Typer parsing is insufficient
3. what the override changes
4. what it intentionally does **not** change

---

## 9. Version logic belongs in `version.py`

Do not inline package metadata lookups in `app.py`.

### Canonical helper

```python
from importlib import metadata


def resolve_version() -> str:
    try:
        return metadata.version(distribution_name="slo")
    except metadata.PackageNotFoundError:
        return "unknown"
```

### Why this small extraction matters

- it keeps `app.py` about parsing only
- it gives `--version` its own test surface
- fallback behavior for editable installs is explicit

### Test example

```python
def test_resolve_version_falls_back_to_unknown(mocker: MockerFixture) -> None:
    mocker.patch(
        "src.cli.version.metadata.version",
        side_effect=metadata.PackageNotFoundError,
    )

    assert resolve_version() == "unknown"
```

---

## 10. Bootstrap / self-update flows get dedicated modules

Slo's `src/cli/update.py` is intentionally **stdlib-only** because it may run before the package dependencies are available.

### When to isolate a flow like this

- self-update
- environment repair
- first-install bootstrap
- migration/bootstrap behavior that must run before normal imports are safe

### Required documentation for such modules

At the top of the file, say plainly:

- why the module exists
- why normal project imports are restricted
- which dependencies are intentionally forbidden

### Bad

- mixing bootstrap behavior into `app.py`
- casually importing half the app into a pre-install command

### Good

- a narrow helper module with strong comments and minimal imports

---

## 11. Rich is allowed, but not in `app.py`

Typer should own:

- parsing
- help text
- option validation
- usage errors
- eager flags like `--version`

Rich should own:

- tables
- panels
- structured command output
- progress displays
- non-Typer terminal rendering

### Correct placement

| Concern | File/layer |
|---|---|
| `--help` usage | Typer / `app.py` |
| `--version` text | callback + `version.py` |
| render a result table | helper module or dispatch-called feature module |
| TUI startup | dispatch |
| transcript rendering | TUI layer |

### Bad

```python
@app.command()
def list_runs() -> None:
    console = Console()
    table = Table(...)
    ...
    console.print(table)
```

This is not always catastrophic, but it trends toward a bloated parse surface. Prefer:

```python
@app.command()
def list_runs() -> None:
    TyperDispatch.list_runs()
```

and let the lower layer own rendering.

---

## 12. TUI launch requires log isolation

If a Typer command launches Textual, stdout/stderr logging must be isolated first.

### Why

Textual owns the terminal screen.
Regular logs interleaving with a live TUI will break layout and make the app feel unstable.

### Canonical shape

```python
with interactive_logging(slo_home=slo_home):
    config: SessionConfigDAO = cls._build_session_config(...)
    session: SloAgentSession = SloAgentSession.build(config=config)
    SloTUI(session=session).run()
```

### Review rule

If you see a CLI command doing:

```python
SloTUI(session=session).run()
```

without an obvious interactive logging boundary around startup, assume the implementation is wrong until proven otherwise.

---

## 13. Import discipline and startup cost

CLI surfaces are invoked constantly for:

- `--help`
- `--version`
- completion
- smoke checks
- shell aliases
- editor integrations

### Rules

| Rule | Detail |
|---|---|
| keep top-level imports honest | `app.py` should not drag in the entire runtime if avoidable |
| isolate heavy helpers | update/bootstrap/version/service boot concerns belong in dedicated modules |
| avoid cycles | `app.py` depends on helpers; helpers should not depend back on `app.py` |
| optimize the common trivial path | help/version should not feel like full app boot |

---

## 14. Detailed testing strategy

Split tests by concern.

### 14.1 `tests/cli/test_app.py`

Use `CliRunner` for user-facing contract:

- `--help` output
- `--version` output
- bare invocation behavior
- positional root argument behavior
- subcommand delegation
- parser ambiguity cases

### 14.2 `tests/cli/test_typer_dispatch.py`

Use mocks/fakes for runtime assembly:

- cwd fallback
- path normalization
- env/config lookup
- session build
- `interactive_logging(...)`
- `uvicorn.run(...)`
- helper invocation

### 14.3 helper tests

Test isolated modules like:

- `version.py`
- `update.py`
- `doctor.py`
- `bootstrap.py`

### Example test matrix

| Behavior | Best test layer |
|---|---|
| `slo --help` lists `serve` | `test_app.py` |
| `slo serve --port 9000` calls `TyperDispatch.serve(port=9000)` | `test_app.py` |
| `TyperDispatch.serve` calls uvicorn correctly | `test_typer_dispatch.py` |
| `resolve_version()` falls back to `unknown` | `test_version.py` |
| TUI boot enters interactive logging | `test_typer_dispatch.py` |

---

## 15. Anti-patterns

### Anti-pattern 1 — `app.py` builds runtime objects directly

```python
@app.command()
def serve() -> None:
    uvicorn.run(...)
```

**Fix:** delegate to dispatch.

### Anti-pattern 2 — one file handles parsing, runtime assembly, rendering, and helpers

**Fix:** split into `app.py`, `typer_dispatch.py`, and focused helper modules.

### Anti-pattern 3 — bare invocation shows help when the CLI's real product is the TUI

**Fix:** use `@app.callback(invoke_without_command=True)`.

### Anti-pattern 4 — logs leak into the Textual screen

**Fix:** add an explicit interactive logging boundary in dispatch before `.run()`.

### Anti-pattern 5 — custom `TyperGroup` becomes a hidden runtime engine

**Fix:** keep custom group logic restricted to parse disambiguation.

### Anti-pattern 6 — helpers like version/update live inline in `app.py`

**Fix:** isolate them in dedicated modules.

---

## 16. Implementation checklist

- [ ] `src/cli/__main__.py` is a tiny `SystemExit(main())` handoff
- [ ] `src/cli/__init__.py` exports `main`
- [ ] `src/cli/app.py` contains Typer declarations and thin wrappers only
- [ ] `src/cli/typer_dispatch.py` owns runtime assembly
- [ ] dispatch methods are keyword-only and fully typed
- [ ] bare-command behavior uses `@app.callback(invoke_without_command=True)` when appropriate
- [ ] positional-vs-subcommand ambiguity is solved only when truly necessary
- [ ] version logic lives in `version.py`
- [ ] bootstrap/update constraints live in dedicated helper modules
- [ ] TUI launch paths isolate terminal logging before `.run()`
- [ ] Rich rendering happens below the parse surface
- [ ] `tests/cli/test_app.py` covers the command contract
- [ ] `tests/cli/test_typer_dispatch.py` covers runtime assembly
- [ ] helper modules have focused tests when non-trivial
- [ ] code also follows `skills/languages/python/named-arguments-and-type-hints/SKILL.md`, `skills/languages/python/declarative-method-structure/SKILL.md`, and `skills/languages/python/method-docstrings/SKILL.md`

---

## 17. Files to read before making changes

Read these together before implementing a new `src/cli/` feature:

- `src/cli/app.py`
- `src/cli/typer_dispatch.py`
- `src/cli/version.py`
- `src/cli/update.py`
- `tests/cli/test_app.py`
- `tests/cli/test_typer_dispatch.py`

If the CLI launches the TUI, also read:

- `src/tui/app.py`
- `tests/tui/test_app.py`

If the CLI starts an HTTP service, also read:

- the app bootstrap module it launches
- the integration test or smoke test for that service
