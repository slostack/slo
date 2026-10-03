---
name: go-recipe-code-test-loop
description: Go test-first red/green/refactor cadence with table-driven decisions, package, race, build,
  vet and build-tag evidence.
when_to_use: Go test-first red/green/refactor cadence with table-driven decisions, package, race, build,
  vet and build-tag evidence.
group: languages
kind: skill
---

# Go Recipe Code Test Loop

## Skill summary

Go test-first red/green/refactor cadence with table-driven decisions, package, race, build, vet and build-tag evidence.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

## One bounded increment

1. Read go-conventions and the project commands. Select one decision point or observable boundary.
2. Write its table row/test first. Run `go test -count=1 -run '^TestService_Execute$/failure' ./internal/app/example` (substitute actual package/case). Confirm it fails for the intended missing behavior, not broken setup.
3. Implement only enough to make it pass. Run the focused case and containing package before adding another unit.
4. Refactor named steps and ownership while green. Add the next failure/success row before its implementation.
5. Run relevant integration tests for actual boundary claims, then full project gates.

| Gate | Example (use project paths/variants) | Evidence |
|---|---|---|
| Targeted | `go test -count=1 -run '^TestExecute$' ./internal/app/example` | exact behavior / failure cutoff |
| Package | `go test ./internal/app/example/...` | local regressions |
| Race | `go test -race -count=1 ./internal/app/...` | lifecycle/shared-state changes |
| All | `go test ./...` | non-tagged suite |
| Build / vet | `go build ./...`; `go vet ./...` | compilation/static diagnostics, not behavior proof |
| Variants | `go test -tags '<project-tags>' ./...` | each supported variant; never invent tags |
| Coverage | `go test -coverprofile=coverage.out ./...`; `go tool cover -html=coverage.out` | inspect missed decisions, not just percentage |

`-run` is a regular expression; anchor overlapping names. Cached results do not prove a new runtime execution; use -count=1 for evidence-sensitive checks. require/ErrorIs (or standard errors.Is) guards preconditions/error identity; independent payload checks should expose all mismatches. Testify is optional unless the project uses it.

Configuration changes can affect precedence, explicit false/zero, parsing and startup: do not exempt them from behavior tests. A truly mechanical change may use compile/static gates plus existing regression coverage, with the limitation stated. A disposable one-shot script can use a recorded smoke when proportional; do not call it full coverage.

Never write hundreds of lines before testing, skip a failing assertion, accept an unexplained t.Skip, or substitute an end-of-task full suite for intermediate green handoffs. When delegating, include the test-first rule and require per-increment command evidence. Parallel execution still requires explicit user authorization.

