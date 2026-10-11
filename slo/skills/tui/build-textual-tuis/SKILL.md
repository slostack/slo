---
name: build-textual-tuis
description: Building Textual TUIs under src/tui with explicit app/router/renderer/
  widget boundaries, detailed examples, and walkthroughs for slash commands, modal
  flows, and pilot-tested interaction.
when_to_use: Use when building or refactoring a Textual UI under `src/tui/`, including
  screens, widgets, renderers, and interaction flows.
group: tui
kind: skill
source_prompt: tui/build-textual-tuis.md
---

# Build Textual TUIs

## Skill summary

- **Name:** `build-textual-tuis`
- **Description:** Building Textual TUIs under src/tui with explicit app/router/renderer/ widget boundaries, detailed examples, and walkthroughs for slash commands, modal flows, and pilot-tested interaction.
- **When to use:** Use when building or refactoring a Textual UI under `src/tui/`, including screens, widgets, renderers, and interaction flows.
- **Group:** `tui`
- **Kind:** `skill`
- **Source prompt:** `tui/build-textual-tuis.md`

## Examples

- The user asks: "Add or revise the textual tuis for this feature."
- You want the canonical build pattern before touching textual tuis.

## Guidance

This document defines the conventions for **Python terminal UIs** built with **Textual** under `src/tui/`, with **Rich** providing formatted output inside widgets and logs.

These rules are derived from Slo's `src/tui/` implementation:

- `src/tui/app.py`
- `src/tui/app.tcss`
- `src/tui/slash_router.py`
- `src/tui/event_renderer.py`
- `src/tui/thinking_spinner.py`
- `src/tui/authentication/`
- `tests/tui/test_app.py`
- `tests/tui/test_event_renderer.py`
- `tests/tui/authentication/...`

---

## 1. Core idea

A maintainable Textual application separates four different concerns that often get mixed together:

1. **UI composition**
   - widget tree, keybindings, lifecycle hooks
2. **UI event interpretation**
   - slash commands, custom widget messages, modal state transitions
3. **Domain interaction**
   - session/service calls, streaming, persistence
4. **Rendering**
   - transcript lines, semantic classes, markdown/final output, spinners

When these are separated, the TUI stays testable.
When they collapse into one `app.py`, the result becomes impossible to reason about.

---

## 2. Golden architecture

```text
App.compose()
-> widget Message / key Binding
-> app handler
-> router/helper (slash router, renderer, modal coordinator)
-> session / service method
-> streamed domain event(s)
-> renderer / adapter
-> transcript widget / screen state update
```

### Responsibility map

| Layer | Canonical files | Responsibility |
|---|---|---|
| App shell | `src/tui/app.py` | `App` subclass, widget tree, bindings, lifecycle hooks |
| Shared helpers | `slash_router.py`, `event_renderer.py` | interpret slash commands and render domain events |
| Reusable widgets | `thinking_spinner.py`, `widgets/*.py` | local interaction and presentation |
| Screen flows | `authentication/auth_screen.py` | multi-step modal orchestration |
| Styling | `app.tcss`, `*_screen.tcss` | layout and semantic presentation |

### The rule of thumb

- **App** decides *what UI pieces exist*
- **widgets** emit *semantic events*
- **routers/renderers** decide *what those events mean*
- **sessions/services** do *real work*
- **adapters/widgets** show *results back to the user*

---

## 3. Canonical folder layout

```text
src/tui/
├── __init__.py
├── app.py
├── app.tcss
├── slash_router.py
├── event_renderer.py
├── thinking_spinner.py
└── <feature>/
    ├── <feature>_screen.py
    ├── <feature>_screen.tcss
    ├── state.py
    └── widgets/
        ├── __init__.py
        ├── widget_a.py
        └── widget_b.py

tests/tui/
├── test_app.py
├── test_event_renderer.py
├── test_slash_router.py
└── <feature>/...
```

### Rules

| Rule | Detail |
|---|---|
| one reusable widget per file | small focused modules are easier to test |
| each screen gets adjacent TCSS | `auth_screen.py` next to `auth_screen.tcss` |
| helpers stay top-level | slash routing and event rendering are shared TUI infrastructure |
| tests mirror source layout | app tests, renderer tests, screen tests, widget tests |

---

## 4. Inject sessions and services — never build them inside widgets

Slo's `SloTUI` receives a pre-built session:

```python
class SloTUI(App):
    def __init__(self, *, session: SloAgentSession) -> None:
        super().__init__()
        self._session: SloAgentSession = session
```

### Why this is non-negotiable

If widgets/screens build sessions, clients, stores, or services internally:

- tests become patch-heavy and brittle
- flow state and object graph setup get tangled together
- CLI/TUI boundary becomes meaningless
- the TUI stops being reusable in alternate startup paths

### Bad

```python
class ChatScreen(Screen):
    def __init__(self) -> None:
        self._client = RealClient(...)
        self._service = ChatService(client=self._client)
```

### Good

```python
class AuthenticationScreen(ModalScreen[CredentialDAO | None]):
    def __init__(
        self,
        *,
        store: CredentialStore | None = None,
        oauth_factory: OAuthFactory | None = None,
    ) -> None:
        ...
```

### Allowed injection targets

- session facades
- service objects
- credential stores
- OAuth/browser factories
- filesystem adapters
- small protocol-based collaborators used only for rendering/testing

---

## 5. `compose()` builds the tree; lifecycle hooks wire behavior

### `compose()` is for structure

Use `compose()` to:

- instantiate widgets
- yield the visible tree
- keep typed refs to widgets you need later

### `on_mount()` is for activation

Use `on_mount()` to:

- set focus/title/subtitle
- subscribe to session streams
- mount/push startup modals
- initialize dynamic UI state

### `on_unmount()` is for cleanup

Use `on_unmount()` to:

- unsubscribe from streams
- cancel long-lived tasks
- detach listeners
- clear transient state that must not leak across runs

### Canonical example

```python
def compose(self) -> ComposeResult:
    yield Header(show_clock=False)
    with Vertical():
        self._transcript = RichLog(...)
        self._adapter = _TranscriptAdapter(tui=self)
        yield self._transcript
        self._input = PromptInput()
        yield self._input
    yield Footer()
```

### Review rules

| Rule | Detail |
|---|---|
| the tree should be readable in one place | avoid scattering widget creation into many helpers |
| store typed refs deliberately | `self._input`, `self._transcript`, `self._spinner` |
| lifecycle hooks stay flat | subscribe, focus, maybe mount modal — not giant nested logic |

---

## 6. Use semantic `Message` subclasses for real UI events

Textual's default widget events are often too low-level.
Define semantic events instead.

### Canonical example

```python
class PromptInput(TextArea):
    class Submitted(Message):
        def __init__(self, *, text: str) -> None:
            self.text: str = text
            super().__init__()
```

### Good semantic events

- prompt submitted
- provider chosen
- auth method chosen
- back requested
- success acknowledged
- modal cancelled

### Why this matters

Without semantic messages, your handlers end up coupled to:

- key names
- widget internals
- brittle DOM assumptions

With semantic messages, handlers read like business/UI intent:

- `on_prompt_input_submitted(...)`
- `on_provider_select_provider_chosen(...)`
- `on_success_widget_closed(...)`

### Walkthrough — build a semantic message

If you need a widget to notify the parent app when the user confirms a choice:

```python
class ProviderSelect(Static):
    class ProviderChosen(Message):
        def __init__(self, *, provider: ProviderKind) -> None:
            self.provider: ProviderKind = provider
            super().__init__()

    def _choose(self, *, provider: ProviderKind) -> None:
        self.post_message(self.ProviderChosen(provider=provider))
```

Then the screen/app consumes it:

```python
@on(ProviderSelect.ProviderChosen)
def _on_provider_chosen(
    self,
    message: ProviderSelect.ProviderChosen,
) -> None:
    self._selected_provider = message.provider
    self._show_method_step(provider=message.provider)
```

This is the expected pattern.

---

## 7. Route slash commands through a dedicated router

Do **not** parse slash commands inline in `App.on_prompt_input_submitted`.
That makes the app a hidden parser.

### Canonical result object

```python
class SlashCommandResultDAO(BaseModel):
    rendered: str | None = None
    should_exit: bool = False
    should_clear: bool = False
    open_auth_modal: bool = False
```

### Canonical use

```python
result = await SlashRouter.dispatch(line=text, session=self._session)
```

### Why this split matters

- slash parsing becomes unit-testable
- command lookup lives in one place
- the app applies results declaratively instead of branching endlessly

### Good router structure

```python
class SlashRouter:
    _HANDLERS: dict[str, Callable[..., Awaitable[SlashCommandResultDAO]]] = {
        "/help": _handle_help,
        "/clear": _handle_clear,
        "/auth": _handle_auth,
    }
```

### Bad router structure

```python
async def on_prompt_input_submitted(...) -> None:
    if text.startswith("/help"):
        ...
    elif text.startswith("/clear"):
        ...
    elif text.startswith("/auth"):
        ...
    elif text.startswith("/logout"):
        ...
```

That code does not scale.

---

## 8. Walkthrough — add a new slash command

### Goal

Add:

```text
/clear
```

that clears the transcript and confirms the action.

### Step 1 — add the handler in `slash_router.py`

```python
async def _handle_clear(*, session: SloAgentSession) -> SlashCommandResultDAO:
    return SlashCommandResultDAO(
        rendered="Cleared transcript.",
        should_clear=True,
    )
```

### Step 2 — register it in the handler map

```python
_HANDLERS: dict[str, SlashHandler] = {
    "/clear": _handle_clear,
}
```

### Step 3 — keep the app declarative

```python
result = await SlashRouter.dispatch(line=text, session=self._session)

if result.should_clear:
    self._clear_transcript()
if result.rendered is not None:
    self._transcript_write(result.rendered, classes="system-line")
```

### Step 4 — test the router separately

```python
async def test_clear_returns_clear_result(fake_session: FakeSession) -> None:
    result = await SlashRouter.dispatch(line="/clear", session=fake_session)

    assert result.should_clear is True
    assert result.rendered == "Cleared transcript."
```

### Step 5 — test the app behavior with pilot

```python
async def test_clear_command_clears_transcript() -> None:
    app = SloTUI(session=FakeSession())

    async with app.run_test() as pilot:
        await pilot.press("slash", "c", "l", "e", "a", "r", "enter")
        ...
```

The exact key-driving varies by widget, but the test goal is stable:

- router gets invoked
- clear branch runs
- transcript updates accordingly

---

## 9. Render streamed/domain events through a dedicated renderer + adapter

Slo's `EventRenderer` is the model.
The app should not manually format tool events, status updates, and final assistant output inline.

### Architecture

| Piece | Job |
|---|---|
| `EventRenderer` | decide what gets rendered for each event type |
| `RichLogLike` protocol | tiny write interface used by the renderer |
| `_TranscriptAdapter` | record semantic writes and forward to the actual widget |
| `SloTUI._transcript_write` | map semantic classes to Rich/Textual rendering |

### Why this split matters

- renderer tests do not need Textual
- formatting rules stay out of event handlers
- the app remains orchestration code
- transcript assertions can target an explicit seam

### Example protocol seam

```python
class RichLogLike(Protocol):
    def write(self, content: str, *, classes: str | None = None) -> None: ...
```

### Example renderer use

```python
EventRenderer.render(event=event, target=self._adapter)
```

### Walkthrough — add a new event type

Suppose streaming introduces a new event:

```python
ProgressEventDAO(kind="tool_started", tool_name="grep")
```

Implement it in the renderer:

```python
if event.kind == "tool_started":
    target.write(
        f"Running tool: {event.tool_name}",
        classes="tool-line",
    )
    return
```

Test it with a fake target:

```python
class FakeRichLog:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str | None]] = []

    def write(self, content: str, *, classes: str | None = None) -> None:
        self.lines.append((content, classes))
```

```python
def test_tool_started_renders_tool_line() -> None:
    target = FakeRichLog()

    EventRenderer.render(
        event=ProgressEventDAO(kind="tool_started", tool_name="grep"),
        target=target,
    )

    assert target.lines == [("Running tool: grep", "tool-line")]
```

---

## 10. Centralize semantic class -> style mapping

Do not scatter Rich style strings throughout handlers.

### Canonical map

```python
_CLASS_TO_STYLE: dict[str, str] = {
    "user-line": "bold",
    "tool-line": "dim cyan",
    "tool-result": "dim",
    "assistant-final": "",
    "assistant-aborted": "italic yellow",
}
```

### Rules

| Rule | Detail |
|---|---|
| use semantic classes | `tool-line`, `assistant-final`, `system-line` |
| centralize mapping | one table, one obvious place |
| special cases are allowed | final markdown can use different rendering logic |

This makes transcript styling editable without rewriting event logic.

---

## 11. Transient UI belongs in its own widget module

Slo's `ThinkingSpinner` is the pattern.

### Extract a standalone widget when it owns

- a timer
- rotating text/state
- mount/unmount lifecycle
- a stable CSS class contract
- focused tests

### Bad

```python
class SloTUI(App):
    def _tick_spinner(self) -> None:
        ...  # 60 lines of spinner state management
```

### Good

```python
class ThinkingSpinner(Static):
    ...
```

The app should mount/unmount it, not implement it inline.

---

## 12. Multi-step modal flows use a screen + state enum + step widgets

Slo's authentication flow is the canonical example.

### Correct structure

- `AuthenticationScreen` owns flow orchestration
- `ScreenState` enum names the current step
- each step widget lives in its own file
- `_swap_step()` (or equivalent) replaces the active child cleanly
- the screen handles persistence, async work, and dismissal

### Why this pattern wins

- each step widget stays tiny
- transitions are explicit
- tests can drive the flow one state at a time
- side effects stay at the screen level

### Bad

One 400-line widget that:

- shows all auth controls
- stores all state
- launches OAuth
- persists credentials
- decides transitions
- owns success/failure rendering

### Good

A screen that coordinates dumb steps.

---

## 13. Walkthrough — implement a modal flow the Slo way

### Goal

Add a multi-step credential wizard.

### Step 1 — define explicit state

```python
class ScreenState(StrEnum):
    PROVIDER = "provider"
    METHOD = "method"
    API_KEY = "api_key"
    SUCCESS = "success"
```

### Step 2 — create one widget per step

Example files:

```text
src/tui/authentication/widgets/provider_select.py
src/tui/authentication/widgets/method_select.py
src/tui/authentication/widgets/api_key_input.py
src/tui/authentication/widgets/success_widget.py
```

Each widget should:

- render controls
- validate local input
- emit semantic messages

Each widget should not:

- persist credentials
- call network APIs directly
- decide the overall flow

### Step 3 — let the screen own transitions

```python
def _swap_step(self, widget: Widget) -> None:
    container = self.query_one("#auth-step-host")
    container.remove_children()
    container.mount(widget)
```

### Step 4 — react to messages and update state

```python
@on(ProviderSelect.ProviderChosen)
def _on_provider_chosen(self, message: ProviderSelect.ProviderChosen) -> None:
    self._provider = message.provider
    self._state = ScreenState.METHOD
    self._swap_step(MethodSelect(provider=message.provider))
```

### Step 5 — keep persistence and side effects in the screen

```python
def _save_api_key(self, *, api_key: str) -> None:
    credential = CredentialDAO(provider=self._provider, api_key=api_key)
    self._store.save(credential)
    self._state = ScreenState.SUCCESS
    self._swap_step(SuccessWidget())
```

### Step 6 — test the flow one state at a time

- initial provider screen renders
- provider choice opens method step
- API-key submission persists via injected store
- success widget appears
- cancel/back cleans up and dismisses predictably

---

## 14. Background tasks must be tracked and cancelled explicitly

If a task can outlive one handler, store it on `self`.

### Common task slots

- `self._in_flight_task`
- `self._oauth_task`
- `self._spinner_timer`

### Rules

| Rule | Detail |
|---|---|
| store every task handle | no fire-and-forget `create_task(...)` |
| add a cancellation helper | `_cancel_oauth_if_running()` is the model |
| clean up in back/cancel/unmount flows | modal steps and prompt streams must not leak |
| use `finally` | restore UI state even on failure/cancel |

### Bad

```python
asyncio.create_task(self._run_prompt(...))
```

with no stored handle and no cleanup path.

### Good

```python
self._in_flight_task = asyncio.create_task(self._run_prompt(...))
```

plus:

```python
def _cancel_in_flight_if_running(self) -> None:
    if self._in_flight_task is not None:
        self._in_flight_task.cancel()
```

---

## 15. Global keybindings belong on the app or screen

Keep keyboard policy visible.

### Good home

- `BINDINGS`
- `action_interrupt`
- `action_clear`
- `action_quit`

### Why

- one place to audit shortcuts
- easier pilot tests
- explicit conflict handling (`priority=True` where needed)

### Bad

Hiding global behavior in random child widgets unless the shortcut is truly local to that widget.

---

## 16. TCSS should live next to the module it styles

Slo keeps:

- `src/tui/app.tcss`
- `src/tui/authentication/auth_screen.tcss`

### Rules

| Rule | Detail |
|---|---|
| app-level CSS is adjacent to `app.py` | `CSS_PATH = "app.tcss"` |
| screen-level CSS is adjacent to the screen | `auth_screen.py` -> `auth_screen.tcss` |
| class names are semantic | `thinking-spinner`, `auth-title`, `tool-line` |
| prefer theme tokens | `$surface`, `$accent`, `$error`, `$text-muted` |

TCSS should describe layout and look, not business logic.

---

## 17. Detailed testing strategy

### 17.1 App tests

Use `app.run_test()` + pilot to prove:

- prompt submission behavior
- busy-state behavior
- transcript clear behavior
- global bindings (`ctrl+c`, `ctrl+l`, `ctrl+d`)
- spinner mount/unmount lifecycle
- startup modal behavior

### 17.2 Router tests

Test `SlashRouter` without Textual:

- command lookup
- unknown-command fallback
- typed result object fields
- auth/open/clear/exit semantics

### 17.3 Renderer tests

Test `EventRenderer` with fake targets:

- each event kind renders expected content
- class assignment is correct
- final markdown / aborted output branches behave correctly

### 17.4 Screen tests

Drive multi-step flows with pilot:

- initial step
- forward transition
- back transition
- persistence side effect through injected fake store
- cancel/dismiss behavior
- success path

### 17.5 Widget tests

Assert:

- local validation
- emitted semantic messages
- button interactions
- disabled/enabled state logic

### Test seam guidance

If a behavior matters and is hard to assert, create a seam:

- a protocol
- an adapter
- a helper method
- a semantic message

Do **not** default to scraping deep Textual internals.

---

## 18. Anti-patterns

### Anti-pattern 1 — one giant `app.py`

`app.py` should not own:

- slash parsing
- event formatting
- modal step internals
- persistence logic
- background-task cleanup logic for every feature

**Fix:** split into app / router / renderer / screens / widgets.

### Anti-pattern 2 — widgets build domain objects

**Fix:** inject collaborators from the app or screen.

### Anti-pattern 3 — event formatting is hard-coded inline in handlers

**Fix:** move it into `event_renderer.py`.

### Anti-pattern 4 — slash commands parsed inline in submit handlers

**Fix:** route through `SlashRouter`.

### Anti-pattern 5 — multi-step flows hidden inside one widget

**Fix:** use a screen + explicit state + step widgets.

### Anti-pattern 6 — untracked background tasks

**Fix:** store handles and cancel them explicitly.

### Anti-pattern 7 — tests prove behavior by scraping unstable UI internals

**Fix:** add explicit adapters/protocols/messages and assert there.

---

## 19. Implementation checklist

- [ ] sessions/services are injected into the `App`/`Screen`
- [ ] `compose()` builds the tree and keeps typed refs where needed
- [ ] `on_mount()` and `on_unmount()` own setup/cleanup clearly
- [ ] semantic `Message` subclasses exist for real UI events
- [ ] slash commands route through a dedicated router with a typed result object
- [ ] streamed/domain events render through a dedicated renderer
- [ ] protocol/adapter seams exist where Rich/Textual output needs testing
- [ ] semantic classes map to styles in one obvious place
- [ ] transient UI like spinners lives in standalone widget modules
- [ ] modal flows use a screen + explicit state enum + per-step widgets
- [ ] long-lived tasks are stored, cancelled, and cleared explicitly
- [ ] global keybindings live on the app/screen
- [ ] TCSS files sit next to the modules they style
- [ ] pilot-based tests cover interactive behavior
- [ ] code also follows `skills/languages/python/named-arguments-and-type-hints/SKILL.md`, `skills/coding/declarative-method-structure/SKILL.md`, `skills/languages/python/declarative-method-structure/SKILL.md`, and `skills/languages/python/method-docstrings/SKILL.md`

---

## 20. Files to read before making changes

Read these together before implementing a new `src/tui/` feature:

- `src/tui/app.py`
- `src/tui/app.tcss`
- `src/tui/slash_router.py`
- `src/tui/event_renderer.py`
- `src/tui/thinking_spinner.py`
- `src/tui/authentication/auth_screen.py`
- `src/tui/authentication/widgets/*.py`
- `tests/tui/test_app.py`
- `tests/tui/test_event_renderer.py`
- `tests/tui/authentication/...`

If the TUI is launched from a CLI path, also read:

- `src/cli/app.py`
- `src/cli/typer_dispatch.py`

If the TUI renders session-stream events, also read:

- the injected session/facade type
- the tests for that streaming surface
