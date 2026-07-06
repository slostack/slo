---
name: 05-vue-router
description: 'Vue tutorial: Vue Router setup and navigation.'
when_to_use: Use only for learning.
group: frontend-vue
kind: skill
source_prompt: vue-prompts/tutorial/05-vue-router.md
---

# Tutorial 5: Routing with Vue Router

## Skill summary

- **Name:** `05-vue-router`
- **Description:** Vue tutorial: Vue Router setup and navigation.
- **When to use:** Use only for learning.
- **Group:** `frontend-vue`
- **Kind:** `skill`
- **Source prompt:** `vue-prompts/tutorial/05-vue-router.md`

## Examples

- The user asks for help with: Vue tutorial: Vue Router setup and navigation.
- Use only for learning.

## Guidance

Web applications need to respond to URL changes. When the user navigates to `/chat/abc-123`,
the app should show that conversation. When they go to `/settings`, the settings page should
appear. Vue Router handles this mapping between URLs and components.

If you have used Flask or FastAPI, this will feel familiar -- it is the frontend equivalent of
`@app.route("/chat/<conversation_id>")`.

---

## 1. Route Definitions

Open `web/src/router/index.ts`:

```typescript
import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/chat',
  },
  {
    path: '/chat',
    name: 'chat-new',
    component: () => import('@/views/ChatPage.vue'),
  },
  {
    path: '/chat/:conversationId',
    name: 'chat',
    component: () => import('@/views/ChatPage.vue'),
    props: true,
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsPage.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
```

Python comparison (FastAPI):

```python
@app.get("/")
async def root():
    return RedirectResponse("/chat")

@app.get("/chat")
async def chat_new():
    return render("ChatPage")

@app.get("/chat/{conversation_id}")
async def chat(conversation_id: str):
    return render("ChatPage", conversation_id=conversation_id)

@app.get("/settings")
async def settings():
    return render("SettingsPage")
```

The structure is nearly identical: a path pattern, a name, and a handler (component).

---

## 2. Anatomy of a Route

Each route object has these key properties:

```typescript
{
  path: '/chat/:conversationId',   // URL pattern with dynamic segment
  name: 'chat',                    // Named identifier (optional but useful)
  component: () => import('@/views/ChatPage.vue'),  // Lazy-loaded component
  props: true,                     // Pass route params as component props
}
```

### `path` -- The URL Pattern

- `/chat` matches exactly `/chat`
- `/chat/:conversationId` matches `/chat/abc-123`, `/chat/xyz-789`, etc.
- `:conversationId` is a dynamic segment (like `{conversation_id}` in FastAPI)

### `name` -- A Symbolic Reference

Instead of hardcoding URLs, you can navigate by name:

```typescript
router.push({ name: 'chat', params: { conversationId: 'abc-123' } })
// equivalent to:
router.push('/chat/abc-123')
```

### `component` -- Lazy Loading

The arrow function `() => import(...)` is a dynamic import. The component is not loaded until
the user navigates to that route. This keeps the initial bundle small.

Python comparison -- this is like lazy module loading:

```python
# Eager
from views import ChatPage

# Lazy
def get_chat_page():
    from views import ChatPage
    return ChatPage
```

### `props: true` -- Route Params as Props

When `props: true`, Vue Router passes route params directly as component props. So for the
URL `/chat/abc-123`:

```typescript
// The route param :conversationId becomes a prop
// ChatPage receives props.conversationId === 'abc-123'
```

This is how `ChatPage.vue` receives the conversation ID cleanly.

---

## 3. The Redirect Route

```typescript
{
  path: '/',
  redirect: '/chat',
}
```

When the user visits the root URL, they are immediately redirected to `/chat`. This is like
Flask's:

```python
@app.route("/")
def index():
    return redirect("/chat")
```

---

## 4. Creating the Router Instance

```typescript
const router = createRouter({
  history: createWebHistory(),
  routes,
})
```

`createWebHistory()` uses the browser's History API for clean URLs (`/chat/abc-123` instead
of `/#/chat/abc-123`). The alternative is `createWebHashHistory()` which uses hash-based
URLs -- useful when your server does not support URL rewriting.

The router is installed in `main.ts`:

```typescript
app.use(router)
```

---

## 5. `<RouterView>` -- Where Routes Render

In `AppLayout.vue`:

```vue
<template>
  <div class="app-layout">
    <Sidebar :class="{ collapsed: !ui.sidebarOpen }" />
    <div class="main-area">
      <Header />
      <RouterView />
    </div>
  </div>
</template>
```

`<RouterView />` is a placeholder. Vue Router replaces it with whichever component matches
the current URL. If the URL is `/chat/abc-123`, `RouterView` renders `ChatPage`. If the URL
is `/settings`, it renders `SettingsPage`.

The sidebar and header remain constant -- only the `RouterView` content changes. This is the
frontend equivalent of a base template in Jinja:

```html
<!-- Jinja base template -->
<div class="app-layout">
  {% include "sidebar.html" %}
  <div class="main-area">
    {% include "header.html" %}
    {% block content %}{% endblock %}   <!-- RouterView equivalent -->
  </div>
</div>
```

---

## 6. Navigation -- Moving Between Pages

### Programmatic Navigation with `router.push`

From `Sidebar.vue`:

```typescript
const router = useRouter()

async function handleNewChat(): Promise<void> {
  const conversation: Conversation = await chat.createConversation()
  await router.push(`/chat/${conversation.id}`)
}

async function handleSelectConversation(id: string): Promise<void> {
  await router.push(`/chat/${id}`)
}
```

`router.push(url)` navigates to a new URL, adding an entry to the browser history (so the
back button works). It returns a Promise that resolves when navigation is complete.

Python comparison:

```python
# Flask
return redirect(f"/chat/{conversation.id}")
```

### Programmatic Navigation After Delete

```typescript
async function handleDeleteConversation(id: string, event: Event): Promise<void> {
  event.stopPropagation()
  await chat.deleteConversation(id)
  if (chat.currentConversationId === null) {
    await router.push('/chat')
  }
}
```

After deleting, if the deleted conversation was the active one, navigate back to the empty
chat page.

### `<RouterLink>` -- Declarative Navigation

Vue Router also provides a `<RouterLink>` component for template-based navigation:

```vue
<RouterLink to="/settings">Settings</RouterLink>
<RouterLink :to="{ name: 'chat', params: { conversationId: id } }">
  Open Chat
</RouterLink>
```

This renders an `<a>` tag that intercepts clicks and uses client-side navigation instead of a
full page reload. The Orders admin UI uses programmatic navigation (`router.push`) in the
sidebar, but `RouterLink` is useful for simple navigation links.

---

## 7. Accessing Route Information with `useRoute`

From `ChatPage.vue`:

```typescript
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()

const conversationId = computed<string | undefined>(() => {
  return route.params.conversationId as string | undefined
})
```

`useRoute()` gives you the current route's information:

- `route.params` -- Dynamic segments (e.g., `{ conversationId: 'abc-123' }`)
- `route.path` -- The current URL path
- `route.name` -- The matched route's name
- `route.query` -- Query parameters (e.g., `?page=2`)

The `computed` wrapping is important: it makes `conversationId` reactive. When the URL
changes, `route.params` updates, which triggers the computed to recalculate, which triggers
any watcher or template that depends on it.

---

## 8. How It All Connects

Here is the full flow when a user clicks a conversation in the sidebar:

1. **Sidebar.vue**: User clicks a conversation item
2. **Sidebar.vue**: `handleSelectConversation(id)` calls `router.push('/chat/abc-123')`
3. **Vue Router**: URL changes to `/chat/abc-123`, matches the `chat` route
4. **AppLayout.vue**: `<RouterView>` swaps in `ChatPage.vue`
5. **ChatPage.vue**: The `computed` reads `route.params.conversationId` = `'abc-123'`
6. **ChatPage.vue**: Passes `conversationId` as a prop to `ChatView`
7. **ChatView.vue**: The `watch` on `conversationId` fires, loads the conversation and
   connects WebSocket

Each step is reactive -- no manual coordination required.

---

## 9. `useRouter` vs `useRoute`

These are easy to confuse:

| | `useRouter()` | `useRoute()` |
|---|---|---|
| Returns | The router instance | The current route object |
| Purpose | Navigate to new pages | Read current page info |
| Example | `router.push('/settings')` | `route.params.conversationId` |
| Mutable? | Yes (navigate, go back) | Read-only |

---

## Key Takeaways

1. Routes map URL patterns to Vue components, just like Flask/FastAPI decorators.
2. Dynamic segments (`:conversationId`) capture URL parts as parameters.
3. `props: true` passes route params directly as component props.
4. `<RouterView>` is the outlet where matched components render.
5. `router.push()` navigates programmatically; `<RouterLink>` navigates declaratively.
6. `useRoute()` gives reactive access to the current URL, params, and query.
7. Lazy loading (`() => import(...)`) keeps the initial bundle small.

---

## Try It Yourself

1. Visit `/chat` in the browser (no conversation ID). Notice that `ChatView` shows the
   empty state. Then visit `/chat/some-id`. The component is the same (`ChatPage.vue`) but
   with different props.

2. Add a new route for a hypothetical `/about` page. Define it in `router/index.ts` with a
   lazy-loaded component. You do not need to create the component file -- just observe how
   the route definition works.

3. In `Sidebar.vue`, change `router.push(...)` to `router.replace(...)`. Navigate between
   conversations and try using the browser back button. `replace` does not add a history
   entry, so the back button skips over those navigations.

4. Add a query parameter to the chat route. For example, modify `ChatPage.vue` to read
   `route.query.highlight` and log it. Navigate to `/chat/abc-123?highlight=true` and
   verify the value appears.
