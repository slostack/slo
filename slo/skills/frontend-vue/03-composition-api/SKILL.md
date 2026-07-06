---
name: 03-composition-api
description: 'Vue tutorial: Vue 3 Composition API patterns.'
when_to_use: Use only for learning.
group: frontend-vue
kind: skill
source_prompt: vue-prompts/tutorial/03-composition-api.md
---

# Tutorial 3: The Composition API Deep Dive

## Skill summary

- **Name:** `03-composition-api`
- **Description:** Vue tutorial: Vue 3 Composition API patterns.
- **When to use:** Use only for learning.
- **Group:** `frontend-vue`
- **Kind:** `skill`
- **Source prompt:** `vue-prompts/tutorial/03-composition-api.md`

## Examples

- The user asks for help with: Vue tutorial: Vue 3 Composition API patterns.
- Use only for learning.

## Guidance

The Composition API is Vue 3's way of organizing component logic. If you have used Python
classes with methods grouped by concern rather than by type, you already understand the
motivation. The Composition API lets you group related state, computed values, and functions
together instead of scattering them across separate `data`, `methods`, and `computed` sections.

---

## 1. `<script setup>` -- The Magic Block

Every component in the Orders admin UI uses `<script setup lang="ts">`. This is a compile-time
convenience that does three things:

1. Everything you declare is automatically available in the template (no `return` statement).
2. Imported components are automatically registered.
3. It runs once when the component is created (like `__init__`).

From `ChatView.vue`:

```vue
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
```

Everything declared here -- `props`, `chat`, `connect`, `disconnect`, `sendQuery` -- is
usable in the template without any additional wiring. Compare this to a Python class:

```python
class ChatView:
    def __init__(self, conversation_id: str | None = None):
        self.conversation_id = conversation_id
        self.chat = ChatStore()
        self.stream = AgentStream()
```

The key difference: `<script setup>` does not need `self`. Variables are just `const`
declarations in the module scope, and Vue's compiler handles the rest.

---

## 2. `defineProps` -- Typed Component Contracts

Props are the inputs to a component. `defineProps` declares them with full TypeScript types.

### Simple Props

From `ChatInput.vue`:

```typescript
defineProps<{
  disabled: boolean
}>()
```

This declares a single required prop. In the template, you access it directly:

```vue
<textarea :disabled="disabled" />
<button :disabled="disabled || !inputText.trim()">
```

### Optional Props

From `ChatView.vue`:

```typescript
const props = defineProps<{
  conversationId?: string
}>()
```

The `?` makes `conversationId` optional. It will be `undefined` if the parent does not pass it.
Notice we assign the result to `props` -- this is necessary when you need to access props in the
script block (not just the template):

```typescript
onMounted(() => {
  if (props.conversationId) {
    chat.loadConversation(props.conversationId)
    connect(props.conversationId)
  }
})
```

### Props in the Template vs Script

In the template, you access props by name directly:

```vue
<template v-if="conversationId || chat.messages.length > 0">
```

In the script, you use the `props` object:

```typescript
if (props.conversationId) { ... }
```

Python comparison -- this is like the difference between instance attributes and explicit
`self.attribute` access:

```python
# In a method (script) -- explicit
if self.conversation_id:
    self.load_conversation(self.conversation_id)

# In a template (Jinja) -- implicit
{% if conversation_id %}
```

---

## 3. `defineEmits` -- Child-to-Parent Communication

Emits are the outputs of a component. They are typed event declarations.

From `ChatInput.vue`:

```typescript
const emit = defineEmits<{
  send: [content: string]
}>()
```

This declares that ChatInput can fire a `send` event carrying a `string` payload. Usage:

```typescript
function handleSubmit(): void {
  const content: string = inputText.value.trim()
  if (!content) return
  emit('send', content)
  inputText.value = ''
}
```

The parent listens with `@send`:

```vue
<!-- In ChatView.vue -->
<ChatInput :disabled="chat.isStreaming" @send="handleSend" />
```

Python comparison -- this is like a callback pattern:

```python
class ChatInput:
    def __init__(self, on_send: Callable[[str], None]):
        self._on_send = on_send

    def handle_submit(self):
        content = self.input_text.strip()
        if not content:
            return
        self._on_send(content)
        self.input_text = ''
```

The TypeScript generics ensure type safety: if you emit `'send'` with a number instead of a
string, the compiler catches it.

---

## 4. `ref` vs `reactive` -- When to Use Which

### `ref` -- Single Values

Use `ref` for primitives and for values you need to reassign entirely.

From `ChatInput.vue`:

```typescript
const inputText = ref<string>('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
```

From `stores/chat.ts`:

```typescript
const conversations = ref<Conversation[]>([])
const isLoading = ref<boolean>(false)
const isStreaming = ref<boolean>(false)
```

Access with `.value` in script code:

```typescript
inputText.value = ''
conversations.value = await api.conversations.list()
```

### `reactive` -- Objects

Use `reactive` for objects where you want to mutate properties directly without `.value`.
The Orders admin UI codebase favors `ref` consistently, which is the recommended approach for
new projects. Here is what `reactive` would look like:

```typescript
// Hypothetical reactive version (not used in the Orders admin UI)
const state = reactive({
  conversations: [] as Conversation[],
  isLoading: false,
  isStreaming: false,
})

// No .value needed
state.isLoading = true
state.conversations = await api.conversations.list()
```

### The Rule of Thumb

| Scenario | Use |
|---|---|
| Primitive (string, number, boolean) | `ref` |
| Array that gets reassigned | `ref` |
| Object that gets reassigned entirely | `ref` |
| Object where you only mutate properties | `reactive` (or `ref`, both work) |

The Orders admin UI uses `ref` everywhere, and that is perfectly fine. It is simpler to
remember one pattern.

---

## 5. `computed` -- Derived State

A `computed` property is a value derived from other reactive values. It automatically updates
and caches its result.

From `MarkdownRenderer.vue`:

```typescript
const props = defineProps<{
  source: string
}>()

const { render } = useMarkdown()

const html = computed<string>(() => {
  return render(props.source)
})
```

The template uses `html` directly:

```vue
<div class="markdown-content" v-html="html" />
```

Whenever `props.source` changes, `html` recalculates. If `props.source` has not changed
since the last access, Vue returns the cached result.

From `ChatPage.vue`:

```typescript
const route = useRoute()

const conversationId = computed<string | undefined>(() => {
  return route.params.conversationId as string | undefined
})
```

This derives the conversation ID from the current URL. When the URL changes, the computed
updates, which triggers the watcher in ChatView (see below).

Python comparison:

```python
@property
def conversation_id(self) -> str | None:
    return self.route.params.get("conversationId")
```

The difference: Vue's `computed` automatically tracks which reactive values are read inside
the function and only re-runs when those values change. A Python `@property` runs every time.

---

## 6. `watch` -- Reacting to Changes

`watch` observes one or more reactive sources and runs a callback when they change.

From `ChatView.vue`:

```typescript
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
```

This watches the `conversationId` prop. When it changes (the user navigates to a different
chat), the callback disconnects the old WebSocket and connects to the new one.

The callback receives both the new and old values, which is handy for comparison logic.

From `MessageList.vue`:

```typescript
watch(
  () => props.messages.length,
  () => {
    scrollToBottom()
  },
)
```

This watches just the message count. When a new message arrives, it scrolls the list to the
bottom. The watched expression is a getter function `() => props.messages.length` -- Vue
tracks that specific derived value.

From `stores/ui.ts`:

```typescript
watch(darkMode, (isDark: boolean) => {
  document.documentElement.setAttribute(
    'data-bs-theme',
    isDark ? 'dark' : 'light',
  )
}, { immediate: true })
```

The `{ immediate: true }` option means the callback runs once right away, not just on change.
This ensures the theme is set when the store is first created.

### `watchEffect` (Not Used in the Orders admin UI, but Good to Know)

`watchEffect` runs immediately and re-runs whenever any reactive dependency accessed inside it
changes:

```typescript
watchEffect(() => {
  console.log('Current ID:', currentConversationId.value)
  // Re-runs whenever currentConversationId changes
})
```

The difference from `watch`: you do not explicitly specify what to watch. Vue figures it out.

Python comparison -- `watch` is like a `__setattr__` hook or a `property.setter` that
triggers a side effect:

```python
@conversation_id.setter
def conversation_id(self, new_id: str):
    old_id = self._conversation_id
    self._conversation_id = new_id
    if new_id and new_id != old_id:
        self.disconnect()
        self.load_conversation(new_id)
        self.connect(new_id)
```

---

## 7. Template Refs -- Accessing DOM Elements

Sometimes you need a direct reference to a DOM element. Use `ref` with a matching `ref`
attribute in the template.

From `MessageList.vue`:

```typescript
const listRef = ref<HTMLDivElement | null>(null)

function scrollToBottom(): void {
  nextTick(() => {
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight
    }
  })
}
```

```vue
<div ref="listRef" class="message-list">
```

The `ref="listRef"` attribute tells Vue to assign the DOM element to the `listRef` variable
after the component mounts. The type is `HTMLDivElement | null` because it is `null` until
mounted.

`nextTick` waits for Vue to finish updating the DOM. This is necessary because Vue batches
DOM updates -- if you read `scrollHeight` immediately after pushing a new message, the DOM
might not have the new element yet.

Python comparison -- this is like getting a widget reference in a GUI framework:

```python
self.list_widget = tk.Frame(parent)
# later
self.list_widget.yview_moveto(1.0)  # scroll to bottom
```

---

## Key Takeaways

1. `<script setup>` eliminates boilerplate -- everything declared is template-accessible.
2. `defineProps` declares typed inputs; `defineEmits` declares typed outputs.
3. Use `ref` for almost everything. Access with `.value` in script, directly in template.
4. `computed` is a cached derived value that auto-tracks dependencies.
5. `watch` runs side effects when specific values change -- use it for API calls, WebSocket
   connections, or DOM manipulation.
6. Template refs (`ref="name"`) give you direct DOM access when needed.

---

## Try It Yourself

1. Open `ChatInput.vue`. The `inputText` ref is bound to the textarea with `v-model`. Try
   adding a `computed` that shows a character count below the input (e.g.,
   `const charCount = computed(() => inputText.value.length)`).

2. In `ChatView.vue`, the `watch` on `conversationId` includes the guard
   `newId && newId !== oldId`. Remove the `!== oldId` check and think about what would happen
   if the user clicked the same conversation again. Would it reconnect unnecessarily?

3. In `MessageList.vue`, the watcher observes `props.messages.length`. What would happen if
   you watched `props.messages` directly (the array reference)? Hint: the array reference does
   not change when items are pushed -- only `length` and contents change.

4. Create a simple countdown timer component. Use `ref<number>(10)` for the count,
   `onMounted` to start a `setInterval`, and `onUnmounted` to clear it. Display the count in
   the template and watch it tick down without manual DOM updates.
