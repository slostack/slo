# Slo — A Reader's Guide to the Code


### How to read this book

- **Linear reading** is the right default. The chapters are
  dependency-ordered: each one assumes the previous one. Chapter 4 — the
  full lifecycle of a prompt — is the centerpiece; everything else is
  scaffolding for it or extension of it.
- **As a reference**, jump to the [File Map appendix](#appendix-a--file-map)
  for "where does X live?" lookups.
- **As a primer for Textual**, [Chapter 3](#chapter-3--a-five-minute-textual-primer)
  stands alone.
- **As a maintainer**, read [Maintainer Reference](#maintainer-reference)
  at the end: the maintained repository layout, style rules, testing rules,
  commit/branch conventions, specification conventions, and the rule for
  keeping this README current. Exact values (timeouts, env-var defaults,
  caps, on-disk layouts, step-by-step how-tos) live in the repository's
  root `RESEARCH.md`.
- Every code excerpt cites its source as `path/to/file.py:line-line`. Open
  the file in your editor; the citation is the contract.

### Who this book is for

- Engineers joining the Slo project who need to be productive on day one.
- Engineers maintaining a similar Textual-based agent and looking for a
  working blueprint.
- Curious readers who have used Claude Code or Aider and want to see how a
  comparable system is wired internally.

If you have never used Textual: keep going. Chapter 3 brings you up to
speed in fifteen minutes.

### A note on scope

Slo lives in a monorepo. This book covers the **`slo/` subdirectory only**
— the agent, the TUI, the CLI, the auth layer, and the tests. Sibling
specifications under `specifications/` and the Knowledge Base under
`KB/slo/` are referenced where relevant but are not the subject.

This README is the single maintained reference for the codebase (it
replaces the former `AGENTS.md`). The repository instruction file that
Slo auto-loads into every agent session is `SLO.md`; durable,
value-level project knowledge lives in `RESEARCH.md`.

### What Slo is

Slo is a **Python ReAct coding-agent harness** modelled on
[pi.dev](https://pi.dev) — a mature TypeScript reference agent. We borrow
pi's design ideas and re-implement them in Python under our own
conventions: LangGraph for the state machine, LangChain for the LLM layer,
and Textual for the TUI. One-line framing: *pi is the teacher; Slo is the
student we own.*

What Slo does:

- Runs an unbounded ReAct loop (reason → act → observe → repeat) over a
  cloud LLM with the file/shell tool bundle bound at session start
  ([§5.4](#54-tools)).
- Streams progress to the Textual TUI via `AgentStreamEventDAO` events
  ([Chapter 4](#chapter-4--the-anatomy-of-a-prompt)).
- Persists a full-fidelity event log per session under
  `~/.slo/sessions/history/` ([Maintainer Reference → History and
  persistence](#history-and-persistence)).
- Loads project instruction files (`SLO.md` / `AGENTS.md` / `CLAUDE.md`,
  plus `docs/RESEARCH.md`) from the working-directory lineage into the
  system prompt automatically ([§5.3](#53-the-system-prompt-builder)).
- Keeps the vendored convention skills (`skills/`) readable on demand via
  the `read` tool ([Chapter 5.7](#chapter-57--user-defined-skills-and-workflows)).
- Spawns and supervises headless sub-agents via `spawn_sub_agents` when
  promoted to orchestrator mode ([Chapter 9](#chapter-9--sub-agent-orchestration)).

---

## Chapter 1 — Installing Slo on Your Laptop

> **Installing, updating, or hosting the one-line installer?** See
> KB **`slo/install-guide.md`** — the authoritative guide to
> `install.sh`, the credential-free `curl | bash` production flow (Cloudflare
> Worker hosting at `get-slo.sh`), `slo update`, uninstalling, and
> troubleshooting. The narrative below is a summary; that document supersedes
> it wherever the two disagree.
>
> **Need architecture and runtime docs?** See
> the knowledge base page KB **`slo/codebase-index.md`** for the codebase index,
> KB **`slo/headless-guide.md`** for headless
> execution and orchestrator usage, and
> KB **`slo/scheduler-guide.md`** for the
> scheduler CLI, recurring runs, TUI/session delivery, and control-flow
> walkthroughs.

Before any of the agent code matters, Slo has to exist on your machine in
a form Python can run. There are two supported installation paths: the
**production path** (a one-line installer that drops a `slo` binary in
your shell), and the **developer path** (a virtualenv-managed checkout
you can hack on). Both end at the same place — a `slo` command that opens
the TUI — but they differ in how the source code is laid out and which
Python environment owns it.

### 1.1 Prerequisites

Slo runs on Python 3.11.7. Specifically `>=3.11,<3.12` per the
`requires-python` line in `pyproject.toml:9`. The narrow upper bound is
intentional: the dependency lockfile is validated against 3.11 only, and
the installer pins `--python python3.11` when calling `pipx`. Open the
upper bound when you regenerate the lock against 3.12 and prove the
suite green — until then, stay on 3.11.

You also need:

- **`pyenv`** with `pyenv-virtualenv` to manage interpreters and create
  isolated venvs without contaminating system Python. (`install.sh`
  bootstraps this for you if it is missing.)
- **Poetry 2.x** — developer path only, for dependency resolution and the
  editable install.
- **`git`**, because pip fetches the package straight from the public Git
  repository.
- **Either an Anthropic Claude subscription or an OpenAI ChatGPT
  subscription** for the OAuth path, *or* an API key from
  `console.anthropic.com` / `platform.openai.com` for the paste-a-key
  path. You can sort this out after first launch — the TUI will walk you
  through it.

### 1.2 The Production Path — `install.sh`

The script at the repository root handles the end-to-end install. It is
published as a Cloudflare Worker bound to `get-slo.sh`, served at both `/`
and `/install.sh`:

```bash
curl -fsSL https://get-slo.sh/install.sh | bash
```

Both the bootstrap script and its Git source are **public** — no
`SLO_DEPLOY_TOKEN`, deploy token, or personal access token is required, and
any such variables already in your environment are ignored. To pin a
release instead of the hosted default, add `SLO_REF`:

```bash
curl -fsSL https://get-slo.sh/install.sh | SLO_REF=v0.3.2 bash
```

The script:

1. Ensures the toolchain it needs — `git`, `pyenv`, Python 3.11.x, and
   `pipx` — installing only what is missing. Each step is a no-op when
   already satisfied.
2. Resolves `SLO_HOME` (default `~/.slo`) and creates it if missing — as a
   **data** directory, not a checkout. Install, upgrade, and uninstall
   never write into it.
3. Runs `pipx install --force --python <python3.11>
   "git+https://gitlab.com/core-27/slo.git@<ref>#subdirectory=slo"`, which
   builds an isolated venv and puts the `slo` binary on your `$PATH`. The
   `#subdirectory=slo` fragment is required because the repo root has no
   `pyproject.toml`.

Re-running the installer upgrades in place; it is idempotent.

If GitLab is inaccessible, the installer and `slo update` retry once from
`https://github.com/slostack/slo.git` with the same requested ref and subdirectory.
Build/dependency errors on a reachable GitLab are not retried. Latest-release
lookup also falls back when GitLab cannot be reached. Set
`SLO_REPO_FALLBACK_URL=''` to disable fallback; custom primary URLs require an
explicit mirror. **While the GitHub mirror is private, installs require existing
Git read authentication; anonymous fallback requires making the mirror public.**
No setup/API token is injected into installation URLs. A private mirror
requires pre-existing Git read authentication; the push deploy key is not an
end-user credential. `SLO_REPO_URL` and `SLO_REPO_FALLBACK_URL` configure both
the installer and `slo update` (`Updater` in `src/cli/update.py`), and
finalisation still runs only after installation succeeds. See the installation
guide, KB `slo/install-guide.md` (section "Public repository installation").

`pyproject.toml` declares packaging-owned `slo` and `slo-entry` scripts, both
currently targeting `src.cli:main`. After pipx generates both artifacts,
`install.sh` replaces only the user-facing `slo` launcher with a validated,
marked POSIX wrapper. The wrapper invokes the pinned pipx interpreter as
`python -I <absolute slo-entry>`, so hostile Python import paths cannot select
foreign `src` or `config` modules before the Typer app starts. This installed
path is distinct from trusted development source execution, which may run
`python -m src.cli`. `install.sh` is the only wrapper writer; `-I` protects
initial CLI import resolution while preserving ordinary environment values.

The same isolation applies to the processes Slo starts itself (spec 82.a):
sub-agents, detached workflow orchestrators, and workflow resumes always run
`sys.executable -I -m src.cli` with the sanitized child environment. Slo must
therefore be *installed* in that interpreter (an editable install is fine); a
source checkout on cwd or `PYTHONPATH` alone is not enough. Isolation applies
to the agent interpreter, not to project commands the agent launches. The
visualizer source fallback remains trusted-source-only with no forwarded
`PYTHONPATH`.

To upgrade later, run `slo update` (latest release tag), `slo update
--development` (`main`), `slo update --ref <ref>`, or re-run the matching
tagged public installer. Every successful update first runs the installed
`install.sh --finalize-launcher`, then sets only missing `SLO_HOME`,
`SLO_SKILLS_DIR`, and `SLO_KB_DIR` defaults through
`install.sh --finalize-environment`; existing variables are never changed.
Direct `pipx install`, `upgrade`, or `reinstall` bypasses launcher
finalisation. It is not a supported repair path; rerun the matching tagged
public installer instead.

### 1.3 The Developer Path — pyenv + Poetry

If you cloned the repo manually and want a Poetry-managed workflow:

```bash
# From the repo root
cd slo/

# Create and activate the venv
pyenv virtualenv 3.11.7 slo
pyenv local slo   # writes .python-version; auto-activates on cd

# Confirm the interpreter
which python
# /Users/<you>/.pyenv/versions/slo/bin/python

# Install everything including dev deps
poetry install
```

`poetry install` reads `pyproject.toml` and `poetry.lock`, then installs
every runtime dependency (LangChain, LangGraph, Textual,
aiohttp, …), every dev dependency (`pytest`, `black`, `mypy`,
`autoflake`), and finally registers the `slo` console script the same
way `install.sh` does. After this you can run `slo` directly from any
directory.

Three environment rules matter on the developer path:

- **The pyenv virtualenv named `slo` (Python 3.11.7) is mandatory.** Never
  use system Python (the macOS default is 3.9).
- **Run `poetry install`, not `poetry install --no-root`**, while the
  virtualenv is active. `poetry.toml` sets `virtualenvs.create=false`, so
  Poetry installs into the pyenv env instead of creating its own.
- **Non-interactive tool shells** (agents, CI steps) may not fire the
  `pyenv activate` hooks. Verify that `which python` resolves to
  `~/.pyenv/versions/slo/bin/python` before running anything.

The Makefile targets (`make test`, `make lint`, `make format`,
`make build-skill-index`, `make install`, …) are listed in
[Maintainer Reference → Everyday commands](#everyday-commands).

### 1.4 Where Things Live

Two directories outside your working tree matter:

- **`~/.slo/`** is Slo's persistent **data** root — not a checkout. pipx
  owns the code in its own isolated venv; `~/.slo/` holds runtime state:
  user skills at `~/.slo/user_skills/`, sessions, and logs. Install,
  upgrade, and uninstall leave it untouched.
- **`~/.slo/global/authentication.json`** is the credential store written
  by the auth modal. Mode `0600` on the file, `0700` on its parent. We
  walk through this in [Chapter 6](#chapter-6--credentials-and-the-auth-modal).

For backwards compatibility Slo also reads **`~/.claude/.credentials.json`**
— the OAuth file the Claude desktop CLI writes after `claude /login`.
This is honoured for Anthropic only, as a third-tier fallback. If you
already authenticated `claude` against your subscription, Slo inherits
that login.

### 1.5 Verifying the Installation

Once installed, three commands prove the surface is alive:

```bash
slo --version            # prints the version from pyproject.toml
slo --help               # the Typer help block
make test                # full non-E2E suite; inspect the actual result
```

The Makefile lives at `slo/Makefile`. Run `make test-env` first: it reports
`tests.env` when the local file is readable, otherwise `fallback`. Inspect a local
`environments/tests.env` before sourcing it; it is not a shipped-file assumption.
The tracked Makefile fallback supplies non-secret test settings, disables automatic
windows and Herdr, and uses a synthetic credential placeholder. Root test fixtures
also strip inherited Herdr settings and guard real process/window boundaries.
Never source development settings for tests. `make test` runs the full non-E2E
suite; `make smoke` runs only smoke tests; `make lint` checks **src and tests**.
A passing test suite does not waive a failing static or live-acceptance gate.

---

## Optional Herdr integration

This checkout adds optional status reporting, private native restore, and workflow
viewer submission inside Herdr. Slo still owns execution, tools, retries, history,
and token accounting; a slow or unavailable Herdr must not become a prompt gate.
**Herdr 0.9.2+ is a target, not verified live compatibility.** Offline implementation
evidence is not release approval. T6 composed acceptance, independent review and
live pane/restart evidence have separate gates; static failures remain unwaived.

Start Slo normally from a Herdr pane that supplies `HERDR_ENV=1`, `HERDR_PANE_ID`
and an absolute `HERDR_BIN_PATH` (`HERDR_SOCKET_PATH` is optional). The compact
metadata profile is default; `SLO_HERDR_METADATA_PROFILE=detail` explicitly opts
into additional numeric telemetry. Neither profile publishes conversation text,
credentials, raw errors, arbitrary model/provider/session labels or private paths.
See setup, privacy, retention and rollback in KB `slo/install-guide.md` → "Optional Herdr integration"
before enabling or testing it.

Eligible interactive sessions advertise exactly:

```text
slo --resume <canonical-UUID> --herdr-restore r1-<32-lowercase-hex>
```

Use the installed plain `slo` on PATH, the same `SLO_HOME`, and its default history
root across restart. The reference restores immutable saved configuration with
**current history**, not a history checkpoint or a replay of a submitted prompt.
Records are private and retained without automatic garbage collection; missing or
unsafe records fail closed. Ordinary `--resume` still supports normal name/slug
resolution but does not promise exact saved policy.

Workflow viewers get one automatic split/run attempt per parent per adapter
lifetime. A submitted command is not proof that a viewer painted or stayed alive.
Repeated requests give manual selection/recovery guidance; Slo does not discover,
focus, replace or close retained panes automatically. Enabled-but-unavailable Herdr
does not fall back to opening an OS terminal.

A shutdown-refused inbox item stays **claimed and unacknowledged**. Investigate
privately before explicit resubmission; there is no automatic replay/requeue or
exactly-once crash guarantee. An already registered task follows its existing
execution policy; acknowledgement is not completion proof.

To disable integration, set `SLO_HERDR_DISABLED=1` **before restarting Slo**.
This is not a hot toggle or a cleanup command. Keep history, retained references
and user-owned viewer panes. Older Slo may not understand `--herdr-restore`;
remove the saved Herdr command through an explicitly authorized operation or use
ordinary resume explicitly when rolling back.

## Chapter 2 — Your First Conversation

Launching the TUI is one word: `slo`. What you see next depends on whether
you have credentials configured. We'll walk through both states.

### 2.1 Launching the TUI

```bash
slo                      # opens the TUI scoped to the current directory
slo /path/to/project     # opens the TUI scoped to the given directory
```

The Typer dispatcher at `src/cli/app.py` interprets the first positional
argument as a workdir. The agent uses this directory as its filesystem
root when running tools like `read`, `write`, `bash`, and `grep`. If you
run `slo` from inside a project, the agent operates on that project; if
you `slo ~/code/other-project`, the agent operates on the other project
*without changing your shell's `cwd`*.

The TUI fills your terminal. The body is a transcript area; the bottom
is a multi-line input box; the footer shows the bindings for `ctrl+c`
(abort/quit), `ctrl+d` (quit), and `ctrl+l` (clear). The header carries
the title (`slo · <workdir> · <model>`) and a subtitle (`session
<8-char-id>`).

The theme is `tokyo-night` by default (`src/tui/app.py` sets
`DEFAULT_THEME = "tokyo-night"` and the `__init__` assigns
`self.theme = self.DEFAULT_THEME`). Switch themes at runtime with
`ctrl+p` (Textual's command palette) → "Change theme".

### 2.2 The Authentication Modal

On first launch — no env vars set, no
`~/.slo/global/authentication.json`, no legacy `~/.claude/.credentials.json`
— the TUI immediately pushes the authentication modal on top of the
transcript. The check happens in `SloTUI.on_mount` at `src/tui/app.py`:
once the renderer is subscribed and the input is focused, the mount calls
`self._has_credential_for_active_model()`. If that returns `False`, the
modal pushes via `self.push_screen(AuthenticationScreen(),
callback=self._on_auth_dismissed)`.

The modal is a five-step state machine driven by message bubbling. The
states are enumerated in `src/tui/authentication/auth_state.py`:

```
PROVIDER → METHOD → ( OAUTH | API_KEY ) → SUCCESS
```

You pick a provider (Anthropic or OpenAI), then a method: browser
authorization, device authorization (OpenAI), or paste-an-API-key.

- **Browser authorization.** The modal paints the authorization URL and
  the loopback redirect URI, then binds a one-shot local callback server.
  It tries to open your browser only when a graphical session exists
  (macOS, Windows, or `DISPLAY` / `WAYLAND_DISPLAY` / `BROWSER` set), and
  never blocks the TUI while doing so. You sign in on the provider's page;
  the redirect lands, or you paste the displayed code or the final
  redirect URL into the modal (the paste fallback for SSH, containers, or
  another machine).
- **Device authorization.** The modal paints the verification URL
  (`https://auth.openai.com/codex/device`) and a user code. Open the URL on
  any device, enter the code, and the modal finishes on its own once you
  approve.

Authorization and verification URLs are clickable hyperlinks. Terminals
that support OSC 8 open them with Cmd/Ctrl-click, and clicking (or Enter
on the focused link) inside the modal asks the app to open a browser. The
full URL always stays painted, wrapped and selectable, so you can copy it
when neither works. The redirect URI is plain text because it is not a
page to visit. Browser authorization URLs sign in to your account: treat
them like a password.

On success the modal exchanges the code for a token and writes a
`CredentialDAO` to `~/.slo/global/authentication.json` (mode `0600`).

If you pick paste-an-API-key, the modal shows a password-styled input,
validates non-empty, and persists the row the same way.

Either way, the modal dismisses with the persisted `CredentialDAO` and
the transcript regains focus. Future launches skip the modal because
`CredentialResolver.resolve` finds the persisted credential.

To re-open the modal later — to switch providers, paste a new key, or
re-sign-in — type `/auth` and press Enter. We walk through the modal's
internals in [Chapter 6](#chapter-6--credentials-and-the-auth-modal).

### 2.3 Sending Your First Prompt

Type a prompt and press Enter:

```
> Give me a short summary of this project
```

A spinner appears below the input — `✦ Pondering…`, rotating through
verbs every 1.5 seconds (Investigating, Crafting, Reading, Working,
Thinking). The agent is loading the system prompt, opening files,
running tools.

As tool calls land, the transcript fills with `⏺` / `⎿` blocks:

```
⏺ Read(file_path="src/cli/app.py", offset=0)
⎿ 134 lines · 4.2 KB
⏺ Grep(pattern="def main", path="src/")
⎿ 3 matches
⏺ Bash(command="ls -la src/auth")
⎿ exit 0 · 8 lines
```

Each `⏺` line is a headline: the tool name plus its salient arguments.
Each `⎿` line is a one-line summary of what the tool returned — number
of lines for `read`, number of matches for `grep`, exit code and line
count for `bash`, and so on. The summarizer is a class-level dispatch
table in `src/tui/event_renderer.py`.

When the agent finishes, the final response is shown as conventional readable
Markdown: headings, lists, code fences, and link destinations are compiled away
from the visible selectable buffer while exact raw Markdown remains available
through the explicit raw-copy shortcut.

```
This project is a Python coding agent built on LangGraph and Textual…
```

### 2.4 Reading the Transcript

The transcript is a scrollable column of widgets — a
`VerticalScroll(#transcript-scroll)` wrapping a `Vertical(#transcript-content)`
into which each conversational entry is mounted as its own component (see
Chapter 4): a `UserMessageBlock` for your turn, an
`AssistantStreamThinkingBlock` per thinking segment, an answer-only
`AssistantStreamBlock` per assistant iteration, and a `ToolExecutionBlock`
per tool call. Only
non-conversational notices (slash-command output, the `(aborting…)` marker)
mount as plain `Static`s. Every entry also records a logical line with a
*semantic class* — `user-line`, `tool-line`, `tool-result`,
`assistant-final`, `assistant-aborted` — into `_TranscriptAdapter.lines`
for tests, copy, and replay. The classes are themed via `src/tui/app.tcss`:

```css
.tool-line     { color: $success; text-style: bold; }
.tool-result   { color: $text-muted; }
.thinking-spinner { color: $accent; text-style: italic; padding: 0 1; }
```

`$success`, `$text-muted`, `$accent` are theme tokens. When you change
themes via the command palette, the entire transcript repaints with new
colors because the palette only changes which RGB the tokens resolve to.

**Copying text.** Drag the mouse across the transcript to select any range;
releasing the drag **auto-copies** the selection to your clipboard — no
keystroke needed. AI answer, thinking, and user bodies support character, word,
and wrapped-range selection from their compiler-produced visible Markdown buffer.
Structural source chrome is hidden in normal rendering; exact whole-message raw
Markdown is available from a focused transcript body through `ctrl+shift+m` /
`meta+shift+m`. Standard `ctrl+shift+c` / `meta+c` copies the complete visible
body buffer. Every path uses the same local `pyperclip` then OSC 52 delivery
funnel, so copy works both locally and over SSH/tmux. Native selection needs Textual's
selection API, so slo pins
`textual >= 8.2.7`. One consequence of that version: `Static` treats `[...]`
in a string as console markup, so every plain-text transcript surface is
rendered through `LiteralTextStatic` (a `Static` with `markup=False`) to keep
type hints (`list[str]`), timestamps, JSON, and regex spans literal.

### 2.5 Slash Commands

Type `/` at the start of a line and press Enter to invoke a slash
command. The router is in `src/tui/slash_router.py:32`:

| Command | What it does |
|---|---|
| `/help` `/h` `/?` | Print the slash-command help block |
| `/clear` | Clear the transcript (agent state untouched) |
| `/exit` `/quit` `/q` | Quit the TUI |
| `/cwd` | Print the active workdir |
| `/abort` | Cancel the in-flight prompt (graceful — the agent finishes its current step) |
| `/steer <text>` | Queue a steering message that joins the next turn |
| `/auth` | Re-open the authentication modal |
| `/new [session name]` | Replace the current session with a fresh one (optionally named) |
| `/rename <session name>` | Rename the current session (resumable by name via `--resume`) |
| `/model <name>` | Switch model; on a pooled session this clears the pool |
| `/reasoning <level>` | Set the canonical reasoning level |
| `/diff <repository-relative-path>` | Open the focused HEAD-versus-worktree diff screen for one file |
| `/context-window` | Report the routed model's capacity and the projector-faithful durable replay estimate |
| `/compact` | Request one lock-safe, transactional manual compaction (rejected while a prompt owns the session lock) |
| `/workflows` `/wf` | List detached workflows; `abort <id>` SIGTERMs the workflow's process group (SIGKILL after 5 s); `dismiss <id>` acknowledges a stalled one; `tui dismiss [<id>]` clears finished groups from the TUI session list (in memory only; running groups stay) |

The router is **Textual-free**: every handler returns a
`SlashCommandResultDAO` (`src/tui/slash_router.py:17`) carrying flags
like `rendered`, `should_clear`, `should_exit`, `open_auth_modal`. The
TUI translates those flags into `push_screen`, `exit`, transcript
writes. This separation is what lets us test the router in plain pytest
without spinning up a Textual `App`.

Three collaborators sit around the router: `SlashCommandRegistry`
(`src/tui/slash_command_registry.py`) holds the command metadata as
`SlashCommandSpecDAO`s; `SlashSuggestionEngine`
(`src/tui/slash_suggestion_engine.py`) does prefix-match autocomplete; and
`SlashSuggestionMenu` (`src/tui/widgets/slash_suggestion_menu.py`) renders
the dropdown. `/workflows resume <workflow-id>` relaunches a stalled or
failed detached workflow (see [§9.7](#97-detached-workflows-the-session-list-and-child-abort)).

---

## Chapter 3 — A Five-Minute Textual Primer

Slo is built on Textual — a Rich-powered TUI framework that brings web
conventions (DOM, CSS, event bubbling, virtual widgets) to the terminal.
If you've used React or Vue you'll feel at home; if you haven't, you only
need five concepts to read the code.

### 3.1 Apps, Widgets, and the DOM

A Textual program is a `textual.app.App` subclass. The `App` owns the
screen, the event loop, the message pump, and the input devices. When you
run the app, Textual constructs a **DOM tree** of widgets — much like a
browser builds a DOM from HTML.

`SloTUI` lives at `src/tui/app.py`:

```python
class SloTUI(App):
    CSS_PATH = "app.tcss"
    BINDINGS = [Binding(key="ctrl+c", action="interrupt", ...), ...]
    DEFAULT_THEME: str = "tokyo-night"

    def __init__(self, *, session: SloAgentSession) -> None:
        super().__init__()
        self.theme = self.DEFAULT_THEME
        self._session = session
        # ...

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="chat-shell"):
            self._transcript_scroll = VerticalScroll(id="transcript-scroll")
            self._transcript_content = Vertical(id="transcript-content")
            with self._transcript_scroll:
                yield self._transcript_content   # turns mount here, in order
            self._status_region = Vertical(id="status-region")
            yield self._status_region            # fixed spinner slot
            self._input = PromptInput()
            yield self._input                    # pinned at the bottom
        yield Footer()
```

Three key pieces:

- **`CSS_PATH`** points to a `.tcss` file (Textual CSS). Loaded once at
  app start, applied to the DOM.
- **`BINDINGS`** is a list of `Binding` objects. Each maps a key chord to
  an action method on the app (`action_interrupt`, `action_clear`, etc.).
- **`compose`** is the constructor of the DOM tree. It's a Python
  generator — `yield` a widget and Textual mounts it as a child of the
  current container. `with Vertical():` enters a container; everything
  yielded inside is a child.

After `compose` returns, Textual calls `on_mount` on every widget in
mount order. `SloTUI.on_mount` is where we subscribe the renderer to the
session, set the header title, focus the input, and conditionally push
the auth modal.

### 3.2 Compose, Mount, and Render

Three lifecycle methods on every widget, in order:

1. **`compose() -> ComposeResult`** — declares children. Called once.
2. **`on_mount()`** — called after the widget joins the live DOM. You
   subscribe to events, fetch data, start timers here.
3. **`render() -> RenderableType`** — Textual asks the widget what to
   paint. Widgets backed by Rich renderables (`Static`, `RichLog`,
   `Label`) implement this for you; you'd override it only for a custom
   visual.

You'll see `compose` and `on_mount` everywhere in the auth widgets at
`src/tui/authentication/widgets/`. None of them override `render` —
they're all built from `Static` + `RadioSet` + `Button` + `Input`
primitives that handle their own painting.

### 3.3 Messages and Event Handlers

This is the most important Textual concept for reading Slo's code.

Widgets communicate by **posting messages**. A `Message` is a class
nested inside the widget that emits it. The message bubbles up through
the DOM tree until something handles it. Handlers are discovered by
**name convention**: a method named `on_<widget_snake_case>_<message_snake_case>`
on any ancestor will be called.

Example from `src/tui/authentication/widgets/provider_select.py`:

```python
class ProviderSelectWidget(Vertical):
    class Chosen(Message):
        def __init__(self, *, provider: ProviderName) -> None:
            self.provider = provider
            super().__init__()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "provider-continue":
            self.post_message(self.Chosen(provider=self._selected_provider()))
```

And the handler in `src/tui/authentication/auth_screen.py`:

```python
async def on_provider_select_widget_chosen(
    self, event: ProviderSelectWidget.Chosen
) -> None:
    self._chosen_provider = event.provider
    await self._swap_step(widget=MethodSelectWidget(provider=event.provider))
```

Three things to absorb:

1. The handler name is **derived mechanically** from the message class.
   `ProviderSelectWidget` → `provider_select_widget`. `Chosen` → `chosen`.
   The whole handler name is `on_provider_select_widget_chosen`.
2. The handler runs on the **first ancestor** that defines it. So
   `AuthenticationScreen` handles the message; the button itself does
   not, even though the click happened on the button.
3. Multi-word names: Textual's snake-case converter treats consecutive
   uppercase letters as one word — `OAuthStatusWidget` becomes
   `oauth_status_widget`, **not** `o_auth_status_widget`. If you get the
   handler name wrong, the message silently goes uncaught. (We hit this
   bug during implementation.)

### 3.4 Modal Screens and Screen Stacks

Textual organises its UI as a **stack of Screens**. The default Screen
is whatever your `App.compose` returned. You can push another Screen on
top with `app.push_screen(screen, callback=...)`. The pushed screen
captures input until it dismisses itself via `self.dismiss(value)`. The
callback receives whatever `dismiss` was called with.

A **`ModalScreen`** is a Screen subclass that visually overlays the
underlying screen and grabs focus. The auth modal is a `ModalScreen`:

```python
class AuthenticationScreen(ModalScreen[Optional[CredentialDAO]]):
    def __init__(self, *, store=None, oauth_factory=None) -> None:
        super().__init__()
        # ...
```

The generic parameter `Optional[CredentialDAO]` tells Textual the type
the modal dismisses with. So the callback in `SloTUI._on_auth_dismissed`
is typed as `(value: Optional[CredentialDAO]) -> None` — you get either
a credential (on success) or `None` (on cancel).

### 3.5 TCSS — Styling the DOM

Textual's CSS is conceptually identical to web CSS but with TUI-specific
properties. Selectors target widget class names; properties target
colour, layout, text style, scrollbars, borders.

`src/tui/app.tcss`:

```css
Screen {
    background: $surface;
    padding: 0 1;
}

PromptInput {
    border: round $accent;
    background: $surface;
    height: auto;
    min-height: 3;
    max-height: 17;
    padding: 0 1;
    margin: 1 0 0 0;
}

.tool-line     { color: $success; text-style: bold; }
.tool-result   { color: $text-muted; }
.thinking-spinner { color: $accent; text-style: italic; padding: 0 1; }
```

A few key conventions:

- **Type selectors** (`Screen`, `PromptInput`) match widget class names
  and their subclasses. `PromptInput` matches because the widget is a
  subclass of `TextArea`.
- **Class selectors** (`.tool-line`) match widgets that have that
  *semantic class* set. We use them for transcript styling: every
  `_TranscriptAdapter.write(content, classes="tool-line")` lands a line
  tagged with that class.
- **Theme tokens** (`$surface`, `$accent`, `$success`, `$text-muted`,
  `$error`) are theme-dependent. Changing the theme via the command
  palette swaps the RGB the tokens resolve to without touching the CSS.

### 3.6 Pilot — Driving Textual in Tests

Every Textual `App` exposes `run_test()`, an async context manager that
returns a `Pilot` driver. The pilot can click buttons by selector, send
keypresses, and pause the event loop so the DOM settles.

Example from `tests/tui/authentication/widgets/test_provider_select.py`:

```python
class _Harness(App):
    def __init__(self) -> None:
        super().__init__()
        self.received_provider: Optional[ProviderName] = None

    def compose(self) -> ComposeResult:
        yield ProviderSelectWidget()

    def on_provider_select_widget_chosen(self, event) -> None:
        self.received_provider = event.provider


async def test_default_continue_emits_anthropic() -> None:
    app: _Harness = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#provider-continue")
        await pilot.pause()

    assert app.received_provider is ProviderName.ANTHROPIC
```

Three idioms to know:

1. **`async with app.run_test() as pilot:`** — runs the app inside a
   real Textual event loop, headless. The terminal isn't touched.
2. **`pilot.pause()`** — yields back to the event loop so pending
   mounts, message-pumps, and timers settle. Use it between every
   action; it costs nothing.
3. **`pilot.click("#some-id")`** / **`pilot.press("enter")`** — drive
   user actions. Selectors are Textual CSS-style; `#some-id` matches
   the widget with that `id`.

Pilot is what makes 50+ pilot-driven tests in this repo possible without
spinning up a terminal.

### 3.7 The Reactive System (Optional)

Widgets can declare **reactive attributes** (`reactive(...)`). Mutating
a reactive attribute on a widget triggers a re-render and an optional
watcher method. Slo uses this lightly: the auth modal's state machine
tracks `self._state: ScreenState`, but as a plain field — we change the
visible step by swapping the child widget, not by mutating a reactive.

You can ignore reactives until you need them. Most agent UIs don't.

---

## Chapter 4 — The Anatomy of a Prompt

This is the centerpiece. The following sections trace one prompt from
the moment your finger hits Enter to the moment the agent's final text
renders on screen. Every step cites a real file. By the end of this
chapter you should be able to set a breakpoint at any hop and know
exactly what's in scope.

> **What changed (feature `agent_reasoning_summaries`).** The prompt path
> was rebuilt around two ideas borrowed from `pi`. First, the runtime now
> streams **token-level deltas** for both reasoning summaries and answer
> text — not just whole-node updates — via a normalized event contract,
> `AgentStreamEventDAO`, which replaces the old `ProgressEventDAO`. Second,
> the transcript is no longer one giant `RichLog`: each assistant turn and
> each tool call is its **own mounted widget**, so a streaming delta
> re-renders only its own block instead of reparsing the entire log. The
> status spinner now lives in a fixed region pinned above the input. The
> sections below describe this new flow; the section "Per-Component
> Rendering" explains why the component-per-message model matters.
>
> **What changed again (feature `per_component_markdown_rendering`).** That
> first pass only componentised the *live* stream. This feature finished the
> job: **every** conversational entry is now a dedicated component, including
> the user turn (a new `UserMessageBlock`) and session **replay**. A resumed
> session mounts the same widgets the live path mounts — there are no flat
> conversational lines left. Replay reconstructs completed turns as
> `TranscriptEntryDAO`s via `ReplayEntryProjector` and feeds them through the
> same projector.

### The Runtime Chain at a Glance

Before the hop-by-hop walk, here is the whole chain and who owns what:

```
slo (pipx isolated wrapper → generated slo-entry → src/cli/__main__.py)
  └── TyperDispatch (src/cli/typer_dispatch.py)
        └── SloTUI.run() (src/tui/app.py)               # Textual app, interactive path
              └── SloAgentSession (src/agents/slo_agent/sessions/service.py)
                    └── SloAgent (src/agents/slo_agent/agent.py)
                          └── build_slo_agent() (src/agents/slo_agent/graph/service.py)
                                └── LangGraph StateGraph
                                      ├── [agent node]  — llm.ainvoke(messages)
                                      └── [tools node]  — tool execution
```

- **`TyperDispatch`** — parses CLI flags, resolves model/provider plus
  `--resume` session references (session id or name) and optional
  `--workspace <file.code-workspace>`, launches the TUI or a headless run,
  and owns the async boundary for `slo plugin install|list|uninstall|upgrade`.
- **`SloTUI`** — the Textual app. Owns the layout (header, scroll container,
  `UsageStatusBar`, `PromptInput`, footer), mounts transcript widgets,
  dispatches slash commands, owns `/new` session replacement and `/rename`,
  manages in-process prompt-history recall, and subscribes to the session's
  event stream.
- **`SloAgentSession`** — the process-level wrapper. Holds one `SloAgent`,
  enforces one in-flight prompt at a time, owns the subscriber list for render
  events, discovers/merges trusted plugins and subscribes their dispatcher,
  persists the history trace, exposes runtime naming (`rename_session`,
  `session_name`), and exposes slash methods (`abort`, `steer`, …).
- **`SloAgent`** — the multi-turn ReAct loop. Streams the graph in a loop
  until the model emits no tool calls, `abort()` fires, or the
  `should_stop_after_turn_hook` returns `True`; emits normalized
  `AgentStreamEventDAO` events on every chunk.
- **One LangGraph pass = one agent turn** — one LLM call followed by
  execution of whatever tool calls it returned (batch planning is described
  in [§5.4](#54-tools)).

Some module paths cited in the sections below predate the package split
(`session.py` → `sessions/service.py`, `graph.py` → `graph/service.py`,
`stream_event_dao.py` → `events/stream.py`, `rate_limit_policy.py` →
`rate_limit/`). The maintained tree is in
[Maintainer Reference → Repository layout](#repository-layout).

### 4.1 The Cast of Characters

The participants, roughly in order of appearance:

| Object | Lives at | What it does |
|---|---|---|
| `PromptInput` | `src/tui/app.py:33` | The text-area widget that captures the user's typing |
| `SloTUI` | `src/tui/app.py:78` | The `App` subclass; routes events; owns the transcript + fixed spinner; is the projector's mount **host** |
| `SloAgentSession` | `src/agents/slo_agent/session.py` | One agent per process; in-flight guard; persistent-history orchestration; subscriber fan-out |
| `SloAgent` | `src/agents/slo_agent/agent.py` | The stateful ReAct loop; runs the dual-mode graph stream (`react_streaming`) |
| LangGraph `StateGraph` | `src/agents/slo_agent/graph.py:build_slo_agent` | The compiled state machine that drives the loop |
| `AssistantChunkNormalizer` | `src/agents/slo_agent/assistant_chunk_normalizer.py` | Per-turn; turns raw `AIMessageChunk`s into ordered `AgentStreamEventDAO`s |
| `TurnStreamAccumulator` | `src/agents/slo_agent/turn_stream_accumulator.py` | Per-turn; holds completed-node truth (final text, stop-hook input) |
| `AgentStreamEventDAO` | `src/agents/slo_agent/stream_event_dao.py` | The normalized stream-event contract — 13 `kind`s |
| `TranscriptProjector` | `src/tui/transcript_projector.py` | Projects live events **and** replay entries into per-message transcript widgets |
| `UserMessageBlock` | `src/tui/widgets/user_message_block.py` | One user turn, rendered as padded markdown |
| `AssistantStreamThinkingBlock` | `src/tui/widgets/assistant_stream_thinking_block.py` | One thinking segment, keyed by normalized `block_id`; sealed by its repair end or a terminal sweep |
| `AssistantStreamBlock` | `src/tui/widgets/assistant_stream_block.py` | One assistant iteration, answer-only (thinking lives on the sibling thinking block) |
| `ToolExecutionBlock` | `src/tui/widgets/tool_execution_block.py` | One live tool call: a ⏺ headline + a ⎿ result line |
| `TranscriptEntryDAO` | `src/agents/slo_agent/history/transcript.py` | One completed entry for replay (the replay counterpart to `AgentStreamEventDAO`) |
| `ReplayEntryProjector` | `src/agents/slo_agent/history/transcript.py` | Folds canonical history events into ordered `TranscriptEntryDAO`s for replay |

### 4.2 The Keystroke Reaches `PromptInput`

`PromptInput` is a thin `TextArea` subclass. The `TextArea` widget
handles multi-line text editing out of the box — arrow keys, selection,
clipboard, multi-line wrapping. We customize two things: **soft wrap is
made explicit**, and a **bare Enter** submits the buffer instead of
inserting a newline. In the stylesheet, the widget uses `height: auto`
with a `max-height` that keeps up to 15 visible prompt lines on screen
before internal scrolling begins.

`src/tui/app.py:26`:

```python
class PromptInput(TextArea):
    def __init__(self) -> None:
        super().__init__(soft_wrap=True)

    class Submitted(Message):
        def __init__(self, *, text: str) -> None:
            self.text: str = text
            super().__init__()

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted(text=self.text))
            return
        await super()._on_key(event)
```

Why this matters: `TextArea` has no built-in `Submitted` message
(that's for `Input`, the single-line cousin). We synthesise one. Bare
Enter posts our custom `Submitted`; Shift+Enter falls through to the
base class which inserts a real newline. Every other key — arrows,
typing, backspace — falls through unchanged.

`event.prevent_default()` and `event.stop()` are Textual's way of saying
"this event is consumed; nobody else should see it". Without them,
TextArea's default Enter handling would also fire and add a newline.

### 4.3 `SloTUI` Routes the Submitted Text

`PromptInput.Submitted` bubbles up the DOM. `SloTUI` is its first
ancestor with a matching handler:

`src/tui/app.py` (the on_prompt_input_submitted method):

```python
async def on_prompt_input_submitted(
    self, event: PromptInput.Submitted
) -> None:
    text: str = (event.text or "").strip()
    if self._input is not None:
        self._input.load_text("")            # clear the input
    if not text:
        return                                # bare Enter on empty buffer → no-op
    if self._in_flight_task is not None:
        await self._queue_prompt(text=text)   # already running → visible one-deep queue
        return
    if text.startswith("/"):
        await self._dispatch_slash_command(line=text)
        return
    self._echo_user_line(text=text)
    self._in_flight_task = asyncio.create_task(self._run_prompt(text=text))
```

Read it top-to-bottom. Each line is one decision:

1. Strip and capture the text.
2. Clear the input box.
3. Empty? No-op.
4. Already running? Hold the prompt in the visible one-deep queue
   (`⏳ Queued: …`); it auto-submits when the current run ends. A second
   mid-run submission *replaces* the held one. `/abort` keeps the held
   prompt (with a notice); `/clear` drops it.
5. Slash command? Dispatch to the router (covered in 4.10).
6. Echo `> <text>` into the transcript with class `user-line`.
7. Spawn the prompt as a background asyncio task.

That last step is key. `_run_prompt` is a coroutine. We don't `await`
it — we wrap it in `asyncio.create_task` and keep going. The event loop
returns to the UI, the spinner mounts, and the prompt runs concurrently.

### 4.4 `_run_prompt` and the Fixed Status Spinner

`_run_prompt` is the task spawned in §4.3. It is small but its shape
encodes the spinner-placement fix:

```python
async def _run_prompt(self, *, text: str) -> None:
    self._projector.reset_for_new_run()
    await self._mount_spinner()
    saw_failed_event: bool = False
    try:
        async for event in self._session.prompt_streaming(text=text):
            if event.kind == "run_failed":
                saw_failed_event = True
    except ValueError as exc:
        self._write_adapter_line(
            content=f"(configuration error: {exc})", classes="tool-result",
        )
    except Exception as exc:                       # surface every failure
        if not saw_failed_event:
            self._render_run_error(exc=exc)
    finally:
        await self._unmount_spinner()
        self._in_flight_task = None
```

Three things to notice, all of them deliberate:

1. **`reset_for_new_run()`** clears the projector's per-run bookkeeping
   (which assistant block belongs to which iteration, which tool blocks
   are live) so the new prompt starts clean.
2. **The spinner mounts once and stays mounted for the whole run.** In
   the old design the first streamed event unmounted the spinner; that
   made the "Working…/Thinking…" indicator vanish the instant reasoning
   text appeared. Now the spinner lives in its own fixed region
   (`#status-region`) and is unmounted only in the `finally`. See §4.10.
3. The `async for` just drains the stream — every event has already been
   dispatched to subscribers (the projector included), so the loop body
   only watches for a `run_failed` event to avoid double-rendering the
   same error.

The transcript itself is **not** a `RichLog` anymore. `compose` builds a
scroll viewport holding a content column, with the status region and the
input pinned beneath it (`src/tui/app.py`):

```python
with Vertical(id="chat-shell"):
    self._transcript_scroll = VerticalScroll(id="transcript-scroll")
    self._transcript_content = Vertical(id="transcript-content")
    with self._transcript_scroll:
        yield self._transcript_content          # turns mount here, in order
    self._status_region = Vertical(id="status-region")
    yield self._status_region                   # the fixed spinner slot
    self._adapter = _TranscriptAdapter(tui=self)
    self._input = PromptInput()
    yield self._input                           # pinned at the bottom
```

### 4.5 `SloAgentSession.prompt_streaming` — Orchestration and History

`prompt_streaming` (`src/agents/slo_agent/session.py`) is the
orchestration seam. It does more than forward events: it owns the
persistent-history lifecycle around the agent run.

```python
async def prompt_streaming(
    self, *, text: str, history: Optional[list[dict]] = None,
) -> AsyncGenerator[AgentStreamEventDAO, None]:
    if self._is_running:
        raise RuntimeError("SloAgentSession already processing a prompt.")
    async with self._lock:
        self._is_running = True
        turn_id = str(uuid4())
        try:
            await self._ensure_history_session()         # 1
            await self._ensure_agent_ready()             # 2 (lazy LLM build)
            message_history = await self._load_message_history()  # 3
            await self._append_history_event(... kind="run_started" ...)   # 4
            await self._append_history_event(... kind="user_message" ...)  # 4
            runtime_handler = self._runtime_handler_for_turn(turn_id=turn_id)
            async for event in self.agent.react_streaming(   # 5
                query=text,
                message_history=message_history or None,
                runtime_handler=runtime_handler,
            ):
                await self._dispatch_event(event=event)      # fan-out
                if event.kind == "run_completed":
                    final_response = event.content or ""
                elif event.kind == "run_aborted":
                    aborted = True
                yield event
            # 6: append run_completed / run_aborted / run_failed terminal record
        finally:
            self._is_running = False
```

The lifecycle, in order: (1) ensure on-disk session metadata exists;
(2) lazy-build the `SloAgent` — its constructor calls
`LLMFactory.create → CredentialResolver.require`, so a missing token
raises `ValueError` that propagates out to `_run_prompt`'s
`except ValueError`; (3) load projected `BaseMessage` history from disk;
(4) persist `run_started` + `user_message` **before** the agent starts;
(5) run the agent, dispatching every event to subscribers and capturing
terminal content; (6) persist the terminal record.

Two invariants carried over from before:

- **`self.agent`** lazy-builds on first access (step 2).
- **The `_lock` + `_is_running` guard** serialize prompts; a second
  concurrent caller hits the `RuntimeError`.

`_dispatch_event` iterates `self._subscribers` and awaits each handler,
failure-isolated (one bad subscriber can't kill the run). The TUI
subscribed `self._render_event` at mount time. Tests register their own
subscriber to capture the event sequence. The `runtime_handler` is a
separate, correctness-critical observer that writes one canonical
history event per trace event — it is **not** a render subscriber.

### 4.6 `SloAgent.react_streaming` — The Dual-Mode LangGraph Loop

`SloAgent` wraps a **compiled LangGraph state graph** (`build_slo_agent`
in `src/agents/slo_agent/graph.py`) with two nodes — `agent` (calls the
LLM) and `tools` (executes requested tools) — run in a loop until the
agent emits an `AIMessage` with no `tool_calls`.

The important change is the **stream mode**. The loop now subscribes to
*both* of LangGraph's streams at once:

```python
async for raw_item in self._graph.astream(
    turn_state,
    stream_mode=["messages", "updates"],
):
```

- **`messages`** yields *token-level* `AIMessageChunk`s as the provider
  emits them. This is the live-streaming channel — reasoning summaries
  and answer text arrive a few tokens at a time.
- **`updates`** yields *completed* node outputs — the finished
  `AIMessage` for the turn and any `ToolMessage`s. This is the
  authoritative-truth channel.

Why both? The deltas give a responsive UI; the completed messages give
correct final formatting (provider spacing/paragraph breaks that partial
deltas mangle), the tool results, and the exact text the stop-hook and
the next turn must reason over. The loop reconciles the two channels per
turn.

The outer loop runs one iteration per ReAct turn and sets
`self._current_iteration` so every emitted event is tagged with its
turn (the projector keys assistant blocks on this — §4.9):

```python
iteration = 0
while True:
    self._current_iteration = iteration
    normalizer = AssistantChunkNormalizer(iteration=iteration)
    turn = TurnStreamAccumulator()
    turn_state = SloAgentStateDAO(messages=list(accumulated_messages))

    async for raw_item in self._graph.astream(turn_state, stream_mode=["messages", "updates"]):
        if self._abort_event.is_set():
            yield AgentStreamEventDAO(kind="run_aborted", iteration=iteration, content="<aborted>")
            return
        parsed = parse_graph_stream_item(raw_item=raw_item)     # version-safe decode
        if parsed.mode == "messages":
            for ev in normalizer.absorb_chunk(chunk=parsed.message_chunk):
                yield ev                                        # live thinking/text/tool-call deltas
            continue
        # updates: completed node truth
        delta_messages = self._chunk_message_delta(chunk=parsed.update_chunk)
        accumulated_messages.extend(delta_messages)
        turn.absorb_messages(messages=delta_messages)
        for msg in delta_messages:
            if isinstance(msg, AIMessage):
                for ev in normalizer.finalize_open_blocks(completed_assistant_message=msg):
                    yield ev                                    # *_end events carry completed truth
        for ev in self._stream_events_from_update_messages(messages=delta_messages, iteration=iteration):
            yield ev                                            # tool_result events

    for ev in normalizer.finalize_open_blocks(completed_assistant_message=turn.completed_assistant_message):
        yield ev
    self._last_assistant_text = turn.final_assistant_text
    if await self._evaluate_stop_hook(...) or not self._last_turn_has_tool_calls(...):
        break
    iteration += 1
    accumulated_messages.extend(self._drain(queue=self._steering_queue))   # injected /steer messages

yield AgentStreamEventDAO(kind="run_completed", iteration=self._current_iteration, content=self._last_assistant_text)
```

`parse_graph_stream_item` (`graph_stream_parser.py`) is a small
version-safe decoder: LangGraph wraps dual-stream items in several tuple
shapes (`("messages", (chunk, meta))`, `("updates", dict)`, optionally
namespaced), and the parser normalizes all of them into one
`ParsedGraphStreamItemDAO` so the loop never inspects raw tuples.

### 4.7 Provider-Progress Watchdog and Local Tools

Each streamed graph turn has a provider-progress watchdog. It permits **300
seconds** for the first provider-stream item and **300 seconds** between later
provider-progress items. These limits detect a provider stream that never
starts or stalls; they are not a general deadline for an entire agent run.
Operators may override them before starting Slo with:

- `SLO_PROVIDER_STREAM_FIRST_PROGRESS_TIMEOUT_SECONDS` — first provider-progress
  deadline (default: `300`).
- `SLO_PROVIDER_STREAM_IDLE_TIMEOUT_SECONDS` — gap allowed between later
  provider-progress items (default: `300`).

A tool call changes what the combined LangGraph stream is waiting on. Once Slo
observes a local `tool_call_start`, it suspends provider-progress timing while
local tools run. Timing resumes only after **all** observed local tool results
arrive. Consequently, a slow `bash`, file, PDF, or other local tool execution
is not misclassified as a stalled provider stream, including when a tool-call
message closes before its result is available.

The `bash` tool has a separate per-command ceiling of **1800 seconds** by
default. Set `SLO_BASH_DEFAULT_TIMEOUT_SECONDS` to a positive number to choose
a different default, or to `0` to disable that default ceiling. An explicit
tool-call timeout still takes precedence. For the complete headless and
orchestrator timeout reference, including reconnect, heartbeat, and child
inactivity settings, see KB `slo/headless-guide.md`; the exact values are
also collected in `RESEARCH.md`.

**Provider stream disconnection (spec 70).** `StreamRecoveryService`
(`src/agents/providers/stream_recovery/`) is the sole registry of concrete
`httpx`/`httpcore` transport-failure families; it never inspects model
identity. From the exception family plus the agent-owned *commit boundary*
(has visible output been committed yet?) it returns a redacted decision:
`RETRY_FRESH_CONNECTION` before commit, `DO_NOT_REPLAY` after. A known
pre-commit failure classifies as `STREAM_DISCONNECTED`; a `ModelPool` may
switch members only before its first chunk and records
`provider_stream_disconnected` rather than raw error text. After committed
output there is no automatic replay and no mid-stream switch. A reconnect
delay (`SLO_PROVIDER_STREAM_RECONNECT_DELAY_SECONDS`) completes the fast
transport policy that sits beneath the unchanged outer watchdogs. The
`stream_reconnecting` history event is diagnostic only and is excluded from
replay context. `WatchDogTimer` (`src/agents/slo_agent/watchdog_timer.py`)
owns the provider deadlines and the local-tool suspension described above.

### 4.7.1 Normalizing Chunks into Stream Events

The two channels from §4.6 are reconciled by two per-turn helpers.

**`AssistantChunkNormalizer`** (`assistant_chunk_normalizer.py`) is the
seam for the `messages` channel. It is stateful for one turn: it
remembers which thinking, text, and tool-call blocks are currently open
so it can emit deterministic `*_start` / `*_delta` / `*_end` events. Each
raw `AIMessageChunk` is decomposed:

- A `reasoning`/`thinking` content block → `thinking_start` then
  `thinking_delta`s. Reasoning summaries arrive as a provider `summary`
  (a string, or a list of `{text}` items) — the normalizer extracts the
  visible text. A reasoning block with only an `encrypted_content` /
  `signature` marker and no visible text emits a `redacted` thinking
  start+end pair (so encrypted reasoning is *acknowledged* but never
  shown).
- A `text`/`output_text` block → `text_start` then `text_delta`s.
- A `tool_call_chunk` / `function_call` / `tool_use` block (or, as a
  fallback, the chunk's `tool_call_chunks` attribute) → `tool_call_start`
  then `tool_call_delta`s carrying partial JSON argument fragments.

Switching from a thinking block to a text block (or vice versa) auto-emits
the closing `*_end` for the block being left open — so the projector
never interleaves two open streams.

**`TurnStreamAccumulator`** (`turn_stream_accumulator.py`) is the seam for
the `updates` channel. It just stores completed truth: the latest
completed `AIMessage`, the list of completed `ToolMessage`s, and
`final_assistant_text` (computed via `assistant_message_text`, which
normalizes the OpenAI Responses content-block shape to plain text). That
`final_assistant_text` is what feeds the stop-hook and the terminal
`run_completed` event.

When a completed `AIMessage` arrives on the `updates` channel, the loop
calls `normalizer.finalize_open_blocks(completed_assistant_message=msg)`.
This closes the open blocks with `*_end` events that **carry the completed
content** — the full reasoning summary and the full answer text. The
projector uses that completed text to overwrite the partial it streamed,
fixing any spacing/paragraph artifacts the token deltas introduced.
`ToolMessage`s on the `updates` channel become `tool_result` events via
`_stream_events_from_update_messages`.

### 4.8 The `AgentStreamEventDAO` Contract

Every event crossing the session→TUI boundary is now an
`AgentStreamEventDAO` (`stream_event_dao.py`) — this replaces the old
`ProgressEventDAO`. It is a discriminated union over a `kind` field:

```python
StreamEventKind = Literal[
    "thinking_start", "thinking_delta", "thinking_end",
    "text_start",     "text_delta",     "text_end",
    "tool_call_start","tool_call_delta","tool_call_end",
    "tool_result",
    "run_completed",  "run_aborted",    "run_failed",
]

class AgentStreamEventDAO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: StreamEventKind
    iteration: int = 0                       # which ReAct turn
    block_id: Optional[str] = None           # stable id for one visible block
    content_index: int = 0
    delta: Optional[str] = None              # incremental text for *_delta
    content: Optional[str] = None            # full/terminal text for *_end / run_*
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None
    tool_arguments_delta: Optional[str] = None
    redacted: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
```

The `kind` discriminator is what makes the rendering path a flat dispatch
instead of an isinstance chain — and `extra="forbid"` keeps raw provider
payloads from leaking into the contract. The `iteration` field is load-
bearing: it tells the projector which assistant block a delta belongs to
when a single prompt spans multiple ReAct turns.

### 4.9 Fan-Out and the `TranscriptProjector`

Each event is dispatched to subscribers in `prompt_streaming`. The TUI's
subscriber is now a one-liner — it owns no rendering logic itself:

```python
async def _render_event(self, event: AgentStreamEventDAO) -> None:
    await self._projector.project(event=event)
```

`TranscriptProjector` (`src/tui/transcript_projector.py`) is the stateful
event→widget machine. It holds three maps, all reset per run:

- `_assistant_blocks: dict[int, AssistantStreamBlock]` — **one block per
  iteration**, keyed by `event.iteration`. A later turn's reasoning never
  rewrites an earlier turn's block.
- `_tool_blocks: dict[str, ToolExecutionBlock]` — one block per
  `tool_call_id`.
- `_tool_argument_buffers` — accumulates streamed JSON argument fragments
  for best-effort live parsing of a tool call's args.

`project()` is the dispatch table:

```python
if event.kind == "thinking_delta":
    block = await self._ensure_assistant_block(iteration=event.iteration)
    block.append_thinking(delta=event.delta or "")
elif event.kind == "thinking_end":
    if event.content: block.set_thinking(content=event.content)   # completed truth
elif event.kind == "text_delta":
    block = await self._ensure_assistant_block(iteration=event.iteration)
    block.append_text(delta=event.delta or "")
elif event.kind == "text_end":
    if event.content: block.set_answer(content=event.content)     # completed truth
elif event.kind in {"tool_call_start", "tool_call_delta", "tool_call_end"}:
    block = await self._ensure_tool_block(tool_call_id=..., tool_name=...)
    block.update_tool_call(tool_name=..., tool_input=parsed_input)
elif event.kind == "tool_result":
    block.update_result(tool_name=..., output=event.content or "")
elif event.kind == "run_completed":
    await self._finalize_completed_run(iteration=..., content=...)
# run_aborted / run_failed → mark the block aborted/failed
```

`_ensure_assistant_block` mounts a fresh `AssistantStreamBlock` via the
host the **first** time it sees an iteration, then caches it; every
later delta for that iteration mutates the same widget. The host (the
`SloTUI`, via the `TranscriptMountHost` protocol) does the actual
`mount(...)` into `#transcript-content` and scrolls to the end. The
projector also calls `record_transcript_line(...)` for each logical line
— that updates the `_TranscriptAdapter`'s `lines` list (the test / copy /
replay seam) **without** mounting a duplicate visible widget, because the
live block already shows it.

The same projector owns two more entry points, so *every* transcript
entry — not just the streamed ones — flows through one component layer:

- **`project_user_turn(text=...)`** — called from `SloTUI._echo_user_line`
  the instant a prompt is submitted. It asks the host to mount a turn
  separator if prior content exists, mounts a `UserMessageBlock`, and
  records the `> text` logical line.
- **`project_replay_entry(entry=...)`** — called once per completed entry
  when a session resumes (see the replay section). It dispatches on
  `entry.kind` through a declarative `_replay_projectors` table
  (`user`/`assistant`/`tool`) and mounts a *finalized* component — the
  same widget classes the live path mounts, just built in one step
  instead of streamed.

### 4.10 Per-Component Rendering — Why Not One Giant Log

This is the architectural heart of the change, and it mirrors how `pi`
renders its chat.

**The old model.** The transcript was a single `RichLog`. Every assistant
turn appended to one growing document, and each streamed delta re-rendered
the whole accumulated markdown. That is `O(n²)` over a long turn: a
500-token answer reparses the entire block 500 times. It also blocked the
event loop and produced the "mangled, unspaced markdown" symptom.

**The new model.** Each semantic unit is its own widget, mounted once into
`#transcript-content` and mutated in place thereafter:

- **`UserMessageBlock`** (`widgets/user_message_block.py`) is a `Vertical`
  with a single compiler-produced visible `Content` body. It retains exact raw
  Markdown on the block and is built once — its
  renderable is constructed in `__init__` (not `on_mount`), because setting a
  `Static`'s content mid-mount-cycle races the child's first render and
  Textual raises while compositing.

- **`AssistantStreamBlock`** (`widgets/assistant_stream_block.py`) is an
  answer-only `Vertical` — one `AssistantAnswerBody` surface plus a
  terminal-note line. Reasoning lives on the sibling
  **`AssistantStreamThinkingBlock`** (`widgets/assistant_stream_thinking_block.py`),
  one widget per normalized thinking segment (keyed by `block_id`), mounted
  in true chronological order between answer and tool blocks.
  `append_thinking` / `append_text` accumulate into each block's own buffer
  and re-render **only that block's** compiler-visible `Content` body.
  `markdown_content_compiler.py` is the shared markdown-it AST owner: it writes
  a readable visible buffer and semantic spans while the block retains raw
  Markdown for explicit raw copy. Generic code spans precede safe Pygments
  overlays for exact case-insensitive trim-only aliases (Python, shell, data,
  diff/patch, JS/TS, TOML/INI/XML/HTML/CSS/SQL/Dockerfile/Markdown); diff and
  patch also add semantic added/removed/hunk/file line roles. Every fenced and
  indented block retains generic code styling, including unknown, malformed,
  attribute-bearing, unlabeled, unclosed, resolver-failed, lexer-failed, and
  reconstruction-failed fences; tokenization never changes the visible code.

  Reasoning renders as muted italic visible text with Pi-style
  horizontal padding, and — deliberately — **without** a literal "Thinking"
  heading, because the region is already visually distinct. `finalize(final_text=)`
  overwrites the answer with the completed text from the runtime (the
  source of truth), so streamed-delta artifacts never survive into the
  final view.

- **`ToolExecutionBlock`** (`widgets/tool_execution_block.py`) is a
  `Vertical` with a headline `Static` (the `⏺ tool(args)` line) and a
  result `Static` (the `⎿ summary` line). It reuses the same
  `format_tool_call_headline` / `format_tool_result_line` formatters from
  `event_renderer.py` (the ⏺/⎿ glyphs and per-tool summarizers — `read` →
  "<n> lines · <kb> KB", `bash` → "exit 0 · <n> lines", etc. — are
  unchanged; only their call site moved).

A streamed delta now touches exactly one `Static` inside one block. The
rest of the transcript — every prior turn, every prior tool call — is
untouched. That is the property that eliminates the quadratic reparse.

**The component hierarchy.** After this feature, `#transcript-content` is a
flat, ordered column of dedicated components — one per conversational
entry — and each textual message component owns its own compiler-visible
`Content` body:

```
SloTUI (App)
└── Vertical #chat-shell
    ├── VerticalScroll #transcript-scroll
    │   └── Vertical #transcript-content          ← entries mount here, in order
    │       ├── UserMessageBlock                  user turn
    │       │   └── Content .user-message-body         (compiled visible Markdown, rendered ONCE at build)
    │       ├── AssistantStreamBlock  (iteration 0)   assistant turn
    │       │   ├── Content .assistant-thinking-body   (compiled visible reasoning)
    │       │   ├── Content .assistant-answer-body ◀━━ UPDATED at end of stream
    │       │   └── Static .assistant-terminal-warning
    │       ├── ToolExecutionBlock  (tool_call_id)    tool call
    │       │   ├── Static .tool-call-headline         (⏺, rebuilt on each arg delta)
    │       │   └── Static .tool-call-result       ◀── reparsed once, when result arrives
    │       ├── AssistantStreamBlock  (iteration 1)   next assistant turn → its own block
    │       │   └── …
    │       └── Static .turn-separator / .tool-result  (non-conversational notices only)
    ├── Vertical #status-region
    │   └── ThinkingSpinner                       (fixed; run or flagged slash command)
    └── PromptInput                               (pinned at the bottom)
```

**Which component is independently reprocessed at end-of-stream.** The
**`AssistantStreamBlock`** is the one re-rendered when the message stream
closes. During streaming its `answer` region updates the *partial* source
buffer on each `text_delta`; then at the **end** of the assistant message
stream the completed truth replaces that partial in one final update of
**that block's answer `Content` only**:

- `text_end` (carrying completed text) → `set_answer(content=...)` →
  `_render_answer()` updates compiler-visible styled `Content`.
- `run_completed` → `finalize(final_text=...)` → `_render_answer()` updates
  once more with the runtime's authoritative final source, so any
  streamed-delta spacing artifacts are discarded.

The thinking block is likewise replaced once via `set_thinking` on a
content-bearing repair `thinking_end` (a contentless end leaves the segment
open for its repair). By contrast, the **`UserMessageBlock`** renders its
compiler-visible content exactly once at construction and is never reprocessed,
and a **`ToolExecutionBlock`** updates its result line only when its single
`tool_result` arrives. So the end-of-stream source update is scoped to one
`Content` body — the answer region of the current turn's
`AssistantStreamBlock` — never the transcript as a whole.

#### 4.10.1 The Transcript Window, Block Liveness, and the Protected Tail

Mounting one widget per semantic unit is what makes streaming cheap, but it
also means a long session accumulates widgets without bound. `TRANSCRIPT_WINDOW_SIZE`
(`src/tui/app.py`, currently `500`) caps how many children stay mounted under
`#transcript-content`. Every transcript mount calls `_enforce_transcript_window`,
which runs a single-flight `_run_window_enforcement_pass` that walks the children
**oldest first** and removes settled ones until the overflow is absorbed.

The pass has exactly one safety rule, decided by `_is_block_live`: **a block still
receiving streamed updates must never be evicted.** An `AssistantStreamBlock` is
live while `finalized` is `False`; a `ToolExecutionBlock` is live while it awaits
its result; a `SteeringPendingBlock` is live while it sits in
`_pending_steer_blocks`. Everything else — including `UserMessageBlock` — is
settled, because it never streams.

**The dual of that rule matters just as much: liveness must eventually be
*released*.** The projector mounts one `AssistantStreamBlock` per outer-loop ReAct
iteration, but the agent emits exactly one terminal event per prompt, carrying only
the *final* iteration number. A turn that drove five iterations therefore mounted
five blocks and resolved one — the other four sat at `finalized is False` forever,
and `reset_for_new_run` then cleared the tracking dict, making the leak permanent.
Because skipping a live child in the eviction walk costs nothing against the
overflow budget, enough falsely-live blocks let the walk march all the way to the
newest child. At exactly `live_blocks >= TRANSCRIPT_WINDOW_SIZE` the child it
reached and deleted was the `UserMessageBlock` the user had just submitted — the
prompt was accepted, mounted, and silently removed in the same frame.

Three changes close this (spec `61-deleting-user-message-fix`):

- **Run-end sweep.** `TranscriptProjector._seal_stale_assistant_blocks(except_iteration=…)`
  is called from all three terminal handlers (`_finalize_completed_run`,
  `_finalize_aborted_run`, `_finalize_failed_run`), so every block a run mounted is
  sealed before `reset_for_new_run` forgets about it. `AssistantStreamBlock.seal()`
  is idempotent and content-preserving — it stops the block accepting deltas without
  discarding what it already streamed.
- **Seal-on-advance.** `_ensure_assistant_block` calls the same helper right after
  mounting a new iteration's block. The ReAct iteration counter is strictly
  monotonic, so mounting iteration *n* proves every earlier block has stopped
  streaming. This bounds a single long-running turn, which the run-end sweep alone
  cannot do because it only fires once the run terminates.
- **Protected tail.** `TRANSCRIPT_PROTECTED_TAIL_SIZE` (`10`) and
  `_eviction_candidates(children=…)` structurally exclude the newest ten children
  from the candidate set, regardless of liveness. This is a *starvation guard*, not
  a replacement for `_is_block_live` — the `finalized` flag remains the correctness
  guard. Its job is to fix the failure *direction*: any future liveness-tracking bug
  now degrades to "the window briefly holds a few more widgets than the cap" instead
  of "the user's message vanished". The constant must stay strictly below
  `TRANSCRIPT_WINDOW_SIZE`, or enforcement stops converging; a test that patches the
  window below the tail must patch both.

`tests/tui/test_app.py::TestProtectedTail` reproduces the original threshold sweep
(`29 / 60 / 79 / 80 / 90 / 500 / 510` stuck-live blocks) against the real eviction algorithm,
and `TestLivenessLeakReproduction` drives the whole stack — agent, projector, and
widgets — to prove a multi-iteration turn no longer hides the next prompt.

#### 4.10.2 Recovering What the Window Collapsed

Evicted content is not lost — it is still on disk as `TranscriptEntryDAO` history.
Scrolling to the top triggers `_load_older_entries`, which prepends the next batch
above the current oldest child. That path is driven by one number,
`_load_older_cursor`, whose contract is **"how many logical entries sit above the
oldest entry currently mounted"**.

Hydration is what establishes it, and it does so by *bounding what it mounts*:
`_newest_hydration_entries` returns only the newest `TRANSCRIPT_HYDRATION_ENTRY_LIMIT`
(30) entries, and the cursor becomes exactly the number left behind. Mounting
everything and letting the window evict the excess — the previous behaviour —
made the cursor unrecoverable, because it was assigned `len(entries)` even though
eviction had already put most of those entries on screen. The first scroll-to-top
pass then re-fetched the batch that was already mounted and prepended it above
itself, duplicated and out of chronological order.

The cursor is deliberately **never** derived from evicted widget counts. One entry
mounts a variable number of widgets — a user turn mounts a separator *and* a
`UserMessageBlock`, and a single tool call can mount more than one
`ToolExecutionBlock` — so there is no ratio to invert.

Two consequences worth knowing:

- **The cursor can under-report, never over-report.** Nothing advances it while a
  live session evicts entries that hydration did mount, so scroll-to-top may not
  reach a middle band of history. That is the safe direction: under-reporting
  leaves a gap, over-reporting reintroduces duplicates.
- **A live, never-resumed session has no cursor at all** — there was nothing to
  hydrate, so it stays at `0`. `_earlier_summary_text` handles that honestly: with
  no reachable entry it renders `▲ earlier messages collapsed — resume this session
  to recover them` rather than the nonsensical `▲ 0 earlier messages hidden` plus a
  scroll-to-top hint that `_has_older_entries_to_load` would refuse.

### 4.11 The Fixed Spinner, Terminal Events, and Replay

**The spinner.** `#status-region` is a `Vertical` docked between the
scroll viewport and the input. `_mount_spinner` mounts the
`ThinkingSpinner` there at run start; it stays for the whole run and is
removed only in `_run_prompt`'s `finally`. Registry commands whose
`SlashCommandSpecDAO.shows_activity` flag is true also mount it for the
lifetime of slash dispatch; `/compact` is the first consumer and the existing
compaction events override its text with `Compacting session history…`.
Slash dispatch records whether it mounted the spinner and only removes that
instance, so a command cannot tear down a run-owned spinner. Because the
spinner is a sibling of the scroll region rather than a line *inside* the
transcript, scrolling content never hides it and the `PromptInput` never
moves.

**Terminal events.** When the loop ends, `react_streaming` yields one
terminal `AgentStreamEventDAO`:

- `run_completed` → `_finalize_completed_run` calls
  `block.finalize(final_text=content)` and records an `assistant-final`
  logical line.
- `run_aborted` (Ctrl+C) → `block.mark_aborted()` paints a `(aborted)`
  note while preserving partial content.
- `run_failed` → `block.mark_failed(error_message=…)` paints
  `(error: …)`; the session also persists a `run_failed` history record.

If no block exists yet (the run died before any visible content), the
projector falls back to a plain append-only line.

**Replay.** A resumed session reconstructs the transcript as **components**,
not flat lines. `SloAgentSession.hydrate_transcript_entries` asks
`ReplayEntryProjector.build_entries(events=...)` to fold the canonical
history event stream into ordered `TranscriptEntryDAO`s — one per completed
user turn, assistant turn (reasoning + answer + any terminal note), and
tool execution (its `tool_call` paired with its `tool_result`). Then
`_hydrate_transcript_from_history` feeds each entry through
`TranscriptProjector.project_replay_entry`, which mounts the same
`UserMessageBlock` / `AssistantStreamBlock` / `ToolExecutionBlock` widgets
the live path mounts. The result: a resumed conversation renders identically
to the live one that produced it.

Hydration runs **before** the live renderer subscribes, so the replayed
tail and live events never interleave. Each mounted entry still records its
logical line into `_TranscriptAdapter.lines` (the copy / dedupe seam), and
encrypted/redacted reasoning is never surfaced as visible text — it simply
mounts no thinking block, matching the live path.

The `async for` in `_run_prompt` exits; the `finally` unmounts the
spinner and clears `_in_flight_task`. The TUI is idle. Your next prompt
is on the way.

### Slash command branch

If the input started with `/`, step 4 from §4.3 took the
`_dispatch_slash_command` branch:

```python
async def _dispatch_slash_command(self, *, line: str) -> None:
    result = await SlashRouter.dispatch(line=line, session=self._session)
    if result.should_clear:
        await self.action_clear()
    if result.rendered is not None:
        self._write_adapter_line(content=result.rendered, classes="tool-result")
    if result.open_auth_modal:
        self._push_auth_modal()
    if result.should_exit:
        self.exit()
```

The router is at `src/tui/slash_router.py:32`. It looks up the command
in a handler dict and awaits the handler — handlers return a
`SlashCommandResultDAO`. The TUI honours each flag in turn. `/auth`
returns `open_auth_modal=True`; the TUI calls `push_screen` with the
auth modal; the modal lifecycle from Chapter 2 runs.

### 4.12 TUI Ownership Notes

The sections above follow one prompt. This section collects the TUI
ownership rules that apply around it.

**Thinking segments and routing.** An `AssistantStreamThinkingBlock` is one
normalized parent thinking segment, keyed by the normalizer's stable
`block_id`. It is sealed by its content-bearing repair end or by the
terminal-run sweep; a contentless `thinking_end` leaves the segment open and
live. `TranscriptProjector` owns parent `block_id` routing and mounts replay
reasoning as a sealed thinking block immediately before its answer block
(replay adjacency). `SloTUI` owns child/sub-agent events: they never mount a
foreground transcript block; child lifecycle events only request one
coalesced session-list refresh (feature 94, [§9.7](#97-detached-workflows-the-session-list-and-child-abort)).

**Pi design restyle (spec 72.a.5).** Both `Theme.variables` mappings in
`src/tui/theme.py` define the same seven Pi-derived semantic tokens —
`user-msg-bg`, `tool-pending-bg`, `tool-success-bg`, `tool-error-bg`,
`thinking-text`, `md-heading`, `border-muted` — and widget `DEFAULT_CSS`
consumes them via `$<token>` references (no hard-coded role colours). A user
turn is a quiet `user-msg-bg` band; thinking and answers stay bare on the
canvas (thinking is muted italic `thinking-text`, answer headings use warm
`md-heading`). A `ToolExecutionBlock` paints pending/success/error fills and
gains the CSS-state hooks `-done` (added by `update_result()`) and `-error`
(added by `mark_incomplete()`) purely as styling seams — `_result_output` /
`is_incomplete` remain the lifecycle truth used by `_is_block_live`. The
turn separator is a muted `─` rule (`_TranscriptAdapter.TURN_SEPARATOR`,
`border-muted`). `SloTUI._refresh_title_bar()` collapses the session workdir
to `~` / `~/...` via `_collapse_home_in_path` (`Path.relative_to` ancestry,
so home-prefix lookalikes stay absolute); the usage bar owns no cwd display.

**`UsageStatusBar`** (`src/tui/widgets/usage_status_bar.py`) is a `Static`
fixed above the footer, updated via `session.usage_snapshot` whenever
`SloAgentSession` emits a `SessionUsageSnapshotDAO` (which accumulates
`TokenUsageTotalsDAO` across turns). It renders Pi-style compact token
quantities (`6.0k`, `12k`, `1.0M`) for token values only — rpm, cooldown
seconds and context percent keep their raw units.

**Queued prompt (spec 72.a.4, input-adjacent anchoring).** An ordinary
(non-slash) prompt submitted while a run is active is held in a one-deep,
latest-wins app-owned slot (`_queued_prompt_text` plus its mounted
`QueuedPromptBlock`, rendered as `⏳ Queued: <text>`); a newer busy
submission replaces the held text in place. The block mounts into
`#chat-shell` directly before `PromptInput` — outside the scroll region — so
it stays visible while the transcript scrolls; it is never a transcript
child, so window eviction cannot reach it and `_is_block_live` has no
`QueuedPromptBlock` branch. There is still exactly one `session.invoke()`
task at a time: `_prompt_submission_lock` serializes acceptance with the
run-completion handoff (`_finish_prompt_run` → `_start_queued_prompt_if_idle`),
which removes the anchored block before echoing and starting the held turn.
`/abort` (and Ctrl+C) preserve the held prompt and write one survival notice;
`/clear` and an allowed `/new` discard it. Slash commands and inbox
`chat_turn` items never enter the user queue.

**Copy and output padding (specs 72.a.3 and 81).** No transcript block has a
card-local copy control. Copy runs through `SloTUI` only: the focus chord
(`ctrl+shift+c` / `meta+c` → `action_copy_visible_text` → the focused
block's `get_copyable_text()`) and mouse drag selection (`on_text_selected`)
both funnel into `copy_to_clipboard` (pyperclip → OSC 52). All four message
widgets keep the uniform `TRANSCRIPT_OUTPUT_PAD` convention (CSS
`padding: 0 1`); the `#transcript-content` outer-frame padding is unchanged.
OSC 133 prompt-zone markers are deferred until Textual offers a
terminal-output seam that preserves raw zero-cell controls end to end.

**Granular Markdown selection (spec 81.c.1).** `MarkdownContentCompiler`
(`src/tui/widgets/markdown_content_compiler.py`) is the one app-free
markdown-it AST-to-visible-text owner for `AssistantAnswerBody`,
`AssistantThinkingBody` and `UserMessageBody`. Its single append-only writer
produces `MarkdownContentDAO(raw_markdown, visible_text, spans)`: the message
block keeps raw Markdown, while `Content` renders, and native drag selection
extracts, only the readable visible buffer. Role-name spans resolve through the
active theme only at mounted body boundaries; Pygments adds spans, never display
text. Every fenced and indented block keeps `markdown-code`; unknown,
attribute-bearing, unlabeled, and failed fences stay generic-only; diff/patch
adds `markdown-code-diff-added` / `-removed` / `-hunk` / `-file` line roles
defined in both themes. There is no offset mapper, Rich visual, custom
selection paint, second clipboard path, or scroll-time selection clearing.
`ctrl+shift+m` / `meta+shift+m` resolves the nearest focused transcript-block
owner and copies its complete raw Markdown through the same
`copy_to_clipboard()` funnel. Both themes keep native
`screen-selection-background` / `screen-selection-foreground` ownership.
Coverage: `test_markdown_content_compiler.py`, `test_user_message_block.py`,
`test_selection_scroll_highlight.py`, `test_selection_copy.py`,
`test_selection_copy_e2e.py`.

**Prompt-history recall** is owned by `PromptHistoryNavigator`
(`src/tui/prompt_history.py`). `PromptInput` only emits semantic older/newer
history messages; the app records submitted non-slash prompts, gives slash
suggestions precedence, and restores the preserved draft when history
navigation exits.

**`ThinkingSpinner`** (`src/tui/thinking_spinner.py`) is a `Horizontal` with
two child `Static`s: an accent braille activity glyph (`_BRAILLE_FRAMES`) and
a muted italic text surface that rotates verbs every `interval_seconds` or
carries a retry/compaction override via `set_override_status(text=...)` —
overrides never stop the glyph. It is mounted while the agent runs or while a
slash command whose `SlashCommandSpecDAO.shows_activity` flag is true is
dispatching; slash dispatch only unmounts a spinner it mounted itself.

---

## Chapter 5 — The Agent Loop

The previous chapter walked the prompt through LangGraph as an opaque
"compiled graph that does react reasoning". This chapter opens it up.

### 5.1 LangGraph in 200 Words

LangGraph is LangChain's state-machine library. You declare:

- A **state schema** (`MessagesState` for slo — a `TypedDict` with a
  `messages: list[BaseMessage]` field annotated as additive).
- A set of **nodes** (functions or runnables that take the state and
  return a partial update).
- A set of **edges** (which node runs next given the current state).
- A **compile step** that returns a runnable graph.

You drive the runnable with `astream(...)`. With `stream_mode="updates"`
it yields one chunk per node-completion (the partial state update that
node produced); with `stream_mode="messages"` it yields token-level
`AIMessageChunk`s as the LLM emits them. Slo subscribes to **both** at
once (`stream_mode=["messages", "updates"]`) — see §4.6. The graph keeps
going until an edge routes to `END`.

That's the entire mental model. The runnable handles state merging,
retry, parallelism (if you ever use it), and streaming.

### 5.2 The Slo State Graph

`build_slo_agent` at `src/agents/slo_agent/graph.py:build_slo_agent`
builds and compiles the graph. Two nodes, two edges:

```
   START
     │
     ▼
  ┌──────┐
  │agent │  ← LLM call: produces an AIMessage. If it carries
  └──────┘    tool_calls, route to tools. Otherwise route to END.
     │
     ├─tool_calls──▶  ┌─────┐
     │                │tools│  ← runs the requested tools, emits
     │                └─────┘    one ToolMessage per call.
     │                   │
     │  ◀────────────────┘
     │
     ▼
    END
```

The `agent` node calls the LLM via `ChatAnthropic` or `ChatOpenAI`
(constructed by `LLMFactory.create`) — or, when a pool is configured,
via a `ModelPool` that fronts several of them (see
[Section 6.7](#67-multi-model-pool-and-rate-limit-defense)). It binds
the tool registry so the LLM knows what tools are available. The
response is an `AIMessage`; if
it carries `tool_calls`, the conditional edge routes to `tools`. The
`tools` node executes each call in turn, appends one `ToolMessage` per
call to the state, and routes back to `agent`. The loop ends when the
LLM produces a tool-free `AIMessage`.

### 5.3 The System Prompt Builder

The agent node doesn't just call the LLM. It prepends a system prompt
built at agent-construction time by `SystemPromptBuilder`
(`src/agents/slo_agent/prompts/__init__.py`; every static string constant
— `ROLE_LINE`, `KB_BLOCK_TEMPLATE`, `SKILLS_BLOCK_TEMPLATE`, … — lives in
`prompts/system_prompt.py`).

**Project context discovery.** `SloAgent.__init__` first calls
`ProjectContextDiscovery.invoke(cwd=..., workspace_folders=...)`
(`src/agents/slo_agent/project_context/service.py`). It collects, in this
filename order, `SLO.md` (preferred), `AGENTS.md`, `CLAUDE.md`, and
`docs/RESEARCH.md` when present in the repo lineage. The cwd lineage is
always walked from `cwd` to the filesystem root; files closer to cwd come
first and the deepest copy of each filename wins within that walk. When
`--workspace <file.code-workspace>` is active, Slo first loads the workspace
file via `VscodeWorkspaceLoader.invoke(workspace_file=...)`
(`workspace/service.py`) and then walks from each declared workspace folder
to the root as an additive tier, contributing only new absolute paths after
the cwd-derived entries. The workspace file itself is never treated as an
instruction file. The collected `ContextFileEntryDAO`s go to the builder.
(In this repository the instruction file is `SLO.md`.)

**Assembly order.** `SystemPromptBuilder.invoke()` emits these sections in
order:

1. Role line (`ROLE_LINE`).
2. Available tools — one `- <name>: <snippet>` line per tool that has a
   `TOOL_PROMPT_SNIPPETS` entry (`src/agents/tools/prompt_snippets.py`).
3. Custom tools note.
4. Guidelines block (adapts to whether bash and the native explorers are
   both present).
5. Skills block — the `<available_skills>` XML manifest plus a line naming
   `SKILLS_LOCATION` (path and source) when skills loaded; otherwise
   `SKILLS_BLOCK_TEMPLATE`: `<SKILLS_LOCATION.path>/INDEX.md`, its source, and
   OS-independent recovery steps (`$SLO_SKILLS_DIR` → `$SLO_HOME/skills` →
   `pipx runpip slo show slo` → `<Location>/skills`).
6. Knowledge-base block (`KB_BLOCK_TEMPLATE`) — see below.
7. Optional append block (`append_system_prompt`).
8. Project context — each discovered file wrapped in
   `<project_instructions path=…>`.
9. Current date line.
10. Current working directory line.
11. Optional `Current workspace folders:` block when a workspace file is
    active.

**The knowledge base.** `config.cfg.KB_LOCATION` resolves the KB path from
`SLO_KB_DIR`, else `KB_DIR` (fallback alias), else
`$SLO_HOME/KnowledgeBase/KB`; a value pointing at a file resolves to its
directory. The path may not exist and resolution never creates it. The
prompt block shows the resolved path and its source, the lookup order, and
the entry points (`Welcome.md`, `index.md`, `Index.md`, `Home.md`). When no
KB is found, the agent tells the user, offers to create one (the
`locate-knowledge-base` skill), and continues — a missing KB never blocks.
The installer's managed `~/.slo/shell/environment.sh` sets `SLO_KB_DIR` only
when it is unset.

**Known issue B1 (historical).** Earlier builds passed the raw constructor
`tools=` argument (default `None`) to the builder, so the tools block
rendered as `(none)` even though the graph had every tool bound. The
current `SloAgent.__init__` passes the resolved `list(_build_result.tools)`
from `build_slo_agent()` into `_resolve_system_prompt`. If the tools block
ever renders as `(none)` again, check that wiring first.

The builder is invoked once per `SloAgent.__init__` — the system prompt
is baked into the graph's compiled state. Changing the prompt requires
restarting the agent (Slo's "session = one process" design makes this
acceptable).

### 5.4 Tools

Tools live under `src/agents/tools/`. Each tool is a `StructuredTool`
(LangChain's class for tools with typed arguments) bound to a Pydantic
args schema. The agent's tool bundle is assembled by
`create_extended_tools()` (`src/agents/tools/bundles.py`).

The standard tool set (`create_extended_tools()` — the default bundle):

| Tool | File | What it does |
|---|---|---|
| `read` | `tools/read.py` | Read a UTF-8 text file or image attachment; rejects PDFs/binary files |
| `write` | `tools/write.py` | Write/overwrite a file |
| `edit` | `tools/edit.py` | Exact-string find-and-replace |
| `bash` | `tools/bash.py` | Run a bash command (semaphore-guarded async) |
| `grep` | `tools/grep.py` | Regex search across files |
| `find` | `tools/find.py` | Find files by name/pattern |
| `ls` | `tools/ls.py` | List directory contents |
| `read_pdf` | `tools/read_pdf.py` | Extract text from a PDF |
| `now` | `tools/now.py` | Return the current datetime |
| `show_git_diff` | `tools/show_git_diff.py` | Return safe JSON HEAD-versus-worktree content for one repository-relative UTF-8 text file |

`tools/tool_output.py` is not a tool: it defines `ToolOutputUpdateDAO`, the
typed, display-only partial-output snapshot that streaming-capable tools
(today `bash`) publish — see [Plugins and tool-output
streaming](#plugins-and-tool-output-streaming). Shared private helpers live
beside the tools (`_blocking.py`, `_truncate.py`, `_gitignore.py`,
`_image_content.py`).

Three pi-parity sub-bundles also exist: `create_coding_tools()`
(read/bash/edit/write), `create_read_only_tools()` (read/grep/find/ls), and
`create_all_tools()` (all seven pi tools). Tool batches are planned by
`plan_tool_batch` (`src/agents/slo_agent/tool_execution/service.py`) into
parallel or sequential execution (`ToolExecutionPlanDAO`) and run by
`SequentialToolExecutor` / `ConcurrentToolExecutor` (`executors.py`).

Additional tools available but **not** in the default bundle:

| Tool | When available |
|---|---|
| `spawn_sub_agents` | Orchestrator sessions only — spawns child `slo run` processes |
| `echo` | Debug/test sessions only |

Adding a tool is three steps: write a `StructuredTool` with a Pydantic
args schema, register it in `create_extended_tools`, and add a
`prompt_snippet` to `src/agents/tools/prompt_snippets.py` so the system
prompt mentions it.

### 5.5 Hooks and Stop Conditions

The agent loop runs until the LLM stops asking for tools. But the host
(the session, a test, the user) may want to intervene — abort, steer,
follow up. These are managed by the **hook layer** at
`src/agents/hooks/`.

The relevant hook is `should_stop_after_turn_hook`. It's a callable
invoked after every turn that returns `True` to stop the loop early.
Default behaviour: never stop (let the LLM decide). Tests inject
custom hooks to bound the iteration count.

`SloAgent` also exposes:

- **`abort()`** — sets `self._abort_event`. The next chunk-yield in
  `react_streaming` checks this and emits a final `<aborted>` event.
- **`steer(message)`** — queues a `HumanMessage` to be appended at the
  next turn boundary.
- **`followUp(message)`** — queues a message that runs after the agent
  would stop.

The session forwards `abort`, `steer`, `followUp` to the agent; the
slash router forwards user `/abort` and `/steer <msg>` to the session.
The chain is: keypress → router → session → agent → graph state.

### 5.6 Keeping the Event Loop Responsive — Blocking Tool Offload

The `tools` node runs on the **same asyncio event loop as the Textual
UI**. The file/PDF/image tools (`read`, `write`, `edit`, `grep`, `find`,
`ls`, `read_pdf`) do genuinely blocking work — `read_text`, directory
walks, `fsync`, PDF/image decoding. If that work ran inline, a single
large read or a fan-out batch of read-only tools would freeze the
spinner, stall streaming, and make the whole TUI hang.

These tools keep their `async` public surface, but the blocking leaf work
is pushed off the loop through one shared helper
(`src/agents/tools/_blocking.py`):

```python
async def run_blocking_tool_call(*, func: Callable[..., T], **kwargs: Any) -> T:
    semaphore = _semaphore_for_current_loop()
    async with semaphore:
        return await asyncio.to_thread(func, **kwargs)
```

Two design points:

- **`asyncio.to_thread`** runs the sync body in a worker thread, so the
  event loop keeps servicing the UI and the stream.
- **A bounded semaphore** caps concurrency at `BLOCKING_TOOL_THREAD_LIMIT`
  (4). A read-only tool batch can't spawn an unbounded pile of threads.
  The semaphore is stored **per event loop** in a `WeakKeyDictionary`,
  because an `asyncio.Semaphore` binds to the first loop that awaits it —
  this keeps pytest's per-test loops and the live TUI loop isolated while
  still enforcing one shared cap inside any single loop.

The pattern each tool follows is: keep `async def invoke(...)` as the API,
move the body into a sync `_invoke_sync(...)`, and call it via
`await run_blocking_tool_call(func=cls._invoke_sync, ...)`.

`bash` is split differently. Subprocess ownership (`_spawn`,
`_communicate_with_timeout`, `_terminate_process_group`) stays async on the
caller loop; only the synchronous post-processing leaf —
`BashTool._format_result` (decode, exit-code framing, tail truncation, and
optional full-output spill after the subprocess completes) — crosses the
gateway. `_spill_to_tempfile` stays a plain leaf called from
`_format_result` (no nested offload). That keeps large bash outputs from
stalling Textual.

---

## Chapter 5.7 — User-Defined Skills and Workflows

Slo ships with 100+ vendored skills under `skills/`. Starting with
feature-29, users can add their **own** skills and workflows without
touching the vendored tree.

One of the vendored TUI skills is
`skills/tui/tui-scheduled-workflows/SKILL.md`, which tells an interactive
session how to use `slo schedule ...` to supervise dynamic workflows,
post recurring progress updates back into the live TUI, and clean up the
monitor schedule when the workflow ends.

Another is `skills/tui/tui-scheduled-operations/SKILL.md`, which covers
generic scheduled actions from the TUI such as repeated reminders,
interval-based in-session output, delayed follow-ups, and schedules that
run until the user explicitly stops them.

### The vendored skill library

Skills are vendored convention prompts that the agent reads on demand.

- **Location:** `skills/<group>/<slug>/SKILL.md` — 188 skills across 14 groups:
  `orientation/`, `design-and-analysis/`, `coding/`, `git-ops/`, `cli/`,
  `tui/`, `integration-tests/`, `frontend-vue/`, `presentation/`,
  `user-content/`, `engineering/`, `languages/`, `samples/`, and
  `orchestration/`.
- **Runtime access:** the system prompt carries the `<available_skills>`
  manifest and names the skills location ([§5.3](#53-the-system-prompt-builder));
  when no skills load it falls back to pointing at `skills/INDEX.md`
  (absolute path via `SKILLS_DIR`). The agent reads the matching `SKILL.md`
  with the `read` tool.
- **Index format:** each `INDEX.md` entry has `name`, `description`,
  `when_to_use`, and a relative `Path:`. The YAML frontmatter in each
  `SKILL.md` carries the same fields plus `group` and `kind`.
- **Regeneration:** `make build-skill-index` or `make refresh-skills`
  rewrites `skills/INDEX.md` from the committed `SKILL.md` tree (same
  builder). Neither command imports upstream prompts, rewrites skill bodies,
  or removes workflow definitions, samples, or assets.
  `SLO_CODE_PROMPTS_DIR` is no longer used.
- `SkillRegistry` (`src/agents/skills/registry.py`) parses individual
  `SKILL.md` files but is not wired into the session boot path;
  `SkillsLoader` (below) is.

**Layered skill discovery (feature 87).** The skills prompt directs
non-trivial tasks through `skills/engineering/engineering-routing/SKILL.md`:
shared policy, the affected language root, the component/test-category
recipe, the relevant framework, then explicit project contracts. Python
recipes live in `skills/languages/python/`; the old `skills/coding/` paths
remain as non-invocable forwarders. Go and TypeScript families are bundled
under `skills/languages/`; Vue and canonical workflow paths are stable. There
is no automatic routing classifier and no extra project skill-loading tier:
descriptions carry applicability, because the XML manifest does not expose
arbitrary metadata fields. The reorganization's source inventory and routing
scenarios are regression fixtures in
`tests/agents/skills/fixtures/reorganization/` (its design notes were removed
on 2026-10-21; see git history for `docs/skills-reorganization/`).

### Workflows vs skills — the routing rule

The skills directory holds **two distinct kinds of artifact**:

| Kind | Location pattern | Purpose |
|---|---|---|
| **Individual skill** | `skills/<group>/<slug>/SKILL.md` | Single-concern convention for one task type |
| **Formal workflow** | `skills/orchestration/workflows/<name>.md` | Multi-step pipeline sequencing several skills |

**When the user mentions "workflow" or names one, load it from
`skills/orchestration/workflows/` — never a skill with a similar name.**
Named workflows: Code-Test-Review
(`skills/orchestration/workflows/code-test-review.md`) and Specification
Development (`skills/orchestration/workflows/specification-development.md`).

*Anti-pattern:* "use the code-test-review workflow" → loading
`skills/coding/code-test-loop/SKILL.md`. `code-test-loop` is the coding
cadence that forms Step 1 *inside* Code-Test-Review; loading it instead
silently skips Step 2 (Code Review) and Step 3 (Completion Check).

**"Dynamic workflows"** (or the common misspelling "dyanmic workflows") is an
explicit request to run the named workflow **in the current session**: the
orchestrator decomposes phases and dispatches them with `spawn_sub_agents`,
blocking until the synthesis returns in the same turn. To **detach** it as a
headless orchestrator process, the user must add an explicit qualifier —
"headless", "detached", or "independent" applied to the request, or wording
such as "in the background" / "without blocking". A detach-qualified request
routes to exactly one `launch_workflow` call; a detached orchestrator never
calls `launch_workflow`.

**Scheduled supervision from the TUI.** Load
`skills/tui/tui-scheduled-workflows/SKILL.md` when a dynamic workflow
launched from a TUI session also needs recurring monitoring or progress
posted back to that session (continuous schedules, session-inbox delivery,
stalled-orchestrator recovery, cleanup on completion or abort). Load
`skills/tui/tui-scheduled-operations/SKILL.md` for generic scheduled
behaviour (reminders, periodic checks, "print the time every 5 seconds until
I ask you to stop"): interval, cron and one-shot schedules, targeting the
live TUI session, and stopping on request.

**Orchestrator timeouts for slow test suites.** `spawn_sub_agents` is
**blocking**: while a child runs, the orchestrator's own LangGraph stream
emits nothing, so the parent guard `SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS`
measures wall-clock silence for the child's entire runtime. A busy child
keeps resetting its own `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS` and never
trips it, so the parent guard is the real ceiling on one blocking phase. If a
phase's gates run long (e.g. Go `go test -race ./...`), the orchestrator
aborts a healthy run with `TimeoutError: main agent stream produced no events
for <N>s; treated as hung` and kills the child mid-task. Before launching
against such a project, export both guards (parent strictly greater than
child) in the shell that starts the orchestrator, before it starts — a `bash`
tool export inside a running session cannot change the running
orchestrator's environment (the orchestrator prompt in `spawn_tool.py` says
so explicitly); prefer splitting phases so no single blocking call outlives
the parent guard. Defaults and the exact export lines are in
`RESEARCH.md`; background is in KB `slo/headless-workflow-orchestration.md`
→ "Long-running phases / slow test suites".

**Workflow-turn counting.** Counting and stopping rules live in
`skills/orchestration/workflows/SKILL.md#workflow-turns-and-limits`. One
workflow turn is a complete pass through all required phases, not one agent
dispatch. Track partial passes, phase retries and dispatch limits
separately; disclose a harness budget conflict before launch; never claim
repeated writing attempts were complete writing-and-review cycles. The
default budgets (turns per task, dispatches per turn, failed-task retries)
are prompt rules, not runtime counters — the numbers are in `RESEARCH.md`.
Explicit user instructions override those budgets (higher, lower or
unlimited); record the effective limits and keep consumed counts. Resume and
takeover preserve counts; aborted tasks are never retried. Runtime caps,
retry/abort policy and required review are unchanged, and the runtime
child-concurrency cap (`SLO_SUBAGENT_MAX_CONCURRENCY`) is a separate limit.
Advance on verified phase verdicts and artifacts, not process exit alone.

### Explain a functionality with HTML

Use the bundled [`explain-with-html`](skills/design-and-analysis/explain-with-html/SKILL.md)
skill for a programmer-facing explanation of an existing feature or a proposed
design. For example:

> Use explain-with-html to explain this functionality. Show one concept per
> section, the domain owners and control flow, then the interfaces and code journey.

Before designing the HTML, the skill requires `solution-design`, `coding-rules`,
and `code-design-principles`. It connects the current and intended user journeys
to domain state, whole interfaces, lifecycle and failure behavior, using diagrams
with explicit return paths. Near the end, separate **Domains as code**,
**Interfaces as code**, and **The journey through code** sections show concrete
contracts and ordered caller examples; complete implementation is not required.
Existing source is cited and distinguished from proposed interfaces. Present one
concept per section and trace ownership and control flow through observable
results; the numbered code journeys must match the diagrams.

The output is a self-contained scrolling page with inline diagrams, accessible
navigation and syntax highlighting readable without JavaScript. It composes with
`present-as-single-page` for visual presentation; it does not implement the feature
or claim that proposed behavior has been tested. After editing bundled skills,
run `make build-skill-index` from the application root to refresh discovery.

### Where user content lives

```
~/.slo/user_skills/          ← user-defined skills (one SKILL.md per subdirectory)
~/.slo/user_workflows/       ← user-defined multi-step workflow pipelines
```

Both paths are configurable via environment variables:
- `SLO_USER_SKILLS_DIR` — override `~/.slo/user_skills`
- `SLO_USER_WORKFLOWS_DIR` — override `~/.slo/user_workflows`

### The merge algorithm (`SkillsLoader.load_merged`)

`src/agents/slo_agent/skills_loader.py` owns discovery. At session start,
`SloAgent.__init__` calls `SkillsLoader.load_merged(vendored_skills_dir=..., user_skills_dir=..., user_workflows_dir=...)` which:

1. Loads all vendored `SKILL.md` files (filesystem order, deduped by name).
2. Loads all user skills from `~/.slo/user_skills/` (same pattern).
3. Loads all user workflows from `~/.slo/user_workflows/`.
4. Merges by `name` — **user entries win on collision**, silently replacing
   the vendored entry. No files are modified on disk.

The result is injected into the system prompt's `<available_skills>` block,
so the LLM sees user-defined entries exactly like vendored ones.

### Creating your own skills

Two meta-skills guide the process:

- **`create-user-skill`** (`skills/user-content/create-user-skill/SKILL.md`)
  — step-by-step guide to authoring a `SKILL.md` with correct YAML
  frontmatter and placing it under `~/.slo/user_skills/<slug>/`.
- **`create-user-workflow`** (`skills/user-content/create-user-workflow/SKILL.md`)
  — same for multi-step pipeline workflows under `~/.slo/user_workflows/<name>/`.

Ask the agent: `"Create a user skill for <topic>"` and it will read the
appropriate meta-skill and guide you through the authoring process.

---

## Chapter 6 — Credentials and the Auth Modal

Chapter 4 mentioned that `SloAgent.__init__` calls `LLMFactory.create`
which calls `CredentialResolver.require`. This chapter is the bottom of
that stack.

### 6.1 The Resolver and Its Sources

`CredentialResolver` lives at `src/auth/credential_resolver.py`. Two
public methods:

- **`resolve(*, provider) -> Optional[CredentialDAO]`** — never raises,
  returns `None` when no credential exists.
- **`require(*, provider) -> CredentialDAO`** — wraps `resolve`; raises
  `ValueError` with a provider-specific message when `None`.

The split is deliberate. The TUI's `on_mount` calls `resolve` (it
mustn't crash startup); `LLMFactory.create` calls `require` (a missing
credential is a runtime error that should propagate).

The resolver checks three sources in order:

1. **Environment variable.** `SLO_ANTHROPIC_API_KEY`,
   `SLO_OPENAI_API_KEY`, or `SLO_KIMI_FOR_CODING_API_KEY`. Always wins.
2. **`~/.slo/global/authentication.json`** via `CredentialStore`. The
   row written by the auth modal. Skipped if expired.
3. **`~/.claude/.credentials.json`** — Anthropic-only legacy file.
   Compatible with users who set up before the auth modal shipped.

The resolver is **stateless**. Each call queries each source fresh —
there is no cache. This is intentional: the auth modal writes a new
credential and the next prompt resolves it without restarting the
agent. `LLMFactory.create` (`src/agents/base.py`, the **only** LLM
construction point) calls `require` once per build. `SloTUI.on_mount`
pushes `AuthenticationScreen` (`src/tui/authentication/`) when `resolve`
returns `None` for the active model's provider; users re-open it with
`/auth`.

### 6.2 The Credential Store

`CredentialStore` at `src/auth/credential_store.py` is the **only**
object permitted to read or write the on-disk file. It owns:

- Atomic temp-and-rename writes (write to `<path>.tmp`, `chmod 600`,
  then `Path.replace`).
- `chmod 700` on the parent dir on every write — fixes a hand-edited
  mode.
- Schema validation via `AuthenticationFileDAO`.
- A typed `CredentialStoreCorruptError` for unparseable files so
  callers can render a user-facing message.

The DAOs are Pydantic models. `CredentialDAO` carries the bearer
token, optional refresh token, optional expiry, optional subject (for
the success banner). `AuthenticationFileDAO` is the envelope:
`schema_version: int = 1` plus `providers: dict[ProviderName,
CredentialDAO]`. We chose Pydantic over `TypedDict` because:

- Pydantic gives runtime validation. A corrupt file produces a clear
  error path instead of an `AttributeError` deep in the resolver.
- Field defaults are honoured uniformly.
- `model_dump_json(indent=2)` produces a deterministic, diffable
  on-disk format.

### 6.3 The Auth Modal's State Machine

`AuthenticationScreen` at `src/tui/authentication/auth_screen.py:52`
walks the user through five states:

```
PROVIDER  →  METHOD  →  ( OAUTH  |  API_KEY )  →  SUCCESS
                                                    │
                                                    ▼
                                             dismiss(cred)
```

Each state is a separate widget under
`src/tui/authentication/widgets/`. The screen swaps the body's child
when the previous widget posts its `Chosen` message. The widgets
communicate via custom `Message` subclasses:

- `ProviderSelectWidget.Chosen(provider=...)`
- `MethodSelectWidget.Chosen(method=...)` / `.BackRequested` / `.Cancelled`
- `OAuthStatusWidget.BackRequested` / `.Cancelled`
- `ApiKeyInputWidget.Submitted(api_key=...)` / `.BackRequested` / `.Cancelled`
- `SuccessWidget.Closed`

The screen has one handler per message, each one decision long. The
OAuth-task lifecycle (spawn, cancel-on-back, persist-on-success) is
owned by `_begin_oauth`, `_on_oauth_done`, `_cancel_oauth_if_running`.
Errors land in a class-level lookup table:

```python
_ERROR_MESSAGES: dict[type[BaseException], Callable[[BaseException], str]] = {
    OAuthTimeoutError: lambda e: "Sign-in timed out. Use Back to retry.",
    OAuthStateError:   lambda e: "Sign-in failed: state mismatch. Use Back to retry.",
    OAuthTokenError:   lambda e: f"Sign-in failed: {e}",
}
```

The `_render_oauth_error` method does one dict lookup — no isinstance
chain — and writes the message into the OAuth status widget's error
region.

### 6.4 OAuth — PKCE in 5 Minutes

Both Anthropic and OpenAI use **OAuth 2.0 with PKCE** for their CLI
grants. PKCE (Proof Key for Code Exchange) avoids needing a client
secret on the CLI, which would otherwise leak.

The flow:

1. Generate a random **`code_verifier`** (32 bytes, base64url).
2. Compute **`code_challenge`** = base64url(sha256(verifier)).
3. Generate a random **`state`** (16 bytes, base64url).
4. Bind a **callback server** on `127.0.0.1:0` (OS-assigned port). Read
   back the port. Construct the `redirect_uri` =
   `http://127.0.0.1:<port>/callback`.
5. Build the authorization URL with `client_id`, `redirect_uri`,
   `code_challenge`, `code_challenge_method=S256`, `state`.
6. Open the URL in the user's browser via `webbrowser.open(url)`.
7. The user signs in on the provider's page. The provider redirects to
   the callback URL with `code=<auth-code>&state=<state>`.
8. The callback server receives the redirect, validates `state` matches,
   captures `code`.
9. POST to the token endpoint with `grant_type=authorization_code`,
   `code`, `code_verifier`, `redirect_uri`, `client_id`. The provider
   verifies that SHA256(verifier) == challenge and returns an access
   token + refresh token + expiry.
10. The flow returns a `CredentialDAO`. The modal persists it; the
    success widget shows "Signed in as `<subject>`."

The implementation is at `src/auth/oauth_flow.py:OAuthFlow`. The
callback server is `_CallbackServer` — an aiohttp app bound for one
request, torn down when the `async with` exits. PKCE helpers
(`generate_code_verifier`, `code_challenge_s256`, `generate_state`) live
at `src/auth/pkce.py`.

**Login methods and ownership.** Subscription OAuth declares its interaction
capability through `OAuthLoginMethod` (`BROWSER_AUTHORIZATION` /
`DEVICE_AUTHORIZATION`). `DeviceAuthorizationFlow` owns generic device
polling; `OAuthFlow` owns the browser/manual hand-off. An
`OAuthFlowFactory()` instance is the factory seam: its `__call__` takes the
`provider`, the `login_method`, the browser/device presentation callbacks,
and an optional authorization-response receiver — the modal injects faux
flows through it in tests.

**Browser opening** is guarded by `BrowserHost` (`src/auth/browser_host.py`).
On any host other than macOS/Windows with `DISPLAY`, `WAYLAND_DISPLAY` and
`BROWSER` all unset, neither `OAuthFlow` nor `SloTUI.open_url` calls
`webbrowser` (it would run a console browser on the TUI terminal).
Elsewhere they open the browser off the event loop, and `OAuthFlow` opens it
concurrently with the callback/paste race. Tests inject `browser_host=`
instead of patching the environment. The callback, browser/manual attempt,
and device attempt deadlines each have their own environment variable (names
and defaults in `RESEARCH.md`).

Concrete provider configuration (endpoints, client_id, scopes) lives
in `src/auth/providers/anthropic_provider.py` and
`src/auth/providers/openai_codex_provider.py`. **The `client_id` values
in these files are placeholders with `# TODO: verify` markers** — a
human must confirm them against the canonical Anthropic and OpenAI
Codex CLI source before the OAuth path actually works against the live
providers. Until then the paste-an-API-key path is the working entry.

### 6.5 Adding a New Provider

Suppose you want to add a `MistralOAuthProvider`. Three files:

1. **`src/auth/providers/mistral_provider.py`** — a class extending
   `OAuthProvider` with the four abstract properties
   (`provider_name`, `authorization_endpoint`, `token_endpoint`,
   `client_id`, `scopes`) and a `parse_token_response` method.
2. **`src/auth/providers/__init__.py`** — re-export the new class.
3. **`src/auth/provider_factory.py`** — add a branch in `_concrete_for`
   that returns `MistralOAuthProvider()` for the new `ProviderName`.

You'll also need to add `MISTRAL = "mistral"` to `ProviderName`, and
update `provider_for_model` to recognise `mistral-*` model prefixes,
and update the auth modal's provider-select widget to offer Mistral as
a third option. Each change is a one-file edit.

### 6.6 Kimi For Coding (KFC) Provider

v0.8.0 adds **Kimi For Coding** — a code-optimised model from
[Moonshot AI](https://www.moonshot.cn/) served through an
OpenAI-compatible API at `https://api.kimi.com/coding/v1`. The canonical
model name is `kimi-for-coding`; newer first-class entries include
`kimi-k3` and `kimi-for-coding-highspeed`. The `ProviderName` enum value
is `ProviderName.KIMI_FOR_CODING = "kimi_for_coding"`.

#### Getting credentials

Sign up at [kimi.com](https://kimi.com) to obtain an API key, then
either:

- Set the environment variable before launching Slo:
  ```bash
  export SLO_KIMI_FOR_CODING_API_KEY=<your-key>
  ```
- Or use the TUI `/auth` flow: select **Kimi For Coding** (the third
  radio button in the provider-select step), skip the OAuth step — KFC
  is API-key only — and paste your key into the API Key input. The
  credential is stored as `kimi_for_coding` in
  `~/.slo/global/authentication.json`.

#### LLMFactory dispatch

`LLMFactory` (`src/agents/base.py`) uses the canonical model catalog
(`src/agents/model_catalog/`) to route a model name to the correct
provider builder. Both the `kimi-` prefix and the legacy `moonshot-`
prefix route to the KFC builder, so `moonshot-*` model names continue
to work without any migration:

```
kimi-*      → KFC builder  (ChatOpenAI pointed at kimi.com)
moonshot-*  → KFC builder  (backward-compatible alias)
claude-*    → Anthropic builder
gpt-*       → OpenAI builder
o1-*        → OpenAI builder
o3-*        → OpenAI builder
```

Two special requirements are enforced automatically by the builder:

- **`temperature=1`** — KFC rejects any other value. The builder
  overrides whatever temperature the caller supplies.
- **`User-Agent: KimiCLI/1.5`** — required by the KFC endpoint. Sent
  as a default header on every request.

`LLMFactory._build_kimi_for_coding_chat_openai` builds a `ChatOpenAI` with
`base_url="https://api.kimi.com/coding/v1"`, `max_retries=0` (the pool and
the retry layers own fallback, so errors must surface immediately), and
`supports_explicit_caching=False` (KFC has no prompt caching). Supported
model names come from the canonical model catalog
(`src/agents/model_catalog/seed.py`); older `moonshot-*` aliases still resolve
but are not advertised as preferred names. The credential env var is
`SLO_KIMI_FOR_CODING_API_KEY`.

#### K3 reasoning levels

`kimi-k3` always reasons and supports Slo's canonical reasoning levels
`low`, `high`, and `xhigh`. The builder maps those levels to K3's top-level
provider `reasoning_effort` values `low`, `high`, and `max`, respectively.
`max` is provider vocabulary, not an additional Slo reasoning level.

Other canonical selections use nearest-notch clamping: `off` and `minimal`
resolve to `low`, while `medium` resolves to `high`. Only enabled K3 resolved
reasoning adds the top-level `reasoning_effort` field. The K2 coding pair
(`kimi-for-coding` and `kimi-for-coding-highspeed`) remains off-only and does
not send a reasoning field. The Kimi builder never emits `thinking`, OpenAI
`reasoning`, `use_responses_api`, or `output_version`.

This command selects the canonical `low` level; Slo maps it to K3's native
provider effort internally:

```bash
slo --model kimi-k3 --reasoning low
```

#### ModelPool and credit-exhaustion policy

`LLMFactory.create_pool()` builds a **priority-ordered fallback router**
(`ModelPool` at `src/agents/providers/model_pool.py`). As of v0.9.0 the
pool is wired into the production build path (see
[Section 6.7](#67-multi-model-pool-and-rate-limit-defense)); KFC is the
provider most likely to need it, since credit exhaustion (HTTP 402) is
the failure that motivated a fallback router in the first place. Each
entry is a `ModelPoolEntryDAO` with:

- `model_name` — the model to try first.
- `priority` — lower wins.
- `cooldown_seconds` (default 300 s) — how long to skip the entry
  after a credit-exhaustion error (HTTP 402).
- `rate_limit_cooldown_seconds` (default 60 s) — how long to skip
  after a rate-limit or transient server failure.

Error classification is handled by the shared `ProviderErrorClassifier`
(`src/agents/providers/credit_exhaustion_policy.py`; `CreditExhaustionPolicy`
remains as a backward-compatible alias). For KFC:

- **HTTP 402** → `CREDIT_EXHAUSTED` → entry cooled for `cooldown_seconds`.
- **HTTP 429** → `RATE_LIMITED` → entry cooled for `rate_limit_cooldown_seconds`.
- **HTTP 500/502/503/529** → `TRANSIENT_PROVIDER_FAILURE` → also cooled for
  `rate_limit_cooldown_seconds`.

When an entry is cooled down, the pool's `_select_model()` skips it and
tries the next priority entry. If all entries are cooling, `ModelPool`
raises `AllModelsExhaustedError` (see [§6.7](#67-multi-model-pool-and-rate-limit-defense)).

#### TUI model selector

The model catalog (`src/tui/model_catalog.py`) lists `kimi-for-coding`
under the **Kimi For Coding** group, so it appears as a selectable
option in the TUI's `/model` selector alongside the Anthropic and
OpenAI families.

### 6.7 Multi-Model Pool and Rate-Limit Defense

Through v0.8.0, `ModelPool` lived in the tree but was never constructed
on the production build path — every real session was single-model.
v0.9.0 wires it in and adds a three-layer defense against rate limits,
credit exhaustion, and transient provider failures. With no pool
configured, behaviour is exactly as before; the whole feature is opt-in.

#### Wiring the pool into production

`build_slo_agent(model_pool_dao=...)` now builds a `ModelPool` via
`LLMFactory.create_pool(...)`, forwarding every build knob it would
have passed to a single model — temperature, streaming, max_retries,
max_tokens, model_kwargs, session_id, and reasoning_level. `ModelPool`
is a drop-in `BaseChatModel`: it overrides `_generate`, `_agenerate`,
and `_astream`, so the graph's `agent` node calls it exactly as it would
a `ChatAnthropic` or `ChatOpenAI`. Internally it routes across a
priority-ordered list of members with cooldown-based failover, and
streaming is preserved through pooled members.

**Key types** (`src/agents/providers/model_pool.py`):

- `ModelPoolEntryDAO` — `model_name`, `provider`, `priority`,
  `cooldown_seconds` (credit), `rate_limit_cooldown_seconds` (rate-limit and
  transient failures).
- `ModelPoolDAO` — `entries: List[ModelPoolEntryDAO]` with `min_length=2`.
- `ModelPool` — overrides `_generate` / `_agenerate` / `_astream` and
  `bind_tools`, and exposes the introspection surface `llm` (→ self),
  `active_llm`, `active_provider`, `supports_explicit_caching`,
  `active_model_name`, plus a route-switch audit log
  (`drain_route_switch_log()`).
- `RouteSwitchRecordDAO` — one audit record (`from_model_name`,
  `to_model_name`, `kind`, `error_text`).

**Fallback rules (spec 37).** `_select_model()` picks the lowest-priority
entry that is not cooling. On a *switchable* error (`should_switch(kind)` →
`CREDIT_EXHAUSTED` / `RATE_LIMITED` / `TRANSIENT_PROVIDER_FAILURE`) the failing
entry is cooled (long cooldown for credit, short for rate-limit/transient),
the switch is recorded, and the next available entry replays the **same**
request. `_astream` switches only **before the first streamed chunk**. On
`OTHER` (e.g. a 400) the error re-raises immediately. When every entry is
cooling, `AllModelsExhaustedError` reaches the caller.

**Creation.** `LLMFactory.create_pool(pool_dao=..., <all build knobs>)`
forwards `temperature` / `streaming` / `max_retries` / `max_tokens` /
`model_kwargs` / `session_id` / `reasoning_level` to every member and injects
`adapt_chatgpt_backend_request` as the per-member request adapter. Both a
single-model `LLMBuildResult` and a `ModelPool` satisfy the `LLMBuildProduct`
protocol (`.llm` / `.supports_explicit_caching`); local imports avoid cycles.

**Session integration.** `SloAgentSession._resolve_active_model_name()` uses
`hasattr(llm, "active_model_name")` to detect a pool — no `isinstance` check
and no import of `ModelPool` in the session module. Pool config is parsed by
`config/model_pool_config.py::parse_model_pool_config` and threaded via
`SessionConfigDAO.model_pool_dao`. `_refresh_oauth_credential_if_needed`
warms **every** pool provider.

#### The three layers (composed top-to-bottom)

1. **History-aware preflight (session).** The local token estimate now
   counts the *replayed message history* — assistant text, tool-call
   payloads, and tool outputs — not just the new prompt. A resumed
   session therefore waits *before* it would 429, emitting a
   `Waiting Ns for <model> local rate window` status.
   `PreflightDecisionDAO` owns one history-aware estimate per provider
   attempt. RPM smoothing may wait, but a local TPM hint is advisory only:
   an empty-window oversized request emits `preflight_bypassed` and still
   reaches the provider. Degraded local preflight records no local attempt.
   The decision's exact estimate is reused for any escaped-provider or pool
   failed-lane observation — never re-estimated or read from a later deque
   entry. Per-model limits come from `ModelRateLimitPolicyDAO`
   (`src/agents/slo_agent/rate_limit/dao.py`: `requests_per_minute`,
   `tokens_per_minute`, `automatic_retry_attempts`,
   `local_retry_wait_cap_seconds`), sourced from the canonical model catalog
   via `MODEL_DEFAULTS` in `config/ai_model_config.py`.
   `retry_plan_from_error()` (`rate_limit/service.py`) turns a caught
   rate-limit error into a `RateLimitRetryPlanDAO` (`wait_seconds`,
   `retryable`).
2. **In-call route switch (pool).** On a *switchable* provider error —
   a rate limit (429), credit exhaustion (402/quota), or a transient
   server failure (500/502/503/529) — the pool cools the active member
   and replays the same request through the next available member,
   **before the first streamed chunk**. A mid-stream failure propagates
   rather than corrupting the transcript.
3. **Iteration-scoped retry (agent).** A late 429 is retried at the
   **single ReAct-iteration** boundary — and only when that iteration
   has emitted no visible output yet, so no transcript line is
   duplicated — instead of giving up because an earlier iteration
   already streamed. It emits `Rate limited by <model>; retrying in Ns`.
   `SloAgent.invoke(iteration_retry_policy=...)` replays the unchanged
   `accumulated_messages`. Retryability is decided by
   `SloAgentSession._is_iteration_retryable_error`, which resolves the active
   provider (`_resolve_active_provider` → pool `active_provider`, else
   `provider_for_model`) and consults the shared classifier: only
   `RATE_LIMITED` and `TRANSIENT_PROVIDER_FAILURE` wait and retry — so the
   status-less OpenAI overload message takes a bounded delayed retry
   (`run_retrying`) rather than an immediate same-model LLM recovery
   observation (`run_recovering`). `AllModelsExhaustedError` is retryable
   within the attempt budget. The session injects the policy via
   `_build_iteration_retry_policy` and relays/persists the agent's
   `run_retrying` events; with no injected policy the legacy no-retry
   behaviour is preserved.

**Overflow backstop (spec 46.a.2).** When a provider explicitly rejects an
initial request for confirmed context overflow before any committed visible
output, `_derive_next_attempt_plan` (not `_finalize_failed_attempt`) runs a
forced compaction pass, emits the four compaction lifecycle kinds
(`compaction_started`, `compaction_completed`, `compaction_failed`,
`compaction_retrying`), persists a `run_retrying` audit event anchored to the
failed turn, and returns a one-shot `overflow_retry` attempt plan
(`persist_user_message=False`, `excluded_turn_ids` filtering the failed turn
from immediate replay context, `preflight_compaction_mode="skip"`). If
compaction returns `False` or raises, it returns `None` and the original
overflow error surfaces unchanged. Committed output, a second overflow on
the retry attempt, and an HTTP 413 / `REQUEST_BODY_TOO_LARGE` rejection are
terminal: no replay, pool switch, iteration retry, LLM recovery, or forced
compaction.

**Fail loudly.** When every pool member is cooling, the run surfaces a
terminal `run_failed` that names every cooled member
(`All models in pool are in cooldown: …`). There is never an infinite
loop and never a silent hang.

#### Configuration

A pool is opt-in via the `SLO_MODEL_POOL` environment variable **or** the
`default_model_pool` user preference — a comma-separated,
priority-ordered list of model names. Each name's provider is inferred
automatically from its prefix (the same prefix table that powers
`LLMFactory`). Fewer than two names collapses to the single-model path,
unchanged.

```bash
# Try gpt-5.4 first, fall back to claude-sonnet-4-6, then kimi-for-coding
export SLO_MODEL_POOL="gpt-5.4,claude-sonnet-4-6,kimi-for-coding"
```

#### Truthful routed-model identity

Everything that reports "which model" reports the **routed** member —
the one actually in play after any switch — not the originally
configured name: the title bar, the usage/status line, the rate policy,
the persisted `run_started` / `run_failed` events, and `session.json`.
The configured name remains "what you picked"; the routed name is "what
answered". A `/model X` on a pooled session is an explicit override: it
clears the pool and drops to single-model mode with `X`.

#### Observability

Two new history event kinds are persisted to the session history
(`tree.json` by default, `events.jsonl` in the legacy flat store):

- `route_switched` — an audit record of each pool switch, carrying
  `from`, `to`, and the error `kind` that triggered it.
- `run_retrying` — one record per wait-and-retry decision.

Both are diagnostic-only: they are excluded from model context and never
inflate the next request.

#### Provider error taxonomy

A new `ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE` (500/502/503/529)
joins the existing rate-limit and credit-exhaustion kinds, and a single
`should_switch(kind)` predicate decides switch-vs-propagate. A
malformed or `OTHER` error — for example a 400 bad request — propagates
without switching, because retrying it on another member would not help.

`ProviderErrorClassifier.classify(error, provider)` → `ProviderErrorKind`
(`src/agents/providers/credit_exhaustion_policy.py`) is the **one shared
classifier** for all three failure paths: `ModelPool` route switching,
`RecoveryPolicy`, and the session's iteration retry. Classification is
per provider (Anthropic, OpenAI, Kimi For Coding each have their own
status-code and error-code mapping — the full table is in `RESEARCH.md`).
When no HTTP status settles the kind, a shared message-text fallback maps
`"rate limit"` / `"429"` in the message to `RATE_LIMITED`, preserving the
former provider-agnostic heuristic. Transport disconnects are classified by
`StreamRecoveryService` ([§4.7](#47-provider-progress-watchdog-and-local-tools)).

---

## Chapter 7 — Extending Slo

### 7.1 Adding a New Tool

Suppose you want a `wiki_search` tool that hits an internal wiki API.

**Step 1**: write the tool. `src/agents/tools/wiki_search.py`:

```python
"""Search the internal wiki by query."""
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool


class WikiSearchArgs(BaseModel):
    """Arguments for ``wiki_search``."""
    query: str = Field(description="Free-text search query.")
    limit: int = Field(default=10, description="Max number of results.")


def _wiki_search(query: str, limit: int = 10) -> str:
    """Body — return the search results as plain text."""
    # … your HTTP call here …
    return formatted_results


wiki_search_tool: StructuredTool = StructuredTool.from_function(
    func=_wiki_search,
    name="wiki_search",
    description="Search the internal wiki.",
    args_schema=WikiSearchArgs,
)
```

**Step 2**: register it. `src/agents/tools/bundles.py`:

```python
from src.agents.tools.wiki_search import wiki_search_tool

def create_extended_tools() -> list[BaseTool]:
    return [
        # … existing tools …
        wiki_search_tool,
    ]
```

**Step 3**: add a prompt snippet so the system prompt advertises it.
`src/agents/tools/prompt_snippets.py`:

```python
WIKI_SEARCH_SNIPPET = (
    "Use `wiki_search` to find pages in the internal wiki by free-text "
    "query. Provide `query` (required) and optional `limit`."
)
```

**Step 4**: write tests. `tests/agents/tools/test_wiki_search.py` — at
minimum, a happy path that monkeypatches the HTTP call and asserts the
tool returns the expected string.

**Optional step 5**: add a custom summary to `EventRenderer._SUMMARIZERS`
in `src/tui/event_renderer.py` so the `⎿` continuation reads nicely.
Without it, you'll get the default first-line-truncated-at-120-chars
summary.

### 7.2 Adding a New Slash Command

`src/tui/slash_router.py` is the single point of entry. To add
`/explain <topic>` that prints a paragraph from a static text bank:

**Step 1**: write the handler:

```python
@classmethod
async def _handle_explain(
    cls, *, rest: str, session: SloAgentSession,
) -> SlashCommandResultDAO:
    """Render a stored explanation for the given topic.

    Args:
        rest (str): The topic the user asked about.
        session (SloAgentSession): Active session (unused).

    Returns:
        SlashCommandResultDAO: With ``rendered`` set to the explanation.
    """
    explanation = _EXPLANATIONS.get(rest.strip(), "No entry for that topic.")
    return SlashCommandResultDAO(rendered=explanation)
```

**Step 2**: register it in `dispatch`'s handler dict:

```python
handlers: dict[str, SlashHandler] = {
    # … existing handlers …
    "explain": cls._handle_explain,
}
```

**Step 3**: extend `_help_text` so `/help` lists it.

**Step 4**: write a test:

```python
@pytest.mark.asyncio
async def test_explain_renders_explanation():
    session = _build_session_stub()
    result = await SlashRouter.dispatch(line="/explain pkce", session=session)
    assert "PKCE" in (result.rendered or "")
```

If your slash command needs to mutate the TUI (push a modal, exit, etc.),
add a new flag to `SlashCommandResultDAO` and honour it in
`SloTUI._dispatch_slash_command`. The router stays Textual-free.

### 7.3 Customising the Renderer

Styling now lives in two places, because the transcript has two kinds of
content (see Chapter 4):

1. **Append-only logical lines** (slash output, the `> you typed this`
   echo) carry the app-level semantic classes `tool-line`, `tool-result`,
   `assistant-final`, etc., styled in `src/tui/app.tcss`:

   ```css
   .tool-line   { color: #ff8800; text-style: bold; }   /* warm orange */
   .tool-result { color: #555; text-style: dim; }
   ```

2. **Live streaming widgets** style themselves through `DEFAULT_CSS` on
   the widget class. To restyle a live tool call, edit
   `ToolExecutionBlock.DEFAULT_CSS` (the `.tool-call-headline` /
   `.tool-call-result` rules); to restyle live reasoning vs. answer text,
   edit `AssistantStreamBlock.DEFAULT_CSS` (`.assistant-thinking-body` /
   `.assistant-answer-body`).

The ⏺/⎿ glyphs and the per-tool result summaries are still produced by
the shared formatters in `src/tui/event_renderer.py`
(`format_tool_call_headline`, `format_tool_result_line`, and the
`EventRenderer._SUMMARIZERS` table) — both the live `ToolExecutionBlock`
and the recorded logical line call through them, so a new summarizer added
to that table shows up in both places at once.

---

## Chapter 8 — Testing

### 8.1 The Faux Provider

`src/agents/providers/faux.py` defines `FauxChatModel` — a LangChain
`BaseChatModel` subclass that takes a scripted list of `AIMessage`s and
returns them one at a time. Tests inject this as the LLM so the agent
loop runs without any real provider call:

```python
agent: SloAgent = SloAgent(
    llm=FauxChatModel(responses=[AIMessage(content="hi")]),
)
session: SloAgentSession = SloAgentSession(
    agent=agent, workdir=tmp_path, session_id=str(uuid4()),
)
```

`FauxChatModel` honours both blocking (`invoke`) and streaming
(`astream`) call paths. It's deterministic — same input, same output —
which means TUI tests can assert on the exact transcript content
without flake.

### 8.2 Pilot-Driven TUI Tests

Every TUI test follows the same shape:

```python
@pytest.mark.asyncio
async def test_submitting_a_prompt_renders_final_response() -> None:
    session: SloAgentSession = _build_session(
        responses=[AIMessage(content="hi")],
    )
    app: SloTUI = SloTUI(session=session)

    async with app.run_test() as pilot:
        await pilot.pause()
        app._input.load_text("hello")
        await pilot.press("enter")
        await _await_idle(app=app, pilot=pilot)

        assert ("hi", "assistant-final") in app._adapter.lines
```

`_await_idle` polls until `app._in_flight_task is None`. Without it, the
assertion races the in-flight asyncio task.

The transcript adapter records every logical line — both append-only
writes and the `record_transcript_line` calls the projector makes for
live blocks — via `_TranscriptAdapter.lines: list[tuple[str, str]]`.
Tests assert on this list directly. There is no scraping of mounted
widget internals: the logical-line seam stays stable even though the
visible transcript is now a tree of `AssistantStreamBlock` /
`ToolExecutionBlock` / `Static` widgets.

### 8.3 The Conftest Auto-Fixture

`tests/tui/conftest.py` is the most important fixture in the repo. It's
an autouse fixture scoped to `tests/tui/` that patches
`CredentialResolver.resolve` to return a fake `CredentialDAO`:

```python
@pytest.fixture(autouse=True)
def _suppress_auth_modal(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(*, provider: ProviderName) -> CredentialDAO:
        return CredentialDAO(
            provider=provider,
            auth_type=AuthType.API_KEY,
            access_token="sk-fake-default",
        )
    monkeypatch.setattr("src.tui.app.CredentialResolver.resolve", _fake)
```

Without this, every TUI test would push the auth modal on mount,
intercepting the test's assertions. With it, the modal stays closed and
tests can drive the chat path. The three tests that *specifically*
exercise the missing-credential path re-monkeypatch the resolver to
return `None`.

### 8.4 Coverage Discipline

The repo follows a strict **one test per decision point** policy:

- Every `if`/`elif`/`try`/`except` branch in production code has a test
  that exercises it.
- Test names follow `test_<method>_<expected_outcome>_<when_condition>`.
- Tests are organised by class, one class per method-under-test.

`make test` runs the full suite (currently 1300+ tests). A new feature
that doesn't ship with tests is not done.

### 8.5 Suite Rules

- **Never real keys in the default gate.** Tests use `FauxChatModel`
  (`src/agents/providers/faux.py`) for every LLM call.
- **Default gate:** `pytest -m "not e2e"` (set in `pyproject.toml`
  `addopts`). Run `pytest -m e2e` only when real provider credentials are
  intentionally in scope.
- **Test env:** `make test-env` identifies a readable local
  `environments/tests.env` or the tracked Makefile fallback. Inspect local
  settings first; never source the development environment or assume a
  gitignored test file ships. The fallback supplies synthetic credentials and
  disables automatic windows/Herdr. Root fixtures strip inherited Herdr
  settings and require independently registered temp-owned fake executables
  before transport spawning. `slo-harness` Python 3.11.7 is the approved
  existing interpreter for this feature checkout; do not install an absent alias.
- **Never real terminal windows.** `VisualizerLauncher.launch()` opens a real
  Terminal/iTerm window running `slo visualize --follow` that outlives the
  suite. Any test path that reaches it (a `sub_agent_spawned` event or a
  `launch_workflow` tool result through `SloTUI._render_event`) must patch
  `VisualizerLauncher.launch` or inject `spawn=`. Two suite-wide guards back
  this up: `environments/tests.env` sets `SLO_AUTO_VISUALIZE=0` (covers
  `make test`), and the autouse `_never_spawn_real_terminals` fixture in
  `tests/conftest.py` stubs `VisualizerLauncher._default_spawn` (covers bare
  `pytest`). Regression tests:
  `tests/tui/test_visualizer_launcher.py::TestSuiteNeverSpawnsRealTerminals`.
  During **manual smoke** runs, close every visualizer terminal you open
  (quit `slo visualize` and its window) — detached windows otherwise
  accumulate on the operator's machine.
- **Layout:** `tests/agents/slo_agent/` (agent loop, session, rate limits,
  usage), `tests/tui/` (app, replay, slash commands, status bar, tool
  blocks; `tests/tui/workflows/` for the detached-workflow receive path),
  and `tests/integration/` (cross-component composed flows, e.g. the
  feature 94 list → progress → child-abort flow).
- `asyncio_mode = "auto"` is set in `pyproject.toml`, so async tests run
  without an explicit `@pytest.mark.asyncio`.

---

## Chapter 9 — Sub-Agent Orchestration

Slo can spawn child `slo` processes — **sub-agents** — to run tasks in
parallel or in sequence. This chapter covers the headless run mode that
child processes use, the orchestrator domain that manages them, and how
their progress surfaces in the TUI.

### 9.1 Headless Run Mode — `slo run`

The orchestrator communicates with child agents via a **headless one-shot
mode** added to the CLI:

```bash
slo run -p "write a test for the login module" --json
```

`HeadlessRunner` (`src/cli/headless.py`) drives one `SloAgentSession` to
completion and streams every `AgentStreamEventDAO` as a newline-terminated
JSON line to stdout (JSONL). The terminal event determines the POSIX exit
code:

| Terminal event | Exit code | Meaning |
|---|---|---|
| `run_completed` | 0 | Success |
| `run_aborted` | 2 | Aborted by user/orchestrator |
| `run_failed` | 1 | Unhandled error |

History is **disabled by default** for direct headless runs. Use
`--enable-history` to opt in. Pool-spawned sub-agents are the deliberate
exception: the pool always passes its assigned `--session-id` and
`--enable-history`, so each child's heartbeat, captures, history record, and
future `--resume` reference use one stable identity.

### 9.2 Orchestrator Domain (`src/agents/slo_agent/orchestrator/`)

Five modules form the orchestrator domain:

| Module | What it does |
|---|---|
| `dao.py` | Shared DAOs: `SubAgentTaskDAO`, `SubAgentStatusDAO`, `SubAgentResultDAO`, `OrchestratorResultDAO`, `SubAgentMode`, `SubAgentStatus` |
| `registry.py` | `ProcessRegistry` — in-memory lifecycle store; tracks status snapshots for active sub-agents |
| `process.py` | `SubAgentProcess` — spawns one `slo run --json` child, reads JSONL stdout (16 MB limit), enforces `PER_TASK_OUTPUT_CAP`, implements `cancel()` |
| `pool.py` | `SubAgentPool` — concurrency-capped dispatcher; parallel/chain/single modes; `Semaphore(MAX_CONCURRENCY)`; relays lifecycle events to TUI |
| `spawn_tool.py` | `SpawnSubAgentsTool` — LangChain `BaseTool` factory; `build(pool=)` returns a bound tool; `ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM` injected for orchestrator sessions |

**Three dispatch modes** (`SubAgentMode`):

- **`parallel`** — all tasks fan out concurrently, bounded by `MAX_CONCURRENCY`.
- **`chain`** — sequential; `{previous}` in each prompt is substituted with the prior task's answer; a failure stops the chain.
- **`single`** — exactly one task (a degenerate parallel batch of size 1).

### 9.3 The `spawn_sub_agents` Tool

`spawn_sub_agents` is NOT in the default tool bundle. It is attached
only to **orchestrator sessions** — sessions where `SessionConfigDAO.extra_tools`
includes it. The `SloTUI._attach_pool_to_session()` helper builds and
attaches the pool when a session starts; the `SloAgentSession` merges
`extra_tools` into its agent bundle.

**Critical dispatch policy** (enforced via system prompt addendum):
> Call `spawn_sub_agents` **only** when the user explicitly requests
> parallel or concurrent execution. Do NOT call it autonomously to
> decompose complex tasks.

```python
# Tool schema (SpawnSubAgentsSchemaDAO)
class SpawnSubAgentsSchemaDAO(BaseModel):
    mode: SubAgentMode          # 'parallel' | 'chain' | 'single'
    tasks_json: str             # JSON array of {task_id, prompt, cwd?, model?}
```

The tool returns a JSON-serialised `OrchestratorResultDAO` that the LLM
uses to synthesise a combined final answer.

### 9.4 Child Process Lifecycle

```
SubAgentPool.dispatch(tasks)
  └─ for each task: SubAgentProcess.run()
        ├─ asyncio.create_subprocess_exec("slo", "run", "--json", ...)
        ├─ reads JSONL lines from child stdout
        ├─ relays each AgentStreamEventDAO to the parent's event bus
        │   (tagged with sub_agent_id / task_id)
        ├─ enforces PER_TASK_OUTPUT_CAP (aborts excessively verbose children)
        ├─ 7200-second inactivity timeout (no output for 2 h → terminate + fail, env SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS, alias SLO_SUBAGENT_INACTIVITY_TIMEOUT)
        └─ terminal result: SubAgentResultDAO{status, answer, exit_code}
```

Cross-process credential safety is handled by a file lock
(`credential_refresher.py`): `fcntl.flock` advisory locking on
`~/.slo/.credentials.lock` prevents simultaneous token refreshes from
multiple child processes corrupting the credential store.

### 9.5 TUI Rendering for Sub-Agents

The TUI shows concurrent sub-agent progress through three components:

**`AgentPaneManager`** (`src/tui/agent_pane_manager.py`) — owns one
scroll region + `TranscriptProjector` per active agent. Pane `[0]` is
always the orchestrator; panes `[1..N]` are sub-agents registered
dynamically on `sub_agent_spawned` events. Switching panes is instant
because hidden panes stay mounted.

**`AgentTabStrip`** (`src/tui/widgets/agent_tab_strip.py`) — horizontal
strip of tab buttons, one per registered pane. Shows a status icon
(⏳ running, ✓ completed, ✗ failed) and the task id. Invisible until the
first sub-agent registers. Clicking a tab sends `AgentTabStrip.TabSelected`
to `SloTUI` which delegates the switch to `AgentPaneManager`.

**`SubAgentFleetPanel`** (`src/tui/widgets/sub_agent_fleet_panel.py`) —
the "Ongoing workflow tasks" session list between `PromptInput` and the
usage bar (feature 94). Each `SubAgentFleetRow` reads
`[status] session-id: task`, where the task is the literal 150-code-point
`TaskPreview` label (never the latest activity). Owned attached and detached
groups list orchestrator first, then children. Rows stay after a prompt ends;
an empty list takes no height. Tab focuses the list; Up/Down select; Enter or
click opens `SessionProgressScreen`, a live, position-preserving progress modal
refreshed every 5 s by the single `WorkflowProgressCoordinator`. From there
"Abort child…" asks for confirmation and requests a child-only abort; the UI
shows "Abort requested" until terminal evidence arrives. Escape/Minimize never
cancels execution. `/workflows tui dismiss [<id>]` hides finished groups.

**`TranscriptProjector` sub-agent routing** — the projector's
`is_sub_agent_event` gate routes events with a `sub_agent_id` to the
correct pane via `AgentPaneManager`, while orchestrator events go to
pane `[0]`. *Current ownership (feature 94):* `SloTUI` owns child/sub-agent
events, which never mount a foreground transcript block; child lifecycle
events only request one coalesced session-list refresh, and child progress is
read through the session list and progress modal (§9.7).

### 9.6 Session Resilience Fixes

The sub-agent work also delivered several resilience fixes:

- **`/steer` queued-steer rendering** — steers render as a pending
  message until consumed, then as a regular user message via the new
  `steering_applied` stream event kind.
- **Hard `/abort` escalation** — abort is cooperative (sets the abort
  event); if the run is still alive after a grace period, Slo cancels
  the asyncio task directly. A `(aborted)` line always appears.
- **Dangling `tool_use` healing** — if a session history contains a
  `tool_call` with no matching `tool_result` (e.g. agent was killed
  mid-tool), the history projector synthesises a placeholder
  `ToolMessage` so the next resume doesn't 400 the provider.
- **Child inactivity timeout** — if a child process produces no output
  for 7200 seconds (2 hours, configurable via `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS`; alias `SLO_SUBAGENT_INACTIVITY_TIMEOUT`), `SubAgentProcess` terminates it and marks it failed.

### 9.7 Detached Workflows, the Session List, and Child Abort

Beyond the five core modules in §9.2, the orchestrator domain now also holds:
`fleet_store.py` (`FleetStore` — durable `ProcessRegistry` projection to
`fleet.json`), `status_store.py` (`OrchestratorStatusStore` — owner of the
self-reported `orchestrator.json`), `layout.py` (`OrchestrationLayout` —
canonical workflow/fleet/capture paths), `process_probe.py` (`ProcessProbe` —
the one conservative PID-liveness semantic), `spawn_env.py` (shared
allowlisted headless-child environment and capture opener), `task_preview.py`
(`TaskPreview` — the one task label), `child_abort.py` (`ChildAbortStore` and
the runner's `ChildAbortController`), `launch_tool.py` (`launch_workflow` —
detached orchestrator spawn), `relaunch.py` (`WorkflowRelauncher` — resume a
dead detached workflow), and `workflow_registry.py` (`WorkflowHandleStore` and
workflow commands). `SubAgentPool` dispatches explicit `dispatch_id` batches
and exposes `abort_child`.

**Headless heartbeat and failure envelope (specs 70/71).** `HeadlessRunner`
emits a stderr-only `headless_status` heartbeat from a watchdog thread
(interval `SLO_HEADLESS_HEARTBEAT_SECONDS`). A recognised same-session
heartbeat is advisory liveness telemetry (`healthy`, `degraded`, `silent`);
it never cancels a child or shortens the sole stdout-inactivity authority,
`SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS`. `SubAgentResultDAO` carries
additive, redacted `failure_code`, `partial_output_committed`, `attempts`,
and `safe_message` fields. Cancellation stays SIGTERM → grace → SIGKILL →
reap, with one cached terminal result.

**Workflow visualizer auto-launch (platform path; Herdr extension below).** When a TUI session is promoted to
orchestrator mode and the first sub-agent spawns,
`SloTUI._maybe_launch_visualizer` opens a separate terminal window running
`slo visualize --session <parent_session_id> --follow` via
`VisualizerLauncher` (`src/tui/visualizer_launcher.py`). It fires once per run
(guarded by `_visualizer_launched_for_run`, reset in
`_cleanup_sub_agent_state`). The launch is best effort: macOS drives
Terminal.app/iTerm through `osascript`, Linux probes common terminal
emulators, and any other platform (or a failed spawn) writes the manual
`slo visualize` command into the transcript. Only a non-secret `SLO_*`
allowlist is forwarded into the new window. Disable with
`SLO_AUTO_VISUALIZE=0`; choose the emulator with
`SLO_VISUALIZER_TERMINAL_APP`. The visualizer TUI
(`src/tui/headless_workflow_visualizer.py`, fed by the bounded
`WorkflowVisualizerLoader` and the one capture reader `JsonlTail`) has a
workflow-summary bar, a status-coloured sub-agent list, Markdown transcript
rendering through the shared `WorkflowTranscriptRenderer`, and
keyboard-resizable panes (`ctrl+←/→` list width, `ctrl+↑/↓` diagnostics
height).

**Detached workflow supervision.** Workflow handles live at
`<owner_session>/workflows/wf-*.json` (TUI-owned). Each orchestrator session
also carries `orchestrator.json` (`HeadlessRunner` self-report), `fleet.json`
(pool projection), `abort_request.json` (the TUI's durable whole-workflow
abort channel) and `child-control.v1/` (child-only abort requests and
receipts); each child has a `status.json` terminal result (full layout in
[History and persistence](#history-and-persistence)).
`/workflows resume <workflow-id>` relaunches a `stalled` or `failed` handle
against its original orchestrator session with `--resume`; a dedicated
flock-protected store transition returns it to `launching`, and fresh
self-reported evidence advances it to `running`.

**The receive path (`src/tui/workflows/`, spec 57.a.5)** is a strict
delegation chain for headless-orchestrator lifecycle data:

```
SloTUI ── raw kind/payload ──> DetachedWorkflowAppService ── typed HandleAdvanceOutcomeDAO ──> SloTUI
                                     │                                                    │
                                     │ durable handle advance + live-state cache           ▼
                                     │                                          DetachedWorkflowRenderer
                                     │                                          (apply_effects only)
                                     └──────── typed DetachedWorkflowUiEffectDAO ─────────┘
```

- `dao.py` owns the only parsing/validation seams
  (`parse_workflow_lifecycle_message`, `parse_launch_workflow_result`) and the
  typed effect vocabulary (`launch_visualizer`, `reset_launch_guard`). No
  Textual, no filesystem.
- `DetachedWorkflowAppService` (`service.py`) owns `WorkflowHandleStore`
  reconcile/update, the legal durable transitions, and the
  `workflow_id → state` cache behind the resume/exit hint. Terminal advances
  emit **reset-only** effects — never a launch effect.
- `DetachedWorkflowRenderer` (`renderer.py`) owns typed-effect
  deduplication and shared attached/detached outcome notices via
  `DetachedWorkflowNoticeSink`. `DetachedVisualizerSchedule` registers with
  the app; it returns no launch result. The renderer no longer parses raw
  launch results or calls a window launcher. Typed `reset_launch_guard`
  resets request deduplication, not the session-owned Herdr one-shot attempt
  ledger.
- **Strict app boundary:** `SloTUI` passes the raw inbox kind/payload (or the
  raw `launch_workflow` tool-result text) to the service exactly once, then
  only executes the typed effects returned. The app never parses workflow
  payloads or branches on terminal fields itself.

**Session list, progress modal and child abort (feature 94).** Spec family:
`specifications/94-slo-tui-redesign/tui/`; runtime notes: KB
`slo/codebase-index.md` "Feature 94 — TUI session controls".

```
SloTUI ── one WorkflowProgressCoordinator (single flight) ──> DetachedWorkflowAppService
   ▲                                                         │ load_session_snapshot (owner-scoped,
   │ _WorkflowProgressSink (apply_sessions / apply_progress) │  attached batch first, then detached)
   │                                                         │ load_session_progress (bounded loader)
   ├── SubAgentFleetPanel ("Ongoing workflow tasks", below PromptInput, above UsageStatusBar)
   ├── SessionProgressScreen (ProgressLog, Minimize, Abort child…)
   └── AbortConfirmationScreen ──> service.begin_child_abort ──> attached: session.abort_child → pool
                                                                detached: ChildAbortStore → runner ChildAbortController → pool
```

- `PromptInput` paints only top and bottom accent rules (`app.tcss`);
  editing, queue anchor, history recall, Enter handling and its min/max
  height are unchanged.
- Rows (`SubAgentFleetRow` in `FleetSessionList`) read
  `[status] session-id: task`, with the task from `TaskPreview` (truncated
  with `…`, rendered literally). Tab/Shift+Tab focus the list; Up/Down select
  without wrapping; Enter or click opens the exact session. There is no
  workflow Ctrl+W binding.
- `SessionProgressScreen` (+ `ProgressLog`) loads immediately and refreshes
  on the coordinator's timer. It preserves the reader's position (the tail
  follows only from the bottom; End resumes). Escape/Minimize keeps the
  viewport for reopen and never cancels execution. The modal and
  `slo visualize` share `WorkflowTranscriptRenderer`.
- "Abort child…" needs explicit confirmation in `AbortConfirmationScreen`
  (safe default) and reports "Abort requested" until terminal evidence
  arrives; `ChildAbortSubmission` tracks the request and posts a
  not-confirmed notice after a timeout. It never resubmits, never signals a
  PID from the TUI, and never touches siblings, the orchestrator or
  `abort_request.json` (an older runner would abort the whole workflow).
- `/workflows tui dismiss [<id>]` hides finished groups in memory only.

`ChildAbortStore` owns bounded no-follow reads, immutable request IDs and a
per-run request capacity under a run-scoped `admission.lock`.
`HeadlessRunner` starts `ChildAbortController` only for an attached pool with
an explicit `--notify-session` owner, and closes it before the final fleet
drain. Requests and receipts are private audit state: never deleted,
backfilled or migrated. Exact intervals, caps and timeouts are in
`RESEARCH.md`.

**Feature 94 — optional Herdr runtime (not live-certified).**

`HerdrEnvironmentGate` captures inherited pane configuration; construction is inert.
Session activation selects the null path outside/disabled, or assembles one reporter,
shared transport and viewer. Enabled configuration/activation failure is unavailable,
not permission to open a fallback OS window. `SLO_HERDR_DISABLED=1` takes effect at
restart; metadata defaults to compact, with explicit detail opt-in.

| Owner | Actual responsibility |
|---|---|
| `sessions/service.py` | Committed lifecycle/usage authority, private immutable capture and generation, publication, activation/close and retained drain; existing snapshot remains sole token accounting source |
| `sessions/dao.py` | Operation/attention tokens and provenance carriers |
| `sessions/identity.py`, `sessions/token_format.py` | Extracted identity validator closure and shared half-up formatter; CLI/footer compatibility delegates retained |
| `orchestrator/bootstrap.py` | Before/after standard attachment provenance; matching names alone cannot establish reproducibility |
| `herdr/dao.py` | Frozen typed public snapshot/private capture, restore, admission, close and viewer contracts |
| `herdr/service.py` | Environment/null path, safe projection, shared CLI lock/process/deadline/reap mechanics and retained task join |
| `herdr/reporter.py` | Sole private-save scheduler, capture/generation matching, report revisions, ordered commands, remote binding versus acknowledgements |
| `herdr/sequence_store.py` | Shared file lease primitive; distinct durable pane sequence and restore lock scopes |
| `herdr/restore.py` | Secure bounded immutable revision records using unchanged `AtomicFileWriter`; no latest pointer, overwrite, GC or history ownership |
| `herdr/visualizer.py` | Session-owned per-parent one-shot attempt ledger, split result parsing and lock-held live admission |
| `cli/app.py`, `cli/typer_dispatch.py` | Thin `--herdr-restore` parse surface; canonical literal UUID/conflict checks and private load before runtime construction, without ambient policy merge |
| `cli/headless.py` | Adopted headless integration lifetime/final drain without changing original result/stdout; no native restore advertisement |
| `tui/app.py` | Captured session/timer/inbox ownership, irreversible replacement and retained shutdown; `_register_prompt_task` is the final synchronous cutoff for local, queued and machine prompts |
| `tui/app.py::_schedule_visualizer_launch` | One captured-parent task registry, identity-safe done callbacks, awaited cancellation and suppression of late notices |
| `tui/visualizer_launcher.py::launch_async` | One destination decision; platform thread joined before cancellation escapes; Herdr delegates to session, never fallback after failure |
| `tui/workflows/service.py`, `renderer.py` | One raw-result parser/service → typed effects → schedule callback; one shared typed outcome renderer; duplicate renderer parser/old launch callable removed |
| `orchestrator/context_reader.py` | Single `OrchestratorContextReader.load` parser, shared by eligibility and `tui/workflow_visualizer_loader.py`; duplicate loader parser removed, no reverse TUI import |
| `scheduling/runtime/subprocess_runner.py` | Copies inherited environment excluding exactly case-insensitive `HERDR_` prefix; child/detached/relaunch allowlist ownership unchanged |

Public reports contain fixed vocabulary and numeric telemetry only, not arbitrary
model/provider/session labels, conversation, credentials, errors or private paths.
Private capture preserves configured ordered pool policy and effective reasoning,
not transient routed fallback. Reporter publishes reference argv only after durable
save. Same configuration can reuse a save with newer display; a different capture
cannot adopt it merely because session IDs match. Under the acquired transport lock,
each command's owner admits synchronously before tracked spawn.

Native restore uses plain installed `slo --resume UUID --herdr-restore r1-<hex>`
on PATH with unchanged SLO_HOME/default history. It restores exact saved supported
configuration and current history, not a checkpoint or automatic prompt replay.
Current capability/trust admission still applies. Ordinary name/slug resume is not
tightened by Herdr's canonical UUID rule. Private records remain after release;
quota refuses without eviction. See KB `slo/install-guide.md` → "Optional Herdr integration" for limits and rollback.

Replacement prepares a candidate before irreversible old close/adoption; captured
old-ID inbox leases cannot silently move to a successor. Uncertain release suppresses
successor integration; undrained local resources retain one retired session and keep
final teardown pending if drain cannot complete. Refused inbox delivery remains
claimed without ack/replay: investigate before explicit resubmission. Pre-cutoff
registered work retains its existing policy, but no queued successor starts.

Attached and detached viewer requests converge on the same registry/typed outcomes.
Herdr retains one split/run attempt per parent/adapter lifetime even if uncertain;
manual recovery replaces automatic focus/query/retry/close. Platform work admitted
before cutoff may still spawn while its owned thread is joined. `submitted` is not
paint/liveness evidence. Herdr 0.9.2+ remains a target, **UNPROVEN live**; T6 acceptance,
independent review and all-green static gates are separate from T1–T5 author readiness.

---

## Appendix A — File Map

> This map is a narrative reading aid and predates the package split of
> several modules. The maintained tree is in
> [Maintainer Reference → Repository layout](#repository-layout); where the
> two disagree, that tree wins.

### Source code (`slo/src/`)

```
agents/
├── base.py                     # LLMFactory; provider prefix tables
├── hooks/                       # Stop-after-turn hooks
├── slo_agent/
│   ├── agent.py                # SloAgent: lazy LLM build, dual-mode react_streaming
│   ├── assistant_chunk_normalizer.py  # AIMessageChunk → AgentStreamEventDAO (per-turn)
│   ├── turn_stream_accumulator.py     # completed-node truth for one turn
│   ├── graph_stream_parser.py  # version-safe LangGraph dual-stream item decoder
│   ├── stream_event_dao.py     # AgentStreamEventDAO — the stream-event contract
│   ├── message_text.py         # assistant text / reasoning-summary normalizers
│   ├── dao.py                  # SloAgentConfigDAO, SessionConfigDAO, SubmitResultDAO
│   ├── graph.py                # build_slo_agent(model_pool_dao=...) — compiled graph; builds ModelPool when a pool is configured
│   ├── history/                # persistent session history (store, projectors)
│   │   ├── dao.py              # HistoryEventKind, SessionHistoryEventDAO
│   │   ├── filesystem_store.py # FilesystemSessionHistoryStore — JSONL writer
│   │   ├── projector.py        # SessionHistoryProjector → list[BaseMessage]; dangling-tool healing
│   │   └── transcript.py       # ReplayEntryProjector + TranscriptEntryDAO
│   ├── orchestrator/           # Sub-agent orchestration domain
│   │   ├── dao.py              # SubAgentMode/Status/TaskDAO/StatusDAO/ResultDAO/OrchestratorResultDAO
│   │   ├── registry.py         # ProcessRegistry — in-memory lifecycle store
│   │   ├── process.py          # SubAgentProcess — spawns 'slo run --json' child; 16MB stdout limit
│   │   ├── pool.py             # SubAgentPool — parallel/chain/single dispatch; concurrency semaphore
│   │   └── spawn_tool.py       # SpawnSubAgentsTool + SpawnSubAgentsSchemaDAO + ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM
│   ├── prompts/                # SystemPromptBuilder
│   ├── rate_limit_policy.py    # ModelRateLimitPolicyDAO, retry_plan_from_error; history-aware preflight + iteration-scoped retry
│   ├── session.py              # SloAgentSession: in-flight guard, history, fan-out, sub-agent pool relay
│   ├── session_dao.py          # SessionConfigDAO (extra_tools, append_system_prompt), SubmitResultDAO
│   ├── session_usage_dao.py    # TokenUsageTotalsDAO, SessionUsageSnapshotDAO
│   └── skills_loader.py        # SkillsLoader: load() + load_merged() — vendored + user + workflow merge
├── providers/
│   ├── faux.py                 # FauxChatModel (test seam)
│   ├── model_pool.py           # ModelPool — priority-ordered fallback BaseChatModel; in-call route switch on switchable errors
│   └── credit_exhaustion_policy.py  # ProviderErrorKind taxonomy + should_switch(kind) predicate
└── tools/                      # All built-in tools + registry + snippets
    └── _blocking.py            # run_blocking_tool_call — to_thread + per-loop semaphore

auth/                            # 02.b authentication feature
├── credential_dao.py           # CredentialDAO, AuthenticationFileDAO
├── credential_resolver.py      # The single seam for credential lookup
├── credential_store.py         # Atomic JSON file owner
├── oauth_errors.py             # OAuthTimeoutError, OAuthStateError, OAuthTokenError
├── oauth_flow.py               # OAuthFlow + _CallbackServer
├── oauth_provider.py           # OAuthProvider ABC + FauxOAuthProvider
├── pkce.py                     # PKCE + state helpers
├── provider_factory.py         # OAuthFlowFactory
├── provider_for_model.py       # model_name → ProviderName
└── providers/                   # AnthropicOAuthProvider, OpenAICodexOAuthProvider

cli/
├── app.py                      # Typer app — bare slo = TUI; slo run = headless; update
├── __init__.py                 # Console-script entry
├── __main__.py                 # python -m src.cli entry
├── headless.py                 # HeadlessRunner — drives one session to completion, JSONL to stdout
├── typer_dispatch.py           # TyperDispatch: TUI launch, headless run, session resume
├── update.py                   # ~/.slo self-updater
└── version.py                  # __version__

tui/
├── app.py                      # SloTUI — the App; PromptInput; mount host; _TranscriptAdapter; sub-agent pane switching
├── app.tcss                    # Layout (#transcript-scroll/#status-region) + palette
├── agent_pane_manager.py       # AgentPaneManager — per-agent scroll regions and projectors (pane[0]=orchestrator)
├── authentication/             # The auth modal
│   ├── auth_screen.py          # AuthenticationScreen orchestrator
│   ├── auth_screen.tcss        # Modal styling
│   ├── auth_state.py           # ScreenState enum
│   └── widgets/                # ProviderSelect, MethodSelect, ApiKeyInput, OAuthStatus, Success
├── prompt_history.py           # PromptHistoryNavigator — Up/Down in-process prompt recall
├── slash_command_registry.py   # SlashCommandRegistry + SlashCommandSpecDAO
├── slash_router.py             # SlashRouter — dispatches /commands
├── slash_suggestion_engine.py  # SlashSuggestionEngine — prefix-match autocomplete
├── transcript_projector.py     # live AgentStreamEventDAO + replay TranscriptEntryDAO → widgets; sub-agent routing
├── widgets/
│   ├── agent_tab_strip.py         # AgentTabStrip — horizontal tab strip for pane switching
│   ├── assistant_stream_block.py  # one assistant turn: reasoning + answer regions; optional title_prefix
│   ├── slash_suggestion_menu.py   # SlashSuggestionMenu — autocomplete dropdown
│   ├── sub_agent_fleet_panel.py   # SubAgentFleetPanel + FleetSessionList — "Ongoing workflow tasks" session list
│   ├── sub_agent_fleet_row.py     # SubAgentFleetRow — one literal `[status] session-id: task` row
│   ├── tool_execution_block.py    # one live tool call: ⏺ headline + ⎿ result
│   ├── usage_status_bar.py        # UsageStatusBar — token/rate display above footer
│   └── user_message_block.py      # one user turn: raw source + compiled visible Content
├── event_renderer.py           # ⏺/⎿ formatters + tool summarizers (shared by live + recorded)
├── model_catalog.py            # supported_models_by_provider()
└── thinking_spinner.py         # Rotating-verb ✦ spinner (fixed in #status-region)
```

### Tests (`slo/tests/`)

Mirrors `src/` one-to-one. Notable conftests and test modules:

- `tests/tui/conftest.py` — autouse fixture that suppresses the auth modal on TUI tests.
- `tests/agents/slo_agent/orchestrator/` — `test_dao`, `test_registry`, `test_process`, `test_pool`, `test_spawn_tool`.
- `tests/tui/test_agent_pane_manager.py` — pane register/switch/hide.
- `tests/tui/test_agent_tab_strip.py` — tab add/status/select.
- `tests/tui/test_sub_agent_fleet_panel.py` — fleet row lifecycle.
- `tests/tui/test_subagent_event_routing.py` — end-to-end sub-agent event routing through TUI.
- `tests/tui/test_pane_scroll_follow.py` — scroll-follow behaviour per pane.
- `tests/agents/slo_agent/skills/test_committed_skills.py` — validates all SKILL.md files have required frontmatter.
- `tests/agents/slo_agent/test_skills_loader.py` — load + load_merged unit tests.

### Specifications (`specifications/`)

Engineering and product specs by phase. The 02.b authentication feature
is documented in `02-slo-tui-cli/02.b-*.md` (parent + 7 substeps).

A particularly useful companion document is
`specifications/slo-object-hierarchy-and-message-types.md`, which gives a
narrative walkthrough of Slo's message stack: `BaseMessage` objects,
LangGraph's dual `messages` / `updates` streams, `AgentStreamEventDAO`,
canonical `SessionHistoryEventDAO` persistence, and replay-time
`TranscriptEntryDAO` projection. Read it when you need to understand how a
single prompt moves from the model, through the TUI, onto disk, and back
into replay.

### Config (`slo/config/`)

- `cfg.py` — environment-variable resolver. Exports `cfg(key)` for runtime lookups. Key constants: `SKILLS_DIR`, `USER_SKILLS_DIR` (`~/.slo/user_skills`, override via `SLO_USER_SKILLS_DIR`), `USER_WORKFLOWS_DIR` (`~/.slo/user_workflows`, override via `SLO_USER_WORKFLOWS_DIR`).
- `ai_model_config.py` — `MODEL_DEFAULTS` compatibility projection (per-model temperature, streaming, max_tokens) derived from the canonical model catalog.
- `logger.py` — JSON-structured logging.

### Environments (`slo/environments/`)

- `tests.env` — optional local test env (used by `make test` when readable; otherwise the tracked Makefile fallback applies).
- `.env.template` — the canonical list of every variable.

---

## Appendix B — Glossary

| Term | Meaning |
|---|---|
| **DAO** | Pydantic model used as a typed data carrier. Never `TypedDict` or `@dataclass`. |
| **`SloAgent`** | The stateful ReAct loop. One per process. |
| **`SloAgentSession`** | Wraps one `SloAgent`. Enforces one-prompt-at-a-time and fans events out to subscribers. |
| **ReAct** | Reason-and-act — the agent loop pattern: think → call a tool → observe → think again. |
| **`StateGraph`** | LangGraph's state-machine builder. Compiles to a runnable. |
| **Dual-mode stream** | `graph.astream(stream_mode=["messages","updates"])` — token-level deltas (`messages`) plus completed node truth (`updates`), reconciled per turn. |
| **`AgentStreamEventDAO`** | The normalized stream-event contract (13 `kind`s). Replaces `ProgressEventDAO` on the interactive path. |
| **`AssistantChunkNormalizer`** | Per-turn; turns raw `AIMessageChunk`s into ordered `*_start`/`*_delta`/`*_end` events. |
| **`TurnStreamAccumulator`** | Per-turn; holds completed-node truth (final text, tool messages) for the stop-hook and final answer. |
| **`TranscriptProjector`** | Stateful event→widget machine. Mounts live stream events *and* replay entries: one `UserMessageBlock` per user turn, one `AssistantStreamBlock` per iteration, one `ToolExecutionBlock` per tool call. |
| **`UserMessageBlock`** | A mounted widget for one user turn — exact raw source plus compiler-visible Content, rendered once at construction. |
| **`AssistantStreamThinkingBlock`** | A mounted widget for one thinking segment, keyed by normalized `block_id`; sealed by its repair end or a terminal sweep. |
| **`AssistantStreamBlock`** | A mounted answer-only widget for one assistant iteration. Updates only itself; its raw answer owner recompiles the terminal visible body update. |
| **`ToolExecutionBlock`** | A mounted widget for one live tool call — ⏺ headline + ⎿ result. |
| **`TranscriptEntryDAO`** | The replay-time counterpart to `AgentStreamEventDAO` — one completed entry (`user`/`assistant`/`tool`) reconstructed from history. |
| **`ReplayEntryProjector`** | Folds canonical history events into ordered `TranscriptEntryDAO`s for replay (renamed from the old history `TranscriptProjector`; also still renders `transcript.md`). |
| **`EventRenderer`** | Now a holder of the shared ⏺/⎿ formatters + `_SUMMARIZERS` table used by live blocks and recorded lines. |
| **`run_blocking_tool_call`** | Offloads a blocking tool body to a worker thread behind a per-loop `Semaphore(4)`, keeping the TUI responsive. |
| **`_TranscriptAdapter`** | Logical-line seam: records every `(content, classes)` pair for tests/copy/replay; mounts `Static`s for append-only lines. |
| **TCSS** | Textual CSS. Same idioms as web CSS; TUI-specific properties. |
| **Pilot** | Textual's headless test driver. `async with app.run_test() as pilot:` gives you `pilot.click`, `pilot.press`, `pilot.pause`. |
| **ModalScreen** | A Textual `Screen` that overlays the underlying screen and grabs focus. Returns a value via `dismiss(value)`. |
| **PKCE** | Proof Key for Code Exchange. OAuth 2.0 extension that lets CLIs run an OAuth flow without a client secret. |
| **`CredentialDAO`** | One persisted credential row. Provider, auth_type, access_token, optional refresh_token, optional expiry, optional subject. |
| **`CredentialResolver`** | The stateless lookup for credentials. Env → store → legacy. |
| **`CredentialStore`** | The only object permitted to read or write `~/.slo/global/authentication.json`. |
| **Faux LLM** | `FauxChatModel` — a scripted-response LangChain model used in tests. |
| **Workdir** | The directory the agent operates in. Tool calls (read, write, bash, grep) resolve paths relative to this. |
| **Slash command** | A line starting with `/`. Dispatched by `SlashRouter`. |
| **`SlashCommandResultDAO`** | The router's return shape. Flags the TUI honours: `rendered`, `should_clear`, `should_exit`, `open_auth_modal`. |
| **`SystemPromptBuilder`** | Assembles the agent's system prompt at construction time. |
| **Hook** | A callable injected into the agent loop (e.g. `should_stop_after_turn_hook`). |
| **`HeadlessRunner`** | Drives one `SloAgentSession` to completion without a TUI; streams JSONL to stdout; used by `slo run --json`. |
| **`SubAgentPool`** | Concurrency-capped orchestrator dispatcher. Manages parallel/chain/single batches of child `slo run` processes. |
| **`SubAgentProcess`** | Wraps one `slo run --json` child process; reads JSONL events from stdout (16 MB limit); enforces inactivity timeout. |
| **`SubAgentMode`** | Dispatch strategy: `parallel` \| `chain` \| `single`. |
| **`OrchestratorResultDAO`** | Aggregated result returned to the orchestrator LLM after a batch completes; JSON-serialised as the tool return value. |
| **`AgentPaneManager`** | Owns per-agent scroll regions and `TranscriptProjector` instances. Pane 0 = orchestrator; pane 1..N = sub-agents. |
| **`AgentTabStrip`** | Horizontal strip of tab buttons for switching panes; shows status icon per sub-agent. |
| **`SubAgentFleetPanel`** | "Ongoing workflow tasks" session list below `PromptInput`; one row per owned orchestrator/child session; Enter/click opens the progress modal. |
| **`SkillsLoader`** | Scans skill directories for `SKILL.md` files; `load_merged()` merges vendored + user + workflow skills with user-wins-on-collision. |
| **`USER_SKILLS_DIR`** | Default `~/.slo/user_skills`; user-defined skills placed here automatically override same-named vendored skills. |
| **`USER_WORKFLOWS_DIR`** | Default `~/.slo/user_workflows`; multi-step pipeline workflows scanned alongside user skills. |
| **`steering_applied`** | New `AgentStreamEventDAO` kind emitted when a queued `/steer` message is consumed by the agent loop. |
| **`ModelPool`** | A drop-in `BaseChatModel` (overrides `_generate`/`_agenerate`/`_astream`) that routes across a priority-ordered list of models with cooldown-based failover; wired into the production build path in v0.9.0. |
| **`ProviderErrorKind`** | The taxonomy that classifies a provider error — rate limit (429), credit exhaustion (402/quota), `TRANSIENT_PROVIDER_FAILURE` (500/502/503/529), or `OTHER`. `should_switch(kind)` decides switch-vs-propagate. |
| **`SLO_MODEL_POOL`** | Environment variable (or the `default_model_pool` user preference) holding a comma-separated, priority-ordered list of model names. Two or more names enable the pool; fewer collapses to single-model. |
| **`route_switched`** | Diagnostic-only history event recording each pool switch (`from`/`to`/`kind`). Persisted to the session history; excluded from model context. |
| **`run_retrying`** | Diagnostic-only history event recording each wait-and-retry decision. Persisted to the session history; excluded from model context. |

---

## Appendix C — Further Reading

**Textual**

- The official Textual tutorial: <https://textual.textualize.io/tutorial/>
- The Textual reference: <https://textual.textualize.io/reference/>
- Rich's Markdown rendering: <https://rich.readthedocs.io/en/stable/markdown.html>

**LangGraph & LangChain**

- LangGraph guide: <https://langchain-ai.github.io/langgraph/>
- The ReAct paper, *Yao et al. 2022*: <https://arxiv.org/abs/2210.03629>

**OAuth 2.0 + PKCE**

- RFC 7636 (PKCE): <https://datatracker.ietf.org/doc/html/rfc7636>
- The `claude` CLI's source — for the canonical Anthropic OAuth client_id.
- The OpenAI Codex CLI's source — for the canonical OpenAI Codex
  OAuth endpoints and client_id.

**Pydantic**

- Pydantic v2 migration guide:
  <https://docs.pydantic.dev/latest/migration/>
- Field validators and computed fields:
  <https://docs.pydantic.dev/latest/concepts/validators/>

---

## License

Slo is licensed under the GNU General Public License v2.0 only.
See [`LICENSE`](LICENSE) for the full license text and [`COPYRIGHT`](COPYRIGHT)
for the project-specific notice, attribution, and contact details.

> *You now know enough to navigate every file in this codebase. When the
> code surprises you, return to Chapter 4 — the prompt's lifecycle is
> the spine that connects everything else. Happy reading.*

---

## Chapter 7 — Sub-Agent Orchestration

Slo can spawn real child agent processes to work on sub-tasks in parallel, in sequence, or one at a time. The orchestrator is the system that makes this work — five files in `src/agents/slo_agent/orchestrator/` plus the child runner in `src/cli/headless.py`.

### 7.1 The Five Files

| File | Single-sentence job |
|---|---|
| `dao.py` | Shared vocabulary — every DAO and type alias used across the other four files |
| `registry.py` | In-memory lifecycle scoreboard keyed by child `session_id` |
| `process.py` | Wrapper around one OS subprocess: spawn, pump JSONL stdout, relay tagged events, cancel |
| `pool.py` | Fleet manager: concurrency semaphore, dispatch modes, lifecycle event emission, result aggregation |
| `spawn_tool.py` | LangChain `@tool` adapter — the LLM-facing API that bridges tool calls to the pool |

### 7.2 Boot: Every TUI Session Becomes Orchestrator-Capable

Before any user message is typed, `SloTUI.__init__` calls:

```python
self._attach_pool_to_session(session=self._session)  # src/tui/app.py
```

`_attach_pool_to_session` (a `@staticmethod`) does three things:

```python
# 1. Create the fleet manager for this session
pool = SubAgentPool(
    orchestrator_session_id=session.session_id,
    default_model=session.active_model_name,
    relay=session.event_relay,        # all child events funnel here
)

# 2. Build the LangChain tool closed over this specific pool
spawn_tool = SpawnSubAgentsTool.build(pool=pool)

# 3. Attach both to the session before the first prompt
session.attach_sub_agent_pool(pool=pool, spawn_tool=spawn_tool)
```

`attach_sub_agent_pool` (`sessions/service.py`) merges `spawn_tool` into `SessionConfigDAO.extra_tools` and appends `ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM` to `SessionConfigDAO.append_system_prompt`. The addendum instructs the LLM: *call `spawn_sub_agents` **only** when the user explicitly requests parallel or concurrent execution; never auto-decompose.*

**The grandchildren invariant:** `HeadlessRunner`-created sessions (the child processes) never pass through `_attach_pool_to_session`. There is no code, no guard, and no check preventing grandchildren — the structural absence of the call *is* the mechanism.

### 7.3 The LLM Calls `spawn_sub_agents`

When the user says something with explicit parallel intent, the LLM emits a tool call:

```json
{
  "name": "spawn_sub_agents",
  "args": {
    "mode": "parallel",
    "tasks_json": "[{\"task_id\": \"t1\", \"prompt\": \"Read dao.py and summarise it.\"},
                    {\"task_id\": \"t2\", \"prompt\": \"Read pool.py and summarise it.\"},
                    {\"task_id\": \"t3\", \"prompt\": \"Read registry.py and summarise it.\"}]"
  }
}
```

The `SpawnSubAgentsSchemaDAO` Pydantic model is set as an explicit `args_schema` on the `@tool`. This validates both fields before the function body runs and guards against a LangChain bug where string-encoded args cause a `TypeError` inside `StructuredTool._arun` when no schema is present.

The function body (`spawn_tool.py`) parses `tasks_json`, rejects oversized batches (> `MAX_PARALLEL_TASKS = 8`), validates each entry into a `SubAgentTaskDAO`, then delegates:

```python
result: OrchestratorResultDAO = await _pool.dispatch(mode=mode, tasks=tasks)
return result.model_dump_json()   # returned to the LLM as the tool result string
```

### 7.4 `SubAgentPool.dispatch()` — Three Modes

**Parallel** — all tasks fire concurrently via `asyncio.gather`:

```python
results = list(await asyncio.gather(*[self._run_one(task=t) for t in tasks]))
```

A shared `asyncio.Semaphore(MAX_CONCURRENCY)` (default 6, env `SLO_SUBAGENT_MAX_CONCURRENCY`) is the ceiling. Tasks beyond the cap queue until a slot opens.

**Chain** — `_run_chain` runs tasks one at a time. Each step's prompt may contain `{previous}`, substituted with the prior step's final `answer` before the child is spawned. A failed step stops the chain; remaining tasks are skipped entirely.

**Single** — a degenerate parallel batch of size 1. Same `asyncio.gather` code path.

### 7.5 `_run_one()` — One Task's Lifecycle

Every task (regardless of mode) flows through `_run_one` → `_run_reserved`. The pool first admits the whole batch: `_admit` calls `registry.begin_dispatch(dispatch_id)` once and reserves every child session. Then each task runs this lifecycle:

```
1. reservation.claim(session_id)                         # session resolved at admission
2. execution_id = registry.register(dispatch_id, task_id, session_id, task)
                                                         # status → pending; fresh incarnation
3. process = SubAgentProcess(..., execution_id=execution_id)
   _install_incarnation(process)                         # _active_by_session_id[session_id] = process,
                                                         # abort event + completion future per (session_id, execution_id)
4. relay ← sub_agent_spawned (dispatch metadata, TaskPreview label)
5. _run_with_slot: race the semaphore against a targeted child abort
     sealed pool / abort won  → process.finish_without_spawn(...)   # never spawns
     otherwise                → process.run()   # wrapper calls registry.mark_running(session_id, execution_id, ...)
   both end in SubAgentProcess._publish_terminal → registry.commit_terminal → winner,
   then the child status.json is written from that winner
6. relay ← sub_agent_completed / sub_agent_failed / sub_agent_aborted (from the winner)
7. finally: del _active_by_session_id[session_id]; settle the completion future once;
   reservation.release(session_id)
8. return the registry winner (SubAgentResultDAO)
```

The pool itself writes no terminal state. The winner returned by `commit_terminal` is the only terminal truth it emits.

### 7.6 `SubAgentProcess` — The Child OS Process

`SubAgentProcess` (`orchestrator/process.py`) manages exactly one `slo run --json` child process.

**Command line (`_build_argv`):**

```python
[
    sys.executable,        # same interpreter and venv as the parent
    "-I",                  # isolated mode (spec 82.a)
    "-m", "src.cli",
    "run", "--json",
    "-p", self._task.prompt,
    # + optional: ["--model", model]  ["--cwd", cwd]
]
```

Using `sys.executable` rather than a bare `slo` ensures the child always runs under the same virtualenv in both dev and installed layouts.

**Stdout pump (`_pump_stdout`):**

```python
while True:
    raw = await asyncio.wait_for(
        stream.readline(),
        timeout=CHILD_INACTIVITY_TIMEOUT_SECONDS,   # 7200 s default (env SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS; alias SLO_SUBAGENT_INACTIVITY_TIMEOUT)
    )
    if not raw:   # EOF = child exited
        return
    await self._handle_line(raw=raw)
```

The `_STDOUT_STREAM_LIMIT = 16 * 1024 * 1024` constant is passed as `limit=` to `asyncio.create_subprocess_exec`. This raises asyncio's default 64 KB per-line buffer to 16 MB, preventing `ValueError: Separator is found, but chunk is longer than limit` on large `run_completed` JSON lines. The inactivity watchdog (default 7200 s, configurable via `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS`; alias `SLO_SUBAGENT_INACTIVITY_TIMEOUT`) treats a hung `readline()` as a failure rather than blocking the parent forever.

**Per-line handler (`_handle_line`):**

1. Parse bytes → `AgentStreamEventDAO`. Non-JSON child diagnostic lines are silently ignored.
2. If terminal: capture `event.content` as the final answer.
3. If `forwarded_bytes >= PER_TASK_OUTPUT_CAP` (512 KB) and not terminal: drop the event. The relay stays bounded; terminal events are always forwarded regardless of the cap.
4. If `text_delta`: call `registry.update_last_text(session_id=..., execution_id=..., text=event.delta)` (live registry preview; the TUI session list shows the task label, not this text).
5. Tag: `event.model_copy(update={"sub_agent_id": session_id, "task_id": task_id})`.
6. `await self._relay(tagged)` → pool relay → `session._dispatch_event` → TUI subscribers and history.

**Cancellation (`cancel`):** SIGTERM → `asyncio.wait_for(proc.wait(), timeout=5s)` → SIGKILL on timeout. Called by `pool.cancel_all()` when the orchestrator session aborts. `cancel_all()` uses `asyncio.gather(..., return_exceptions=True)` so one child's cancellation failure never blocks the others.

### 7.7 `HeadlessRunner` — What Runs Inside Each Child

`src/cli/headless.py` is invoked as `python -m src.cli run --json -p <prompt>` in a fresh OS process.

```python
async def invoke(self, *, prompt: str) -> int:
    session = SloAgentSession.build(config=self._config)
    # No _attach_pool_to_session here → children cannot spawn grandchildren
    session.subscribe(handler=self._emit)
    await session.invoke(text=prompt)
    return self._exit_code_for_terminal_kind(kind=self._terminal_kind)

async def _emit(self, event: AgentStreamEventDAO) -> None:
    if event.is_terminal:
        self._terminal_kind = event.kind
    sys.stdout.write(event.model_dump_json() + "\n")
    sys.stdout.flush()   # flush immediately so parent readline() sees it
```

Exit codes: `run_completed → 0`, `run_aborted → 2`, everything else → `1`. History is disabled by default for child runs (`enable_history=False`); the orchestrator links children by `session_id`, not by replaying their histories.

### 7.8 `ProcessRegistry` — The Live Scoreboard

`ProcessRegistry` (`orchestrator/registry.py`) is the in-memory write authority over `dict[session_id → SubAgentStatusDAO]`, one per pool. A bound `FleetStore` mirrors its transitions to durable fleet and execution evidence (`fleet.json`, `execution.v1.json`, `execution-index.v1.json`).

**Write API** (called by the pool, the process wrapper and `HeadlessRunner`'s straggler sweep only):

| Method | Called when | Transition |
|---|---|---|
| `begin_dispatch(dispatch_id)` | Pool admits one batch (feature 94) | new explicit dispatch generation |
| `register(dispatch_id, task_id, session_id, task)` | Before `sub_agent_spawned` emit | → `pending`; returns the new `execution_id` |
| `mark_running(session_id, execution_id, ...)` | By the wrapper right after the child subprocess is created | → `running` |
| `update_last_text(session_id, execution_id, text)` | Each `text_delta` from the child | updates `last_text` |
| `commit_terminal(result, terminal_reason, terminated_by)` | From `SubAgentProcess._publish_terminal` (natural run, confirmed reap, `finish_without_spawn` pending abort) and from `mark_terminal` | first terminal wins; later candidates get the winner |
| `mark_terminal(session_id, execution_id, status, answer, ...)` | `HeadlessRunner`'s terminal straggler sweep, for a child no wrapper will publish | builds a complete result and delegates to `commit_terminal`; unknown or stale incarnations no-op; writes no child `status.json` |

Every write is keyed by `(session_id, execution_id)`, so a stale incarnation can never overwrite a restarted child. Both terminal routes share `commit_terminal`'s first-wins arbitration, so the sweep and a wrapper can never install two different winners.

**Read API** (TUI session list via `attached_snapshot()`, tests):
- `snapshot()` → `list[SubAgentStatusDAO]` in insertion order.
- `get(session_id=)` → one entry or `None`.
- `count` / `running_count` properties.

### 7.9 Results Flow Back to the LLM

After all child processes exit, `_aggregate` builds an `OrchestratorResultDAO`:

```json
{
  "mode": "parallel",
  "all_completed": true,
  "failed_task_ids": [],
  "results": [
    {"task_id": "t1", "status": "completed", "answer": "dao.py defines ...", "exit_code": 0},
    {"task_id": "t2", "status": "completed", "answer": "pool.py manages ...", "exit_code": 0},
    {"task_id": "t3", "status": "completed", "answer": "registry.py tracks ...", "exit_code": 0}
  ]
}
```

This is serialised via `model_dump_json()` and returned as the `spawn_sub_agents` tool result string. The parent LLM reads it and writes its synthesised final answer in the next ReAct iteration.

### 7.10 The Full Data-Flow

```
User: "analyse in parallel"
         │
         ▼
  SloAgent (parent) ── LangGraph ReAct loop
         │   emits tool call: spawn_sub_agents(mode="parallel", tasks_json="[...]")
         ▼
  SpawnSubAgentsTool  ── validate JSON → [SubAgentTaskDAO, ...]
         │
         ▼
  SubAgentPool.dispatch()
         │
    ┌────┼────┐  asyncio.gather (parallel)
    ▼    ▼    ▼
  _run_one _run_one _run_one
         │
    async with semaphore (MAX_CONCURRENCY=6)
         │
         ▼
  SubAgentProcess.run()
         │  asyncio.create_subprocess_exec
         │  [python, -I, -m, src.cli, run, --json, -p, <prompt>]
         ▼
  Child OS process
         │  HeadlessRunner.invoke()
         │  → SloAgentSession (no pool → no grandchildren)
         │  → writes JSONL to stdout line-by-line, flushing each line
         ▼
  SubAgentProcess._pump_stdout()
         │  parse → tag (sub_agent_id, task_id) → relay
         │  update ProcessRegistry on each text_delta
         ▼
  pool relay → session._dispatch_event
         ├──▶ TUI (lifecycle events request one session-list refresh)
         └──▶ History (JSONL event log)

  ── all children exit ──
  OrchestratorResultDAO (aggregated answers)
         └──▶ returned as tool result string
                → parent LLM synthesises final answer
```

### 7.11 Key Design Decisions

| Decision | Rationale |
|---|---|
| Children run `slo run --json` (OS process, not a library import) | Process isolation: a crashed child cannot corrupt the parent's event loop or memory |
| Headless children never get `_attach_pool_to_session` | Structural grandchildren prevention — the path is never taken; no explicit guard needed |
| `ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM` is the only gate | The tool is always in the bundle; the LLM-layer constraint is what prevents autonomous use |
| `PER_TASK_OUTPUT_CAP = 512 KB` | Prevents a verbose child from flooding the relay; terminal events always forwarded regardless |
| `CHILD_INACTIVITY_TIMEOUT_SECONDS = 7200 s` (env `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS`, alias `SLO_SUBAGENT_INACTIVITY_TIMEOUT`) | A hung `readline()` surfaces as a clean `failed` result; the 2-hour default accommodates large-context LLM calls with slow TTFT and long test gates |
| `_STDOUT_STREAM_LIMIT = 16 MB` | Prevents `ValueError` on large `run_completed` JSON lines; asyncio's default is 64 KB |
| `args_schema=SpawnSubAgentsSchemaDAO` | Fixes LangChain bug where string-encoded args cause `TypeError` inside `StructuredTool._arun` |
| `asyncio.gather(..., return_exceptions=True)` in `cancel_all` | One child's cancel failure never blocks the others |

---

## Maintainer Reference

This part is the maintained reference for anyone — human or AI — changing
the codebase. It absorbs the former `AGENTS.md`. Narrative explanations
live in the chapters above; exact values (timeouts, env-var defaults, caps,
status-code tables, budgets, on-disk file lists, how-tos) live in the
repository's root `RESEARCH.md`.

### Everyday commands

Run these from the application root (`slo/`) with the `slo` virtualenv
active ([§1.3](#13-the-developer-path--pyenv--poetry)):

| Command | What it does |
|---|---|
| `make test` | Reviewed local `tests.env` or tracked safe fallback; full `pytest -m "not e2e"` |
| `make test-env` | Reports `tests.env` or `fallback`; does not create a file |
| `make smoke` | Smoke-only `tests/test_smoke.py` |
| `make lint` | `poetry run mypy src/ tests/` |
| `make format` | `poetry run black src/ tests/` (line length 110) |
| `make build-skill-index` | Regenerate `skills/INDEX.md` from the committed `SKILL.md` files |
| `make refresh-skills` | Same builder as `make build-skill-index` |
| `make install` | `install.sh` → pipx install of the code, then finalise the managed shell environment file under `~/.slo/shell/` |

### Repository layout

The maintained tree. (Appendix A is an older, narrative file map; where the
two disagree, this tree wins.)

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
│   │   │   ├── credit_exhaustion_policy.py  # ProviderErrorClassifier (alias CreditExhaustionPolicy)
│   │   │   ├── model_pool.py                # ModelPool — priority-ordered BaseChatModel router
│   │   │   └── faux.py                      # FauxChatModel — queue-based deterministic mock
│   │   ├── slo_agent/
│   │   │   ├── agent.py               # SloAgent — multi-turn invoke loop
│   │   │   ├── watchdog_timer.py      # WatchDogTimer — provider deadlines + local-tool suspension
│   │   │   ├── runtime.py             # SloRuntimeContext — session-owned plugin/introspection seam
│   │   │   ├── turn_stream_accumulator.py
│   │   │   ├── assistant_chunk_normalizer.py
│   │   │   ├── graph_stream_parser.py
│   │   │   ├── message_text.py
│   │   │   ├── dao.py                 # SloAgentConfigDAO and related
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
│   │   │   │   └── service.py         # ProjectContextDiscovery — SLO.md / AGENTS.md / CLAUDE.md / docs/RESEARCH.md
│   │   │   ├── skills/
│   │   │   │   ├── dao.py             # SkillEntryDAO
│   │   │   │   └── service.py         # SkillsLoader
│   │   │   ├── prompts/
│   │   │   │   ├── __init__.py        # SystemPromptBuilder — assembles runtime system prompt
│   │   │   │   └── system_prompt.py   # All static string constants (ROLE_LINE, KB_BLOCK_TEMPLATE, …)
│   │   │   ├── history/
│   │   │   │   ├── atomic_io.py       # AtomicFileWriter — shared temp+replace durable-state writer
│   │   │   │   ├── dao.py             # HistoryEventKind, SessionHistoryEventDAO, metadata incl. session_name/session_name_key
│   │   │   │   ├── filesystem_store.py # FilesystemSessionHistoryStore — flat JSONL store + resume-by-name resolution
│   │   │   │   ├── tree_store.py      # TreeBasedFileSystemSessionHistoryStore — default store
│   │   │   │   ├── store_protocol.py  # SessionHistoryStoreProtocol
│   │   │   │   ├── token_estimator.py # TokenUsageEstimator
│   │   │   │   ├── projector.py       # SessionHistoryProjector → list[BaseMessage]
│   │   │   │   └── transcript.py      # TranscriptEntryDAO, ReplayEntryProjector
│   │   │   ├── orchestrator/
│   │   │   │   ├── dao.py              # Sub-agent DAOs and centralized terminal projections
│   │   │   │   ├── fleet_store.py      # FleetStore — durable ProcessRegistry projection to fleet.json
│   │   │   │   ├── status_store.py     # OrchestratorStatusStore — self-reported orchestrator.json owner
│   │   │   │   ├── layout.py           # OrchestrationLayout — canonical workflow/fleet/capture paths
│   │   │   │   ├── process_probe.py    # ProcessProbe — conservative shared PID liveness semantic
│   │   │   │   ├── spawn_env.py        # Shared allowlisted headless-child env and capture opener
│   │   │   │   ├── process.py          # SubAgentProcess — child spawn, stream relay, captures
│   │   │   │   ├── pool.py             # SubAgentPool — bounded dispatch, explicit dispatch_id batches, abort_child
│   │   │   │   ├── task_preview.py     # TaskPreview — the one task label (feature 94)
│   │   │   │   ├── child_abort.py      # ChildAbortStore (versioned request/receipt files) + runner ChildAbortController
│   │   │   │   ├── launch_tool.py      # launch_workflow — detached orchestrator spawn
│   │   │   │   ├── relaunch.py         # WorkflowRelauncher — resume a dead detached workflow
│   │   │   │   └── workflow_registry.py # WorkflowHandleStore and workflow commands
│   │   │   ├── tool_execution/
│   │   │   │   ├── service.py         # plan_tool_batch — parallel vs sequential planning
│   │   │   │   ├── dao.py             # ToolExecutionPlanDAO
│   │   │   │   └── executors.py       # SequentialToolExecutor, ConcurrentToolExecutor
│   │   │   ├── plugins/               # Feature 75: typed plugin contract, trust/loader/registry/dispatcher, identity + managed installer
│   │   │   └── compaction/            # Compacter, CompactionChecker, CompactionResult, ContextWindowSnapshotService (context_window.py)
│   │   ├── model_catalog/             # canonical model catalog — identity, defaults, reasoning, aliases, discovery
│   │   │   ├── dao.py                 # ModelCatalogEntryDAO, ModelRuntimeProfileDAO, ModelReasoningProfileDAO, …
│   │   │   ├── seed.py                # committed first-class entries, family templates, aliases
│   │   │   ├── discovery.py           # ProviderModelDiscoveryService, ModelCatalogOverrideService
│   │   │   ├── service.py             # ModelCatalogService.load() — merged snapshot + projections
│   │   │   ├── store.py               # cache and override file persistence
│   │   │   └── prompt_clause.py       # append_kimi_for_coding_clause exact-match helper
│   │   ├── skills/
│   │   │   └── registry.py            # SkillRegistry — parses skills/<name>/SKILL.md (not wired into boot)
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
│   │   ├── browser_host.py            # BrowserHost — graphical-session guard for browser opening
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
│   │   ├── theme.py                   # Theme.variables — the seven Pi-derived semantic tokens
│   │   ├── prompt_history.py          # PromptHistoryNavigator — in-process Up/Down prompt recall
│   │   ├── transcript_projector.py    # TranscriptProjector — events → widgets
│   │   ├── event_renderer.py          # tool-call line formatting helpers
│   │   ├── slash_router.py            # SlashRouter — dispatches /commands
│   │   ├── slash_command_registry.py  # SlashCommandRegistry + SlashCommandSpecDAO
│   │   ├── slash_suggestion_engine.py # SlashSuggestionEngine — prefix-match autocomplete
│   │   ├── thinking_spinner.py        # ThinkingSpinner widget
│   │   ├── headless_workflow_visualizer.py # `slo visualize` TUI — resizable panes, summary bar, markdown transcript
│   │   ├── workflow_visualizer_loader.py   # WorkflowVisualizerLoader — bounded parent/child capture + progress reads
│   │   ├── jsonl_tail.py              # JsonlTail — the one bounded capture JSONL reader
│   │   ├── visualizer_launcher.py     # VisualizerLauncher — opens `slo visualize` in a new OS terminal window
│   │   ├── slodiff/                   # Clean-room extractable diff model + Textual widget
│   │   ├── git_diff_content_service.py # Safe HEAD-versus-worktree content loader
│   │   ├── git_diff_screen.py         # Focused /diff screen and controls
│   │   ├── workflows/                 # Detached-workflow receive path (spec 57.a.5) + session observation (feature 94)
│   │   │   ├── dao.py                 # Parsed lifecycle/launch DTOs, effects, session key/row/snapshot/progress/viewport DAOs
│   │   │   ├── service.py             # DetachedWorkflowAppService — handles, typed effects, owner-scoped list/progress gateway, child-abort begin
│   │   │   ├── renderer.py            # DetachedWorkflowRenderer — launch guard, notices (no Textual)
│   │   │   ├── progress_coordinator.py # WorkflowProgressCoordinator — the one single-flight observation timer
│   │   │   ├── session_progress_screen.py (+ .tcss) # SessionProgressScreen + ProgressLog — position-preserving progress modal
│   │   │   ├── abort_confirmation_screen.py (+ .tcss) # AbortConfirmationScreen — exact-child confirmation (safe default)
│   │   │   ├── abort_submission.py    # ChildAbortSubmission — tracked request, not-confirmed notice
│   │   │   └── transcript_renderer.py # WorkflowTranscriptRenderer — shared entry formatter (modal + `slo visualize`)
│   │   ├── model_catalog.py           # supported_models_by_provider()
│   │   ├── authentication/            # AuthenticationScreen + widgets (api_key, oauth, …)
│   │   └── widgets/
│   │       ├── user_message_block.py     # UserMessageBlock — one user turn with panel surface styling
│   │       ├── assistant_stream_block.py # AssistantStreamBlock — one assistant answer turn (answer-only)
│   │       ├── assistant_stream_thinking_block.py # AssistantStreamThinkingBlock — one thinking segment per normalized block_id
│   │       ├── tool_execution_block.py   # ToolExecutionBlock — one tool call+result with panel surface styling
│   │       ├── queued_prompt_block.py    # QueuedPromptBlock — one visible latest-wins held ordinary prompt
│   │       ├── markdown_content_compiler.py # MarkdownContentCompiler — markdown-it AST → visible text + spans
│   │       ├── usage_status_bar.py       # UsageStatusBar — token/rate display
│   │       ├── sub_agent_fleet_panel.py  # SubAgentFleetPanel + FleetSessionList — "Ongoing workflow tasks" list below PromptInput
│   │       ├── sub_agent_fleet_row.py    # SubAgentFleetRow — one literal `[status] session-id: task` ListItem
│   │       └── slash_suggestion_menu.py  # SlashSuggestionMenu — autocomplete dropdown
│   └── exceptions.py
├── tests/
│   ├── agents/
│   │   └── slo_agent/                 # unit tests: agent loop, session, rate limits, usage
│   ├── tui/                           # TUI tests: app, replay, slash, status bar, tool blocks
│   │   └── workflows/                 # receive-path dao/service/renderer unit tests
│   └── integration/                   # cross-component composed flows (e.g. feature 94 list → progress → child abort)
├── plugins/
│   └── bash_live_output/              # bundled Feature 75 consumer-only Bash live-output renderer
├── skills/                            # vendored SKILL.md files + INDEX.md
│   ├── INDEX.md                       # regenerated by `make build-skill-index`
│   ├── orientation/  design-and-analysis/  orchestration/  engineering/  languages/
│   ├── presentation/  user-content/  samples/  coding/  git-ops/  cli/  tui/
│   └── integration-tests/  frontend-vue/
├── specifications -> ../specifications  # symlink to the canonical spec root
├── pyproject.toml
├── README.md       ← this file: the maintained codebase reference
├── RESEARCH.md     # distilled project specifics (values, layouts, how-tos)
└── SLO.md          # repository instruction file Slo auto-loads into every agent session
```

### History and persistence

**Default store:** `TreeBasedFileSystemSessionHistoryStore`
(`history/tree_store.py`), laid out under
`~/.slo/sessions/history/<session_id>/`:

```
session.json       # SessionHistoryMetadataDAO — atomic temp+rename; includes session_name/session_name_key
tree.json          # SessionTreeDAO — turn-grouped event tree (default)
transcript.md      # derived; not authoritative
orchestrator.json  # detached-orchestrator self-report when applicable
fleet.json         # durable child fleet projection when applicable
abort_request.json # TUI-to-orchestrator whole-workflow abort channel when applicable
child-control.v1/capability.json                                   # runner child-abort capability
child-control.v1/<run_id>/{requests,receipts}/<request_id>.json   # one child's abort request / settled receipt
children/<child_session_id>/status.json          # child terminal result when applicable
children/<child_session_id>/execution.v1.json    # child incarnation evidence (execution_id, dispatch_id, terminal binding)
execution-index.v1.json                           # session_id → current execution_id, beside fleet.json
```

`status.json`, `fleet.json` and `spawn_context.json` keep their released,
closed shapes; execution identity lives only in the `*.v1.json` siblings, so
older readers keep decoding. `ProcessRegistry.commit_terminal` decides the
first-wins terminal winner before any cache or file projection. It is
reached through `SubAgentProcess._publish_terminal` (wrapper results,
including `finish_without_spawn`) and through `ProcessRegistry.mark_terminal`
(`HeadlessRunner`'s straggler sweep); both share the same arbitration. Child
abort never uses `abort_request.json` (see [§9.7](#97-detached-workflows-the-session-list-and-child-abort)).

The legacy flat store (`FilesystemSessionHistoryStore`) uses `events.jsonl`
instead of `tree.json`. Both satisfy `SessionHistoryStoreProtocol`
(`history/store_protocol.py`); pass a `FilesystemSessionHistoryStore`
explicitly to `SloAgentSession` to opt back into the flat layout.

**Tree layout (`tree.json`):**

- `preamble_events` — envelope events with no `turn_id` (e.g.
  `session_started`).
- `turns` — an ordered `TurnNodeDAO` list; each node holds all events of one
  turn. Tool-call events and their tool-result events always share a
  `TurnNodeDAO` (same `turn_id`), which makes whole-turn compaction safe.
- `token_usage` per `TurnNodeDAO` — running sum of event-level estimates,
  stamped at append time by `TokenUsageEstimator`
  (`history/token_estimator.py`, `ceil(chars / 4)` over the substantive text:
  content, thinking, serialised tool args, tool output, delta; lifecycle
  events count 0).

**`HistoryEventKind`** values: `session_started`, `run_started`,
`user_message`, `steering_message`, `assistant_message`, `assistant_delta`,
`tool_call`, `tool_result`, `run_retrying`, `route_switched`,
`run_completed`, `run_aborted`, `run_failed`, `slash_command` (plus
orchestrator/sub-agent lifecycle kinds). `run_retrying` and `route_switched`
are diagnostic/audit events (spec 37) excluded from
`SessionHistoryProjector.build_message_history`, so audit volume never
inflates model context.

**Per accepted prompt**, `SloAgentSession` (1) ensures the session directory
exists, (2) loads prior history via `SessionHistoryProjector` →
`list[BaseMessage]`, (3) persists `run_started` and `user_message` before
the agent runs, (4) forwards full-fidelity trace events to the store, and
(5) appends the terminal event (`run_completed` / `run_aborted` /
`run_failed`). `SessionHistoryProjector` (`history/projector.py`) excludes
incomplete turns (no terminal event) from model context; they remain
visible in replay.

**Session naming / resume-by-name.** The session directory stays rooted by
`session_id`. Human-readable naming is additive metadata in `session.json`
(`session_name`, `session_name_key`).
`FilesystemSessionHistoryStore.resolve_session_reference()` resolves
`--resume` input by exact `session_id` first, then by normalized
`session_name_key`.

**Context-window snapshot and manual compaction (spec 62).**
`ContextWindowSnapshotService`
(`src/agents/slo_agent/compaction/context_window.py`) is a pure read model:
it resolves routed-model capacity through the model catalog and sums only
`SessionHistoryProjector.context_events()` (selected, message-producing
durable replay events). It is intentionally distinct from cumulative
provider `session_totals`, and may be lower than the automatic compaction
check because `assistant_delta` and incomplete/audit events do not replay.
`SloAgentSession` owns history I/O and caches the snapshot in
`SessionUsageSnapshotDAO`; the TUI refreshes it only at mount,
session/model transitions, `/context-window`, session-owned manual
compaction, and prompt cleanup — never per streamed delta.

`SessionHistoryStoreProtocol.compact_to_boundary()` is the single durable
rewrite seam for automatic, overflow, and manual compaction. The flat store
writes and fsyncs a candidate, moves active history to a collision-free
deterministic archive, activates the candidate, then writes metadata.
Ordinary post-archive failures restore byte-identical active history and
metadata; `HistoryCompactionRecoveryError` names the active/archive paths if
restoration itself fails, and readers restore the deterministic archive
before loading. The tree store delegates to the same transaction.

### Plugins and tool-output streaming

**Plugin runtime (feature 75).** `SloAgentSession` loads managed plugins from
`~/.slo/plugins/plugins/<plugin-id>/`, trusted project plugins from
`.slo/plugins/`, and explicit `--plugin` paths, in that order.
`PluginLoader` imports under isolated `slo_plugin_<namespace>` names;
`PluginRegistry` validates collisions and managed-manifest suffix
declarations; `PluginDispatcher` is one isolated event subscriber and owns
the interception chains. `SLO_PLUGINS_DISABLED=1` disables all plugin tiers.
`slo plugin` lifecycle commands use `PluginInstallerService` as the single
managed-directory writer; the installer never executes installation-source
Python. Dog-food the bundled renderer with
`--plugin plugins/bash_live_output/plugin.py`.

**Tool-output streaming.** `BashTool` may publish accumulated, throttled
`ToolOutputUpdateDAO` snapshots. The executor places them on the
graph-owned queue; `SloAgent` drains it into
`AgentStreamEventDAO(kind="tool_output_update")`. The TUI updates the
existing `ToolExecutionBlock` by `tool_call_id`; partials are emitted on
headless stdout JSONL, persisted when history is enabled, and excluded from
replay model context. The terminal `ToolMessage` remains the sole
model-visible tool result.

### Feature requests and specification artifacts

- **Incoming feature requests:** the repo-local `feature-requests/`
  directory.
- **Canonical specification root:** the operator-side specifications
  directory that `specifications/` points at (a symlink). Resolve it with
  `readlink specifications`; never hard-code a machine path.
- **New specs:** one numbered folder per feature under the canonical root —
  never scattered inside `src/` or ad hoc repo folders.
- **File naming:** the primary document is always `overview.md`; sub-specs
  follow `<spec-number>.<letter>.<index>-<title>.md` (e.g.
  `28.a.1-moonshot-credential-lane.md`). Never name a spec `request.md` (a
  superseded convention).
- **Format:** Markdown (`.md`).

### Style rules

- **Google-style docstrings** on every public function and method.
- **Named arguments** at every call site with two or more arguments:
  `foo(bar=baz, qux=quux)`.
- **Explicit type hints** on every parameter and return value;
  `Optional[T]` with `= None` for nullable parameters; specific containers
  (`list[str]`).
- **Black** formatting, line length 110 (`black src/ tests/`).
- **No bare `Any`** — prefer `BaseChatModel`, `BaseTool`, `BaseMessage`, etc.
- **Declarative method structure** — one decision per method; orchestrators
  read like a table of contents; no nested conditionals past two levels.
- **Class convention** — core logic lives in a class with `@classmethod`
  methods; the public entry is `invoke` (or `build` / `load` / `create`).
  Free functions are reserved for `@tool` bridges, LangGraph nodes, and test
  helpers.

### Testing rules

The suite rules (FauxChatModel only, the `not e2e` default gate,
`environments/tests.env`, the no-real-terminal-windows guards, test layout,
`asyncio_mode = "auto"`) are in [§8.5](#85-suite-rules); the
one-test-per-decision policy is in [§8.4](#84-coverage-discipline).

### Commit and branch conventions

- **One feature per branch** from `main`. Branch name:
  `feature-<detail_in_snake_case>` or a JIRA ID in lowercase.
- **Commit title:** `<JIRA-ID or topic> <one-line description>`, at most 72
  characters.
- **Commit body:** list the core changes and files modified.
- **`Co-Authored-By:`** footer when pairing with an AI assistant.
- For the operational sub-steps (sync main, branch, commit and push, PR,
  review fix), use the matching skills in `skills/git-ops/`.

### Keeping this README current

**Update README.md whenever you:**

- Add a new component, module, or package.
- Rename or move a module.
- Change the runtime chain (CLI → TUI → Session → Agent → Graph).
- Alter the system prompt assembly order or add/remove a section.
- Change the default tool bundle or add a new tool.
- Regress or change the tools-block wiring behind known issue B1.
- Add a new slash command, change prompt-history semantics, or change the
  auth flow.
- Change plugin discovery, managed installation, plugin
  dispatch/interception, or tool-output streaming.
- Change the history event schema or persistence layout.
- Add a new provider or change credential resolution precedence.
- Change the `--workspace` CLI surface or workspace-context discovery
  semantics.
- Change the canonical feature-request root (`feature-requests/`) or the
  specification root that `specifications/` points at.

Keep [§5.3](#53-the-system-prompt-builder) (system prompt assembly) and
[§5.4](#54-tools) (tool bundle) accurate — they directly affect what every
agent session sees and does. When a change alters an exact value (a
timeout, default, cap, budget, status-code mapping, file name, or command),
update `RESEARCH.md` as well.
