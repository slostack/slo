---
name: 11-integration-test-investigation-format
description: 'Integration tests: canonical format for describing a failing integration-test
  investigation (identity, scenario verbatim, repro steps, exact failure, predicate,
  causal chain, isolation result, root cause cited by file:lineno).'
when_to_use: Use when writing up what's wrong in a failing integration test.
group: integration-tests
kind: skill
source_prompt: integration-tests/11-integration-test-investigation-format.md
---

# Integration-Test Investigation Format

## Skill summary

- **Name:** `11-integration-test-investigation-format`
- **Description:** Integration tests: canonical format for describing a failing integration-test investigation (identity, scenario verbatim, repro steps, exact failure, predicate, causal chain, isolation result, root cause cited by file:lineno).
- **When to use:** Use when writing up what's wrong in a failing integration test.
- **Group:** `integration-tests`
- **Kind:** `skill`
- **Source prompt:** `integration-tests/11-integration-test-investigation-format.md`

## Examples

- The user asks for help with: Integration tests: canonical format for describing a failing integration-test investigation (identity, scenario verbatim, repro steps, exact failure, predicate, causal chain, isolation result, root cause cited by file:lineno).
- Use when writing up what's wrong in a failing integration test.

## Guidance

## When to use

When writing up a failing integration test for review, handoff, or a session-end postmortem. This is the integration-test specialization of `[[../design-and-analysis/describe-a-problem]]`. Use this when the failure crosses services, hits async workers, or appears non-deterministic — i.e. when the general 12-section format needs concrete shapes for "which container", "which event", "which durable consumer", "which mock store".

Companion prompts:
- `[[../design-and-analysis/describe-a-problem]]` — general 12-section diagnostic backbone.
- `[[../design-and-analysis/debug-by-isolation]]` — the 5-phase method underlying the structure here.
- `07-debugging-failing-tests.md` — the 7-step methodology that feeds Sections 4–7 below.
- `10-cardinal-rules-and-anti-patterns.md` — what to check against once Section 9 has a candidate cause.

---

## Required sections (must all be present, in order)

The investigation is not done until every section can be filled in concretely. If a section can't be written, the bug isn't understood yet.

### 0. PM-friendly summary

Four short paragraphs, no jargon:

- **Setup** — what the test prepares in business terms (e.g. "a tenant with an attribute mapping that says CSV column `Order_Number` maps to the `unique_order_number` field on the order; a fulfillment-partner SOR integration is enabled").
- **Expected control flow** — the happy path described as observable behaviour, not handler/method names (e.g. "uploading a CSV with two rows should create two orders in the Orders Service and produce two `order_records` at the fulfillment partner").
- **What we want to see** — concrete success criteria (rows in `mapped_orders`, rows in `csv_import_row_processing_results.mapped_order_created=true`, mock got 2 POST requests).
- **What actually happens** — concrete failure (`TimeoutError: Timed out after 30.0s waiting for: mapped_order for order 441`; mock got 1 request; `mapped_orders` table has 1 row instead of 2).

If a stakeholder can't read this section, the writer doesn't yet understand the test's intent.

### 1. Test identity

- File path: `tests/step_defs/test_X.py`
- Line number of the failing scenario function
- Scenario name (verbatim from the `@scenario(...)` decorator)
- Feature file path + line range of the matching `Scenario:` block
- Run command: `loadenv environments/local.env && poetry run pytest -s tests/step_defs/test_X.py::test_specific_name -v`

### 2. Setup state (verified)

Show that every Background precondition is satisfied AT THE MOMENT OF the failure. Snapshot the DB at the failure point — do not assume Backgrounds succeeded just because they didn't raise.

- Background steps and the file:line of each `@given` implementation.
- Env vars verified inside the container: `docker exec orders_it_api sh -c 'echo "$SOR_ENABLED|$SOR_NAME|$PARTNER_BASE_URL|$USE_NATS_PUBLISHER|$USE_NATS_CONSUMER"'`. Paste the output.
- `mapped_systems` row verified: `SELECT id, name, is_active, remote_url FROM mapped_systems WHERE name = 'partner'`.
- `mapped_system_errors` verified empty (or expected state): `SELECT id, order_id, mapped_system_id, error_message FROM mapped_system_errors WHERE mapped_system_id = <id>`.
- `system_configurations` attributes verified: query for `SOR_INTEGRATION_ENABLED`, `PARTNER_SYNC_ENABLED`.

### 3. The fail signal

- `File: tests/helpers/polling.py:52` (or wherever) + quoted failure line.
- Exception class + full exception message.
- Which `poll_until` predicate timed out — paste the predicate body.
- For `AssertionError`: the LHS, the RHS, and the comparison operator.

### 4. Service inventory check (Step 0 of the methodology)

```bash
for c in $(docker ps --format '{{.Names}}'); do
  echo "=== $c ==="
  docker exec "$c" ps -ef | grep -E "launch_|celery|dbos" | grep -v grep
done
```

Paste the output. State explicitly: "No duplicate long-running services observed" OR identify the duplicate. If a duplicate is found, this section is the root cause — most other sections become irrelevant. Cite: `[[integration_tests/no-duplicate-services-rule]]`.

### 5. Event audit (the publish path)

Query `system_event_histories` for the test's tenant:

```sql
SELECT h.id, h.event_name, h.partition_id, h.event_timestamp
FROM system_event_histories h
JOIN orders o ON o.id = h.partition_id
WHERE o.tenant_id = <test_tenant_id>
ORDER BY h.id ASC;
```

Show expected vs actual. For event-driven failures, also compute the routing — `partition_key = "order_<id>"` → which subject via `PartitionUtilsForNATS.get_stream_name()` → which durable consumer `it_events:stream_processor_NN`. Dump the per-durable NATS state: `curl :18223/jsz?streams=true&consumers=true | jq '.streams[] | .consumer_detail[] | select(.name == "it_events:stream_processor_NN")'`.

### 6. Handler trace (the dispatch + consume path)

For each order in the test scope, count log markers in `docker logs orders_it_api`:

| order_id | `GSP-RECV` | `[handler] entered` | `[handler] completed` | First early-return point |
|---|---|---|---|---|
| 440 | 1 | 1 | 1 | n/a (happy path) |
| 441 | 0 | 0 | 0 | event never reached `_consume_from_nats` (cold-start race) |

If `GSP-RECV` is present but `[handler] entered` is not, the dispatcher's event-name filter mismatched. If `[handler] entered` is present but `[handler] completed` is not, one of the silent early-returns in `07-debugging-failing-tests.md` Step 5 fired.

### 7. Mock state (the outbound path)

For the fulfillment partner: `sqlite3 /tmp/partner_mock/partner_mock.db "SELECT id, method, path, body FROM captured_requests ORDER BY id DESC LIMIT 10;"` — paste the output. (The mock also exposes `GET /mock/requests`; use whichever the mock supports.)

- Number of captured requests vs expected.
- For each captured request: was the body shape what the V2 SOR mapping should produce? Verify `referenceNumber`, `principalAssigned`, demographics block (`ORIGINAL` type).
- The mock's response: did it include `orderId`? Without `orderId` the chain raises `ValueError` at `order_utils.py:564` and silently fails. See `[[integration_tests/cardinal-rules]]` rule 7.

### 8. Isolation result

Run the failing test in single-test mode on a fresh stack (`make down && make up`, then run only the one test). Record:

- **Passes in isolation?** → it's a state-pollution problem from upstream. Examine teardown completeness, Redis flush state, autouse fixtures from sibling conftests, NATS retention.
- **Fails in isolation?** → it's a real reproducible bug. Continue to Section 9.

### 9. Named root cause

`file:lineno` + one sentence. No hand-waving. Examples of "good enough":

- `orders_service/src/integrations/sor/partner/services/order_create_service.py:72` — silent early-return when `is_mapped_system_active` is False because `mapped_systems(name='partner')` was deleted by a per-test teardown that should have been session-scope.
- `launch_partner_integrations.sh:92` — redundant `launch_global_stream_processor.py` invocation in the partner-integrations container shares durable consumer names with the orders_service pool, JetStream round-robins event delivery and the partner-integrations container ack's events with no registered handler.
- `tests/conftest_csv_import.py:171-193` — `_purge_nats_streams` autouse fixture yanks the backlog from in-flight durables between tests, producing non-deterministic dispatch.

### 10. Recommended fix (last, not first)

Identify the correct layer:

- **App** — requires user authorization. Pre-create durables at startup, add readiness barrier, fix a silent early-return. See `[[integration_tests/cardinal-rules]]` rule 2.
- **Harness / conftest** — change autouse scope, remove banned fixtures, fix teardown order.
- **Step defs** — fix Background order, add a missing `@given` for a flag precondition, switch to snapshot-based assertions.
- **Fixture data** — fix the seed payload to match the production attribute mapping shape.
- **Infrastructure** — remove duplicate launchers, fix env-var compose overrides.

Concrete diff snippet. Cite all KB pages updated as part of the fix per `[[meta/kb-upkeep-rule]]`.

---

## Anti-patterns

- Filling in Section 9 before Sections 4–7. The root cause is the LAST thing named, not the first.
- Inferring routing instead of running `PartitionUtilsForNATS.get_stream_name(partition_key)` and showing the math.
- Paraphrasing the exception. Always quote with file:lineno.
- "Let me bump the timeout and see" — that's not a section here.

## When the format is "done"

A finished writeup lets a teammate who has never seen the code:
1. Reproduce the failure.
2. Point at the file:line where the wrong thing happens.
3. Decide whether the fix belongs in the test, the harness, the app code, or the infra — and why.
