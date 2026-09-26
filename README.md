# Slo

**A terminal coding agent that writes code the way *your team* writes code.**

Slo is a Python ReAct coding agent. You run it in a project directory, describe a
task in plain English, and it reads files, runs commands, edits code, and reports
back — the same loop you would run by hand, but automated.

What makes it different from a generic chat model is that Slo carries **116
built-in skill documents** — written conventions for routers, services, tests,
git operations, feature specs, code review — and loads the relevant ones on every
task. The output looks like your codebase, not like a model's default style.

- **Docs:** <https://www.get-slo.sh> — installation, tutorials, feature guides
- **License:** GPL v2 · early access / beta
- **Platforms:** macOS and Linux

> **A note on this document.** This is the map. It explains the whole system in
> plain language with diagrams. When you want the file-by-file narrative of how
> the code actually works, read [`slo/README.md`](slo/README.md) — a long-form
> walkthrough of the agent loop, the TUI, and the prompt assembly. When you want
> the terse operational reference (module paths, event kinds, style rules), read
> [`slo/AGENTS.md`](slo/AGENTS.md).

---

## Table of contents

1. [Installation](#1-installation)
2. [Architecture — how Slo is put together](#2-architecture--how-slo-is-put-together)
3. [How to use Slo](#3-how-to-use-slo)
4. [Skills](#4-skills)
5. [Dynamic workflows](#5-dynamic-workflows)
6. [Code structure](#6-code-structure)
7. [More usage details](#7-more-usage-details)
8. [Known limitations](#8-known-limitations)

---

## 1. Installation

Slo installs with a single command. The installer pulls the pinned release and
installs it with `pipx`. The 117 vendored skill documents ship **inside the
installed package** (beside it in pipx's venv, not in `~/.slo/`); after a
successful install the installer writes one non-secret managed environment
file, `~/.slo/shell/environment.sh`, which defaults `SLO_HOME` to `~/.slo`,
`SLO_SKILLS_DIR` to that validated installed skills path, and `SLO_KB_DIR` to
`$KB_DIR` or `$SLO_HOME/KnowledgeBase/KB`, and attaches it to your shell
startup files. Each default applies only when that variable is not already
set, and the knowledge-base folder itself is never created. Your own skills still live in `~/.slo/user_skills/`
and override the built-ins by name.

```bash
curl -fsSL https://get-slo.sh/install.sh | bash
```

**Installation is credential-free.** Both the installer script and the Git
repository it installs from are public, so no username, token, or account is
needed to install. The only credentials Slo ever asks for are your model
provider's, and that happens inside the TUI on first launch (see
[§3.1](#31-connecting-a-model-provider)) — never at install time.

Then:

```bash
cd ~/Code/my-project
slo
```

On first launch a sign-in modal appears. Pick a provider, authenticate, and you
are in.

### Choosing a version

The hosted installer is pinned to the latest release by default. `SLO_REF` is
the source-of-truth selector — a release tag, branch, or commit. The older
`SLO_VERSION` variable still works as a compatibility alias (`dev` means the
`main` branch; anything else is treated as a ref):

```bash
# a specific release version
curl -fsSL https://get-slo.sh/install.sh | SLO_REF=v0.15.0 bash

# the development version — tracks the main branch
curl -fsSL https://get-slo.sh/install.sh | SLO_REF=main bash

# any other development ref (branch, tag, or commit)
curl -fsSL https://get-slo.sh/install.sh | SLO_REF=feature-my-branch bash
```

### Updating

```bash
slo update                 # latest release
slo update --development   # track main
```

After reinstalling, `slo update` checks for `SLO_HOME`, `SLO_SKILLS_DIR`, and
`SLO_KB_DIR` (or `KB_DIR`). If any is missing, it runs the installed
`install.sh --finalize-environment` to set the missing defaults; variables that
already exist are left alone. It also warns when an existing `SLO_SKILLS_DIR`
has no `INDEX.md` or differs from the skills it just installed.

### Requirements

| Requirement | Detail |
|---|---|
| OS | macOS or Linux (no Windows build) |
| Python | 3.11 (`>=3.11,<3.12`) — the installer uses `python3.11` |
| Installer | `pipx`, installed for you if missing |
| Provider | An OpenAI, Anthropic, or Kimi For Coding **API** account (see [§3.1](#31-connecting-a-model-provider)) |

**Full documentation lives at <https://www.get-slo.sh>.** This README summarises
it; the site has the tutorials, per-feature deep dives, and the changelog.

---

## 2. Architecture — how Slo is put together

### 2.1 The one-paragraph version

Slo is a **loop around a language model**. The model is given a system prompt (who
it is, what tools it has, what your project's conventions are) plus the
conversation so far. It replies either with an answer or with tool calls. If it
asks for tools, Slo runs them, feeds the results back, and asks again. That
repeats until the model stops asking for tools. Everything else — the terminal
UI, the history files, the sub-agents — is scaffolding around that loop.

### 2.2 The ReAct loop

"ReAct" means **Rea**son → **Act** → observe, repeated.

```
        ┌──────────────────────────────────────────────┐
        │                                              │
        ▼                                              │
  ┌───────────┐    wants tools?   ┌───────────┐        │
  │   THINK   │ ────── yes ─────▶ │    ACT    │        │
  │ (LLM call)│                   │ run tools │        │
  └───────────┘                   └─────┬─────┘        │
        │                               │              │
        │ no tool calls                 │ results      │
        ▼                               └──────────────┘
  ┌───────────┐                          (OBSERVE — feed
  │  ANSWER   │                           results back in)
  └───────────┘
```

One trip around that diagram is called a **turn**. A single request from you may
take dozens of turns. There is no fixed iteration cap — the loop ends when the
model stops calling tools, when you abort, or when a stop-hook fires.

### 2.3 The runtime chain

When you type `slo`, control passes down this chain:

```
  you type: slo
      │
      ▼
┌─────────────────┐
│  CLI (Typer)    │   parses flags, resolves the model, picks a mode
└────────┬────────┘
         ▼
┌─────────────────┐
│  SloTUI         │   the Textual terminal UI — panes, widgets, slash commands
│  (or headless)  │   in headless mode this layer is replaced by a JSONL printer
└────────┬────────┘
         ▼
┌─────────────────┐
│ SloAgentSession │   one conversation. Owns history on disk, enforces one
│                 │   prompt at a time, broadcasts events to subscribers
└────────┬────────┘
         ▼
┌─────────────────┐
│  SloAgent       │   the multi-turn loop — keeps calling the graph until done
└────────┬────────┘
         ▼
┌─────────────────┐
│ LangGraph       │   ONE turn: [agent node] → LLM call
│  StateGraph     │            [tools node] → run the requested tools
└────────┬────────┘
         ▼
   your model provider (OpenAI / Anthropic / Kimi)
```

Read it as responsibilities, not just call order:

| Layer | Owns |
|---|---|
| **CLI** | Flags, model choice, `--resume`, which mode to launch |
| **TUI** | Everything you see; slash commands; nothing about the model |
| **Session** | Persistence, locking, event fan-out, naming |
| **Agent** | The multi-turn loop and when to stop |
| **Graph** | Exactly one turn: one LLM call plus its tools |

The split matters: because the **Session** owns history and the **TUI** only
renders events, a replayed session and a live session paint identically, and the
same session can be driven headlessly with no UI at all.

### 2.4 What goes into the system prompt

Before the first turn, Slo assembles the model's instructions from parts:

```
┌─ system prompt ───────────────────────────────────────┐
│ 1. Role line — "you are a coding agent…"              │
│ 2. Available tools — one line per bound tool          │
│ 3. Guidelines — adapts to which tools are present     │
│ 4. Skills pointer — the path to skills/INDEX.md       │
│ 5. Knowledge-base block — the path in SLO_KB_DIR      │
│ 6. Project context ── SLO.md / AGENTS.md / CLAUDE.md  │
│    found by walking UP from your working directory    │
│ 7. Today's date + current working directory           │
└───────────────────────────────────────────────────────┘
```

Step 6 is the one that makes Slo feel like it knows your project. Drop an
`AGENTS.md` at your repo root describing your conventions and every session
starts with it loaded. Slo can write that file for you — just ask.

### 2.5 Where things live on disk

```
~/.slo/
├── global/
│   └── authentication.json     your provider credentials (chmod 0600)
├── shell/
│   └── environment.sh          installer-managed defaults (SLO_HOME, SLO_SKILLS_DIR, SLO_KB_DIR)
├── user_skills/                YOUR skills — these override the built-ins
├── user_workflows/             your own multi-step workflows
├── sessions/history/
│   └── <session_id>/
│       ├── session.json        metadata: id, name, model, workdir, timestamps
│       ├── tree.json           the append-only event log, grouped by turn
│       └── transcript.md       human-readable, derived (not authoritative)
└── schedules/
    └── <schedule_id>/
        ├── schedule.json       the persisted prompt + trigger
        └── runs/<run_id>.json  one immutable record per fire
```

Set `SLO_HOME` to move this whole tree somewhere else. The 117 vendored skill
documents are *not* here — they ship inside the installed pipx package, and
the managed `shell/environment.sh` points `SLO_SKILLS_DIR` at them. (A
populated legacy `$SLO_HOME/skills` tree, if you have one from an old install, is
left untouched and remains a fallback when `SLO_SKILLS_DIR` is unset.)

---

## 3. How to use Slo

### 3.1 Connecting a model provider

Slo supports three providers. You connect one on first launch, or any time with
`/auth` inside the TUI.

| Provider | How you sign in | Notes |
|---|---|---|
| **OpenAI** (recommended) | Browser OAuth **or** API key | Default model `gpt-5.4` |
| **Anthropic** | Browser OAuth **or** API key | ⚠️ read the warning below |
| **Kimi For Coding** | API key only | Talks to `https://api.kimi.com/coding/v1` |

> ### ⚠️ Important: Anthropic subscriptions do not work
>
> **A Claude.ai Pro or Team subscription cannot be used with Slo.** Those plans
> cover the Claude apps, not programmatic access.
>
> Slo requires the **Anthropic API with usage-based billing enabled**. If your
> Anthropic account has API credits, you are fine. A plain Claude.ai
> subscription without API access will not work, and the failure appears as an
> authentication or quota error at the first model call — not at sign-in.
>
> The same principle applies to OpenAI: a ChatGPT Plus subscription is not an
> API plan. Billing is at standard API rates, per token, for whichever provider
> you connect.

**Where credentials are stored.** `~/.slo/global/authentication.json`, created
`0600` inside a `0700` directory. You can bypass the file entirely with
environment variables, which take precedence:

```bash
export SLO_OPENAI_API_KEY=…
export SLO_ANTHROPIC_API_KEY=…
export SLO_KIMI_FOR_CODING_API_KEY=…
```

For Anthropic only, Slo also falls back to `~/.claude/.credentials.json` if it
finds no credentials of its own.

To re-authenticate: type `/auth` in the TUI, or delete the credentials file.
There is no `slo auth` subcommand.

### 3.2 Models you can use

These are the models registered in the catalog today. Pick one with `--model`,
the `/model` slash command, or the `SLO_DEFAULT_MODEL_NAME` environment variable.

**Anthropic**

| Model | Notes |
|---|---|
| `claude-opus-4-8` | 200K context |
| `claude-opus-4-8-1m-context` | 1M input context |
| `claude-opus-4-7` | |
| `claude-sonnet-4-6` | 200K context |
| `claude-sonnet-4-6-1m-context` | 1M input context |
| `claude-haiku-4-5` | fast / cheap |
| `claude-fable` | |

**OpenAI**

| Model | Notes |
|---|---|
| `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-5.6-luna` | newest generation |
| `gpt-5.5`, `gpt-5.4` | `gpt-5.4` is the default |
| `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `gpt-5.2-codex`, `gpt-5-codex` | coding-tuned |
| `gpt-5`, `gpt-4.1`, `gpt-4o` | |
| `o3`, `o1` | reasoning models |

**Kimi For Coding**

| Model | Notes |
|---|---|
| `kimi-for-coding` | |
| `kimi-for-coding-highspeed` | |
| `kimi-k3` | |

Reasoning effort is set separately with `--reasoning` or `/reasoning`:
`off`, `minimal`, `low`, `medium`, `high`, `xhigh`. Not every model supports
every level — the catalog knows which, and rejects the rest.

### 3.3 The four ways to run Slo

```
     ┌──────────────────────────────────────────────────────────┐
     │  1. TUI            you + agent, interactive, in terminal  │
     │  2. HEADLESS       one prompt in, JSONL events out        │
     │  3. DYNAMIC        one orchestrator, many sub-agents      │
     │     WORKFLOWS                                             │
     │  4. SCHEDULED      launchd / cron fires a prompt on time  │
     └──────────────────────────────────────────────────────────┘
```

#### Mode 1 — the TUI (interactive)

```bash
slo                      # in the current directory
slo /path/to/project     # point at a project without cd-ing
slo --resume my-session  # pick up an old conversation by id or name
```

Useful flags:

| Flag | Effect |
|---|---|
| `--model <name>` | Override the model for this session |
| `--reasoning <level>` | `off` … `xhigh` |
| `--resume <id-or-name>` | Resume a stored session |
| `--workspace <file.code-workspace>` | Also load context from a VS Code workspace's folders |

Slash commands inside the TUI:

| Command | What it does |
|---|---|
| `/help` | List commands |
| `/diff <path>` | Open a full-screen diff of one file against `HEAD` |
| `/new [name]`, `/rename <name>` | Start or name a session |
| `/model <name>`, `/reasoning <level>` | Switch model or effort mid-session |
| `/context-window` | How full the context window is |
| `/compact` | Compact the history now |
| `/steer <text>` | Redirect the agent mid-run |
| `/abort` | Stop the current run |
| `/auth` | Re-open the sign-in modal |
| `/clear`, `/quit` | Clear the screen, exit |

#### Mode 2 — headless (scripts and CI)

`slo run` executes one prompt with no UI. **Every line of stdout is one JSON
event**, so you can pipe it straight into `jq`.

```bash
slo run -p "What is the current date?"
```

```json
{"kind":"text_start","iteration":0,"block_id":"blk-0"}
{"kind":"text_delta","iteration":0,"delta":"The current date is "}
{"kind":"text_delta","iteration":0,"delta":"2026-07-18."}
{"kind":"text_end","iteration":0,"content":"The current date is 2026-07-18."}
{"kind":"run_completed","iteration":0,"content":"The current date is 2026-07-18."}
```

The last line is always terminal: `run_completed`, `run_failed`, or `run_aborted`.

```bash
# just the final answer
slo run -p "Summarize src/" | jq -r 'select(.kind=="run_completed") | .content'

# stream the answer live
slo run -p "Write a haiku about Python" | jq -j 'select(.kind=="text_delta") | .delta'

# count tool calls by name
slo run -p "Refactor utils.py" \
  | jq -r 'select(.kind=="tool_call_end") | .tool_name' | sort | uniq -c | sort -rn
```

Exit codes let scripts branch without parsing anything:

| Terminal event | Exit code |
|---|---|
| `run_completed` | `0` |
| `run_failed` | `1` |
| `run_aborted` | `2` (SIGINT, `timeout`, orchestrator cancel) |

stdout carries agent events; **stderr carries structured lifecycle JSONL**
(`headless_session_started`, `headless_run_completed`, …), so you can split them:

```bash
slo run -p "Refactor utils.py" > output.jsonl 2> run.log
```

`slo run` flags:

| Flag | Default | What it does |
|---|---|---|
| `-p`, `--prompt` | required | The prompt to execute |
| `--model` | your preference | Override the model |
| `--reasoning` | model default | `off` … `xhigh` |
| `--cwd` | `$PWD` | Directory the agent reads and writes against |
| `--enable-history` | off | Persist the session (needed for `--resume`) |
| `--resume <ref>` | — | Resume by id or name (implies `--enable-history`) |
| `--session-id <val>` | generated | Explicit session id |
| `--orchestrator` | off | Turn this run into a sub-agent orchestrator |
| `--append-system-prompt-file` | — | Add per-run context to the system prompt |
| `--json` | — | Accepted for compatibility; output is JSONL either way |

**Slo as a long-lived service.** Headless runs are stateless by default, but give
them a stable session id and history and they thread one conversation across
calls:

```bash
export SLO_SESSION_ID="pr-$(git rev-parse --short HEAD)"
slo run -p "What does this branch change?" --enable-history > changes.jsonl
slo run -p "Any obvious bugs in those changes?" --enable-history > bugs.jsonl
slo run -p "Write a PR description from the above" --enable-history > pr.jsonl
```

The third call can see what the first two found. Bound any run with a hard wall
clock — on `SIGTERM` Slo aborts cleanly with exit code 2:

```bash
timeout -k 15 300 slo run -p "Long analysis task" > out.jsonl
```

#### Mode 3 — dynamic workflows

See [§5](#5-dynamic-workflows). In one line: say *"use dynamic workflows"* and
Slo stops doing the work itself and becomes a supervisor that splits the job
across focused sub-agents.

#### Mode 4 — scheduled runs (timers)

Slo persists a prompt plus a trigger, then registers it with your operating
system's scheduler — `launchd` on macOS, `cron` on Linux. The OS wakes up and
calls `slo schedule execute --name <id>`, which handles exactly one fire.

```bash
slo schedule add \
  --name "Daily Summary" \
  --prompt "Summarize the repo changes and failing tests from today." \
  --cron "0 18 * * *" \
  --cwd ~/Code/my-project \
  --session-mode fresh

slo schedule install --name "Daily Summary"
```

Commands:

| Command | What it does |
|---|---|
| `add` / `edit` | Create or rewrite a schedule |
| `list` / `show` | Inspect schedules |
| `execute` (alias `run`) | Fire one now — this is what the OS calls |
| `install` / `uninstall` | Register with or remove from the OS scheduler |
| `reports` / `show-report` | Immutable run records for a schedule |
| `cleanup` | Prune old run records (`--keep`, default 100) |

Exactly one trigger per schedule:

| Flag | Meaning |
|---|---|
| `--cron "0 18 * * *"` | Five-field cron expression |
| `--interval-seconds 300` | Every N seconds |
| `--run-at "2026-07-20T09:00:00+07:00"` | One-shot at an ISO-8601 timestamp |

Add `--tz` for cron timezone (default UTC), `--model` and `--cwd` to shape the run.

**Session modes** decide whether fires accumulate state:

| Mode | Each fire… | Good for |
|---|---|---|
| `fresh` | Runs as a new, isolated headless run | Daily summaries, batch checks |
| `continuous` | Targets one evolving session | Repo-watch, release prep, rolling reviews |

**The safety property worth understanding.** If a `continuous` schedule targets a
session you currently have **open in the TUI**, Slo does *not* start a second
process against it — that would give one conversation two writers. Instead:

```
   timer fires
       │
       ▼
  is the target session open in a TUI?
       │
       ├── no  ──▶ resume it headlessly (resume_headless)
       │
       └── yes ──▶ queue the work in that session's INBOX
                        │
                        ▼
                   the TUI polls its inbox only when idle,
                   claims the message, and runs it as a
                   normal turn inside the existing session
```

Use `--coalescing-mode latest_by_key --coalescing-key <key>` so a newer fire
replaces an older pending one instead of piling up while you are away.

### 3.4 Configuration reference

All configuration is environment variables.

**Core**

| Variable | Default | Meaning |
|---|---|---|
| `SLO_HOME` | `~/.slo` | Base directory for everything |
| `SLO_DEFAULT_MODEL_NAME` | `gpt-5.4` | Model used when none is specified |
| `SLO_SESSION_ID` | generated | Fixed session id for headless runs |
| `SLO_KB_DIR` | `$KB_DIR`, else `$SLO_HOME/KnowledgeBase/KB` | Path to a markdown knowledge base (optional; may not exist) |
| `KB_DIR` | unset | Fallback name for `SLO_KB_DIR` |
| `SLO_SKILLS_DIR` | installed package's `skills/` | Override the vendored skills directory |
| `SLO_LOG_FORMAT` | `json` | `json` or `text` |

**Credentials**

| Variable | Provider |
|---|---|
| `SLO_OPENAI_API_KEY` | OpenAI |
| `SLO_ANTHROPIC_API_KEY` | Anthropic |
| `SLO_KIMI_FOR_CODING_API_KEY` | Kimi For Coding |
| `SLO_AUTH_FILE` | Full path to the credentials file |

**Sub-agents and orchestration**

| Variable | Default | Meaning |
|---|---|---|
| `SLO_SUBAGENT_MAX_CONCURRENCY` | `4` | Sub-agents running at once |
| `SLO_SUBAGENT_MAX_TASKS` | `8` | Tasks per dispatch |
| `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS` | `10800` | Parent's silence ceiling (3h) |
| `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` | `7200` | Child's silence ceiling (2h) |
| `SLO_SUBAGENT_TERMINATE_GRACE_SECONDS` | `5` | Grace before a child is killed |
| `SLO_AUTO_VISUALIZE` | `1` | Auto-open the visualizer window; `0` disables |
| `SLO_VISUALIZER_REFRESH_SECONDS` | `2` | Visualizer poll cadence |
| `SLO_DETACHED_WORKFLOWS` | `1` | Allow detached (headless) workflows |
| `SLO_MAX_DETACHED_WORKFLOWS` | `2` | Cap on concurrent detached workflows |

> **The timeout trap.** `spawn_sub_agents` **blocks** the orchestrator. While a
> child runs, the parent's own stream emits nothing — so the *parent* guard
> (`SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS`) is the real ceiling on one phase, not
> the child's. A busy child keeps resetting its own guard and never trips it. If
> a phase runs a slow test suite, raise the parent guard **above** the child's,
> or the orchestrator will kill a perfectly healthy run with
> `TimeoutError: main agent stream produced no events`.

---

## 4. Skills

A **skill** is a markdown document that teaches Slo one repeatable task —
"how we build FastAPI routers", "how we write commit messages". Slo ships 116 of
them.

### 4.1 How a skill gets used

You never name a skill. You describe the task; Slo finds the skill.

```
  you: "Build a FastAPI router for user auth,
        with named arguments and type hints."
        │
        ▼
  Slo reads skills/INDEX.md  (the catalogue of all 117)
        │
        ▼
  matches: build-routers
           named-arguments-and-type-hints
           auth-security-patterns
        │
        ▼
  reads those SKILL.md files with the `read` tool
        │
        ▼
  writes the router following all three
```

The system prompt only carries a *pointer* to `skills/INDEX.md`. The agent reads
the index, picks what it needs, and reads only those files — so 117 skills cost
almost nothing until they are actually relevant.

### 4.2 What ships in the box

| Group | Count | Covers |
|---|---|---|
| `coding/` | 38 | Services, DAOs, routers, workers, agents, tests, conventions |
| `design-and-analysis/` | 26 | Feature specs, code review, planning, workflows |
| `git-ops/` | 13 | Branch, commit, PR, release, worktrees |
| `frontend-vue/` | 11 | Vue 3, Pinia, router, composables, SSE/WebSocket |
| `integration-tests/` | 11 | pytest-bdd scenarios, step definitions, debugging |
| `cli/` | 5 | Typer apps, command classes, Makefile conventions |
| `tui/` | 5 | Textual TUIs, scheduled operations |
| `presentation/` | 3 | HTML decks, single-page reports, print-ready PDF books |
| `orientation/` | 2 | Project onboarding, `RESEARCH.md` generation |
| `user-content/` | 2 | Creating your own skills and workflows |
| **Total** | **116** | |

**Python** is the deepest area — the `coding/` group carries the full stack:
domain features (model + DAO + service), application services, FastAPI routers,
middleware, Celery workers, DBOS workflows, LangGraph agents, ClickHouse,
Alembic, plus the always-on conventions (named arguments, type hints, Google
docstrings, declarative method structure).

**Design and specification** work is covered by `design-and-analysis/`: writing a
feature specification with mandatory PRE and POST hooks, verifying it, breaking
it into tasks, reviewing feature code, and distilling learnings into a knowledge
base.

### 4.3 Writing your own skill

Create `~/.slo/user_skills/<skill-name>/SKILL.md`. If the name matches a built-in,
**yours wins** — the built-in is shadowed, not merged.

```markdown
---
name: build-payments-service
description: How we build payment services in this organisation.
when_to_use: Load when writing or reviewing anything under src/payments/.
group: coding
kind: skill
---

# Building a payments service

## Guidance

1. Every amount is an integer of minor units. Never a float.
2. …
```

The frontmatter is what makes the skill findable: `description` and
`when_to_use` are how Slo decides whether to load it. Write them as triggers
("load when …"), not as prose.

This is the intended way to adopt Slo: take the defaults, override only what your
team does differently.

---

## 5. Dynamic workflows

### 5.1 The problem they solve

One agent doing a long, multi-step job accumulates everything in a single context
window — the spec, code written three steps ago, test output, review notes.
Signal gets diluted and later steps drift.

A **dynamic workflow** gives each phase its own clean context:

```
   WITHOUT                              WITH DYNAMIC WORKFLOWS

  ┌──────────────────┐                 ┌──────────────┐
  │   one agent      │                 │ ORCHESTRATOR │  supervises only
  │                  │                 └──────┬───────┘
  │  spec            │                        │ decomposes into phases
  │  + code          │                ┌───────┼───────┬─────────┐
  │  + tests         │                ▼       ▼       ▼         ▼
  │  + review        │             ┌─────┐ ┌─────┐ ┌──────┐ ┌──────┐
  │  + PR notes      │             │code │ │test │ │review│ │ ship │
  │                  │             └─────┘ └─────┘ └──────┘ └──────┘
  │  ...all in ONE   │              each a separate process with its
  │  context window  │              OWN fresh context window
  └──────────────────┘                        │
                                              ▼
                                       orchestrator synthesizes
```

What you gain:

- **Focus** — the "write tests" sub-agent sees only what it needs.
- **Isolation** — a phase that derails is one child process; the orchestrator
  retries just that phase instead of poisoning the run.
- **Parallelism** — independent phases run at once, up to the concurrency cap.
- **Oversight** — the orchestrator never does bulk work, so it always has room
  to reason about the whole.

### 5.2 Triggering one

**In the TUI**, say the words:

> "Use dynamic workflows: run the code-test-review workflow for
> `specifications/42-payments/overview.md`"

That runs **in your session** — the orchestrator dispatches phases and blocks
until it can hand back a synthesis.

To **detach** it into a background process, add an explicit detach word:
*"headless"*, *"detached"*, *"independent"*, *"in the background"*, or
*"without blocking"*.

**Headlessly**, use the flag:

```bash
slo run \
  -p "Use dynamic workflows: run the code-test-review workflow for
      the feature in specifications/42-payments/overview.md" \
  --orchestrator \
  --enable-history \
  --session-id ctr-20260718
```

`--orchestrator` injects the orchestrator system prompt, so you describe the
**task**, not the procedure.

### 5.3 What the orchestrator actually does

1. Reads the workflow file and enumerates its phases.
2. Builds a **self-contained** prompt for each phase — no pronouns, no "the
   previous step"; every sub-agent prompt stands alone.
3. Dispatches phases serially (a pipeline) or in parallel, up to
   `SLO_SUBAGENT_MAX_CONCURRENCY`.
4. Checks in on children, retrying a failed or aborted phase **once** with
   corrected parameters.
5. Collects every child's answer and synthesizes one result.

### 5.4 The two essential workflows

Slo ships two first-class workflows. Both live in
`slo/skills/design-and-analysis/workflows/`.

#### Specification Development — turn a rough idea into a verified spec

```
  rough request
       │
       ▼
  ┌──────────────┐   loads CLAUDE.md / AGENTS.md / RESEARCH.md,
  │  PRE hook    │   the affected code surface, every matching
  │ (mandatory)  │   build-*.md skill, and second-order needs
  └──────┬───────┘   (scale, latency, idempotency, deployment)
         ▼
  ┌──────────────┐
  │  draft spec  │   written to specifications/<n>-<title>/overview.md
  └──────┬───────┘
         ▼
  ┌──────────────┐   verifies against every applicable convention,
  │  POST hook   │   audits examples, checks test coverage, and
  │ (mandatory)  │   decides whether to split into sub-specs
  └──────┬───────┘
         ▼
    REVISE ──loop back──┐   until the verdict is READY
         │              │
         └──────────────┘
```

#### Code-Test-Review — take a feature from code to a reviewed PR

```
  Step 1          Step 2           Step 3            Step 4
┌────────┐     ┌────────┐      ┌──────────┐     ┌──────────┐
│ CODE   │────▶│ TESTS  │─────▶│  REVIEW  │────▶│   SHIP   │
│ (loop) │     │        │      │          │     │  the PR  │
└────────┘     └────────┘      └──────────┘     └──────────┘
   write         one test        an INDEPENDENT     branch,
   → test        per decision    reviewer checks    commit,
   → green       point           another agent's    open MR
                                 output
```

This is a **pipeline**: each phase waits for the previous phase's `READY`
verdict. Run it as a dynamic workflow and the reviewer is genuinely a different
agent with a different context — not the same model marking its own homework.

> A common mistake: asking for "the code-test-review workflow" and getting the
> `code-test-loop` **skill** instead. They are not the same. `code-test-loop` is
> only Step 1's coding cadence; loading it silently skips review and the
> completion check. Named workflows always come from the `workflows/` folder.

A third variant, `gitlab-code-test-review.md`, is the same pipeline with GitLab
merge-request steps.

### 5.5 Watching it run — `slo visualize`

When phases fan out across processes you want to see them. `slo visualize` is a
**read-only** TUI that attaches to the orchestrator's session:

```bash
slo visualize --session ctr-20260718 --follow --refresh-seconds 2
```

```
┌─ sub-agents ─────────┐┌─ transcript: phase-2-tests ──────────────┐
│ ✓ phase-1-code       ││ prompt: Write tests for the payments…    │
│ ⏳ phase-2-tests     ││ ⏺ read  src/payments/service.py          │
│ ◌ phase-3-review     ││ ⏺ write tests/payments/test_service.py   │
│ ◌ phase-4-ship       ││ ⏺ bash  pytest tests/payments -q         │
│                      ││    24 passed in 3.1s                     │
└──────────────────────┘└──────────────────────────────────────────┘
 parent: ctr-20260718 · running · 4 children · follow: on · 12:04:31
```

Status icons: ⏳ running · ✓ completed · ✗ failed · ⊘ aborted · ◌ pending.

| Key | Action |
|---|---|
| `↑` / `↓` | Move through the sub-agent list |
| `Enter` | Load the selected child's transcript |
| `r` | Force a refresh |
| `f` | Toggle follow (live polling) |
| `q` | Quit |
| `ctrl+←/→`, `ctrl+↑/↓` | Resize the panes |

It reads from the history store, so it never interferes with the running
workflow — and it works just as well after the workflow has finished
(`--no-follow`). From the TUI it opens automatically in a new terminal window
when the first sub-agent spawns; set `SLO_AUTO_VISUALIZE=0` if you would rather
launch it yourself.

### 5.6 Scheduled supervision

Combine a `continuous` schedule with an orchestrator session and you get a
supervised loop that needs nobody at the keyboard:

```bash
slo --resume nightly-review          # orchestrator owns a rolling session

slo schedule add \
  --name "Nightly Review Check-in" \
  --prompt "Check in on the running sub-agents: report which phases are still
            running, retry anything stalled, and synthesize completed work." \
  --cron "0 * * * *" \
  --session-mode continuous \
  --session-reference nightly-review \
  --coalescing-mode latest_by_key \
  --coalescing-key nightly-review

slo schedule install --name "Nightly Review Check-in"
```

Every hour the orchestrator wakes through the session inbox, inspects its
children, retries what failed, and folds finished work into the session.

---

## 6. Code structure

### 6.1 The libraries Slo is built on

| Library | Role |
|---|---|
| **LangGraph** | The state machine for one turn: `[agent node] → [tools node]` |
| **LangChain** | The model abstraction (`BaseChatModel`, `BaseTool`, `BaseMessage`) |
| **Textual** | The terminal UI framework (both the main TUI and the visualizer) |
| **Typer** | The CLI — `slo`, `slo run`, `slo schedule`, `slo visualize` |
| **Pydantic** | Every DAO; all data crossing a layer boundary is a typed model |
| **Pillow** | Image sniffing and resizing for the `read` tool |
| **pypdf** | Text extraction for `read_pdf` |

### 6.2 The three-file pattern

Almost every feature area follows the same shape, so once you can read one you
can read them all:

```
  <feature>/
  ├── dao.py       Pydantic types. No behaviour. The vocabulary.
  ├── service.py   The logic. Classmethods, one public entry point.
  └── model.py     Persistence, where a feature has any.
```

The house rules that shape all of it: named arguments at every call site with two
or more arguments, explicit type hints everywhere, Google-style docstrings, and
**declarative method structure** — one decision per method, orchestrator methods
that read like a table of contents, no nesting past two levels.

### 6.3 Directory map

```
slo/
├── src/
│   ├── agents/
│   │   ├── base.py              LLMFactory.create — the ONLY place an LLM is built
│   │   ├── providers/           Anthropic / OpenAI / Kimi adapters, ModelPool,
│   │   │                        the error classifier, FauxChatModel (test double)
│   │   ├── model_catalog/       Which models exist, their limits and aliases
│   │   ├── slo_agent/
│   │   │   ├── agent.py         the multi-turn loop
│   │   │   ├── graph/           the LangGraph state machine (one turn)
│   │   │   ├── sessions/        SloAgentSession — persistence, locking, events
│   │   │   ├── history/         the event log, projector, token estimator
│   │   │   ├── compaction/      context-window measurement and compaction
│   │   │   ├── tool_execution/  parallel-vs-sequential tool planning
│   │   │   ├── orchestrator/    sub-agent spawning and supervision
│   │   │   ├── prompts/         SystemPromptBuilder + the static strings
│   │   │   └── project_context/ walks up for SLO.md / AGENTS.md / CLAUDE.md
│   │   └── tools/               the 10 tools (see below)
│   ├── auth/                    credential resolver, store, OAuth flows
│   ├── cli/                     Typer app: run / serve / visualize / update / schedule
│   └── tui/                     the Textual UI (see §6.7)
├── skills/                      117 SKILL.md files + INDEX.md
├── tests/                       ~3,200 tests
└── docs/                        headless + scheduler cookbooks
```

### 6.4 The tools

Ten tools are bound to every session by default:

| Tool | What it does |
|---|---|
| `read` | Read a text file — or an image, or reject a binary safely |
| `write` | Write or overwrite a file |
| `edit` | Exact-string find and replace |
| `bash` | Run a shell command |
| `grep` | Regex search across files |
| `find` | Find files by name or pattern |
| `ls` | List a directory |
| `read_pdf` | Extract text from a PDF |
| `now` | Current date and time |
| `show_git_diff` | **New** — safe `HEAD`-versus-worktree content for one file |

Blocking work (file I/O, PDF extraction) is pushed onto threads behind a
semaphore, so a read-heavy batch never freezes the UI.

In orchestrator mode the agent also gets `spawn_sub_agents` and
`launch_workflow` — see [§5](#5-dynamic-workflows).

#### The new diff tools

Two surfaces, one safety model.

**`/diff <repository-relative-path>`** — in the TUI, opens a full-screen,
read-only diff of one worktree file against `HEAD`:

```
  src/payments/service.py                      HEAD ⟷ worktree
 ────────────────────────────────────────────────────────────────
   14   def charge(self, *, amount: int) -> Receipt:
 - 15       if amount > 0:                            ← red gutter
 + 15       if amount <= 0:                           ← green gutter
 + 16           raise ValueError("amount must be positive")
   17       return self._gateway.charge(amount=amount)
 ────────────────────────────────────────────────────────────────
  s side-by-side   w wrap   a annotations   Esc back
```

**`show_git_diff(repository_relative_path="src/tui/app.py")`** — the agent-callable
version, returning the same validated before/after content as JSON.

Both were built **clean-room**: the diff engine (`src/tui/slodiff/`) uses only
Python's standard-library `difflib` plus Textual — no third-party diff library is
vendored. It is deliberately extractable, with the model separated from the view,
and the view is imported lazily so a diff dependency can never slow down startup.

The safety rules are identical on both surfaces: absolute paths, `..` traversal,
and `.git` paths are rejected; UTF-8 text only, 1 MB per side; binary, unchanged,
or unavailable files produce a message rather than an error. Neither surface ever
modifies the repository.

One difference worth knowing: `/diff` resolves against the **session working
directory**; `show_git_diff` resolves against the **process working directory**.

### 6.5 Image resizing — protecting the context window

Reading a screenshot used to be a good way to blow up a session. A 4000×3000 PNG
base64-encodes to megabytes; the provider rejects it, or it eats the context
window, and every later turn replays it.

Slo fixes this at both ends:

```
  read("screenshot.png")
        │
        ▼
  Pillow sniffs the content ── JPEG / PNG / GIF / WEBP?
        │
        ▼
  longest edge > 1568 px? ──yes──▶ resize in memory (aspect preserved)
        │                           the file on disk is NEVER modified
        ▼
  encoded payload > 5 MiB? ──yes──▶ ONE JPEG fallback re-encode
        │                              │
        │                              └─ still over? → clear read error
        ▼                                  (better than a provider rejection)
  ┌──────────────────────┬───────────────────────────────────┐
  │ THIS turn gets:      │ DURABLE HISTORY gets:             │
  │ a real image block   │ [image attached: shot.png,        │
  │ the model can see    │  1568x1176, ref /abs/path]        │
  └──────────────────────┴───────────────────────────────────┘
```

That last split is the important part. The live turn sees the actual image; the
stored history keeps a compact **reference**. So when you resume a session
tomorrow, the transcript still tells you an image was there and where it lives,
without replaying megabytes of base64 into the context or inflating token
estimates.

### 6.6 Auto-compaction — never running out of room

Context is finite. Slo tracks fullness and rewrites history before it becomes a
problem.

**Measuring.** `ContextWindowSnapshotService` is a pure read model. It resolves
the routed model's capacity from the catalog and sums **only the events that
actually replay** into a prompt. That is deliberately different from cumulative
provider billing totals, and usually lower — streamed deltas and audit events
count toward your bill but never re-enter the context. `/context-window` shows
you this number.

**Rewriting.** All three paths — automatic, overflow, and your manual `/compact`
— go through one durable seam, `compact_to_boundary()`, which is transactional:

```
  1. write the compacted candidate + fsync
  2. move the live history to a deterministic archive
  3. activate the candidate
  4. write metadata

  If any ordinary step fails ──▶ the original history is restored byte-identical
  If restoration itself fails ─▶ HistoryCompactionRecoveryError names both paths
```

Compaction always cuts on a **turn boundary**. Because a tool call and its result
share a turn, a compacted history can never end up with an orphaned tool call —
which is the usual way naive compaction corrupts a conversation.

**The overflow backstop.** If a provider rejects a request outright for being too
large, Slo does not just fail. It runs a forced compaction, emits compaction
lifecycle events, records an audit entry, and retries **once**. That retry does
not re-persist your message (no duplicate history) and excludes the failed turn
from replay. A second overflow is terminal — the budget guard stops it looping.

### 6.7 How the TUI is designed

The central idea: **every conversational entry is its own widget**, and the same
widgets serve both live streaming and replay.

```
┌─ SloTUI (Textual App) ───────────────────────────────────┐
│ ┌──────────────────────────────────────────────────────┐ │
│ │  UserMessageBlock       "add tests for payments"     │ │
│ │  AssistantStreamBlock   reasoning ▸ answer (streams) │ │
│ │  ToolExecutionBlock     ⏺ read  service.py     ✓     │ │
│ │  ToolExecutionBlock     ⏺ bash  pytest -q      ✓     │ │
│ │  AssistantStreamBlock   "24 tests pass."             │ │
│ └──────────────────────────────────────────────────────┘ │
│  ThinkingSpinner        ✦ working…                       │
│  UsageStatusBar         tokens · model · rate state      │
│  PromptInput            > _                              │
└──────────────────────────────────────────────────────────┘
```

- `UserMessageBlock` — one of your turns.
- `AssistantStreamBlock` — one assistant turn; reasoning and answer stream into
  separate surfaces inside it. One block per loop iteration.
- `ToolExecutionBlock` — one tool call plus its result, updating as it runs.

**Live and replay share one path.** `TranscriptProjector` mounts widgets for
streamed events; `ReplayEntryProjector` reads the stored JSONL and mounts *the
same widget types*. A resumed session is pixel-identical to a live one — and any
rendering fix lands in both at once.

**Slash commands** are a three-part split: `SlashCommandRegistry` holds the
metadata, `SlashSuggestionEngine` does prefix-match autocomplete, and
`SlashRouter` dispatches. Adding a command means adding a spec and a handler.

**Copying text.** Drag-select any range and releasing the mouse copies it — no
keystroke. Every assistant block also has a Copy control for the whole response.
Delivery tries the local clipboard first and *always* falls back to an OSC 52
escape, so copy works over SSH and inside tmux.

> A detail that explains an odd-looking class: Textual's `Static` treats `[...]`
> as console markup, so `list[str]` in a transcript would silently vanish. Every
> plain-text surface therefore renders through `LiteralTextStatic` (a `Static`
> with `markup=False`), keeping type hints, timestamps, JSON, and regex literal.

**Strict boundaries.** The app never parses workflow payloads itself. It hands
raw data to a service, gets back typed *effects* (`launch_visualizer`,
`reset_launch_guard`), and executes them. The UI layer holds no domain logic.

---

## 7. More usage details

Condensed from <https://www.get-slo.sh> — see the site for the full guides.

**Project context is automatic.** Slo walks up from your working directory
looking for `SLO.md`, `AGENTS.md`, and `CLAUDE.md`, and loads what it finds. A
global `~/.slo/SLO.md` is prepended first, so your personal preferences are
always in scope. No project context file yet? Ask:

> "Generate a RESEARCH.md and AGENTS.md for this project."

**A knowledge base is optional but powerful.** Point `SLO_KB_DIR` at a folder of
markdown and Slo navigates it with the same `read` and `grep` tools it uses on
code — following cross-links and searching by symptom. Good for cross-project
patterns, failure-mode lookups, and conventions too broad for one repo.

```bash
export SLO_KB_DIR=~/Code/KnowledgeBase/KB
```

No `SLO_KB_DIR`? Skills also look in `$SLO_HOME/KnowledgeBase/KB`
(`~/.slo/KnowledgeBase/KB` by default) for a `Welcome.md` or `index.md`. If
neither location has a knowledge base, the agent says so, offers to create
one there, and keeps working. A missing knowledge base never blocks a task.

**Ask Slo what it knows.** Rather than memorising 117 skill names:

> "What skills do you have for working with Vue components?"

**Sessions persist by default in the TUI**, and not at all in headless runs
unless you pass `--enable-history`. Resume either by id or by the name you gave
it:

```bash
slo --resume payments-refactor
```

**A PDF document skill ships in the box.** Ask Slo to turn a report, brief, or
portfolio into a print-ready, field-guide-style PDF and it uses the
`present-as-pdf-book` skill — full-bleed cover, dotted-leader table of contents
with real page numbers, part dividers, callout boxes, captioned diagrams.

---

## 8. Known limitations

An honest list. Some are deliberate trade-offs, some are just not built yet.

### Access and platform

- **Early access.** Installation is credential-free — the installer and its
  Git source are public — but there is no package on PyPI or Homebrew; the
  one-line installer is the only distribution channel.
- **macOS and Linux only.** No Windows build. WSL is untested.
- **Python 3.11 exactly** (`>=3.11,<3.12`). Not 3.12 — the dependency lock is
  validated on 3.11 and `pipx` installs against `python3.11`.

### Providers and cost

- **No subscription plans.** Claude.ai Pro/Team and ChatGPT Plus do **not** work.
  Slo needs API access with usage-based billing, and you pay per token. This is
  the single most common setup failure.
- **Three providers only** — OpenAI, Anthropic, Kimi For Coding. No Gemini,
  Bedrock, Vertex, Ollama, or local models.
- **Kimi has no OAuth** and no prompt caching, so repeated context is re-billed
  on every call.

### Safety and sandboxing

- **The `bash` tool is not sandboxed.** It runs with your user's full
  permissions. Slo is not a safe place to run untrusted instructions, and there
  is no container or VM boundary. Point it at repositories you trust.
- **No per-tool approval prompts.** Once a session is running, the agent uses
  its tools without asking each time. Your controls are `/abort`, the working
  directory scope, and version control.

### Agent behaviour

- **Skills are read, not injected.** The system prompt carries a pointer to
  `skills/INDEX.md` rather than an inline manifest of skill names. This keeps
  the prompt small, but it means the agent must *choose* to read the index — a
  vaguely worded request can miss a skill that would have applied. Being
  specific measurably improves selection.
- **Blocking sub-agent dispatch.** `spawn_sub_agents` blocks the orchestrator
  while children run, so the parent's inactivity guard — not the child's — is
  the real ceiling on one phase. Long test suites need both guards raised, or a
  healthy run gets killed as "hung". See [§3.4](#34-configuration-reference).
- **One retry per failed phase.** A phase that fails twice is reported, not
  rescued.
- **Compaction is lossy by nature.** Old turns are summarised away. Anything
  that must survive belongs in a file, not in the conversation.

### Compared with other coding agents

- **No IDE extension.** Slo is terminal-only — no VS Code or JetBrains plugin,
  no inline-in-editor diffs. It reads a `.code-workspace` file for context, but
  that is the extent of the integration.
- **No web or desktop UI.**
- **Git operations go through `bash` and skills**, not a native integration.
  There is no built-in GitHub/GitLab app, no PR review UI. Diff *viewing* is
  native (`/diff`); staging, committing, and pushing are shell commands the
  agent runs.
- **No MCP support.** Slo has its own fixed tool bundle and does not speak the
  Model Context Protocol, so the MCP server ecosystem is not available to it.
  Adding a capability means adding a tool to the codebase.
- **No image generation or computer use** — Slo reads images, it does not create
  them or drive a browser.
- **Small ecosystem.** The skills are the extension point, and they are markdown
  documents — powerful for conventions, but not a plugin API. There is no
  marketplace.

---

## Repository layout

This repository is the workspace for Slo development:

```
slo-harness/
├── README.md            ← you are here
├── slo/                 the agent package
│   ├── README.md        long-form code walkthrough
│   ├── AGENTS.md        terse operational reference
│   ├── CHANGELOG.md     release history
│   ├── src/  tests/  skills/  docs/
└── feature-requests/    incoming feature requests
```

Contributor docs: [`slo/AGENTS.md`](slo/AGENTS.md) for conventions and module
layout, [`slo/docs/SLO_HEADLESS_README.md`](slo/docs/SLO_HEADLESS_README.md) for
the headless cookbook, and
[`slo/docs/SLO_SCHEDULER_README.md`](slo/docs/SLO_SCHEDULER_README.md) for the
scheduler.

---

*Slo · GPL v2 · early access · <https://www.get-slo.sh>*
