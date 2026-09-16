---
name: development-reviews
description: The two-agent review handshake protocol (.agent_discussions.md turns).
when_to_use: Use whenever participating in the coding-agent / review-agent loop.
group: design-and-analysis
kind: workflow
source_prompt: development-reviews.md
---

# Development-Time Reviews (Coding Agent ↔ Review Agent)

## Skill summary

- **Name:** `development-reviews`
- **Description:** The two-agent review handshake protocol (.agent_discussions.md turns).
- **When to use:** Use whenever participating in the coding-agent / review-agent loop.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `development-reviews.md`

## Examples

- The user asks for an end-to-end workflow that fits: The two-agent review handshake protocol (.agent_discussions.md turns).
- Use whenever participating in the coding-agent / review-agent loop.

## Guidance

A protocol for **continuous, turn-by-turn code review during development** — not after the feature is finished. A dedicated **review agent** runs alongside the **coding agent** and, at the end of every turn, immediately surfaces coding-convention violations, logic gaps, and missing conventions while the change is still fresh and cheap to fix. The two agents converse on a shared discussions file and coordinate through an explicit go-ahead handshake.

---

## When To Use This Guide

This prompt applies when agents are pair programming with one coding and one reviewer agent. 

Use this when a coding agent is doing real implementation work and you want a second agent to catch problems **as they are introduced**, turn by turn, rather than discovering them in a single large review at the end.

- The coding agent writes code in turns and, at the end of each turn, requests review.
- The review agent inspects only what changed that turn, checks it against every coding standard in this repository (the `skills/coding/` library) and the KB, and either requests changes or gives a go-ahead.
- The coding agent does **not** start its next turn until the review agent responds (or the wait window elapses).

**How this differs from [`skills/design-and-analysis/review-feature-code/SKILL.md`](../review-feature-code/SKILL.md):** that guide is a *post-hoc, whole-feature* review against a finished specification — read the spec, inventory the implementation, map spec-to-code, produce a report. This guide is a *live, incremental* review of one turn's diff while the work is in flight. Use `skills/design-and-analysis/review-feature-code/SKILL.md` once at the end; use this one on every turn along the way. They compose: the per-turn reviews keep each step clean, and the final review confirms the whole feature hangs together.

This is a collaboration, not a gate for its own sake. **Both agents share one goal: ship the change correctly and to convention, quickly.** Friction is minimized by being articulate, specific, and fast.

---

## The Two Agents

| Agent | Responsibility |
|---|---|
| **Coding Agent** | Plans and writes the implementation in turns. At the end of each turn, records what it did on the discussions file and waits for review. Addresses feedback, then either resumes the next turn or hands control back to the human. |
| **Review Agent** | Gathers context at the start of the first turn and retains it. On each turn, reads the changed files (and any relevant code or KB pages it needs), checks the change against this repository's coding standards, and responds with a verdict plus feedback, suggestions, and questions. Aims to be fast and unblock the coding agent. |

They run as two separate agent sessions. They never edit each other's code or talk directly — **all coordination happens through the discussions file** described below.

---

## The Discussions File

The two agents communicate by appending to a single shared markdown file.

**Location.** The file lives in the **project root**, or the **parent folder** if the project is a sub-folder of a multi-root workspace. Each agent resolves it by checking the current project root first, then the parent.

**Naming.** `.<something>_discussions.md` — a leading dot (it is scratch coordination, not a tracked artifact) and the `_discussions.md` suffix. Default to `.agent_discussions.md`. If a file matching `.*_discussions.md` already exists in the root or parent, both agents use that one rather than creating a second.

**Creation & first contact.** Before the first turn, the coding agent (whichever agent acts first) **checks for an existing `.*_discussions.md` in the root or parent; if none exists, it creates `.agent_discussions.md` in the project root.** It then **informs the collaborating agent of the file's path** (and that it was just created) so both sides are watching the same file from turn 1 — never assume the other agent already knows where it is.

**Gitignore.** Add the file to `.gitignore` — it is ephemeral inter-agent state, not source.

**Append-only.** Agents only ever **append** new turn blocks, or append their own section to the current turn block. Never rewrite or delete prior turns — the file is the audit trail of the collaboration.

---

## Discussion Entry Format

Each turn is one block, delimited by a dashed rule above and below the title line. The coding agent writes the `Coding Agent:` section; the review agent appends the `Review Agent:` section to the **same** block. The dashed-rule length is not significant — keep it consistent.

```
----------------------------------------------------------------------------------------
<Turn Title> - <DateTime>
----------------------------------------------------------------------------------------
Coding Agent:

<Turn Goal>: <A one or two line description>
<Turn Context>: <A one or two line description with links to sources or places that offer context>

## Changes Introduced

1. <File1>: <Change Description And Reason>
2. <File2>: <Change Description And Reason>

Review Agent:

**Verdict**: Go-ahead | Changes requested | Blocked on questions

**Feedback** (blocking — address before proceeding)

1. <File:line>: <what violates which convention, and the fix>
2. ...

**Suggestion** (non-blocking — consider)

1. <File:line>: <improvement, with the reason>

**Question**

1. <File:line>: <what the review agent needs answered>
```

Field notes:

- **`<Turn Title>`** — a short, descriptive label for the turn's unit of work (e.g., `Add PaymentReversal domain`).
- **`<DateTime>`** — ISO-ish local timestamp, e.g. `2026-05-27 14:32`.
- **`<Turn Goal>`** — one or two lines: what this turn set out to accomplish.
- **`<Turn Context>`** — one or two lines with links to the source of truth: the JIRA ticket, the spec file, the Confluence RFC, the KB page, or the prior turn this builds on. This is how the review agent re-orients without re-asking.
- **`## Changes Introduced`** — a numbered list, one entry per file touched, each stating **the change and the reason**. "Reason" matters: the review agent reviews against the intent, not just the diff.
- **`**Verdict**`** — the explicit handshake signal (an extension to the base format so the coding agent can act unambiguously). One of:
  - **Go-ahead** — no blocking feedback, no unanswered blocking questions. The coding agent may proceed.
  - **Changes requested** — at least one blocking item under **Feedback**. The coding agent must address it before proceeding.
  - **Blocked on questions** — the review agent cannot give a verdict until a question is answered.
- **Feedback / Suggestion / Question** — each a numbered list keyed by `File:line`. Empty subsections may be omitted. Anything under **Feedback** is blocking by default; non-blocking improvements go under **Suggestion**.

---

## Turn Lifecycle (The Handshake)

```
Coding Agent turn N
        │  does the work, then appends the "Coding Agent:" block
        ▼
   discussions file  ──────────────►  Review Agent picks up the new block
        ▲                                     │ reads changed files + relevant code/KB
        │                                     │ appends "Review Agent:" with a Verdict
   Coding Agent polls (≤ 10 min) ◄────────────┘
        │
        ├─ Verdict = Go-ahead          → resume next turn, or hand back to human
        ├─ Verdict = Changes requested → address feedback, write turn N+1, wait again
        └─ Verdict = Blocked on Qs     → answer in turn N+1, wait again
```

0. **Initialize (once, before turn 1).** The coding agent ensures the discussions file exists (create `.agent_discussions.md` if no `.*_discussions.md` is present) and informs the collaborating agent of its path. See *The Discussions File → Creation & first contact*.
1. **Coding agent finishes a turn** and appends a complete `Coding Agent:` block (title, datetime, goal, context, changes introduced).
2. **Coding agent waits.** It polls the discussions file for the matching `Review Agent:` section. **Maximum wait: 10 minutes.** Poll on a modest cadence (roughly every 30–60s) rather than busy-waiting.
3. **Review agent responds promptly** by appending its section with a `**Verdict**`. It should target **1–3 minutes**, well inside the 10-minute ceiling.
4. **Coding agent reads the verdict:**
   - **Go-ahead** → it resumes its next planned task (turn N+1), or, if the work item is complete, **hands control back to the human in the main chat** with a short summary.
   - **Changes requested** → it makes the changes and records them as the next turn, then waits again.
   - **Blocked on questions** → it answers the questions in the next turn (and makes any implied changes), then waits again.
5. **Timeout.** If 10 minutes pass with no `Review Agent:` response, the coding agent does **not** silently proceed past an unreviewed turn. It appends a short `Coding Agent:` note recording the timeout and **hands control back to the human**, who can re-run the review agent or explicitly authorize proceeding. The human may override the timeout behavior for a session.

---

## Review Agent Responsibilities

### 1. Gather context once, on the first turn — then retain it

Before reviewing the first turn, the review agent builds its working context **using the same rules as the specification and specification-verification prompts**, so its mental model matches the spec author's and the implementer's:

- Follow [`skills/design-and-analysis/feature-specifications/SKILL.md`](../feature-specifications/SKILL.md) for *what the feature is* — the Context / Why / Current State / Proposed Approach framing, and the Self-Containedness and Introduce-Before-Using rules. If a spec document exists for this work, read it.
- Follow [`skills/design-and-analysis/feature-specification-verification/SKILL.md`](../feature-specification-verification/SKILL.md) **Step 1 — Load Context** for *how to load it*: read the spec in full, fetch the source JIRA story / Confluence RFC, read the relevant `skills/coding/` convention files for the layers being touched, and read `RESEARCH.md` for existing domains, services, and naming collisions.
- **Context-gathering rule (inherited from those prompts):** if context beyond the conversation is needed — a JIRA ticket, a Confluence RFC, code in a repo not yet read — **ask the human explicitly** (via a `Question` on the discussions file). Do not invent context.

**Retain** this context across turns. Do **not** re-gather it every turn — that is the single biggest threat to the "be quick" requirement. On turns 2..N, reuse the retained model and read only the files the turn touched plus anything specifically implicated by them.

### 2. The review agent has full KB access

The review agent is granted full access to the Knowledge Base at `$SLO_KB_DIR`. Use it to ground feedback in established truth rather than re-deriving it:

- Read the relevant repo folder's `gotchas.md` before flagging behavior in that domain — many "bugs" are documented, intentional quirks (event-loop isolation, Redis lock contention, vendor behavior).
- Check `KB/<repo>/index.md` and `KB/architecture/` for the design rationale behind a pattern before objecting to it.
- `rg -i "<keyword>" $SLO_KB_DIR` to confirm whether a problem is already solved or documented.

The review agent **has the right to read any relevant code** to gather the context it needs to give correct guidance, ask a sharp question, or propose a concrete fix. It does not guess.

### 3. What to check each turn

Review the turn's changes against the intent stated in `<Turn Goal>`, on three axes:

**(a) Coding-convention violations** — check the changed code against **every** coding standard in this repository, not a favored subset. Cite the specific convention file in the feedback.

> **The review agent honors all coding conventions in the `skills/coding/` library.** The tables below are the menu of what exists; the **source of truth is the live `skills/coding/` directory and the conventions table in ``AGENTS.md``** — consult it so newly added prompts are never silently skipped. For each turn, apply the always-on standards plus **every** prompt that matches a layer the turn touched. Do not check against prompts for layers the turn did not touch.

**Always-on — apply to every turn, regardless of layer:**

| Convention file | What to check |
|---|---|
| [`skills/coding/declarative-method-structure/SKILL.md`](../../coding/declarative-method-structure/SKILL.md) | Flat code, early returns, one decision per method, no deep nesting; "tell, don't ask". |
| [`skills/coding/named-arguments-and-type-hints/SKILL.md`](../../coding/named-arguments-and-type-hints/SKILL.md) | Named args for 2+ params; explicit type hints on every parameter and return. |
| [`skills/coding/method-docstrings/SKILL.md`](../../coding/method-docstrings/SKILL.md) | Google-style docstrings on every public method/function. |
| [`skills/coding/python-path-and-import-resolution/SKILL.md`](../../coding/python-path-and-import-resolution/SKILL.md) | `src.*` import resolution, no broken/relative-path imports. |
| [`skills/git-ops/branching-and-commit-conventions/SKILL.md`](../../git-ops/branching-and-commit-conventions/SKILL.md) | Branch naming and commit-message structure (when the turn commits). |

**Architecture & structure:**

| Convention file | What to check |
|---|---|
| [`skills/coding/application-structure/SKILL.md`](../../coding/application-structure/SKILL.md) | Folder layout, `app.py`/`main.py` patterns, config, lifespan, connector usage. |
| [`skills/coding/bootstrap-project-scaffolding/SKILL.md`](../../coding/bootstrap-project-scaffolding/SKILL.md) | Scaffolding and initial setup of a brand-new project/service. |
| [`skills/coding/build-middleware/SKILL.md`](../../coding/build-middleware/SKILL.md) | Cross-cutting middleware (DB sessions, request tracking, auth) wiring. |

**Domains, services, routers, API contracts:**

| Convention file | What to check |
|---|---|
| [`skills/coding/build-domain-features/SKILL.md`](../../coding/build-domain-features/SKILL.md) | 3-file `dao.py` / `model.py` / `service.py` layout; CRUD method names; Pydantic models. |
| [`skills/coding/build-application-services/SKILL.md`](../../coding/build-application-services/SKILL.md) | The `invoke()` entry-point pattern; single responsibility; private `_` step methods. |
| [`skills/coding/build-routers/SKILL.md`](../../coding/build-routers/SKILL.md) | Prefix convention, `SuccessResponseDAO` wrapper, permissions, OpenAPI docs. |
| [`skills/coding/api-response-conventions/SKILL.md`](../../coding/api-response-conventions/SKILL.md) | Response envelope shape, error format, status-code conventions. |
| [`skills/coding/build-api-documentation/SKILL.md`](../../coding/build-api-documentation/SKILL.md) / [`skills/coding/generate-swagger-documentation/SKILL.md`](../../coding/generate-swagger-documentation/SKILL.md) | Redoc/OpenAPI docs kept in sync with endpoint changes. |

**Workers, events, scheduling:**

| Convention file | What to check |
|---|---|
| [`skills/coding/build-celery-workers/SKILL.md`](../../coding/build-celery-workers/SKILL.md) | Celery task naming, registration, routes, beat, async bridging. |
| [`skills/coding/build-dbos-workflow-orchestration-pattern/SKILL.md`](../../coding/build-dbos-workflow-orchestration-pattern/SKILL.md) | DBOS queues, watcher pattern, enqueuer, dedup IDs. |
| [`skills/coding/build-schedulers-tasks-with-dbos/SKILL.md`](../../coding/build-schedulers-tasks-with-dbos/SKILL.md) | DBOS init, DB pool config, cron/scheduled tasks. |
| [`skills/coding/build-event-handlers/SKILL.md`](../../coding/build-event-handlers/SKILL.md) | `process()` signature, `handler.py` routing, `base.py` registration. |
| [`skills/coding/build-partitioned-events/SKILL.md`](../../coding/build-partitioned-events/SKILL.md) | Consistent-hashing partitioning (`uhashring`) for scalable distribution. |

**External integrations & data stores:**

| Convention file | What to check |
|---|---|
| [`skills/coding/build-clients/SKILL.md`](../../coding/build-clients/SKILL.md) | `make_request()` central method; client DAO; error handling. |
| [`skills/coding/build-clickhouse-features/SKILL.md`](../../coding/build-clickhouse-features/SKILL.md) | ClickHouse clients, migrations, DAOs, S3, query patterns. |
| [`skills/coding/setup-alembic/SKILL.md`](../../coding/setup-alembic/SKILL.md) | Alembic migrations for new/changed Postgres tables. |

**AI & agents:**

| Convention file | What to check |
|---|---|
| [`skills/coding/build-agent-tools/SKILL.md`](../../coding/build-agent-tools/SKILL.md) | LangChain `@tool` conventions, async persistence. |
| [`skills/coding/build-react-agent-with-langgraph/SKILL.md`](../../coding/build-react-agent-with-langgraph/SKILL.md) | LangGraph ReAct state/nodes/routing/graph assembly. |

**Frontend:**

| Convention file | What to check |
|---|---|
| [`skills/frontend-vue/vue-coding-conventions/SKILL.md`](../../frontend-vue/vue-coding-conventions/SKILL.md) | **Mandatory** Vue 3 / TypeScript conventions for any Vue change. |
| [`skills/frontend-vue/build-vue-components/SKILL.md`](../../frontend-vue/build-vue-components/SKILL.md) | 3-layer component pattern mirroring the backend. |
| [`skills/frontend-vue/build-websocket-endpoints/SKILL.md`](../../frontend-vue/build-websocket-endpoints/SKILL.md) | Real-time WebSocket bridges between Vue and backend agents. |
| [`skills/coding/create-frontend-htmx-jinja2-fastapi-app/SKILL.md`](../../coding/create-frontend-htmx-jinja2-fastapi-app/SKILL.md) | Server-rendered FastAPI + Jinja2 + HTMX admin portals. |

Pull in whichever prompts above match the layers this turn touched. If a turn introduces a pattern that **no** prompt covers, do not improvise — point the coding agent to [`skills/design-and-analysis/derive-new-convention/SKILL.md`](../derive-new-convention/SKILL.md) (see Collaboration Principles).

**(b) Logic gaps** — what the diff *fails* to handle:

- Unhandled error/exception paths; a `try` with no meaningful `except`.
- A branch of an `if/elif/else` with no behavior or no test.
- Edge cases: empty input, duplicates, retries, concurrent access, null/`None`.
- **Broken wiring** — a worker defined but never registered, a service that creates a job but never enqueues it, an event emitted that no handler consumes, a router never included. (See `skills/design-and-analysis/review-feature-code/SKILL.md` Step 4 for the common disconnects.)

**(c) Missing conventions** — the steps that make a change *actually run* and stay covered:

- Registration/wiring steps the relevant build-* prompt requires (queue definitions, handler lists, router includes, task routes).
- Migrations for new/changed tables ([`skills/coding/setup-alembic/SKILL.md`](../../coding/setup-alembic/SKILL.md)).
- Tests for every new decision point, per [`skills/coding/test-verification-policy/SKILL.md`](../../coding/test-verification-policy/SKILL.md) — happy path, error path, each branch, edge cases. A turn that adds logic without tests is a blocking gap. Check the test against the prompt that matches the layer under test:

| Layer under test | Test convention |
|---|---|
| Domain service | [`skills/coding/test-domain-services/SKILL.md`](../../coding/test-domain-services/SKILL.md) |
| Application service | [`skills/coding/test-app-services/SKILL.md`](../../coding/test-app-services/SKILL.md) |
| Router / controller | [`skills/coding/test-controllers/SKILL.md`](../../coding/test-controllers/SKILL.md) |
| LangGraph agent / graph | [`skills/coding/test-graphs-and-agents/SKILL.md`](../../coding/test-graphs-and-agents/SKILL.md) |
| Test infra & fixtures | [`skills/coding/setup-dependencies-and-tests/SKILL.md`](../../coding/setup-dependencies-and-tests/SKILL.md), [`skills/coding/switch-environments-and-run-tests/SKILL.md`](../../coding/switch-environments-and-run-tests/SKILL.md), [`skills/coding/build-vscode-launch-configurations/SKILL.md`](../../coding/build-vscode-launch-configurations/SKILL.md) |
| Cross-service integration tests | the ``integration-tests/`` suite — start with [`skills/integration-tests/10-cardinal-rules-and-anti-patterns/SKILL.md`](../../integration-tests/10-cardinal-rules-and-anti-patterns/SKILL.md), then [`01-test-setup.md`](../../integration-tests/01-test-setup/SKILL.md), [`04-scenario-conventions.md`](../../integration-tests/04-scenario-conventions/SKILL.md), [`05-step-definitions-with-domain-helpers.md`](../../integration-tests/05-step-definitions-with-domain-helpers/SKILL.md), [`03-teardown-and-reporting.md`](../../integration-tests/03-teardown-and-reporting/SKILL.md) |

- Documentation kept in sync after non-trivial changes, per [`skills/design-and-analysis/update-documentation-after-code-changes/SKILL.md`](../update-documentation-after-code-changes/SKILL.md) (e.g., a new domain/router/worker should be reflected in `RESEARCH.md`).

### 4. Be quick

The review agent must not hold the coding agent for long. The coding agent waits **at most 10 minutes**; the review agent should respond in **1–3 minutes**. Achieve this by:

- Leaning on retained turn-1 context instead of re-gathering.
- Reading only the changed files and what they directly implicate — not the whole feature.
- Doing targeted KB/`rg` lookups, not broad sweeps.
- Writing concise, specific feedback (see Collaboration Principles) rather than essays.

A fast "Go-ahead" is a valid and common outcome. If the turn is clean, say so and unblock immediately.

### 5. Verdict rule

- **Go-ahead** iff there are no **Feedback** (blocking) items and no unanswered blocking **Questions**.
- Non-blocking improvements go under **Suggestion** and never hold up a go-ahead — the coding agent may adopt or defer them.
- A **Question** is only blocking if the review agent genuinely cannot assess correctness without the answer. Otherwise, ask it as a suggestion-level note and still give the go-ahead.

---

## Coding Agent Responsibilities

1. **Initialize the channel.** Before turn 1, ensure the discussions file exists (create `.agent_discussions.md` if none is present) and tell the collaborating agent where it is.
2. **Scope each turn to a coherent unit of work** — one domain, one service, one wiring step — so the review is bounded and fast. Don't bundle ten unrelated changes into one turn.
3. **Write a complete `Coding Agent:` block** every turn: a descriptive title, the timestamp, a crisp `<Turn Goal>`, a `<Turn Context>` with links to the spec/ticket/KB, and a `## Changes Introduced` list that states the **reason** for each file's change, not just the diff.
4. **Wait for the verdict** (≤ 10 min) before starting the next turn. Do not race ahead of an unreviewed turn.
5. **Act on the verdict** — address every blocking **Feedback** item and answer every blocking **Question** in the next turn; record adopted/deferred **Suggestions** explicitly so the trail is clear.
6. **Hand back cleanly.** When the work item is done and the last verdict is Go-ahead, hand control to the human in the main chat with a short summary of what shipped and any deferred suggestions.

---

## Collaboration Principles

Both agents are solving the same problem together. Being articulate and clear is what keeps the loop fast and low-friction.

- **Cite, don't assert.** Reference code as `path/to/file.py:42` (clickable) and name the exact convention being applied — "violates `skills/coding/named-arguments-and-type-hints/SKILL.md`: `create_payment` passes 3 positional args" beats "fix the args."
- **Propose the fix, not just the problem.** Feedback should say what to do, concretely, so the coding agent can act without a second round-trip.
- **Keep entries scannable.** Numbered lists keyed by file; one issue per line; lead with the most important item.
- **Preserve the goal.** The review agent's job is to reach the coding agent's stated `<Turn Goal>` correctly and to convention — not to redesign the feature mid-stream. If the goal itself looks wrong, raise it as a `Question`, don't silently re-scope.
- **Disagree explicitly.** If the coding agent believes a piece of feedback is wrong (e.g., a KB gotcha says otherwise), it says so on the file with the citation, rather than silently complying or silently ignoring. The human can adjudicate.
- **Default to unblocking.** When in doubt and nothing is actually broken, give the go-ahead with suggestions rather than holding the turn.

Remember the reviewer agent can request specifics. 
---

## Worked Example

```
----------------------------------------------------------------------------------------
Add PaymentReversal domain - 2026-05-27 14:32
----------------------------------------------------------------------------------------
Coding Agent:

Turn Goal: Introduce the PaymentReversal domain (model/dao/service) so a settled payment can be reversed.
Turn Context: PROJ-2841 (spec: <feature-specifications-root>/PROJ-2841/PROJ-2841-Payment-Reversals.md, Section 5).
              Follows skills/coding/build-domain-features/SKILL.md. Builds on the existing Payment domain.

## Changes Introduced

1. src/domains/payment_reversal/model.py: New PaymentReversal Pydantic model — fields per spec Section 5.
2. src/domains/payment_reversal/dao.py: New PaymentReversalDAO with create/get/update — mirrors PaymentDAO.
3. src/domains/payment_reversal/service.py: New PaymentReversalService.create_reversal() — validates the
   source payment is in 'settled' state before reversing.

Review Agent:

**Verdict**: Changes requested

**Feedback** (blocking — address before proceeding)

1. src/domains/payment_reversal/service.py:18: `create_reversal(payment_id, amount, reason)` passes 3
   positional args downstream — `skills/coding/named-arguments-and-type-hints/SKILL.md` requires named args for 2+ params,
   and `reason` has no type hint. Add `reason: str` and call with keywords.
2. src/domains/payment_reversal/service.py:24: only the 'settled' branch is handled; a payment in
   'pending' or 'failed' falls through and returns None silently. `skills/coding/test-verification-policy/SKILL.md` needs a
   test per branch — and KB gotcha ([[payments_service/gotchas]], "Reversing a non-settled
   payment") says this must raise, not return None.

**Suggestion** (non-blocking — consider)

1. src/domains/payment_reversal/service.py:30: docstring is present but omits the Raises: clause now that
   the method will raise on bad state — add it per skills/coding/method-docstrings/SKILL.md.

**Question**

1. src/domains/payment_reversal/model.py:11: spec Section 5 lists `reversed_by` as required; the model has
   it nullable. Intentional, or should it be non-null? (Non-blocking — flag only.)
```

The coding agent's next turn would fix items 1 and 2, adopt suggestion 1, answer the question, and record all of it as a new turn block — then wait for a Go-ahead.

---

## Related Prompts

- [`skills/design-and-analysis/review-feature-code/SKILL.md`](../review-feature-code/SKILL.md) — the post-hoc, whole-feature review this complements. Run it once at the end.
- [`skills/design-and-analysis/feature-specifications/SKILL.md`](../feature-specifications/SKILL.md) — how the feature is framed; the review agent's turn-1 context model.
- [`skills/design-and-analysis/feature-specification-verification/SKILL.md`](../feature-specification-verification/SKILL.md) — Step 1 (Load Context) is the review agent's context-gathering procedure.
- [`skills/coding/test-verification-policy/SKILL.md`](../../coding/test-verification-policy/SKILL.md) — the coverage bar the review agent enforces per turn.
- [`skills/coding/declarative-method-structure/SKILL.md`](../../coding/declarative-method-structure/SKILL.md), [`skills/coding/named-arguments-and-type-hints/SKILL.md`](../../coding/named-arguments-and-type-hints/SKILL.md), [`skills/coding/method-docstrings/SKILL.md`](../../coding/method-docstrings/SKILL.md) — the always-on code-style standards checked every turn.
- [`skills/design-and-analysis/derive-new-convention/SKILL.md`](../derive-new-convention/SKILL.md) — if a turn introduces a pattern no code-prompt covers, the review agent points here rather than improvising.
