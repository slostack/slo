---
name: gather-feature-context
description: 'On-request extended context companion feeding feature-specifications mandatory Gather context stage; retains business, architecture, code and source evidence in a sign-off briefing, not a default pre-hook.'
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

Source of truth: the workspace's `<project>.code-workspace` file (it lists the member repos).

Gather context from the product repositories, e.g. for an order-management platform:

- `orders_service`
- `payments_service`
- `notifications_service`
- `admin_ui`
- `integration_tests`

**Skip** the prompt / tooling / out-of-scope repositories:

- the prompt/skills library itself
- any sibling repo the user marks out of scope
- `partner_integrations` (unless the feature explicitly touches it)

If the user names additional repos, include them. If the user names a specific subset, scope to those.

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

### Sources (search all of them — they each cover a different angle)

1. **JIRA ticket** (if provided) — pull description, acceptance criteria, linked epics, comments, RFC links.
   - Use the Atlassian connector tools (`getJiraIssue`, `searchJiraIssuesUsingJql`) when available.
   - Look for linked Confluence RFC pages; pull them via `getConfluencePage`.
2. **Confluence — RFC / spec pages** — search by subject keywords using `searchConfluenceUsingCql`. Atlassian cloud ID: `<atlassian-cloud-id>`. These are engineering-flavoured.
3. **Confluence — PRDs and product pages** — PRDs are usually written by product/business and explain the *why* and the customer/operator workflow. Search separately for `"PRD"`, `"Product Requirement"`, `"Proposal"`, `"Strategy"` alongside the subject keyword. Don't stop at the first RFC — the PRD almost always lives on a sibling page.
4. **Confluence — runbooks, post-mortems, compliance pages** — for regulated or SLA-bound areas (dispute handling, refunds, data-retention, partner contractual rules) there are usually compliance one-pagers or operational runbooks. Pull these for the regulatory framing.
5. **Google Drive — meeting notes and chat threads** — if a Google Drive / Docs connector is available, search Drive for the subject keywords and pull any **meeting notes, design conversations, vendor discussions, customer-success threads, or product brainstorms** that pre-date the JIRA ticket. These often contain the "real" rationale before it got sanitised into a ticket. If no Drive connector is available, **ask the user** whether such a thread exists and request a link.
6. **Knowledge base** — locate it first with `skills/design-and-analysis/locate-knowledge-base/SKILL.md`.
   Discovery is non-blocking: when no KB is found, tell the user, offer to
   create one, and move on to the next source. Otherwise grep `$SLO_KB_DIR`:
   ```bash
   rg -i "<subject keywords>" "$SLO_KB_DIR"
   ```
   - Start at the KB entry point (`Welcome.md` or `index.md`) and the relevant repo's `index.md`.
   - Always read `gotchas.md` in the relevant domain folder.
7. **Memory** — check `<project-memory>/MEMORY.md` for prior project / feedback / reference notes on the subject. The memory often has a one-line summary plus a link to the deeper page.
8. **External authoritative sources (only if internal sources are thin)** — for industry terminology, use reputable references (regulator guidance, published standards, vendor public docs). Cite the source URL in the briefing. Do not rely on training-time recall for regulatory definitions.

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

JIRA tickets often reference an RFC (Confluence page) that contains the canonical design.

- Walk the JIRA ticket's links and remote links (`getJiraIssueRemoteIssueLinks`) for any `confluence` URLs.
- Search Confluence by ticket ID and subject for `RFC`, `Spec`, `Design`.
- Pull any RFC found and include its current status (draft / approved / superseded).

If you cannot locate an RFC, **ask the user explicitly**:

> "I couldn't find an RFC for this feature in Confluence or linked from the ticket. Do you have one you can link? If none exists, I'll proceed without and note that the spec has no upstream RFC."

Do not silently proceed if the absence of an RFC is unusual for the area.

---

## Step 4 — Application & technical context (current state)

**Goal:** Describe the system *as it exists today* in the area the feature touches. The feature spec will build on this.

For each in-scope repo, locate and summarise:

1. **Entry points touched by the subject** — routers, event handlers, scheduled workers, CLI tasks.
2. **Domain services and DAOs** in the relevant domain folder.
3. **Data model** — tables, columns, indexes, FKs relevant to the feature.
4. **Event flow** — what NATS events / Celery tasks fire today in this path. (Memory note: Celery does NOT dispatch events; events flow NATS → `GlobalStreamProcessor` → `EventHandlerProcessing`.)
5. **External integrations** — vendor clients, third-party APIs.
6. **Tests** — existing test coverage in this area, so the spec can extend it rather than duplicate it.

Tools to use:

- `RESEARCH.md` at the root of the core service repo — the codebase index.
- `AGENTS.md` per repo — repo-level conventions and architecture pointers.
- `skills/design-and-analysis/find-how-it-works/SKILL.md` for tracing a flow end-to-end.
- GitHub CLI (`gh`) or local code reads — local is faster if the worktree is fresh.

### Step 4a — Verify the schema against running code or live data (mandatory)

Every column name, table name, type, and nullability that the spec will mention **must** be verified against the actual code or live data — never inferred from a sibling spec, from a prior conversation, or from analogy to another table. Specs that name nonexistent columns or guess at types waste reviewer time and produce broken downstream code; this step is the gate that prevents it.

For each table or model the spec will touch, do at least one of the following — **do not skip both**:

1. **Read the SQLAlchemy model file directly.** It is the authoritative source for table name, column names, types, nullability, indexes, FKs, constraints, and relationships. For the orders service this means `src/domains/<domain>/model.py` (or `src/apps/<subapp>/domains/<domain>/model.py` for subapp-local domains). Quote the actual `__tablename__` string and column list in the context briefing.

2. **Query the live data.** Use one of the following, in order of preference:

   - **Local Postgres** for the orders service — `psql -h localhost -p 5434 -U orders_app -d orders_development` (see KB [[reference_dev_database]]). Run `\d <table>` for schema, `SELECT * FROM <table> LIMIT 10` for representative rows, and `SELECT DISTINCT <enum_column> FROM <table>` to enumerate live status / code values.
   - **BigQuery tenant mirror** — dataset `<bq-project>.<dataset>.*` (see KB [[reference_bigquery_datasets]]). Use the `mcp__claude_ai_Google_Cloud_BigQuery__execute_sql_readonly` MCP connector when available, or fall back to the `bq` / `gcloud` CLI:

     ```bash
     bq query --use_legacy_sql=false --project_id=<bq-project> \
       'SELECT * FROM `<bq-project>.<dataset>.<table>` ORDER BY created_at DESC LIMIT 50'
     ```

     If `mcp.tools.call` is denied on the project (it has been denied before — flagged in workspace memory), fall back to (1) reading the Postgres model directly.

If the spec will introduce **new columns** on an existing table, verify the existing columns first and explicitly enumerate which are new vs reused. If the spec will introduce **new tables**, search for analogous tables and confirm none of them already cover the use case (`grep -r 'class.*Base' src/domains/ | head -50` to enumerate existing models).

Common failure modes this step prevents:

- Naming a table that doesn't exist (e.g. assuming `return_cases` when the table is `returns` — see KB [[returns-schema-and-tracking]]).
- Inventing columns that don't exist (e.g. assuming `received_at` when the column is `returned_at`, or assuming `status` when no `status` column has been added).
- Assuming a polymorphic table covers a discriminator it does not (e.g. assuming `documents.entity_type` accepts `"returns"` when the DAO restricts it to `{"orders", "customers"}`).
- Assuming an enum has a value it does not (e.g. assuming `orders.status` contains `RETURNED` when no such value exists in `src/domains/order/dao.py`).
- Designing a denormalised column to "avoid a JOIN" without checking that the JOIN target column already exists and is indexed.

If you can verify neither the model file nor the live data (e.g. behind a firewall, on a cold worktree, MCP denied), **stop and surface the gap to the user before drafting the spec**. Drafting against assumed schema is worse than drafting nothing.

### Capture (the context-briefing inputs)

- **Current control flow** as a short numbered list (1. Request hits `router.py:foo` → 2. calls `XAppService.invoke()` → 3. ...).
- **Verified schema** — the actual table / column inventory from Step 4a, quoted (not paraphrased). Mark new columns/tables vs existing.
- **Gaps in the current system** — what's missing today that the feature must add.
- **Touchpoints** — exact file paths the spec will need to modify or create alongside.

---

## Step 5 — Implementation details (precedents)

**Goal:** Pull the precedents that the spec should follow so it doesn't reinvent patterns.

- Find the **closest analogous feature** already implemented and capture the file layout it used (router + app service + domain `dao.py`/`model.py`/`service.py`).
- Find the **existing owners** of every capability the feature implies. The system may already do this work wholly, do part of it, or own the responsibility the feature is about to duplicate — and the existing component is usually named differently, which is why it gets missed. For each hit, record the symbol and `file:line`, whether the overlap is whole, partial, or adjacent, and whether the spec should consolidate by deleting and replacing it, encapsulating the new behavior in it, or re-designing it to absorb the new functionality. Redundant artefacts, entities, and domains are a design defect; the briefing must give the spec writer what it needs to keep the design DRY.
- Pull the matching **coding skill** from `skills/coding/` (e.g., `skills/coding/build-routers/SKILL.md`, `skills/coding/build-application-services/SKILL.md`, `skills/coding/build-event-handlers/SKILL.md`, `skills/coding/build-dbos-workflow-orchestration-pattern/SKILL.md`).
- Note any **conventions** that apply: named args, type hints, Google docstrings, declarative method structure, single-responsibility app services.
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

## 2. Current System State
- Entry points today: <files + line refs>
- Control flow today (numbered)
- Verified schema today: <quoted column inventory from Step 4a — for every table the spec will touch, list real columns + types + nullability, and how it was verified (model file path / `psql \d <table>` / BigQuery query). Mark which columns are existing vs new for this story.>
- Event flow today: <NATS events / scheduled workers>
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
3. **Verify the schema; never paraphrase it.** Every table / column / type / nullability the spec will mention must be read from the SQLAlchemy model file or queried from the live data (local Postgres or BigQuery) per Step 4a. If neither is available, stop and surface the gap — drafting against assumed schema is worse than drafting nothing.
4. **Non-disruptive.** The user's working tree must look identical after the gather. Use worktrees by default.
5. **Business first.** The briefing leads with *why*, not *what files*.
6. **Surface the gaps.** Tell the user what is missing, not just what was found.
7. **Surface the duplicates too.** Say what already exists that the feature would otherwise rebuild, so the spec consolidates instead of adding a second owner for the same responsibility.
8. **Hand off cleanly.** The output is a briefing the user can paste forward — [canonical author](../feature-specifications/SKILL.md#gather-context) should be able to consume it directly.
