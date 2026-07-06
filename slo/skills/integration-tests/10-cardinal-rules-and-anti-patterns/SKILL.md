---
name: 10-cardinal-rules-and-anti-patterns
description: 'Integration tests: cardinal rules and anti-patterns to avoid.'
when_to_use: Use as a checklist while writing or reviewing integration tests.
group: integration-tests
kind: skill
source_prompt: integration-tests/10-cardinal-rules-and-anti-patterns.md
---

# Cardinal Rules & Anti-Patterns for Integration Tests

## Skill summary

- **Name:** `10-cardinal-rules-and-anti-patterns`
- **Description:** Integration tests: cardinal rules and anti-patterns to avoid.
- **When to use:** Use as a checklist while writing or reviewing integration tests.
- **Group:** `integration-tests`
- **Kind:** `skill`
- **Source prompt:** `integration-tests/10-cardinal-rules-and-anti-patterns.md`

## Examples

- The user asks for help with: Integration tests: cardinal rules and anti-patterns to avoid.
- Use as a checklist while writing or reviewing integration tests.

## Guidance

## When to use

Read this **before** writing or modifying any integration-test code, fixture, conftest, or harness helper. These rules consolidate the hard NOs and ALWAYS-DOs that emerged from multi-hour debugging sessions in `integration_tests`. Each violation in the wild has cost real time.

Source of truth (live KB pages):
- `[[integration_tests/cardinal-rules]]` — the 10 consolidated rules
- `[[integration_tests/no-duplicate-services-rule]]` — CRITICAL
- `[[integration_tests/no-nats-subscriptions-rule]]`
- `[[integration_tests/teardown-fk-order-rule]]`
- `[[integration_tests/debugging-cheatsheet]]`
- `[[meta/kb-upkeep-rule]]`

---

## NEVER — hard prohibitions

### NEVER create NATS subscriptions, durable consumers, or stream purges from test code

Tests must observe events via the application's `system_event_histories` audit table (joined to `orders.tenant_id`), never via a side-channel JetStream subscriber or `js.purge_stream(...)` call. Side-channel subscribers compete with the app's durable pull-consumers for interest-set routing and silently ack messages out from under the real handlers. Per-test purges yank the backlog out from under in-flight durables and produce non-deterministic dispatch.

Banned from anything under `tests/`: `js.subscribe`, `js.pull_subscribe`, `js.add_consumer`, `js.consumer_info`, `js.delete_consumer`, `js.purge_stream`, `_purge_nats_streams`, `purge_all_streams`, and any fixture that wraps them. Full rule + three independent reasons: `[[integration_tests/no-nats-subscriptions-rule]]`.

### NEVER duplicate long-running services across containers — **CRITICAL**

Pick ONE owner container per service (NATS consumer pool, Celery worker pool, DBOS workflow runtime, scheduler). Two containers running the same `launch_*.py` script register identical durable identifiers and silently share or steal state from each other. Canonical incident: a second `partner_integrations_it_api` container redundantly ran `launch_global_stream_processor.py` alongside `orders_it_api`. Its 32 subprocesses bound to the same durable consumer names against the same `ORDERS_EVENTS_IT` stream, JetStream round-robined `order_created_from_csv_import` across both, and the half delivered to the second container was ack'd with no handler — **two days** of debugging burned. Full rule: `[[integration_tests/no-duplicate-services-rule]]`.

### NEVER modify core application code from the test repo without explicit user authorization

In-scope app repos: `orders_service`, `payments_service`, `notifications_service`, `admin_ui`. The test harness adapts to the app, never the reverse. If a failure looks like it requires an app-side change, surface it to the user with the failing test reference and wait for authorization. Diagnostic in-container overlays via `docker cp` are allowed during a session but are discarded at session end — they never land in `main`. See `[[integration_tests/cardinal-rules]]` rule 2.

### NEVER assume teardown will cascade — enumerate FK children explicitly

PG will not auto-cascade because nearly every FK in `orders_service` is `ON DELETE NO ACTION`. Run the `information_schema.referential_constraints` discovery query (in `03-teardown-and-reporting.md`) for every new parent table you intend to delete from. Two-pass deletes for the raceable subset (`email_addresses`, `phone_numbers`, `addresses`, `mapped_orders`, `mapped_system_errors`, `line_items`, `misc_order_attributes`). Full rule: `[[integration_tests/teardown-fk-order-rule]]`.

### NEVER skip Redis flush between tests when Celery is involved

Stale broker state produces "ghost" task pickups in the next test — symptoms include unexpected `mapped_orders` rows, line_items inserted post-teardown, FK violations on the next test's parent delete. Use either a per-test Redis database (`SELECT N`) or an autouse fixture that flushes between tests.

### NEVER add NATS purges from the test side

`js.purge_stream(...)` and any wrapper around it (`_purge_nats_streams`, `purge_all_streams`) are banned. The 32 durable consumers may still be mid-fetch from prior test publishes when the purge lands, and their pending set vanishes under them. The next test then observes non-deterministic dispatch ordering and pass/fail flips between runs. Each test must observe via the Postgres audit table only.

### NEVER bump a timeout to paper over a flake

Increasing `poll_until` from 30s to 60s when a test "sometimes" times out is a workaround, not a fix. The right move is Step 0–7 in `07-debugging-failing-tests.md` to name the actual cause. Recognise that a bump may sometimes be the correct fix (the chain genuinely needs more time), but it must be justified by a measured timing, not by guessing.

---

## ALWAYS — required practices

### ALWAYS read the KB before assuming a race or starting a deep dive

Before opening `pytest -s --pdb` or asking the user, grep the KB:

```bash
rg -i "<keyword>" $SLO_KB_DIR/integration_tests
```

If the symptom matches any entry in `gotchas.md`, `cardinal-rules.md`, or `debugging-cheatsheet.md`, follow that page's playbook before constructing a new hypothesis. The KB exists so the next reader does not pay the same cost. See `[[meta/kb-upkeep-rule]]` for the upstream rule.

### ALWAYS capture session learnings back to the KB

Every non-trivial debugging session ends with a KB write. A bug fixed without a KB / gotchas / docstring update is half-done. Specifically:

- Every non-trivial bug/fix → gotcha entry in `KB/integration_tests/gotchas.md` (or a new dedicated page if substantial).
- Every non-obvious rule (test-harness contract, infra invariant) → its own rule page (e.g. `KB/integration_tests/no-nats-subscriptions-rule.md`).
- Every investigation that took >30 minutes → postmortem-style note linking timeline, diagnostics, and cumulative diagnosis. Canonical shape: `[[integration_tests/csv-import-partner-investigation-report]]`.

Then update `KB/integration_tests/index.md` so the new page is discoverable. Full rule: `[[meta/kb-upkeep-rule]]`.

### ALWAYS audit the service inventory before chasing a "race"

Step 0 in `07-debugging-failing-tests.md`. If two containers run the same launcher, no further investigation is needed — fix that first. See `[[integration_tests/no-duplicate-services-rule]]`.

### ALWAYS make feature-flag preconditions explicit `@given` steps

`SOR_INTEGRATION_ENABLED`, `PARTNER_SYNC_ENABLED`, `SOR_ENABLED`, `SOR_NAME` — every flag the handler reads must have a visible Background step (typically wrapping `set_system_configuration_attribute`) plus an env-var preflight. Never rely on an implicit default. See `05-step-definitions-with-domain-helpers.md` §"Explicit feature-flag preconditions".

### ALWAYS pin session-scope rows in session-scope fixtures

Rows keyed by a non-tenant column (`mapped_systems(name='partner')`) are shared across the suite — never deleted per-test. Use a session-scope autouse fixture + UPSERT-on-conflict. Cite: `[[integration_tests/csv-import-partner-prereq-setup]]`.

---

## Quick anti-pattern catalogue

| Anti-pattern | Why it's bad | Correct shape |
|---|---|---|
| `await js.purge_stream(stream)` in a fixture | Yanks backlog from in-flight durables | Observe via `system_event_histories`; don't purge |
| Test-side `js.pull_subscribe(...)` for assertion | Competes with app durables for interest-set routing | `then_event_published` reads PG audit table |
| `launch_global_stream_processor.py` in two containers | JetStream shares durable group, events lost | One owner container; remove duplicates |
| Bumping `poll_until` timeout from 30s → 90s | Hides the real cause | Step 0–7 first, name the cause |
| `mapped_systems` deletion in per-test teardown | Races async handler that needs the row | Session-scope fixture, `mapped_system_id=None` in teardown |
| Reordering Background to "fix" a key error | Likely violates step-order dependencies | Trace each step's context reads vs writes |
| Asserting on the partner response body for V2 SOR | Only checks echo round-trip | Assert on mock-captured request body |
| Patching app code in a source repo to make a test pass | Boundary violation | Surface to user, wait for authorization |

---

## When in doubt

- A two-line clarifying question to the user is cheaper than a wrong implementation.
- If the rule above feels like it shouldn't apply to your case, the answer is to surface that to the user — not to silently override.
- Companion long-form methodology: `[[../design-and-analysis/describe-a-problem]]` (12-section diagnostic), `[[../design-and-analysis/debug-by-isolation]]` (5-phase isolation), `07-debugging-failing-tests.md` (the 7-step playbook), `11-integration-test-investigation-format.md` (the structured writeup format).
