---
name: gather-feature-context
description: 'On-request extended context companion feeding feature-specifications mandatory Gather context stage; provides language-aware (Python, Go, TypeScript), framework-neutral tracing and an evidence-backed behavior map, not a default pre-hook.'
when_to_use: 'Use on-request for an extended sign-off briefing feeding the mandatory Gather context stage, not as a default pre-hook.'
group: design-and-analysis
kind: workflow
source_prompt: analyze/gather-feature-context.md
---

# Gather Feature Context

## Skill summary

- **Name:** `gather-feature-context`
- **Description:** On-request extended context companion feeding the mandatory Gather context stage with business, architecture, code and source evidence; not a default pre-hook.
- **When to use:** On-request when an extended sign-off briefing is needed before drafting.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `analyze/gather-feature-context.md`

## Examples

- “Gather an extended business and technical context briefing for this feature before drafting.”
- “Prepare a source-backed briefing for my sign-off, then feed the mandatory Gather context stage.”
- This companion runs on-request; ordinary specification authoring starts directly with the canonical author's mandatory Gather context stage.

## Request and specification artifact paths

Use the canonical [artifact paths and compatibility vocabulary](../feature-specifications/SKILL.md#artifact-paths-and-skill-discovery), including project-local precedence and its request/specification folder examples. This companion defines no competing environment or home defaults.

## Guidance

> **Companion role:** On-request extended context briefing for [`feature-specifications`](../feature-specifications/SKILL.md). Its output feeds the canonical Gather context stage; it is not a second default pre-hook.
>
> **Opt-out:** The user can skip this extended briefing (e.g., "skip the pre-hook", "don't gather context", "I already have the context"). Continue with the canonical authoring skill, reusing supplied context; skipping this companion does not silently waive its mandatory context bundle.
>
> **Context check:** Before doing anything else, decide whether the existing conversation already supplies the business + application + implementation context. If it does, summarise what you have and ask the user whether to skip the gather. If it does not, ask the user for what is missing (ticket ID, Confluence URL, subject area, owning service) before running the heavy steps. **Never invent context.**

---

## Purpose

Gather the complete context — business rationale, current application/technical state, and implementation details — that a feature specification needs in order to be useful. Feed that context back to the user for sign-off **before** generating the spec.

A feature specification without business context becomes a checklist. A feature specification without current-state context becomes wishful thinking. This on-request companion prevents both and feeds the mandatory Gather context stage; it does not replace that stage.

The gather can also run in the background while the user is still brainstorming — the output is a "context briefing" the user reviews before we commit to writing the spec.

---

## Inputs

Required (ask if missing):

1. **Subject** — the feature name, theme, or short description (e.g., "partial-shipment split", "fulfillment-partner sync").
2. **Anchor** — at least one of:
   - JIRA ticket ID / URL
   - Confluence page ID / URL
   - PR or branch
   - A clear English statement of the problem

Optional:

3. **Scope hints** — repos to focus on, services known to be involved, related prior work.
4. **Out-of-scope** — areas explicitly excluded.

If only the subject is given and no anchor exists, explicitly ask the user whether they can link a JIRA ticket / Confluence page / RFC, and proceed without if they confirm none exists.

---

## Repositories in scope

The workspace file lists member repositories when one exists; otherwise follow
operator scope hints. Skip prompt/tooling libraries and every repository the
user marks out of scope. Include additional repositories only within that scope.

---

## Step 1 — Preserve git state

Before reading code, ensure we are looking at the **latest main** of each in-scope repo without disturbing the user's working tree.

For each repo, prefer one of these in order:

1. **Worktree from latest main** (preferred, non-disruptive):
   ```bash
   cd <repo>
   git fetch origin main
   git worktree add -B context-gather-<YYYYMMDD> ../.worktrees/<repo>-context origin/main
   ```
   Read code from the worktree path. Tear down with `git worktree remove` once context is gathered.

2. **Stash + checkout** (only if worktrees aren't viable):
   - Capture `git status` and `git rev-parse HEAD` first so the state is recoverable.
   - `git stash push -u -m "context-gather-<YYYYMMDD>"`, fetch + checkout `origin/main`.
   - **Restore** original branch and `git stash pop` at the end of the gather.

3. **Read-only via GitHub** (`gh` CLI or a connector) — use this for any repo where local clone is missing or stale, or when the user prefers not to touch local state.

Record per repo: original branch, original commit SHA, and the path you actually read from. Surface this in the final briefing so the user can verify nothing was disturbed.

---

## Step 2 — Business context

**Goal:** Answer two questions, in this order:

1. **Domain question:** "What does this concept mean in the industry?" — explain the term as someone outside the company would use it. E.g., for **partial shipment** in order fulfillment, explain that it refers to fulfilling an order across multiple deliveries when not all line items are in stock, why it affects invoicing and customer-visible status, and where the compliance/SLA rules around it bite. For **SOR (System of Record)** explain that it is the authoritative upstream system that owns the order data we sync against. For a **fulfillment partner**, explain that they are an external provider whose orders we service on their behalf.
2. **Product question:** "What problem does this solve for our business, and for whom?" — the in-house framing layered on top of the industry framing.

Lead the briefing with the domain explanation. Engineers and reviewers rarely share the operator/partner vocabulary, and skipping this step is the single most common cause of off-target specs.

### Sources — tiered and explicit

Consult in this order, retaining evidence and status for each source:

| Source | What it contributes | If absent |
|---|---|---|
| Knowledge base | Terminology, architecture, decisions, conventions, historical findings, limitations | Record "no KB found"; discovery is non-blocking |
| Jira / Confluence | Requirements, acceptance criteria, business context, discussions, linked design material | Record unavailable; ask the user; proceed on confirmation |
| Code | Actual wiring, execution paths, behavior, integrations, persistence, configuration | Record unavailable and surface the verification gap |
| Documentation / READMEs | Structure, setup, API descriptions, architecture, operations, testing instructions | Record empty or unavailable |
| Tests | Behavioral contracts, edge cases, fixtures, integration boundaries | Record empty if inspected without findings |

Use `skills/design-and-analysis/locate-knowledge-base/SKILL.md` for non-blocking
KB discovery. Read its entry point and relevant repository index and gotchas.
A source consulted with findings is **consulted-with-findings**; inspected without
relevant findings is **empty**; no connector, access, or source is **unavailable**.
When connectors are absent, record unavailable rather than skipping silently.
Report material contradictions between code, documentation, and tickets; never
silently resolve them by assumption. Ask which intended contract should govern.
Search linked RFCs, PRDs, runbooks and discussions when connectors are available;
request links from the user otherwise. Consult project memory and, only when
internal sources are thin, authoritative external references with citations.

### Capture

For every source touched, retain enough that the next step ([canonical author](../feature-specifications/SKILL.md#gather-context)) can read it without re-querying:

- **Domain glossary** — every acronym or industry term that appears, with a one-line plain-English definition and the source it came from.
- **The overarching goal** — what outcome the feature unlocks. Not necessarily monetary; could be compliance, operator UX, scale, risk reduction.
- **Stakeholders** — who is asking for this and who is affected (business team, operators, customers, vendors, legal).
- **Constraints** — regulatory / compliance, partner contractual, SLA-driven, deadline-driven, infra-budget.
- **Prior art** — earlier RFCs, PRDs, or specs in the same area, deprecated approaches, decisions already made.
- **Raw links** — JIRA URLs, Confluence page IDs + URLs, Drive doc URLs, KB page paths, external URLs. Keep these so the next step and the user can drill down.

### Carry-forward and confirmation

- **Keep everything you gathered alive for Step 6.** Don't discard sources after summarising — the briefing surfaces summaries, but the full notes (or paths to them) must be available so [canonical author](../feature-specifications/SKILL.md#gather-context) can pull verbatim quotes for the spec.
- **Confirm the domain framing with the user before moving on.** A 30-second check ("Here's how I'm reading partial shipment — does this match your team's working definition?") catches misunderstandings before they propagate into the spec. If the user corrects you, update the glossary and re-confirm.
- **Confirm the business goal with the user.** Phrase it back in one sentence and ask for thumbs up. This avoids spending the rest of the gather pointed at the wrong problem.

If no business context is found anywhere, explicitly tell the user. Do not fabricate.

---

## Step 3 — RFC discovery

When connectors are available, follow tickets and linked design documents. JIRA tickets often reference an RFC (Confluence page) that contains the canonical design. Record unavailable connectors distinctly from an empty search.

- Walk the JIRA ticket's links and remote links (`getJiraIssueRemoteIssueLinks`) for any `confluence` URLs.
- Search Confluence by ticket ID and subject for `RFC`, `Spec`, `Design`.
- Pull any RFC found and include its current status (draft / approved / superseded).

If you cannot locate an RFC, **ask the user explicitly**:

> "I couldn't find an RFC for this feature in Confluence or linked from the ticket. Do you have one you can link? If none exists, I'll proceed without and note that the spec has no upstream RFC."

Do not silently proceed if the absence of an RFC is unusual for the area.

---

## Step 4 — Application & technical context (current state)

**Goal:** Describe the system *as it exists today* in the area the feature touches. The feature spec will build on this.

Read RESEARCH.md, AGENTS.md and applicable conventions first. Use
`skills/design-and-analysis/find-how-it-works/SKILL.md` for deeper tracing.
Record actual file/symbol references and handoffs, not a hypothetical stack.

### Python

This is a discovery guide, not a mandated architecture — follow the actual
repository and its conventions; do not invent layers. Support CLI, worker, and
event-driven entry points as well as web applications.
When present: bootstrap → route registration → middleware/dependencies →
handler/controller → application service → domain behavior → persistence/external
clients → response/error handling → tests.

### Go

This is a discovery guide, not a mandated architecture — follow the actual
repository and its conventions; do not invent layers. Support CLI, worker, and
event-driven entry points as well as web applications.
When present: entrypoint/wiring → router or command registration → middleware →
handler → application/domain services → repositories/clients → response/error
handling → tests. Trace context propagation and cancellation where relevant.

### TypeScript

This is a discovery guide, not a mandated architecture — follow the actual
repository and its conventions; do not invent layers. Support CLI, worker, and
event-driven entry points as well as web applications.
When present: workspace/package/bootstrap → route/controller or UI entry point →
middleware/providers → application services or state/data access → domain
behavior → persistence/external APIs → response/rendering/error handling → tests.
Distinguish frontend component/state/rendering paths from backend request paths;
trace their actual shared boundary rather than treating them as one process.

### Step 4a — Verify the schema against running code or live data (mandatory)

Every column name, table name, type, and nullability that the spec will mention **must** be verified against the actual code or live data — never inferred from a sibling spec, from a prior conversation, or from analogy to another table. Specs that name nonexistent columns or guess at types waste reviewer time and produce broken downstream code; this step is the gate that prevents it.

Read the repository's authoritative model/schema source — the ORM model,
migration directory, schema definition, or protobuf — and/or query live data
through the project's documented development-database path. Use the project's
documented local data path (KB-referenced where present), never assumed connection
strings. Quote actual names, types and nullability and name the verification source.
Mark new versus existing fields and structures. Verify existing state first;
before proposing a new structure, search for an existing responsibility owner.
Check constraints, indexes, relationships and actual enum/discriminator values.
If neither source nor permitted data is available, **stop and surface the gap to
the user before drafting the spec**. Drafting against assumed schema is worse
than drafting nothing. Verify, never paraphrase.

### Capture (the context-briefing inputs)

- **Current control flow** as a short numbered list (1. Request hits `router.py:foo` → 2. calls `XAppService.invoke()` → 3. ...).
- **Verified schema** — the actual table / column inventory from Step 4a, quoted (not paraphrased). Mark new columns/tables vs existing.
- **Gaps in the current system** — what's missing today that the feature must add.
- **Touchpoints** — exact file paths the spec will need to modify or create alongside.

---

## Step 5 — Implementation details (precedents)

**Goal:** Pull the precedents that the spec should follow so it doesn't reinvent patterns.

- Find the **closest analogous feature** already implemented and capture its actual language, framework, file layout and responsibility boundaries.
- Find the **existing owners** of every capability the feature implies. The system may already do this work wholly, do part of it, or own the responsibility the feature is about to duplicate — and the existing component is usually named differently, which is why it gets missed. For each hit, record the symbol and `file:line`, whether the overlap is whole, partial, or adjacent, and whether the spec should consolidate by deleting and replacing it, encapsulating the new behavior in it, or re-designing it to absorb the new functionality. Redundant artefacts, entities, and domains are a design defect; the briefing must give the spec writer what it needs to keep the design DRY.
- Select generic and language-appropriate conventions through
  `skills/engineering/engineering-routing/SKILL.md`: `skills/languages/python/`,
  `skills/languages/go/`, or `skills/languages/typescript/` as actually present.
- Record the applicable conventions rather than imposing Python idioms elsewhere.
- Note any **gotchas** from `KB/<repo>/gotchas.md` that the spec must respect.

---

## Step 6 — Briefing (deliverable to the user)

Produce a single, scannable briefing **before** invoking [canonical author](../feature-specifications/SKILL.md#gather-context). Structure:

```
# Context Briefing — <Subject>

## 1. Business Context
- Overarching goal: <one paragraph — what outcome this unlocks>
- Stakeholders: <list>
- Constraints: <regulatory / deadline / vendor>
- Linked RFC: <Confluence URL, or "none found — confirmed with user">
- JIRA: <ticket ID + status + assignee>

## 2. Behavior map — concise and evidence-backed
- Entry points today: <files + line refs>
- Control flow today (numbered)
- Verified schema today: <quoted names, types, nullability; authoritative source; new vs existing>
- Event flow today: <actual events, tasks and completion boundaries>
- Applicable conventions: <source paths and implications for this change>
- Material contradictions: <code vs docs vs tickets; unresolved decision and impact>
- Test coverage today: <files / coverage summary>
- Gaps the feature must close: <bullets>

## 3. Implementation Precedents
- Closest analogous feature: <path + brief>
- Existing owners / consolidation candidates: <capability — existing symbol at file:line — whole|partial|adjacent overlap — delete-and-replace|encapsulate|re-design; or "no existing owner found">
- Code-prompts that apply: <list>
- Gotchas in scope: <bullets from gotchas.md>

## 4. Gather Hygiene
- Repos read: <list with original branch + SHA + path used>
- Worktrees created / stashes pushed: <list, with cleanup status>
- Source status: <each source: consulted-with-findings / empty / unavailable, and why>
- Anything not gathered (and why): <list>

## 5. Open Questions for the User
- <questions that must be answered before the spec is generated>
```

Stop here and wait for user sign-off (or explicit "go ahead") before calling [canonical author](../feature-specifications/SKILL.md#gather-context). If the user wants to skip the sign-off, that's fine — they will say so.

---

## Step 7 — Cleanup

After the user signs off (or after the spec is generated, depending on the flow):

- Remove any worktrees created in Step 1 (`git worktree remove ...`).
- If a stash was pushed, restore the user's original branch and `git stash pop`.
- Confirm in one line that all repos are back to their pre-gather state.

---

## Principles

1. **Ask before assuming.** If business context, RFC, or scope is unclear, ask. A short clarifying question is cheaper than a wrong spec.
2. **Never invent.** If a source doesn't exist, say so. Do not fabricate goals, stakeholders, or precedents.
3. **Verify the schema; never paraphrase it.** Quote actual names, types and nullability from authoritative schema sources or permitted live data per Step 4a. If neither is available, stop and surface the gap — drafting against assumed schema is worse than drafting nothing.
4. **Non-disruptive.** The user's working tree must look identical after the gather. Use worktrees by default.
5. **Business first.** The briefing leads with *why*, not *what files*.
6. **Surface the gaps.** Tell the user what is missing, not just what was found.
7. **Surface the duplicates too.** Say what already exists that the feature would otherwise rebuild, so the spec consolidates instead of adding a second owner for the same responsibility.
8. **Hand off cleanly.** The output is a briefing the user can paste forward — [canonical author](../feature-specifications/SKILL.md#gather-context) should be able to consume it directly.

9. **Name what you found.** Name the language and framework the trace actually found; never present a guide’s ordering as the repository’s architecture.
