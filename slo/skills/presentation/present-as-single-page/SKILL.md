---
name: present-as-single-page
description: Present information as ONE self-contained, single-page HTML document —
  a long scrolling page with a hero, anchored sections, and an optional sticky
  table-of-contents — styled with the Slo design language (Tokyo Night primary,
  near-black/green alternate) mirrored from the TUI themes. No slides, no
  scroll-snap; dependency-free and CSP-safe.
when_to_use: Use when the user wants information rendered as a single HTML page or
  long-form document (report, briefing, explainer, reference) that is read and
  scrolled top-to-bottom — NOT stepped through as a slide deck. If the user asks
  for a "slide deck" or "single-page deck", use present-as-html instead.
group: presentation
kind: skill
---

# Present as Single Page

## Skill summary

- **Name:** `present-as-single-page`
- **Description:** Present information as one self-contained, single-page HTML
  document — a long scrolling page with a hero, anchored sections, and an optional
  sticky TOC — styled with the Slo design language.
- **When to use:** Use when the user wants a single scrolling HTML page / long-form
  document, not a slide deck.
- **Group:** `presentation`
- **Kind:** `skill`

## Examples

- The user asks: "Make this a single-page HTML, not a slide deck."
- The user asks: "Turn this into one HTML page I can scroll through."
- The user asks: "Write a single-page report / explainer / briefing in HTML."
- The user asks: "Give me a one-page HTML write-up of this."

## Guidance

When this skill is invoked, produce **one self-contained HTML file** that presents
the requested information as a **single scrolling page** — a hero followed by
stacked, anchored sections. This is the long-form sibling of `present-as-html`; the
**only** difference is the layout shell:

- **This skill** → one continuous document. Normal page scroll. Sections flow
  top-to-bottom at their natural height. Optional sticky TOC / progress bar.
- **`present-as-html`** → a scroll-snap slide deck of full-viewport panels stepped
  through with arrow keys.

**Never** use `.slo-deck` / `.slo-slide` / `scroll-snap` / full-viewport panels here.
If the content really wants to be stepped through one idea at a time, stop and use
`present-as-html` instead.

---

### Step 1 — Ground the content in the real subject

Identical discipline to the deck skill: use the **real** finding, code, data, or
analysis from the conversation or codebase — never placeholder text. **Verify any
claim about how code behaves** against the source before presenting it. Cite
`file.py:line` so the reader can click through. A polished page that asserts
something false is worse than plain prose.

---

### Step 2 — Apply the Slo design language (inlined)

The canonical stylesheet is the shared one at
`skills/presentation/present-as-html/assets/slo-design-language.css`. **Read it** and
use its `--slo-*` tokens and component classes — do not invent a parallel palette.

Token source of truth (mirrors `src/tui/theme.py`):

- **Primary — `slo-default` (Tokyo Night):** ground `#1a1b26`, text `#c0caf5`, blue
  accent `#7aa2f7`, cyan `#7dcfff`, green `#9ece6a`, amber `#e0af68`, red `#f7768e`,
  violet `#bb9af7`. Default (`:root`).
- **Alternate — `slo-dark` (near-black / phosphor green):** ground `#080808`, text
  `#d8d8d8`, green accent `#00ff7f`. Activate with `data-theme="dark"` on `<html>`.

**Ship the CSS inlined** inside a single `<style>` tag — Slo HTML is frequently
rendered under a strict CSP (claude.ai Artifacts, sandboxed previews) that blocks
external stylesheets, font CDNs, and remote scripts. Never `<link>` a CDN stylesheet
or font; use only the system font stacks in the tokens. Embed images as `data:` URIs
and draw graphics with inline `<canvas>` / `<svg>`.

Reach for these component classes: `.slo-eyebrow`, `.slo-lede`, `.slo-card`,
`.slo-panel`, `.slo-note` (+ `--success/--warning/--error`), `.slo-badge`,
`.slo-code` (+ `.tok-*` for short inline fragments; multi-line code uses highlight.js — see Step 2.5), `.slo-kv`, `.slo-table-scroll` (wrap wide tables), and the
single-page shell `.slo-doc` / `.slo-wrap`.

---

### Step 2.5 — Syntax-highlight code blocks (highlight.js, inlined)

Every multi-line code block must be syntax-highlighted with a real highlighter that
supports any language — **inlined**, so the page stays self-contained and CSP-safe.
Use the highlight.js bundle vendored beside this skill; never `<script src>` a CDN.

1. **Inline the library.** Paste the contents of `present-as-html/assets/highlight.min.js` (highlight.js
   v11.9.0, BSD-3-Clause; ~35 common languages with auto-detection) into a `<script>` tag
   near the end of `<body>`.
2. **Inline the theme.** Paste `present-as-html/assets/hljs-slo-theme.css` into the `<style>` block. It maps
   highlight.js token classes onto the `--slo-*` tokens, so highlighting stays correct in
   both the Tokyo Night default and the green `data-theme="dark"` alternate.
3. **Tag every code block with its language** so coloring is deterministic:
   `<pre><code class="language-python">…</code></pre>`. Use `language-bash`,
   `language-typescript`, `language-json`, etc. Use `language-plaintext` for ASCII trees or
   console dumps you do NOT want tokenized.
4. **Activate on load** with a tiny inline script: `if (window.hljs) hljs.highlightAll();`.
5. **Escape `<`, `>`, `&`** inside code blocks as `&lt;`, `&gt;`, `&amp;`.
6. **Bake the tokens in statically — DO NOT rely on the runtime script alone.** `hljs.highlightAll()`
   only colorizes at view time, *if* JavaScript runs. Many viewers open these files with JS disabled or
   under a strict CSP that blocks inline scripts, and then **every code block renders as flat,
   uncolored text** — the single most common defect in generated HTML. The robust fix is to run
   highlight.js at *generation* time and write the resulting `<span class="hljs-*">…</span>` markup
   directly into each block, marking it `<code class="hljs language-python" data-highlighted="yes">…</code>`
   (the `data-highlighted="yes"` makes the runtime `highlightAll()` skip it, so there is no
   double-processing). Keep the inline script as a harmless progressive enhancement. A reliable way to
   pre-render: extract the inlined library, then for each block run
   `require('highlight.min.js').highlight(rawSource, {language}).value` and substitute it back.

> **CRUCIAL — syntax highlighting is non-negotiable.** Before shipping, **open the file and confirm code
> blocks are actually colored**, ideally with JavaScript disabled (the worst-case viewer). A spec or
> report whose code is a wall of monochrome text fails the quality bar. If you cannot verify rendering,
> bake the tokens in statically (step 6) so highlighting cannot silently disappear.

Reserve the manual `.tok-*` classes only for short *inline* fragments where loading the
highlighter is overkill. Multi-line code blocks always go through highlight.js.

---

### Step 3 — Build the single-page shell

Use this skeleton. The page scrolls normally; sections are anchored so a TOC and a
top progress bar can track position.

```html
<div class="slo-progress" id="progress"></div>

<!-- Hero: state the thesis, not a table of contents -->
<header class="page-hero">
  <div class="slo-wrap">
    <p class="slo-eyebrow">Context · one short label</p>
    <h1>The single clearest statement of the subject</h1>
    <p class="slo-lede">One or two sentences of real framing.</p>
  </div>
</header>

<!-- Optional sticky in-page nav -->
<nav class="page-toc" aria-label="On this page">
  <div class="slo-wrap">
    <a href="#overview">Overview</a>
    <a href="#detail">Detail</a>
    <a href="#takeaway">Takeaway</a>
  </div>
</nav>

<main class="slo-doc">
  <section id="overview" class="page-section">
    <h2>Section heading</h2>
    <p>Real content…</p>
  </section>
  <!-- more <section class="page-section" id="…"> -->
</main>

<footer class="page-foot"><div class="slo-wrap">…</div></footer>
```

Add small page-specific CSS on top of the design language (still inlined):

```css
.page-hero { padding: clamp(3rem,10vh,7rem) 0 clamp(2rem,5vh,3.5rem); border-bottom: 1px solid var(--slo-hair); }
.page-toc { position: sticky; top: 0; z-index: 20; background: color-mix(in srgb, var(--slo-bg) 88%, transparent); backdrop-filter: blur(8px); border-bottom: 1px solid var(--slo-hair-soft); }
.page-toc .slo-wrap { display: flex; gap: 1.4rem; padding-block: .7rem; flex-wrap: wrap; }
.page-toc a { font-family: var(--slo-font-mono); font-size: var(--slo-step--1); color: var(--slo-fg-muted); border: 0; letter-spacing: .04em; }
.page-toc a:hover, .page-toc a[aria-current="true"] { color: var(--slo-signal); }
.page-section { scroll-margin-top: 4rem; padding-block: clamp(2rem,6vh,3.5rem); border-bottom: 1px solid var(--slo-hair-soft); }
.page-section:last-child { border-bottom: 0; }
```

Optional, minimal vanilla JS (inline): update `#progress` width on scroll and set
`aria-current` on the TOC link whose section is in view via `IntersectionObserver`.
Keep running text within `--slo-measure` (65ch). No keyboard slide navigation — this
is a document, not a deck.

Content rules:
- **Hero leads with the thesis**, not an agenda.
- Use `<h2>` per major section, `<h3>` for sub-points — real document hierarchy.
- Use numbered markers only when content is genuinely sequential.
- Break long stretches with `.slo-card`, `.slo-note`, tables, and `.slo-code`.

---

### Step 4 — Quality bar before shipping

- [ ] **Single scrolling page** — no scroll-snap, no full-viewport slide panels.
- [ ] **Self-contained** — no external CSS/JS/font/image URLs; opens offline.
- [ ] **Code blocks highlighted — verified, not assumed** — every multi-line block tagged `language-*`, and the colored tokens **baked statically** into the markup (`<code class="hljs language-* " data-highlighted="yes">` with `hljs-*` spans) so highlighting survives a no-JS / strict-CSP viewer. Open the file and confirm color renders.
- [ ] **No horizontal page scroll** — wide code/tables in their own
      `overflow-x:auto` container.
- [ ] **Real content throughout**; claims verified against source.
- [ ] **Valid HTML** — tags closed, attributes double-quoted.
- [ ] **Accessible** — visible `:focus-visible`; anchor links work; TOC has
      `aria-label`.
- [ ] **Reduced-motion respected.**
- [ ] **Tasteful** — one bold accent, the rest quiet; avoid generic-AI tells.

---

### Step 5 — Deliver

1. Write the `.html` file — default to the session **scratchpad** unless the user
   names a repo path.
2. If a hosted preview is wanted, you may publish an Artifact, but **always report
   the raw local file path** (an Artifact is hosted on claude.ai, not raw HTML the
   user owns).
3. State plainly: the file path, that it is a single scrolling page (not a deck),
   the theme, and that it is fully self-contained.

A worked single-page reference is bundled at `assets/example-single-page.html`. Read
it when you need a concrete model.
