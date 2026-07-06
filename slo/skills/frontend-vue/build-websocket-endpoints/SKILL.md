---
name: build-websocket-endpoints
description: Building real-time WebSocket bridges between Vue and backend agents.
when_to_use: Use when wiring streaming UI updates from backend events.
group: frontend-vue
kind: skill
source_prompt: vue-prompts/build-websocket-endpoints.md
---

# Build WebSocket Endpoints — A2A Bridge Patterns

## Skill summary

- **Name:** `build-websocket-endpoints`
- **Description:** Building real-time WebSocket bridges between Vue and backend agents.
- **When to use:** Use when wiring streaming UI updates from backend events.
- **Group:** `frontend-vue`
- **Kind:** `skill`
- **Source prompt:** `vue-prompts/build-websocket-endpoints.md`

## Examples

- The user asks: "Add or revise the websocket endpoints for this feature."
- You want the canonical build pattern before touching websocket endpoints.

## Guidance

This document defines the conventions for building WebSocket endpoints in FastAPI that bridge the Vue frontend to backend A2A (Agent-to-Agent) services. The canonical reference implementation is the chat WebSocket in `orders_service/src/routers/chat_controller.py` and the frontend composable in `web/src/composables/useAgentStream.ts`.

---

## 1. Mental Model — The WebSocket Bridge

The WebSocket endpoint acts as a bridge between the Vue frontend and the A2A agent service. It does not contain business logic — it translates between WebSocket frames and A2A streaming events.

```
┌──────────────┐    WebSocket     ┌──────────────────────┐    HTTP/SSE    ┌──────────────────┐
│  Vue Client   │ ◄────────────► │  FastAPI WS Endpoint  │ ◄──────────► │  A2A Agent        │
│  (browser)    │   JSON frames   │  (bridge)             │   streaming   │  (LangGraph)      │
└──────────────┘                 └──────────────────────┘                └──────────────────┘
```

| Layer | File | Responsibility |
|---|---|---|
| **Frontend** | `web/src/composables/useAgentStream.ts` | WebSocket lifecycle, reconnection, event dispatching |
| **Bridge** | `orders_service/src/routers/chat_controller.py` | Accept WebSocket, route messages, stream A2A events back |
| **Connection Manager** | `orders_service/src/services/chat/connection_manager.py` | Track active connections per conversation |
| **A2A Client** | `orders_service/src/services/chat/a2a_client_service.py` | Connect to A2A agent, parse streaming events |
| **Agent** | `orders_service/src/agents/*/agent.py` | LangGraph agent exposed via A2A protocol |

---

## 2. Backend File Organization

```
orders_service/src/
├── routers/
│   └── chat_controller.py            # WebSocket endpoint
├── services/
│   └── chat/
│       ├── connection_manager.py      # Active connection tracking
│       └── a2a_client_service.py      # A2A protocol client
```

---

## 3. WebSocket Event Protocol

### 3.1 Client-to-Server Messages

The client sends JSON messages with a `type` field:

```typescript
// Query message — triggers an A2A agent call
{ "type": "query", "content": "What is metformin used for?" }

// Ping — keepalive
{ "type": "ping" }
```

### 3.2 Server-to-Client Messages

The server sends JSON messages with a `type` field:

```typescript
// Status — progress updates from the agent
{ "type": "status", "message": "Searching PubMed for 'metformin mechanism'...", "state": "working" }

// Artifact — final response from the agent
{ "type": "artifact", "data": { "response": "**Metformin** is a biguanide..." } }

// Error — something went wrong
{ "type": "error", "message": "Agent timed out" }

// Pong — response to ping
{ "type": "pong" }
```

### 3.3 TypeScript Type Definitions

Define these in `web/src/types/chat.ts`:

```typescript
// Client-to-server
export interface QueryMessage {
  type: 'query'
  content: string
}

export interface PingMessage {
  type: 'ping'
}

export type ClientMessage = QueryMessage | PingMessage

// Server-to-client
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

---

## 4. Backend Implementation

### 4.1 WebSocket Controller

The WebSocket endpoint is a FastAPI route that accepts a WebSocket connection, reads client messages, and streams A2A events back.

```python
# src/routers/chat_controller.py

from typing import Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from config.cfg import cfg
from config.logger import log_info, log_error
from src.services.chat.a2a_client_service import A2AClientService
from src.services.chat.connection_manager import manager

router = APIRouter(prefix="/api/v1/chat")


@router.websocket("/ws/{conversation_id}")
async def chat_websocket(
    websocket: WebSocket,
    conversation_id: str,
):
    await manager.connect(websocket=websocket, conversation_id=conversation_id)

    agent_url: str = cfg("A2A_PUBMED_AGENT_URL") or "http://localhost:9901"
    a2a_service: A2AClientService = A2AClientService(
        agent_url=agent_url,
    )

    try:
        while True:
            data: Dict[str, Any] = await websocket.receive_json()
            msg_type: str = data.get("type", "")

            if msg_type == "query":
                query: str = data.get("content", "")
                if not query:
                    await websocket.send_json(
                        {"type": "error", "message": "Empty query"}
                    )
                    continue

                log_info(
                    msg=f"Chat query received for conversation {conversation_id}",
                )

                async for event in a2a_service.send_query(query=query):
                    await websocket.send_json(event)

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(websocket=websocket, conversation_id=conversation_id)
    except Exception as e:
        log_error(msg=f"WebSocket error: {e}", e=e)
        manager.disconnect(websocket=websocket, conversation_id=conversation_id)
```

### 4.2 Connection Manager

The connection manager tracks active WebSocket connections per conversation. It is a module-level singleton.

```python
# src/services/chat/connection_manager.py

from typing import Dict, List
from fastapi import WebSocket
from config.logger import log_info


class ConnectionManager:
    """Tracks active WebSocket connections per conversation."""

    def __init__(self) -> None:
        self._active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, conversation_id: str) -> None:
        await websocket.accept()
        if conversation_id not in self._active_connections:
            self._active_connections[conversation_id] = []
        self._active_connections[conversation_id].append(websocket)
        log_info(msg=f"WebSocket connected for conversation {conversation_id}")

    def disconnect(self, websocket: WebSocket, conversation_id: str) -> None:
        if conversation_id in self._active_connections:
            self._active_connections[conversation_id] = [
                conn
                for conn in self._active_connections[conversation_id]
                if conn != websocket
            ]
            if not self._active_connections[conversation_id]:
                del self._active_connections[conversation_id]
        log_info(msg=f"WebSocket disconnected for conversation {conversation_id}")

    def get_connections(self, conversation_id: str) -> List[WebSocket]:
        return self._active_connections.get(conversation_id, [])


manager: ConnectionManager = ConnectionManager()
```

### 4.3 A2A Client Service

The A2A client service connects to the A2A agent via HTTP streaming and yields normalized event dicts.

```python
# src/services/chat/a2a_client_service.py

import httpx
from a2a.client import A2AClient
from a2a.types import MessageSendParams, Role
from typing import AsyncGenerator, Dict, Any
from uuid import uuid4
from config.logger import log_info, log_error


class A2AClientService:
    """Manages connection to an A2A agent service.

    Uses a2a.client.A2AClient to connect via HTTP transport
    with streaming enabled. Yields status updates and artifact events
    to the caller (WebSocket handler).
    """

    def __init__(self, agent_url: str = "http://localhost:9901") -> None:
        self._agent_url: str = agent_url

    async def send_query(
        self, query: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Send a query to the A2A agent and stream events back.

        Yields dicts with:
          {"type": "status", "message": "..."} for progress updates
          {"type": "artifact", "data": {...}} for final response
          {"type": "error", "message": "..."} for errors
        """
        try:
            async with httpx.AsyncClient() as http_client:
                client: A2AClient = await A2AClient.get_client_from_agent_card_url(
                    base_url=self._agent_url,
                    httpx_client=http_client,
                )

                send_params: MessageSendParams = MessageSendParams(
                    message={
                        "role": Role.user,
                        "parts": [{"kind": "data", "data": {"query": query}}],
                        "messageId": str(uuid4()),
                    },
                )

                log_info(
                    msg=f"Sending query to A2A agent at {self._agent_url}",
                )

                response = await client.send_message_streaming(
                    params=send_params,
                )

                async for event in response:
                    event_dict: Dict[str, Any] = self._parse_event(event=event)
                    if event_dict:
                        yield event_dict

        except Exception as e:
            log_error(msg=f"A2A client error: {e}", e=e)
            yield {"type": "error", "message": str(e)}

    def _parse_event(self, event: Any) -> Dict[str, Any] | None:
        """Parse an A2A streaming event into a simplified dict."""
        try:
            if hasattr(event, "status"):
                status_text: str = ""
                if event.status and event.status.message:
                    for part in event.status.message.parts:
                        if hasattr(part, "text"):
                            status_text = part.text
                        elif hasattr(part, "root") and hasattr(part.root, "text"):
                            status_text = part.root.text
                state: str = event.status.state if event.status else ""
                return {
                    "type": "status",
                    "message": status_text,
                    "state": str(state),
                }

            if hasattr(event, "artifact"):
                artifact_data: Dict[str, Any] = {}
                if event.artifact and event.artifact.parts:
                    for part in event.artifact.parts:
                        if hasattr(part, "data"):
                            artifact_data = part.data
                        elif hasattr(part, "text"):
                            artifact_data = {"response": part.text}
                        elif hasattr(part, "root"):
                            if hasattr(part.root, "data"):
                                artifact_data = part.root.data
                            elif hasattr(part.root, "text"):
                                artifact_data = {"response": part.root.text}
                return {"type": "artifact", "data": artifact_data}

        except Exception as e:
            log_error(msg=f"Error parsing A2A event: {e}", e=e)

        return None
```

---

## 5. Frontend Implementation

### 5.1 WebSocket Composable

The WebSocket composable manages the connection lifecycle, reconnection with exponential backoff, and event dispatching to the store.

```typescript
// composables/useAgentStream.ts

import { ref, onUnmounted } from 'vue'
import type { WebSocketEvent, ConnectionStatus } from '@/types/chat'
import { useChatStore } from '@/stores/chat'

export function useAgentStream() {
  const store = useChatStore()
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  const MAX_RECONNECT_DELAY: number = 10000
  const reconnectAttempts = ref<number>(0)

  function getWsUrl(conversationId: string): string {
    const protocol: string = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host: string = window.location.host
    return `${protocol}//${host}/api/v1/chat/ws/${conversationId}`
  }

  function connect(conversationId: string): void {
    disconnect()

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
      ws.onclose = null
      ws.close()
      ws = null
    }
    store.setConnectionStatus('disconnected')
  }

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

  function sendPing(): void {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ping' }))
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connect,
    disconnect,
    sendQuery,
    sendPing,
    reconnectAttempts,
  }
}
```

### 5.2 Using the Composable in a Container Component

```vue
<!-- components/chat/ChatView.vue -->
<script setup lang="ts">
import { watch, onMounted } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useAgentStream } from '@/composables/useAgentStream'
import MessageList from '@/components/chat/MessageList.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import StreamingIndicator from '@/components/chat/StreamingIndicator.vue'

const props = defineProps<{
  conversationId?: string
}>()

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
  (newId: string | undefined, oldId: string | undefined) => {
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
    await new Promise((resolve: (value: unknown) => void) => setTimeout(resolve, 300))
    sendQuery(content)
    return
  }
  sendQuery(content)
}
</script>

<template>
  <div class="chat-container">
    <template v-if="conversationId || chat.messages.length > 0">
      <MessageList :messages="chat.messages" />
      <StreamingIndicator
        v-if="chat.isStreaming"
        :status-messages="chat.statusMessages"
      />
    </template>
    <template v-else>
      <div class="empty-state">
        <h2>Orders Admin Assistant</h2>
        <p>Ask a question about an order to search for the relevant records.</p>
      </div>
    </template>
    <ChatInput
      :disabled="chat.isStreaming"
      @send="handleSend"
    />
  </div>
</template>
```

---

## 6. Adding a New WebSocket Endpoint

When adding a new WebSocket-backed feature (e.g., a different agent, a notification channel), follow these steps:

### Step 1: Define the Event Protocol

Define the client-to-server and server-to-client message types in `web/src/types/`:

```typescript
// types/notifications.ts

export interface SubscribeMessage {
  type: 'subscribe'
  channel: string
}

export interface UnsubscribeMessage {
  type: 'unsubscribe'
  channel: string
}

export type NotificationClientMessage = SubscribeMessage | UnsubscribeMessage

export interface NotificationEvent {
  type: 'notification'
  channel: string
  title: string
  body: string
  severity: 'info' | 'warning' | 'error'
  timestamp: string
}

export type NotificationServerMessage = NotificationEvent | PongEvent
```

### Step 2: Create the Backend Controller

```python
# src/routers/notifications_controller.py

from typing import Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from config.logger import log_info, log_error

router = APIRouter(prefix="/api/v1/notifications")


@router.websocket("/ws")
async def notifications_websocket(
    websocket: WebSocket,
):
    await websocket.accept()

    try:
        while True:
            data: Dict[str, Any] = await websocket.receive_json()
            msg_type: str = data.get("type", "")

            if msg_type == "subscribe":
                channel: str = data.get("channel", "")
                log_info(msg=f"Client subscribed to channel {channel}")
                # subscribe logic...

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        log_info(msg="Notification WebSocket disconnected")
    except Exception as e:
        log_error(msg=f"Notification WebSocket error: {e}", e=e)
```

### Step 3: Create the Frontend Composable

```typescript
// composables/useNotifications.ts

import { ref, onUnmounted } from 'vue'
import type { NotificationServerMessage } from '@/types/notifications'

export function useNotifications() {
  let ws: WebSocket | null = null
  const notifications = ref<NotificationServerMessage[]>([])

  function connect(): void {
    const protocol: string = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host: string = window.location.host
    const url: string = `${protocol}//${host}/api/v1/notifications/ws`

    ws = new WebSocket(url)

    ws.onmessage = (event: MessageEvent): void => {
      const data: NotificationServerMessage = JSON.parse(event.data)
      if (data.type === 'notification') {
        notifications.value.push(data)
      }
    }
  }

  function subscribe(channel: string): void {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'subscribe', channel }))
    }
  }

  function disconnect(): void {
    if (ws) {
      ws.onclose = null
      ws.close()
      ws = null
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connect,
    disconnect,
    subscribe,
    notifications,
  }
}
```

### Step 4: Register the Router

```python
# src/web_app.py (add to _initialize_routers)

from src.routers import notifications_controller

def _initialize_routers(app: FastAPI) -> FastAPI:
    # ... existing routers ...
    app.include_router(notifications_controller)
    return app
```

---

## 7. Rules and Patterns

### 7.1 Backend Rules

| Rule | Detail |
|---|---|
| **WebSocket endpoints are bridges** | They translate between WebSocket frames and backend services. No business logic in the controller. |
| **Module-level ConnectionManager** | One singleton manager tracks all connections. Use `manager.connect()` and `manager.disconnect()`. |
| **Type-hint every variable** | `data: Dict[str, Any] = await websocket.receive_json()`, not `data = await websocket.receive_json()` |
| **Named arguments everywhere** | `manager.connect(websocket=websocket, conversation_id=conversation_id)` |
| **Structured error logging** | `log_error(msg=f"WebSocket error: {e}", e=e)` |
| **Catch `WebSocketDisconnect` explicitly** | Always handle disconnection cleanly with `manager.disconnect()` |
| **Stream A2A events with `async for`** | The A2A client yields events; the controller forwards them directly |

### 7.2 Frontend Rules

| Rule | Detail |
|---|---|
| **One composable per WebSocket** | `useAgentStream` for chat, `useNotifications` for notifications |
| **Reconnect with exponential backoff** | `delay = min(1000 * 2^attempts, MAX_DELAY)` |
| **Clean up on `onUnmounted`** | Always close the WebSocket and clear timers when the component unmounts |
| **Dispatch events to the store** | The composable calls store actions, never modifies component state directly |
| **Type all event handlers** | `ws.onmessage = (event: MessageEvent): void => { ... }` |
| **Parse and validate incoming messages** | `JSON.parse` in a `try/catch`, type the result as the discriminated union |
| **Protocol detection** | Build the URL from `window.location.protocol` and `window.location.host` for portability |

### 7.3 Event Protocol Rules

| Rule | Detail |
|---|---|
| **Every message has a `type` field** | Discriminated union pattern on both sides |
| **Status events are progress indicators** | Display them in the UI during streaming, clear when done |
| **Artifact events carry the final response** | The `data` field contains the agent's synthesized answer |
| **Error events stop streaming** | Display the error and set `isStreaming = false` |
| **Ping/pong for keepalive** | Client sends `{"type": "ping"}`, server responds `{"type": "pong"}` |

---

## 8. Testing

### 8.1 Backend WebSocket Testing

Use `httpx.AsyncClient` or FastAPI's test client with WebSocket support:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from src.main import app


class TestChatWebSocket:
    @pytest.mark.asyncio
    async def test_ping_pong(self):
        """When the client sends a ping
        It should respond with a pong
        """
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            async with client.stream(
                method="GET",
                url="/api/v1/chat/ws/test-conv-id",
                headers={"connection": "upgrade", "upgrade": "websocket"},
            ) as response:
                # WebSocket test logic via test client
                pass

    @pytest.mark.asyncio
    async def test_query_streams_events(self):
        """When a query message is sent
        And the A2A agent responds with status and artifact events
        It should forward all events to the client
        """
        mock_events = [
            {"type": "status", "message": "Searching...", "state": "working"},
            {"type": "artifact", "data": {"response": "Results found."}},
        ]

        with patch(
            "src.services.chat.a2a_client_service.A2AClientService.send_query"
        ) as mock_send:
            async def mock_stream(query: str):
                for event in mock_events:
                    yield event

            mock_send.return_value = mock_stream(query="test")
            # Test WebSocket interaction
```

### 8.2 Frontend Composable Testing

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const mockWs = {
  send: vi.fn(),
  close: vi.fn(),
  readyState: WebSocket.OPEN,
  onopen: null as ((ev: Event) => void) | null,
  onmessage: null as ((ev: MessageEvent) => void) | null,
  onclose: null as ((ev: CloseEvent) => void) | null,
  onerror: null as ((ev: Event) => void) | null,
}

vi.stubGlobal('WebSocket', vi.fn(() => mockWs))

describe('useAgentStream', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('sends a JSON query over the WebSocket', async () => {
    const { useAgentStream } = await import('@/composables/useAgentStream')
    const { connect, sendQuery } = useAgentStream()

    connect('conv-123')
    mockWs.onopen?.({} as Event)

    sendQuery('What is metformin?')

    expect(mockWs.send).toHaveBeenCalledWith(
      JSON.stringify({ type: 'query', content: 'What is metformin?' }),
    )
  })

  it('dispatches status events to the store', async () => {
    const { useAgentStream } = await import('@/composables/useAgentStream')
    const { connect } = useAgentStream()

    connect('conv-123')
    mockWs.onopen?.({} as Event)

    const statusEvent: string = JSON.stringify({
      type: 'status',
      message: 'Searching PubMed...',
    })
    mockWs.onmessage?.({ data: statusEvent } as MessageEvent)

    const { useChatStore } = await import('@/stores/chat')
    const store = useChatStore()
    expect(store.statusMessages).toContain('Searching PubMed...')
  })
})
```

---

## 9. Checklist — Before Submitting a WebSocket Feature

### Backend
- [ ] WebSocket endpoint registered in `_initialize_routers`
- [ ] Controller uses `manager.connect()` and `manager.disconnect()`
- [ ] Every variable has a type hint on first assignment
- [ ] Every function call uses named arguments
- [ ] `WebSocketDisconnect` caught and handled cleanly
- [ ] Errors logged with `log_error(msg=..., e=...)`
- [ ] A2A client service yields normalized event dicts
- [ ] No business logic in the WebSocket controller

### Frontend
- [ ] Composable created with `use*` prefix
- [ ] WebSocket cleaned up in `onUnmounted`
- [ ] Reconnection with exponential backoff
- [ ] All event types handled in `switch` statement
- [ ] Every variable typed on first assignment
- [ ] Every function has typed parameters and return type
- [ ] Events dispatched to store, not local state
- [ ] TypeScript discriminated union for event types
