---
name: vue-coding-conventions
description: Mandatory Vue 3 / TypeScript conventions for this workspace.
when_to_use: Read before any Vue work — covers Composition API, type hints, naming,
  prop patterns.
group: frontend-vue
kind: skill
source_prompt: vue-prompts/vue-coding-conventions.md
---

# Vue + TypeScript Coding Conventions

## Skill summary

- **Name:** `vue-coding-conventions`
- **Description:** Mandatory Vue 3 / TypeScript conventions for this workspace.
- **When to use:** Read before any Vue work — covers Composition API, type hints, naming, prop patterns.
- **Group:** `frontend-vue`
- **Kind:** `skill`
- **Source prompt:** `vue-prompts/vue-coding-conventions.md`

## Examples

- The user asks for help with: Mandatory Vue 3 / TypeScript conventions for this workspace.
- Read before any Vue work — covers Composition API, type hints, naming, prop patterns.

## Guidance

This document defines the mandatory coding conventions for the Vue 3 / TypeScript frontend. These conventions mirror the Python backend's emphasis on explicit type annotations, named arguments, declarative structure, and clear file organization.

---

## 1. Project Structure

The frontend lives under `web/src/` with the following layout:

```
web/src/
├── api/                  # API client and typed request/response
│   ├── client.ts         # HTTP client with typed methods
│   └── types.ts          # API-specific interfaces (request/response shapes)
├── components/           # Reusable UI components, grouped by feature
│   ├── chat/             # Chat feature components
│   │   ├── ChatView.vue
│   │   ├── MessageList.vue
│   │   ├── MessageBubble.vue
│   │   ├── ChatInput.vue
│   │   └── StreamingIndicator.vue
│   └── layout/           # Layout shell components
│       ├── AppLayout.vue
│       ├── Header.vue
│       └── Sidebar.vue
├── composables/          # Stateful logic extracted from components
│   ├── useAgentStream.ts
│   └── useMarkdown.ts
├── router/               # Vue Router configuration
│   └── index.ts
├── stores/               # Pinia state stores
│   ├── chat.ts
│   └── ui.ts
├── types/                # Shared TypeScript interfaces and type aliases
│   └── chat.ts
├── views/                # Route-level page components
│   ├── ChatPage.vue
│   └── SettingsPage.vue
├── App.vue
└── main.ts
```

### Naming Conventions

| Item | Convention | Example |
|---|---|---|
| **Components** | PascalCase `.vue` files | `MessageBubble.vue`, `ChatInput.vue` |
| **Composables** | camelCase with `use` prefix | `useAgentStream.ts`, `useMarkdown.ts` |
| **Stores** | camelCase, named after the domain | `chat.ts`, `ui.ts` |
| **Type files** | camelCase | `chat.ts`, `api.ts` |
| **Directories** | kebab-case (when multi-word) | `components/chat/`, `api/` |
| **Views** | PascalCase with `Page` suffix | `ChatPage.vue`, `SettingsPage.vue` |

### File Grouping Rules

| Rule | Detail |
|---|---|
| **Group by feature** | Components for a feature live in a subdirectory under `components/` (e.g., `components/chat/`) |
| **One component per file** | Never define multiple components in a single `.vue` file |
| **Colocate types** | If a type is used by only one file, define it in that file. If shared across files, put it in `types/` |
| **Views are thin** | View components compose feature components and connect to stores. They contain minimal logic. |

---

## 2. Component Conventions

### 2.1 Always Use `<script setup lang="ts">`

Every component must use the Composition API with `<script setup>`. The Options API is not permitted.

```vue
<!-- Good -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Message } from '@/types/chat'

const props = defineProps<{
  message: Message
}>()

const isExpanded = ref<boolean>(false)
</script>

<!-- Bad: Options API -->
<script lang="ts">
export default {
  props: {
    message: { type: Object, required: true }
  },
  data() {
    return { isExpanded: false }
  }
}
</script>
```

### 2.2 Typed Props and Emits

Props and emits must use TypeScript generics with `defineProps` and `defineEmits`. Never use the runtime declaration (object syntax).

```vue
<script setup lang="ts">
// Good: TypeScript-first props with defaults
const props = withDefaults(
  defineProps<{
    title: string
    subtitle?: string
    isActive: boolean
    count: number
  }>(),
  {
    subtitle: '',
    isActive: false,
    count: 0,
  },
)

// Good: Typed emits
const emit = defineEmits<{
  send: [content: string]
  cancel: []
  update: [id: string, value: number]
}>()

// Bad: runtime props
const props = defineProps({
  title: String,
  isActive: Boolean,
})
```

### 2.3 Template Structure

Templates follow this order:

1. Structural directives (`v-if`, `v-for`) first
2. Dynamic attributes (`:class`, `:style`)
3. Event handlers (`@click`, `@submit`)
4. Static attributes

```vue
<template>
  <div
    v-if="isVisible"
    :class="['message-bubble', message.role]"
    @click="handleClick"
    data-testid="message-bubble"
  >
    <slot />
  </div>
</template>
```

### 2.4 Script Block Ordering

Within `<script setup>`, follow this order:

1. Imports (Vue, then libraries, then local)
2. Props and emits
3. Store and composable usage
4. Reactive state (`ref`, `reactive`)
5. Computed properties
6. Watchers
7. Functions
8. Lifecycle hooks

```vue
<script setup lang="ts">
// 1. Imports
import { ref, computed, watch, onMounted } from 'vue'
import type { Message } from '@/types/chat'
import { useChatStore } from '@/stores/chat'

// 2. Props and emits
const props = defineProps<{
  conversationId: string
}>()

const emit = defineEmits<{
  loaded: []
}>()

// 3. Store usage
const chat = useChatStore()

// 4. Reactive state
const isExpanded = ref<boolean>(false)
const searchQuery = ref<string>('')

// 5. Computed
const filteredMessages = computed<Message[]>(() => {
  return chat.messages.filter(
    (m: Message) => m.content.includes(searchQuery.value),
  )
})

// 6. Watchers
watch(
  () => props.conversationId,
  (newId: string) => {
    chat.loadConversation(newId)
  },
)

// 7. Functions
function handleToggle(): void {
  isExpanded.value = !isExpanded.value
}

// 8. Lifecycle
onMounted(() => {
  emit('loaded')
})
</script>
```

### 2.5 Scoped Styles

Styles must be scoped to the component. Use `<style scoped>` or `<style scoped lang="scss">`. Global styles go in a dedicated stylesheet, never in a component.

```vue
<style scoped lang="scss">
.message-bubble {
  padding: var(--app-spacing-md);
  border-radius: var(--app-radius);

  &.user {
    background-color: var(--app-user-bg);
  }

  &.assistant {
    background-color: var(--app-assistant-bg);
  }
}
</style>
```

---

## 3. TypeScript Strictness

### 3.1 Explicit Type Annotations on ALL Variables at First Assignment

This is the single most important convention. Every variable must have an explicit type annotation when it is first declared or assigned. This mirrors the Python convention `result: str = await func()`.

```typescript
// Good: explicit type on every assignment
const isLoading = ref<boolean>(false)
const messages = ref<Message[]>([])
const currentId = ref<string | null>(null)
const response: Response = await fetch(url)
const body: ApiResponse<T> = await response.json()
const index: number = items.findIndex((item: Message) => item.id === id)
const filtered: Message[] = messages.filter((m: Message) => m.role === 'user')

// Bad: missing type annotations
const isLoading = ref(false)
const messages = ref([])
const response = await fetch(url)
const body = await response.json()
const index = items.findIndex(item => item.id === id)
```

### 3.2 Function Signatures

Every function must have parameter types and an explicit return type. Every callback and lambda must type its parameters.

```typescript
// Good
function handleSend(content: string): void {
  sendQuery(content)
}

async function loadConversation(id: string): Promise<void> {
  const conversation: Conversation = await api.conversations.get(id)
  messages.value = conversation.messages ?? []
}

const sortedItems = computed<Conversation[]>(() => {
  return [...conversations.value].sort(
    (a: Conversation, b: Conversation) =>
      new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
  )
})

// Bad: missing return types and parameter types
function handleSend(content) {
  sendQuery(content)
}

async function loadConversation(id) {
  const conversation = await api.conversations.get(id)
}

const sortedItems = computed(() => {
  return [...conversations.value].sort((a, b) =>
    new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
  )
})
```

### 3.3 Interface-First Design

Define interfaces before using them. Prefer interfaces over inline type literals for any shape used more than once.

```typescript
// Good: interfaces in types/chat.ts
export interface Message {
  id: string
  conversationId: string
  role: 'user' | 'assistant'
  content: string
  meta?: {
    statusHistory?: string[]
  }
  createdAt: string
}

export interface Conversation {
  id: string
  title: string | null
  createdAt: string
  updatedAt: string
  messages?: Message[]
}

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error'
```

### 3.4 No `any`

Never use `any`. Use `unknown` for truly unknown types and narrow with type guards.

```typescript
// Good
function parseEvent(raw: unknown): WebSocketEvent {
  if (typeof raw !== 'object' || raw === null) {
    throw new Error('Invalid event data')
  }
  return raw as WebSocketEvent
}

catch (error: unknown) {
  console.error('Failed to parse:', error)
}

// Bad
function parseEvent(raw: any): any {
  return raw
}

catch (error: any) {
  console.error(error.message)
}
```

### 3.5 Discriminated Unions for Event Types

Use discriminated unions with a `type` field for events and message variants. This provides exhaustive type checking in `switch` statements.

```typescript
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

export type WebSocketEvent = A2AStatusEvent | A2AArtifactEvent | A2AErrorEvent

// Exhaustive handling
function handleEvent(event: WebSocketEvent): void {
  switch (event.type) {
    case 'status':
      store.addStatusMessage(event.message)
      break
    case 'artifact': {
      const responseText: string = event.data?.response ?? ''
      store.addAssistantMessage(responseText)
      break
    }
    case 'error':
      console.error('Agent error:', event.message)
      break
  }
}
```

---

## 4. State Management — Pinia

### 4.1 Setup Syntax Only

Always use the setup function syntax (`defineStore('name', () => { ... })`). Never use the options syntax.

```typescript
// Good: setup syntax
export const useChatStore = defineStore('chat', () => {
  const messages = ref<Message[]>([])
  const isLoading = ref<boolean>(false)

  async function loadConversation(id: string): Promise<void> {
    isLoading.value = true
    // ...
  }

  return {
    messages,
    isLoading,
    loadConversation,
  }
})

// Bad: options syntax
export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [],
    isLoading: false,
  }),
  actions: {
    async loadConversation(id) { /* ... */ },
  },
})
```

### 4.2 Store Structure

Stores follow this internal order:

1. Reactive state (`ref`, `reactive`)
2. Computed properties (derived state)
3. Actions (functions that modify state)
4. Return statement (explicit public API)

```typescript
export const useChatStore = defineStore('chat', () => {
  // 1. State
  const conversations = ref<Conversation[]>([])
  const currentConversationId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const isStreaming = ref<boolean>(false)

  // 2. Computed
  const currentConversation = computed<Conversation | undefined>(() => {
    return conversations.value.find(
      (c: Conversation) => c.id === currentConversationId.value,
    )
  })

  // 3. Actions
  async function loadConversation(id: string): Promise<void> {
    const conversation: Conversation = await api.conversations.get(id)
    currentConversationId.value = id
    messages.value = conversation.messages ?? []
  }

  function addUserMessage(content: string): Message {
    const message: Message = {
      id: crypto.randomUUID(),
      conversationId: currentConversationId.value ?? '',
      role: 'user',
      content,
      createdAt: new Date().toISOString(),
    }
    messages.value.push(message)
    return message
  }

  // 4. Return — explicit public API
  return {
    conversations,
    currentConversationId,
    messages,
    isStreaming,
    currentConversation,
    loadConversation,
    addUserMessage,
  }
})
```

### 4.3 Store Rules

| Rule | Detail |
|---|---|
| **One store per domain** | `chat.ts`, `ui.ts`, `auth.ts` — not one giant store |
| **Typed refs** | `ref<boolean>(false)`, not `ref(false)` |
| **Typed computed** | `computed<Message[]>(() => ...)`, not `computed(() => ...)` |
| **Return everything used externally** | The return object is the store's public API. Anything not returned is private. |
| **No direct mutation from components** | Components call store actions, not `store.messages.value.push(...)` |

---

## 5. Composables

### 5.1 Naming and Structure

Composables are functions prefixed with `use` that encapsulate stateful logic. They live in `composables/`.

```typescript
// composables/useAgentStream.ts

import { ref, onUnmounted } from 'vue'
import type { WebSocketEvent, ConnectionStatus } from '@/types/chat'
import { useChatStore } from '@/stores/chat'

export function useAgentStream() {
  const store = useChatStore()
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  const reconnectAttempts = ref<number>(0)

  function connect(conversationId: string): void {
    // ...
  }

  function disconnect(): void {
    // ...
  }

  function sendQuery(content: string): void {
    // ...
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connect,
    disconnect,
    sendQuery,
    reconnectAttempts,
  }
}
```

### 5.2 Composable Rules

| Rule | Detail |
|---|---|
| **`use` prefix** | Always: `useAgentStream`, `useMarkdown`, `useAuth` |
| **Explicit return type shape** | The returned object is the composable's public API |
| **Lifecycle cleanup** | If the composable sets up timers, listeners, or connections, clean them up in `onUnmounted` |
| **Type all internal state** | `ref<number>(0)`, `ref<WebSocket | null>(null)` |
| **Type all function parameters and returns** | `function connect(conversationId: string): void` |
| **No side effects at import time** | Side effects happen inside the function body, not at module scope |

---

## 6. API Layer

### 6.1 Typed Client

The API client lives in `api/client.ts`. All requests go through a single `request<T>` function that handles the response envelope.

```typescript
import type { Conversation, Message } from '@/types/chat'

const API_BASE = '/api/v1'

interface ApiResponse<T> {
  data: T
  api_version: string
  errors: {
    msg: string[]
    code: string | null
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url: string = `${API_BASE}${path}`
  const response: Response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const errorBody: ApiResponse<unknown> = await response.json().catch(() => ({} as ApiResponse<unknown>))
    const errorMessage: string = errorBody?.errors?.msg?.[0] ?? `Request failed: ${response.status}`
    throw new Error(errorMessage)
  }

  const body: ApiResponse<T> = await response.json()
  return body.data
}
```

### 6.2 API Method Organization

Group API methods by resource, mirroring the backend's controller structure:

```typescript
export const api = {
  conversations: {
    async list(page: number = 1): Promise<Conversation[]> {
      return request<Conversation[]>(`/conversations?page=${page}`)
    },

    async get(id: string): Promise<Conversation> {
      return request<Conversation>(`/conversations/${id}`)
    },

    async create(title?: string): Promise<Conversation> {
      return request<Conversation>('/conversations', {
        method: 'POST',
        body: JSON.stringify({ title }),
      })
    },

    async delete(id: string): Promise<void> {
      await request<unknown>(`/conversations/${id}`, {
        method: 'DELETE',
      })
    },
  },
}
```

### 6.3 API Rules

| Rule | Detail |
|---|---|
| **Single `request<T>` function** | All HTTP requests go through one function that handles the `ApiResponse<T>` envelope |
| **Typed return values** | Every API method declares its return type: `Promise<Conversation[]>`, `Promise<void>` |
| **Error handling at the client level** | The `request` function throws on non-OK responses. Callers catch in `try/catch`. |
| **API types mirror backend DAOs** | The `types/` interfaces match the backend's Pydantic DAOs |
| **No raw `fetch` in components** | Components use `api.*` methods, never `fetch()` directly |

---

## 7. Styling

### 7.1 Priority Order

1. **Bootstrap utility classes** for spacing, flexbox, typography, visibility
2. **CSS custom properties** for theming (`var(--app-*)`)
3. **Scoped SCSS** for component-specific layouts and states

```vue
<template>
  <!-- Bootstrap utilities for layout -->
  <div class="d-flex flex-column gap-3 p-3">
    <h2 class="fs-4 fw-semibold mb-0">{{ title }}</h2>
    <!-- Custom properties for theme-aware colors -->
    <p class="text-muted" style="color: var(--app-text-muted)">
      {{ subtitle }}
    </p>
  </div>
</template>

<style scoped lang="scss">
// Component-specific styles only when Bootstrap utilities aren't enough
.message-bubble {
  border-radius: var(--app-radius);
  transition: background-color 0.2s ease;

  &.user {
    background-color: var(--app-user-bg);
  }
}
</style>
```

### 7.2 CSS Custom Properties

Define theme tokens as CSS custom properties. Components reference these instead of hardcoded colors.

```css
:root {
  --app-bg: #1a1a2e;
  --app-surface: #16213e;
  --app-text: #e0e0e0;
  --app-text-muted: #8892b0;
  --app-accent: #64ffda;
  --app-border: #2d3748;
  --app-radius: 0.5rem;
  --app-spacing-sm: 0.5rem;
  --app-spacing-md: 1rem;
  --app-spacing-lg: 1.5rem;
  --app-user-bg: #1e3a5f;
  --app-assistant-bg: #1a1a2e;
}
```

### 7.3 Styling Rules

| Rule | Detail |
|---|---|
| **No inline styles except simple one-offs** | Use classes or custom properties |
| **`<style scoped>`** | Always scoped. Global styles in a dedicated file. |
| **Bootstrap first** | Use `d-flex`, `gap-2`, `p-3`, `mt-2` before writing custom CSS |
| **Custom properties for colors** | Never hardcode colors in components. Use `var(--app-*)` |
| **No `!important`** | If you need `!important`, the selector specificity is wrong |

---

## 8. Testing

### 8.1 Component Testing

Use Vitest + Vue Test Utils. Tests live alongside their source in `__tests__/` directories or in a parallel `tests/` tree.

```typescript
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import MessageBubble from '@/components/chat/MessageBubble.vue'
import type { Message } from '@/types/chat'

describe('MessageBubble', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders user message content', () => {
    const message: Message = {
      id: '1',
      conversationId: 'conv-1',
      role: 'user',
      content: 'What is metformin used for?',
      createdAt: new Date().toISOString(),
    }

    const wrapper = mount(MessageBubble, {
      props: { message },
    })

    expect(wrapper.text()).toContain('What is metformin used for?')
    expect(wrapper.find('.message-bubble').classes()).toContain('user')
  })

  it('renders assistant message with markdown', () => {
    const message: Message = {
      id: '2',
      conversationId: 'conv-1',
      role: 'assistant',
      content: '**Metformin** is a medication used to treat type 2 diabetes.',
      createdAt: new Date().toISOString(),
    }

    const wrapper = mount(MessageBubble, {
      props: { message },
    })

    expect(wrapper.find('.message-bubble').classes()).toContain('assistant')
  })

  it('shows research steps when meta.statusHistory is present', () => {
    const message: Message = {
      id: '3',
      conversationId: 'conv-1',
      role: 'assistant',
      content: 'Results found.',
      meta: {
        statusHistory: ['Searching PubMed...', 'Analyzing results...'],
      },
      createdAt: new Date().toISOString(),
    }

    const wrapper = mount(MessageBubble, {
      props: { message },
    })

    expect(wrapper.find('details').exists()).toBe(true)
    expect(wrapper.findAll('li')).toHaveLength(2)
  })
})
```

### 8.2 Store Testing

Test stores in isolation using `createPinia()` and `setActivePinia()`.

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useChatStore } from '@/stores/chat'
import type { Message, Conversation } from '@/types/chat'

describe('useChatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('adds a user message', () => {
    const store = useChatStore()
    store.setCurrentConversation('conv-1')

    const message: Message = store.addUserMessage('Hello')

    expect(message.role).toBe('user')
    expect(message.content).toBe('Hello')
    expect(store.messages).toHaveLength(1)
  })

  it('clears status messages when streaming ends', () => {
    const store = useChatStore()
    store.addStatusMessage('Searching...')
    store.addStatusMessage('Analyzing...')

    expect(store.statusMessages).toHaveLength(2)

    store.setStreaming(false)

    expect(store.statusMessages).toHaveLength(0)
  })
})
```

### 8.3 Composable Testing

Test composables by wrapping them in a component or using a test helper.

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// Mock WebSocket before importing the composable
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

  it('sends a JSON query message over the WebSocket', async () => {
    const { useAgentStream } = await import('@/composables/useAgentStream')
    // Test logic here
  })
})
```

### 8.4 Testing Rules

| Rule | Detail |
|---|---|
| **Type test data** | `const message: Message = { ... }`, not `const message = { ... }` |
| **Named arguments in test utilities** | `mount(Component, { props: { message } })` |
| **One behavior per test** | Each `it()` tests one thing |
| **Descriptive test names** | `it('clears status messages when streaming ends')`, not `it('works')` |
| **Mock at boundaries** | Mock API calls, WebSocket, timers. Don't mock Vue internals. |

---

## 9. Import Conventions

### 9.1 Absolute Paths with `@/` Alias

Always use the `@/` alias for project imports. Never use relative paths.

```typescript
// Good: absolute imports
import { useChatStore } from '@/stores/chat'
import type { Message } from '@/types/chat'
import MessageBubble from '@/components/chat/MessageBubble.vue'

// Bad: relative imports
import { useChatStore } from '../../stores/chat'
import type { Message } from '../types/chat'
```

### 9.2 Import Grouping

Group imports in this order, separated by blank lines:

1. Vue core (`vue`, `vue-router`, `pinia`)
2. Third-party libraries
3. Local types (using `import type`)
4. Local modules (stores, composables, api)
5. Local components

```vue
<script setup lang="ts">
// 1. Vue core
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'

// 2. Third-party (if any)
import { marked } from 'marked'

// 3. Local types
import type { Message, Conversation, ConnectionStatus } from '@/types/chat'

// 4. Local modules
import { useChatStore } from '@/stores/chat'
import { useAgentStream } from '@/composables/useAgentStream'
import { api } from '@/api/client'

// 5. Local components
import MessageList from '@/components/chat/MessageList.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
</script>
```

### 9.3 Import Rules

| Rule | Detail |
|---|---|
| **Use `import type` for type-only imports** | `import type { Message } from '@/types/chat'` |
| **No barrel exports** | Don't create `index.ts` re-export files. Import directly from the source file. |
| **No default exports for non-components** | Stores, composables, and utilities use named exports. Only `.vue` components use default exports (implicit in `<script setup>`). |
| **Never import from `node_modules` paths** | Use package names: `import { ref } from 'vue'`, not `from 'node_modules/vue'` |

---

## 10. Summary Checklist

Before submitting any Vue/TypeScript code, verify:

- [ ] Every variable has an explicit type annotation on first assignment
- [ ] Every function has typed parameters and an explicit return type
- [ ] Every callback/lambda types its parameters
- [ ] No `any` — use `unknown` with type guards instead
- [ ] Components use `<script setup lang="ts">` exclusively
- [ ] Props and emits use TypeScript generics (`defineProps<{...}>()`)
- [ ] Stores use the setup syntax (`defineStore('name', () => { ... })`)
- [ ] All refs are typed: `ref<boolean>(false)`, `ref<Message[]>([])`
- [ ] All computed are typed: `computed<string>(() => ...)`
- [ ] Imports use `@/` absolute paths, not relative paths
- [ ] Type-only imports use `import type`
- [ ] Styles are scoped
- [ ] CSS custom properties used for colors, not hardcoded values
- [ ] Tests type their test data and use named arguments
- [ ] Select `build-websocket-endpoints` or `build-sse-endpoints` from the actual browser transport; do not treat LangGraph graph streaming as browser SSE
- [ ] Preserve real API versus mock client boundaries when the application has both
- [ ] Keep user content escaped; use assistant `v-html` only after a constrained, tested renderer (for example, `html: false`)
- [ ] Run `vue-tsc -b` or the project's strict equivalent separately from Vitest when configured
