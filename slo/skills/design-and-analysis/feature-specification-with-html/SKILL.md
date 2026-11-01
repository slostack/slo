---
name: feature-specification-with-html
description: Render the feature specification family as self-contained HTML in the Slo theme — overview.html in the feature-specifications section order, one page per standalone engineering sub-spec in the breakdown-feature-spec-to-tasks template, and a task list page.
when_to_use: Use when the operator wants the feature specification delivered as HTML instead of Markdown. Content rules come from feature-specifications (overview) and breakdown-feature-spec-to-tasks (sub-specs and task list); this skill adds only the HTML rendering, theme and navigation rules.
group: design-and-analysis
kind: skill
---

# Feature Specifications in HTML

## Skill summary

- **Name:** `feature-specification-with-html`
- **Description:** Renders the same specification family as the Markdown skills, as self-contained HTML pages in the Slo theme: an overview, one page per standalone engineering sub-spec, and a task list.
- **When to use:** The operator wants the feature specification itself delivered as HTML. For Markdown, use `feature-specifications` and `breakdown-feature-spec-to-tasks` directly.
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Output:** `<feature-specifications-root>/<NN>-<feature>/` with `overview.html`, `task-list.html` and `<NN>.a.n-<slice>.html` pages

## Examples

- "Write the spec for this feature in HTML."
- "Give me the overview and the engineering sub-specs as HTML pages I can open in a browser."
- "Revise sub-spec 96.a.1 in the HTML spec after this review."

## Guidance

> **Remember:** the content is defined elsewhere. This skill changes the format, never the content or the quality bar.

| Concern | Owner |
|---|---|
| What the overview contains and in what order | [`feature-specifications`](../feature-specifications/SKILL.md#the-document) |
| What each engineering sub-spec contains | [`breakdown-feature-spec-to-tasks`](../breakdown-feature-spec-to-tasks/SKILL.md#5-write-a-standalone-sub-spec-for-each-sub-step) |
| What the task list contains | [`breakdown-feature-spec-to-tasks`](../breakdown-feature-spec-to-tasks/SKILL.md#9-add-a-concise-sub-spec-index-and-implementation-order) |
| How the family is reviewed | [`feature-specification-verification`](../feature-specification-verification/SKILL.md) |
| How behaviour is tested | [`test-verification-policy`](../../coding/test-verification-policy/SKILL.md) |
| Theme, layout and HTML rules | This skill |

Where this file and an owning skill seem to disagree on content, the owning skill wins.

## 1. The specification family

The HTML family mirrors the Markdown family file for file:

```text
<feature-specifications-root>/
└── <NN>-<feature>/
    ├── overview.html               # feature-specifications section order
    ├── task-list.html              # dependency-ordered links to every sub-spec
    ├── <NN>.a.1-<slice>.html       # standalone engineering sub-spec
    └── <NN>.a.2-<slice>.html
```

- **Paths and naming** follow [Artifact paths and skill discovery](../feature-specifications/SKILL.md#artifact-paths-and-skill-discovery). Keep the `<NN>.a.n` numbering; use `<NN>.b.n` for a later phase. Never name a spec `request.md`.
- **Both halves are required.** An overview without sub-specs, or sub-specs without an overview, is an incomplete family, even for a small feature.
- **HTML is the authority.** Do not keep a parallel Markdown copy that can drift. Review notes and evidence stay outside the spec pages.

## 2. Before writing

Do exactly what the Markdown overview skill requires. Follow these sections by link; do not restate them:

1. [Inputs](../feature-specifications/SKILL.md#inputs). The source request may live in any source-control or project-management tool.
2. [Mandatory first task: establish knowledge-base context](../feature-specifications/SKILL.md#mandatory-first-task-establish-knowledge-base-context), through [`locate-knowledge-base`](../locate-knowledge-base/SKILL.md). A missing knowledge base is non-blocking.
3. [Read before writing](../feature-specifications/SKILL.md#read-before-writing), including the matching convention skills.
4. [Duplicate-code check](../feature-specifications/SKILL.md#duplicate-code-check). The table appears in the overview's current state and in each sub-spec's ownership section.
5. [Cohesion over line-level DRY](../feature-specifications/SKILL.md#cohesion-over-line-level-dry).

For the sub-specs, also follow sections 2 to 4 of [`breakdown-feature-spec-to-tasks`](../breakdown-feature-spec-to-tasks/SKILL.md).

## 3. Overview page

`overview.html` uses the eight sections of [The document](../feature-specifications/SKILL.md#the-document), in the same order, each as its own anchored `<section>`:

1. What this feature does
2. Prerequisites
3. Approach
4. Domains and data
5. Journeys and workflows
6. Modules, interfaces and caller use
7. Existing code changes
8. Tests, limits and next steps

In the delivery order, link each vertical slice to its sub-spec page. Apply the [Before saving](../feature-specifications/SKILL.md#before-saving) checklist unchanged.

## 4. Sub-spec and task list pages

Each `<NN>.a.n-<slice>.html` page uses the numbered template in [Write a standalone sub-spec for each sub-step](../breakdown-feature-spec-to-tasks/SKILL.md#5-write-a-standalone-sub-spec-for-each-sub-step):

- status callout and metadata table at the top;
- numbered sections: Outcome, Read first, Ownership and interfaces, Schema contract, Core logic, the feature-specific detailed contracts, Files and handoff, Acceptance and tests;
- a Definition of done checklist at the end, unchecked while authoring.

`task-list.html` follows [Add a concise sub-spec index and implementation order](../breakdown-feature-spec-to-tasks/SKILL.md#9-add-a-concise-sub-spec-index-and-implementation-order): one table row per sub-spec, schema work first, acyclic dependencies.

Apply the [family review checklist](../breakdown-feature-spec-to-tasks/SKILL.md#10-review-the-detailed-specification-family), reading `.md` as `.html`.

## 5. Testing guidance

Tests follow [`test-verification-policy`](../../coding/test-verification-policy/SKILL.md). In short:

- **Behaviour tests first,** driving each slice end to end through its real entry point and persistence.
- **Unit tests only** for critical methods with complex computation.
- **No elaborate Playwright harness** is required, for the feature or for the HTML pages themselves.

## 6. HTML rendering rules

### Theme

- Use the Slo design language from [`present-as-single-page`](../../presentation/present-as-single-page/SKILL.md).
- Tokyo Night is the default (`--slo-bg #1a1b26`, `--slo-accent #7aa2f7`). Near-black with phosphor-green accents (`--slo-accent #00ff7f`) is the alternate, set with `data-theme="dark"` on `<html>`.
- Use the `--slo-*` tokens, a hero, sticky section navigation and a visible theme toggle.
- Use a different template only when the operator supplies one.

### Self-contained and CSP-safe

- One `.html` file per document. Embed all styles and scripts; load no remote fonts, scripts, images or stylesheets.
- No inline event handlers (`onclick=`) and no `eval`. Keep scripts small and optional: every page must read correctly with scripts disabled.
- Support narrow screens, keyboard focus and print.

### Content fidelity

- Code and contracts go in full in `<pre><code>` blocks. Tables are real `<table>` elements, never images or styled `<div>` grids.
- Markdown callouts (`[!warning]`, `[!note]`, `[!important]`) become styled `<aside>` blocks with a visible text label, such as "Status: BLOCKED".
- Mark new, changed, removed, proposed and unresolved items with text labels as well as colour.
- Collapsible `<details>` may hold long detail, but never the only copy of a contract, and never the acceptance table.
- Each section, acceptance row (`A1`, `A2`, …) and open decision has a stable `id` so reviewers can link to it.

### Diagrams

The owning skills choose which diagrams to draw (see [Visual aids](../feature-specifications/SKILL.md#visual-aids)). This skill decides how they render:

- **Inline SVG** is the default for entity-relationship, class, sequence, state and flow diagrams. Give each SVG a `<title>` and use the same names as the tables.
- **ASCII in `<pre>`** is the fallback for trees and small flows.
- **No Mermaid runtime.** It needs a remote or large embedded script. A Mermaid source block alone is not a diagram; if you keep one, place it beside the rendered SVG, not instead of it.
- A TUI change needs before and after wireframes showing focus, input and unaffected areas.

### Navigation

| Page | Must link to |
|---|---|
| `overview.html` | `task-list.html` and every sub-spec, from the delivery order |
| `task-list.html` | `overview.html` and every sub-spec |
| `<NN>.a.n-<slice>.html` | `overview.html` and `task-list.html` in a header breadcrumb; each "Depends on" and "Hands off to" sub-spec; previous and next sub-spec in delivery order |

Use relative links only. Every link and `#id` anchor must resolve inside the family folder.

## 7. Before saving

- [ ] The overview passes the `feature-specifications` checklist; every sub-spec and the task list pass the `breakdown-feature-spec-to-tasks` checklist.
- [ ] Every overview section and sub-spec section is present, visible and anchored.
- [ ] Each page is self-contained: no remote assets, no inline event handlers, readable without scripts.
- [ ] Every diagram renders offline as inline SVG or ASCII.
- [ ] Every relative link and anchor in the family resolves.
- [ ] No Markdown copy of the spec exists beside the HTML.
- [ ] No claim of approval, review, implementation or passing tests that did not happen.

Report the saved paths, a short summary, the checks run and the open decisions. Get explicit confirmation before committing, publishing or creating external tasks.

## 8. Relationship to other skills

- [`feature-specifications`](../feature-specifications/SKILL.md) remains the default overview author and produces `overview.md`. This skill renders the same overview as HTML.
- [`breakdown-feature-spec-to-tasks`](../breakdown-feature-spec-to-tasks/SKILL.md) owns the breakdown into standalone engineering sub-specs and the task list. This skill renders them as HTML.
- [`feature-specification-verification`](../feature-specification-verification/SKILL.md) reviews the whole family. REVISE findings go to the owning skill: overview findings follow `feature-specifications`, sub-spec and task list findings follow `breakdown-feature-spec-to-tasks`. Re-render the affected HTML pages afterwards.
- The [Specification Development workflow](../../orchestration/workflows/specification-development.md) sequences these steps.
- [`explain-with-html`](../explain-with-html/SKILL.md) explains existing behaviour in HTML; this skill specifies proposed behaviour.
