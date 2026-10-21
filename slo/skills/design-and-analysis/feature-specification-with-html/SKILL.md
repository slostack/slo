---
name: feature-specification-with-html
description: Author feature specifications as self-contained HTML documents in the Slo theme, with the same completeness as the Markdown format — runnable cores, shared vocabulary, explicit ownership, interface-level control flow, file contracts and behavior-level acceptance tests.
when_to_use: Use when the user wants the feature specification itself delivered as HTML — a product overview and standalone engineering sub-specifications as runnable cores. Use feature-specifications for Markdown.
group: design-and-analysis
kind: skill
---

# Feature Specifications in HTML — runnable-core authoring format

## Skill summary

- **Name:** `feature-specification-with-html`
- **Description:** Author feature specifications as self-contained HTML documents in the Slo theme, with the same completeness as the Markdown format — runnable cores, shared vocabulary, explicit ownership, interface-level control flow, file contracts and behavior-level acceptance tests.
- **When to use:** Use when the user wants the feature specification itself delivered as HTML — a product overview and standalone engineering sub-specifications as runnable cores. Use feature-specifications for Markdown.
- **Group:** `design-and-analysis`
- **Kind:** `skill`

## Examples

- "Write the spec for this feature in HTML."
- "Split this multi-stage spec into small runnable cores, each as its own HTML sub-spec with behavior tests."
- "Revise sub-spec 96.a.1 in the HTML spec after this review."

## Guidance

- **The HTML is the spec,** not a summary. Same content, same quality bar; only the format changes (§9).
- **One authority:** no parallel Markdown copy. `request.md` and `evidence/` stay as plain text.
- This skill covers authoring only. Verification, task breakdown and implementation are separate workflow steps (see §13).
- Behavior tests follow `skills/coding/test-verification-policy/SKILL.md`.

## 1. Outcome

A specification has two readers:

| Reader | Needs |
|---|---|
| Human | Understand the change in minutes: terms, problem, before → after, flow, what is done at the end. |
| AI implementer | Build it without guessing: exact files, symbols, types, defaults, errors, ordering, tests. |

Serve both by putting the narrative first and the exact contracts second. Never trade a contract for brevity. Remove repetition, not meaning.

A reader must be able to answer, in order:

1. What do these domain terms mean?
2. What user problem does this slice solve?
3. What exists now, and what will change?
4. Which entities own the work, and which interfaces carry control and data?
5. When does each operation happen?
6. What exactly must an implementer add, change or remove?
7. What works when this slice finishes, without any later slice?
8. Which behavior tests prove it?

## 2. Runnable cores, not multi-stage monsters

Every sub-spec delivers a **complete runnable core**: a real entry point, the core behavior and an observable end state, working on its own once it ships.

- **Start with the smallest useful core.** The first slice is the thinnest end-to-end journey a user or real client can run. Later slices extend it, and each one is runnable when it finishes.
- **No hidden gaps.** If a slice removes old behavior, it ships the full replacement. If that is impossible, move the removal later. Never cover a gap with a no-op adapter or a receipt that falsely reports success.
- **No future debt.** Each slice says plainly: *no later slice is required to finish the work this slice accepts.*
- **Prefer fewer, complete slices.** Split a slice only when one of these holds:
  - it has two independently shippable outcomes;
  - it introduces more than one new domain;
  - it mixes unrelated backend, frontend and deployment work;
  - its journey runs past about 10 steps, or it has more than about 15 acceptance criteria.
  Each part of a split must still be a runnable core.
- **Keep the dependency graph acyclic.** Each slice lists the completed slices it builds on.

## 3. Gather context before writing

Read in this order. Repository instructions take precedence over the generic order.

1. The request, every user clarification and any referenced ticket or issue. Keep `request.md` unchanged.
2. Global and repository `SLO.md`, `CLAUDE.md` and `AGENTS.md`, plus `RESEARCH.md` and `MEMORY.md` when present.
3. Overarching guidance: `coding/coding-rules`, `coding/code-design-principles`, `coding/solution-design`. Then the affected language root and matching component conventions. Python always adds named-arguments-and-type-hints, method-docstrings and declarative-method-structure.
4. The knowledge base. Find it via `locate-knowledge-base`. Read the folders that overlap the feature, including their "I saw this error, what now?" tables. A missing knowledge base is reported, not a blocker.
5. The code itself. Read callers, interfaces, lifecycle owners and adjacent tests. Confirm responsibilities by reading code, not by trusting names.

Resolve skills from the active catalog, including user overrides. Use `SLO_SKILLS_DIR` when set; an invalid explicit path is reported, never silently replaced. Never hard-code a home directory or install path.

### Context bundle

Produce this before the first heading of the spec. Keep it short. Store it under `evidence/`.

```markdown
### Context Bundle — <feature or ticket>

**Source ask:** <1–2 sentences>
**Family:** overview.html + <every sub-spec path>; prerequisites per slice
**Current truths:** <file:line — symbol or runtime behavior that is true today>
**Stale design text to correct:** <path or snippet — what is wrong now>
**Existing owners (consolidation):** <capability — owner file:line — verdict — form>
**Conventions in force:** <skill path — one-line takeaway>
**Quality attributes:** <only the ones that apply: scale, latency, concurrency/idempotency,
  error model, security/auth, logging/observability, data lifecycle, deployment, cross-repo>
**Knowledge-base lessons:** <entry — failure mode to pre-empt>
**Open questions:** <question — which decision it blocks>
**Verification commands:** <real project test/lint commands>
```

**Pause on blocking questions.** If an open question would change scope, ownership, a contract or safety, ask the operator before drafting. Otherwise record the question in the spec's Open issues section and continue.

Do not implement code, run tests, create tickets or publish anything just because the spec describes those activities.

## 4. Artifact family and authority

```text
<number>-<feature>/
  request.md                          # unchanged user intent
  overview.html                         # product journey and delivery map
  <number>.<letter>.<index>-name.html   # one complete runnable core each
  evidence/                             # context bundle, self-checks, reviews (Markdown)
```

- **Paths:** explicit user instruction → repository override (for example the repo-local `specifications/`) → configured defaults. Never name a spec `request.md`.
- **Family:** every feature has `overview.html` plus at least one separate sub-spec, even when the feature is small. When revising one slice, re-check the whole family: dependencies, acceptance mapping and summaries.
- **One owner per contract:** define each interface, record, invariant and configuration rule once, in its owning slice. Other slices link to it and show only their import and call.
- **HTML is normative.** Each HTML file is the authoritative spec for its slice. Do not keep a Markdown copy that could drift.
- **Linked family:** the overview links to every sub-spec, and each sub-spec links back to the overview and its prerequisites.
- **Honest status:** never fabricate review, test or acceptance evidence. An old hash or READY verdict does not validate revised content.
- **Revision hygiene:** fix the owning section in place and delete superseded wording. Review findings, workflow counters, tool logs and approval history go in `evidence/`, not in the spec body.

## 5. Engineering sub-spec layout

Use these sections in this order, each as its own anchored HTML section (§9). The `markdown` blocks below show content, not file format. A section may be short. Leaving out a safety, lifecycle or failure contract is never acceptable.

### 0. Header

- Slice ID and an outcome-oriented title.
- Status (`draft`, `REVISE`, `author-ready`, `independently verified`), owner, last-updated date (`YYYY-MM-DD`), repository and branch.
- Parent overview, source request and completed prerequisite slices.
- **Runnable outcome:** one sentence saying what works when this slice ships.

### 1. Glossary and ownership

Put the glossary before the walkthrough. It has two parts:

1. **Refresher** — the existing domains and terms the slice builds on, so a reader returning to the codebase can follow the walkthrough without opening other documents. Keep each entry to one or two lines and link to the owning file or spec.
2. **New and changed terms** — the terms this slice introduces or extends, plus any existing term a newcomer would misread.

Include only terms the walkthrough actually uses. For each term give:

- Its plain meaning, with the code identifier beside it.
- Whether it is existing (refresher), extended or new.
- What it owns and what it explicitly does not own.
- What kind of thing it is (process, task, thread, interface or data record) where that is easy to confuse.

Use one name per concept across the spec, code, CLI and UI. Do not give one entity several synonyms.

### 2. Purpose and current → proposed behavior

- The user's problem and the smallest complete improvement.
- A side-by-side table of current versus proposed behavior.
- What is added, changed, removed and deliberately unchanged.
- Label each statement as an inspected fact (cite `path:symbol`) or a proposed contract.
- Non-goals. Do not absorb the adjacent roadmap.
- **Bug fixes:** state the symptom, the expected behavior and the actual divergence, with source references.

### 3. Runnable-core boundary

- The starting baseline and the completed prerequisites.
- The end-to-end outcome a real user or client can run when the slice completes.
- Existing journeys that must keep working.
- Capabilities not yet enabled, and exactly how they are refused.
- Temporary compatibility adapters: owner, single execution path and the slice that removes them.
- Schema or configuration migration from the previous slice. Never retroactively change a released schema.
- Activation order, shutdown behavior and recovery behavior.
- The statement *"No later slice is required to finish work this slice accepts."*

### 4. Interactions and control flow

Provide:

1. **An ownership map:** components, what each owns and the interfaces between them.
2. **A trigger-to-end-state sequence** using real existing or proposed interfaces.

Every arrow names the caller, the callee, the method or event, and the important typed value. It also says whether it is a call, return, signal, persisted transition or observation, and where it falls relative to acceptance, side effects and acknowledgement.

Trace the normal, empty, rejected, uncertain, cancelled and recovery paths that apply. Show lock and task ownership, commit and rollback boundaries, and where control returns. End at an observable state, not at "calls the service".

Use an inline SVG or ASCII diagram (§9). Add a plain-text trace table only when it carries something the diagram does not, such as failure exits. Do not draw the same flow twice.

### 5. Ordered changes

Start with an annotated target file tree marking each file as added, changed, moved or removed. Then give one record per change:

```markdown
### Change N: <specific outcome>

**Code delta** — exact repository-relative files, symbols and call sites added,
changed, moved, removed or rewired.

**What and why** — the observable behavior, its owner and why it is needed.
Say why, not what the signature already says.

**When it runs** — runtime trigger, caller, timing, repetition and shutdown.
Keep this separate from build order ("after Change 2").

**Interface** — a short convention-compliant declaration, or a link to its
contract in Section 8. Include inputs, outputs, errors and side effects.

**State after this change** — what still runs, whether the new path is inactive
until cutover, and what must land before callers switch.

**Proven by** — acceptance-criterion IDs.
```

Intermediate changes may be inactive. The whole slice may not be. If intermediate commits must stay runnable, keep the old path active until the replacement is complete.

### 6. Acceptance criteria and behavior tests

Acceptance criteria describe **behavior a user or client can observe**. Each one names the test that proves it.

| ID | Given / When | Then (observable result + forbidden side effect) | Test | Source |
|---|---|---|---|---|
| `96.a.1-AC01` | … | … | `tests/<path>/test_<file>.py::test_<behavior>` | `request.md` item or derived safety rule |

Cover what applies:

- The full real journey, and existing behavior that must not change.
- Ordering, duplicates, retries and concurrency.
- Errors, uncertain outcomes, capacity limits and authorization.
- Startup, shutdown, cancellation, crash recovery and durable transitions.
- Future capabilities refused before partial activation.
- Schema and configuration upgrades across slices.
- Visible UI or CLI behavior and accessibility.

**Test policy for the specified tests:**

- **Behavior, not structure.** Name each test after the behavior (`test_urgent_message_is_delivered_at_next_safe_boundary`). Drive it through the slice's real entry point and assert observable outcomes and forbidden effects. No BDD framework is required; use standard `pytest`, with plain Given/When/Then comments if they help.
- **Real database.** Use the project's disposable test database, with migrations applied. Never mock the database, the ORM session or repositories. Persistence, constraints, transactions and rollback are proven only against the real store.
- **Mock only third-party APIs.** External vendor or network services (LLM providers, payment, SMS) are mocked at their client boundary.
- **Stubs for internal collaborators.** Replace internal collaborators such as clocks, schedulers, transports and sibling services with small stub objects passed in through constructor or function parameters (dependency injection). Do not patch module internals.
- For each test, name the file and function, its fixture or stub setup, and the key assertions.

"Add tests", "works correctly" or "the file exists" is not acceptance. Define the count, state, response, persisted record or visible outcome. An acceptance table is a plan, not a claim that tests passed.

**Out of scope for the spec:** one test per decision branch, coverage thresholds, test folder layout and full-suite gates. `code-test-review` Step 1 enforces these through `test-verification-policy`, and Step 2 reviews them.

### 7. Verification and rollout

- The real project commands that run the specified tests, plus lint and format.
- Manual smoke steps for interactive or runtime-heavy behavior.
- Upgrade or cutover steps, rollback limits and when compatibility code is removed.
- What was checked during authoring versus what implementation must run. If the user forbids running tests during authoring, prescribe them without running them.

### 8. File contracts

Group by production file, using exact repository-relative paths as headings. This section is the single source for interfaces; Section 5 links here and must not compete with it. For each file:

1. One or two sentences on its responsibility and the change.
2. Syntax-highlighted declarations in the target language:
   - one field per line, with explicit types, requiredness, nullability, defaults and bounds;
   - complete public signatures, return types and exact enum and constant values;
   - imports that show ownership;
   - no `...` standing in for fields, parameters, members or defaults.
3. Only the behavior the declarations cannot express: validation, invariants, ordering, atomicity, idempotency, errors, cancellation, and transaction or resource ownership. Write these next to the interface they govern.

Further rules:

- Omit method bodies in labeled interface listings. Include bodies only for non-obvious algorithms, integration seams or ordering constraints.
- Do not encode classes as prose or table cells, and do not repeat a declaration as a second field list.
- Include deletions, consolidation work, every caller to repoint, and configuration or environment keys.
- Label proposed code with its target file. Never imply proposed code already exists.
- Mark legacy excerpts that have not been convention-checked as review debt.
- Use the packaged granularity sample as the depth reference.
- An unresolved material decision blocks readiness. Do not invent a missing contract to fill a gap.

### 9. Open issues and readiness

- Each unresolved question with the criteria it affects, its owner and whether it blocks implementation.
- Keep author self-check, independent review and runtime acceptance separate. Never call a spec complete because its headings exist.

## 6. Consolidation: one owner per responsibility

Before proposing any new domain, model, DAO, service, router, worker, event, agent, tool, client, CLI command, config key or UI store, search the code **by behavior, not by name**. Duplicates are usually named differently.

| Verdict | Meaning | Required action |
|---|---|---|
| New | No existing owner. | Record "no existing owner found for X". |
| Duplicate | Existing code does this wholly. | Reuse it, or delete and replace it. |
| Partial overlap | Existing code does part of it, or owns the responsibility. | Encapsulate into the owner, or redesign the owner. |
| Adjacent | A neighbor owns a related responsibility. | Draw the boundary and name the interface across it. |

The three consolidation forms are:

- **Delete and replace:** name the files and symbols to delete, the call sites to repoint and any data migration.
- **Encapsulate:** fold the new behavior into the existing owner within its conventions.
- **Redesign:** reshape the owner so it absorbs the new behavior.

State every boundary in prose and in the docstrings of the code samples. A second owner for an existing responsibility makes the spec REVISE.

## 7. Overview adaptation

Use the same reading order at feature level:

1. Shared glossary: a refresher on the existing domains plus the feature's new terms.
2. Product purpose and before/after journeys.
3. The whole-feature runnable outcome and what must not change.
4. Architecture and control-flow map.
5. A dependency-ordered delivery map: each slice, its runnable outcome and its prerequisites.
6. Feature acceptance criteria mapped to slices.
7. Rollout, verification and unresolved decisions.
8. A brief technical overview linking to each engineering owner.

Keep DTOs, signatures and algorithms in their owning sub-specs. Reconcile parent summaries with current child scope. Do not present spec approval as implementation or runtime acceptance.

## 8. Writing and code rules

**Prose**

- Short paragraphs with one idea each, concrete verbs and descriptive headings.
- Use inline code for symbols, paths and literals.
- No `§`, no unexplained abbreviations, no "as above". Link to the exact heading or file instead.
- No word limit. Remove repetition before removing detail.
- Pick the format by content:

| Content | Format |
|---|---|
| Interfaces, schemas, constants, configuration | Code |
| Comparisons, state transitions, acceptance | Tables |
| Dependencies, ownership, flow, transaction boundaries | Diagrams |
| Intent, rationale, exceptions | Prose |

**Code samples**

- Follow the resolved language and component rules, not conventions inferred from an old draft.
- Python: keyword arguments, explicit type hints, Google-style docstrings (Args/Returns/Raises). Go: context-first calls, named-field structs, godoc. TypeScript: options objects, JSDoc.
- Write declarative orchestration. Domain and storage rules live in their owners, not in UI code, controllers or chains of trivial wrappers.
- Use `invoke()` only for a newly introduced Python application workflow service. Do not rename existing lifecycle interfaces to fit it.
- Use realistic identifiers. Label excerpts and omitted bodies. Never invent helper names to shorten a sample.
- Introduce each block with one sentence on its purpose.
- **Consistency:** snake_case for Python fields and files, PascalCase for classes, kebab-case for URL segments and slugs; concrete ID types; stable terminology.

## 9. HTML document rules

The HTML is the spec. These rules cover rendering only; every content rule above still applies.

- **Theme:** use the Slo design language from `skills/presentation/present-as-single-page/SKILL.md` (first used by the Feature 93 spec template and Feature 96's `html-spec/`):
  - Tokyo Night is the default (`--slo-bg #1a1b26`, `--slo-accent #7aa2f7`).
  - Near-black with phosphor-green accents (`--slo-accent #00ff7f`) is the alternate, applied with `data-theme="dark"` on `<html>`.
  - Use the `--slo-*` tokens with a hero, sticky section navigation and numbered walkthroughs.
  - Include a visible theme toggle.
  - Use a different template only if the user supplies one.
- One self-contained `.html` file per document. Each §5 section gets its own anchor, and each change and acceptance criterion is linkable.
- Keep the glossary before the walkthrough and show acceptance criteria as a visible section. Collapsible sections may hold long detail, but never the only copy of a contract.
- Put code and contracts in full in `<pre><code>` blocks, and tables as real tables.
- Mark current, proposed and unresolved items with text labels as well as colour.
- Render real diagrams offline. A Mermaid source block alone is not a diagram.
- Any TUI change needs before/after wireframes showing focus, input, transcript and unaffected areas.
- Embed all styles and scripts with no remote assets. Support section links, narrow screens, keyboard focus and print.

## 10. Author self-check

Run this after every draft or revision, before handoff. It is a short author pass, not the independent audit. The full traceability matrix and layer-by-layer audit belong to `feature-specification-verification`.

| Check | Question | Gap type |
|---|---|---|
| Structure | Does the family exist, with each document in the right role and each slice a runnable core? | STRUCTURE |
| Requirements | Does every request item map to an acceptance criterion or an explicit exclusion? | STRUCTURE |
| Readability | Can a reader find the purpose, flow, changes, failures and acceptance quickly? | NARRATIVE |
| Meaning preserved | After shortening, are types, nullability, defaults, bounds, invariants, ordering, atomicity, idempotency, errors, security, migrations and unchanged behavior all still present? | CONTRACT |
| Failure paths | Are database failure, external errors, malformed input, missing entities, timeout and concurrency defined where they apply? | CONTRACT |
| Conventions | Do the code samples follow the resolved language and component skills? | CONVENTION |
| Consolidation | Was each new artefact re-searched, with no second owner left? | REDUNDANCY |
| Contracts | Is every interface complete and in an exact file, with no `...` and no unlabeled proposed code? | EXAMPLE |
| HTML | Is every §5 section present, visible and linkable, in the Slo theme? | STRUCTURE |
| Behavior tests | Does every criterion name a behavior test that follows the test policy (real DB, third-party mocks only, injected stubs)? | TEST |
| Caller burden | Is the interface simple for its callers? (Advisory; never forces REVISE on its own.) | — |

**Verdict:** any STRUCTURE, NARRATIVE, CONTRACT, REDUNDANCY, EXAMPLE or TEST gap means **REVISE**. Fix the owning section, then re-run the self-check until it is READY.

Store the report in `evidence/`:

```markdown
### Author Self-check — <slice> — <YYYY-MM-DD>
| Gap type | Count | Findings (section → required edit) |
|---|---|---|
Verdict: READY | REVISE
```

Author READY is not independent approval. Hand the family, the context bundle and the self-check to independent verification. Fold its findings back into the owning sections and re-run the self-check. Get explicit confirmation before committing, publishing or creating external tasks.

## 11. Author process

1. **Gather:** reading order, context bundle, blocking questions.
2. **Slice:** declare the family and acyclic prerequisites; prove each slice is a runnable core.
3. **Draft:** header → glossary → purpose → runnable boundary → flow → changes → acceptance and tests → verification → file contracts → open issues.
4. **Consolidate:** run the one-owner search and record the verdicts.
5. **Self-check and revise** until READY.
6. **Independent verification** of the complete family; revise, then re-check.
7. **Breakdown and implementation** happen in `breakdown-feature-spec-to-tasks` and `code-test-review`. Any material contract change repeats the affected authoring and review steps.

## 12. Acceptance criteria for this skill

| ID | Check | Passing condition |
|---|---|---|
| FORMAT-01 | Family shape | `request.md`, an overview and separate sub-specs exist. |
| FORMAT-02 | Vocabulary | The glossary refreshes the existing domains the slice builds on and defines its new terms. A newcomer can tell records, ports, services, tasks and processes apart before the journey starts. |
| FORMAT-03 | Runnable core | Every slice lists its prerequisites and finishes its accepted work with no later slice. No slice is scaffolding only. |
| FORMAT-04 | Control flow | Trigger-to-end-state diagrams name interfaces, owners, signals or returns, and failure branches. |
| FORMAT-05 | Changes | Every change has a code delta, what and why, when it runs, interface, state after and proof. |
| FORMAT-06 | Behavior tests | Every criterion has a stable ID, an observable Then and a named behavior test (pytest, `go test` or Vitest) using a real database, mocks only for third-party APIs and injected stubs. |
| FORMAT-07 | Contracts | File contracts are complete, with one owner each and no ellipses. Unresolved decisions block readiness. |
| FORMAT-08 | Consolidation | Every new artefact has a verdict. No duplicate owner remains. |
| FORMAT-09 | Readable and complete | Shortened text keeps every type, default, invariant, error and safety rule. |
| FORMAT-10 | UI evidence | Every visible TUI change has before/after wireframes, and unchanged behavior is stated. |
| FORMAT-11 | Single authority | Overview, sub-specs, schema versions and dependencies agree; no parallel Markdown copy exists; otherwise the family stays REVISE. |
| FORMAT-12 | HTML document | Every document is self-contained HTML in the Slo theme (Tokyo Night default, phosphor-green alternate) with every §5 section visible. |
| FORMAT-13 | Honest completion and scope | No author edit implies implementation, review or passing tests. No execution or publication happens without authorization. |

## 13. Relationship to other skills

- `feature-specifications` remains the default authoring skill and produces Markdown. Use this skill when the user wants the specification in HTML. Both skills hold specs to the same quality bar.
- Independent verification stays in `feature-specification-verification`.
- Task breakdown stays in `breakdown-feature-spec-to-tasks`.
- Implementation, per-branch coverage and test execution stay in `code-test-review`, with tests governed by `skills/coding/test-verification-policy/SKILL.md`.
- HTML explanations of existing (not proposed) behavior use `explain-with-html`.
