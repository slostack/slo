---
name: 06-composables
description: 'Vue tutorial: writing and using composables.'
when_to_use: Use only for learning.
group: frontend-vue
kind: skill
source_prompt: vue-prompts/tutorial/06-composables.md
---

# Tutorial 6: Custom Composables -- Vue's Reusable Logic Units

## Skill summary

- **Name:** `06-composables`
- **Description:** Vue tutorial: writing and using composables.
- **When to use:** Use only for learning.
- **Group:** `frontend-vue`
- **Kind:** `skill`
- **Source prompt:** `vue-prompts/tutorial/06-composables.md`

## Examples

- The user asks for help with: Vue tutorial: writing and using composables.
- Use only for learning.

## Guidance

Composables are functions that encapsulate and reuse stateful logic. If you have written Python
context managers, utility classes, or mixins, you already understand the motivation: extract
repeated patterns into something you can import and use anywhere.

---

## 1. What Is a Composable?

A composable is a plain function that:
1. Uses Vue's reactivity system (`ref`, `computed`, `watch`, lifecycle hooks).
2. Returns reactive state and/or methods for the caller to use.
3. Is named with a `use` prefix by convention.

Python comparison:

| Vue Composable | Python Equivalent |
|---|---|
| `useAgentStream()` | A service class or context manager |
| `useMarkdown()` | A utility class with methods |
| `useChatStore()` | A singleton/service locator |

The key advantage over a plain utility function is that composables participate in Vue's
reactivity system and lifecycle. They can create reactive variables that update the UI, and
they can hook into `onMounted`/`onUnmounted` to set up and clean up resources.

---

## 2. The `useMarkdown` Composable -- A Simple Example

Open `web/src/composables/useMarkdown.ts`:

```typescript
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

const md: MarkdownIt = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  highlight(str: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang }).value}</code></pre>`
      } catch {
        /* fall through */
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  },
})

export function useMarkdown() {
  function render(source: string): string {
    return md.render(source)
  }

  return { render }
}
```

### Line-by-Line Walkthrough

**Lines 1-2**: Import the markdown parser and syntax highlighter libraries.

**Lines 4-18**: Create a configured `MarkdownIt` instance at module level. This is created
once and shared across all calls. The configuration:
- `html: false` -- Do not allow raw HTML in markdown (security).
- `linkify: true` -- Automatically turn URLs into clickable links.
- `typographer: true` -- Smart quotes and dashes.
- `highlight` -- A function that syntax-highlights code blocks using highlight.js.

**Lines 20-25**: The composable function. It wraps `md.render()` in a simple interface.

**Line 25**: Returns an object with the `render` function. Callers destructure this.

### Usage in MarkdownRenderer.vue

```typescript
const { render } = useMarkdown()

const html = computed<string>(() => {
  return render(props.source)
})
```

```vue
<div class="markdown-content" v-html="html" />
```

The `v-html` directive renders the HTML string as actual DOM elements (not escaped text).

### Python Comparison

```python
import markdown
from pygments import highlight

class MarkdownRenderer:
    """A utility class that converts markdown to HTML with syntax highlighting."""

    def __init__(self):
        self._md = markdown.Markdown(extensions=['fenced_code', 'codehilite'])

    def render(self, source: str) -> str:
        return self._md.convert(source)

# Usage
renderer = MarkdownRenderer()
html = renderer.render(some_markdown_text)
```

The composable pattern is simpler than a class because you do not need `self`, constructors,
or instantiation. It is a function that returns functions.

---

## 3. The `useAgentStream` Composable -- A Complex Example

Open `web/src/composables/useAgentStream.ts`. This composable manages a WebSocket connection
for real-time communication with the backend agent. Let us walk through it section by section.

### Setup and State

```typescript
import { ref, onUnmounted } from 'vue'
import type { WebSocketEvent, ConnectionStatus } from '@/types/chat'
import { useChatStore } from '@/stores/chat'

export function useAgentStream() {
  const store = useChatStore()
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  const MAX_RECONNECT_DELAY = 10000
  let reconnectAttempts = ref<number>(0)
```

Notice the mix of reactive and non-reactive state:
- `reconnectAttempts` is a `ref` -- it could be used in a template.
- `ws` and `reconnectTimer` are plain `let` variables -- they are internal plumbing that does
  not need to trigger re-renders.
- `store` connects the composable to the Pinia chat store.

Python comparison -- this is like `__init__` in a class:

```python
class AgentStream:
    def __init__(self):
        self.store = ChatStore()
        self._ws: WebSocket | None = None
        self._reconnect_timer: Timer | None = None
        self.MAX_RECONNECT_DELAY = 10000
        self.reconnect_attempts = 0
```

### URL Builder

```typescript
function getWsUrl(conversationId: string): string {
  const protocol: string = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host: string = window.location.host
  return `${protocol}//${host}/api/v1/chat/ws/${conversationId}`
}
```

This dynamically constructs the WebSocket URL based on the current page's protocol and host.
In production (HTTPS), it uses `wss:`. In development (HTTP), it uses `ws:`.

### Connect and Disconnect

```typescript
function connect(conversationId: string): void {
  disconnect()  // Clean up any existing connection first

  const url: string = getWsUrl(conversationId)
  store.setConnectionStatus('connecting')

  ws = new WebSocket(url)

  ws.onopen = (): void => {
    store.setConnectionStatus('connected')
    reconnectAttempts.value = 0
  }

  ws.onmessage = (event: MessageEvent): void => {
    try {
      const data: WebSocketEvent = JSON.parse(event.data)
      handleEvent(data)
    } catch (error: unknown) {
      console.error('Failed to parse WebSocket message:', error)
    }
  }

  ws.onclose = (): void => {
    store.setConnectionStatus('disconnected')
    scheduleReconnect(conversationId)
  }

  ws.onerror = (): void => {
    store.setConnectionStatus('error')
  }
}

function disconnect(): void {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (ws) {
    ws.onclose = null      // Prevent reconnect when we intentionally close
    ws.close()
    ws = null
  }
  store.setConnectionStatus('disconnected')
}
```

The key detail in `disconnect`: setting `ws.onclose = null` before calling `ws.close()`.
Without this, closing the WebSocket would trigger the `onclose` handler, which would schedule
a reconnect. We do not want that when disconnecting intentionally.

Python comparison -- this is like an async context manager:

```python
class AgentStream:
    async def connect(self, conversation_id: str):
        await self.disconnect()
        self._ws = await websockets.connect(url)

    async def disconnect(self):
        if self._reconnect_timer:
            self._reconnect_timer.cancel()
        if self._ws:
            await self._ws.close()
```

### Sending Messages

```typescript
function sendQuery(content: string): void {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    console.error('WebSocket is not connected')
    return
  }

  store.addUserMessage(content)
  store.setStreaming(true)
  store.clearStatusMessages()

  ws.send(JSON.stringify({ type: 'query', content }))
}
```

This function guards against sending on a closed connection, updates the store to show the
user message and streaming state, then sends the query as JSON.

### Lifecycle Cleanup

```typescript
onUnmounted(() => {
  disconnect()
})
```

When the component using this composable is removed from the DOM, the WebSocket is
disconnected. This prevents resource leaks. This is the composable equivalent of Python's
`__del__` or `__aexit__`.

### The Public API

```typescript
return {
  connect,
  disconnect,
  sendQuery,
  sendPing,
  reconnectAttempts,
}
```

The caller gets back functions to control the connection and a reactive ref for reconnect
attempts. Internal details like `ws`, `reconnectTimer`, and `handleEvent` are encapsulated.

---

## 4. How Composables Are Used in Components

From `ChatView.vue`:

```typescript
const chat = useChatStore()
const { connect, disconnect, sendQuery } = useAgentStream()

onMounted(() => {
  if (props.conversationId) {
    chat.loadConversation(props.conversationId)
    connect(props.conversationId)
  }
})

watch(
  () => props.conversationId,
  (newId, oldId) => {
    if (newId && newId !== oldId) {
      disconnect()
      chat.loadConversation(newId)
      connect(newId)
    }
  },
)

async function handleSend(content: string): Promise<void> {
  if (!props.conversationId) {
    const conversation = await chat.createConversation()
    connect(conversation.id)
    await new Promise((resolve) => setTimeout(resolve, 300))
    sendQuery(content)
    return
  }
  sendQuery(content)
}
```

The component does not know or care about WebSocket internals. It just calls `connect`,
`disconnect`, and `sendQuery`. All the reconnection logic, event handling, and state updates
happen inside the composable.

---

## 5. Composable Design Patterns

### Pattern 1: Stateless Utility (useMarkdown)

- No reactive state
- Returns helper functions
- Instance created once at module level
- Analogous to a Python utility module

### Pattern 2: Stateful Service (useAgentStream)

- Manages reactive and non-reactive state
- Uses lifecycle hooks for cleanup
- Interacts with Pinia stores
- Analogous to a Python service class

### Pattern 3: Store Accessor (useChatStore, useUiStore)

- Pinia stores are themselves composables
- They follow the `use` naming convention
- Return reactive state, getters, and actions
- Analogous to a Python singleton/repository

### When to Extract a Composable

Extract logic into a composable when:
1. Two or more components need the same stateful logic.
2. A component is getting too large and you want to separate concerns.
3. You have a reusable pattern (API calls, timers, event listeners).

Do not extract if the logic is simple and used in only one place. Premature abstraction makes
code harder to follow.

---

## 6. Composable vs Python Alternatives

| Composable Feature | Python Equivalent |
|---|---|
| Returns reactive state | Returns an object with observable properties |
| Uses `onUnmounted` for cleanup | Uses `__del__`, `__aexit__`, or `atexit` |
| Shares state via closures | Shares state via `self` attributes |
| Called at component setup | Called in `__init__` |
| `use` prefix convention | No standard convention (maybe `create_` or `make_`) |

The composable pattern is closest to Python's context manager:

```python
# Python context manager
class agent_stream:
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

# Usage
with agent_stream() as stream:
    stream.send_query("What is the evidence for...")
```

Vue composables automatically call their cleanup code (`onUnmounted`) when the component is
destroyed, much like `__exit__` runs when leaving a `with` block.

---

## Key Takeaways

1. Composables are functions that encapsulate reusable, reactive logic.
2. They follow the `use` prefix naming convention.
3. Simple composables (like `useMarkdown`) wrap utility logic.
4. Complex composables (like `useAgentStream`) manage state, lifecycle, and side effects.
5. Composables can use other composables and Pinia stores.
6. The `onUnmounted` hook ensures cleanup when the component is destroyed.
7. Think of them as Python context managers or service classes for the Vue world.

---

## Try It Yourself

1. Read through `useAgentStream.ts` end to end. Trace what happens when a WebSocket message
   of type `'artifact'` arrives. Follow the flow from `ws.onmessage` through `handleEvent`
   into the store's `addAssistantMessage`.

2. The `useMarkdown` composable creates the `MarkdownIt` instance at module level (outside
   the function). What would happen if you moved it inside `useMarkdown()`? It would create
   a new parser for every component that uses it -- wasteful but functionally correct.

3. Write a `useTimer` composable that starts a repeating timer on mount and clears it on
   unmount:
   ```typescript
   export function useTimer(intervalMs: number, callback: () => void) {
     let id: ReturnType<typeof setInterval> | null = null
     onMounted(() => { id = setInterval(callback, intervalMs) })
     onUnmounted(() => { if (id) clearInterval(id) })
   }
   ```
   Use it in a component to ping the WebSocket every 30 seconds.

4. Think about how you would write a `useLocalStorage` composable that syncs a `ref` to
   `localStorage`. Read the initial value from storage, watch for changes, and write back.
   This would solve the dark mode persistence problem from Tutorial 4.
