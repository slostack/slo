---
name: explain-how-it-works
description: Canonical guided-lesson style for explaining a feature, commit, subsystem,
  or skill — layered structure (how-to-read, one-minute overview, shared language,
  workflow guided tour), gradual context expansion, one-analogy-per-component, and
  mandatory diagrams for the system shape, sequences, and decision gates.
when_to_use: Use when the user asks you to explain, walk through, or teach how a
  feature, commit, or subsystem works — after the facts are known (pair with
  find-how-it-works for the investigation itself).
group: design-and-analysis
kind: skill
source_prompt: analyze/explain-how-it-works.md
---

# Explain How Something Works

## Skill summary

- **Name:** `explain-how-it-works`
- **Description:** Canonical guided-lesson style for explaining a feature, commit, subsystem, or skill — layered structure (how-to-read, one-minute overview, shared language, workflow guided tour), gradual context expansion, one-analogy-per-component, and mandatory diagrams for the system shape, sequences, and decision gates.
- **When to use:** Use when the user asks you to explain, walk through, or teach how a feature, commit, or subsystem works — after the facts are known (pair with find-how-it-works for the investigation itself).
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Source prompt:** `analyze/explain-how-it-works.md`

## Examples

- The user asks: "Walk me through the changes introduced in the last commit — explain it like I'm new to this domain."
- The user asks: "Now go deeper and walk me through the code control flow step by step, but keep the same guided tone."
- You finished tracing a feature with find-how-it-works and must present it to a mixed technical/non-technical audience.

## Guidance

Canonical style for **explaining** a feature, commit, subsystem, or skill to a reader as a
guided lesson. `find-how-it-works` is the investigation half — it tells you how to
*discover* the control flow. This skill is the presentation half: once the facts are known,
this is the exact shape the explanation must take.

The audience contract: write for the non-specialist first, with the precision layered in later.
The reader should be able to stop at the end of any section and still walk away with a correct
(if shallower) mental model. Never require a later section to make an earlier one true.

---

### 1. Pick the depth mode

| Mode | What it explains | Cites code? |
|---|---|---|
| **Conceptual walkthrough** | The domain and its workflows: what exists, when each workflow fires, what happens when it does. | Names components; no line numbers required. |
| **Control-flow walkthrough** | The literal call chain: entry point → function → function, with data handoffs. | Every claim cited as `file.go:123`. |

When asked to "go deeper" after a conceptual walkthrough, produce the control-flow walkthrough
**reusing the same vocabulary and workflow boundaries** — the deep version is the shallow version
with the hood open, not a new document.

### 2. The document skeleton

Produce the sections below in order. Headings may be renamed to fit the subject; the *roles* may not
be dropped or reordered.

1. **How to read this document.** One short paragraph: what this document is, what it is not,
   how it is layered, and the stop-early promise ("if you stop early you'll still leave with the
   right mental model").
2. **A one-minute overview.** Plain-language introduction of the domain: what the system is for,
   what hurts today (or what was wrong before the change), and what the subject does about it.
   End the section with a blockquote labeled **"The one-sentence version."** that compresses the
   entire subject into a single sentence.
3. **The shared language.** A short glossary — 5 to 8 terms maximum — containing *only* the words
   the rest of the document relies on. One line per term. Every later section must use these
   words and no synonyms (see `ubiquitous-language`).
4. **Guided tour — the workflows.** One subsection per workflow. Each subsection answers exactly
   two questions, in this order, using these literal phrases as anchors:
   - **"When is it called?"** — the trigger: who or what initiates it, and how often.
   - **"What happens when it's invoked?"** — numbered steps following control in execution
     order. In control-flow mode every step names the function and cites `file:line`.
   Order the workflows so each one only depends on machinery introduced by an earlier one
   (typically: startup/wiring first, then the steady-state loop, then the operator commands).
5. **Supporting changes / edge notes.** The riders: removals, renames, test coverage,
   deliberate limitations (fail-open paths, things intentionally not handled). Keep it to one
   paragraph unless a rider is load-bearing.
6. **The takeaway in one line.** A closing bolded sentence that restates the whole subject —
   the reader's souvenir. It should echo, not repeat, the one-sentence version from section 2.

For a control-flow walkthrough, insert between sections 3 and 4:

- **The boot ceremony.** Walk the process startup in order, introducing each long-lived object
  *as it is constructed* and stating which later scenario needs it ("remember this stamp —
  scenario 1 reads it"). By the end the reader knows who holds what.
- **The connection/request lifecycle** (when relevant): the shared plumbing every scenario
  travels through, explained once so the scenarios don't repeat it.

### 3. Style rules (all mandatory)

- **Gradual context expansion.** A section may only use concepts introduced in earlier sections.
  No forward references. If a step needs a concept you haven't introduced, the concept is in the
  wrong section — move it earlier, don't footnote it.
- **Plain language first, precision later.** The overview and glossary carry zero jargon that the
  glossary itself doesn't define. Line numbers, type names, and interface seams belong in the
  guided tour and beyond.
- **One analogy per component, used consistently.** Analogies are allowed and encouraged
  (the event log is "the diary", the replicator is "the postal service", the sync timer is
  "the metronome") — but each component gets exactly one analogy, introduced once, then reused
  verbatim every time. Never stack a second metaphor on the same component.
- **Contrast callouts.** When two checks, paths, or designs look similar but differ, say the
  difference explicitly in one sentence: "this check asks *may you reconfigure*; the gate asks
  *may this file travel*." Inversions and role/authorization distinctions always get one.
- **Plant callbacks.** When an early section wires something a later scenario depends on, flag it
  at the wiring site ("hold onto this picture"), and when the payoff arrives, point back
  ("the stamp from Part 2 — this is where it was written").
- **Complete sentences, no fragments.** No arrow-chain shorthand (`A → B → fails`) in prose.
  Arrows are allowed only inside diagrams and inline call-path parentheticals.
- **Cite, don't gesture** (control-flow mode). Every mechanism claim carries `file:line`. If you
  can't cite it, you haven't verified it — go back to `find-how-it-works`.
- **Report boundaries honestly.** State what the subject does *not* do (what isn't purged,
  what fails open, what is deferred) in the same calm register as what it does.

### 4. Diagrams

Every explanation includes diagrams; they carry the spatial intuition prose can't. Rules:

- **Vocabulary lock.** Diagram labels use the shared-language terms exactly — a box says
  `Replicator`, never "sync engine".
- **One diagram per role.** At most one diagram per placement below; a diagram that needs a
  paragraph to explain has failed and should be split or cut.
- **Size cap.** Keep each diagram under ~20 lines. Elide with `...` rather than cramming.
- **Format.** ASCII inside fenced blocks by default (renders everywhere, including terminals).
  Use Mermaid (`sequenceDiagram`, `flowchart`) only when the output target is known to render it.

Standard placements:

1. **After the one-minute overview — the system shape.** Boxes-and-arrows of the components the
   glossary is about to name:

   ```
   ┌──────────┐  RPC   ┌────────────────── atlasd ──────────────────┐
   │ atlasctl │ ─────► │ RPC server → Authorship → EventLog (diary) │
   └──────────┘        │                     │                      │
                       │   TeamRegistry ◄─ Replicator (post office) │
                       └─────────────────────┼──────────────────────┘
                                             ▼ sync (every 10s)
                                          peer nodes
   ```

2. **Inside each workflow — the sequence.** A vertical trigger-to-outcome trace, one hop per
   line, matching the numbered steps beside it:

   ```
   tick ─► SendSyncRequest(cursor)
                 │  FrameTypeSyncRequest
                 ▼
           peer readLoop ─► Dispatch ─► handleSyncRequest
                                            │ eventsSince(cursor)
                                            ▼
                                       filterByFlow ──► SyncBatch back
   ```

3. **At each gate or branch — the decision tree.** Conditions in evaluation order, one outcome
   per leaf:

   ```
   filterByFlow(peerID, e)
   ├─ peerID zero / no members?  → pass everything (fail-open, relay)
   ├─ governance event?          → pass (always)
   └─ file event                 → MaySendFileTo(peer)?
                                     ├─ no shared team        → block
                                     ├─ any shared team fails → block
                                     └─ all shared teams pass → send
   ```

### 5. Self-check before delivering

- Could a reader stop after section 2 and hold a correct one-sentence model? After section 4 and
  hold a correct workflow model?
- Does any section use a term the glossary or an earlier section didn't introduce?
- Does every workflow answer both anchor questions, in order?
- Does each component have exactly one analogy, and is it used consistently?
- (Control-flow mode) Does every mechanism claim carry a `file:line`?
- Is there a one-sentence-version blockquote near the top and a one-line takeaway at the bottom,
  and do they agree?
- Does every diagram use glossary vocabulary and stay under the size cap?
