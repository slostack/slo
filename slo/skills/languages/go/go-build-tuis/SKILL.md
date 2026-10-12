---
name: go-build-tuis
description: "Go scoped recipe (Bubble Tea): Conventions for Go terminal UIs built with bubbletea (Elm\
  \ architecture) + lipgloss styling + bubbles widgets. Separates composition, message interpretation,\
  \ domain interaction, and rendering so the TUI stays testable \u2014 the Go analog of the Textual/Rich\
  \ conventions."
when_to_use: "Only for the named project stack and component. Use when building or reviewing a Go TUI\
  \ \u2014 anything under internal/tui/ using github.com/charmbracelet/bubbletea. Read before adding a\
  \ Model, wiring key/mouse messages, turning async domain calls into tea.Cmd, or composing sub-models."
group: languages
kind: skill
---

# Build Go TUIs

## Skill summary

- **Name:** `go-build-tuis`
- **Description:** Conventions for Go terminal UIs built with **bubbletea** (Elm
  architecture: `Model` / `Init` / `Update` / `View`), **lipgloss** for styling, and
  **bubbles** for reusable widgets (textinput, viewport, spinner, list). Keeps
  composition, message interpretation, domain interaction, and rendering separated so
  the TUI stays testable.
- **When to use:** Building or reviewing a Go TUI (`internal/tui/`). Read before
  adding a model, routing key/mouse messages, turning async domain calls into
  `tea.Cmd`, or composing sub-models.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Build a bubbletea TUI for browsing runs."
- "Add a slash-command palette to the TUI."
- "How do I make an async API call from Update without blocking?"
- "Wire a multi-step auth wizard as bubbletea sub-models."
- "Review this bubbletea Update method for convention violations."
- "How should key bindings route in our Go TUI?"
- "Turn this streaming session into tea.Msg events on the transcript."

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

This is the Go equivalent of the Textual/Rich TUI conventions. Textual is
object-oriented and event-driven (widgets post `Message` objects, `@on` handlers
mutate widget state). Bubbletea is the **Elm architecture**: a single immutable-ish
`Model`, a pure `Update(msg) (Model, Cmd)` that folds messages into new state, and a
pure `View() string` that renders state. The mapping is exact once you name it:

| Textual concept | Bubbletea equivalent |
|---|---|
| `App`/`Screen` subclass + widget attrs | a `Model` struct holding state + sub-models |
| `compose()` (build tree) | struct construction in a `New(...)` constructor |
| `on_mount()` (activation) | `Init() tea.Cmd` returns startup commands |
| widget `Message` subclass | a named `tea.Msg` type (a struct) |
| `@on(...)` handler mutating state | a `case` in the `Update` type switch |
| slash router / event renderer helper | plain packages called from `Update`/`View` |
| async `create_task` + streamed events | `tea.Cmd` returning `tea.Msg` (see §7) |
| TCSS style classes | `lipgloss.Style` values in a style table |
| `run_test()` + pilot | direct `Update(msg)` calls + `teatest` |

The four concerns the Textual doc demanded stay separated remain the spine here:

1. **UI composition** — the model struct + `New()` + `View()` layout.
2. **Message interpretation** — the `Update` type switch (key/mouse/domain msgs).
3. **Domain interaction** — session/service calls, wrapped as `tea.Cmd`.
4. **Rendering** — lipgloss styles + a renderer package that maps events to strings.

When these collapse into one 800-line `Update`, the TUI becomes impossible to reason
about. Keep them apart.

> Defer to `go-conventions` for all naming, godoc, declarative structure,
> ubiquitous-language, and error-wrapping rules. This skill only adds the
> TUI-specific layering. Cross-reference `go-recipe-cli-configuration` for the entrypoint
> that launches the TUI.

---

## 1. Golden architecture

```text
New(deps...)                       // composition: build model + sub-models
-> Init() tea.Cmd                  // activation: kick off startup commands
-> tea.KeyMsg / tea.MouseMsg / domainMsg
-> Update(msg)                     // interpretation: type switch, one case each
-> router/helper (slash router, event renderer)
-> tea.Cmd  ── (goroutine) ──▶ session/service method
                                        │
                                        ▼ returns a tea.Msg
-> Update(resultMsg)               // fold result into state
-> View()                          // rendering: lipgloss styles → string
```

### Responsibility map

| Layer | Canonical files | Responsibility |
|---|---|---|
| App shell | `internal/tui/app/model.go` | root `Model`, `Init`, `Update` dispatch, `View` layout |
| Sub-models | `internal/tui/<feature>/model.go` | one focused Elm model per screen/panel |
| Reusable widgets | `internal/tui/widgets/*.go` | spinner, prompt input — local state + `Update`/`View` |
| Messages | `internal/tui/msg/msg.go` | named `tea.Msg` types (the semantic events) |
| Commands | `internal/tui/cmd/cmd.go` | `tea.Cmd` factories wrapping domain calls |
| Slash router | `internal/tui/slashrouter/router.go` | parse a line → typed result struct |
| Event renderer | `internal/tui/renderer/renderer.go` | domain event → rendered string(s) |
| Styles | `internal/tui/style/style.go` | semantic name → `lipgloss.Style` table |

### The rule of thumb

- **`New`/`View`** decide *what UI pieces exist and where they sit*.
- **messages** name *what happened* (`PromptSubmittedMsg`, `ProviderChosenMsg`).
- **`Update`** decides *what each message means* (one `case` per message type).
- **commands** do *real work* off the render loop.
- **renderer + styles** show *results back to the user*.

---

## 2. Canonical folder layout

```text
internal/tui/
├── app/
│   ├── model.go          # root Model, Init, Update, View
│   └── keys.go           # key.Binding set (global keymap)
├── msg/
│   └── msg.go            # named tea.Msg types
├── cmd/
│   └── cmd.go            # tea.Cmd factories (domain calls → tea.Msg)
├── slashrouter/
│   ├── router.go
│   └── router_test.go
├── renderer/
│   ├── renderer.go
│   └── renderer_test.go
├── style/
│   └── style.go          # lipgloss styles keyed by semantic name
├── widgets/
│   ├── spinner.go
│   └── promptinput.go
└── auth/                 # a multi-step feature
    ├── model.go          # screen-level orchestrator sub-model
    ├── state.go          # step enum
    └── widgets/
        ├── providerselect.go
        ├── methodselect.go
        └── apikeyinput.go

# tests live beside sources as _test.go (see go-conventions)
```

### Rules

| Rule | Detail |
|---|---|
| one focused model per file | a screen/panel is its own `Model` with its own `Update`/`View` |
| messages live in one package | `msg` is shared TUI vocabulary; import it everywhere |
| commands live in one package | domain calls become `tea.Cmd` in `cmd`, not inline in `Update` |
| router & renderer are plain packages | no bubbletea import needed → unit-testable |
| tests mirror source | `router_test.go` next to `router.go`, table-driven |

---

## 3. Inject sessions and services — never build them inside a model

The Go analog of "inject collaborators into the App" is **constructor injection**
(`go-conventions`). The root model receives a pre-built session; it
never dials clients or opens stores itself.

### Bad

```go
// Model builds its own dependencies — untestable, tangles setup with UI state.
func New() Model {
    client := realclient.New(os.Getenv("API_URL"))
    return Model{session: session.New(client)}
}
```

### Good

```go
// agentSession is the consumer-local interface the TUI actually needs.
// Defined at the consumer, per go-conventions.
type agentSession interface {
    // Prompt streams assistant events for a user prompt over ch until closed.
    Prompt(ctx context.Context, text string, ch chan<- msg.StreamEvent) error
    Reset(ctx context.Context) error
}

// New builds the root model with injected collaborators.
//
// The caller (the CLI command, per go-recipe-cli-configuration) owns object-graph setup and
// passes a ready session, store, and spinner in.
type DependenciesDAO struct {
    Session agentSession
    Store CredentialStore
}

func New(in DependenciesDAO) Model {
    session, store := in.Session, in.Store
    return Model{
        session:  session,
        store:    store,
        prompt:   widgets.NewPromptInput(),
        viewport: viewport.New(0, 0),
        keys:     defaultKeyMap(),
        styles:   style.Default(),
    }
}
```

Allowed injection targets mirror the source: session facades, service objects,
credential stores, OAuth/browser factories, filesystem adapters, and small
interface-typed collaborators used only for rendering or testing.

---

## 4. `New`/`View` build structure; `Init` wires startup behavior

Textual split `compose()` (structure) from `on_mount()` (activation). Bubbletea
splits the **constructor + `View`** (structure) from **`Init`** (activation).

- **`New(...)`** instantiates sub-models and stores typed refs. No I/O.
- **`View()`** composes those pieces into a layout with lipgloss. Pure, no side
  effects, no state mutation.
- **`Init() tea.Cmd`** returns the commands to run at startup — subscribe to a
  stream, focus the input, load initial data. It is the only "activation" hook.

Bubbletea has no `on_unmount`; cleanup happens by **cancelling the `context.Context`
you own** (see §7) and letting `tea.Quit` tear the program down.

```go
// Model holds all TUI state and typed refs to sub-models.
type Model struct {
    session  agentSession
    store    CredentialStore
    prompt   widgets.PromptInput   // typed ref, like self._input
    viewport viewport.Model        // scrollable transcript, like RichLog
    spinner  widgets.Spinner
    keys     keyMap
    styles   style.Styles
    lines    []string              // rendered transcript lines
    busy     bool
    width    int
    height   int
}

// Init returns startup commands: blink the input cursor and focus it.
func (m Model) Init() tea.Cmd {
    return tea.Batch(
        m.prompt.Focus(),
        m.spinner.Tick,
    )
}

// View renders the full frame. Pure — no mutation, no I/O.
func (m Model) View() string {
    header := m.styles.Header.Render("agent")
    body := m.viewport.View()
    footer := m.footerView()
    return lipgloss.JoinVertical(lipgloss.Left, header, body, m.prompt.View(), footer)
}
```

### Review rules

| Rule | Detail |
|---|---|
| the layout should read in one place | `View` joins named pieces; don't scatter it across 10 helpers |
| store typed refs deliberately | `m.prompt`, `m.viewport`, `m.spinner` — not `any` grab-bags |
| `Init` stays flat | batch a few startup commands; no branching logic |
| `View` is pure | never mutate `m` or call the session inside `View` |

---

## 5. Define named `tea.Msg` types for real UI events

Textual defined semantic `Message` subclasses instead of leaning on low-level key
events. The bubbletea equivalent is a **named struct message type per real event**.
Raw `tea.KeyMsg` is the low-level input; you translate it into a semantic message so
`Update` reads like intent, not like DOM scraping.

### Bad — interpreting raw keys everywhere, business meaning inlined

```go
func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    if k, ok := msg.(tea.KeyMsg); ok {
        if k.String() == "enter" && strings.HasPrefix(m.prompt.Value(), "/") {
            // slash parsing crammed into the key handler — brittle
        }
    }
    return m, nil
}
```

### Good — named semantic messages in `internal/tui/msg`

```go
// Package msg defines the semantic message vocabulary of the TUI.
// Each type is a tea.Msg (any value is a tea.Msg; these give it a name).
package msg

// PromptSubmittedMsg is emitted when the user submits a prompt line.
type PromptSubmittedMsg struct {
    Text string
}

// ProviderChosenMsg is emitted when the user selects an auth provider.
type ProviderChosenMsg struct {
    Provider string
}

// StreamEvent is one streamed domain event forwarded to the transcript.
type StreamEvent struct {
    Kind     string // "tool_started", "tool_result", "assistant_final", ...
    ToolName string
    Text     string
}

// StreamDoneMsg signals the current prompt stream finished.
type StreamDoneMsg struct{ Err error }
```

A sub-model emits a semantic message by returning a command that yields it:

```go
// submitCmd wraps the current input value in a PromptSubmittedMsg.
func submitCmd(text string) tea.Cmd {
    return func() tea.Msg { return msg.PromptSubmittedMsg{Text: text} }
}
```

Now the root `Update` reads as intent — one case per semantic event:

```go
func (m Model) Update(message tea.Msg) (tea.Model, tea.Cmd) {
    switch t := message.(type) {
    case msg.PromptSubmittedMsg:
        return m.onPromptSubmitted(t)
    case msg.ProviderChosenMsg:
        return m.onProviderChosen(t)
    case msg.StreamEvent:
        return m.onStreamEvent(t)
    case msg.StreamDoneMsg:
        return m.onStreamDone(t)
    }
    return m, nil
}
```

Each `onX` is a small, single-decision method (`go-conventions`) that
returns `(tea.Model, tea.Cmd)` — the Elm equivalent of a Textual `@on` handler.

---

## 6. Route key and mouse messages through a keymap, not string literals

Keep keyboard policy visible and in one place — the analog of Textual's `BINDINGS`.
Use `github.com/charmbracelet/bubbles/key` so bindings are declarative and
self-documenting (help text included).

```go
// internal/tui/app/keys.go

// keyMap is the global key policy. Defined once so shortcuts are auditable.
type keyMap struct {
    Submit    key.Binding
    Clear     key.Binding
    Interrupt key.Binding
    Quit      key.Binding
}

func defaultKeyMap() keyMap {
    return keyMap{
        Submit:    key.NewBinding(key.WithKeys("enter"), key.WithHelp("enter", "submit")),
        Clear:     key.NewBinding(key.WithKeys("ctrl+l"), key.WithHelp("ctrl+l", "clear")),
        Interrupt: key.NewBinding(key.WithKeys("ctrl+c"), key.WithHelp("ctrl+c", "interrupt")),
        Quit:      key.NewBinding(key.WithKeys("ctrl+d"), key.WithHelp("ctrl+d", "quit")),
    }
}
```

`Update` interprets keys via the keymap and translates them into semantic messages or
commands — it does not embed behavior in string comparisons:

```go
// handleKey maps a raw key press to a semantic action. One decision per branch.
func (m Model) handleKey(k tea.KeyMsg) (tea.Model, tea.Cmd) {
    switch {
    case key.Matches(k, m.keys.Quit):
        return m, tea.Quit
    case key.Matches(k, m.keys.Interrupt):
        return m.cancelInFlight()          // §7 — cancel, don't fire-and-forget
    case key.Matches(k, m.keys.Clear):
        return m.clearTranscript()
    case key.Matches(k, m.keys.Submit):
        text := m.prompt.Value()
        m.prompt.Reset()
        return m, submitCmd(text)          // §5 — emit a semantic message
    }

    // Otherwise it's ordinary text input — delegate to the sub-model.
    var cmd tea.Cmd
    m.prompt, cmd = m.prompt.Update(k)
    return m, cmd
}
```

Mouse messages (`tea.MouseMsg`, enabled via `tea.WithMouseCellMotion()`) route the
same way: match in `Update`, translate to a semantic action, delegate to the relevant
sub-model. Global policy lives on the root model; a shortcut lives on a sub-model only
when it is genuinely local to that widget.

---

## 7. Async domain calls become `tea.Cmd` → `tea.Msg` — never block `Update`

This is the single most important Go-specific rule. **`Update` and `View` run on the
render loop and must never block.** The Textual pattern was "store the `asyncio.Task`
on `self`, cancel it explicitly, clean up in `finally`." The bubbletea pattern is:

- A **`tea.Cmd`** is `func() tea.Msg`. Bubbletea runs it in its own goroutine.
- The command does the blocking domain work and returns a **result `tea.Msg`**.
- `Update` receives that message later and folds the result into state.
- For **streaming**, a command reads one item off a channel and returns a message;
  you re-issue the command to pull the next item, until a done sentinel arrives.
- To cancel (the interrupt key, or quitting), **cancel the `context.Context`** the
  command captured. Store the `cancel` func on the model — this is the Go analog of
  storing the task handle.

### One-shot async call

```go
// internal/tui/cmd/cmd.go

// ResetSession issues a session reset off the render loop.
//
// It returns a msg.StreamDoneMsg carrying any error so Update can restore UI state.
func ResetSession(ctx context.Context, session agentSession) tea.Cmd {
    return func() tea.Msg {
        if err := session.Reset(ctx); err != nil {
            return msg.StreamDoneMsg{Err: fmt.Errorf("resetting session: %w", err)}
        }
        return msg.StreamDoneMsg{}
    }
}
```

### Streaming a domain session onto the transcript

```go
// StartPrompt begins streaming assistant events for text.
//
// It spawns the session in a goroutine (owned by the returned context's cancel),
// then returns a command that pulls the first event. Cancel via the returned func
// to interrupt — the analog of _cancel_in_flight_if_running.
func StartPrompt(parent context.Context, session agentSession, text string) (tea.Cmd, context.CancelFunc) {
    ctx, cancel := context.WithCancel(parent)
    ch := make(chan msg.StreamEvent)

    go func() {
        defer close(ch)
        // Session error is delivered as the stream's done sentinel below.
        _ = session.Prompt(ctx, text, ch)
    }()

    return WaitForEvent(ch), cancel
}

// WaitForEvent pulls one event off ch. When ch closes it yields StreamDoneMsg.
// The recipient re-issues this command to pull the next event.
func WaitForEvent(ch <-chan msg.StreamEvent) tea.Cmd {
    return func() tea.Msg {
        ev, ok := <-ch
        if !ok {
            return msg.StreamDoneMsg{}
        }
        return ev
    }
}
```

The root model stores the cancel func (the task-handle analog) and re-pumps the
stream on each event:

```go
type Model struct {
    // ...
    cancelPrompt context.CancelFunc     // nil when idle; set while a prompt streams
    streamCh     <-chan msg.StreamEvent
}

// onPromptSubmitted starts a streaming prompt and enters the busy state.
func (m Model) onPromptSubmitted(t msg.PromptSubmittedMsg) (tea.Model, tea.Cmd) {
    if m.busy {
        return m, nil // guard: one prompt at a time
    }
    streamCmd, cancel := cmd.StartPrompt(context.Background(), m.session, t.Text)
    m.busy = true
    m.cancelPrompt = cancel
    return m, tea.Batch(streamCmd, m.spinner.Tick)
}

// onStreamEvent renders one event and re-issues the pull command.
func (m Model) onStreamEvent(ev msg.StreamEvent) (tea.Model, tea.Cmd) {
    m.appendLine(renderer.Render(ev, m.styles)) // §8 — renderer decides formatting
    return m, cmd.WaitForEvent(m.streamCh)       // pump the next event
}

// onStreamDone leaves the busy state and clears the cancel handle.
func (m Model) onStreamDone(t msg.StreamDoneMsg) (tea.Model, tea.Cmd) {
    if t.Err != nil {
        m.appendLine(m.styles.Error.Render(t.Err.Error()))
    }
    m.busy = false
    m.cancelPrompt = nil
    return m, nil
}

// cancelInFlight interrupts a running prompt. The analog of an explicit task cancel.
func (m Model) cancelInFlight() (tea.Model, tea.Cmd) {
    if m.cancelPrompt != nil {
        m.cancelPrompt()
        m.cancelPrompt = nil
        m.busy = false
    }
    return m, nil
}
```

### Rules

| Rule | Detail |
|---|---|
| never call the session directly in `Update`/`View` | wrap it in a `tea.Cmd`; block only inside the command goroutine |
| store the `cancel` on the model | it is the Go equivalent of storing the task handle |
| cancel on interrupt/quit | `cancelInFlight()` before `tea.Quit`; leaked goroutines are a bug |
| re-pump streams via a command | `WaitForEvent` returns one msg, then is re-issued |
| errors travel as messages | domain errors become `StreamDoneMsg{Err: ...}`, wrapped with `%w` |

---

## 8. Render domain events through a dedicated renderer + a style table

Textual split an `EventRenderer` from the app and a semantic-class → style map. Both
carry straight across: put event-formatting logic in a **renderer package with no
bubbletea import**, and put the semantic-name → `lipgloss.Style` mapping in **one
table**.

### Style table — semantic names in one place

```go
// Package style centralizes lipgloss styles keyed by semantic name,
// the analog of the semantic-class → TCSS mapping.
package style

// Styles is the resolved style set for the TUI.
type Styles struct {
    Header    lipgloss.Style
    UserLine  lipgloss.Style
    ToolLine  lipgloss.Style
    ToolRes   lipgloss.Style
    Assistant lipgloss.Style
    Error     lipgloss.Style
}

// Default returns the default style set. Prefer adaptive colors so the TUI
// reads on light and dark terminals — the theme-token analog.
func Default() Styles {
    accent := lipgloss.AdaptiveColor{Light: "#005f87", Dark: "#5fd7ff"}
    muted := lipgloss.AdaptiveColor{Light: "#6c6c6c", Dark: "#8a8a8a"}
    return Styles{
        Header:    lipgloss.NewStyle().Bold(true).Foreground(accent),
        UserLine:  lipgloss.NewStyle().Bold(true),
        ToolLine:  lipgloss.NewStyle().Foreground(accent),
        ToolRes:   lipgloss.NewStyle().Foreground(muted),
        Assistant: lipgloss.NewStyle(),
        Error:     lipgloss.NewStyle().Italic(true).Foreground(lipgloss.Color("9")),
    }
}
```

### Renderer — event kind → rendered string, no TUI framework needed

```go
// Package renderer turns domain stream events into rendered transcript lines.
// It imports lipgloss but NOT bubbletea, so it is unit-testable in isolation.
package renderer

// renderers maps an event kind to its formatter — the registry pattern from
// go-conventions, replacing a long switch. Add a kind = one entry.
var renderers = map[string]func(msg.StreamEvent, style.Styles) string{
    "tool_started":    renderToolStarted,
    "tool_result":     renderToolResult,
    "assistant_final": renderAssistantFinal,
}

// Render formats one stream event into a styled line.
//
// Unknown kinds render as plain text so a new event type never crashes the UI.
func Render(ev msg.StreamEvent, styles style.Styles) string {
    render, ok := renderers[ev.Kind]
    if !ok {
        return ev.Text
    }
    return render(ev, styles)
}

func renderToolStarted(ev msg.StreamEvent, s style.Styles) string {
    return s.ToolLine.Render("Running tool: " + ev.ToolName)
}
```

Because the renderer takes plain values and returns a string, tests need no terminal:

```go
func TestRenderToolStarted(t *testing.T) {
    got := renderer.Render(
        msg.StreamEvent{Kind: "tool_started", ToolName: "grep"},
        style.Styles{ToolLine: lipgloss.NewStyle()}, // no color → assert plain text
    )
    assert.Equal(t, "Running tool: grep", got)
}
```

### Rules

| Rule | Detail |
|---|---|
| renderer imports lipgloss, not bubbletea | formatting stays testable without a program |
| one style table | `style.Styles` — never scatter `lipgloss.NewStyle()` through `Update` |
| use a kind→func registry | adding an event type is one map entry, no `Update` edit |
| unknown kinds degrade gracefully | render plain text, never panic |

---

## 9. Route slash commands through a dedicated router with a typed result

Do not parse `/help`, `/clear`, `/auth` inline in `onPromptSubmitted`. Route through
a plain `slashrouter` package that returns a **typed result struct**, so `Update`
applies the result declaratively (the Textual `SlashCommandResultDAO` analog).

```go
// Package slashrouter parses slash-command lines into typed results.
// No bubbletea import → fully unit-testable.
package slashrouter

// Result is the typed outcome of dispatching a slash command.
type Result struct {
    Rendered      string // text to append to the transcript, if any
    ShouldClear   bool
    ShouldExit    bool
    OpenAuthModal bool
}

// handlers maps a command to its handler — registry pattern, not an if/else ladder.
var handlers = map[string]func() Result{
    "/help":  handleHelp,
    "/clear": handleClear,
    "/auth":  handleAuth,
}

// Dispatch parses line and returns the matching command's Result.
//
// Returns ok=false when line is not a recognized slash command, so the caller can
// treat it as an ordinary prompt.
func Dispatch(line string) (Result, bool) {
    fields := strings.Fields(line)
    if len(fields) == 0 || !strings.HasPrefix(fields[0], "/") {
        return Result{}, false
    }
    handle, ok := handlers[fields[0]]
    if !ok {
        return Result{Rendered: "Unknown command: " + fields[0]}, true
    }
    return handle(), true
}

func handleClear() Result { return Result{Rendered: "Cleared transcript.", ShouldClear: true} }
```

`Update` applies the result without branching endlessly:

```go
// onPromptSubmitted routes slash commands, else starts a prompt stream.
func (m Model) onPromptSubmitted(t msg.PromptSubmittedMsg) (tea.Model, tea.Cmd) {
    result, isSlash := slashrouter.Dispatch(t.Text)
    if !isSlash {
        return m.startPrompt(t.Text)
    }
    if result.ShouldExit {
        return m, tea.Quit
    }
    if result.ShouldClear {
        m.lines = nil
    }
    if result.Rendered != "" {
        m.appendLine(m.styles.Assistant.Render(result.Rendered))
    }
    return m, nil
}
```

The router is table-driven-testable with no terminal (`go-conventions`):

```go
func TestDispatch(t *testing.T) {
    tests := []struct {
        name        string
        line        string
        wantClear   bool
        wantRender  string
        wantIsSlash bool
    }{
        {name: "clear sets ShouldClear", line: "/clear", wantClear: true, wantRender: "Cleared transcript.", wantIsSlash: true},
        {name: "unknown command reports back", line: "/nope", wantRender: "Unknown command: /nope", wantIsSlash: true},
        {name: "plain text is not a slash command", line: "hello", wantIsSlash: false},
    }
    for _, tc := range tests {
        t.Run(tc.name, func(t *testing.T) {
            got, isSlash := slashrouter.Dispatch(tc.line)
            assert.Equal(t, tc.wantIsSlash, isSlash)
            assert.Equal(t, tc.wantClear, got.ShouldClear)
            assert.Equal(t, tc.wantRender, got.Rendered)
        })
    }
}
```

---

## 10. Sub-models compose; the parent delegates in `Update` and `View`

Reusable widgets and screens are their own `Model`s satisfying the bubbletea contract
(`Init`/`Update`/`View`, or at least `Update`/`View`). The parent embeds them, routes
messages into them in `Update`, and composes their `View` output. This is how the
Textual "one widget per file, app owns the tree" rule survives in Go.

### A reusable widget as a sub-model

```go
// internal/tui/widgets/promptinput.go

// PromptInput is a single-line prompt built on the bubbles textinput widget.
type PromptInput struct {
    input textinput.Model
}

// NewPromptInput builds a focused prompt input.
func NewPromptInput() PromptInput {
    ti := textinput.New()
    ti.Placeholder = "type a message…"
    return PromptInput{input: ti}
}

// Update folds a message into the input and returns the updated widget.
func (p PromptInput) Update(m tea.Msg) (PromptInput, tea.Cmd) {
    var cmd tea.Cmd
    p.input, cmd = p.input.Update(m)
    return p, cmd
}

// View renders the prompt line.
func (p PromptInput) View() string { return p.input.View() }

// Value returns the current text. Reset clears it. Focus focuses the field.
func (p PromptInput) Value() string  { return p.input.Value() }
func (p *PromptInput) Reset()        { p.input.Reset() }
func (p PromptInput) Focus() tea.Cmd { return p.input.Focus() }
```

### The parent delegates

The critical Elm idiom: `sub, cmd = sub.Update(msg)` — reassign the returned sub-model
(bubbles models are value types), collect the command, and batch them.

```go
// Update delegates to sub-models and collects their commands.
func (m Model) Update(message tea.Msg) (tea.Model, tea.Cmd) {
    var cmds []tea.Cmd

    switch t := message.(type) {
    case tea.WindowSizeMsg:
        m.width, m.height = t.Width, t.Height
        m.viewport.Width, m.viewport.Height = t.Width, t.Height-verticalChrome
        return m, nil
    case tea.KeyMsg:
        return m.handleKey(t)             // §6
    case msg.PromptSubmittedMsg:
        return m.onPromptSubmitted(t)     // §9
    case msg.StreamEvent:
        return m.onStreamEvent(t)         // §7/§8
    case msg.StreamDoneMsg:
        return m.onStreamDone(t)          // §7
    }

    // Always drive the spinner sub-model so its animation ticks continue.
    var cmd tea.Cmd
    m.spinner, cmd = m.spinner.Update(message)
    cmds = append(cmds, cmd)
    return m, tea.Batch(cmds...)
}
```

### Multi-step modal flows: a screen sub-model + a step enum + per-step widgets

The Textual auth-wizard pattern maps to a parent sub-model holding a **step enum**,
one dumb widget per step, and explicit transitions in `Update`. The screen owns
persistence and side effects; step widgets only render and emit semantic messages.

```go
// internal/tui/auth/state.go

// Step names the current position in the credential wizard.
type Step int

const (
    StepProvider Step = iota
    StepMethod
    StepAPIKey
    StepSuccess
)
```

```go
// internal/tui/auth/model.go

// Model orchestrates the multi-step credential flow. It owns transitions,
// persistence, and dismissal; the step widgets stay dumb.
type Model struct {
    step     Step
    provider string
    store    CredentialStore // injected, per §3
    // one field per step widget…
}

// Update advances the flow on semantic messages. One case per transition.
func (m Model) Update(message tea.Msg) (Model, tea.Cmd) {
    switch t := message.(type) {
    case msg.ProviderChosenMsg:
        m.provider = t.Provider
        m.step = StepMethod           // explicit transition, like _swap_step
        return m, nil
    case msg.APIKeySubmittedMsg:
        return m.saveAPIKey(t.APIKey) // persistence/side effects stay at screen level
    }
    return m, nil
}

// saveAPIKey persists the credential and advances to the success step.
func (m Model) saveAPIKey(apiKey string) (Model, tea.Cmd) {
    cred := Credential{Provider: m.provider, APIKey: apiKey}
    return m, func() tea.Msg {
        if err := m.store.Save(cred); err != nil {
            return msg.StreamDoneMsg{Err: fmt.Errorf("saving credential: %w", err)}
        }
        return msg.CredentialSavedMsg{}
    }
}

// View renders the widget for the current step only.
func (m Model) View() string {
    switch m.step {
    case StepProvider:
        return m.providerView()
    case StepMethod:
        return m.methodView()
    case StepAPIKey:
        return m.apiKeyView()
    default:
        return m.successView()
    }
}
```

Each step widget renders controls, validates local input, and emits a semantic
message (`ProviderChosenMsg`, `APIKeySubmittedMsg`). It does **not** persist
credentials, call the network, or decide the flow — exactly the Textual split.

---

## 11. Wiring the program (and the CLI entrypoint)

The cobra command owns object-graph setup and launches the program. Enable mouse and
alt-screen at construction. See `go-recipe-cli-configuration` for the command scaffolding.

```go
// RunTUI builds the root model with real dependencies and runs the program.
func RunTUI(ctx context.Context, session agentSession, store CredentialStore) error {
    model := app.New(app.DependenciesDAO{Session: session, Store: store})
    program := tea.NewProgram(
        model,
        tea.WithAltScreen(),
        tea.WithMouseCellMotion(),
        tea.WithContext(ctx), // program stops when ctx is cancelled
    )
    if _, err := program.Run(); err != nil {
        return fmt.Errorf("running TUI: %w", err)
    }
    return nil
}
```

---

## 12. Testing strategy

Bubbletea's Elm shape makes most tests plain function calls — no terminal needed.
Use `github.com/charmbracelet/x/exp/teatest` only when you must drive a full program.

### 12.1 Update tests (the bulk) — call `Update` directly

`Update` is `(tea.Msg) → (tea.Model, tea.Cmd)`, a pure fold. Feed a message, assert
the new state. This is the Go analog of pilot key-driving, but simpler and faster.

```go
func TestUpdatePromptSubmittedEntersBusy(t *testing.T) {
    m := app.New(app.DependenciesDAO{Session: fakeSession{}, Store: fakeStore{}})
    next, cmd := m.Update(msg.PromptSubmittedMsg{Text: "hello"})

    assert.True(t, next.(app.Model).Busy())
    assert.NotNil(t, cmd) // a stream command was issued
}

func TestUpdateStreamDoneLeavesBusy(t *testing.T) {
    m := app.New(app.DependenciesDAO{Session: fakeSession{}, Store: fakeStore{}}).WithBusy(true)
    next, _ := m.Update(msg.StreamDoneMsg{})
    assert.False(t, next.(app.Model).Busy())
}
```

### 12.2 Router tests — table-driven, no framework (see §9).
### 12.3 Renderer tests — plain values in, string out, no terminal (see §8).

### 12.4 Command tests — assert the returned message

A `tea.Cmd` is just `func() tea.Msg`. Call it and assert what it yields.

```go
func TestResetSessionYieldsDone(t *testing.T) {
    c := cmd.ResetSession(context.Background(), fakeSession{})
    got := c() // execute the command in-line
    assert.Equal(t, msg.StreamDoneMsg{}, got)
}
```

### 12.5 Full-program tests — `teatest`, sparingly

Drive keystrokes and assert on final output only for end-to-end confidence:

```go
func TestClearCommandClearsTranscript(t *testing.T) {
    tm := teatest.NewTestModel(t, app.New(app.DependenciesDAO{Session: fakeSession{}, Store: fakeStore{}}))
    tm.Type("/clear")
    tm.Send(tea.KeyMsg{Type: tea.KeyEnter})
    tm.Send(tea.QuitMsg{})

    out, _ := io.ReadAll(tm.FinalOutput(t))
    assert.Contains(t, string(out), "Cleared transcript.")
}
```

### Test seam guidance

If a behavior matters and is hard to assert, add a seam — a semantic message type, a
renderer function, an interface, or an exported accessor — rather than scraping
rendered ANSI output. Do not default to string-matching styled terminal frames.

---

## 13. Anti-patterns

| # | Anti-pattern | Fix |
|---|---|---|
| 1 | one giant `Update` owning parsing, formatting, persistence, streaming | split into `handleKey`, per-message `onX` methods, router, renderer, sub-models |
| 2 | a model dials clients / opens stores in `New` | inject collaborators (§3) |
| 3 | calling the session directly in `Update`/`View` (blocks the loop) | wrap in a `tea.Cmd` returning a `tea.Msg` (§7) |
| 4 | fire-and-forget goroutine with no `cancel` stored | store the `context.CancelFunc` on the model; cancel on interrupt/quit (§7) |
| 5 | slash commands parsed inline with `strings.HasPrefix` ladders | route through `slashrouter` with a typed `Result` (§9) |
| 6 | `lipgloss.NewStyle()` scattered through handlers | one `style.Styles` table (§8) |
| 7 | event formatting hard-coded in `Update` | move to the `renderer` package (§8) |
| 8 | interpreting raw key strings for business meaning | translate to semantic `tea.Msg` types via a keymap (§5, §6) |
| 9 | a multi-step flow crammed into one widget | screen sub-model + step enum + per-step widgets (§10) |
| 10 | ignoring the `tea.Cmd` returned by `sub.Update(...)` | reassign the sub-model and batch its command |
| 11 | mutating `m` or doing I/O inside `View` | `View` is pure — mutate only in `Update`, do I/O only in commands |
| 12 | tests scraping ANSI frames | add a message/renderer/interface seam and assert there (§12) |

---

## 14. Checklist

Run through before merging a Go TUI change. Each unchecked item is a blocker.

- [ ] Sessions/services/stores are **injected** into the model (`New(...)`), never built inside it.
- [ ] `New`/`View` build structure; `Init` returns startup commands; `View` is pure.
- [ ] Real UI events have **named `tea.Msg` types** in `internal/tui/msg`.
- [ ] `Update` is a **type switch dispatching to small `onX` methods** — one decision each.
- [ ] Key/mouse handling goes through a **`key.Binding` keymap**, not string literals.
- [ ] Async/domain calls are **`tea.Cmd`s that return `tea.Msg`s** — `Update`/`View` never block.
- [ ] Long-lived work stores a **`context.CancelFunc`** on the model and is cancelled on interrupt/quit.
- [ ] Streaming re-pumps via a **`WaitForEvent`-style command** until a done sentinel.
- [ ] Slash commands route through a **`slashrouter` with a typed `Result`** struct.
- [ ] Event formatting lives in a **`renderer` package** (imports lipgloss, not bubbletea).
- [ ] Semantic name → style mapping lives in **one `style.Styles` table** with adaptive colors.
- [ ] Reusable widgets and screens are **sub-models**; the parent delegates in `Update`/`View`.
- [ ] Multi-step flows use a **screen sub-model + step enum + per-step widgets**; side effects at screen level.
- [ ] `Update`/router/renderer/command tests exist; `teatest` used only for end-to-end.
- [ ] Code also follows **`go-conventions`** (named struct fields, godoc, declarative structure, `%w` wrapping, `ctx` first).
- [ ] The TUI is launched from a CLI entrypoint per **`go-recipe-cli-configuration`**.
