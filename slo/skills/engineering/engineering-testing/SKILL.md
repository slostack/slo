---
name: engineering-testing
description: Shared verification obligations and distinct unit, orchestration, adapter integration and
  end-to-end test categories; no framework is assumed.
when_to_use: Shared verification obligations and distinct unit, orchestration, adapter integration and
  end-to-end test categories; no framework is assumed.
group: engineering
kind: skill
---

# Engineering Testing

## Skill summary

Shared verification obligations and distinct unit, orchestration, adapter integration and end-to-end test categories; no framework is assumed.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

## Continuous verification

Work in small, dependency-ordered increments. Establish the intended behavior, implement and verify each bounded unit, run surrounding tests, then proceed. Follow the language's test ordering: Go explicitly requires test first. Existing Python/TypeScript cadence remains in their recipes. Never bulk-write then test only at the end. Never disable failing assertions or tests to manufacture green.

Cover each meaningful decision, failure cutoff, boundary and regression; assert observable effects and forbidden effects, not just non-null results. Cover input validation, error translation, cancellation, cleanup, atomicity, retries/idempotency, ordering and compatibility where affected. Skips require a reason and removal condition; report them as unverified, not passing.

## Categories and collaborators

| Category | Purpose | Collaborators / evidence |
|---|---|---|
| Isolated unit | deterministic domain decision or pure transformation | inputs and result/error assertions; no infrastructure required |
| Orchestration unit | delegation order, arguments, failure cutoffs, lifecycle ownership | injected recording fakes at consumer boundaries; assert later calls did not happen |
| Adapter/database integration | driver/schema/transaction/protocol behavior | actual relevant adapter and disposable real dependency; apply migrations, assert persistence/rollback/constraints and cleanup |
| End-to-end | composed externally observable flow | deployed/booted stack with declared controlled external boundaries; assert ingress to terminal effects |

A recording fake cannot prove SQL rollback. A database test cannot reliably replace a deterministic lifecycle-order test. A Python recipe historically calling database tests 'unit' is still integration by this taxonomy. Do not turn one category's mock policy into a universal ban or universal requirement.

## Evidence and safety

Read project test commands and environment files; never run against development/production data or real credentials by default. Use bounded waits, isolated resources, deterministic clocks/recorders and cleanup on failure. Run targeted tests after each increment, surrounding tests, then applicable full suite, static/build/race/tag gates. A missing dependency or unavailable test environment is BLOCKED evidence, not success.

Report command, cwd, environment/variant, exit status, passed/failed/skipped counts, and relevant output/artifact. Separate new failures from reproduced baseline failures. Never infer testing from a prose verdict, source existence or a compile-only check. Runtime/model routing claims require behavioral evidence beyond document validation.

