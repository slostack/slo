---
name: 01-vue-fundamentals
description: 'Vue tutorial: Vue 3 fundamentals (templates, directives, reactivity
  basics).'
when_to_use: Use only for learning, not as a convention reference.
group: frontend-vue
kind: skill
source_prompt: vue-prompts/tutorial/01-vue-fundamentals.md
---

# Tutorial 1: Vue 3 Fundamentals for Python Developers

## Skill summary

- **Name:** `01-vue-fundamentals`
- **Description:** Vue tutorial: Vue 3 fundamentals (templates, directives, reactivity basics).
- **When to use:** Use only for learning, not as a convention reference.
- **Group:** `frontend-vue`
- **Kind:** `skill`
- **Source prompt:** `vue-prompts/tutorial/01-vue-fundamentals.md`

## Examples

- The user asks for help with: Vue tutorial: Vue 3 fundamentals (templates, directives, reactivity basics).
- Use only for learning, not as a convention reference.

## Guidance

Welcome to the Orders admin UI codebase. If you have been writing Python and are now staring at `.vue`
files wondering what is going on, this tutorial is for you. We will map every Vue concept to
something you already know from Python, using real code from this project.

---

## 1. Single File Components -- The `.vue` File

In Python you organize code into modules (`.py` files). A module can contain a class, its methods,
and maybe some module-level constants. A Vue Single File Component (SFC) does something similar
but splits a component into three co-located sections:

```
<script setup lang="ts">   <!-- Logic  (like the class body)   -->
<template>                 <!-- HTML    (the render output)     -->
<style>                    <!-- CSS     (visual presentation)   -->
```

Open `web/src/App.vue`, the simplest SFC in the project:

```vue
<script setup lang="ts">
import AppLayout from '@/components/layout/AppLayout.vue'
</script>

<template>
  <AppLayout />
</template>
```

That is the entire root component. It imports another component and renders it. Compare this to
Python, where you might write:

```python
# app.py
from components.layout import AppLayout

class App:
    def render(self):
        return AppLayout().render()
```

The mental model is the same: import a dependency, use it. The difference is that Vue uses an
HTML-like `<template>` block instead of a `render()` method.

---

## 2. Template Syntax

Vue templates look like HTML with superpowers. Here is a side-by-side comparison with Python
(Jinja2 templates, which you may have seen in Flask or FastAPI).

### Displaying Data -- `{{ }}`

```vue
<!-- Vue -->
<span>{{ chat.currentConversation?.title ?? 'Orders Admin' }}</span>
```

```python
# Jinja2
<span>{{ chat.current_conversation.title or 'Orders Admin' }}</span>
```

The double-curly-brace syntax is identical. Inside the braces you write JavaScript expressions
(not Python), but the idea is the same.

### Conditionals -- `v-if` / `v-else`

From `ChatView.vue`:

```vue
<template v-if="conversationId || chat.messages.length > 0">
  <MessageList :messages="chat.messages" />
  <StreamingIndicator v-if="chat.isStreaming" :status-messages="chat.statusMessages" />
</template>
<template v-else>
  <div class="empty-state">
    <h2>Orders Admin Assistant</h2>
    <p>Ask a question about an order to search for the relevant records.</p>
  </div>
</template>
```

Python equivalent thinking:

```python
if conversation_id or len(chat.messages) > 0:
    render(MessageList(messages=chat.messages))
    if chat.is_streaming:
        render(StreamingIndicator(status_messages=chat.status_messages))
else:
    render("<div class='empty-state'>...</div>")
```

`v-if` is the `if` statement. `v-else` is the `else`. There is also `v-else-if`.

### Loops -- `v-for`

From `MessageList.vue`:

```vue
<MessageBubble
  v-for="message in messages"
  :key="message.id"
  :message="message"
/>
```

Python equivalent:

```python
for message in messages:
    render(MessageBubble(key=message.id, message=message))
```

The `:key` is important -- Vue uses it to track which DOM elements correspond to which data
items, so it can update efficiently. Think of it like a primary key in a database.

### Attribute Binding -- `v-bind` (`:`)

The colon (`:`) is shorthand for `v-bind`. It tells Vue "evaluate this as an expression, not a
string literal."

```vue
<!-- Static string (no colon) -->
<button title="Send (Enter)">

<!-- Dynamic expression (with colon) -->
<button :disabled="disabled || !inputText.trim()">
```

Without the colon, `disabled` would be the literal string `"disabled || !inputText.trim()"`.
With the colon, Vue evaluates the JavaScript expression and passes the boolean result.

### Event Handling -- `v-on` (`@`)

The `@` symbol is shorthand for `v-on`. It binds a DOM event to a method.

From `ChatInput.vue`:

```vue
<textarea
  @keydown="handleKeydown"
  @input="autoResize"
/>
<button @click="handleSubmit">
```

Python comparison -- this is like connecting a signal handler or registering a callback:

```python
textarea.on("keydown", handle_keydown)
textarea.on("input", auto_resize)
button.on("click", handle_submit)
```

---

## 3. Reactivity -- ref, reactive, computed

This is where Vue differs most from plain Python. In Python, if you change a variable, nothing
happens automatically. In Vue, changing a *reactive* variable automatically re-renders every
template that uses it.

### `ref` -- A Reactive Box

From `ChatInput.vue`:

```typescript
const inputText = ref<string>('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
```

A `ref` wraps a value. To read or write it in script code, use `.value`:

```typescript
const content: string = inputText.value.trim()  // read
inputText.value = ''                             // write (triggers re-render)
```

In the template, Vue automatically unwraps refs, so you write `inputText` instead of
`inputText.value`:

```vue
<textarea v-model="inputText" />
```

Python comparison -- think of it like a property descriptor that fires a notification on set:

```python
class ReactiveRef:
    def __init__(self, initial):
        self._value = initial

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, new_val):
        self._value = new_val
        self._notify_subscribers()  # <-- this is the magic
```

### `computed` -- Derived Values

From `stores/chat.ts`:

```typescript
const currentConversation = computed<Conversation | undefined>(() => {
  return conversations.value.find(
    (c: Conversation) => c.id === currentConversationId.value,
  )
})
```

A `computed` value automatically recalculates whenever any reactive dependency it reads changes.
It is cached -- if `conversations` and `currentConversationId` have not changed, the function
does not re-run.

Python comparison -- this is a `@property` that caches its result:

```python
@property
def current_conversation(self) -> Conversation | None:
    return next((c for c in self.conversations if c.id == self.current_id), None)
```

The difference: Vue tracks the dependencies automatically. You do not need to declare which
variables the computed depends on.

---

## 4. Lifecycle Hooks

Vue components have a lifecycle: they are created, mounted into the DOM, updated, and eventually
unmounted. You can hook into these stages.

### `onMounted` -- Like `__init__` or `__post_init__`

From `Sidebar.vue`:

```typescript
onMounted(async () => {
  await chat.loadConversations()
})
```

This runs once when the component is inserted into the page. It is your "fetch initial data"
spot, similar to `__init__` or `__post_init__` in a Python dataclass.

### `onUnmounted` -- Like `__del__` or `__exit__`

From `useAgentStream.ts`:

```typescript
onUnmounted(() => {
  disconnect()
})
```

This runs when the component is removed from the page. It is your cleanup spot -- close
connections, cancel timers, release resources. Like a context manager's `__exit__` method.

Other hooks you may encounter: `onBeforeMount`, `onUpdated`, `onBeforeUnmount`. You rarely need
them, but they exist.

---

## 5. Component Communication

### Parent to Child -- Props

From `ChatView.vue`, the parent passes data down:

```vue
<ChatInput :disabled="chat.isStreaming" @send="handleSend" />
```

The child declares what it accepts:

```typescript
// ChatInput.vue
defineProps<{
  disabled: boolean
}>()
```

Python comparison -- this is like constructor arguments:

```python
class ChatInput:
    def __init__(self, disabled: bool):
        self.disabled = disabled
```

### Child to Parent -- Emits

The child can fire events upward:

```typescript
// ChatInput.vue
const emit = defineEmits<{
  send: [content: string]
}>()

function handleSubmit(): void {
  emit('send', content)
}
```

The parent listens with `@send="handleSend"`. This is like the observer pattern or Python
signals.

---

## 6. The Application Entry Point

`web/src/main.ts` boots the entire application:

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

import 'bootstrap/dist/css/bootstrap.min.css'
import './assets/css/main.scss'

const app = createApp(App)

app.use(createPinia())   // Install state management
app.use(router)          // Install routing
app.mount('#app')        // Attach to <div id="app"> in index.html
```

Python comparison:

```python
app = Flask(__name__)         # createApp(App)
app.register_blueprint(api)  # app.use(router)
app.run()                    # app.mount('#app')
```

The `app.use()` calls install plugins. Pinia handles state management (Tutorial 4), and the
router handles page navigation (Tutorial 5).

---

## Key Takeaways

1. A `.vue` file is a self-contained component with template, script, and style sections.
2. Template directives (`v-if`, `v-for`, `v-bind`, `v-on`) replace Python control flow in HTML.
3. `ref()` makes a value reactive -- changing it automatically updates the UI.
4. `computed()` creates cached derived values, like a Python `@property` with auto-tracking.
5. `onMounted`/`onUnmounted` are lifecycle hooks -- your setup and teardown spots.
6. Props flow data down (parent to child); emits flow events up (child to parent).

---

## Try It Yourself

1. Open `web/src/components/chat/MessageBubble.vue`. Identify the prop it receives and how
   the template uses `v-if` to render differently for user vs assistant messages.

2. Open `web/src/components/layout/Header.vue`. Find the `@click` event handler for the
   sidebar toggle. Trace how `ui.toggleSidebar()` changes a reactive value that causes the
   sidebar to collapse.

3. Open `web/src/components/chat/MessageList.vue`. Find the `v-for` loop. What is the `:key`?
   Why does it use `message.id` instead of the loop index?

4. Create a tiny test component: make a file with a `ref<number>(0)`, a button that increments
   it on click, and a `<p>` that displays the count. See how the UI updates without any
   manual DOM manipulation.
