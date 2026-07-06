---
name: 04-pinia-state-management
description: 'Vue tutorial: Pinia state management.'
when_to_use: Use only for learning.
group: frontend-vue
kind: skill
source_prompt: vue-prompts/tutorial/04-pinia-state-management.md
---

# Tutorial 4: State Management with Pinia

## Skill summary

- **Name:** `04-pinia-state-management`
- **Description:** Vue tutorial: Pinia state management.
- **When to use:** Use only for learning.
- **Group:** `frontend-vue`
- **Kind:** `skill`
- **Source prompt:** `vue-prompts/tutorial/04-pinia-state-management.md`

## Examples

- The user asks for help with: Vue tutorial: Pinia state management.
- Use only for learning.

## Guidance

Every non-trivial application needs shared state -- data that multiple components read and write.
In Python you might use module-level variables, a singleton class, or a framework like Redux. In
Vue 3, the standard answer is Pinia.

---

## 1. Why Pinia?

Consider the example chat app. The sidebar needs the list of conversations. The header needs
the current conversation title. The chat view needs messages. The streaming indicator needs
status messages. These components are not direct parent-child -- they live in different parts
of the component tree.

Without a store, you would have to pass data through multiple layers of props (called "prop
drilling"), which gets painful fast. Pinia gives you a central store that any component can
access directly.

Python comparison:

```python
# Module-level state (simple but not reactive)
conversations: list[Conversation] = []
current_id: str | None = None

# Or a singleton service class
class ChatService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
```

Pinia is like a reactive singleton service with built-in Vue integration.

---

## 2. Defining a Store -- The Setup Syntax

Open `web/src/stores/chat.ts`. The app uses the "setup" store syntax (as opposed to the
"options" syntax). It looks like a regular Composition API setup function:

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Conversation, Message, ConnectionStatus } from '@/types/chat'
import { api } from '@/api/client'

export const useChatStore = defineStore('chat', () => {
  // ... state, getters, and actions go here
  // ... return them at the end
})
```

`defineStore` takes two arguments:
1. A unique string ID (`'chat'`) -- like a table name in a database.
2. A setup function that returns the store's public API.

The naming convention `useChatStore` follows Vue's composable pattern (prefixed with `use`).

---

## 3. State -- Reactive Data

State is declared with `ref()`, just like in a component:

```typescript
const conversations = ref<Conversation[]>([])
const currentConversationId = ref<string | null>(null)
const messages = ref<Message[]>([])
const isLoading = ref<boolean>(false)
const isStreaming = ref<boolean>(false)
const statusMessages = ref<string[]>([])
const connectionStatus = ref<ConnectionStatus>('disconnected')
```

Each of these is a reactive value. When you change `isLoading.value = true`, every component
that reads `chat.isLoading` will re-render.

Python comparison -- these are like typed instance attributes in a dataclass:

```python
@dataclass
class ChatState:
    conversations: list[Conversation] = field(default_factory=list)
    current_conversation_id: str | None = None
    messages: list[Message] = field(default_factory=list)
    is_loading: bool = False
    is_streaming: bool = False
    status_messages: list[str] = field(default_factory=list)
    connection_status: ConnectionStatus = 'disconnected'
```

---

## 4. Getters -- Computed Properties

Getters are `computed` values derived from state:

```typescript
const currentConversation = computed<Conversation | undefined>(() => {
  return conversations.value.find(
    (c: Conversation) => c.id === currentConversationId.value,
  )
})

const sortedConversations = computed<Conversation[]>(() => {
  return [...conversations.value].sort(
    (a: Conversation, b: Conversation) =>
      new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
  )
})
```

`currentConversation` looks up the active conversation by ID. `sortedConversations` returns
conversations ordered by most recently updated. Both are cached and only recalculate when
their dependencies change.

Python comparison:

```python
@property
def current_conversation(self) -> Conversation | None:
    return next(
        (c for c in self.conversations if c.id == self.current_conversation_id),
        None
    )

@property
def sorted_conversations(self) -> list[Conversation]:
    return sorted(self.conversations, key=lambda c: c.updated_at, reverse=True)
```

In the Header component, the getter is used to display the conversation title:

```vue
<!-- Header.vue -->
<span>{{ chat.currentConversation?.title ?? 'Orders Admin' }}</span>
```

The `?.` safely handles the case where no conversation is selected.

---

## 5. Actions -- Methods That Mutate State

Actions are regular functions that change state. They can be synchronous or async.

### Async Action -- Loading Data

```typescript
async function loadConversations(): Promise<void> {
  try {
    conversations.value = await api.conversations.list()
  } catch (error: unknown) {
    console.error('Failed to load conversations:', error)
  }
}
```

This fetches conversations from the API and replaces the state. The `try/catch` prevents the
app from crashing on network errors.

### Async Action with Loading State

```typescript
async function loadConversation(id: string): Promise<void> {
  try {
    isLoading.value = true
    const conversation: Conversation = await api.conversations.get(id)
    currentConversationId.value = id
    messages.value = conversation.messages ?? []

    const existingIndex: number = conversations.value.findIndex(
      (c: Conversation) => c.id === id,
    )
    if (existingIndex >= 0) {
      conversations.value[existingIndex] = conversation
    } else {
      conversations.value.push(conversation)
    }
  } catch (error: unknown) {
    console.error('Failed to load conversation:', error)
  } finally {
    isLoading.value = false
  }
}
```

Notice the pattern:
1. Set `isLoading` to `true`
2. Perform the async operation
3. Update state with the result
4. Set `isLoading` to `false` in `finally` (runs even if there is an error)

This is identical to how you would write a Python service method:

```python
async def load_conversation(self, id: str) -> None:
    try:
        self.is_loading = True
        conversation = await api.conversations.get(id)
        self.current_conversation_id = id
        self.messages = conversation.messages or []
    except Exception as error:
        print(f"Failed to load conversation: {error}")
    finally:
        self.is_loading = False
```

### Sync Action -- Mutating State

```typescript
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
```

This creates a message object, pushes it to the messages array, and returns it. The UI
updates instantly because `messages` is reactive.

### Action -- Delete with Cascading State Update

```typescript
async function deleteConversation(id: string): Promise<void> {
  await api.conversations.delete(id)
  conversations.value = conversations.value.filter(
    (c: Conversation) => c.id !== id,
  )
  if (currentConversationId.value === id) {
    currentConversationId.value = null
    messages.value = []
  }
}
```

After the API call, the function removes the conversation from the local array and clears
the current selection if the deleted conversation was active. This keeps the UI consistent.

---

## 6. The Return Statement

The setup function ends by returning everything that should be public:

```typescript
return {
  // State
  conversations,
  currentConversationId,
  messages,
  isLoading,
  isStreaming,
  statusMessages,
  connectionStatus,
  // Getters
  currentConversation,
  sortedConversations,
  // Actions
  loadConversations,
  loadConversation,
  createConversation,
  deleteConversation,
  renameConversation,
  addUserMessage,
  addAssistantMessage,
  addStatusMessage,
  clearStatusMessages,
  setStreaming,
  setConnectionStatus,
  setCurrentConversation,
}
```

Anything not returned is private to the store. This is like Python's `__all__` for module
exports, or like making methods private by prefixing with `_`.

---

## 7. Using Stores in Components

Any component can access the store by calling the `use` function:

```typescript
// Sidebar.vue
const chat = useChatStore()

// Access state
chat.conversations
chat.currentConversationId

// Access getters
chat.sortedConversations
chat.currentConversation

// Call actions
await chat.loadConversations()
await chat.deleteConversation(id)
```

In the template:

```vue
<div v-for="conversation in chat.sortedConversations" :key="conversation.id">
  {{ conversation.title ?? 'Untitled' }}
</div>
```

The store is reactive. When any action modifies state, every component reading that state
re-renders automatically.

---

## 8. The UI Store -- A Simpler Example

`web/src/stores/ui.ts` is a minimal store that manages sidebar and theme state:

```typescript
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export const useUiStore = defineStore('ui', () => {
  const sidebarOpen = ref<boolean>(true)
  const darkMode = ref<boolean>(false)

  function toggleSidebar(): void {
    sidebarOpen.value = !sidebarOpen.value
  }

  function toggleDarkMode(): void {
    darkMode.value = !darkMode.value
  }

  watch(darkMode, (isDark: boolean) => {
    document.documentElement.setAttribute(
      'data-bs-theme',
      isDark ? 'dark' : 'light',
    )
  }, { immediate: true })

  return {
    sidebarOpen,
    darkMode,
    toggleSidebar,
    toggleDarkMode,
  }
})
```

Notice the `watch` inside the store. When `darkMode` changes, it updates the HTML root
element's `data-bs-theme` attribute, which triggers Bootstrap's dark mode CSS. This is a
side effect that belongs in the store, not in any particular component.

Used in `Header.vue`:

```vue
<button @click="ui.toggleDarkMode()">
  <svg v-if="!ui.darkMode"><!-- moon icon --></svg>
  <svg v-else><!-- sun icon --></svg>
</button>
```

And in `AppLayout.vue`:

```vue
<Sidebar :class="{ collapsed: !ui.sidebarOpen }" />
```

Two different components reading from the same store. Change the state once, both update.

---

## 9. Installing Pinia

In `main.ts`, Pinia is installed as a Vue plugin:

```typescript
import { createPinia } from 'pinia'

const app = createApp(App)
app.use(createPinia())
```

This is a one-time setup. After this, any component can call `useChatStore()` or
`useUiStore()` without additional configuration.

---

## Key Takeaways

1. Pinia stores are reactive singletons -- shared state accessible from any component.
2. The setup syntax uses `ref` for state, `computed` for getters, and plain functions for
   actions.
3. Actions can be async and should handle errors with `try/catch/finally`.
4. The `return` statement controls what is public vs private.
5. Components access stores with `const store = useXxxStore()` and read/write just like
   regular reactive objects.
6. Watchers inside stores can trigger side effects (like updating DOM attributes for themes).

---

## Try It Yourself

1. Trace the flow of creating a new conversation. Start at `Sidebar.vue`'s `handleNewChat`,
   follow it into `chat.createConversation()`, and see how the new conversation appears in
   the sidebar list (because `conversations` is reactive).

2. In the chat store, look at `setStreaming`. Notice that when streaming ends
   (`value = false`), it also clears status messages. This prevents stale status from showing
   up in the next query.

3. Try adding a `messageCount` getter to the chat store:
   ```typescript
   const messageCount = computed<number>(() => messages.value.length)
   ```
   Return it from the store, then display it in the Header component next to the conversation
   title.

4. The UI store does not persist dark mode across page reloads. Think about how you would add
   `localStorage` persistence: save to `localStorage` in the `watch` callback, and read from
   `localStorage` when initializing the `darkMode` ref.
