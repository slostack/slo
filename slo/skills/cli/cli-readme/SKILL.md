---
name: cli-readme
description: Orientation guide for the CLI prompt family.
when_to_use: Read before working on CLI prompts so you choose the right CLI convention
  set.
group: cli
kind: skill
source_prompt: cli/README.md
---

# CLI Prompt Family README

## Skill summary

- **Name:** `cli-readme`
- **Description:** Orientation guide for the CLI prompt family.
- **When to use:** Read before working on CLI prompts so you choose the right CLI convention set.
- **Group:** `cli`
- **Kind:** `skill`
- **Source prompt:** `cli/README.md`

## Examples

- The task touches a Python CLI and you need to know whether it follows the Typer or operator-command tradition.
- You want the reading order for the CLI prompt family before implementing a command.

## Guidance

This folder covers two distinct CLI traditions that coexist in the workspace:

1. **Product CLIs** — Typer-based commands that end users run directly, often opening a Textual TUI as their default action (`src/cli/`).
2. **Operator / deployment CLIs** — Make-target-driven control-plane verbs backed by `Command` classes that talk to a deployed service over HTTPS (`<project>/cli/`).

Read the matching file(s) for the task at hand. The two traditions share the same Python ground rules (named args, type hints, Google docstrings, declarative structure) but have different architecture, different entry points, and different test strategies.

---

## Files

| File | Kind | When to read |
|---|---|---|
| [`build-typer-cli-apps.md`](../build-typer-cli-apps/SKILL.md) | Product CLI | Adding or modifying `src/cli/` — Typer parse surface, `TyperDispatch` split, `@app.callback` default routing, version/update isolation, TUI log isolation, `CliRunner` tests. |
| [`build-cli-commands.md`](../build-cli-commands/SKILL.md) | Operator CLI | Adding a new `make <verb>` target — Makefile as thin shim, bash-vs-Python boundary, CLI → Router → Application Service layering, Bearer-token auth, polling + idempotency. |
| [`build-cli-modules.md`](../build-cli-modules/SKILL.md) | Operator CLI | Implementing a Python module under `<project>/cli/` — full stack rules, `@handle_cli_errors`, argument patterns, two-console discipline (`stdout` for data / `stderr` for status), `poll_until_terminal`, `RetryPolicy`, `DryRunGate`, structlog-to-stderr, test layers. |
| [`build-cli-command-class.md`](../build-cli-command-class/SKILL.md) | Operator CLI | Writing any `Command` class — mandatory `Command` suffix, `__init__`/`build`/`execute` triad, `execute`-as-table-of-contents, Make-target → Typer-function → async-helper naming chain, file layout, anti-patterns, pre-merge checklist. |

### Reading order for operator CLIs

Read `build-cli-command-class.md` first when writing any `Command` class. Read all three operator files together for a complete picture of a new command end-to-end.

---

## Orientation

### Product CLI (`build-typer-cli-apps.md`)

The architecture separates **parsing** (`src/cli/app.py`) from **runtime assembly** (`src/cli/typer_dispatch.py`) from **feature logic** (helper modules). Bare invocation typically opens a Textual TUI; subcommands delegate to `TyperDispatch` class methods. Rich rendering never lives in `app.py`.

### Operator CLI (the three `build-cli-*` files)

The chain is:

```
make <verb>  →  <project>/cli/<module>.py  →  POST /api/v1/cli/<verb>  →  router  →  Application Service
```

Every operator verb is a `.PHONY:` Make target with ≤ 4 recipe lines. Real work lives in a Python `Command` class with three methods (`__init__`, `build`, `execute`). The naming chain `make verify-flow` → `verify_flow()` → `_verify_flow_async()` → `VerifyFlowCommand.build().execute()` must be unbroken.

---

## Cross-links

- **TUI conventions** — [`../skills/tui/build-textual-tuis/SKILL.md`](../../tui/build-textual-tuis/SKILL.md) (for product CLIs that open a Textual TUI)
- **Deployment conventions** — ``../deployment/conventions.md`` (deploy-time choreography, secrets pipeline — complements operator CLI rules)
- **Application service patterns** — [`../skills/languages/python/build-application-services/SKILL.md`](../../languages/python/build-application-services/SKILL.md) (the layer operator CLIs call through the router)
- **Router patterns** — [`../skills/languages/python/build-routers/SKILL.md`](../../languages/python/build-routers/SKILL.md) (the `/api/v1/cli/*` endpoint layer)
- **Python ground rules** — [`../skills/languages/python/named-arguments-and-type-hints/SKILL.md`](../../languages/python/named-arguments-and-type-hints/SKILL.md), [`../skills/coding/declarative-method-structure/SKILL.md`](../../coding/declarative-method-structure/SKILL.md) plus [`../skills/languages/python/declarative-method-structure/SKILL.md`](../../languages/python/declarative-method-structure/SKILL.md), and [`../skills/languages/python/method-docstrings/SKILL.md`](../../languages/python/method-docstrings/SKILL.md)
