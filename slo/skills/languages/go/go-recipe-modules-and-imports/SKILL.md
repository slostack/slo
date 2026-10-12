---
name: go-recipe-modules-and-imports
description: "Go scoped recipe (GORM, Gin, asynq): The Go equivalent of PYTHONPATH / import resolution\
  \ \u2014 how go.mod's module path anchors every import, the internal/ visibility rule, breaking import\
  \ cycles with consumer-side interfaces, local vs remote module replacement (replace, go.work), vendoring,\
  \ and stdlib/external/internal import grouping via gofumpt/goimports."
when_to_use: Only for the named project stack and component. Use when setting up a new Go module, debugging
  import-path or "package not found" errors, wiring multi-module local development, resolving import cycles,
  deciding whether to vendor, or enforcing import grouping in review. A short reference skill.
group: languages
kind: skill
---

# Go Modules and Import Resolution

## Skill summary

- **Name:** `go-recipe-modules-and-imports`
- **Description:** The Go equivalent of `PYTHONPATH` / import resolution. Go has no
  search-path variable — the `module` path in `go.mod` is the single anchor from which
  every import path derives. This skill covers module paths, the `internal/` visibility
  rule, breaking import cycles, `replace` / `go.work` for local multi-module dev,
  vendoring, and stdlib/external/internal import grouping.
- **When to use:** Setting up a module, debugging import errors, wiring local
  multi-module development, resolving cycles, or enforcing import grouping.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Getting `package foo is not in std` / `cannot find module` — how does Go resolve this import?"
- "How do I point one repo's import at my local checkout of a dependency?"
- "Set up a Go workspace so I can edit two modules at once."
- "I have an import cycle between `order` and `payment` — how do I break it?"
- "Why can't my `cmd/` code import that package under `internal/`?"
- "How should imports be grouped and ordered in a Go file?"
- "Should this service vendor its dependencies?"

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

Python resolves imports at runtime by scanning `sys.path`, and `collin_collections`
forces the repo root onto that path via `PYTHONPATH` in every env file. **Go has no
equivalent.** There is no path variable to set, nothing to `loadenv`, and no
`ModuleNotFoundError` at test-collection time. Import resolution is fully static and
anchored by one line: the `module` directive in `go.mod`. Get that line right and every
import in the module derives from it mechanically.

Defer to `go-conventions` for naming, structure, and the package layout this
skill assumes; defer to `go-recipe-cli-configuration` for configuration layout and `go-conventions` for the standard `cmd/ internal/ pkg/`
folder rationale. This skill is only about *how import paths resolve and how modules
compose*.

---

### Section 1 — The module path is the anchor (the PYTHONPATH analog)

`go.mod` sits at the module root. Its `module` line names the module, and **every import
path inside the module is that name plus the directory path.** There is no `src.`
prefix, no `PYTHONPATH`, no per-environment path juggling.

```go.mod
// go.mod at the repository root
module github.com/trustingsocial/slo-atlas

go 1.23

require (
    github.com/gin-gonic/gin v1.10.0
    github.com/go-playground/validator/v10 v10.22.0
    gorm.io/gorm v1.25.12
    gorm.io/driver/postgres v1.5.9
    github.com/pressly/goose/v3 v3.22.0
    github.com/spf13/viper v1.19.0
    github.com/hibiken/asynq v0.25.0
    github.com/stretchr/testify v1.9.0
)
```

Given `module github.com/trustingsocial/slo-atlas`, the file
`internal/domain/user/service.go` is imported as:

```go
import "github.com/trustingsocial/slo-atlas/internal/domain/user"
```

The directory under the module root **is** the import path suffix. Rename a folder →
its import path changes. Move the module → change one line in `go.mod` and every import
follows. Contrast with the Python convention where a wrong `PYTHONPATH` value in one
`.env.*` file breaks collection with `No module named 'src'`. In Go the same class of
error is caught at compile time, not at test time, and the fix is always "correct the
`go.mod` module path or the import path," never "export a path variable."

```go
// Bad — relative-looking or invented import that doesn't derive from go.mod.
// Go has no relative imports; this does not compile.
import "internal/domain/user"
import "./domain/user"
import "slo-atlas/internal/domain/user" // missing the module-path prefix

// Good — full path = module path + directory.
import "github.com/trustingsocial/slo-atlas/internal/domain/user"
```

> **Rule of thumb for the Python muscle memory:** wherever you would have reached for
> `PYTHONPATH` or a `src.` prefix, in Go you do *nothing* — the module path already did
> the job. If an import "can't be found," the module path or the go.mod location is
> wrong, not a missing environment variable.

---

### Section 2 — The `internal/` visibility rule

Go enforces one hard visibility boundary at the directory level: **a package under an
`internal/` directory can only be imported by code rooted at `internal/`'s parent.** The
compiler rejects any import that crosses that boundary. This is the enforced version of
"private to this module" — stronger than Python's underscore-prefix convention, which is
advisory only.

```
github.com/trustingsocial/slo-atlas/
├── cmd/server/main.go        // may import internal/... (shares the root)
├── internal/
│   ├── domain/user/          // importable only within slo-atlas
│   └── config/               // importable only within slo-atlas
└── pkg/
    └── slo/                  // importable by ANY external module
```

- `cmd/server/main.go` and anything else under the module root **can** import
  `.../internal/domain/user`.
- A *different* module (`github.com/other/thing`) **cannot** import
  `.../slo-atlas/internal/...` — the build fails with
  `use of internal package ... not allowed`.
- Put genuinely reusable, externally-consumable code in `pkg/`. Everything else lives
  under `internal/` so the compiler guarantees it stays private.

```go
// Bad — external module reaching into another module's internal tree.
// Does not compile: "use of internal package not allowed".
import "github.com/trustingsocial/slo-atlas/internal/domain/user"

// Good — external consumers import from the exported pkg/ tree.
import "github.com/trustingsocial/slo-atlas/pkg/slo"
```

Default to `internal/`. Promote a package to `pkg/` only when another module genuinely
needs it — an over-eager `pkg/` surface is a maintenance liability, not a courtesy.

---

### Section 3 — Import cycles and how to break them

Go **forbids import cycles** at compile time: if package `order` imports `payment` and
`payment` imports `order`, the build fails with `import cycle not allowed`. Python
tolerates many cycles at runtime (until it doesn't); Go rejects them outright, so the
design pressure is felt immediately.

The idiomatic fix is the same as `go-conventions`: **define the
interface at the consumer.** The consumer declares the minimal interface it needs; the
provider depends on nothing. Dependency arrows now point one way.

```go
// Bad — mutual import, compiler rejects it.

// internal/domain/order/service.go
package order
import "github.com/trustingsocial/slo-atlas/internal/domain/payment"

func (s *Service) Checkout(ctx context.Context, id string) error {
    return payment.NewService().Charge(ctx, id) // order → payment
}

// internal/domain/payment/service.go
package payment
import "github.com/trustingsocial/slo-atlas/internal/domain/order" // payment → order — CYCLE

func (s *Service) Charge(ctx context.Context, id string) error {
    o, _ := order.Load(ctx, id) // needs order back — cycle
    ...
}
```

```go
// Good — order defines the tiny interface it consumes; payment implements it
// without importing order at all. Arrow points order → payment only.

// internal/domain/order/service.go
package order

// charger is the consumer-local interface: order names exactly what it needs.
type charger interface {
    Charge(ctx context.Context, orderID string, amount int) error
}

type Service struct {
    charger charger
}

func NewService(charger charger) *Service {
    return &Service{charger: charger}
}

func (s *Service) Checkout(ctx context.Context, id string) error {
    return s.charger.Charge(ctx, id, s.total(id))
}

// internal/domain/payment/service.go — imports nothing from order.
package payment

func (s *Service) Charge(ctx context.Context, orderID string, amount int) error {
    // payment.Service structurally satisfies order.charger; no import needed.
    ...
}
```

Other cycle-breakers, in order of preference:

1. **Consumer-side interface** (above) — the default.
2. **Extract shared types** into a third leaf package (e.g. a `shared` or `types`
   package that both import but that imports neither).
3. **Merge the two packages** if they are genuinely one concept split by accident —
   ubiquitous-language pressure often reveals this.

Never break a cycle by moving logic into a giant `common` grab-bag; that trades a cycle
for a god-package.

---

### Section 4 — Local vs remote modules: `replace` and `go.work`

When you need to develop against a *local* checkout of a dependency instead of the
published version — the closest analog to pointing `PYTHONPATH` at a sibling repo — Go
gives you two mechanisms.

#### 4.1 `replace` directive (per-module, committed-risk)

`replace` in `go.mod` redirects a module path to a local directory or a fork.

```go.mod
module github.com/trustingsocial/slo-atlas

go 1.23

require github.com/trustingsocial/slo-core v1.4.0

// Point the dependency at a local checkout instead of the published tag.
replace github.com/trustingsocial/slo-core => ../slo-core
```

- Use for a **temporary local override** or a permanent fork redirect.
- **A `replace` pointing at a relative local path must not be committed to a shared
  branch** — it breaks the build on every machine that lacks that sibling directory.
  Committing `=> ../slo-core` is the Go equivalent of committing `PYTHONPATH=<project-root>`.
- Committing a `replace` to a *forked, tagged* module (`=> github.com/you/fork v1.4.1`)
  is fine and intentional.

#### 4.2 `go.work` — Go workspaces (the right tool for multi-module dev)

For editing several modules together on your machine, prefer a **workspace**. `go.work`
lives *outside* any module (typically one level up), is **git-ignored**, and never
ships. It transparently wires local modules together without touching any `go.mod`.

```go.work
// ~/Code/go.work  — sits above both module directories, git-ignored
go 1.23

use (
    ./slo-atlas
    ./slo-core
)
```

```
~/Code/
├── go.work            // git-ignored; only on your machine
├── slo-atlas/         // module github.com/trustingsocial/slo-atlas
│   └── go.mod
└── slo-core/          // module github.com/trustingsocial/slo-core
    └── go.mod
```

With this workspace active, `slo-atlas` resolves `github.com/trustingsocial/slo-core` to
`../slo-core` automatically — no `replace`, no `go.mod` edits, nothing to accidentally
commit. Manage it with `go work init`, `go work use ./newmod`, `go work sync`.

**Decision:** `go.work` for local multi-module development (default). `replace` only for
a committed fork redirect or a deliberate, short-lived local override you will delete
before pushing. Add `go.work` and `go.work.sum` to `.gitignore`.

---

### Section 5 — Vendoring

`go mod vendor` copies every dependency's source into a top-level `vendor/` directory,
and `go build` prefers it automatically when present. There is no Python equivalent —
this is closer to committing a fully-pinned virtualenv.

```bash
go mod vendor          # populate ./vendor from go.mod + go.sum
go build ./...         # uses ./vendor automatically when it exists
go build -mod=mod ./...# bypass vendor, resolve from the module cache instead
```

- **Vendor when** builds must run with no network access (air-gapped CI, hermetic build
  systems) or you need a byte-for-byte reproducible dependency tree in the repo.
- **Do not vendor by default.** The module cache + `go.sum` already give reproducible,
  checksum-verified builds; `vendor/` inflates the repo and adds review noise on every
  dependency bump.
- If you vendor, **commit `vendor/` and keep it in sync** — a stale `vendor/` that
  disagrees with `go.mod` fails the build (`go mod verify` / `go mod vendor` to fix).

---

### Section 6 — Import grouping and ordering

Go imports are grouped into blocks separated by a blank line, and within each block
sorted alphabetically. The convention here is three groups: **stdlib**, **external**,
**internal (this module)**. Enforce it with tooling — do not hand-sort.

```go
// Bad — one undifferentiated block, unsorted, stdlib mixed with deps.
import (
    "github.com/gin-gonic/gin"
    "context"
    "github.com/trustingsocial/slo-atlas/internal/domain/user"
    "fmt"
    "gorm.io/gorm"
)

// Good — three groups: stdlib, external, internal; each alphabetized.
import (
    "context"
    "fmt"

    "github.com/gin-gonic/gin"
    "gorm.io/gorm"

    "github.com/trustingsocial/slo-atlas/internal/domain/user"
)
```

Tooling — run one of these on every save / in CI; they are deterministic:

```bash
# goimports: fixes grouping + adds/removes imports. -local pins the internal group.
goimports -w -local github.com/trustingsocial/slo-atlas ./...

# gofumpt: stricter gofmt superset; enforces the same grouping.
gofumpt -w ./...
```

Configure the `-local` prefix (goimports) or `local-prefixes` (golangci-lint's `gci` /
`goimports` linters) to your module path so the internal group is split out correctly.
A file that isn't `goimports`/`gofumpt`-clean is a review blocker — never argue import
order by hand.

---

## Checklist

Run through before merging anything that touches modules or imports.

- [ ] `go.mod`'s `module` line is the true, stable module path; every import derives
      from it (no relative imports, no `src.`-style prefixes).
- [ ] Private code lives under `internal/`; only genuinely external-facing code is in
      `pkg/`. No cross-module reach into another module's `internal/`.
- [ ] No import cycles. Where two packages needed each other, the cycle was broken with
      a **consumer-side interface**, not a `common` grab-bag.
- [ ] No `replace => ../local/path` committed to a shared branch. Local multi-module
      work uses a **git-ignored `go.work`** instead.
- [ ] `go.work` / `go.work.sum` are git-ignored.
- [ ] Vendoring is deliberate: `vendor/` is present *only* if required, committed, and
      in sync with `go.mod` (`go mod verify` clean).
- [ ] Imports are grouped stdlib / external / internal and the file is
      `goimports -local <module>` / `gofumpt` clean.
- [ ] `go build ./...` and `go vet ./...` pass — Go catches resolution errors at compile
      time, so a green build is the proof (no test-collection surprises).
