---
name: 07-websocket-integration
description: 'Vue tutorial: WebSocket integration in Vue.'
when_to_use: Use only for learning.
group: frontend-vue
kind: skill
source_prompt: vue-prompts/tutorial/07-websocket-integration.md
---

# Tutorial 7: WebSocket Integration -- Real-Time Communication

## Skill summary

- **Name:** `07-websocket-integration`
- **Description:** Vue tutorial: WebSocket integration in Vue.
- **When to use:** Use only for learning.
- **Group:** `frontend-vue`
- **Kind:** `skill`
- **Source prompt:** `vue-prompts/tutorial/07-websocket-integration.md`

## Examples

- The user asks for help with: Vue tutorial: WebSocket integration in Vue.
- Use only for learning.

## Guidance

The example chat app uses WebSockets to stream agent progress from the backend to the browser in
real time. Unlike HTTP requests (ask once, get one response), WebSockets maintain a persistent
connection where either side can send messages at any time.

If you have used Python's `websockets` library or FastAPI's `WebSocket` endpoint, you know the
server side. This tutorial covers the browser side -- how the Vue frontend connects, sends
queries, receives events, and handles disconnections.

---

## 1. The Browser WebSocket API

The browser has a built-in `WebSocket` class. No library needed:

```typescript
const ws = new WebSocket('wss://example.com/ws')

ws.onopen = () => { /* connection established */ }
ws.onmessage = (event) => { /* received a message */ }
ws.onclose = () => { /* connection closed */ }
ws.onerror = () => { /* something went wrong */ }

ws.send('Hello')     // send a message
ws.close()           // close the connection
```

Python comparison:

```python
import websockets

async with websockets.connect('wss://example.com/ws') as ws:
    await ws.send('Hello')
    response = await ws.recv()
```

The main difference: Python's `websockets` is async/await-based, while the browser API uses
event callbacks. In the example chat app, the `useAgentStream` composable wraps these callbacks.

---

## 2. Connection Lifecycle

Open `web/src/composables/useAgentStream.ts` and follow the connection flow:

### Step 1: Build the URL

```typescript
function getWsUrl(conversationId: string): string {
  const protocol: string = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host: string = window.location.host
  return `${protocol}//${host}/api/v1/chat/ws/${conversationId}`
}
```

This constructs the WebSocket URL dynamically. If the page is served over HTTPS, the
WebSocket uses `wss:` (encrypted). Over HTTP, it uses `ws:` (unencrypted).

The conversation ID is baked into the URL, so each conversation has its own WebSocket
endpoint. The backend uses this to route messages to the correct agent session.

Python equivalent on the server side (FastAPI):

```python
@app.websocket("/api/v1/chat/ws/{conversation_id}")
async def websocket_endpoint(websocket: WebSocket, conversation_id: str):
    await websocket.accept()
    ...
```

### Step 2: Connect

```typescript
function connect(conversationId: string): void {
  disconnect()                                    // (a) Clean up first
  const url: string = getWsUrl(conversationId)
  store.setConnectionStatus('connecting')         // (b) Update UI state

  ws = new WebSocket(url)                         // (c) Create connection

  ws.onopen = (): void => {                       // (d) Handle open
    store.setConnectionStatus('connected')
    reconnectAttempts.value = 0
  }

  ws.onmessage = (event: MessageEvent): void => { // (e) Handle messages
    try {
      const data: WebSocketEvent = JSON.parse(event.data)
      handleEvent(data)
    } catch (error: unknown) {
      console.error('Failed to parse WebSocket message:', error)
    }
  }

  ws.onclose = (): void => {                      // (f) Handle close
    store.setConnectionStatus('disconnected')
    scheduleReconnect(conversationId)
  }

  ws.onerror = (): void => {                      // (g) Handle error
    store.setConnectionStatus('error')
  }
}
```

Let us break down each step:

**(a)** Always disconnect before connecting. This prevents multiple simultaneous connections if
the user switches conversations quickly.

**(b)** Set the connection status to `'connecting'`. The Header component shows a yellow
indicator dot for this state.

**(c)** Create the WebSocket. The browser immediately begins the handshake.

**(d)** On successful connection, update status to `'connected'` (green dot) and reset the
reconnect counter.

**(e)** On each incoming message, parse the JSON and route it through `handleEvent`.

**(f)** On close, update status and schedule a reconnect attempt.

**(g)** On error, update status. The `onclose` handler will also fire after an error.

### Step 3: Disconnect

```typescript
function disconnect(): void {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (ws) {
    ws.onclose = null       // <-- Critical: prevent reconnect
    ws.close()
    ws = null
  }
  store.setConnectionStatus('disconnected')
}
```

The `ws.onclose = null` line is a subtle but important detail. When you call `ws.close()`, the
`onclose` callback normally fires. But `onclose` calls `scheduleReconnect`, which we do not
want when disconnecting intentionally (e.g., switching conversations). Setting the handler to
`null` first prevents that.

Python comparison -- it is like removing a signal handler before shutting down:

```python
async def disconnect(self):
    if self._reconnect_task:
        self._reconnect_task.cancel()
    if self._ws:
        # Don't trigger reconnect on intentional close
        self._ws.remove_listener('close', self._on_close)
        await self._ws.close()
```

---

## 3. Reconnection with Exponential Backoff

Network connections drop. The server might restart. The user's laptop might sleep. A robust
client reconnects automatically with increasing delays:

```typescript
const MAX_RECONNECT_DELAY = 10000
let reconnectAttempts = ref<number>(0)

function scheduleReconnect(conversationId: string): void {
  reconnectAttempts.value++
  const delay: number = Math.min(
    1000 * Math.pow(2, reconnectAttempts.value),
    MAX_RECONNECT_DELAY,
  )
  reconnectTimer = setTimeout(() => {
    connect(conversationId)
  }, delay)
}
```

The delay doubles each attempt: 2s, 4s, 8s, then caps at 10s. This is exponential backoff:

| Attempt | Delay |
|---|---|
| 1 | 2,000ms |
| 2 | 4,000ms |
| 3 | 8,000ms |
| 4+ | 10,000ms (capped) |

Why exponential backoff? If the server is down, hammering it with immediate reconnect attempts
makes things worse. Spacing out attempts gives the server time to recover.

On successful connection, the counter resets:

```typescript
ws.onopen = (): void => {
  store.setConnectionStatus('connected')
  reconnectAttempts.value = 0        // Reset on success
}
```

Python comparison:

```python
import asyncio

async def schedule_reconnect(self, conversation_id: str):
    self.reconnect_attempts += 1
    delay = min(2 ** self.reconnect_attempts, 10)
    await asyncio.sleep(delay)
    await self.connect(conversation_id)
```

---

## 4. Message Protocol -- Typed JSON Events

The server sends JSON messages, each with a `type` field that identifies the event kind. The
TypeScript types enforce the protocol:

```typescript
// types/chat.ts
export interface A2AStatusEvent {
  type: 'status'
  message: string
  state?: string
}

export interface A2AArtifactEvent {
  type: 'artifact'
  data: {
    response?: string
    [key: string]: unknown
  }
}

export interface A2AErrorEvent {
  type: 'error'
  message: string
}

export interface PongEvent {
  type: 'pong'
}

export type WebSocketEvent = A2AStatusEvent | A2AArtifactEvent | A2AErrorEvent | PongEvent
```

This is a discriminated union (covered in Tutorial 2). The `type` field tells you which variant
you are dealing with.

### Event Handling with Type Narrowing

```typescript
function handleEvent(event: WebSocketEvent): void {
  switch (event.type) {
    case 'status':
      store.addStatusMessage(event.message)
      break
    case 'artifact': {
      const responseText: string =
        event.data?.response ??
        (typeof event.data === 'string' ? event.data : JSON.stringify(event.data))
      store.addAssistantMessage(responseText, {
        statusHistory: [...store.statusMessages],
      })
      store.setStreaming(false)
      break
    }
    case 'error':
      console.error('Agent error:', event.message)
      store.addAssistantMessage(`Error: ${event.message}`)
      store.setStreaming(false)
      break
    case 'pong':
      break
  }
}
```

Here is what each event does:

**`status`**: The agent is working and sends progress updates. These appear as a timeline in
the `StreamingIndicator` component ("Searching PubMed...", "Analyzing 15 papers...", etc.).

**`artifact`**: The agent has finished and sends the final response. The code extracts the
text from `event.data.response`, creates an assistant message with the accumulated status
history as metadata, and turns off the streaming indicator.

**`error`**: Something went wrong. The error message is displayed as an assistant message.

**`pong`**: A keepalive response. The client sends `ping`, the server responds with `pong`.
Nothing to do.

Python comparison -- this is pattern matching:

```python
match event:
    case {"type": "status", "message": msg}:
        store.add_status_message(msg)
    case {"type": "artifact", "data": data}:
        response_text = data.get("response", json.dumps(data))
        store.add_assistant_message(response_text)
        store.set_streaming(False)
    case {"type": "error", "message": msg}:
        store.add_assistant_message(f"Error: {msg}")
        store.set_streaming(False)
    case {"type": "pong"}:
        pass
```

---

## 5. Sending Messages

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

Before sending, the function:
1. Guards against a closed connection (`readyState` check).
2. Optimistically adds the user message to the store (shows immediately in the UI).
3. Sets streaming to true (shows the progress indicator).
4. Clears old status messages.
5. Sends the query as JSON.

The keepalive ping is simpler:

```typescript
function sendPing(): void {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'ping' }))
  }
}
```

---

## 6. Lifecycle Integration

```typescript
onUnmounted(() => {
  disconnect()
})
```

When the component using `useAgentStream` is destroyed (the user navigates away), the
WebSocket is closed cleanly. This prevents orphaned connections that waste server resources.

This is the Vue equivalent of Python's `__del__` or a context manager's `__exit__`:

```python
def __del__(self):
    self.disconnect()

# or better:
async def __aexit__(self, *args):
    await self.disconnect()
```

---

## 7. The Connection Status in the UI

The `Header.vue` component displays the connection state:

```vue
<span
  class="connection-indicator"
  :class="chat.connectionStatus"
  :title="`Connection: ${chat.connectionStatus}`"
/>
```

The CSS in `main.scss` styles each state:

```scss
.connection-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;

  &.connected { background-color: #22c55e; }     // Green
  &.connecting { background-color: #eab308; animation: pulse 1s infinite; }  // Yellow, pulsing
  &.disconnected { background-color: #ef4444; }   // Red
  &.error { background-color: #ef4444; }           // Red
}
```

A tiny colored dot that gives the user immediate feedback about the connection state. The
pulsing animation on `connecting` signals that something is happening.

---

## 8. Full Message Flow

Here is the complete flow when a user sends a message:

1. User types in `ChatInput` and presses Enter.
2. `ChatInput` emits `send` event with the text.
3. `ChatView.handleSend` calls `sendQuery(content)`.
4. `useAgentStream.sendQuery` adds a user message to the store and sends JSON over WebSocket.
5. The backend agent receives the query and begins processing.
6. Backend sends `status` events: "Searching PubMed for relevant articles..."
7. `useAgentStream.handleEvent` adds each status to the store.
8. `StreamingIndicator` shows each status as a timeline step.
9. Backend finishes and sends an `artifact` event with the response.
10. `handleEvent` creates an assistant message and stops streaming.
11. `MessageBubble` renders the markdown response via `MarkdownRenderer`.

Each step is reactive -- there is no polling, no manual DOM update. Data flows from the
WebSocket through the store to the UI automatically.

---

## Key Takeaways

1. The browser `WebSocket` API uses event callbacks (`onopen`, `onmessage`, `onclose`,
   `onerror`).
2. Always disconnect before reconnecting to prevent duplicate connections.
3. Set `onclose = null` before calling `close()` to prevent unintended reconnection.
4. Exponential backoff (2s, 4s, 8s, capped at 10s) prevents hammering a downed server.
5. Typed JSON events with a `type` discriminator enable safe `switch`-based routing.
6. `onUnmounted` ensures cleanup when the component is destroyed.
7. The connection status flows through the Pinia store to a visual indicator in the header.

---

## Try It Yourself

1. Open your browser's DevTools (Network tab, WS filter) while using the chat. Watch the
   WebSocket frames. You will see the JSON messages (`query`, `status`, `artifact`) flow
   back and forth.

2. Try closing the backend server while a WebSocket is connected. Watch the connection
   indicator turn red, then see the exponential backoff timers in the console. Restart the
   server and watch it reconnect.

3. Add a heartbeat to the composable. Create a `setInterval` that calls `sendPing()` every
   30 seconds while connected. Clear the interval on disconnect. This keeps the connection
   alive through proxies and load balancers that close idle connections.

4. Modify `handleEvent` to handle a new event type, say `'progress'`, that includes a
   percentage. Add the interface to `types/chat.ts`, add a case to the switch, and store the
   value in a new ref. Display it as a progress bar in the streaming indicator.
