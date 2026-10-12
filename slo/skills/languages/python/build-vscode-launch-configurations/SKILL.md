---
name: build-vscode-launch-configurations
description: 'Python: Conventions for authoring or revising VS Code launch configurations.'
when_to_use: For Python projects only. Use when adding a new debugger target, refactoring launch.json
  entries, or reviewing existing VS Code launch targets and debugger entry points for this workspace.
group: languages
kind: skill
source_prompt: build-vscode-launch-configurations.md
---

# Build VS Code Launch Configurations

## Skill summary

- **Name:** `build-vscode-launch-configurations`
- **Description:** Conventions for authoring or revising VS Code launch configurations.
- **When to use:** Use when adding a new debugger target, refactoring launch.json entries, or reviewing existing VS Code launch targets and debugger entry points for this workspace.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `build-vscode-launch-configurations.md`

## Examples

- The user asks: "Add a VS Code debug target for the new worker."
- You need to rewrite launch.json so local run targets match the repo conventions.
- The user asks: "What launch.json conventions does this workspace follow?"
- You need to inspect an existing debugger profile before adding a new one.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

Every long-lived process in this project — FastAPI app, A2A agent,
DBOS worker, scheduled job, standalone script that an operator
debugs locally — MUST ship with a matching VSCode launch
configuration. Two `launch.json` files exist; **both must be
updated** in the same MR that introduces the service:

| File | Workspace root | Purpose |
|---|---|---|
| `orders-platform/.vscode/launch.json` | The full monorepo | Used when the developer opens `orders-platform/` (back-end + frontend together) |
| `orders-platform/orders_service/.vscode/launch.json` | `orders_service/` only | Used when the developer opens `orders_service/` standalone |

The two files differ only in `cwd` and `envFile` paths because
``${workspaceFolder}`` resolves differently. The launch entry's
`name`, `module`, and `args` are identical.

---

## When this rule kicks in

Trigger conditions — read this rule and follow it on each:

- A new file appears under `orders_service/src/tasks/<x>_worker.py` (DBOS worker).
- A new FastAPI app or sub-app gets a `main.py` / `<area>_app.py` whose
  module is meant to be served by `uvicorn`.
- A new A2A agent file appears under `orders_service/src/agents/a2a/`.
- A new launchable script lands under `orders_service/scripts/launch_*.sh` —
  the launch script implies an operator wants to run it; it should
  also be runnable from VSCode for debugging.
- Any other long-lived process intended to be run/debug from inside
  VSCode.

If you are unsure whether a service is "launchable", ask: would an
operator ever want to run this with breakpoints set? If yes, add the
launch config.

---

## Configuration types

### 1. DBOS worker (Python module)

```json
{
  "name": "[Python][DBOS]: <Human Readable Worker Name>",
  "type": "python",
  "request": "launch",
  "module": "src.tasks.<module_name>_worker",
  "cwd": "<see cwd matrix below>",
  "console": "integratedTerminal",
  "envFile": "<see envFile matrix below>",
  "justMyCode": false
}
```

Naming: prefix `[Python][DBOS]:` so all DBOS workers cluster together
in the VSCode "Run and Debug" dropdown. The human-readable name
should match the launcher script's service name (e.g.
`Reference Document Index Worker` matches
`launch_orders_reference_document_index_worker.sh`).

### 2. FastAPI / A2A app (uvicorn module)

```json
{
  "name": "Python: <App Display Name>",
  "type": "python",
  "request": "launch",
  "module": "uvicorn",
  "cwd": "<see cwd matrix below>",
  "envFile": "<see envFile matrix below>",
  "args": [
    "<dotted.module:asgi_object>",
    "--port", "<port>",
    "--reload",
    "--host", "0.0.0.0"
  ],
  "jinja": true,
  "justMyCode": false
}
```

Add `--log-level debug` only in `orders_service/.vscode/launch.json` (not the
monorepo one) so the `orders_service/`-only debugger session is verbose by
default.

### 3. Test runner

If the new component introduces a new pytest convention (e.g.
integration tests against a different database), add a dedicated
launch entry. Otherwise the existing "Python: Current Test File" /
"Python: Current Test Method" entries cover ad-hoc test debugging.

---

## `cwd` and `envFile` matrix — paths differ between the two files

The fields below are the ONLY ones that differ between the monorepo
and orders_service-only launch files. Everything else (name, module, args)
is byte-identical.

| Field | `orders-platform/.vscode/launch.json` | `orders-platform/orders_service/.vscode/launch.json` |
|---|---|---|
| `cwd` | `${workspaceFolder}/orders_service` | `${workspaceFolder}` |
| `envFile` | `${workspaceFolder}/orders_service/environments/development.env` | `${workspaceFolder}/environments/development.env` |

**Why this matters:** `${workspaceFolder}` resolves to whichever
folder the developer opened. When they open `orders-platform/`, the
back-end lives under `orders_service/`. When they open `orders_service/` directly,
the back-end IS the workspace root.

---

## Worked example — adding a new DBOS worker

Scenario: you ship a new `reference_document_index_worker.py` under
`orders_service/src/tasks/`. The required launch configurations are:

**`orders-platform/.vscode/launch.json`** — append after the existing
`[Python][DBOS]:` blocks:

```json
{
  "name": "[Python][DBOS]: Reference Document Index Worker",
  "type": "python",
  "request": "launch",
  "module": "src.tasks.reference_document_index_worker",
  "cwd": "${workspaceFolder}/orders_service",
  "console": "integratedTerminal",
  "envFile": "${workspaceFolder}/orders_service/environments/development.env",
  "justMyCode": false
}
```

**`orders-platform/orders_service/.vscode/launch.json`** — same name and `module`,
different paths:

```json
{
  "name": "[Python][DBOS]: Reference Document Index Worker",
  "type": "python",
  "request": "launch",
  "module": "src.tasks.reference_document_index_worker",
  "cwd": "${workspaceFolder}",
  "console": "integratedTerminal",
  "envFile": "${workspaceFolder}/environments/development.env",
  "justMyCode": false
}
```

---

## Common mistakes

- **Updating only one of the two files.** A developer who opens the
  monorepo will see the entry; a developer who opens `orders_service/`
  alone will not. Always update both.
- **Pointing `envFile` at `test.env`.** Launch configs are for
  development, not test. The test entry uses `pytestEnabled: true`
  with the test env loaded by the test fixtures themselves.
- **`justMyCode: true`.** Hides framework stack frames during
  debugging — almost always the wrong choice in this codebase
  because issues frequently surface inside SQLAlchemy / DBOS /
  LangGraph internals. Default is `false`.
- **Naming inconsistencies.** Use the existing prefix pattern —
  `[Python][DBOS]:` for DBOS workers, `Python:` for FastAPI / A2A /
  scripts, `Web:` for Vite / npm. The dropdown is alphabetical;
  consistent prefixes make it scannable.
- **Forgetting the launch config when shipping the launcher script.**
  The launcher and the VSCode entry are paired artefacts — operators
  use the launcher in production, developers use the VSCode entry
  locally. Both must exist.

---

## Verification checklist

Before considering a new service complete:

- [ ] Service has a launcher script under `orders_service/scripts/launch_*.sh`
      (already required by the deployment-stack convention).
- [ ] Service appears in `orders-platform/.vscode/launch.json` with the
      monorepo paths.
- [ ] Service appears in `orders-platform/orders_service/.vscode/launch.json` with
      the orders_service-root paths.
- [ ] `name` and `module` match across both files.
- [ ] `cwd` and `envFile` use the workspace-correct path per the
      matrix above.
- [ ] `justMyCode` is `false`.
- [ ] Launcher service name (e.g. "Reference Document Index Worker")
      and the launch entry name agree.
- [ ] Verified by selecting the entry in VSCode's "Run and Debug"
      dropdown and starting it — the worker boots, picks up the dev
      env, and connects to the dev databases.

---

## When this rule does not apply

- One-off scripts in `orders_service/scripts/poc/` — they are exploratory
  and don't need debugger entries. The "Python: Current File" entry
  is enough.
- Cron / scheduled jobs that run inside an existing worker process —
  the worker's launch entry already covers them.
- Anything that runs only inside a Docker container without a
  matching local-dev path. Document the omission inline so a future
  contributor doesn't add a stale entry.
