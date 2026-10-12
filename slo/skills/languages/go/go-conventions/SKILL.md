---
name: go-conventions
description: Go authoritative architecture, named DAOs, consumer-owned interfaces, declarative services,
  lifecycle ownership, errors, Godoc and test-first development; no default HTTP/ORM stack.
when_to_use: Go authoritative architecture, named DAOs, consumer-owned interfaces, declarative services,
  lifecycle ownership, errors, Godoc and test-first development; no default HTTP/ORM stack.
group: languages
kind: skill
---

# Go Conventions

## Skill summary

Go authoritative architecture, named DAOs, consumer-owned interfaces, declarative services, lifecycle ownership, errors, Godoc and test-first development; no default HTTP/ORM stack.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

## Sources and scope

This family consolidates the user's Go conventions and Atlas CONVENTIONS architecture. Atlas cmd/atlasd is evidence for thin CLI routing, explicit output streams, canonical help defaults and exact error tests, not authority for a help prescan, global configuration getter or mutable daemon internals. Older examples with those patterns are superseded.

Read shared ownership/testing first. The following sections are Go translations of those obligations, not a prescription to create unnecessary layers. Framework stack choices are confined to selected recipes. A lifecycle service does not imply Gin, GORM or PostgreSQL.

## Cadence authority

**Always test first:** write the decision-path test, observe the expected failure, implement the smallest unit, run targeted/package tests, then refactor green. Root installed convention §14.6 explicitly supersedes the old implementation-first Go loop. For feature flows add the relevant integration/end-to-end test; a tiny isolated fix need not acquire a whole stack. See `skills/languages/go/go-recipe-code-test-loop/SKILL.md`.

## 1. The universal shape: resolved model → DAO → service

Every meaningful application concern is deliberately separated into three roles:

```text
resolved model / runtime noun
    ← resolved output of a service
transient DAO
    → typed input/output at a real boundary
service
    → owns one workflow or one cohesive stateful capability
```

This is the mandatory Go architectural pattern, not a configuration-only exception. `Config`, `ConfigDAO`, and `ConfigSvc` are the canonical, smallest example:

```text
defaults + TOML + environment + flags
    → ConfigDAO (raw, source-shaped, transient)
        → ConfigSvc (parse, precedence, resolve, validate)
            → Config (resolved, runtime-safe noun)
```

Use the same design language elsewhere, but do not manufacture three symbols when a concern has no transient boundary or no independent workflow. The rule is **role separation**, not ceremonial naming:

- A **resolved model/runtime noun** holds stable, internally consistent state used after construction. It never stores raw/unresolved staging values or request-specific data.
- A **DAO** is a named transient params, result, request, response, configuration, row, or assembly shape. It has no business behavior except validation or mechanical mapping. It replaces positional arguments and untyped maps at real boundaries.
- A **service** owns a cohesive stateful capability or one cross-domain workflow. It has injected dependencies, no per-request state, and a precise orchestration entry point—normally `Execute(ctx, in)` or a more exact lifecycle/domain verb.

A type that simultaneously stores global runtime state, constructs unrelated dependencies, makes policy decisions, launches goroutines, implements transport handlers, and exposes services to every caller is a service locator/god object and must be decomposed.

## 2. Layer ownership and dependency direction

```text
cmd/<binary>
  → app application services / lifecycle facades
      → domain and support services
          → repositories, protocol, filesystem, network, subprocess adapters
```

- `cmd/` is wiring, I/O routing, help, and exit-code mapping only. It does not parse configuration, host business policy, or construct an ad hoc workflow.
- **Domain/support services** own one cohesive state or capability end-to-end: aliases, registry membership, telemetry projection, connection bookkeeping, log fan-out. They do not perform daemon lifecycle orchestration or implement RPC policy.
- **Application services** compose two or more domains or integrations: daemon bootstrap, storage/runtime assembly, startup-team creation, file-sync processing, RPC use cases. They delegate to domain owners; they do not reimplement them.
- **Adapters** translate a boundary: persistence, filesystem, transport, protocol, relay, subprocess, RPC stream. Adapters do not decide cross-domain policy.
- Lower layers must never import or reach back into a daemon/lifecycle object to acquire unrelated dependencies. Define a minimal lowercase interface at the consumer, inject it, and let a concrete provider satisfy it structurally.

## 3. Application services: one workflow, declarative control flow

An application service holds only injected collaborators and has no request-specific mutable fields. Its entry point reads as a table of contents:

```go
func (s *Service) Execute(ctx context.Context, in ExecuteDAO) (ExecuteResultDAO, error) {
    prepared, err := s.prepare(ctx, in)
    if err != nil {
        return ExecuteResultDAO{}, fmt.Errorf("preparing: %w", err)
    }
    result, err := s.apply(ctx, prepared)
    if err != nil {
        return ExecuteResultDAO{}, fmt.Errorf("applying: %w", err)
    }
    return s.publish(ctx, result)
}
```

Requirements:

1. The orchestration entry contains only ordering and `if err != nil` guards. No inline policy branching, persistence mechanics, protocol decoding, or goroutine bodies.
2. Each private step owns one decision or integration action, has a precise name, takes `context.Context` first when it can block/I/O, and wraps an error with its operation name.
3. A service owns one workflow or tightly coupled lifecycle. An unrelated second workflow is a second service.
4. A cross-domain atomicity/ordering boundary belongs to the application service, not a domain component.
5. Public lifecycle façades are thin delegates. A façade is not permitted to become a dependency container/service locator.

## 4. Runtime model and construction rule

Long-lived process state is represented by a resolved runtime model, generally unexported in `internal/app`:

```text
<Concern>DAO (construction input/result)
  → <Concern>Svc.Execute/build
      → <concern>Runtime (resolved, stable collaborators)
          → thin public façade / downstream services
```

Construction must not mutate a giant long-lived façade one field at a time. A builder/service returns a typed result DAO, which is converted once into a resolved runtime model after all required invariants succeed. A partially assembled runtime must not be published.

A runtime model may aggregate collaborators that share a lifecycle, but it must not be an exported bag every caller can mutate. Consumers receive only their minimal required collaborators/interfaces. Public fields exposing all internals are forbidden.

## Go constructor and lifecycle spelling

Read `skills/coding/naming-and-clarity/SKILL.md` first for the shared, language-neutral lifecycle distinction. This section owns the Go spelling and constructor threshold only.

The package-private constructor form `newX` remains idiomatic Go for a small single-object constructor:

```go
func newConn(fd int) *Conn { ... }   // fine — small, single-object constructor
```

Use `newX` for small single-object constructors; use `build…` when assembling or wiring a composite object graph. This is a Go spelling rule, not a language-independent lifecycle rule; the generic naming owner covers the shared construction-versus-execution distinction.

The complete Go lifecycle examples from the generic vocabulary remain here as Go-owned illustrations:

```go
overlay := buildOverlay(cfg)          // assemble the overlay object graph
strategy := buildNATStrategy(peer)    // assemble the NAT-traversal strategy

CreateSession(ctx, session)            // write an in-memory session to the store
session := BuildAndCreateSession(ctx, cfg)

startRelay(ctx)                        // spawns the relay loop; construction happened earlier
launchWatcher(ctx)                     // spawns a background watcher
```

## 5. DAOs and named boundaries

- A function with three or more non-obvious values besides `context.Context` accepts a named params DAO.
- Constructors with optional behavior use functional options; constructors with multiple required collaborators use a named DAO.
- Every struct literal uses named fields.
- `map[string]any`, `map[string]bool`, anonymous structs, and positional literals do not cross an architectural boundary. Use a named DAO with wire tags where applicable.
- DAO field names use ubiquitous language and mechanically match the canonical database/protocol/config name.
- Inbound DAOs validate themselves where validation is intrinsic to the shape. Service steps apply contextual/policy validation.
- Do not add an argument merely to document a call site and then discard it. Every parameter changes the contract, result, validation, emitted error, or operation; otherwise remove it.

## 6. Lifecycle, context, and goroutine ownership

Every background operation has one owner that starts it, documents its cancellation source, stops it, and waits for it. Lifecycle phases are explicit:

```text
bootstrap (fallible, no publication of partial runtime)
    → launch (supervised long-lived loops)
        → wait (lifecycle cancellation)
            → shutdown (cancel, stop owned integrations, wait)
```

- Context is first for I/O or blocking work; pure in-memory methods do not take it.
- Use the daemon lifecycle context for daemon-owned work and the connection context for connection-owned work.
- `defer cancel()` follows every locally created cancellable context immediately.
- A failed startup must leave no background goroutine or listener running. Prefer launching no loop until all fallible bootstrap work succeeds. If compatibility requires an earlier launch, the lifecycle service must own deterministic rollback/cleanup before returning the startup failure.
- No raw unsupervised goroutines. Use an owning `WaitGroup`/supervisor and make shutdown observable in tests.
- Do not use package-global mutable function seams as a shortcut for testing. Prefer injected interfaces/recorders. Any unavoidable test seam has real default behavior, `t.Cleanup` restoration, no parallel mutation, and race coverage.
- Lifecycle order is behavior. Name and test ordered boundaries whenever reordering changes visibility, readiness, resource ownership, or failure cleanup.

## 7. Domain/support services and policy

A domain/support component owns all state transitions, validation, persistence/peripheral work, and error translation for one concept. Callers tell it to act; they do not read its state and reproduce its rules.

Cross-cutting policies are named, owned steps. A policy must never be hidden in a long construction method. Examples include maintainer data-plane refusal, receive-directory selection, relay fallback, and self-only authorization. The policy owner documents:

- the input it decides;
- the invariant it protects;
- the allowed/denied outcomes;
- its error/sentinel contract; and
- test cases for each decision branch.

## 8. Errors and compatibility

- Each package owns known-condition sentinels in `errors.go` or a focused `<concern>_errors.go`.
- Return known failures as sentinels or typed errors that `Unwrap` to them. At each meaningful boundary wrap with `fmt.Errorf("operation: %w", err)`.
- Use `errors.Is` / `errors.As`; never branch by matching error strings.
- Never silently swallow an error. A deliberately best-effort failure must be logged with its reason and explicitly documented.
- Rendered error text at CLI, RPC, or other external boundaries is observable compatibility behavior. A change requires an explicit before/after string, rationale, `errors.Is` assertion, and exact rendering test. Never claim byte-identical rendering while changing it.

## 9. Interfaces, dependencies, and adapters

- The consumer defines the minimal lowercase interface containing only methods it calls.
- Constructors accept interfaces and return concrete implementations.
- No exported interface exists solely for a single production implementation.
- No globals or `init`-driven dependency graph. Constants and sentinel declarations are the limited exception.
- One integration has one adapter boundary and one configured shared request path; context/deadline, error classification, and resource closing occur there.

## 10. Readability, naming, documentation, imports

- A function has roughly 15 lines of logic or fewer, at most one nesting level, guard clauses first, and a named helper for each further concern.
- Use registries/interface dispatch rather than growing discriminator switches where handlers are independently extensible.
- One concept has one name across config, DAO, service, protocol, storage, and test.
- Every exported symbol has Godoc beginning with its exact name; package documentation describes the package purpose. Explain caller contracts and non-obvious why, not line-by-line implementation.
- Import groups are standard library, external, internal; all are alphabetized and `goimports` clean.

## 11. Test requirements

Tests prove boundaries and behavior—not just statements:

- one decision point per table row;
- named DAO construction at test call sites;
- sentinel assertions with `require.ErrorIs`/`errors.Is` and exact boundary rendering where required;
- deterministic fakes at consumer interfaces for orchestration order and failure cutoffs;
- lifecycle tests prove cancellation, wait completion, and failure rollback;
- `t.Parallel()` only without shared mutable state, temp global seams, process signals, or environment mutation;
- run targeted package tests and race tests, build/vet, relevant build tags, and report any unrelated full-suite baseline failure honestly.

## 12. Mandatory refactor procedure

Before a major refactor, the specification must provide:

1. a current ownership map identifying model, DAO, service, and adapter roles;
2. a target package/file map, including approved new files where role boundaries require them;
3. a migration map from current fields/functions to target owners;
4. typed DAO definitions with named-field examples;
5. dependency injection interfaces owned by consumers;
6. lifecycle/error/wire compatibility analysis;
7. a deterministic test matrix for success, each failure cutoff, cleanup, and ordering;
8. an incremental implementation order that keeps builds passing after each step.

A proposal that only extracts helpers from a god object but leaves ownership, mutation, and dependency access unchanged is not an architecture refactor and must be rejected.

## Component routing

- Core: go-build-domain-features, go-build-application-services, go-build-clients, go-build-lifecycle, go-test-lifecycle, go-test-orchestration, go-review, go-build-tcp-codec, go-auth-security.
- CLI/config: go-recipe-cli-configuration. Preserve Config → ConfigDAO → ConfigSvc, a single flag registry and config-only sanctioned pflag/viper; no parse-in-main or double parsing.
- HTTP: go-build-http-handlers, go-build-middleware, go-recipe-api-response-conventions, go-recipe-api-documentation when that API/stack is present.
- Optional stack recipes: go-build-workers / go-build-schedulers (asynq), go-build-workflow-orchestration (Temporal), go-build-event-handlers / go-build-partitioned-events (NATS), go-build-clickhouse-features, go-recipe-database-migrations (goose), go-build-tuis (Bubble Tea).
- Integration tests: go-test-domain-services, go-test-application-services, go-test-handlers, go-recipe-setup-dependencies-and-tests. Real stores are for persistence proof; go-test-orchestration uses recorders without those dependencies.
- Tooling: go-recipe-modules-and-imports, go-recipe-bootstrap-project-scaffolding, go-recipe-vscode-launch-configurations.

API envelope details have one owner: go-recipe-api-response-conventions. Exported symbol contracts must include caller-visible error/lifecycle behavior, not merely a restatement of the function name. Functional options are for optional behavior; multiple required dependencies use a named DAO. No provider-owned exported interface solely for one implementation.

