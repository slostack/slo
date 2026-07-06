---
name: 02-typescript-essentials
description: 'Vue tutorial: TypeScript essentials for Vue components.'
when_to_use: Use only for learning.
group: frontend-vue
kind: skill
source_prompt: vue-prompts/tutorial/02-typescript-essentials.md
---

# Tutorial 2: TypeScript Essentials for Python Developers

## Skill summary

- **Name:** `02-typescript-essentials`
- **Description:** Vue tutorial: TypeScript essentials for Vue components.
- **When to use:** Use only for learning.
- **Group:** `frontend-vue`
- **Kind:** `skill`
- **Source prompt:** `vue-prompts/tutorial/02-typescript-essentials.md`

## Examples

- The user asks for help with: Vue tutorial: TypeScript essentials for Vue components.
- Use only for learning.

## Guidance

TypeScript is to JavaScript what type hints are to Python -- except TypeScript enforces them at
compile time. If you have been using `mypy` or writing `def greet(name: str) -> str:`, you
already understand the motivation. This tutorial maps TypeScript concepts to their Python
equivalents, using real types from the Orders admin UI.

---

## 1. Type Annotations -- Familiar Territory

### Variables

```typescript
// TypeScript
const name: string = 'Orders Admin'
const count: number = 42
const active: boolean = true
const items: string[] = ['a', 'b', 'c']
```

```python
# Python
name: str = 'Orders Admin'
count: int = 42
active: bool = True
items: list[str] = ['a', 'b', 'c']
```

Nearly identical syntax. TypeScript uses a colon after the variable name, just like Python.

### Functions

```typescript
// TypeScript
function formatDate(dateStr: string): string {
  const date: Date = new Date(dateStr)
  return date.toLocaleDateString()
}
```

```python
# Python
def format_date(date_str: str) -> str:
    date = datetime.fromisoformat(date_str)
    return date.strftime("%x")
```

Return type goes after the parameter list, separated by `:` in TypeScript (vs `->` in Python).

### Async Functions

From `stores/chat.ts`:

```typescript
async function loadConversations(): Promise<void> {
  try {
    conversations.value = await api.conversations.list()
  } catch (error: unknown) {
    console.error('Failed to load conversations:', error)
  }
}
```

```python
# Python equivalent
async def load_conversations() -> None:
    try:
        conversations = await api.conversations.list()
    except Exception as error:
        print(f"Failed to load conversations: {error}")
```

`Promise<void>` is like Python's `Coroutine[Any, Any, None]` -- an async function that
returns nothing. In practice, you will see `Promise<T>` just like Python's
`async def foo() -> T`.

---

## 2. Interfaces -- Like Dataclasses or TypedDict

This is where TypeScript shines for Vue development. Open `web/src/types/chat.ts`:

```typescript
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
```

Python equivalent using dataclasses:

```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class MessageMeta:
    status_history: list[str] | None = None

@dataclass
class Message:
    id: str
    conversation_id: str
    role: Literal['user', 'assistant']
    content: str
    created_at: str
    meta: MessageMeta | None = None

@dataclass
class Conversation:
    id: str
    title: str | None
    created_at: str
    updated_at: str
    messages: list[Message] | None = None
```

Or using TypedDict (closer in spirit, since interfaces describe shape, not behavior):

```python
from typing import TypedDict, NotRequired

class Message(TypedDict):
    id: str
    conversationId: str
    role: Literal['user', 'assistant']
    content: str
    createdAt: str
    meta: NotRequired[MessageMeta]
```

Key differences:
- `?` after a property name means optional (Python's `NotRequired` or `| None`)
- Interfaces have zero runtime cost -- they are erased during compilation
- You do not instantiate interfaces with `new`; any object matching the shape qualifies

---

## 3. Union Types

From `types/chat.ts`:

```typescript
export type WebSocketEvent = A2AStatusEvent | A2AArtifactEvent | A2AErrorEvent | PongEvent
```

This is a discriminated union. Each member has a `type` field that tells you which variant it is:

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

export interface PongEvent {
  type: 'pong'
}
```

Python equivalent (3.10+):

```python
type WebSocketEvent = A2AStatusEvent | A2AArtifactEvent | A2AErrorEvent | PongEvent
```

The `type` field acts as a discriminator. In `useAgentStream.ts`, you see it used in a switch:

```typescript
function handleEvent(event: WebSocketEvent): void {
  switch (event.type) {
    case 'status':
      store.addStatusMessage(event.message)  // TS knows event is A2AStatusEvent here
      break
    case 'artifact':
      // TS knows event is A2AArtifactEvent here, so event.data is available
      break
    case 'error':
      // TS knows event is A2AErrorEvent here
      break
  }
}
```

TypeScript narrows the type inside each `case` branch automatically. This is similar to
Python's `match/case` with structural pattern matching.

---

## 4. Generics -- Like Python's `Generic[T]`

From `api/client.ts`:

```typescript
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
  const response: Response = await fetch(url, { ... })
  const body: ApiResponse<T> = await response.json()
  return body.data
}
```

The `<T>` is a type parameter. When you call `request<Conversation[]>(...)`, TypeScript
substitutes `T = Conversation[]` throughout, so `body.data` is typed as `Conversation[]`.

Python equivalent:

```python
from typing import Generic, TypeVar

T = TypeVar('T')

@dataclass
class ApiResponse(Generic[T]):
    data: T
    api_version: str
    errors: dict

async def request(path: str, T_type: type[T]) -> T:
    response = await fetch(url)
    body: ApiResponse[T] = parse(response)
    return body.data
```

The Orders admin UI API client uses generics elegantly:

```typescript
async list(page: number = 1): Promise<Conversation[]> {
  return request<Conversation[]>(`/conversations?page=${page}`)
}

async get(id: string): Promise<Conversation> {
  return request<Conversation>(`/conversations/${id}`)
}
```

Each call specifies the expected return type, and TypeScript checks it end-to-end.

---

## 5. Special TypeScript Features

### Optional Chaining (`?.`)

```typescript
// TypeScript
chat.currentConversation?.title

// Python (3.10+ doesn't have this -- you use getattr or and/or)
chat.current_conversation.title if chat.current_conversation else None
```

If `currentConversation` is `null` or `undefined`, the expression short-circuits to `undefined`
instead of throwing. Python does not have this operator natively.

### Nullish Coalescing (`??`)

```typescript
// TypeScript
conversation.title ?? 'Untitled'

// Python
conversation.title or 'Untitled'    # close, but not identical
conversation.title if conversation.title is not None else 'Untitled'  # exact equivalent
```

`??` returns the right side only if the left is `null` or `undefined`. Python's `or` returns
the right side for any falsy value (including `""`, `0`, `False`). The `??` is more precise.

From `Sidebar.vue`:

```vue
{{ conversation.title ?? 'Untitled' }}
```

### Non-null Assertion (`!`)

```typescript
const element = document.getElementById('app')!  // "I promise this is not null"
```

This tells TypeScript "trust me, this will not be null." Use sparingly -- it disables a safety
check. Python has no equivalent; you would just use an assert:

```python
element = document.getElementById('app')
assert element is not None
```

### Type Assertions (`as`)

From `ChatPage.vue`:

```typescript
const conversationId = computed<string | undefined>(() => {
  return route.params.conversationId as string | undefined
})
```

This tells TypeScript "treat this value as this type." Similar to Python's `cast()`:

```python
from typing import cast
conversation_id = cast(str | None, route.params.get("conversationId"))
```

---

## 6. The `type` Import

```typescript
import type { Conversation, Message, ConnectionStatus } from '@/types/chat'
```

The `type` keyword means "import this only for type checking -- erase it from the compiled
JavaScript." It has no runtime cost. Python's `TYPE_CHECKING` flag serves the same purpose:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from types.chat import Conversation, Message
```

---

## 7. Utility Types You Will See

| TypeScript | Python Equivalent | Meaning |
|---|---|---|
| `string` | `str` | Text |
| `number` | `int \| float` | Any numeric value |
| `boolean` | `bool` | True/false |
| `string[]` | `list[str]` | Array of strings |
| `Record<string, unknown>` | `dict[str, Any]` | Dictionary |
| `T \| null` | `T \| None` | Nullable |
| `unknown` | `Any` (safer) | Unknown type, must narrow before use |
| `void` | `None` | No return value |
| `ReturnType<typeof fn>` | No direct equivalent | Extracts the return type of a function |

From `useAgentStream.ts`:

```typescript
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
```

This says "reconnectTimer is whatever type `setTimeout` returns (a timer ID), or null." It
avoids hardcoding a platform-specific type.

---

## 8. Index Signatures and `unknown`

From `types/chat.ts`:

```typescript
export interface A2AArtifactEvent {
  type: 'artifact'
  data: {
    response?: string
    [key: string]: unknown    // <-- index signature
  }
}
```

The `[key: string]: unknown` line says "this object can have any additional string keys with
values of unknown type." Python equivalent:

```python
class A2AArtifactData(TypedDict):
    response: NotRequired[str]
    # Additional keys allowed -- TypedDict doesn't support this directly,
    # you'd use a plain dict[str, Any] alongside known fields
```

`unknown` is TypeScript's safe version of `any`. You must narrow it (check its type) before
using it. `any` disables type checking entirely.

---

## Key Takeaways

1. TypeScript type annotations are syntactically similar to Python's -- `name: string` vs
   `name: str`.
2. Interfaces describe object shapes like `TypedDict` or `@dataclass` -- but with zero
   runtime cost.
3. Union types with discriminator fields (`type: 'status' | 'error'`) enable safe pattern
   matching via `switch`.
4. Generics (`<T>`) work just like Python's `Generic[T]` -- parameterize types for reuse.
5. `?.` (optional chaining) and `??` (nullish coalescing) are convenience operators Python
   lacks -- learn them, they appear everywhere in Vue code.
6. `import type` keeps type information out of the runtime bundle.

---

## Try It Yourself

1. Open `web/src/types/chat.ts`. Trace how `WebSocketEvent` is a union of four interfaces.
   Then open `web/src/composables/useAgentStream.ts` and find the `handleEvent` function.
   Notice how `switch (event.type)` narrows the type in each branch.

2. Open `web/src/api/client.ts`. Look at the generic `request<T>` function. Follow a call
   from `api.conversations.list()` through to the return type. How does `T` flow?

3. Add a new field to the `Message` interface -- say `editedAt?: string`. Notice that
   TypeScript does not complain anywhere, because the field is optional. Now make it required
   (remove the `?`). See how TypeScript flags every place that creates a `Message` without
   the new field.

4. Try changing `role: 'user' | 'assistant'` to `role: string` in the `Message` interface.
   Think about what type safety you lose. The literal union means TypeScript can catch a typo
   like `role: 'asistant'` at compile time.
