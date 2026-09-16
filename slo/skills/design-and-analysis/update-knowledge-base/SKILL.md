---
name: update-knowledge-base
description: At session end — incrementally update the Obsidian KB with insights,
  decisions, and gotchas.
when_to_use: Use when you've learned something non-obvious that future sessions need.
group: design-and-analysis
kind: workflow
source_prompt: update-knowledge-base.md
---

# Update Knowledge Base

## Skill summary

- **Name:** `update-knowledge-base`
- **Description:** At session end — incrementally update the Obsidian KB with insights, decisions, and gotchas.
- **When to use:** Use when you've learned something non-obvious that future sessions need.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `update-knowledge-base.md`

## Examples

- The user asks: "Update knowledge base after this change."
- You are at the close-out phase and need the right post-change documentation workflow.

## Guidance

> Incrementally update the Obsidian Knowledge Base at `$SLO_KB_DIR/` with new insights, decisions, and learnings from the current session.

---

## Purpose

The Knowledge Base is the long-term institutional memory for the order-management platform. Unlike `LEARNINGS.md` (which captures reusable coding solutions) or `RESEARCH.md` (which indexes the codebase), the KB captures **business context, architecture, design decisions, gotchas, and cross-repo knowledge** in an interlinked Obsidian vault.

Every conversation produces knowledge that is valuable beyond the current session. This prompt ensures that knowledge is captured before it decays.

---

## When to Trigger

Update the KB when any of these conditions are met:

| Trigger | Why |
|---------|-----|
| **End of conversation** (before signing off) | Capture everything learned in this session |
| **Context compaction occurs** | Long session indicator — knowledge may be lost if not persisted |
| **User resumes after a gap** | Good checkpoint to record what was done before the break |
| **Significant design decision made** | Architecture choices must be recorded for future agents |
| **Bug root cause found** | Gotchas prevent the same debugging effort next time |
| **New integration or workflow implemented** | Flow changes affect multiple repos |
| **Cross-repo connection discovered** | Wiki-links between KB pages add navigational value |

---

## What to Update

### Always capture these when they arise:

1. **New gotchas** discovered during debugging — add to the repo's `gotchas.md`
2. **Design decisions** made during implementation — add to the repo's `design-decisions.md`
3. **New workflows or flow changes** — update the repo's `architecture.md` or relevant flow page
4. **Postmortem/RCA information** from incidents — add to `gotchas.md` with root cause and fix
5. **New integrations or vendor-specific details** — update the relevant repo's index or create a new page
6. **Updated architecture** if services changed — update `architecture/system-overview.md`
7. **Cross-references** between KB pages when connections are discovered — add `[[wiki-links]]`

---

## How to Update

### Step 1: Identify what changed

Review the current conversation for:
- Decisions made (and alternatives considered)
- Bugs fixed (root cause + fix)
- New patterns established
- Architectural changes
- Integration details learned

### Step 2: Read the target KB page

**Always READ the existing KB page before editing.** This prevents:
- Duplicating information already captured
- Accidentally overwriting existing content
- Missing the right section to append to

### Step 3: Append new content

- **Append new sections** rather than rewriting existing content
- Add a dated header for each new addition:
  ```markdown
  ## Updated: 2026-04-20
  ```
- Use Obsidian `[[wiki-link]]` syntax for cross-references:
  ```markdown
  See [[orders_service/gotchas]] for the related backend issue.
  Related: [[architecture/event-bus|Event Bus & Messaging]]
  ```
- Keep entries concise but complete — future agents need enough context to understand without the original conversation

### Step 4: Create new pages if needed

If a new topic does not fit any existing page:
1. Create a new `.md` file in the appropriate repo directory
2. Add a link to it from the repo's `index.md`
3. If it is a new top-level section, also add it to `Home.md`

### Step 5: Verify cross-references

After editing, check that any `[[wiki-links]]` you added point to existing pages. If the target page does not exist yet, either create it or use a plain text reference instead.

---

## What NOT to Do

- **Do not rewrite existing content** unless it is factually wrong or outdated
- **Do not add ephemeral/temporary information** (e.g., "currently debugging X", "waiting for deploy")
- **Do not duplicate** what is already in `AGENTS.md` or `RESEARCH.md` — the KB captures business and architectural knowledge, not codebase indexes
- **Do not push code** — KB updates are local only
- **Do not add code snippets** unless they illustrate a gotcha or design decision — the KB is not a code reference

---

## KB Structure Reference

This is an illustrative layout for a multi-service order-management platform.
The exact repo names and page set will differ per project — mirror whatever the
real vault already uses.

```
$SLO_KB_DIR/
├── Home.md                              # Entry point — links to all repos and cross-cutting concerns
├── architecture/                        # Cross-cutting architectural knowledge
│   ├── system-overview.md               #   How services connect (inter-service map)
│   ├── event-bus.md                     #   Redis Streams, NATS, Celery messaging
│   └── authentication.md               #   HMAC auth, inter-service auth patterns
├── gotchas/
│   └── index.md                         # Cross-repo gotchas and pitfalls
├── orders_service/                      # Core order-management backend
│   ├── index.md                         #   Entry point for this repo's KB
│   ├── architecture.md                  #   Service architecture
│   ├── api-endpoints.md                 #   Key API endpoints
│   ├── data-models.md                   #   Domain models and schemas
│   ├── design-decisions.md              #   Why things are built this way
│   ├── gotchas.md                       #   Known pitfalls and workarounds
│   ├── workflows.md                     #   Business workflows (imports, allocations, etc.)
│   └── queues-and-events.md             #   Async processing details
├── payments_service/                    # Payment processing service
│   ├── index.md
│   ├── architecture.md
│   ├── design-decisions.md
│   ├── gotchas.md
│   └── payment-flows.md                #   Card, bank-transfer, tokenization flows
├── notifications_service/               # SMS/email orchestration service
│   ├── index.md
│   ├── architecture.md
│   ├── design-decisions.md
│   ├── gotchas.md
│   └── providers.md                     #   SMS/email provider integration details
├── admin_ui/                            # Admin dashboard
│   ├── index.md
│   ├── design-decisions.md
│   └── gotchas.md
└── integration_tests/                   # Integration test suite
    ├── index.md
    ├── design-decisions.md
    ├── gotchas.md
    └── test-scenarios.md               #   Test coverage and scenarios
```

### Where to put new information

| Type of knowledge | Target file |
|---|---|
| Bug root cause / workaround | `<repo>/gotchas.md` |
| Why we built it this way | `<repo>/design-decisions.md` |
| How the service is structured | `<repo>/architecture.md` |
| API contract details | `<repo>/api-endpoints.md` |
| Business workflow logic | `<repo>/workflows.md` or relevant flow page |
| Cross-service interactions | `architecture/system-overview.md` |
| Messaging/event patterns | `architecture/event-bus.md` |
| Auth patterns | `architecture/authentication.md` |
| New repo or top-level topic | `Home.md` + new directory |
