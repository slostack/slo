# Slo — A Reader's Guide to the Code

> *An end-to-end walkthrough of an in-process Textual coding agent, from the
> keystroke that lands in your terminal to the streaming response that paints
> back at you. Read this once and you can navigate every file in the
> repository.*

> **Current capability snapshot (June 2026, v0.9.2):** Slo supports
> interactive multi-turn conversations via the Textual TUI, headless one-shot
> runs (`slo run -p "..." --json`) for scripted/CI use, and **sub-agent
> orchestration** — the parent agent can spawn parallel or sequential child
> agents via `spawn_sub_agents`, each running as an isolated `slo run`
> process. User-defined skills and workflows can be dropped into
> `~/.slo/user_skills/` and `~/.slo/user_workflows/` and are automatically
> merged with the 100+ vendored skills at session start. v0.8.0 added a
> **third AI provider: Kimi For Coding (KFC)** — an OpenAI-compatible API
> from Moonshot AI with a `ModelPool` fallback router and automatic
> credit-exhaustion handling (see
> [Section 6.6](#66-kimi-for-coding-kfc-provider)). v0.9.0 **wires that
> `ModelPool` into the production build path** and layers a three-tier
> rate-limit defense on top of it — a history-aware preflight, an in-call
> pool route-switch, and an iteration-scoped retry — opt-in via the
> `SLO_MODEL_POOL` environment variable or the `default_model_pool` user
> preference (see [Section 6.7](#67-multi-model-pool-and-rate-limit-defense)).

---

## Preface

This is not a feature list. This is a **narrative walkthrough** of Slo — a
single-process Python coding agent built on LangGraph, LangChain, and
Textual — written for the reader who already knows Python and wants to
understand exactly how the wires connect.

You will install Slo, send a prompt, then trace that prompt through every
layer it touches: the Textual `App`, the message-pump machinery, the
session wrapper, the agent loop, the LangGraph state graph, the tool
dispatch, the response stream, the renderer, the on-screen widget. Each
hop is grounded in a real file path and a real line number. When the chain
involves something Textual-specific that the average Python reader hasn't
seen — `ComposeResult`, `ModalScreen`, the message handler's snake-cased
auto-discovery — there is a short primer at the point where you need it.

The aim is the same as O'Reilly's *Designing Data-Intensive Applications*
or *Crafting Interpreters*: by the time you finish, the code should read
like prose to you. You should be able to debug a misbehaving prompt by
naming the layer responsible without looking it up.

### How to read this book

- **Linear reading** is the right default. The chapters are
  dependency-ordered: each one assumes the previous one. Chapter 4 — the
  full lifecycle of a prompt — is the centerpiece; everything else is
  scaffolding for it or extension of it.
- **As a reference**, jump to the [File Map appendix](#appendix-a--file-map)
  for "where does X live?" lookups.
- **As a primer for Textual**, [Chapter 3](#chapter-3--a-five-minute-textual-primer)
  stands alone.
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

---

## Chapter 1 — Installing Slo on Your Laptop

> **Installing, updating, or hosting the one-line installer?** See
> **[`docs/INSTALL.md`](docs/INSTALL.md)** — the authoritative guide to
> `install.sh`, the `curl | bash` production flow (deploy-token auth, Cloudflare
> hosting at `get-slo.sh`), `slo update`, uninstalling, and troubleshooting.
> The narrative below predates the current pipx-based installer and is kept as
> background reading.
>
> **Need architecture and runtime docs?** See
> **[`docs/RESEARCH.md`](docs/RESEARCH.md)** for the codebase index,
> **[`docs/SLO_HEADLESS_README.md`](docs/SLO_HEADLESS_README.md)** for headless
> execution and orchestrator usage, and
> **[`docs/SLO_SCHEDULER_README.md`](docs/SLO_SCHEDULER_README.md)** for the
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
  isolated venvs without contaminating system Python.
- **Poetry 2.x** for dependency resolution and the editable install.
- **`git`**, because `install.sh` clones the repo into `~/.slo/`.
- **Either an Anthropic Claude subscription or an OpenAI ChatGPT
  subscription** for the OAuth path, *or* an API key from
  `console.anthropic.com` / `platform.openai.com` for the paste-a-key
  path. You can sort this out after first launch — the TUI will walk you
  through it.

### 1.2 The Production Path — `install.sh`

The script at the repository root handles the end-to-end install:

```bash
curl -fsSL https://example.com/install.sh | bash
```

(The URL is a placeholder until the repo is published.) The script:

1. Clones the repository into `~/.slo/` (configurable via `SLO_HOME`).
2. Creates a pyenv virtualenv named `slo` against Python 3.11.7.
3. Runs `pipx install --editable --python python3.11 ~/.slo`. The
   `--editable` flag means `pipx` symlinks the package into the
   pyenv-managed venv; you can edit source under `~/.slo/slo/src/` and
   the changes are live without reinstalling.
4. Writes the `slo` console-script entry into your shell's `$PATH`.
5. Prints the next-steps banner: *"Run `slo` to start."*

`pyproject.toml:57` declares `slo = "src.cli:main"`. After install,
`~/.pyenv/versions/3.11.7/envs/slo/bin/slo` is a thin shim that calls
`src.cli:main`, which itself defers to the Typer app in `src/cli/app.py`.

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
every runtime dependency (FastAPI, LangChain, LangGraph, Textual,
aiohttp, …), every dev dependency (`pytest`, `black`, `mypy`,
`autoflake`), and finally registers the `slo` console script the same
way `install.sh` does. After this you can run `slo` directly from any
directory.

### 1.4 Where Things Live

Two directories outside your working tree matter:

- **`~/.slo/`** is Slo's persistent root. The installer clones the repo
  here; the `skills/` library lives at `~/.slo/skills/`; persistent
  session state will land at `~/.slo/sessions.db` once 01.o ships.
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
make test                # 431 tests pass
```

The Makefile lives at `slo/Makefile`. `make test` sources the
`environments/tests.env` file (so test runs never use your development
database) and then runs the full pytest suite. If this is green, you're
ready to launch.

---

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

You pick a provider (Anthropic or OpenAI), then a method (browser OAuth
or paste-an-API-key). If you pick OAuth, the modal renders the
authorization URL, calls `webbrowser.open(url)`, and binds a one-shot
HTTP server on `127.0.0.1:<ephemeral-port>` waiting for the redirect.
You sign in on the provider's page; the redirect lands; the modal
exchanges the code for a token and writes a `CredentialDAO` to
`~/.slo/global/authentication.json` (mode `0600`).

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

When the agent finishes, the final response renders as Markdown — code
blocks, lists, headings, all rendered by Rich:

```
This project is a Python coding agent built on LangGraph and Textual…
```

### 2.4 Reading the Transcript

The transcript is a scrollable column of widgets — a
`VerticalScroll(#transcript-scroll)` wrapping a `Vertical(#transcript-content)`
into which each conversational entry is mounted as its own component (see
Chapter 4): a `UserMessageBlock` for your turn, an `AssistantStreamBlock`
for the reasoning + answer, and a `ToolExecutionBlock` per tool call. Only
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
| `/workflows` `/wf` | List detached workflows; `abort <id>` SIGTERMs the workflow's process group (SIGKILL after 5 s); `dismiss <id>` acknowledges a stalled one |

The router is **Textual-free**: every handler returns a
`SlashCommandResultDAO` (`src/tui/slash_router.py:17`) carrying flags
like `rendered`, `should_clear`, `should_exit`, `open_auth_modal`. The
TUI translates those flags into `push_screen`, `exit`, transcript
writes. This separation is what lets us test the router in plain pytest
without spinning up a Textual `App`.

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
| `AssistantStreamBlock` | `src/tui/widgets/assistant_stream_block.py` | One assistant turn: a reasoning region + an answer region |
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
        self._render_busy_line()              # already running → busy message
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
4. Already running? Render the busy line; refuse a second prompt.
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

### 4.7 Normalizing Chunks into Stream Events

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
  with a single `Static`. It renders the user turn as padded markdown and
  is built once — its renderable is constructed in `__init__` (not
  `on_mount`), because setting a `Static`'s content mid-mount-cycle races
  the child's first render and Textual raises while compositing.

- **`AssistantStreamBlock`** (`widgets/assistant_stream_block.py`) is a
  `Vertical` with two `Static` regions — a reasoning region and an answer
  region — plus a terminal-note line. `append_thinking` / `append_text`
  accumulate into that block's own buffers and re-render **only that
  block's** `Static`:

  ```python
  def _render_thinking(self) -> None:
      self._thinking_body.update(
          Padding(Markdown(self._thinking_text.strip(), style="italic"), pad=(0, 1, 0, 1))
      )
  ```

  Reasoning renders as muted italic markdown with Pi-style horizontal
  padding, and — deliberately — **without** a literal "Thinking" heading,
  because the region is already visually distinct. `finalize(final_text=)`
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
entry — and each component owns its own markdown `Static`(s):

```
SloTUI (App)
└── Vertical #chat-shell
    ├── VerticalScroll #transcript-scroll
    │   └── Vertical #transcript-content          ← entries mount here, in order
    │       ├── UserMessageBlock                  user turn
    │       │   └── Static .user-message-body          (markdown, rendered ONCE at build)
    │       ├── AssistantStreamBlock  (iteration 0)   assistant turn
    │       │   ├── Static .assistant-thinking-body    (reasoning markdown)
    │       │   ├── Static .assistant-answer-body  ◀━━ REPARSED at end of stream
    │       │   └── Static .assistant-terminal-warning
    │       ├── ToolExecutionBlock  (tool_call_id)    tool call
    │       │   ├── Static .tool-call-headline         (⏺, rebuilt on each arg delta)
    │       │   └── Static .tool-call-result       ◀── reparsed once, when result arrives
    │       ├── AssistantStreamBlock  (iteration 1)   next assistant turn → its own block
    │       │   └── …
    │       └── Static .turn-separator / .tool-result  (non-conversational notices only)
    ├── Vertical #status-region
    │   └── ThinkingSpinner                       (fixed; mounted only during a run)
    └── PromptInput                               (pinned at the bottom)
```

**Which component is independently reprocessed at end-of-stream.** The
**`AssistantStreamBlock`** is the one re-rendered when the message stream
closes. During streaming its `answer` region reparses the *partial*
buffer on each `text_delta`; then at the **end** of the assistant message
stream the completed truth replaces that partial in a single final reparse
of **that block's answer `Static` only**:

- `text_end` (carrying completed text) → `set_answer(content=...)` →
  `_render_answer()` reparses the full answer markdown.
- `run_completed` → `finalize(final_text=...)` → `_render_answer()` reparses
  once more with the runtime's authoritative final text, so any
  streamed-delta spacing/markdown artifacts are discarded.

The reasoning region is likewise replaced once via `set_thinking` on
`thinking_end`. By contrast, the **`UserMessageBlock`** renders its markdown
exactly once at construction and is never reprocessed, and a
**`ToolExecutionBlock`** reparses its result line only when its single
`tool_result` arrives. So the end-of-stream markdown reprocessing is scoped
to one `Static` — the answer region of the current turn's
`AssistantStreamBlock` — never the transcript as a whole.

#### 4.10.1 The Transcript Window, Block Liveness, and the Protected Tail

Mounting one widget per semantic unit is what makes streaming cheap, but it
also means a long session accumulates widgets without bound. `TRANSCRIPT_WINDOW_SIZE`
(`src/tui/app.py`, currently `80`) caps how many children stay mounted under
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
(`29 / 60 / 79 / 80 / 90` stuck-live blocks) against the real eviction algorithm,
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
removed only in `_run_prompt`'s `finally`. Because it is a sibling of the
scroll region rather than a line *inside* the transcript, scrolling
content never hides it and the `PromptInput` never moves.

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
produces no reasoning region, matching the live path.

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
built at agent-construction time by `SystemPromptBuilder` (lives in
`src/agents/prompts/`). The builder assembles:

- A role line ("You are Slo, a coding agent…").
- The list of tools with their docstrings.
- The skills index from `~/.slo/skills/INDEX.md`.
- Project-context blobs (the contents of `CLAUDE.md`, `AGENTS.md`,
  and `docs/RESEARCH.md` when present in the repo lineage).
- Behavioural guidelines (when to abort, when to ask, how to use
  Markdown).

The builder is invoked once per `SloAgent.__init__` — the system prompt
is baked into the graph's compiled state. Changing the prompt requires
restarting the agent (Slo's "session = one process" design makes this
acceptable).

### 5.4 Tools

Tools live under `src/agents/tools/`. Each tool is a `StructuredTool`
(LangChain's class for tools with typed arguments) bound to a Pydantic
args schema. The agent's tool registry is assembled by
`create_extended_tools()` (`src/agents/tools/registry.py`).

The standard tool set (`create_extended_tools()` — the default bundle):

| Tool | What it does |
|---|---|
| `read` | Read a file (text or image) |
| `write` | Write/overwrite a file |
| `edit` | Exact-string find-and-replace |
| `bash` | Run a shell command |
| `grep` | Regex search across files |
| `find` | Find files by pattern |
| `ls` | List directory contents |
| `now` | Return current UTC timestamp |
| `read_pdf` | Extract text from a PDF |

Additional tools available but **not** in the default bundle:

| Tool | When available |
|---|---|
| `a2a_peer` | Explicit addition — outbound A2A delegation to remote agents |
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
agent.

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
  after a rate-limit or server error (HTTP 429 / 500).

Error classification is handled by `CreditExhaustionPolicy`
(`src/agents/providers/credit_exhaustion_policy.py`). For KFC:

- **HTTP 402** → `CREDIT_EXHAUSTED` → entry cooled down for 300 s.
- **HTTP 429 or 500** → `RATE_LIMITED` → entry cooled down for 60 s.

When an entry is cooled down, `ModelPool.next_available()` skips it
and tries the next priority entry. If all entries are exhausted,
`ModelPool` raises `ModelPoolExhaustedError`.

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

#### The three layers (composed top-to-bottom)

1. **History-aware preflight (session).** The local token estimate now
   counts the *replayed message history* — assistant text, tool-call
   payloads, and tool outputs — not just the new prompt. A resumed
   session therefore waits *before* it would 429, emitting a
   `Waiting Ns for <model> local rate window` status.
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

Two new history event kinds are persisted to `events.jsonl`:

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

**Step 2**: register it. `src/agents/tools/registry.py`:

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

History is **disabled by default** for headless runs — the orchestrator
links children by session id, not by replaying their histories. Use
`--enable-history` to opt in.

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
        ├─ 3600-second inactivity timeout (no output for 60 min → terminate + fail, env SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS, alias SLO_SUBAGENT_INACTIVITY_TIMEOUT)
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
fleet status rows mounted below `PromptInput` during a run. Each row
shows: status icon, task id, elapsed seconds, and the latest activity
text (`text_delta`, `thinking_delta`, or `tool_result` from the child).
Automatically hidden when no sub-agents are active.

**`TranscriptProjector` sub-agent routing** — the projector's
`is_sub_agent_event` gate routes events with a `sub_agent_id` to the
correct pane via `AgentPaneManager`, while orchestrator events go to
pane `[0]`.

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
  for 3600 seconds (60 minutes, configurable via `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS`; alias `SLO_SUBAGENT_INACTIVITY_TIMEOUT`), `SubAgentProcess` terminates it and marks it failed.

---

## Appendix A — File Map

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
│   ├── sub_agent_fleet_panel.py   # SubAgentFleetPanel — live fleet status rows (one per active sub-agent)
│   ├── tool_execution_block.py    # one live tool call: ⏺ headline + ⎿ result
│   ├── usage_status_bar.py        # UsageStatusBar — token/rate display above footer
│   └── user_message_block.py      # one user turn: padded markdown
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

- `tests.env` — test env (sourced by `make test`).
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
| **`UserMessageBlock`** | A mounted widget for one user turn — padded markdown, rendered once at construction. |
| **`AssistantStreamBlock`** | A mounted widget for one assistant turn — a reasoning region + an answer region. Re-renders only itself; the answer region is the one reparsed at end-of-stream. |
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
| **`SubAgentFleetPanel`** | Fleet status row widget shown below `PromptInput` during a sub-agent run; one row per active child. |
| **`SkillsLoader`** | Scans skill directories for `SKILL.md` files; `load_merged()` merges vendored + user + workflow skills with user-wins-on-collision. |
| **`USER_SKILLS_DIR`** | Default `~/.slo/user_skills`; user-defined skills placed here automatically override same-named vendored skills. |
| **`USER_WORKFLOWS_DIR`** | Default `~/.slo/user_workflows`; multi-step pipeline workflows scanned alongside user skills. |
| **`steering_applied`** | New `AgentStreamEventDAO` kind emitted when a queued `/steer` message is consumed by the agent loop. |
| **`ModelPool`** | A drop-in `BaseChatModel` (overrides `_generate`/`_agenerate`/`_astream`) that routes across a priority-ordered list of models with cooldown-based failover; wired into the production build path in v0.9.0. |
| **`ProviderErrorKind`** | The taxonomy that classifies a provider error — rate limit (429), credit exhaustion (402/quota), `TRANSIENT_PROVIDER_FAILURE` (500/502/503/529), or `OTHER`. `should_switch(kind)` decides switch-vs-propagate. |
| **`SLO_MODEL_POOL`** | Environment variable (or the `default_model_pool` user preference) holding a comma-separated, priority-ordered list of model names. Two or more names enable the pool; fewer collapses to single-model. |
| **`route_switched`** | Diagnostic-only history event recording each pool switch (`from`/`to`/`kind`). Persisted to `events.jsonl`; excluded from model context. |
| **`run_retrying`** | Diagnostic-only history event recording each wait-and-retry decision. Persisted to `events.jsonl`; excluded from model context. |

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

A shared `asyncio.Semaphore(MAX_CONCURRENCY)` (default 4, env `SLO_SUBAGENT_MAX_CONCURRENCY`) is the ceiling. Tasks beyond the cap queue until a slot opens.

**Chain** — `_run_chain` runs tasks one at a time. Each step's prompt may contain `{previous}`, substituted with the prior step's final `answer` before the child is spawned. A failed step stops the chain; remaining tasks are skipped entirely.

**Single** — a degenerate parallel batch of size 1. Same `asyncio.gather` code path.

### 7.5 `_run_one()` — One Task's Lifecycle

Every task (regardless of mode) flows through `_run_one`. The full lifecycle:

```
1. session_id = uuid4()                           # unique identity for this child
2. registry.register(task_id, session_id, task)   # status → pending
3. relay ← sub_agent_spawned event                # TUI fleet row appears
4. process = SubAgentProcess(task, session_id, model, relay, registry)
   _active.append(process)                        # tracked for cancel_all()
5. async with semaphore:                          # blocks if MAX_CONCURRENCY running
       registry.mark_running(session_id)          # status → running
       result = await process.run()               # blocks until child exits
6. relay ← sub_agent_completed / sub_agent_failed
7. registry.mark_terminal(session_id, status, answer)
8. return SubAgentResultDAO
```

### 7.6 `SubAgentProcess` — The Child OS Process

`SubAgentProcess` (`orchestrator/process.py`) manages exactly one `slo run --json` child process.

**Command line (`_build_argv`):**

```python
[
    sys.executable,        # same interpreter and venv as the parent
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
        timeout=CHILD_INACTIVITY_TIMEOUT_SECONDS,   # 3600 s default (env SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS; alias SLO_SUBAGENT_INACTIVITY_TIMEOUT)
    )
    if not raw:   # EOF = child exited
        return
    await self._handle_line(raw=raw)
```

The `_STDOUT_STREAM_LIMIT = 16 * 1024 * 1024` constant is passed as `limit=` to `asyncio.create_subprocess_exec`. This raises asyncio's default 64 KB per-line buffer to 16 MB, preventing `ValueError: Separator is found, but chunk is longer than limit` on large `run_completed` JSON lines. The inactivity watchdog (default 3600 s, configurable via `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS`; alias `SLO_SUBAGENT_INACTIVITY_TIMEOUT`) treats a hung `readline()` as a failure rather than blocking the parent forever.

**Per-line handler (`_handle_line`):**

1. Parse bytes → `AgentStreamEventDAO`. Non-JSON child diagnostic lines are silently ignored.
2. If terminal: capture `event.content` as the final answer.
3. If `forwarded_bytes >= PER_TASK_OUTPUT_CAP` (50 KB) and not terminal: drop the event. The relay stays bounded; terminal events are always forwarded regardless of the cap.
4. If `text_delta`: call `registry.update_last_text(session_id, event.delta)` so the TUI fleet panel shows a live preview.
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

`ProcessRegistry` (`orchestrator/registry.py`) is a plain `dict[session_id → SubAgentStatusDAO]`. One registry per pool; never persisted to disk.

**Write API** (called by pool and process only):

| Method | Called when | Transition |
|---|---|---|
| `register(task_id, session_id, task)` | Before `sub_agent_spawned` emit | → `pending` |
| `mark_running(session_id)` | After semaphore acquired | → `running` |
| `update_last_text(session_id, text)` | Each `text_delta` from the child | updates `last_text` |
| `mark_terminal(session_id, status, answer)` | After `process.run()` returns | → `completed`/`failed`/`aborted` |

**Read API** (TUI fleet panel, tests):
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
    async with semaphore (MAX_CONCURRENCY=4)
         │
         ▼
  SubAgentProcess.run()
         │  asyncio.create_subprocess_exec
         │  [python, -m, src.cli, run, --json, -p, <prompt>]
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
         ├──▶ TUI (fleet panel rows, assistant blocks)
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
| `CHILD_INACTIVITY_TIMEOUT_SECONDS = 3600 s` (env `SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS`, alias `SLO_SUBAGENT_INACTIVITY_TIMEOUT`) | A hung `readline()` surfaces as a clean `failed` result; 60-minute default accommodates large-context LLM calls with slow TTFT |
| `_STDOUT_STREAM_LIMIT = 16 MB` | Prevents `ValueError` on large `run_completed` JSON lines; asyncio's default is 64 KB |
| `args_schema=SpawnSubAgentsSchemaDAO` | Fixes LangChain bug where string-encoded args cause `TypeError` inside `StructuredTool._arun` |
| `asyncio.gather(..., return_exceptions=True)` in `cancel_all` | One child's cancel failure never blocks the others |
