---
name: describe-a-problem
description: Canonical granular format for describing any problem under investigation
  — failing test, unexpected 5xx, stuck queue, missing row, flaky CI job. A fix is
  never proposed before the failure is described to this depth.
when_to_use: Use before any debugging or fix discussion; pairs with find-how-it-works
  for navigation and debug-by-isolation for resolution.
group: design-and-analysis
kind: skill
source_prompt: analyze/describe-a-problem.md
---

# Describe a Problem — Granular Diagnostic Format

## Skill summary

- **Name:** `describe-a-problem`
- **Description:** Canonical granular format for describing any problem under investigation — failing test, unexpected 5xx, stuck queue, missing row, flaky CI job. A fix is never proposed before the failure is described to this depth.
- **When to use:** Use before any debugging or fix discussion; pairs with find-how-it-works for navigation and debug-by-isolation for resolution.
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Source prompt:** `analyze/describe-a-problem.md`

## Examples

- The user asks for help with: Canonical granular format for describing any problem under investigation — failing test, unexpected 5xx, stuck queue, missing row, flaky CI job. A fix is never proposed before the failure is described to this depth.
- Use before any debugging or fix discussion; pairs with find-how-it-works for navigation and debug-by-isolation for resolution.

## Guidance

This is the canonical format for describing **any problem under investigation** — a failing test, an unexpected 5xx, a stuck queue, a missing row, a flaky CI job. It is the level of detail the reviewer expects on every problem report before any "fix" is even discussed.

The rule is simple: **a fix is never proposed before the failure is described to this depth**. If we can't describe what's happening at this granularity, we don't understand the bug — we are guessing.

> Companion prompt: when this format requires you to navigate code across one or more repositories to answer "where exactly does X get triggered / fail / mutate state", launch [`find-how-it-works.md`](../find-how-it-works/SKILL.md). That prompt is the right tool for "follow the call chain". This prompt is the right tool for "describe what you found".

---

## The 12 sections every problem description must contain

Order matters. Each section answers exactly one question. Don't merge them.

### 0. Plain-English summary (PM-friendly, always required)

Before the technical sections, write **four short paragraphs** an outsider can read. No code, no field names, no jargon — describe the feature in the language a product manager would use to explain to a stakeholder.

1. **What the setup does.** What did the user / test prepare? What does the system have ready, and why? (e.g. "A customer is registered with the fulfillment partner (SOR), and an order is on file for that customer. The system knows where to route orders for this customer when new orders arrive.")
2. **What the application control flow is expected to do.** Walk through the happy path in business terms. What does the user (or upstream system) do, what does the application do in response, what is the customer-visible outcome? Avoid handler/method names — describe the *behaviour*.
3. **What we want to see.** State the success criteria as something a stakeholder could confirm without reading any code. Examples: "Two order records appear on the partner's portal within 30 seconds." "The confirmation document is delivered to the partner's drop folder."
4. **What actually happens.** Describe the failure in user-visible terms. Did the partner never receive anything? Did the customer-portal show stale data? Did the cancellation request silently disappear? Compare it to (3).

This section makes the rest of the writeup useful to anyone who isn't a backend engineer — and it forces the writer to confirm they understand the *intent* of the feature before debugging the implementation. If you can't write section 0 cleanly, you don't yet know what the feature is supposed to do.

### 1. Test / Workflow Identity

| Field | Required content |
|---|---|
| Test path | `tests/step_defs/<file>.py:<lineno>` or the equivalent worker / endpoint location |
| Function / handler name | The Python identifier |
| Feature file (if BDD) | `tests/features/<file>.feature:<lineno>` |
| Scenario name (if BDD) | The full Gherkin scenario title |

### 2. The User-Facing Behaviour Being Asserted

Write the Gherkin scenario (or the equivalent acceptance criterion) **in full**, not paraphrased. The reader must see the same words the test or product spec uses.

### 3. What Each Step Does — Spelled Out

For every When/Then/And clause, describe:
- What it actually executes (HTTP call, DB seed, NATS publish, polling helper).
- What rows are inserted, what events are published, what subjects/streams the message lands on.
- Which file and function backs the step (`<path>:<lineno>`).

This is the section that grows when you actually understand the test. If you can't write this without rereading the code, you don't understand the test yet — go read the code.

### 4. The Failure Point (precise)

Quote the error text. Then map it to a precise location:
```
File: <full path>:<lineno>
> <the exact line that raised>
E <the exception class and message>
```

If the failure is an assertion, show the assertion code and the actual vs expected values. No paraphrasing.

### 5. The Direct Predicate That Failed

What did the code that raised the error actually check? E.g., "the test polls `SELECT * FROM mapped_orders WHERE order_id=$1` and never sees a row", or "the handler raised `MappedCustomerNotFoundError` because `MappedCustomerService.get_by_customer_id` returned None".

### 6. The Causal Chain (timeline)

In real-time order, list every step that ran between trigger and failure. One line per event. Include timestamps if available from logs. Include WHAT each step did, not just THAT it ran.

```
13:53:13.044  POST /o/api/v1/imports  →  csv_import_id=207 created
13:53:13.978  PG INSERT system_event_histories  (event=order_created_from_csv_import, partition_id=387)
13:53:13.978  NATS publish     subject=it_events:stream_processor_20  seq=2226
...
13:54:13.???  test wait_for_mapped_order(order_id=387) timeout
```

### 7. The Routing / Partitioning (when applicable)

For event-driven failures, compute exactly **which subject / partition / queue** the failed message went to, and identify the consumer that should have processed it. Show the math: `partition_key="order_387" → hash → stream_processor_20`.

If multiple events fan out across multiple subjects, list each (`partition_key → subject`) pair as a table.

### 8. The State Inspection (Postgres + ClickHouse + NATS + S3 — whatever's relevant)

Before claiming "this is a race" or "this is state pollution," **query the relevant store** and paste the result.

- **Postgres**: `SELECT ... FROM <table> WHERE <test's key>` — show the rows.
- **ClickHouse**: `SELECT ... FROM <db>.<table> WHERE <test's key>` — show the rows.
- **NATS — stream + consumer state**: `curl http://localhost:18223/jsz?streams=true&consumers=true` — show the consumer state (`delivered_seq`, `ack_floor`, `num_pending`, `num_redelivered`) for relevant subjects.
- **NATS — the actual message(s)** (mandatory for event-driven failures): you must dump the **entire** in-flight message, not just "did it arrive". Capture and paste:
  - `subject` (the routed stream/partition — confirms section 7's routing math)
  - `seq` (the stream sequence number)
  - `headers` (every header field)
  - `data` decoded as JSON: full `event_name`, `partition_key`, `partition_key_type`, `event_id`, `event_timestamp`, `source`, and the **entire `payload`** (every field — DAO id, customer_id, order snapshot, identifiers, line-item detail, version, etc.)

  This is what enables follow-up diagnosis: "is the partition_key what we expected?", "does the payload contain the field the handler needs?", "is the version compatible with the consumer?". A count-only check answers "did something arrive" but loses the context needed to pin down WHY downstream processing diverged.

  Practical capture options:
  - `docker exec orders_it_natsjs nats consumer next <stream> <durable> --no-ack` (preserves redelivery) and pipe the full message body through `jq` so every payload field is visible.
  - Or read the bind-mounted JetStream blocks under `<workspace>/docker_data/orders_nats/jetstream/.../msgs/` and decode with `nats stream view`.
  - Or use the `NATSSubscriber` test helper directly: subscribe early, log the **full** captured message struct (subject, headers, data) — not just count.

- **S3 / MinIO**: `mc ls --versions --recursive local/<bucket>/<prefix>` — show the objects.
- **Mock-server stores (partner_mock SQLite, etc.)**: `sqlite3 /tmp/<store>.db "SELECT * FROM <captured_requests>"` — show the captured request bodies in full.

Always include "what the system *expected* to see" alongside "what's actually there". Mismatch = the bug.

**The rule for event-driven systems**: dump the whole event — never assume the payload looks right because the count is right. The most common bugs (wrong partition_key, missing field in payload, wrong event_name, wrong DAO version) only surface from the full body.

### 9. Distinguish Real-Failure vs State-Pollution-Flake

Run the test in **isolation** with a clean stack (purged NATS, fresh MinIO, dropped helper tables). Two cases:

- Passes in isolation → state-pollution flake from upstream tests. Identify the polluting predecessor.
- Fails in isolation → real failure. Continue inside the test's own scope.

State this conclusion before proposing a fix.

### 10. Root Cause — Located, Not Guessed

Cite the file and line where the wrong behaviour originates. One sentence. No hand-waving.

### 11. The Fix Proposal (last, not first)

Concrete diff snippet. The fix is the *consequence* of the description; not a substitute for it.

---

## Anti-patterns — what NOT to do

- ❌ "It's flaky in CI, let me bump the timeout" → without sections 1-10, this is guessing.
- ❌ "Looks like a NATS issue, let me purge" → without 7-8, you don't know.
- ❌ "I think the handler isn't running" → say **why** you think that, citing logs and state.
- ❌ Paraphrasing the exception ("timeout error") → quote it exactly, including file:lineno.
- ❌ Inferring routing without computing it → run the partitioner, show the math.
- ❌ "Let me try X and see if it works" → no. Describe the system first, then change one thing on purpose.

---

## Ideal Behavior First, Then the Problem — With Real Code

Sections 1-11 pin down *what broke*. This section governs how the writeup frames the break: lead the reader through the **ideal behavior** of the system before restating the defect against it. Establish how the components should interact when everything works correctly — a detailed, plain-English narrative — and only then reiterate exactly where reality diverges. Section 0's happy-path paragraph opens this framing in business terms; this rule carries the same discipline into the technical body.

Both the ideal-behavior walkthrough and the problem restatement must embed **real code samples taken from the actual codebase**, with `file:line` references — not pseudocode or invented signatures. The reader must see the concrete code the narrative is about, exactly as it exists.

For a bug report, structure the framing as three ordered parts:

1. **Describe the bug** — the symptom plus a one-sentence cause.
2. **Ideal behavior** — a detailed walkthrough of how the components should have interacted, with real code samples.
3. **Reiterate the problem** — restate the defect against the ideal, showing the real code that diverges.

---

## What "good enough" looks like

A finished problem description should let a teammate **who has never seen the code**:

1. Reproduce the failure.
2. Point at the exact line of code where the wrong thing happens.
3. Tell whether the fix should be in the test, the harness, the app code, or the infra — and why.

If your description doesn't enable all three, it isn't done yet.

---

## When to invoke `find-how-it-works.md`

Use it when section 3 (step expansion), section 6 (causal chain), or section 7 (routing) requires walking the code path from a router/worker/handler entry-point to the database. `find-how-it-works.md` gives the standard `router → app service → domain service → DAO` framing. Bring its output back into this document under the section that needed it.

---

## Quick template (paste, fill, present)

```
## 0. Plain-English summary
**What the setup does.** <2-4 sentences in business terms>
**What the app is supposed to do.** <2-4 sentences in business terms, happy path>
**What we want to see.** <2-3 sentences — observable success criteria for a stakeholder>
**What actually happens.** <2-3 sentences — observable failure as a user would experience it>

## 1. Identity
- Test: <path:lineno>
- Function: `<name>`
- Feature: <path:lineno>
- Scenario: "<scenario name>"

## 2. Scenario (verbatim)
<full Gherkin or acceptance criterion>

## 3. Step-by-step
<one bullet per When/Then with the backing file:lineno>

## 4. Failure
File: <path:lineno>
> <line>
E <exception + message>

## 5. Predicate
<the exact thing the failing line checks>

## 6. Causal chain
<timeline, one line per step>

## 7. Routing
<partition_key → subject table, or N/A>

## 8. State
- Postgres: <query + result>
- CH: <query + result>
- NATS: <stream state + consumer state>
- S3: <object list>
Expected: <what should be there>

## 9. Isolation result
- In isolation: PASS / FAIL
- Conclusion: <state-pollution flake | real failure>

## 10. Root cause
<file:lineno, one sentence>

## 11. Fix
<diff snippet>
```
