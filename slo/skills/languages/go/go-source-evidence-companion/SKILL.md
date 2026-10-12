---
name: go-source-evidence-companion
description: Source-grounded Go review companion showing how pinned Atlas examples evidence typed boundaries, runtime publication, lifecycle ownership, normalized adapters, and test gates without making Atlas-specific choices universal.
when_to_use: Use after go-conventions when a Go task needs a compact source-to-principle evidence map, an audit trail for illustrative examples, or a review checklist for lifecycle, boundary, error, and test claims. Do not use it to select Gin, GORM, NATS, asynq, Temporal, SQLite, or Atlas package names without project evidence.
group: languages
kind: skill
---

# Go Source-Evidence Companion

## Skill summary

A source-grounded Go review companion that separates pinned Atlas evidence from illustrative, unverified examples and preserves the existing Go architecture, API-envelope, lifecycle, and test recipe owners.

## Guidance

## Scope and authority

Read `skills/languages/go/go-conventions/SKILL.md` first. This companion is an additive,
source-grounded evidence map for Go work; it is not a replacement for the Go root
conventions or any framework recipe.

The examples below are bounded by the inspected `slo-atlas` checkout:

- Repository: `/root/Code/slo-atlas`
- Pinned revision: `6d493291bdb38058da6cbaf12775f70e276896b5`
- Revision subject: `ci: restore GitLab verification and containerized backend gates`
- Inspection status: source and tests were inspected read-only; no Atlas test, build,
  deployment, network, provider, Docker, or credential operation is claimed here.

Atlas is evidence for the design decision named in each row, not a universal project
contract. Resolve the target project's module path, dependencies, framework, lifecycle,
wire contract, and test gates before copying an example.

## Evidence map

| Design decision to review | Pinned Atlas evidence | Safe conclusion | Do not infer |
|---|---|---|---|
| Keep CLI display/routing separate from application construction | `cmd/atlasd/main.go:14-87,310-319`; `cmd/atlasd/main_test.go:17-152` | A CLI façade can own writers, help/version/error routing, and delegation while configuration/runtime assembly stays elsewhere. | A help pre-scan, a global configuration getter, or Atlas's command names is required. |
| Use named construction and result shapes at real boundaries | `internal/app/daemon_dao.go:17-158`; `internal/app/daemon_runtime_service.go:22-99` | Required collaborators can travel through named DAOs, be validated, and remain unpublished until assembly completes. | Every small function needs a DAO, or Atlas's full runtime field set belongs in another service. |
| Put interfaces at the consuming package | `internal/app/daemon_bootstrap_service.go:19-51`; `internal/app/daemon_lifecycle_service.go:18-26` | A consumer can define the smallest interface needed for the collaborator it orchestrates. | Every implementation needs an exported interface, or interfaces should be moved to providers. |
| Give lifecycle and goroutine ownership one home | `internal/app/daemon_lifecycle_service.go:94-225`; `internal/app/daemon_launch_test.go:75-172` | Start, cancellation, reverse rollback, wait, readiness, and resource release should have an identifiable owner and deterministic tests. | A synchronous command needs a daemon lifecycle façade, or `WaitGroup`/signals are mandatory for every program. |
| Normalize an external streaming boundary | `cmd/sloctl/provider/provider.go:18-140`; `cmd/sloctl/provider/factory.go:31-158` | A consumer-facing typed stream can hide provider wire formats while construction resolves credentials and routing before the stream starts. | Every Go client must be an LLM provider, use this chunk vocabulary, or use Atlas's credential lanes. |
| Preserve typed error identity while bounding diagnostics | `cmd/sloctl/provider/errors.go:23-155`; `cmd/atlasd/main_test.go:17-152` | Sentinel identity, wrapping, bounded/redacted detail, and exact rendered output can be separate testable contracts. | A particular error string, provider status taxonomy, or redaction helper transfers unchanged. |
| Test asynchronous behavior through observable synchronization | `internal/filesync/watcher.go:19-224`; `internal/filesync/watcher_test.go:18-180` | Channels, context cancellation, bounded waits, and explicit cleanup can prove event/lifecycle behavior without assuming sleeps establish completion. | Filesystem watching, fsnotify, a 200ms debounce, or the Atlas event shape is needed. |
| Match gates to the target repository | `/root/Code/slo-atlas/Makefile:203-235` | A project may define separate format, vet, fast-test, race-test, and aggregate checks; report which ones actually ran. | Atlas's `go test -race -p 1 ./...` is a universal command or proof that another repository passes. |

## Examples

### Small illustrative excerpts

The following excerpts are intentionally illustrative adaptations of the pinned evidence.
They are not drop-in Atlas APIs and were not compiled as part of this companion.
Replace names, ownership, error policy, and dependencies with the target project's
actual contracts.

### Consumer-owned lifecycle boundary

```go
// Illustrative shape adapted from slo-atlas/internal/app/daemon_lifecycle_service.go.
// Keep this interface in the consuming package when it is only needed there.
type component interface {
    Start(ctx context.Context) error
    Stop(ctx context.Context) error
    Name() string
}
```

Use this shape only when the consumer needs ordered startup/rollback. The lifecycle
owner should define what `Stop` means, whether it is idempotent, how cancellation is
propagated, and whether cleanup errors are observable.

### Validate before publication

```go
// Illustrative sequence adapted from the Atlas runtime DAO/service evidence.
result, err := runtimeBuilder.Execute(ctx, input)
if err != nil {
    return RuntimeResult{}, fmt.Errorf("build runtime: %w", err)
}
if err := result.Validate(); err != nil {
    return RuntimeResult{}, fmt.Errorf("validate runtime: %w", err)
}
runtime := newRuntime(result)
return runtime, nil
```

This is a decision boundary, not a requirement to create a separate runtime type. The
important questions are: which invariants are checked, whether partial resources are
cleaned up, and whether callers can observe an incomplete runtime.

### Error contract with an inspectable cause

```go
// Illustrative shape adapted from Atlas's typed provider error evidence.
type RemoteError struct {
    StatusCode int
    Detail     string // bounded and already redacted by the adapter
}

func (e *RemoteError) Error() string { return "remote request failed" }
func (e *RemoteError) Unwrap() error { return ErrRemoteRequest }
```

Do not copy the sentinel name or message. Decide whether the target needs
`errors.Is`, `errors.As`, a public status field, redaction, bounded snippets, or an
exact user-facing rendering contract, then test each selected behavior.

## Review checklist

For a source-grounded Go review, record the evidence rather than upgrading an example
into a rule:

1. **Boundary:** name the consumer, input/result type, and adapter or collaborator seam.
2. **Ownership:** identify who starts, cancels, stops, waits for, and cleans up each
   background operation or external resource.
3. **Publication:** identify the validation gate before a runtime, capability, or
   externally visible state is published.
4. **Failure:** identify the root cause, wrapping/sentinel behavior, bounded diagnostics,
   and whether cleanup errors have an explicit policy.
5. **Test category:** use an isolated recorder for order/cutoff policy, a real relevant
   store or transport for persistence/wire behavior, and lifecycle synchronization for
   cancellation/wait/rollback claims.
6. **Applicability:** record why the selected framework or dependency is present. A
   pinned Atlas example is not evidence for adopting Gin, GORM, NATS, asynq, Temporal,
   ClickHouse, SQLite, or a provider SDK in a different project.
7. **Command evidence:** report exact commands, tool versions, skips, and unverified
   gates. Static inspection and compilation do not establish a passing race, Docker,
   deployment, or live-provider check.

## Evidence versus unverified examples

**Source-grounded in this companion:** the repository revision, paths, line ranges, the
high-level decisions in the evidence table, and the fact that the cited Atlas source and
tests were inspected read-only.

**Illustrative and unverified:** the three Go snippets, the generalized review checklist,
and any application of these patterns to a project other than the pinned Atlas checkout.
They must be adapted and compiled/tested in the target repository before being described
as implementation evidence.

**Not established:** current Atlas test status, current release behavior, runtime health,
provider availability, deployment readiness, or compatibility of the examples with a Go
version other than the target project's selected toolchain. The inspected Atlas module
declares `go 1.26.4` in `/root/Code/slo-atlas/go.mod:1-3`; local toolchain availability is
not evidence that Atlas or a target project builds here.

## Companion relationship

Use this skill as a compact audit/evidence companion with these existing owners:

- `go-conventions` — authoritative Go construction, ownership, errors, naming, and tests.
- `go-build-application-services` — typed workflow service construction and orchestration.
- `go-build-lifecycle` / `go-test-lifecycle` — runtime ownership and deterministic lifecycle proof.
- `go-test-orchestration` — consumer-fake ordering and failure-cutoff proof.
- `go-recipe-api-response-conventions` — the sole Go API envelope owner; this companion
  does not define or replace a wire contract.
- `go-recipe-code-test-loop` — Go test-first cadence and project-substituted commands.

Do not duplicate those recipes or use this companion to select an optional framework.
