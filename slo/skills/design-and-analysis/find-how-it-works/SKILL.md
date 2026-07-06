---
name: find-how-it-works
description: Tracing a feature end-to-end through an unfamiliar codebase with a structured,
  developer-readable output format, framework-specific walkthroughs, and optional
  ASCII graphs for interactive sessions.
when_to_use: Use when you need to trace an unfamiliar feature end-to-end through the
  codebase before changing it.
group: design-and-analysis
kind: skill
source_prompt: analyze/find-how-it-works.md
---

# Find How Something Works

## Skill summary

- **Name:** `find-how-it-works`
- **Description:** Tracing a feature end-to-end through an unfamiliar codebase with a structured, developer-readable output format, framework-specific walkthroughs, and optional ASCII graphs for interactive sessions.
- **When to use:** Use when you need to trace an unfamiliar feature end-to-end through the codebase before changing it.
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Source prompt:** `analyze/find-how-it-works.md`

## Examples

- The user asks for help with: Tracing a feature end-to-end through an unfamiliar codebase with a structured, developer-readable output format, framework-specific walkthroughs, and optional ASCII graphs for interactive sessions.
- Use when you need to trace an unfamiliar feature end-to-end through the codebase before changing it.

## Guidance

Use this workflow when the task is **understanding an existing feature before changing it**.

The output must be a **structured control-flow explanation** with named files, symbols, payload handoffs, side effects, and change-surface notes.

The goal is to answer:

1. **Where does this feature start?**
2. **What exact path does control follow?**
3. **What data/state is handed from one layer to the next?**
4. **What side effects happen along the way?**
5. **Which files must be read before changing it safely?**

Do **not** give vague summaries like "it starts in the router and updates the DB."

---

## 1. First classify the entry surface

Before opening files, decide which kind of feature you are tracing.
Different entry surfaces require different tracing styles.

| Surface | Typical entry files | Primary tools/frameworks |
|---|---|---|
| **FastAPI / backend HTTP** | `src/routers/`, `src/main.py`, `src/web_app.py` | FastAPI |
| **Background worker / workflow** | `src/tasks/`, `src/tasks/dbos_workers/`, `src/events/` | Celery, DBOS, event handlers |
| **Operator CLI** | `deployment/cli/`, `verifier/cli/`, Makefiles | Typer, Rich, HTTP control-plane routers |
| **User-facing app CLI** | `src/cli/` | Typer, Rich, sometimes launching a TUI |
| **Textual TUI** | `src/tui/` | Textual, Rich |
| **Vue SPA** | `web/src/main.ts`, `web/src/router/index.ts`, `web/src/views/` | Vue 3, Pinia, composables, API clients |
| **Streaming UI path** | `web/src/composables/useAgentStream.ts`, SSE/WebSocket routes | `fetch()` + `ReadableStream`, SSE, backend stream routes |

### Critical rule

Do **not** force every explanation into:

```text
router -> app service -> domain service -> DB
```

That shape is correct for many backend routes, but it is incomplete for:

- Typer CLIs
- Textual TUIs
- Vue SPAs
- SSE / stream-driven UI flows
- event-driven workers

Use the call shape that matches the feature.

---

## 2. Canonical control-flow shapes

### 2.1 FastAPI / backend HTTP

```text
router
-> application service
-> domain service
-> DB / integration / event publication
```

### 2.2 Background workers / workflows

```text
task decorator / workflow registration
-> worker function
-> orchestration helper / application service
-> domain service
-> DB / downstream event / external integration
```

### 2.3 Operator CLI (deployment / verifier style)

```text
Make target
-> Typer command
-> Command class / CLI helper
-> HTTP CLI endpoint
-> router
-> application service
-> domain / DB / side effects
```

### 2.4 User-facing app CLI (Slo style)

```text
console script / python -m
-> src/cli/__main__.py
-> src/cli/__init__.py
-> src/cli/app.py
-> dispatch helper (for example src/cli/typer_dispatch.py)
-> TUI or runtime service/session
```

### 2.5 Textual TUI

```text
App.compose() / mount lifecycle
-> widget event / key binding / custom Message
-> router/helper (for example SlashRouter)
-> session/service method
-> streamed domain event(s)
-> renderer/adapter
-> transcript widget / screen state update
```

### 2.6 Vue SPA

```text
main.ts
-> App.vue
-> router/index.ts
-> route view
-> feature container component
-> store and/or composable
-> api client or streaming composable
-> backend route
```

### 2.7 Streaming browser path

```text
view/component
-> composable
-> fetch(.../stream)
-> frame parser
-> store mutations
-> reactive UI rerender
-> backend stream route
```

When explaining a feature, explicitly name which shape you are following.

---

## 3. Required answer format

Your answer must be easy for a developer to scan.
Do **not** compress the entire explanation into one paragraph.

### Required sections

Use this structure:

```md
## Entry point
- `path/to/file.ext:Symbol`
- why this is the first code that matters

## Call flow
1. `path/to/file.ext:Symbol`
   - what calls it
   - what input it receives
2. `path/to/file.ext:Symbol`
   - what it does next
3. ...

## State / payload handoffs
- from `A` to `B`: payload / params / event shape
- from `B` to `C`: state mutation / DTO / route params

## Side effects
- DB write / HTTP call / stream emit / localStorage write / modal mount / task spawn

## Important branches
- success path
- empty-state path
- error path
- cancel / abort path

## If you change this, also read
- related file 1
- related file 2
```

### Optional graph

If the user is in an **interactive session** and would benefit from it, include a small ASCII graph **above** the bullet list.

Example:

```text
ChatPage.vue
  -> ChatView.vue
    -> useAgentStream.sendQuery(...)
      -> fetch(/api/v1/chat/query/<id>/stream)
        -> SSE frame parser
          -> chat store mutations
            -> localStorage persistence
```

The graph is optional.
The bullet list is **not** optional.

### Never use this format

Bad:

```text
web/src/views/ChatPage.vue reads route.params.conversationId, passes it to web/src/components/chat/ChatView.vue, which calls useAgentStream().sendQuery(...). sendQuery(...) POSTs to /api/v1/chat/query/<conversation_id>/stream, parses data: SSE frames, and updates useChatStore() via addStatusMessage, appendAssistantDelta, and finalizeAssistantMessage. The store persists messages into localStorage under orders_platform_messages_<conversation_id>
```

That format is hostile to readers.

### Use this format instead

Good:

```md
## Entry point
- `web/src/views/ChatPage.vue`
  - Reads `route.params.conversationId`
  - Passes that value into `ChatView`

## Call flow
1. `web/src/views/ChatPage.vue`
   - extracts `conversationId` from the router
   - renders `ChatView` with that route-scoped context
2. `web/src/components/chat/ChatView.vue`
   - decides whether to load an existing conversation or start a new one
   - calls `useAgentStream().sendQuery(...)` when the user submits a message
3. `web/src/composables/useAgentStream.ts:sendQuery`
   - POSTs to `/api/v1/chat/query/<conversation_id>/stream`
   - parses streamed `data:` frames
4. `web/src/stores/chat.ts`
   - updates status lines, assistant deltas, and final messages
   - persists the conversation state to localStorage

## State / payload handoffs
- route -> view: `conversationId`
- `ChatView` -> `sendQuery(...)`: user text + conversation id
- stream parser -> store: event types like `status`, `delta`, `artifact`, `error`, `done`

## Side effects
- HTTP POST to the chat stream endpoint
- localStorage write under `orders_platform_messages_<conversation_id>`

## If you change this, also read
- `web/src/router/index.ts`
- `web/src/api/client.ts`
- backend stream route implementation
```

That is the minimum acceptable quality bar.

---

## 4. General tracing workflow

No matter which surface you are tracing, do this in order:

1. **Find the entry point**
   - route
   - command
   - view
   - screen
   - worker registration
2. **Follow one hop at a time**
   - do not skip from entry straight to the DB
3. **Name the symbol**
   - file path alone is not enough; include function/class/method when possible
4. **Record the payload at boundaries**
   - route params, DTOs, slash command text, store action args, event payloads, task inputs
5. **Call out side effects explicitly**
   - DB writes, stream emissions, localStorage writes, modal mounts, subprocesses, OAuth launch, etc.
6. **Capture alternate branches**
   - error path, fallback path, empty result, auth failure, cancel path, retry loop
7. **List the adjacent files needed for a safe change**

If you skip steps 4–6, the explanation will look complete while still being unsafe for a developer to rely on.

---

## 5. Workflow for backend HTTP features

Use this when the surface is a backend route.

### Step 1 — find the route declaration

Search for:

- `@router.get(...)`
- `@router.post(...)`
- `@router.patch(...)`
- `@router.delete(...)`

Also read where the router is mounted in:

- `src/main.py`
- `src/web_app.py`
- the app bootstrap module

### Step 2 — read the route function carefully

Capture:

- route path
- HTTP method
- request DTO / body model
- path params
- query params
- auth/dependency requirements
- which application service is called

### Step 3 — follow the application service entry point

Common shapes:

- `invoke(...)`
- `execute(...)`
- `run(...)`
- `handle(...)`

Read the public method, then the private helpers it calls, in order.

### Step 4 — follow the domain service / repository calls actually used

Do not read the whole domain package blindly.
Read:

- the methods actually invoked
- the DAO/model if it affects behavior or validation
- the repository/storage layer if persistence is important to the explanation

### Step 5 — name non-DB side effects

Examples:

- event publication
- integration client call
- DBOS/Celery enqueue
- object-storage write
- SSE chunk emission
- websocket broadcast

### Granular example

```md
## Entry point
- `src/routers/chat.py:create_query_stream`
  - handles `POST /api/v1/chat/query/{conversation_id}/stream`

## Call flow
1. `src/routers/chat.py:create_query_stream`
   - validates the request body
   - extracts `conversation_id`
   - calls `CreateQueryStream.invoke(...)`
2. `src/application/chat/create_query_stream.py:CreateQueryStream.invoke`
   - resolves the conversation
   - starts the agent/session stream
   - returns a streaming response adapter
3. `src/domain/chat/session.py:prompt_streaming`
   - yields progress events and final output

## State / payload handoffs
- router -> app service: `conversation_id`, user prompt DTO
- app service -> session: normalized prompt + session config

## Side effects
- conversation lookup
- streaming response emission
- possible persistence of final message
```

---

## 6. Workflow for workers, DBOS, and event-driven flows

### 6.1 Celery / DBOS / registered workers

Tracing order:

1. find the decorator/registration site
2. identify the function the worker runtime executes
3. follow the first orchestration helper or app service it calls
4. trace downstream state changes and fan-out
5. note completion reporting, retry semantics, and failure handling

### What to capture

- task/workflow name
- task payload shape
- retry policy
- idempotency guards
- downstream writes/events
- completion/failure sinks

### 6.2 Event handlers

Tracing order:

1. find the event publication site
2. find handler registration / subscription
3. read the handler entry point
4. follow the invoked application service
5. capture retry/partition/workflow-enqueue behavior

### Granular example

```md
## Entry point
- `src/events/handlers/run_finished.py:handle`
  - subscribed to `run.finished`

## Call flow
1. publisher emits `run.finished`
2. `run_finished.py:handle`
   - deserializes the event payload
   - calls `FinalizeRun.invoke(...)`
3. `FinalizeRun.invoke(...)`
   - updates run status
   - emits any follow-up events

## Side effects
- DB update for run status
- follow-up event publication
- optional notification send
```

---

## 7. Workflow for user-facing Typer CLIs (`src/cli/`)

This is the pattern Slo uses.

### Reading order

1. `src/cli/__main__.py`
2. `src/cli/__init__.py`
3. `src/cli/app.py`
4. `src/cli/typer_dispatch.py` (or equivalent dispatch helper)
5. downstream target module (`src/tui/app.py`, `src/main.py`, updater helper, etc.)

### Questions to answer by file

| File | Questions |
|---|---|
| `__main__.py` | how does `python -m` enter? |
| `__init__.py` | what `main()` is exported? |
| `app.py` | which callback/command handles the user input? |
| dispatch helper | where are paths/config/session objects assembled? |
| downstream target | what real runtime behavior gets launched? |

### Search patterns

- `typer.Typer(`
- `@app.callback`
- `@app.command`
- `TyperGroup`
- `typer.Option(`
- `typer.Argument(`
- `main()`

### Granular example — default TUI launch

```md
## Entry point
- `src/cli/__init__.py:main`
  - console script entry

## Call flow
1. `src/cli/__main__.py`
   - `python -m` path raises `SystemExit(main())`
2. `src/cli/__init__.py:main`
   - forwards into the Typer app
3. `src/cli/app.py:_default`
   - handles bare invocation and `--version`
   - if no subcommand is invoked, delegates to `TyperDispatch.tui(...)`
4. `src/cli/typer_dispatch.py:TyperDispatch.tui`
   - resolves workdir/cwd
   - enters interactive logging isolation
   - builds session config
   - constructs `SloAgentSession`
5. `src/tui/app.py:SloTUI.run`
   - starts the Textual app

## State / payload handoffs
- callback -> dispatch: optional `workdir`
- dispatch -> session builder: normalized config DTO
- dispatch -> TUI: constructed session object

## Side effects
- cwd resolution
- session construction
- live TUI boot
```

### Granular example — subcommand path

```md
## Entry point
- `src/cli/app.py:_serve`
  - handles `slo serve --port 7700`

## Call flow
1. `src/cli/app.py:_serve`
   - parses `--port`
   - calls `TyperDispatch.serve(port=...)`
2. `src/cli/typer_dispatch.py:TyperDispatch.serve`
   - calls `uvicorn.run(...)`

## Side effects
- process binds a local port
- HTTP service starts
```

---

## 8. Workflow for Textual TUIs (`src/tui/`)

A TUI is not traced like a route.
You must break it into **trigger -> interpretation -> domain call -> render update**.

### Reading order

1. `src/tui/app.py`
2. `src/tui/*.tcss`
3. `slash_router.py`, `event_renderer.py`, and similar helpers
4. feature screens under `src/tui/<feature>/`
5. widget modules under `src/tui/<feature>/widgets/`
6. the injected session/service type used by the TUI

### What to capture

| Question | Where to find it |
|---|---|
| how is the UI composed? | `compose()` |
| what global keys exist? | `BINDINGS`, `action_*` |
| what happens on input submit or button press? | `on_*` handlers + widget `Message` classes |
| how are slash commands interpreted? | router/helper module |
| how are streamed events rendered? | renderer + adapter |
| how are modal steps coordinated? | `Screen` class + state enum + transition helper |
| what async tasks can outlive one handler? | stored `asyncio.Task` refs |

### Search patterns

- `class .*\(App\)`
- `def compose`
- `on_mount`
- `on_unmount`
- `Binding(`
- `action_`
- `post_message(`
- `class .*\(Message\)`
- `ModalScreen`
- `ScreenState`

### Granular example — prompt submit path

```md
## Entry point
- `src/tui/app.py:PromptInput.Submitted`
  - semantic message emitted when the user presses Enter

## Call flow
1. `PromptInput.Submitted`
   - carries the prompt text
2. `src/tui/app.py:on_prompt_input_submitted`
   - branches between slash-command handling and normal prompt execution
3. `src/tui/slash_router.py:SlashRouter.dispatch`
   - for `/...` inputs, returns a typed result object
   - or
   `src/tui/app.py:_run_prompt`
   - for normal inputs, calls into the session
4. `src/domain/.../prompt_streaming`
   - yields progress events
5. `src/tui/event_renderer.py:EventRenderer.render`
   - formats each event into semantic transcript output
6. `_TranscriptAdapter.write(...)`
   - forwards content into the transcript widget

## State / payload handoffs
- widget -> app: submitted text
- app -> slash router: raw slash line
- app -> session: prompt text + active session state
- session -> renderer: typed progress events

## Side effects
- stream starts
- spinner mounts/unmounts
- transcript updates
- task handle may be stored/cancelled
```

### Granular example — modal auth flow

```md
## Entry point
- `src/tui/authentication/auth_screen.py:AuthenticationScreen`

## Call flow
1. auth screen mounts initial step widget
2. step widget emits semantic `Message`
3. screen updates `ScreenState`
4. screen swaps the next step widget
5. screen persists credentials or launches OAuth through injected collaborators
6. success widget is shown and the screen dismisses with a result
```

---

## 9. Workflow for Vue applications (`web/src/`)

This is the correct reading order for the Orders platform Vue app.

### Step 1 — start at boot

Read:

1. `web/src/main.ts`
2. `web/src/App.vue`
3. `web/src/router/index.ts`

This tells you:

- app-wide plugin setup (`createPinia()`, router, observability)
- root shell composition
- available routes
- conditional route installation
- router-level guards and redirects

### Step 2 — read the route view

For the route you care about, open the corresponding file in `web/src/views/`.

Orders platform examples:

- `/chat` and `/chat/:conversationId` -> `web/src/views/ChatPage.vue`
- `/_verifier` -> `web/src/views/verifier/VerifierDashboardView.vue`

### Step 3 — read the container component

In this codebase, route views are intentionally thin.
Most real behavior lives in components below the route view.

Examples:

- `ChatPage.vue` -> `components/chat/ChatView.vue`
- `AppLayout.vue` -> shared layout shell

### Step 4 — read stores and composables

That is where most Vue behavior actually lives.

| Layer | Orders platform examples | Responsibility |
|---|---|---|
| Store | `stores/chat.ts`, `stores/verifier.ts`, `stores/ui.ts` | state, local persistence, async load actions |
| Composable | `composables/useAgentStream.ts`, `useVerifierEnv.ts` | side effects, streaming, env gates |
| API client | `api/client.ts`, `api/verifier_client.ts` | transport |

### Step 5 — trace the backend contract

Once you know which browser-side transport is used, follow it into the backend route.

---

## 10. Granular Vue examples for the Orders platform

### 10.1 Chat flow

Use this reading order:

```text
web/src/main.ts
-> web/src/App.vue
-> web/src/components/layout/AppLayout.vue
-> web/src/router/index.ts
-> web/src/views/ChatPage.vue
-> web/src/components/chat/ChatView.vue
-> web/src/stores/chat.ts
-> web/src/composables/useAgentStream.ts
-> web/src/api/client.ts
-> backend /api/v1 routes
```

### What you must capture

- how `conversationId` comes from `route.params`
- where `loadConversation(...)` is triggered
- how first-message-on-new-conversation works
- where queued messages are stored/drained
- how stream frames are parsed (`status`, `delta`, `artifact`, `error`, `done`)
- which store methods each frame updates
- how localStorage persistence works

### Example answer shape

```md
## Entry point
- `web/src/views/ChatPage.vue`
  - reads `route.params.conversationId`
  - passes route context into `ChatView`

## Call flow
1. `web/src/views/ChatPage.vue`
   - extracts the route param
   - renders `ChatView`
2. `web/src/components/chat/ChatView.vue`
   - coordinates the page-level chat UX
   - loads existing conversation state when a conversation id is present
   - calls `useAgentStream().sendQuery(...)` on submit
3. `web/src/composables/useAgentStream.ts:sendQuery`
   - POSTs to `/api/v1/chat/query/<conversation_id>/stream`
   - parses streamed `data:` frames
4. `web/src/stores/chat.ts`
   - updates status messages, assistant deltas, and finalized messages
   - persists messages to localStorage

## State / payload handoffs
- router -> view: `conversationId`
- `ChatView` -> stream composable: conversation id + user text
- stream parser -> store: frame types like `status`, `delta`, `artifact`, `error`, `done`

## Side effects
- HTTP POST to the streaming endpoint
- localStorage writes under `orders_platform_messages_<conversation_id>`
```

### 10.2 Verifier dashboard flow

Use this reading order:

```text
web/src/router/index.ts
-> web/src/views/verifier/VerifierDashboardView.vue
-> web/src/stores/verifier.ts
-> web/src/api/verifier_client.ts
-> backend verifier routes
```

### What you must capture

- query-string synchronization (`?env=...`)
- environment gating in `router/index.ts`
- store actions that load verifier data
- route-level sidebar-closing logic (`meta.closeSidebar`, `beforeEach(...)`)

---

## 11. Search patterns for Vue work

| What you're looking for | Pattern | Scope |
|---|---|---|
| route definition | `path:` or `name:` | `web/src/router/` |
| lazy-loaded route component | `component: \(\) => import\(` | `web/src/router/index.ts` |
| store definition | `defineStore\(` | `web/src/stores/` |
| composable | `export function use` | `web/src/composables/` |
| HTTP transport | `fetch\(` or `request<` | `web/src/api/` and composables |
| route param bridge | `useRoute\(` / `route.params` | `web/src/views/`, `web/src/components/` |
| frame/event switch | `switch \(event.type\)` | `web/src/composables/` |
| browser persistence | `localStorage` / `loadFromStorage` / `saveToStorage` | `web/src/stores/` |

---

## 12. When the feature crosses framework boundaries

Many real tasks span multiple surfaces:

- Vue page -> stream composable -> backend route -> agent session
- Typer CLI -> Textual TUI -> session -> renderer
- Make target -> Typer CLI -> HTTP CLI router -> app service

### Rule

At each framework boundary:

1. name the boundary explicitly
2. switch tracing style
3. keep going until you reach the real state mutation / persistence / external IO

Do **not** stop just because you crossed from frontend into backend, or from CLI into TUI.

### Example boundary-aware answer

```md
## Call flow
1. `src/cli/app.py:_default`
   - bare command callback
   - delegates to `TyperDispatch.tui(...)`
2. `src/cli/typer_dispatch.py:TyperDispatch.tui`
   - builds the session
   - launches `SloTUI`
3. `src/tui/app.py:on_prompt_input_submitted`
   - handles prompt submission inside Textual
4. `src/tui/event_renderer.py:EventRenderer.render`
   - converts streamed events into transcript writes
```

That is much better than pretending the whole feature is "a CLI command."

---

## 13. Minimum deliverable

When the user asks "how does this work?", your answer must include:

- the exact entry file and symbol
- the ordered call chain
- payload/state handoffs at important boundaries
- explicit side effects
- important success/error/cancel branches
- the files that must be read before safely changing it

### Final template

```md
## Entry point
- `...`

## Call flow
1. `...`
2. `...`
3. `...`

## State / payload handoffs
- `...`
- `...`

## Side effects
- `...`
- `...`

## Important branches
- `...`
- `...`

## If you change this, also read
- `...`
- `...`
```

Optional, only when useful in an interactive session:

```text
A -> B -> C -> D
```

That is the bar.
