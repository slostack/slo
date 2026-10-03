---
name: go-recipe-vscode-launch-configurations
description: "Go scoped recipe (testcontainers, asynq): VSCode launch.json configurations for debugging\
  \ Go services with Delve (dlv) \u2014 Gin HTTP servers, asynq workers and schedulers, Temporal workers,\
  \ cobra CLI commands, single-file/test debugging, env loading via envFile, args, buildFlags, and attaching\
  \ to a running process."
when_to_use: Only for the named project stack and component. Use whenever a new long-lived Go process
  (cmd/api server, cmd/worker, scheduler, Temporal worker, cobra command) is added and must be runnable/debuggable
  from VSCode, or when adding/reviewing entries in a Go project's .vscode/launch.json.
group: languages
kind: skill
---

# Go VSCode Launch Configurations

## Skill summary

- **Name:** `go-recipe-vscode-launch-configurations`
- **Description:** VSCode `launch.json` configurations for debugging Go services
  with the Delve (`dlv`) debugger — a Gin HTTP server (`cmd/api`), an asynq worker
  (`cmd/worker`), an asynq scheduler, a Temporal worker, a cobra CLI command, and
  single-file/test debugging. Covers env-var loading (`envFile`), `args`,
  `buildFlags`, and attaching to a running process.
- **When to use:** Whenever a new launchable Go process is added, or when
  adding/reviewing `.vscode/launch.json` entries in a Go project.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Add a VSCode launch config for the new asynq worker in `cmd/worker`."
- "Set up debugging for our Gin API server with the dev `.env` loaded."
- "How do I attach the Go debugger to a running process?"
- "Give me a launch.json entry to debug the current test with a build tag."
- "Add a launch config for the Temporal worker and the cobra migrate command."
- "Wire up Delve so I can set breakpoints in `cmd/api/main.go`."
- "Our `.vscode/launch.json` is missing an entry for the new scheduler process."

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

Every long-lived Go process in a project — the Gin HTTP server, an asynq worker, an
asynq scheduler, a Temporal worker, a cobra CLI command an operator debugs locally —
MUST ship with a matching VSCode launch configuration in the same PR that introduces
it. The launcher (Makefile target, Dockerfile `CMD`, or `air`/`go run` invocation)
and the VSCode entry are **paired artefacts**: operators run the launcher, developers
debug with the VSCode entry. Both must exist.

This is the Go/Delve counterpart of the Python `uvicorn`/`module` launch conventions.
The Python source used `"type": "python"` with a `"module"`; Go uses
`"type": "go"` (the [gopls / Go extension][go-ext] debug adapter, which drives the
[Delve][delve] debugger `dlv`) with a `"program"` pointing at a package directory.

Defer to `go-conventions` for the package layout these entries target
(`cmd/<binary>/main.go` as the entry point with no logic) and to
`go-recipe-cli-configuration` (configuration/domain structure) and `go-recipe-bootstrap-project-scaffolding` for how those
`cmd/` binaries and their config loading are wired up in the first place.

[go-ext]: https://github.com/golang/vscode-go
[delve]: https://github.com/go-delve/delve

---

### Prerequisite — Delve must be installed

The Go extension shells out to `dlv`. Without it, every launch fails with
`could not launch process: exec: "dlv": executable file not found`.

```bash
go install github.com/go-delve/delve/cmd/dlv@latest
# ensure $(go env GOPATH)/bin is on PATH
```

---

### The four launch modes (Go debug adapter)

Unlike Python, where you pick between `program`, `module`, and `code`, the Go debug
adapter has a small, fixed set of `mode` values. Know which one each entry needs:

| `mode`   | What it does                                        | Use for |
|----------|-----------------------------------------------------|---------|
| `debug`  | Compiles the package with Delve and launches it     | `cmd/*` binaries (server, worker, scheduler, Temporal, CLI) |
| `test`   | Compiles and debugs the test binary for a package   | Debugging the current test file / a single test |
| `exec`   | Debugs an already-compiled binary                   | Rare — a prebuilt binary you don't want to recompile |
| `attach` | Attaches Delve to a process already running (by PID or, remotely, by host:port) | Debugging a live `go run`/`air`/container process |

`request` is `launch` for `debug`/`test`/`exec`, and `attach` for `attach`.

---

### Field reference — the Go-specific knobs

These are the fields that replace the Python source's `module` / `jinja` /
`justMyCode` set. Every one has a direct analog to a `go run` / `dlv` flag.

- **`program`** — the package to build and debug. Point it at a **directory**
  (`"${workspaceFolder}/cmd/api"`), not a file, so Delve compiles the whole package.
  Use `"${file}"` only for single-file debugging and `"${fileDirname}"` for
  debug-the-package-of-the-current-file.
- **`args`** — argv passed to the program. This is how you feed cobra subcommands
  and flags (`["worker", "--queues", "critical,default"]`). Analogous to the Python
  source's `args` array for `uvicorn`.
- **`env`** — inline env vars as a JSON object. Highest precedence; overrides
  `envFile`. Use for one-off overrides (`{"LOG_LEVEL": "debug"}`).
- **`envFile`** — path to a `.env` file loaded before launch. This is the direct
  equivalent of the Python source's `envFile`. Point it at the **development** env,
  never `test.env` (see Common mistakes). viper (`go-recipe-cli-configuration`'s config
  loader) reads these same variables at startup, so `envFile` and production config
  stay in sync.
- **`buildFlags`** — flags passed to `go build`. This is where build tags go:
  `"-tags=integration"` or `"-tags=dev,debug"`. There is no Python analog; it is the
  Go way to compile in/out code paths for a debug session.
- **`cwd`** — working directory for the launched process. Default it to
  `"${workspaceFolder}"` so relative paths (config files, migrations) resolve from
  the repo root, matching how the Makefile launcher runs.
- **`console`** — use `"integratedTerminal"` for anything that reads stdin or that
  you want interleaved with terminal output (all of these do). The Python source
  used the same value for the same reason.
- **`showLog`** / **`trace`** — Delve's own diagnostics. Add `"showLog": true` only
  when debugging why a launch itself fails, not by default.

There is no `justMyCode` in the Go adapter. Delve steps into dependency and stdlib
source by default (the behaviour the Python source forced with
`"justMyCode": false`), which is what you want here — bugs frequently surface inside
Gin, asynq, or the Temporal SDK.

---

### Naming convention — prefix by process class

The "Run and Debug" dropdown is alphabetical. Prefix every entry so like processes
cluster, exactly as the Python source used `[Python][DBOS]:`. Use one bracketed
`[Go]` tag plus a process-class tag:

| Prefix              | Process class                          |
|---------------------|----------------------------------------|
| `[Go][API]:`        | Gin HTTP server                        |
| `[Go][Worker]:`     | asynq worker                           |
| `[Go][Scheduler]:`  | asynq scheduler / periodic task server |
| `[Go][Temporal]:`   | Temporal worker                        |
| `[Go][CLI]:`        | cobra CLI command                      |
| `[Go][Test]:`       | test-runner entries                    |
| `[Go][Attach]:`     | attach-to-process entries              |

The human-readable name after the colon must match the binary / service name the
launcher uses (e.g. `[Go][Worker]: Notifications Worker` pairs with a
`make run-notifications-worker` target).

---

### Configuration types

Each block below is a single entry from the `configurations` array. The complete,
ordered file follows in the next section.

#### 1. Gin HTTP server (`cmd/api`)

```json
{
  "name": "[Go][API]: HTTP Server",
  "type": "go",
  "request": "launch",
  "mode": "debug",
  "program": "${workspaceFolder}/cmd/api",
  "cwd": "${workspaceFolder}",
  "envFile": "${workspaceFolder}/.env",
  "args": ["--port", "8080"],
  "console": "integratedTerminal"
}
```

Set `GIN_MODE=debug` via the `envFile` (or an inline `env` override) so Gin prints
route registration and verbose request logs during the debug session.

#### 2. asynq worker (`cmd/worker`)

The worker is a single binary that boots an `asynq.Server` and processes tasks off
Redis queues. Pass the queues and concurrency as `args` so you can debug a narrow
queue in isolation.

```json
{
  "name": "[Go][Worker]: Task Worker",
  "type": "go",
  "request": "launch",
  "mode": "debug",
  "program": "${workspaceFolder}/cmd/worker",
  "cwd": "${workspaceFolder}",
  "envFile": "${workspaceFolder}/.env",
  "args": ["--concurrency", "10", "--queues", "critical=6,default=3,low=1"],
  "console": "integratedTerminal"
}
```

#### 3. asynq scheduler

The scheduler (`asynq.Scheduler` / periodic-task server) is a **separate process**
from the worker — it only enqueues periodic tasks; the worker executes them. It gets
its own binary and its own launch entry. Do **not** fold it into the worker entry.

```json
{
  "name": "[Go][Scheduler]: Periodic Task Scheduler",
  "type": "go",
  "request": "launch",
  "mode": "debug",
  "program": "${workspaceFolder}/cmd/scheduler",
  "cwd": "${workspaceFolder}",
  "envFile": "${workspaceFolder}/.env",
  "console": "integratedTerminal"
}
```

#### 4. Temporal worker

The Temporal worker registers workflows and activities and long-polls the Temporal
service task queue. Feed the task queue as an arg so you can debug one queue at a
time.

```json
{
  "name": "[Go][Temporal]: Workflow Worker",
  "type": "go",
  "request": "launch",
  "mode": "debug",
  "program": "${workspaceFolder}/cmd/temporalworker",
  "cwd": "${workspaceFolder}",
  "envFile": "${workspaceFolder}/.env",
  "args": ["--task-queue", "orders"],
  "console": "integratedTerminal"
}
```

Point `TEMPORAL_HOSTPORT` at the local dev Temporal (`localhost:7233`) via the
`envFile`.

#### 5. cobra CLI command

A single `cmd/cli` (or root cobra binary) exposes many subcommands. You do **not**
need a separate `program` per subcommand — one `program` and different `args` covers
them. Ship one entry per subcommand a developer commonly debugs (migrations, seed,
one-off backfills).

```json
{
  "name": "[Go][CLI]: migrate up",
  "type": "go",
  "request": "launch",
  "mode": "debug",
  "program": "${workspaceFolder}/cmd/cli",
  "cwd": "${workspaceFolder}",
  "envFile": "${workspaceFolder}/.env",
  "args": ["migrate", "up"],
  "console": "integratedTerminal"
}
```

#### 6. Single-file / current-test debugging

Two general-purpose entries cover ad-hoc debugging — the Go analog of the Python
source's "Current Test File" / "Current Test Method" entries. `${file}` and
`${fileDirname}` resolve to whatever the developer has open, so these are written
once and never edited.

Debug the package of the file currently open:

```json
{
  "name": "[Go][Debug]: Current File Package",
  "type": "go",
  "request": "launch",
  "mode": "debug",
  "program": "${fileDirname}",
  "cwd": "${workspaceFolder}",
  "envFile": "${workspaceFolder}/.env",
  "console": "integratedTerminal"
}
```

Debug the test(s) in the currently open package, optionally narrowed to one test.
`${selectedText}` lets you highlight a test name and pass it to `-run`; drop the
`args` pair to run the whole file.

```json
{
  "name": "[Go][Test]: Current Test (selection as -run)",
  "type": "go",
  "request": "launch",
  "mode": "test",
  "program": "${fileDirname}",
  "cwd": "${workspaceFolder}",
  "args": ["-test.run", "${selectedText}"],
  "buildFlags": "-tags=unit",
  "console": "integratedTerminal"
}
```

For integration tests behind a build tag, swap `buildFlags` to
`"-tags=integration"` — this is the canonical use of `buildFlags`.

#### 7. Attach to a running process

For debugging a process started outside VSCode — `go run ./cmd/api`, an `air`
hot-reload session, or a binary in a container with Delve headless. Two shapes:

Attach by local PID (VSCode prompts you to pick the process):

```json
{
  "name": "[Go][Attach]: Local Process (by PID)",
  "type": "go",
  "request": "attach",
  "mode": "local",
  "processId": 0
}
```

Attach to a remote/headless Delve server (the container/CI shape) started with
`dlv exec ./app --headless --listen=:2345 --api-version=2 --accept-multiclient`:

```json
{
  "name": "[Go][Attach]: Headless Delve (remote)",
  "type": "go",
  "request": "attach",
  "mode": "remote",
  "host": "127.0.0.1",
  "port": 2345,
  "cwd": "${workspaceFolder}"
}
```

With `mode: "local"`, leaving `processId: 0` makes VSCode show a process picker at
launch time. Build the target with `-gcflags="all=-N -l"` (disable optimisation and
inlining) so breakpoints and variables survive; `air`'s default build already omits
optimisation flags, so add them to its build command when you intend to attach.

---

### Complete `.vscode/launch.json`

Named and ordered by process class — server, worker, scheduler, Temporal, CLI, then
the ad-hoc debug/test/attach entries — so the dropdown reads top-down from
"the service" to "the tools".

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "[Go][API]: HTTP Server",
      "type": "go",
      "request": "launch",
      "mode": "debug",
      "program": "${workspaceFolder}/cmd/api",
      "cwd": "${workspaceFolder}",
      "envFile": "${workspaceFolder}/.env",
      "args": ["--port", "8080"],
      "console": "integratedTerminal"
    },
    {
      "name": "[Go][Worker]: Task Worker",
      "type": "go",
      "request": "launch",
      "mode": "debug",
      "program": "${workspaceFolder}/cmd/worker",
      "cwd": "${workspaceFolder}",
      "envFile": "${workspaceFolder}/.env",
      "args": ["--concurrency", "10", "--queues", "critical=6,default=3,low=1"],
      "console": "integratedTerminal"
    },
    {
      "name": "[Go][Scheduler]: Periodic Task Scheduler",
      "type": "go",
      "request": "launch",
      "mode": "debug",
      "program": "${workspaceFolder}/cmd/scheduler",
      "cwd": "${workspaceFolder}",
      "envFile": "${workspaceFolder}/.env",
      "console": "integratedTerminal"
    },
    {
      "name": "[Go][Temporal]: Workflow Worker",
      "type": "go",
      "request": "launch",
      "mode": "debug",
      "program": "${workspaceFolder}/cmd/temporalworker",
      "cwd": "${workspaceFolder}",
      "envFile": "${workspaceFolder}/.env",
      "args": ["--task-queue", "orders"],
      "console": "integratedTerminal"
    },
    {
      "name": "[Go][CLI]: migrate up",
      "type": "go",
      "request": "launch",
      "mode": "debug",
      "program": "${workspaceFolder}/cmd/cli",
      "cwd": "${workspaceFolder}",
      "envFile": "${workspaceFolder}/.env",
      "args": ["migrate", "up"],
      "console": "integratedTerminal"
    },
    {
      "name": "[Go][Debug]: Current File Package",
      "type": "go",
      "request": "launch",
      "mode": "debug",
      "program": "${fileDirname}",
      "cwd": "${workspaceFolder}",
      "envFile": "${workspaceFolder}/.env",
      "console": "integratedTerminal"
    },
    {
      "name": "[Go][Test]: Current Test (selection as -run)",
      "type": "go",
      "request": "launch",
      "mode": "test",
      "program": "${fileDirname}",
      "cwd": "${workspaceFolder}",
      "args": ["-test.run", "${selectedText}"],
      "buildFlags": "-tags=unit",
      "console": "integratedTerminal"
    },
    {
      "name": "[Go][Attach]: Local Process (by PID)",
      "type": "go",
      "request": "attach",
      "mode": "local",
      "processId": 0
    },
    {
      "name": "[Go][Attach]: Headless Delve (remote)",
      "type": "go",
      "request": "attach",
      "mode": "remote",
      "host": "127.0.0.1",
      "port": 2345,
      "cwd": "${workspaceFolder}"
    }
  ]
}
```

---

### Common mistakes

- **Pointing `program` at a `.go` file instead of a directory.** For `cmd/api`, use
  `"${workspaceFolder}/cmd/api"`, not `.../cmd/api/main.go`. Delve compiles the
  package; a file path breaks multi-file `main` packages.
- **Folding the scheduler into the worker entry.** The asynq scheduler and worker
  are two processes with two binaries. One entry each. A single entry hides the fact
  that both must run for periodic tasks to fire.
- **`envFile` pointing at `test.env`.** Launch configs are for development. Tests
  load their own env through fixtures / testcontainers. Same rule as the Python
  source.
- **Passing cobra subcommands as separate `program`s.** One CLI binary, many
  subcommands — vary `args`, not `program`. A separate `program` per subcommand is a
  sign the CLI was mis-scaffolded.
- **Attaching to an optimised binary.** Without `-gcflags="all=-N -l"`, breakpoints
  drift and variables read as `<optimized out>`. Build the attach target with
  optimisation and inlining disabled.
- **Setting `showLog`/`trace` by default.** They flood the Debug Console with
  Delve's own logs. Turn them on only to diagnose a failing launch, then remove.
- **Reaching for `justMyCode`.** It does not exist in the Go adapter. Delve steps
  into dependencies by default, which is the desired behaviour here.
- **Naming drift.** Keep the `[Go][<Class>]:` prefix and match the human name to the
  launcher's service name so the dropdown stays scannable and pairs 1:1 with
  Makefile targets.
- **Bad JSON.** `launch.json` allows `//` comments (JSONC), but a trailing comma or
  an unquoted key still breaks the whole file silently — the dropdown just goes
  empty. Validate after editing.

---

### Checklist

Run through this before considering a new Go service or launch entry complete:

- [ ] `dlv` is installed and on `PATH`.
- [ ] The new process has a `cmd/<binary>/main.go` entry point (per
      `go-recipe-cli-configuration`).
- [ ] A `.vscode/launch.json` entry exists for it, with the correct
      `[Go][<Class>]:` prefix and a name matching the launcher/service name.
- [ ] `program` points at the **package directory**, not a file.
- [ ] `mode` is correct: `debug` for `cmd/*`, `test` for test entries, `attach` for
      attach entries.
- [ ] `envFile` points at the **development** env (never `test.env`), and the vars
      match what viper loads at startup.
- [ ] Subcommands/flags are passed via `args`; build tags via `buildFlags`.
- [ ] `cwd` is `${workspaceFolder}` (or the value the launcher uses) so config and
      migration paths resolve.
- [ ] Attach entries target binaries built with `-gcflags="all=-N -l"`.
- [ ] The scheduler and worker have **separate** entries.
- [ ] Generic `Current File Package` / `Current Test` / attach entries are present
      for ad-hoc debugging.
- [ ] JSON is valid — the dropdown shows every entry after saving.
- [ ] Verified by selecting the entry and hitting a breakpoint: the process boots,
      loads the dev env, and connects to the dev dependencies (Postgres, Redis,
      Temporal).
```