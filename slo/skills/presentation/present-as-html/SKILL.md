---
name: present-as-html
description: Present information as self-contained HTML — a single-page scroll-snap
  slide deck or a sequence of paged HTML documents — styled with the Slo design
  language (Tokyo Night primary, near-black/green alternate) mirrored from the TUI
  themes. Output is dependency-free and CSP-safe.
when_to_use: Use when the user asks to turn an explanation, finding, analysis, plan,
  or report into a visual HTML page, a slide deck, a "single-page HTML deck", or a
  sequence of HTML pages — anything where reading it as a designed page beats reading
  it as terminal text.
group: presentation
kind: skill
---

# Present as HTML

## Skill summary

- **Name:** `present-as-html`
- **Description:** Present information as a self-contained HTML slide deck (single
  page, scroll-snap) or a sequence of paged HTML documents, styled with the Slo
  design language mirrored from the TUI themes.
- **When to use:** Use when the user wants a finding, explanation, plan, or report
  rendered as a visual HTML page / deck rather than as terminal prose.
- **Group:** `presentation`
- **Kind:** `skill`

## Examples

- The user asks: "Present this finding as a single-page HTML slide deck."
- The user asks: "Turn this analysis into a visual HTML page so I can understand it."
- The user asks: "Generate a sequence of HTML pages explaining how this subsystem works."
- The user asks: "Make me a deck for this."

## Guidance

When this skill is invoked, produce **one self-contained HTML file** that presents
the requested information using the Slo design language. Follow these rules.

---

### Step 1 — Pick the format

Decide between two shapes from the request:

| Shape | Use when | Structure |
|---|---|---|
| **Single-page slide deck** | The user says "slide deck", "deck", "slides", or the content is a guided sequence the reader steps through | `<main class="slo-deck">` of full-viewport `<section class="slo-slide">` elements with keyboard + dot navigation |
| **Paged document** | The content is a report, briefing, or reference that is read, scanned, and re-visited rather than stepped through | `<div class="slo-doc">` sections, or several linked pages with `.slo-pager` nav |

If the user names the shape, honor it. If unsure, a slide deck is the right default
for an explanation or finding; a paged document is right for a report or reference.
State which you chose in one line.

---

### Step 2 — Ground the content in the real subject

This is a **presentation** skill, not a design-from-imagination skill. Before
writing markup:

1. **Use real content.** Pull the actual finding, code, data, or analysis from the
   conversation or the codebase. Never use lorem ipsum or placeholder bullets.
2. **Verify claims you present.** If the deck asserts how code behaves, confirm it
   against the source first (read the file, check the version). A polished deck that
   states something false is worse than plain text. If you correct an earlier claim,
   say so on a slide rather than silently shipping the right version.
3. **Cite where it helps.** Reference `file.py:line` in the body so the reader can
   click through (these render as links in the Slo TUI and most viewers).

---

### Step 3 — Apply the Slo design language

The canonical stylesheet lives beside this skill at
`assets/slo-design-language.css`. **Read it** and use its tokens and component
classes. Do not invent a parallel palette.

Token source of truth — both palettes mirror `src/tui/theme.py`:

- **Primary identity — `slo-default` (Tokyo Night):** night-blue ground `#1a1b26`,
  text `#c0caf5`, blue accent `#7aa2f7`, cyan `#7dcfff`, green `#9ece6a`, amber
  `#e0af68`, red `#f7768e`, violet `#bb9af7`. This is the default (`:root`).
- **Alternate — `slo-dark` (near-black / phosphor green):** ground `#080808`, text
  `#d8d8d8`, green accent `#00ff7f`, light-blue `#7ec8e3`. Activate by putting
  `data-theme="dark"` on `<html>` or a container.

Default to the Tokyo Night identity. Offer or use the green alternate only when the
user asks for it or the subject calls for a terminal/phosphor feel.

**How to ship the CSS — inline it.** Slo HTML is frequently rendered under a strict
Content Security Policy (claude.ai Artifacts, sandboxed previews) that blocks
external stylesheets, font CDNs, and remote scripts. Therefore:

- Inline the design language inside a single `<style>` tag in `<head>`. Either paste
  the contents of `assets/slo-design-language.css`, or write equivalent rules that
  use the same `--slo-*` tokens.
- **Never** `<link>` a CDN stylesheet or a font URL — it will silently fail and the
  page will fall back to ugly defaults. Use only the system font stacks already in
  the tokens (`--slo-font-sans`, `--slo-font-mono`).
- Embed any image as a `data:` URI. Draw decorative or generative graphics with
  inline `<canvas>` / `<svg>`, not remote assets.

Use the provided component classes rather than ad-hoc styles: `.slo-eyebrow`,
`.slo-lede`, `.slo-card`, `.slo-panel`, `.slo-note` (+ `--success/--warning/--error`),
`.slo-badge`, `.slo-code` (+ `.tok-*` for short inline fragments; multi-line code uses highlight.js — see Step 3.5), `.slo-kv`,
`.slo-table-scroll` around wide tables, and the `.slo-deck` / `.slo-slide` /
`.slo-dots` / `.slo-progress` scaffolding for decks.

---

### Step 3.5 — Syntax-highlight code blocks (highlight.js, inlined)

Every multi-line code block must be syntax-highlighted with a real highlighter that
supports any language — **inlined**, so the page stays self-contained and CSP-safe.
Use the highlight.js bundle vendored beside this skill; never `<script src>` a CDN.

1. **Inline the library.** Paste the contents of `assets/highlight.min.js` (highlight.js
   v11.9.0, BSD-3-Clause; ~35 common languages with auto-detection) into a `<script>` tag
   near the end of `<body>`.
2. **Inline the theme.** Paste `assets/hljs-slo-theme.css` into the `<style>` block. It maps
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

### Step 4 — Build the deck (if slide-deck shape)

Use this skeleton. Keep the JS minimal, vanilla, and inline.

```html
<main class="slo-deck" id="deck">
  <div class="slo-progress" id="progress"></div>

  <section class="slo-slide">
    <div class="slo-slide__inner">
      <p class="slo-eyebrow">Context · one short label</p>
      <h1>The single clearest statement of the idea</h1>
      <p class="slo-lede">One or two sentences of real framing.</p>
    </div>
  </section>

  <!-- more <section class="slo-slide"> … -->
</main>

<nav class="slo-dots" id="dots" aria-label="slides"></nav>
<div class="slo-counter"><b id="cur">1</b> / <span id="tot">1</span></div>
<div class="slo-hint">↑ ↓ / space to move · 1–9 to jump</div>
```

Wire navigation with a small inline script: build dot buttons, observe slides with
`IntersectionObserver` to add `.is-in` (entrance reveal) and track the current
index, advance on `ArrowUp/ArrowDown/PageUp/PageDown/Space/Home/End` and number
keys, and update the progress bar width. Respect `prefers-reduced-motion` (the CSS
already disables transitions; gate any `requestAnimationFrame` loop on the media
query too).

Deck content rules:
- **One idea per slide.** If a slide has two theses, split it.
- **Open with the thesis**, not a table of contents. The first slide states the
  single most important takeaway.
- **6–9 slides** for a typical explanation. More becomes a document, not a deck.
- Lead each slide with a `.slo-eyebrow` kicker that encodes something true about the
  slide's role (e.g. `Source · app.py:313`), not decoration.
- Use numbered markers **only** when the content is genuinely a sequence (a real
  process, an ordered timeline). Don't number unordered points.

---

### Step 5 — Build the document (if paged shape)

Wrap content in `.slo-doc` for a single long page, or produce multiple files linked
with `.slo-pager` (Prev / page x of n / Next). Keep running text within the
`--slo-measure` (65ch) width. Use `.slo-card` / `.slo-note` to break up long
sections and `.slo-table-scroll` around any wide table.

---

### Step 6 — Quality bar before shipping

Check every item:

- [ ] **Self-contained:** no external CSS, JS, font, or image URLs. Opens offline.
- [ ] **Code blocks highlighted — verified, not assumed:** every multi-line block is tagged `language-*`, and the colored tokens are **baked statically** into the markup (`<code class="hljs language-* " data-highlighted="yes">` with `hljs-*` spans) so highlighting survives a no-JS / strict-CSP viewer — no plain or hand-tagged multi-line code. Open the file and confirm color renders.
- [ ] **No horizontal page scroll:** wide code/tables live in their own
      `overflow-x:auto` container (`pre`, `.slo-table-scroll`).
- [ ] **Real content throughout:** no placeholder text; claims verified against
      source.
- [ ] **Valid HTML:** all non-void tags closed, attributes double-quoted.
- [ ] **Keyboard accessible:** visible `:focus-visible` state; deck navigable by
      keyboard; nav buttons have `aria-label`.
- [ ] **Reduced-motion respected.**
- [ ] **Both themes legible:** if you offer the alternate, spot-check contrast.
- [ ] **Tasteful, not over-designed:** spend boldness on one accent; keep the rest
      quiet. Avoid generic-AI tells (centered everything, gratuitous gradients,
      emoji section markers).

---

### Step 7 — Deliver

1. Write the `.html` file. By default write it to the session **scratchpad**
   directory (temporary). If the user wants it kept, write it into the repo at a path
   they choose — do not assume a repo location.
2. If running in the Slo / Claude Code TUI and the user wants a hosted preview, you
   may publish it as an Artifact. **Always also tell the user the raw local file
   path** — an Artifact is hosted on claude.ai, not raw HTML they own.
3. State plainly: the file path, the format chosen (deck vs document), the theme, and
   that it is fully self-contained.

A worked reference deck (this exact pattern, real content) is bundled at
`assets/example-slide-deck.html`. Read it when you need a concrete model.
