---
name: go-review
description: Go review of architecture, declarative style, named construction, lifecycle/error compatibility,
  test-first and component-specific evidence.
when_to_use: Go review of architecture, declarative style, named construction, lifecycle/error compatibility,
  test-first and component-specific evidence.
group: languages
kind: skill
---

# Go Review

## Skill summary

Go review of architecture, declarative style, named construction, lifecycle/error compatibility, test-first and component-specific evidence.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

Load engineering-review, go-conventions and only affected recipes. Produce an ownership map, requirement-to-code/test matrix and actionable findings with path/line.

- Model is resolved, DAO transient, service cohesive, adapter mechanical. Reject a service locator even if split into helpers.
- Consumer-local lowercase interfaces; constructors accept minimal interfaces and return concrete types; required dependencies arrive in named DAOs, optional behavior via options; all literals named.
- Execute is named steps/error guards only; policy and integration mechanics have clear owners; no request data retained on reusable services.
- Every goroutine/listener has cancellation/stop/wait owner, startup rollback and deterministic failure tests; run race gates where applicable.
- Sentinels/typed errors preserve errors.Is/As; boundary text changes have before/after contract and exact tests. No swallowed failure or string-matching policy.
- Godoc begins with symbol name and explains caller contracts; imports stdlib/external/internal and goimports clean; short functions and shallow nesting follow go-conventions.
- Test-first evidence and category-appropriate assertions: recorders for order, real stores for rollback, end-to-end for complete flows. No mock can certify database semantics.
- Framework recipes only when selected; do not adopt Gin/GORM/asynq/Temporal because another Go example uses them.

READY requires concrete evidence; REVISE returns to implementation then re-tests and re-review. An unrun gate is not a stylistic nit and must be reported.

