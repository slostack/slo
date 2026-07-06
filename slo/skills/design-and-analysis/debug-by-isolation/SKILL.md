---
name: debug-by-isolation
description: 'Canonical debugging approach — isolate the problem before solving it.
  Five phases: reproduce in isolation; capture full state across PG/CH/NATS/S3/mocks;
  compute (don''t assume) routing for event-driven systems; traverse the code that
  ran (load find-how-it-works when the trail goes quiet); name the root cause and
  fix at the right layer.'
when_to_use: Use when chasing a failing test, 500 error, stuck queue, missing row,
  or flaky job.
group: design-and-analysis
kind: skill
source_prompt: analyze/debug-by-isolation.md
---

# Debug by Isolation — Approach Guide

## Skill summary

- **Name:** `debug-by-isolation`
- **Description:** Canonical debugging approach — isolate the problem before solving it. Five phases: reproduce in isolation; capture full state across PG/CH/NATS/S3/mocks; compute (don't assume) routing for event-driven systems; traverse the code that ran (load find-how-it-works when the trail goes quiet); name the root cause and fix at the right layer.
- **When to use:** Use when chasing a failing test, 500 error, stuck queue, missing row, or flaky job.
- **Group:** `design-and-analysis`
- **Kind:** `skill`
- **Source prompt:** `analyze/debug-by-isolation.md`

## Examples

- The user asks for help with: Canonical debugging approach — isolate the problem before solving it. Five phases: reproduce in isolation; capture full state across PG/CH/NATS/S3/mocks; compute (don't assume) routing for event-driven systems; traverse the code that ran (load find-how-it-works when the trail goes quiet); name the root cause and fix at the right layer.
- Use when chasing a failing test, 500 error, stuck queue, missing row, or flaky job.

## Guidance

This is the **canonical approach** to debugging a failing test, an unexpected error, an undelivered message, a missing row, or a stuck workflow.

The principle: **isolate before solving**. Never propose a fix until you have proven, by reduction, what the actual problem is. Most fix proposals fail because they're guesses dressed up as theories. Isolation kills the guesses.

> Companion prompts:
> - [`describe-a-problem.md`](../describe-a-problem/SKILL.md) — the format for reporting findings as you isolate.
> - [`find-how-it-works.md`](../find-how-it-works/SKILL.md) — invoke when isolation hits the "the code did X internally" wall and you need to traverse repositories.

---

## The five-phase method

Run these in order. Do not skip ahead. Each phase has a definite output; if you can't produce it, that phase isn't done.

### Phase 1 — Reproduce in isolation

**Goal:** strip away everything that isn't strictly needed for the failure to occur.

1. Run the failing test **alone** on a **clean stack**. For the order-management integration tests this means: stop the relevant containers, wipe MinIO/SQLite state files, drop helper CH tables, restart, and only then invoke the single test. Document the reset command sequence.
2. Two possible outcomes:
   - **Fails in isolation** → the failure is intrinsic to the test/code under test. Continue to Phase 2 with the isolation case.
   - **Passes in isolation** → the failure is **cross-test pollution**. Now bisect: pair the failing test with the suspected predecessor(s) and run those two only. Continue narrowing until you have a **minimum failing pair**. Then continue to Phase 2 against the predecessor's side-effect — that is the actual problem, not the visible failure.

**Output:** the smallest reproducible command (one test, or two tests in order) that triggers the failure, and the exact runtime measurement.

### Phase 2 — Capture full state at the moment of failure

**Goal:** know what every relevant store actually contains when the failure is observed.

For each store the test exercises, paste the full result, not a count:

- **Postgres**: `SELECT * FROM <table> WHERE <test's keys>` — show rows.
- **ClickHouse**: `SELECT * FROM <db>.<table> WHERE <test's keys>` — show rows.
- **NATS** (event-driven failures, mandatory):
  - Stream + per-consumer state: `curl http://localhost:18223/jsz?streams=true&consumers=true` — capture `first_seq`, `last_seq`, `messages`, and **per consumer**: `name`, `filter_subject`, `delivered.stream_seq`, `ack_floor.stream_seq`, `num_pending`, `num_ack_pending`, `num_redelivered`.
  - **The actual message body**: write a focused subscriber (see `integration_tests/scripts/probe_event_arrival.py` for a template), subscribe with `DeliverPolicy.NEW`, capture the next 60s of traffic, dump every message's `subject`, `seq`, `headers`, decoded JSON payload (`event_name`, `partition_key`, `event_id`, `event_timestamp`, full `payload` dict). Do this regardless of whether the test is supposed to publish 1 event or 50 — the body is where the *real* discriminators live (`partition_key`, payload DAO fields, version).
- **S3 / MinIO**: `mc ls --recursive` + `mc anonymous get-json` for the bucket if relevant.
- **Mock-server SQLite stores** (partner_mock, etc.): `sqlite3 <path> "SELECT * FROM <captured_requests>"` — paste the full request bodies, not just counts.

**Output:** one section per store, showing actual vs expected. The mismatch is the bug.

### Phase 3 — Compute, don't assume, the routing

For event-driven systems, **never assume** which consumer/queue/worker should have picked up a message. Compute it.

- Use the project's own partitioner. For the orders service: `orders_service/utils/partition.py::PartitionUtilsForNATS.get_stream_name(partition_key)` — given a partition_key, returns the exact subject. Run it from inside the running container (so you use the same Python version and `uhashring`/`mmh3` libraries).
- Read the consumer's actual `filter_subject` from JetStream's monitoring API (it's NOT always the same as the consumer's `name` — see the gotcha at the bottom of this prompt).
- Confirm: published `subject` MUST equal exactly one consumer's `filter_subject` AND that consumer must have moved its `delivered_seq`/`ack_floor` past the message's stream `seq`.

**Output:** a `partition_key → subject → consumer.filter_subject → consumer.delivered_seq` chain that either matches (message delivered) or breaks at a specific step.

### Phase 4 — Traverse the code that ran

If Phase 1-3 show "the event arrived, the consumer acked it, but the side effect didn't happen," the failure is **inside the handler's silent path**. This is where you switch tools.

**Invoke [`find-how-it-works.md`](../find-how-it-works/SKILL.md)** to traverse the relevant repositories. The traversal must cover:

1. The handler chain — usually `src/events/__init__.py::handlers` list. Confirm the handler that should fire is registered.
2. The handler's `process()` method — every early `return` path. List them. For each, identify what state would cause that return. (Tip: searching for `return\s*$`, `return None`, `return False`, `if not …: return` inside the handler reveals silent skip paths.)
3. The downstream service the handler calls — every check (`check_*`) and every silent fallback (e.g., "if not active: return None").
4. Every silent-error path in error-handler utilities. Some `handle_common_error` implementations swallow exceptions and log only at warning level.

Cross-reference against Phase 2's state capture. The branch the code actually took is the one whose precondition matches the state you captured.

**Output:** the file:line of the silent early-return that was hit, and the precondition that triggered it.

### Phase 5 — Name the root cause, then design the fix

Only now is a fix legitimate. Frame it in one sentence: "X (the state captured in Phase 2) caused Y (the silent path located in Phase 4), which produced the observable failure (Phase 1)." Then ask:

- Is the root cause in the **app code** (a bug or missing log)?
- In the **test setup** (it doesn't create the precondition the handler requires)?
- In the **test teardown** (it removes the precondition before the async handler runs)?
- In the **test fixture lifecycle** (it's per-test when it should be session-scope)?
- In the **infrastructure** (NATS retention, MinIO permission, Postgres isolation)?
- In **state pollution** from a prior test (covered by Phase 1's bisect)?

The right fix attacks the right layer. App-code fixes for test-setup bugs are wrong, and vice versa.

---

## Worked example (canonical case study)

Failure: `test_partner_handler_validates_prerequisites_before_sync` — `TimeoutError: mapped_order for order 388`.

- **Phase 1.** Failed in isolation in 73s. Not state pollution.
- **Phase 2.** Postgres `mapped_orders WHERE order_id=388` → 0 rows. NATS stream had 7 messages but `orders_it:stream_processor_22.delivered_seq=2236, ack_floor=2236` (caught up). The partner_mock's `captured_requests` → 0 `/api/order` rows in this test's window. `mapped_systems` and `mapped_customers` post-teardown → 0 rows.
- **Probe** (`scripts/probe_event_arrival.py`) captured the actual NATS message:
  ```json
  {"_metadata":{"subject":"it_events:stream_processor_22","seq":2235,"headers":{}},
   "event_name":"order_created_from_csv_import",
   "partition_key":"order_388",
   "payload":{"order_id":388,"customer_id":320,...}}
  ```
- **Phase 3.** Ran the partitioner: `PartitionUtilsForNATS.get_stream_name("order_388") = "stream_processor_22"`. Cross-checked with consumer monitor API: `orders_it:stream_processor_22` has `filter_subject='it_events:stream_processor_22'`. The chain is intact — the event WAS routed to consumer 22 and consumer 22 acked it.
- **Phase 4.** Invoked the code traversal:
  - `EventHandlerProcessing.process` iterates handlers, catches per-handler exceptions silently (`handler_processing.py:41-54`).
  - `OrderCreatedPartnerHandler.process` runs `PartnerCreateOrderService.invoke()`.
  - `invoke()` calls `check_mapped_system_is_active()` which queries `mapped_systems WHERE name='partner'`.
  - `create_partner_order()` line 72-73: `if not self.is_sor_enabled or not self.is_mapped_system_active: return None` — **silent return, no log**.
- **Phase 5.** Root cause: **test teardown deletes `mapped_systems`** (`teardown_customer` line 94-95 with `mapped_system_id` from context) BEFORE the async partner handler completes. The handler's `mapped_systems WHERE name='partner'` query returns empty → silent early return → no `mapped_orders` row → test polls indefinitely → timeout. The fix: promote `mapped_systems(name='partner', is_active=True)` to a **session-scope autouse fixture** and stop deleting it per-test. App code is correct; this is a **test fixture lifecycle bug**.

---

## Anti-patterns — what NOT to do

- ❌ **Skipping Phase 1.** "It's flaky, let me retry." → No. Isolate first.
- ❌ **Skipping Phase 2.** "The error says timeout, must be slow." → No. Query the store, paste the result.
- ❌ **Skipping Phase 3.** Assuming partition_key X goes to subject Y because the names look alike. Compute.
- ❌ **Skipping Phase 4.** "Probably the handler doesn't run." → Open the handler file, list its returns, identify which one.
- ❌ **Jumping to a fix.** A fix proposal in the first three messages of a debugging session is a guess. Wait until Phase 5.
- ❌ **Fixing the wrong layer.** Most "the timeout is too short, let me bump it" fixes mask a missing setup. The setup is the bug, not the timeout.
- ❌ **Looking at one log line.** The handler chain is async and per-process; the relevant log may be in a different subprocess (`docker exec ... ps -ef` to see them) at a different time.

---

## Gotchas to remember

These cost time the first time you hit them:

- **Consumer name ≠ subject name.** A NATS consumer named `orders_it:stream_processor_22` may have `filter_subject='it_events:stream_processor_22'`. The monitoring API's `config.filter_subject` is the authoritative source.
- **The handler chain silently catches exceptions.** `EventHandlerProcessing.process` wraps each handler in `try/except`, then logs "UNCAUGHT exception in handler X". If you don't see that log line, the handler ran cleanly to completion — either via the happy path OR via a silent early return.
- **`is_processable() = False` and "missing mapped_system" both return silently.** Distinguish them by querying the state Phase 2 says they depend on.
- **DEFAULT_NUMBER_OF_RETRIES is a misnomer.** The partner handler's class attribute named "number of retries" is actually total attempts (=1). The loop is `while retries < 1` which means one pass. Not a retry on top of a first attempt.
- **`mapped_systems` is global** (keyed by `name`, not `customer_id`). Don't tear it down per-test.
- **Mock failure-injection config persists** across processes via SQLite. `_reset_partner_mock` does clear it, but verify by injecting a 500 and then resetting (see [[describe-a-problem]]).
- **NATS message seq advances across the whole stream**, not per-subject. A consumer's `delivered_seq` jumping by 10 doesn't mean it processed 10 of its messages — some of those seqs may be for other subjects. Use `filter_subject` + the message subject to confirm.

---

## When this is "done"

The five phases close once you can write a complete report in the format of [`describe-a-problem.md`](../describe-a-problem/SKILL.md). If you can't fill out all 11 sections, you haven't finished isolating. Keep going.

A finished isolation lets a teammate who has never seen the code:

1. Reproduce the failure deterministically.
2. Point at the exact file:line of the silent return / wrong query / missing precondition.
3. Choose the correct fix layer (app / setup / teardown / fixture / infra) and explain why.

If your isolation can't deliver those three, you have more reduction to do.
