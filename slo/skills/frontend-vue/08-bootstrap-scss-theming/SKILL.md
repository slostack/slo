---
name: 08-bootstrap-scss-theming
description: 'Vue tutorial: Bootstrap + SCSS theming in Vue.'
when_to_use: Use only for learning.
group: frontend-vue
kind: skill
source_prompt: vue-prompts/tutorial/08-bootstrap-scss-theming.md
---

# Tutorial 8: Bootstrap, SCSS, and Theming

## Skill summary

- **Name:** `08-bootstrap-scss-theming`
- **Description:** Vue tutorial: Bootstrap + SCSS theming in Vue.
- **When to use:** Use only for learning.
- **Group:** `frontend-vue`
- **Kind:** `skill`
- **Source prompt:** `vue-prompts/tutorial/08-bootstrap-scss-theming.md`

## Examples

- The user asks for help with: Vue tutorial: Bootstrap + SCSS theming in Vue.
- Use only for learning.

## Guidance

Styling a web application involves three layers: a CSS framework for structure (Bootstrap 5),
a preprocessor for maintainability (SCSS), and custom properties for theming (CSS variables).
The example chat app uses all three. This tutorial explains how they work together.

If you have used CSS before, even minimally, you will be fine. If you have not, think of CSS as
configuration for visual presentation -- like a config file that controls how things look.

---

## 1. Bootstrap 5 Integration

Bootstrap is a CSS framework that provides pre-built styles for common UI patterns: buttons,
forms, grids, cards, and more. It is imported in `web/src/main.ts`:

```typescript
import 'bootstrap/dist/css/bootstrap.min.css'
import './assets/css/main.scss'
```

The order matters: Bootstrap loads first, then the app's custom styles override it. This is
like Python's MRO (Method Resolution Order) -- the last definition wins.

### Using Bootstrap Classes

From `SettingsPage.vue`:

```vue
<div class="p-4" style="max-width: 600px; margin: 0 auto">
  <h2 class="mb-4">Settings</h2>
  <div class="card mb-3">
    <div class="card-body">
      <h5 class="card-title">Appearance</h5>
      <div class="form-check form-switch">
        <input
          id="darkModeToggle"
          class="form-check-input"
          type="checkbox"
          :checked="ui.darkMode"
          @change="ui.toggleDarkMode()"
        />
        <label class="form-check-label" for="darkModeToggle">Dark mode</label>
      </div>
    </div>
  </div>
</div>
```

Bootstrap classes used here:
- `p-4` -- Padding on all sides (level 4 of the spacing scale)
- `mb-4` -- Margin-bottom level 4
- `card`, `card-body`, `card-title` -- A card component
- `form-check`, `form-switch` -- A toggle switch
- `form-check-input`, `form-check-label` -- Form control styling

You do not need to write any CSS for these. Bootstrap provides them out of the box.

From `Header.vue`:

```vue
<button class="btn btn-sm btn-link text-decoration-none p-1 me-2">
```

- `btn` -- Base button style
- `btn-sm` -- Small size variant
- `btn-link` -- Styled as a link (no background)
- `text-decoration-none` -- Remove underline
- `p-1` -- Minimal padding
- `me-2` -- Margin-end (right in LTR) level 2

Python comparison -- Bootstrap classes are like using a UI framework's built-in widgets:

```python
# tkinter
button = tk.Button(parent, text="Toggle", relief="flat", padx=4)

# Bootstrap equivalent in HTML
# <button class="btn btn-link p-1">Toggle</button>
```

### Bootstrap's Utility Classes -- A Quick Reference

| Class Pattern | What It Does | Example |
|---|---|---|
| `p-{0-5}` | Padding | `p-3` = padding on all sides |
| `m-{0-5}` | Margin | `mb-2` = margin-bottom |
| `d-flex` | Flexbox display | `d-flex align-items-center` |
| `text-{muted,center}` | Text styling | `text-muted` = gray text |
| `fw-{bold,semibold}` | Font weight | `fw-bold` = bold text |
| `gap-{1-5}` | Flex gap | `gap-2` = spacing between flex items |
| `ms-auto` | Margin-start auto | Pushes element to the right |

---

## 2. SCSS -- CSS with Superpowers

SCSS (Sassy CSS) extends CSS with variables, nesting, and mixins. It compiles down to regular
CSS. Vite handles the compilation automatically.

Open `web/src/assets/css/main.scss`:

### Variables

```scss
$primary: #6366f1;
$dark: #1e1e2e;
$body-bg: #f8f9fa;
$font-family-sans-serif: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
```

These are SCSS variables. They are compile-time values -- the SCSS compiler replaces `$primary`
with `#6366f1` in the output CSS. These particular variables are Bootstrap overrides: by
defining them before importing Bootstrap, you customize Bootstrap's color palette.

Python comparison -- these are like constants in a config module:

```python
# config.py
PRIMARY_COLOR = "#6366f1"
DARK_COLOR = "#1e1e2e"
BODY_BG = "#f8f9fa"
FONT_FAMILY = "Inter, -apple-system, ..."
```

### Nesting

SCSS lets you nest selectors, which mirrors the HTML structure:

```scss
.message-bubble {
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
  border-radius: 0.75rem;

  &.user {
    background-color: var(--app-user-bubble);
    margin-left: 2rem;
  }

  &.assistant {
    background-color: var(--app-assistant-bubble);

    h1, h2, h3, h4, h5, h6 {
      margin-top: 1rem;
      margin-bottom: 0.5rem;
      &:first-child { margin-top: 0; }
    }

    p { margin-bottom: 0.75rem; &:last-child { margin-bottom: 0; } }

    pre {
      background-color: var(--app-code-bg);
      border-radius: 0.5rem;
      padding: 1rem;

      code {
        color: #cdd6f4;
        font-size: 0.875rem;
      }
    }
  }
}
```

The `&` symbol refers to the parent selector. So `&.user` compiles to `.message-bubble.user`,
and `&:first-child` compiles to `.message-bubble.assistant h1:first-child`.

Without nesting, you would have to write:

```css
.message-bubble { ... }
.message-bubble.user { ... }
.message-bubble.assistant { ... }
.message-bubble.assistant h1 { ... }
.message-bubble.assistant pre { ... }
.message-bubble.assistant pre code { ... }
```

Nesting keeps related styles together, just like Python's indentation groups related code.

### The Sidebar Collapse Pattern

```scss
.sidebar {
  width: var(--app-sidebar-width);
  background-color: var(--app-sidebar-bg);
  border-right: 1px solid var(--app-border);
  display: flex;
  flex-direction: column;
  transition: margin-left 0.3s ease;
  flex-shrink: 0;

  &.collapsed {
    margin-left: calc(-1 * var(--app-sidebar-width));
  }
}
```

When the `collapsed` class is added, the sidebar slides off-screen by setting a negative
margin equal to its width. The `transition: margin-left 0.3s ease` makes this an animation
instead of a jump.

In `AppLayout.vue`, the class is toggled reactively:

```vue
<Sidebar :class="{ collapsed: !ui.sidebarOpen }" />
```

The `:class` binding with an object adds the `collapsed` class when `ui.sidebarOpen` is
false. This is a common pattern in Vue: bind a CSS class to a reactive boolean.

---

## 3. CSS Custom Properties -- Runtime Theming

SCSS variables are compile-time. CSS custom properties (also called CSS variables) are
runtime -- they can change while the app is running, which makes them perfect for theming.

### Light Theme (Default)

```scss
:root {
  --app-bg: #ffffff;
  --app-sidebar-bg: #f1f3f5;
  --app-sidebar-width: 280px;
  --app-header-height: 56px;
  --app-text: #212529;
  --app-text-muted: #6c757d;
  --app-border: #dee2e6;
  --app-chat-bg: #ffffff;
  --app-user-bubble: #e8eaff;
  --app-assistant-bubble: #f8f9fa;
  --app-input-bg: #ffffff;
  --app-accent: #6366f1;
  --app-accent-hover: #4f46e5;
  --app-status-bg: #f0f9ff;
  --app-status-text: #0369a1;
  --app-code-bg: #1e1e2e;
}
```

### Dark Theme

```scss
[data-bs-theme="dark"] {
  --app-bg: #1e1e2e;
  --app-sidebar-bg: #181825;
  --app-text: #cdd6f4;
  --app-text-muted: #a6adc8;
  --app-border: #313244;
  --app-chat-bg: #1e1e2e;
  --app-user-bubble: #313244;
  --app-assistant-bubble: #24243a;
  --app-input-bg: #24243a;
  --app-status-bg: #1a2332;
  --app-status-text: #7dd3fc;
  --app-code-bg: #11111b;
}
```

The variables are defined on `:root` (light mode) and overridden inside `[data-bs-theme="dark"]`
(dark mode). When the `data-bs-theme` attribute on `<html>` is set to `"dark"`, the browser
uses the dark values.

Using them in styles:

```scss
body {
  background-color: var(--app-bg);
  color: var(--app-text);
}
```

`var(--app-bg)` resolves to `#ffffff` in light mode and `#1e1e2e` in dark mode --
automatically, with no JavaScript involved.

Python comparison -- CSS variables are like environment variables for styling:

```python
# Light mode
os.environ["APP_BG"] = "#ffffff"

# Dark mode
os.environ["APP_BG"] = "#1e1e2e"

# Usage
bg_color = os.environ["APP_BG"]
```

---

## 4. Dark Mode Implementation

The dark mode toggle has three parts:

### Part 1: The UI Store

From `stores/ui.ts`:

```typescript
const darkMode = ref<boolean>(false)

function toggleDarkMode(): void {
  darkMode.value = !darkMode.value
}

watch(darkMode, (isDark: boolean) => {
  document.documentElement.setAttribute(
    'data-bs-theme',
    isDark ? 'dark' : 'light',
  )
}, { immediate: true })
```

When `darkMode` changes, the `watch` callback updates the `data-bs-theme` attribute on the
`<html>` element. Bootstrap and the custom CSS variables both respond to this attribute.

### Part 2: The Toggle Button

From `Header.vue`:

```vue
<button @click="ui.toggleDarkMode()">
  <svg v-if="!ui.darkMode"><!-- moon icon --></svg>
  <svg v-else><!-- sun icon --></svg>
</button>
```

The button shows a moon icon in light mode (suggesting "switch to dark") and a sun icon in
dark mode (suggesting "switch to light").

### Part 3: The CSS Variables

When `data-bs-theme="dark"` is set, all `var(--app-*)` references resolve to the dark
values. Every element using these variables updates its appearance instantly -- no re-render,
no component update. CSS handles it natively.

This is why CSS custom properties are powerful for theming: one attribute change on the root
element cascades through the entire page.

---

## 5. Component-Level Styles

In some projects, components have `<style scoped>` blocks that limit styles to that component.
The example chat app takes a different approach: all styles live in `main.scss` and use class names as
namespaces.

```scss
// In main.scss -- scoped by class name
.chat-input-container { ... }
.chat-input-wrapper { ... }
.chat-textarea { ... }
.send-button { ... }
```

Both approaches work. The `main.scss` approach keeps all styles in one place, which makes
theming easier. The scoped approach prevents accidental conflicts, which matters more in
large teams.

If you see `<style scoped>` in other Vue projects:

```vue
<style scoped>
.button {
  color: red;
}
</style>
```

The `scoped` attribute makes `.button` only apply to elements in this component's template.
Vue achieves this by adding a unique `data-v-xxxx` attribute to elements and selectors.

---

## 6. Layout with Flexbox

The chat app layout uses CSS Flexbox extensively:

```scss
.app-layout {
  display: flex;          // Horizontal row (sidebar + main)
  height: 100vh;          // Full viewport height
}

.main-area {
  flex: 1;                // Take remaining width
  display: flex;
  flex-direction: column; // Vertical stack (header + content)
  min-width: 0;           // Allow shrinking below content size
}

.chat-container {
  flex: 1;                // Take remaining height
  display: flex;
  flex-direction: column; // Vertical stack (messages + input)
}
```

The layout nests flexbox containers:

```
[app-layout (horizontal flex)]
  [sidebar (fixed width)]
  [main-area (vertical flex, fills remaining)]
    [header (fixed height)]
    [RouterView / chat-container (vertical flex, fills remaining)]
      [message-list (scrollable, fills remaining)]
      [chat-input (fixed height)]
```

Python comparison -- this is like a nested layout in tkinter or PyQt:

```python
# PyQt equivalent
main_layout = QHBoxLayout()       # app-layout
main_layout.addWidget(sidebar)    # fixed width sidebar
right_layout = QVBoxLayout()      # main-area
right_layout.addWidget(header)    # fixed height header
right_layout.addWidget(chat)      # stretches to fill
```

---

## 7. Animations

The example chat app uses a `pulse` animation for the streaming indicator and the connection status:

```scss
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.3); }
}

.progress-step {
  &.active::before {
    animation: pulse 1.5s ease-in-out infinite;
  }
}

.connection-indicator {
  &.connecting {
    animation: pulse 1s infinite;
  }
}
```

`@keyframes` defines a named animation. `animation: pulse 1.5s ease-in-out infinite` means:
- Use the `pulse` keyframes
- Each cycle takes 1.5 seconds
- Ease in and out (smooth acceleration/deceleration)
- Repeat forever

The active progress step dot pulses to indicate "currently working," and the connecting
indicator pulses to show "trying to connect."

---

## 8. Responsive Design

```scss
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 1000;

    &.collapsed {
      margin-left: calc(-1 * var(--app-sidebar-width));
    }
  }

  .message-wrapper {
    padding: 0 1rem;      // Less padding on small screens
  }

  .chat-input-container {
    padding: 0.75rem 1rem 1rem;
  }
}
```

`@media (max-width: 768px)` applies styles only when the browser window is 768px wide or
smaller (roughly tablet size and below). On small screens, the sidebar becomes fixed-position
(overlays content instead of pushing it aside) and padding is reduced.

---

## 9. Custom Scrollbars

```scss
.message-list::-webkit-scrollbar,
.sidebar-content::-webkit-scrollbar {
  width: 6px;
}

.message-list::-webkit-scrollbar-track,
.sidebar-content::-webkit-scrollbar-track {
  background: transparent;
}

.message-list::-webkit-scrollbar-thumb,
.sidebar-content::-webkit-scrollbar-thumb {
  background-color: var(--app-border);
  border-radius: 3px;
}
```

These pseudo-elements style the scrollbar in WebKit browsers (Chrome, Safari, Edge). A thin,
subtle scrollbar that matches the theme. Note that these use `var(--app-border)`, so
they adapt to dark mode automatically.

---

## Key Takeaways

1. Bootstrap provides utility classes (`p-4`, `d-flex`, `btn`) for rapid layout and styling.
2. SCSS adds variables (`$primary`), nesting (`&.child`), and other features to CSS.
3. CSS custom properties (`--app-bg`) enable runtime theming -- one attribute change
   cascades to the entire page.
4. Dark mode works by switching `data-bs-theme` on the `<html>` element, which swaps
   all CSS variable values.
5. Flexbox is the primary layout tool -- nested flex containers create the sidebar + header
   + content structure.
6. `@media` queries adapt styles for different screen sizes.
7. Animations (`@keyframes`) add visual feedback for loading and connecting states.

---

## Try It Yourself

1. Open your browser DevTools, go to Elements, find the `<html>` tag, and toggle the
   `data-bs-theme` attribute between `"light"` and `"dark"`. Watch the entire page switch
   themes instantly.

2. In `main.scss`, change `--app-accent: #6366f1` to a different color (try `#10b981`
   for green). See how the send button, links, and connection indicator all update because
   they reference `var(--app-accent)`.

3. Add a new CSS variable `--app-radius` with a value of `0.75rem`. Replace the
   hardcoded `border-radius` values in `.message-bubble`, `.chat-input-wrapper`, and
   `.send-button` with `var(--app-radius)`. Now you can change all border radii from
   one place.

4. Try adding `transition: background-color 0.3s ease, color 0.3s ease` to the `body`
   selector. Toggle dark mode and notice the smooth color transition instead of an
   instant switch.
