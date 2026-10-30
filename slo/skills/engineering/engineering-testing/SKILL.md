---
name: engineering-testing
description: Shared verification obligations — continuous verification, evidence reporting, baselines,
  environment safety and the requirement-and-risk map. Test levels and doubles live in test-verification-policy.
when_to_use: Use before implementing or reviewing to apply shared evidence, baseline and safety obligations;
  load test-verification-policy for how to test.
group: engineering
kind: skill
---

# Engineering Testing

## Skill summary

Shared verification obligations: continuous verification, evidence reporting, baselines, environment safety and the requirement-and-risk map. How to test (levels, doubles, end-to-end scope) is owned by `skills/coding/test-verification-policy/SKILL.md`.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

## Continuous verification

Work in small behavioral increments, respecting dependencies within a runnable slice. Establish the intended behavior, implement and verify it, then extend. Run focused tests per increment and affected surrounding suites at coherent checkpoints; cross-cutting changes need broader checks earlier. Follow the language's test ordering: Go explicitly requires test first. Existing Python/TypeScript cadence remains in their recipes. Never bulk-write then test only at the end. Never disable failing assertions or tests to manufacture green.

Cover each meaningful decision, failure cutoff, boundary and regression; assert observable effects and forbidden effects, not just non-null results. Cover input validation, error translation, cancellation, cleanup, atomicity, retries/idempotency, ordering and compatibility where affected. Skips require a reason and removal condition; report them as unverified, not passing.

## Test levels and doubles

- **Authority:** [`test-verification-policy`](../../coding/test-verification-policy/SKILL.md) owns test levels, priority, test doubles, journey discovery and end-to-end scope. Do not restate them here or in language recipes.
- In short:
  - journey tests first: entry point → application service → domain service → real persistence;
  - real databases and files;
  - mocks only for third-party APIs;
  - injected stubs for internal collaborators;
  - end-to-end tests only as a sparing final check.
- A recording stub cannot prove SQL rollback. A database test cannot reliably replace a deterministic lifecycle-order test. Pick the level that proves the claim.

## Evidence and safety

Read project test commands and environment files; never run against development/production data or real credentials by default. Use bounded waits, isolated resources, deterministic clocks/recorders and cleanup on failure. Run targeted tests after each increment, affected suites at milestones, then applicable full suite, static/build/race/tag gates before final acceptance. A missing dependency or unavailable test environment is BLOCKED evidence, not success.

Report command, cwd, environment/variant, exit status, passed/failed/skipped counts, and relevant output/artifact. Separate new failures from reproduced baseline failures. Never infer testing from a prose verdict, source existence or a compile-only check. Runtime/model routing claims require behavioral evidence beyond document validation.


## Requirement-and-risk map

Before implementation, map acceptance IDs to observable outcomes, test categories,
existing evidence and missing proofs. Identify affected risks: privacy, data loss,
validation, cancellation, cleanup, atomicity, retries, ordering and compatibility.
Explain applicability; do not impose every risk dimension on every component.
Keep the map aligned to the original specification. New tests close a requirement,
meaningful changed decision, critical failure path or reproduced defect.

Cover distinct behavior classes and meaningful interactions. A Cartesian product
is required only when the specification demands it or a critical invariant depends
on the combinations; otherwise justify representative cases. This is not permission
to omit explicit acceptance matrices or critical safety evidence.

Categories are complementary, not cumulative: detailed decisions can be proved by
unit tests, real boundaries by integration tests and wiring by end-to-end journeys.
Do not duplicate the whole matrix at every level. Existing tests may supply evidence
when rerun against the current change; test counts alone do not prove adequacy.

## Baseline and environment decisions

Establish relevant baseline failures and exact commands before implementation.
Introduced regressions block acceptance. Record existing failures with evidence and
an explicit disposition: repair, operator-approved exclusion, or blocked gate.
An unchanged baseline is not an automatic waiver. Skipped or unavailable checks
remain unverified. Run all required gates unless an explicit exemption is approved;
report exemptions and their scope with the final result.

## Test infrastructure boundary

Prefer established fixtures and disposable isolated environments. If testing needs
substantial new supervision, sandboxing or cleanup infrastructure, surface a bounded
harness prerequisite with its owner, acceptance criteria and verification plan.
Do not silently turn feature work into a test-platform project. Safety holds remain
binding: never replace required real-boundary evidence with unsafe runs or mocks
that cannot prove the contract. Escalate missing authority or environment access.
