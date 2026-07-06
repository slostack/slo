---
name: build-vue-components
description: Building Vue components — the 3-layer pattern mirroring backend (component
  / composable / API).
when_to_use: Use when adding or modifying Vue components.
group: frontend-vue
kind: skill
source_prompt: vue-prompts/build-vue-components.md
---

# Build Vue Components

## Skill summary

- **Name:** `build-vue-components`
- **Description:** Building Vue components — the 3-layer pattern mirroring backend (component / composable / API).
- **When to use:** Use when adding or modifying Vue components.
- **Group:** `frontend-vue`
- **Kind:** `skill`
- **Source prompt:** `vue-prompts/build-vue-components.md`

## Examples

- The user asks: "Add or revise the vue components for this feature."
- You want the canonical build pattern before touching vue components.

## Guidance

This document defines the conventions for building Vue 3 components in the Orders admin UI frontend. It mirrors the backend's domain 3-file pattern (`model.py`, `dao.py`, `service.py`) with a component pattern suited to Vue.

---

## 1. Mental Model — Components as a 3-Layer Pattern

Just as the backend organizes each domain into `model.py` (data shape), `dao.py` (validation/transfer), and `service.py` (logic), the frontend organizes each feature into three layers:

| Layer | Backend Analog | Vue Equivalent | Responsibility |
|---|---|---|---|
| **Types** | `dao.py` | `types/*.ts` | Interface definitions, discriminated unions, type aliases |
| **Logic** | `service.py` | `stores/*.ts` + `composables/*.ts` | State management, business logic, side effects |
| **Presentation** | Router/Controller | `components/**/*.vue` + `views/*.vue` | Rendering, user interaction, event emission |

Components are the **presentation layer**. They should be thin — they render data and emit events. All significant logic lives in stores or composables.

---

## 2. File Organization

### 2.1 Feature Directory Structure

Each UI feature gets its own directory under `components/`:

```
components/
├── chat/
│   ├── ChatView.vue           # Container: composes child components, connects to store
│   ├── MessageList.vue         # Presentational: renders a list of messages
│   ├── MessageBubble.vue       # Presentational: renders a single message
│   ├── ChatInput.vue           # Interactive: text input + form submission
│   ├── StreamingIndicator.vue  # Presentational: shows streaming progress
│   └── ProgressStep.vue        # Presentational: a single progress step
├── layout/
│   ├── AppLayout.vue           # Shell: header + sidebar + main content slot
│   ├── Header.vue              # Presentational: app header
│   └── Sidebar.vue             # Interactive: navigation sidebar
```

### 2.2 Component Categories

| Category | Naming Pattern | Characteristics |
|---|---|---|
| **Container** | `*View.vue` | Connects to stores, orchestrates child components, handles routing context |
| **Presentational** | Descriptive noun | Receives all data via props, emits events, no store access |
| **Interactive** | Descriptive noun | Has local state (form values, toggles), emits events for state changes |
| **Shell** | `App*.vue`, layout names | Top-level structure, provides slots for content |
| **Page** | `*Page.vue` (in `views/`) | Route-level entry point, composes containers |

---

## 3. Building a New Component — Step by Step

### 3.1 Define Types First

Before writing any component, define the TypeScript interfaces it will use.

```typescript
// types/research.ts

export interface ResearchQuery {
  id: string
  query: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  createdAt: string
}

export interface ResearchResult {
  id: string
  queryId: string
  title: string
  abstract: string
  source: string
  confidence: number
  citations: Citation[]
}

export interface Citation {
  pmid: string
  title: string
  authors: string[]
  journal: string
  year: number
}
```

### 3.2 Build the Store (if the feature has shared state)

```typescript
// stores/research.ts

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ResearchQuery, ResearchResult } from '@/types/research'
import { api } from '@/api/client'

export const useResearchStore = defineStore('research', () => {
  // State
  const queries = ref<ResearchQuery[]>([])
  const currentQueryId = ref<string | null>(null)
  const results = ref<ResearchResult[]>([])
  const isSearching = ref<boolean>(false)

  // Computed
  const currentQuery = computed<ResearchQuery | undefined>(() => {
    return queries.value.find(
      (q: ResearchQuery) => q.id === currentQueryId.value,
    )
  })

  const completedQueries = computed<ResearchQuery[]>(() => {
    return queries.value.filter(
      (q: ResearchQuery) => q.status === 'completed',
    )
  })

  // Actions
  async function submitQuery(queryText: string): Promise<ResearchQuery> {
    isSearching.value = true
    try {
      const query: ResearchQuery = await api.research.submit(queryText)
      queries.value.unshift(query)
      currentQueryId.value = query.id
      return query
    } finally {
      isSearching.value = false
    }
  }

  async function loadResults(queryId: string): Promise<void> {
    results.value = await api.research.results(queryId)
  }

  function setCurrentQuery(id: string | null): void {
    currentQueryId.value = id
  }

  return {
    queries,
    currentQueryId,
    results,
    isSearching,
    currentQuery,
    completedQueries,
    submitQuery,
    loadResults,
    setCurrentQuery,
  }
})
```

### 3.3 Build Presentational Components (Bottom-Up)

Start with the smallest leaf components and work up to containers.

#### Leaf Component: `CitationCard.vue`

```vue
<script setup lang="ts">
import type { Citation } from '@/types/research'

defineProps<{
  citation: Citation
}>()
</script>

<template>
  <div class="citation-card p-2 border rounded">
    <div class="fw-semibold">{{ citation.title }}</div>
    <div class="text-muted small">
      {{ citation.authors.join(', ') }} &mdash;
      {{ citation.journal }} ({{ citation.year }})
    </div>
    <a
      :href="`https://pubmed.ncbi.nlm.nih.gov/${citation.pmid}/`"
      target="_blank"
      rel="noopener noreferrer"
      class="small"
    >
      PMID: {{ citation.pmid }}
    </a>
  </div>
</template>

<style scoped lang="scss">
.citation-card {
  background-color: var(--app-surface);
  border-color: var(--app-border) !important;
}
</style>
```

#### Mid-Level Component: `ResultCard.vue`

```vue
<script setup lang="ts">
import { ref } from 'vue'
import type { ResearchResult } from '@/types/research'
import CitationCard from '@/components/research/CitationCard.vue'

const props = defineProps<{
  result: ResearchResult
}>()

const isExpanded = ref<boolean>(false)

function toggleExpanded(): void {
  isExpanded.value = !isExpanded.value
}
</script>

<template>
  <div class="result-card p-3 mb-2 border rounded">
    <div class="d-flex justify-content-between align-items-start">
      <div>
        <h5 class="mb-1">{{ result.title }}</h5>
        <span class="badge" :class="confidenceBadgeClass">
          {{ Math.round(result.confidence * 100) }}% confidence
        </span>
      </div>
      <button
        class="btn btn-sm btn-outline-secondary"
        @click="toggleExpanded"
      >
        {{ isExpanded ? 'Collapse' : 'Expand' }}
      </button>
    </div>

    <p v-if="isExpanded" class="mt-2 mb-2">{{ result.abstract }}</p>

    <div v-if="isExpanded && result.citations.length > 0" class="mt-2">
      <h6>Citations ({{ result.citations.length }})</h6>
      <div class="d-flex flex-column gap-2">
        <CitationCard
          v-for="citation in result.citations"
          :key="citation.pmid"
          :citation="citation"
        />
      </div>
    </div>
  </div>
</template>
```

#### Container Component: `ResearchView.vue`

```vue
<script setup lang="ts">
import { watch, onMounted } from 'vue'
import type { ResearchQuery } from '@/types/research'
import { useResearchStore } from '@/stores/research'
import ResultCard from '@/components/research/ResultCard.vue'

const props = defineProps<{
  queryId?: string
}>()

const research = useResearchStore()

onMounted(() => {
  if (props.queryId) {
    research.loadResults(props.queryId)
  }
})

watch(
  () => props.queryId,
  (newId: string | undefined) => {
    if (newId) {
      research.loadResults(newId)
    }
  },
)

async function handleNewQuery(queryText: string): Promise<void> {
  const query: ResearchQuery = await research.submitQuery(queryText)
  await research.loadResults(query.id)
}
</script>

<template>
  <div class="research-view d-flex flex-column h-100">
    <div v-if="research.results.length > 0" class="flex-grow-1 overflow-auto p-3">
      <ResultCard
        v-for="result in research.results"
        :key="result.id"
        :result="result"
      />
    </div>
    <div v-else class="flex-grow-1 d-flex align-items-center justify-content-center">
      <p class="text-muted">No results yet. Submit a research query.</p>
    </div>
  </div>
</template>
```

---

## 4. Props Patterns

### 4.1 Required vs Optional Props

```vue
<script setup lang="ts">
// Required props: no default, TypeScript enforces presence
defineProps<{
  message: Message
  conversationId: string
}>()

// Optional props with defaults
const props = withDefaults(
  defineProps<{
    title: string
    maxItems?: number
    showHeader?: boolean
    variant?: 'default' | 'compact' | 'expanded'
  }>(),
  {
    maxItems: 10,
    showHeader: true,
    variant: 'default',
  },
)
```

### 4.2 Complex Prop Types

When a prop accepts a complex type, define the interface in `types/` and import it.

```vue
<script setup lang="ts">
import type { Message, ConnectionStatus } from '@/types/chat'

defineProps<{
  messages: Message[]
  status: ConnectionStatus
  onRetry: () => void
}>()
```

### 4.3 Props Rules

| Rule | Detail |
|---|---|
| **TypeScript generics only** | `defineProps<{...}>()`, never `defineProps({...})` |
| **Use `withDefaults` for defaults** | Not the options syntax `default:` |
| **Interface types, not inline objects** | If a prop shape has more than 3 fields, define an interface |
| **Boolean props default to `false`** | Consistent with HTML attribute semantics |

---

## 5. Emit Patterns

### 5.1 Typed Emits

```vue
<script setup lang="ts">
const emit = defineEmits<{
  send: [content: string]
  select: [id: string, index: number]
  cancel: []
  'update:modelValue': [value: string]
}>()

// Usage
function handleSubmit(): void {
  emit('send', inputValue.value)
}
```

### 5.2 v-model Support

For components that support `v-model`:

```vue
<script setup lang="ts">
const props = defineProps<{
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

function handleInput(event: Event): void {
  const target: HTMLInputElement = event.target as HTMLInputElement
  emit('update:modelValue', target.value)
}
</script>

<template>
  <input
    :value="modelValue"
    @input="handleInput"
    class="form-control"
  />
</template>
```

---

## 6. Slot Patterns

### 6.1 Named Slots for Layout Components

```vue
<!-- AppLayout.vue -->
<script setup lang="ts">
defineSlots<{
  header(): unknown
  sidebar(): unknown
  default(): unknown
}>()
</script>

<template>
  <div class="app-layout d-flex flex-column vh-100">
    <header class="app-header">
      <slot name="header" />
    </header>
    <div class="d-flex flex-grow-1 overflow-hidden">
      <aside class="app-sidebar">
        <slot name="sidebar" />
      </aside>
      <main class="app-main flex-grow-1 overflow-auto">
        <slot />
      </main>
    </div>
  </div>
</template>
```

### 6.2 Scoped Slots for Data Rendering

```vue
<!-- DataList.vue -->
<script setup lang="ts" generic="T">
defineProps<{
  items: T[]
  keyField: keyof T
}>()

defineSlots<{
  default(props: { item: T; index: number }): unknown
  empty(): unknown
}>()
</script>

<template>
  <div v-if="items.length > 0">
    <div v-for="(item, index) in items" :key="String(item[keyField])">
      <slot :item="item" :index="index" />
    </div>
  </div>
  <div v-else>
    <slot name="empty">
      <p class="text-muted">No items.</p>
    </slot>
  </div>
</template>
```

---

## 7. Error Handling in Components

### 7.1 Async Action Error Handling

Mirror the backend's explicit error handling pattern. Catch errors at the action boundary and surface them to the user.

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { useChatStore } from '@/stores/chat'

const chat = useChatStore()
const errorMessage = ref<string | null>(null)

async function handleSend(content: string): Promise<void> {
  errorMessage.value = null

  try {
    await chat.createConversation(content)
  } catch (error: unknown) {
    const message: string = error instanceof Error
      ? error.message
      : 'An unexpected error occurred'
    errorMessage.value = message
  }
}
</script>

<template>
  <div>
    <div v-if="errorMessage" class="alert alert-danger" role="alert">
      {{ errorMessage }}
    </div>
    <!-- rest of template -->
  </div>
</template>
```

### 7.2 Error Boundary Pattern

For critical sections, use Vue's `onErrorCaptured` lifecycle hook:

```vue
<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'

const hasError = ref<boolean>(false)
const errorInfo = ref<string>('')

onErrorCaptured((error: Error, instance: unknown, info: string): boolean => {
  hasError.value = true
  errorInfo.value = info
  console.error('Component error:', error, info)
  return false // prevent propagation
})
</script>

<template>
  <div v-if="hasError" class="alert alert-warning">
    Something went wrong. Please refresh.
  </div>
  <slot v-else />
</template>
```

---

## 8. Component Composition Patterns

### 8.1 Container/Presentational Split

Containers connect to stores and pass data down. Presentational components receive all data as props.

```
ChatPage.vue (Page/View)
  └── ChatView.vue (Container — uses store, composes children)
        ├── MessageList.vue (Presentational — receives messages as prop)
        │     └── MessageBubble.vue (Presentational — receives single message)
        ├── StreamingIndicator.vue (Presentational — receives status as prop)
        └── ChatInput.vue (Interactive — local form state, emits on submit)
```

### 8.2 When to Create a New Component

| Signal | Action |
|---|---|
| **Template exceeds ~80 lines** | Extract a child component |
| **Logic is reused across views** | Extract into a composable + presentational component |
| **A `v-for` item has its own interactions** | Extract the list item into its own component |
| **Conditional rendering blocks are complex** | Extract each branch into a component |

### 8.3 When NOT to Create a Component

| Signal | Action |
|---|---|
| **A simple `<div>` with one class** | Use the element directly |
| **The "component" would just pass through all props** | Keep it inline |
| **Only used in one place with under 20 lines** | Keep it inline |

---

## 9. Checklist — Before Submitting a New Component

- [ ] Uses `<script setup lang="ts">`
- [ ] Props defined with `defineProps<{...}>()`
- [ ] Emits defined with `defineEmits<{...}>()`
- [ ] Every `ref` has a type parameter: `ref<boolean>(false)`
- [ ] Every `computed` has a type parameter: `computed<string>(() => ...)`
- [ ] Every function has typed parameters and explicit return type
- [ ] Every callback/lambda types its parameters
- [ ] Imports use `@/` absolute paths
- [ ] Type-only imports use `import type`
- [ ] Styles are scoped
- [ ] No `any` in the entire file
- [ ] No direct store mutation from templates
- [ ] Container components connect to stores; presentational components use only props
- [ ] Error states are handled and displayed to the user
