---
name: present-as-pdf-book
description: Produce a beautiful, print-ready PDF that looks like an O'Reilly field
  guide — a navy full-bleed cover, a dotted-leader table of contents, part dividers,
  chapter/section pages with eyebrow kickers and rust underlines, callout boxes,
  accent quotes, clean captioned SVG diagrams, and running footers — rendered with
  WeasyPrint using local book fonts (Baskerville, PT Serif, Helvetica Neue, JetBrains
  Mono). Works for ANY subject (portfolio, report, briefing, whitepaper, explainer,
  proposal, field guide), not just portfolios. Encodes the full design system, the
  render pipeline, the diagram conventions, and the exact witty-but-technical writing
  voice.
when_to_use: Use whenever the user wants a polished, designed PDF document that reads
  like a printed technical book — a portfolio, a product walkthrough, an architecture
  brief, a research report, a proposal, an explainer, or a "field guide". Trigger on
  requests like "make a PDF like the portfolio", "turn this into a designed PDF book",
  "generate a field-guide PDF", "produce a professional PDF report", or any ask that
  pairs "PDF" with a request for design, layout, or a book-like feel. Do NOT use for
  slide decks (use present-as-html) or single scrolling web pages (use
  present-as-single-page).
group: presentation
kind: skill
---

# Present as PDF Book (Field-Guide Style)

## Skill summary

- **Name:** `present-as-pdf-book`
- **Description:** Assemble any subject into a print-ready PDF styled as an O'Reilly-style
  technical field guide — full-bleed navy cover, dotted-leader TOC with real page numbers,
  optional part dividers, chapter pages with eyebrow kickers and short rust underlines,
  callout boxes, accent quotes, legible captioned SVG diagrams, and running footers.
- **When to use:** Any request for a designed, book-like PDF document (portfolio, report,
  brief, whitepaper, proposal, explainer). Not for slide decks or web pages.
- **Group:** `presentation`
- **Kind:** `skill`

## What this produces

A single self-contained HTML file rendered to PDF by **WeasyPrint**. The output is A4,
paginated like a real book:

- A **full-bleed navy cover**: small rust eyebrow, a large Baskerville title, an italic
  subtitle, an optional hero diagram, and a thin footer line.
- A **Contents** page: heading with a short rust rule, a one-line framing sentence, two
  side-by-side callout boxes (one blue, one cream), a rust accent quote, and a
  **dotted-leader table of contents whose page numbers are generated automatically** via
  `target-counter()`.
- Optional **full-bleed part dividers** (navy pages that introduce a section).
- **Chapter / section pages**: an uppercase rust "kicker" (e.g. `CHAPTER TWO · ATLAS`),
  a bold serif title with a short rust underline, a slightly larger `lead` paragraph, then
  body text, `h3` sub-heads, figures, boxes, accent quotes, and tables.
- **Running footers** on every content page: centred page number + a right-aligned muted-rust
  running title.

The look is deliberately identical to the reference build (a technical "field guide"). The
subject is interchangeable — the design, typography, and voice are the constant.

## Examples

- "Make me a PDF like the portfolio, but about our new platform."
- "Turn this architecture doc into a designed field-guide PDF."
- "Produce a professional, book-style PDF report on X."
- "Generate a polished PDF brief with diagrams and a table of contents."
- "Write this up as an O'Reilly-style PDF."

## The toolchain (do this once, reuse every time)

Rendering uses **WeasyPrint 69+** and **local macOS book fonts** — no network, no web fonts.
Fonts relied upon (all present on macOS): **Baskerville** (display titles), **PT Serif**
(body — the exact field-guide body serif), **Helvetica Neue** (eyebrows, labels, captions,
table headers), **JetBrains Mono** (code/identifiers).

Create the render venv once, then reuse it:

```bash
# one-time: weasyprint venv (native deps come from Homebrew: pango cairo harfbuzz fontconfig)
~/.pyenv/versions/3.11.7/bin/python -m venv /tmp/wp-venv
/tmp/wp-venv/bin/pip install --quiet --upgrade pip weasyprint

# render (repeat after every edit). --base-url makes relative diagram paths resolve.
cd <doc-dir>
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
/tmp/wp-venv/bin/python -m weasyprint -e utf-8 --base-url "$(pwd)/" input.html output.pdf
```

Ship a `render.sh` next to the document so the user can regenerate it:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
VENV="/tmp/wp-venv"
[ -x "$VENV/bin/python" ] || { ~/.pyenv/versions/3.11.7/bin/python -m venv "$VENV"; "$VENV/bin/pip" install -q weasyprint; }
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
"$VENV/bin/python" -m weasyprint -e utf-8 --base-url "$(pwd)/" input.html output.pdf
echo "Rendered output.pdf"
```

> **Non-macOS fallback:** if Baskerville / PT Serif are unavailable, substitute
> `Playfair Display` (display) and `Source Serif 4` / `Georgia` (body) via a Google Fonts
> `@import`, keep everything else identical. The macOS system fonts are preferred because they
> render the reference look with zero network dependency.

## The workflow — follow this order every time

**1 · Gather and VERIFY the source material.** Never invent facts. If the subject is code or
a system, explore the real artifacts first (launch parallel `Explore` agents over each
repo/area) and extract *concrete, current* specifics: named components, protocols, models,
counts, and 2–3 "diagram-worthy" structures per topic. If the brief supplies claims, keep
them; where a claim outruns what you can verify, soften it to what is defensible rather than
overstate. Concrete specifics (real numbers, real names) are the flair — mine for them.

**2 · Outline the book.** Decide the spine: cover → contents → (optional introduction /
part divider) → chapters/sections (one per topic) → a short synthesis/closing. Aim for
~2 pages per chapter. Give every chapter an *evocative but concrete* title
("Earning the right to speak", not "The Compliance Module").

**3 · Design the diagrams (1–2 per chapter).** They must carry real information, not
decoration — the old failure mode is illegible, shrunken, value-free diagrams. Author clean
SVGs in the palette (see below), one hero diagram per chapter plus an optional supporting one.

**4 · Write in the voice** (see "Writing voice" — this is the part that makes or breaks it).

**5 · Render** with the command above.

**6 · VERIFY VISUALLY.** Read the produced PDF back page by page (open/inspect the actual
rendered pages, not just the HTML). Check: cover bleed, TOC page numbers, diagram legibility,
widow/orphan and page breaks, footer correctness. Fix and re-render until clean. This visual
read-back is mandatory — layout bugs are invisible in the HTML.

## Writing voice (critical — match this exactly)

The prose is the point. It should be **engaging, witty, and intelligent** — it holds the
subject up to the light without boring the reader, and it stays technically precise and
genuinely relevant. Aim for the flair of a sharp technical essayist, not a brochure.

**Do:**
- Open each chapter with a strong `lead` paragraph that frames the real problem.
- Use concrete numbers and real component names as the texture — they *are* the wit.
- Land the occasional dry, precise aside or unexpected analogy ("meeting aviation through the
  in-flight magazine"). Earn it; don't force it.
- Vary sentence length and rhythm. Prefer the active, specific verb.
- Give each callout box one idea; make each figure caption add a *distinct* fact, never a
  restatement of the diagram's own label.

**Never:**
- Reference the document itself, its purpose, its audience, or the fact that it is a
  portfolio/report ("this is aimed at both technical and non-technical readers", "for the
  hiring team", "the point of this section"). Just present the subject.
- Be conceited or self-congratulatory ("that matters for two reasons: first, it demonstrates
  confidence…", "this is not a pitch-deck artifact"). Show, don't preen.
- Condescend or over-explain the obvious.
- Lapse into AI tells: no end-of-line hyphenation (set `hyphens: manual`, ragged right); use
  em-dashes tastefully, not in every sentence; avoid the "Not X. Just Y." staccato and the
  reflexive rule-of-three.

The test: a knowledgeable reader should find it a *pleasure* to read and learn nothing false.

## Diagram conventions

- Author each diagram as its own `.svg` file in a `diagrams/` folder; reference with
  `<img src="diagrams/name.svg">`. Size to full content width; **never** cap the height (the
  classic bug that renders diagrams illegible).
- Use **system fonts inside SVG** (`font-family="'Helvetica Neue', Arial, sans-serif"`) so text
  is crisp regardless of web-font loading. Labels ≥ 10px; titles 12–14px.
- Use the palette. Colour-code node types (navy / teal / rust / cream). Give generous
  whitespace and clear arrowheads (an SVG `<marker>`). Keep 4–8 elements per diagram.
- Vocabulary that reads well: horizontal **pipelines** with labelled arrows; **node graphs**
  (mesh / fan-out); **layered stacks**; **metaphor cards** in a row; **before/after** panels;
  **budget bars**. Put a one-line caption below via `<figcaption>` that states a fact the
  picture does not already spell out.
- For the cover, a small labelled **constellation** of the topics reads beautifully on navy
  (light strokes, coloured nodes, soft-white labels).

## The design system — copy this CSS verbatim

Palette: navy `#1e2f4d`, rust `#c06a2f` (soft `#d98a4e`), teal `#2f7d72`, cream `#f5ecd9`
(border `#e6d5b6`), blue box `#eef2f7` (border `#d5deeb`), ink `#2b2f36`, muted `#6c7480`,
faint `#8a919c`.

```css
:root{
  --navy:#1e2f4d; --rust:#c06a2f; --rust-soft:#d98a4e; --teal:#2f7d72;
  --ink:#2b2f36; --muted:#6c7480; --faint:#8a919c; --line:#c9d2de;
  --cream:#f5ecd9; --cream-bd:#e6d5b6; --blue:#eef2f7; --blue-bd:#d5deeb;
}
@page{
  size:A4; margin:20mm 20mm 17mm 20mm;
  @bottom-center{ content: counter(page); font-family:"Helvetica Neue",Arial,sans-serif; font-size:8pt; color:#9aa0aa; }
  @bottom-right{ content:"RUNNING TITLE HERE"; font-family:"Helvetica Neue",Arial,sans-serif; font-size:7.5pt; letter-spacing:.3px; color:#b57a49; }
}
@page cover{ margin:0; @bottom-center{content:none} @bottom-right{content:none} }
@page divider{ margin:0; @bottom-center{content:none} @bottom-right{content:none} }

body{ font-family:"PT Serif",Georgia,serif; color:var(--ink); font-size:10.4pt; line-height:1.52; margin:0; hyphens:manual; }
p{ margin:0 0 7.5pt 0; }
strong{ color:var(--navy); } em{ color:#3a3f47; }
code{ font-family:"JetBrains Mono","SFMono-Regular",Menlo,monospace; font-size:8.6pt; background:#f1f3f6; padding:1px 4px; border-radius:3px; color:#33475f; }

/* full-bleed cover */
.cover{ page:cover; background:var(--navy); color:#fff; width:210mm; height:297mm; box-sizing:border-box; padding:36mm 26mm 20mm 26mm; display:flex; flex-direction:column; justify-content:space-between; }
.cover-kicker{ font-family:"Helvetica Neue",Arial,sans-serif; text-transform:uppercase; letter-spacing:4px; font-size:9.5pt; color:var(--rust-soft); margin:0 0 14pt 0; }
.cover-title{ font-family:"Baskerville",Georgia,serif; font-weight:normal; font-size:52pt; line-height:1.02; margin:0; color:#fff; }
.cover-sub{ font-style:italic; font-size:15pt; line-height:1.4; color:#c4cfe0; margin:16pt 0 0 0; max-width:150mm; }
.cover-art img{ width:66%; display:block; margin-left:auto; }
.cover-foot{ font-family:"Helvetica Neue",Arial,sans-serif; font-size:9pt; letter-spacing:.4px; color:#8fa0bd; border-top:1px solid rgba(255,255,255,.16); padding-top:11pt; }

/* full-bleed part divider */
.divider{ page:divider; background:var(--navy); color:#fff; width:210mm; height:297mm; box-sizing:border-box; padding:110mm 26mm 0 26mm; }
.div-kicker{ font-family:"Helvetica Neue",Arial,sans-serif; text-transform:uppercase; letter-spacing:4px; font-size:9.5pt; color:var(--rust-soft); margin:0 0 12pt 0; }
.div-title{ font-family:"Baskerville",Georgia,serif; font-weight:normal; font-size:37pt; line-height:1.05; margin:0; color:#fff; }
.div-sub{ font-size:13pt; line-height:1.5; color:#b9c4d6; margin:16pt 0 0 0; max-width:135mm; }

/* chapters */
.chapter{ break-before:page; }
.kicker{ font-family:"Helvetica Neue",Arial,sans-serif; text-transform:uppercase; letter-spacing:2.5px; font-size:8.5pt; color:var(--rust); margin:0 0 6pt 0; }
h1.title{ font-family:"PT Serif",Georgia,serif; font-weight:700; font-size:21pt; line-height:1.12; color:var(--navy); margin:0; }
h1.title::after{ content:""; display:block; width:52px; height:2.5px; background:var(--rust); margin:9pt 0 0 0; }
h3{ font-family:"PT Serif",Georgia,serif; font-weight:700; font-size:12.6pt; color:var(--navy); margin:15pt 0 4pt 0; page-break-after:avoid; }
.lead{ font-size:12.2pt; line-height:1.5; color:#39404a; margin-top:14pt; }

/* contents + dotted-leader TOC with auto page numbers */
h1.contents-h{ font-family:"PT Serif",Georgia,serif; font-weight:700; font-size:24pt; color:var(--navy); margin:0 0 3pt 0; }
h1.contents-h::after{ content:""; display:block; width:52px; height:2.5px; background:var(--rust); margin:9pt 0 14pt 0; }
ul.toc{ list-style:none; padding:0; margin:6pt 0 0 0; }
ul.toc li{ font-family:"PT Serif",Georgia,serif; font-size:12pt; margin:0 0 11pt 0; }
ul.toc li .num{ font-family:"Helvetica Neue",Arial,sans-serif; font-size:8.5pt; letter-spacing:1.5px; color:var(--rust); margin-right:9pt; }
ul.toc a{ color:var(--ink); text-decoration:none; }
ul.toc a::after{ content: leader('.') " " target-counter(attr(href url), page); color:var(--rust); font-family:"Helvetica Neue",Arial,sans-serif; font-size:9.5pt; }

/* callout boxes + accent quote */
.two-col{ display:flex; gap:12pt; margin:14pt 0; }
.two-col .box{ flex:1; }
.box{ border-radius:7px; padding:11pt 13pt; break-inside:avoid; }
.box.blue{ background:var(--blue); border:1px solid var(--blue-bd); }
.box.cream{ background:var(--cream); border:1px solid var(--cream-bd); }
.box h4{ font-family:"PT Serif",Georgia,serif; font-weight:700; font-size:11pt; color:var(--navy); margin:0 0 5pt 0; }
.box p,.box li{ font-size:10pt; line-height:1.45; }
.box ul{ margin:2pt 0 0 0; padding-left:15pt; }
.accent{ border-left:3px solid var(--rust); padding:2pt 0 2pt 14pt; margin:15pt 0; break-inside:avoid; }
.accent .label{ font-family:"Helvetica Neue",Arial,sans-serif; text-transform:uppercase; letter-spacing:2px; font-size:8pt; color:var(--rust); margin:0 0 5pt 0; }
.accent p{ font-size:12.5pt; line-height:1.45; color:var(--navy); margin:0; font-style:italic; }

/* figures + tables */
figure{ margin:15pt 0; break-inside:avoid; text-align:center; }
figure img{ width:100%; max-width:100%; }
figure.narrow img{ width:74%; }
figcaption{ font-family:"Helvetica Neue",Arial,sans-serif; font-size:8.6pt; color:var(--faint); margin-top:7pt; line-height:1.4; }
table{ width:100%; border-collapse:collapse; margin:13pt 0; font-size:9.2pt; break-inside:avoid; }
thead th{ background:var(--navy); color:#fff; font-family:"Helvetica Neue",Arial,sans-serif; font-weight:600; font-size:8.6pt; text-align:left; padding:6pt 8pt; }
tbody td{ border-bottom:1px solid #e2e7ee; padding:6pt 8pt; vertical-align:top; line-height:1.4; }
tbody tr:nth-child(even){ background:#f6f8fb; }
.pull{ color:var(--navy); font-weight:700; }
```

## HTML skeleton — the elements

```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<title>Document Title</title><style>/* the CSS above, with the running title set */</style></head>
<body>

<!-- COVER -->
<section class="cover">
  <div>
    <p class="cover-kicker">Eyebrow · Kicker</p>
    <h1 class="cover-title">Big<br/>Title</h1>
    <p class="cover-sub">An italic subtitle that states the through-line.</p>
  </div>
  <div class="cover-art"><img src="diagrams/cover.svg" alt=""/></div>
  <div class="cover-foot">Topic one · Topic two · Topic three</div>
</section>

<!-- CONTENTS (dotted-leader TOC; hrefs point to chapter ids) -->
<section>
  <h1 class="contents-h">Contents</h1>
  <p style="max-width:150mm;color:#39404a;">One-line framing sentence.</p>
  <div class="two-col">
    <div class="box blue"><h4>Left box</h4><p>…</p></div>
    <div class="box cream"><h4>Right box</h4><ul><li>…</li></ul></div>
  </div>
  <div class="accent"><p class="label">The one idea</p><p>A single memorable line.</p></div>
  <ul class="toc">
    <li><span class="num">01</span><a href="#ch-one">Chapter One — Title</a></li>
    <li><span class="num">02</span><a href="#ch-two">Chapter Two — Title</a></li>
  </ul>
</section>

<!-- OPTIONAL PART DIVIDER -->
<section class="divider" id="part-x">
  <p class="div-kicker">Part / Introduction</p>
  <h1 class="div-title">Section<br/>Title</h1>
  <p class="div-sub">A short framing line.</p>
</section>

<!-- CHAPTER -->
<section class="chapter" id="ch-one">
  <p class="kicker">Chapter One · Topic</p>
  <h1 class="title">An evocative, concrete title</h1>
  <p class="lead">A strong opening that frames the real problem.</p>
  <p>Body… use <code>identifiers</code> and <span class="pull">key terms</span> inline.</p>
  <figure>
    <img src="diagrams/one.svg" alt=""/>
    <figcaption>A caption that adds a fact the diagram does not spell out.</figcaption>
  </figure>
  <h3>A sub-head</h3>
  <p>More body.</p>
  <div class="two-col">
    <div class="box blue"><h4>What it is</h4><ul><li>…</li></ul></div>
    <div class="box cream"><h4>Why it matters</h4><p>…</p></div>
  </div>
</section>

</body></html>
```

Notes:
- The TOC page numbers are produced automatically by `target-counter(attr(href url), page)` —
  each `<a href="#id">` must match an element `id` on its target page. Re-render after adding
  chapters; the numbers recompute.
- The cover is page 1 but unnumbered (footer suppressed); the Contents page shows "2", matching
  the reference look.
- Use `figure.narrow` for portrait-ish diagrams so they don't dominate the page.

## Adapting to the subject (it is not always a portfolio)

- **Report / brief / whitepaper:** cover + contents + sections + a "what this means" closing.
  Kicker = `SECTION ONE · <AREA>`. Running title = the report name.
- **Product / architecture walkthrough:** one chapter per subsystem; hero diagram per chapter;
  a synthesis chapter on the cross-cutting design.
- **Explainer / field guide:** optional part dividers ("Part One — In plain language" / "Part Two
  — For builders") — but never phrase dividers as instructions to the *reader*; describe the
  *subject matter* of the part.
- Keep the palette, fonts, spacing, and voice fixed across all of them — that constancy is the
  brand.

## Guidance

Follow the workflow in order: gather verified source material, outline the book, design diagrams, write in the required voice, render with WeasyPrint, and visually verify the PDF. Reuse the design system and CSS palette exactly; adapt only the subject matter and running title. Always deliver `input.html`, `output.pdf`, `diagrams/*.svg`, and `render.sh`.


- Renders cleanly with WeasyPrint (no errors).
- You have **read the rendered PDF back** and confirmed: cover bleed, auto TOC numbers, legible
  diagrams, clean page breaks, correct running footer.
- Prose is in-voice: witty, precise, no meta/audience/purpose references, no condescension, no
  end-of-line hyphenation.
- Deliver `input.html`, `output.pdf`, `diagrams/*.svg`, and `render.sh`; offer the `.md` source
  too when useful.
