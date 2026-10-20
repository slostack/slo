---
name: explain-with-html
description: Explain existing or proposed functionality in self-contained HTML, one concept per section, with source-grounded journeys, domain ownership, control-flow diagrams, and a final code walkthrough of domain types and actual or explicitly proposed interfaces. Explanation only, not implementation.
when_to_use: Use when the user asks for an HTML explanation of how a functionality works or will work, especially its domains, interfaces, execution flow, lifecycle, and smallest complete change. Not a generic slide deck or permission to implement the feature.
group: design-and-analysis
kind: skill
---

# Explain Functionality with HTML

## Skill summary

Help a programmer visualize a functionality from user action to observable outcome,
then connect that mental model to named domain types, interfaces, and calls in code.
Produce one self-contained scrolling HTML document: one concept per section,
diagrams that explain behavior, and implementation-facing examples near the end.
Explain existing and proposed systems without confusing either with the other.

## Examples

- “Explain how this functionality works in HTML, including the domains and interfaces.”
- “Expand this architecture with process ownership, replies, cancellation, and code flow.”
- “Show the smallest complete change, then walk through the interfaces a programmer would use.”

A good reading journey is:

```text
User problem → current journey → intended outcome → ownership and contracts
             → behavior diagrams → domain types → interfaces → code journey
```

Arrows describe the order of explanation, not runtime dependencies. Use the actual
feature and repository language; do not carry over a previous feature's database,
queues, agent roles, or framework as a default architecture.

## Guidance

### 1. Read the required design guidance before designing the HTML

Read all three prerequisites in full **before choosing the document structure,
domains, interfaces, diagrams, or visual layout**:

1. [solution-design](../../coding/solution-design/SKILL.md) — investigate actual
   callers, design domain-first, define whole interfaces, and identify the
   smallest complete vertical slice. Present the journey before implementation.
2. [coding-rules](../../coding/coding-rules/SKILL.md) — reduce complexity, reuse
   existing responsibility owners, and hide decisions rather than duplicate them.
3. [code-design-principles](../../coding/code-design-principles/SKILL.md) — assign
   ownership, choose deep modules and real seams, and make control flow explicit.

Apply the guidance, not just links in the finished page. Record the selected
sources and material design decisions. Respect project instructions and the
user's approved contracts; do not silently redesign a feature to simplify a diagram.

Then read [explain-how-it-works](../explain-how-it-works/SKILL.md) for the guided
narrative and [present-as-single-page](../../presentation/present-as-single-page/SKILL.md)
for rendering, accessibility, and static syntax highlighting. This skill owns the
functionality explanation; the presentation skill owns the visual shell. Use the
active skill index/manifest to resolve installed overrides and relevant language
conventions, preserving explicitly supplied paths and identifying conflicts.

**Permission boundary:** this is explanation-only work. Do not implement application
code, change wiring, run migrations, install skills, or spawn sub-agents without
separate authorization. Creating this skill does not execute it. Prefer the user's
requested HTML destination; do not silently add or overwrite `design.md` merely
because a prerequisite describes that output. Produce companion documents only
when requested. Preserve unrelated artifacts when expanding an existing HTML file.

### 2. Investigate the functionality, not just the diagram

Collect the audience, problem, repository/revision, source artifacts, output path,
constraints, and non-goals. Trace real callers through state owners to the final
observable result, including the return path. For greenfield work, say explicitly
that no implementation exists.

Separate **verified current behavior**, **proposed behavior**, **assumptions**, and
**open decisions**. Cite source files, identifiers and revision; use `file:line` for
mechanism claims and label excerpts. A method name is not proof of its contract.
Never describe a proposal, read test, or successful HTML render as working software.

Investigate existing owners by behavior, not only by a proposed feature name.
Explain what will be reused, extended, replaced, removed, and deferred. Compare the
strongest simpler alternative and name the guarantees it sacrifices. Do not call a
partial delivery checkpoint a complete solution.

Before styling, build a compact explanation map:

| Reader's question | Evidence / design decision | Diagram | Later code anchor |
|---|---|---|---|
| What initiates the journey? | Real entry point and input | Sequence start | Caller snippet |
| Who owns this state? | Domain and lifetime | Ownership diagram | Named state type |
| What can the caller request? | Whole interface | Labeled handoff | Method signature |
| How does the result return? | Response/event/result contract | Return arrows | Result handling |

Populate it for the actual feature; do not publish an unfilled template.

### 3. One concept per section

Every HTML section must focus on **one concept or one reader question**. Give it a
claim-bearing heading, define the concept in plain language, then explain its
responsibility, its relationships, and its observable effect. Finish with a short
takeaway. Split unrelated questions into separate anchored sections; do not hide a
second design inside a large card or an omnibus “architecture details” section.

Use this local pattern, omitting only inapplicable elements:

1. **Question / claim:** what will the programmer understand here?
2. **Meaning and purpose:** what is it, and why is it needed?
3. **Owner and contract:** who decides, what data crosses the interface?
4. **Diagram or concrete example:** show the decision or handoff.
5. **Boundary:** what does this concept not promise?
6. **Code connection:** link to the relevant type or call near the end.

Introduce terms before relying on them. Start with five to eight essential terms
and add domain detail progressively. A reader stopping early must retain a correct
model; do not save a safety-critical qualification for an appendix.

Recommended reading order (expand repeated domain/journey sections as necessary):

1. Status, scope, and how to read.
2. The problem and intended user outcome.
3. The current end-to-end journey.
4. The proposed change and its smallest complete scope.
5. Shared language and a system-shape overview.
6. Each domain's state, rules, and ownership, one concept at a time.
7. Each interface's behavior and guarantees.
8. Each main journey, from trigger through observation of the result.
9. Lifecycle, cancellation, and recovery, in separate focused sections.
10. Alternatives, compatibility, and deferred work, separated by question.
11. **Domains as code.**
12. **Interfaces as code.**
13. **The journey through code.**
14. Verification, unresolved decisions, and the takeaway/sources.

The final three code sections are mandatory, not optional appendices. They connect
previously explained concepts to implementation without moving a wall of code
before the conceptual explanation.

### 4. Define domains, modules, and whole interfaces

A **domain** groups a cohesive concept, state, and rules; it is not automatically a
table, service class, process, or diagram box. For each domain explain meaning,
identity, authoritative versus derived/cached state, valid transitions, invariants,
operations, lifetime, and what it explicitly does not own. Name the data structures
and validation boundaries; static type declarations alone do not validate input.

A **module** hides implementation behind an **interface**. Its **seam** is where
callers request behavior without reproducing its internal decisions. Identify real
callers and adapters, public versus host-only/private interfaces, hidden mechanisms,
leverage, and locality. Do not invent a class for each arrow.

Apply this deletion test verbatim:

> “If this module disappeared, would complexity disappear too, or would its work have to be repeated across callers?”

Define the whole interface: purpose, operations, named input/output types, caller
responsibilities, invariants, ordering, defaults, configuration, authorization,
errors, effects, retries/idempotency, concurrency, limits, startup, shutdown,
cancellation, cleanup, and performance expectations. State what is not guaranteed.
Use a common caller example and a failure or advanced example.

Distinguish commands expressing intent, events reporting facts, admission/application
receipts, streamed content, and terminal results. Explain correlation IDs and their
lifetimes. Show how replies reach the initiating user or caller; do not stop the
journey at “queued” or “method called.”

### 5. Draw behavior and execution ownership

Use diagrams to answer specific questions, not decorate repeated prose:

- **Architecture:** modules, dependencies, and authoritative owners.
- **Sequence:** exact requests, data handoffs, responses, and asynchronous events.
- **Lifecycle/state:** valid transitions, cancellation, terminal outcomes.
- **Decision:** eligibility, authorization, capacity, and failure branches.
- **Storage/execution topology:** logical state versus physical files/databases,
  processes, threads, async tasks, and external systems where relevant.

Use inline SVG or HTML/CSS diagrams; do not require remote Mermaid or scripts to
make the explanation appear. Label arrows with operations or data and use a legend
for different arrow meanings. Distinguish planned versus existing elements. Keep
one primary idea per diagram; split a crowded drawing.

Name who creates, starts, awaits/joins, cancels, closes, and releases each resource.
Show what runs concurrently, what waits, who writes shared state, where transactions
begin/end, and what survives a crash. A logical module is not necessarily a process.
Do not invent concurrency or persistence for a simple synchronous feature.

Each journey answers **“When is it called?”** and **“What happens when it's invoked?”**
Use one concrete, non-secret example and carry its values/IDs through every step.
Number sequence arrows so they can be matched to code later. Show successful
observation and at least one material rejection, partial failure, or cancellation.
Mark irrelevant paths as not applicable rather than adding speculative machinery.

Separate acceptance from completion, priority from preemption, and a cancellation
request from confirmed termination. Explain timeouts, stale requests, partial effects,
unsupported cancellation, cleanup failures, replay, and irreversible actions where
applicable. Do not promise atomicity, exactly-once effects, rollback, or bounded
termination without a mechanism and evidence.

### 6. Near the end: domains as code, interfaces as code, the journey through code

Use the repository's actual language and idioms. Complete implementation is not
needed, but concrete contract definitions and connected caller examples are required.
Do not substitute generic boxes, method-name lists, anonymous dictionaries, or
unrelated toy examples for the functionality's actual domains.

**Domains as code:** show the earlier domain concepts as named types: IDs, value
objects, entities/state, requests, results, errors, and events where applicable.
Show meaningful fields, optionality/defaults, units, constraints, and lifecycle states.
Explain which type owns data versus which module owns behavior. Do not invent
separate types when their meaning and contract are identical.

**Interfaces as code:** show actual interface signatures and relevant excerpts from
verified source. For additions, give concrete proposed signatures instead. Label
every block **Existing source**, **Proposed interface**, or **Illustrative flow**;
never present an invented API as already implemented. Cite source path/symbol/revision
for existing code and proposed placement for new code. Include construction and
lifecycle methods only where needed to understand ownership.

**The journey through code:** connect the types and interfaces with short, ordered
snippets, one step per block:

1. Composition/bootstrap creates the required owners and dependencies.
2. The real entry point constructs the request using the example values.
3. The caller invokes the public interface; the owning module validates and decides.
4. Domain operations change state and delegate to actual adapters as necessary.
5. The result/event returns to the caller and becomes the user-visible outcome.
6. A material failure or cancellation follows its cleanup and reporting path.

Accompany those snippets with a sequence diagram using the **same symbols, types,
example IDs, and numbered steps**. A small trace table should link each step to its
method, input, state/effect, output, and source location. A programmer should be able
to point at an arrow and find the corresponding call and result handling.

Keep code small but internally consistent: callers match declared signatures,
returned types match their handlers, and mentioned collaborators are defined or
linked. Use explicit `...`/stubs only for hidden implementation; never omit a
load-bearing decision or error path behind “do work.” Show asynchronous waits,
transaction boundaries, cancellation propagation, and cleanup where they matter.
Do not fabricate production implementation to fill gaps. Report unresolved contracts.

Use escaped, language-tagged code blocks and **statically baked syntax highlighting**
per the presentation skill so code is readable with JavaScript disabled. Validate
syntax/types of self-contained examples where practical; label excerpts/pseudocode
and report omitted collaborators rather than implying they compile or were executed.

### 7. Render a self-contained, accessible page

Follow the single-page presentation skill and read its design-language assets.
Inline the stylesheet and use its tokens; do not invent a parallel theme. Use
semantic headings, anchored navigation, readable measures, and restrained callouts.
No slide panels or forced scroll snapping.

Essential prose, diagrams, code, and navigation must work offline with JavaScript
disabled. Do not depend on remote scripts, fonts, or images. Provide SVG titles and
descriptions, textual diagram explanations, visible keyboard focus, sufficient
contrast, reduced-motion support, responsive layouts, and print styling. Contain wide
tables/code/diagrams in their own scroll areas rather than overflowing the page.

Use native `details`/`summary` only for supplementary depth. Never hide assumptions,
critical guarantees, failure semantics, or unresolved decisions. When expanding a
page, retain useful anchors and sources, remove contradictions, and update diagrams
and code together.

### 8. Verify and report

Before delivery, check:

- All three mandatory design prerequisites were read and applied before HTML design.
- Every section has one primary concept; terms appear before use.
- The full user journey includes the return path and observable outcome.
- Domains, interfaces, owners, diagrams, and final code examples agree.
- Actual versus proposed code is labeled, and every important arrow maps to a call.
- Code examples define their contracts without pretending to be full implementations.
- Invariants and decision paths map to proposed or existing tests: public-interface
  behavior, orchestration, real adapters, failures, cleanup, and end-to-end outcomes.
- Local links/anchors resolve; HTML/SVG structure is valid; no external rendering
  dependencies; highlighting remains visible without JavaScript.
- Desktop/narrow-screen rendering, diagram legibility, keyboard access and print
  output were checked where tooling permits. State any unperformed checks explicitly.

Keep document validation separate from application tests and design review. Read
source tests are not executed tests; rendered HTML is not implementation proof.
Report exact saved path, what changed, checks performed, limitations, and open
questions. Never imply approval, independent review, runtime correctness, or feature
completion merely because an explanation was saved.
