---
name: go-recipe-cli-configuration
description: "The domain/DAO/service structure for Go binary configuration \u2014 a Cli struct in cmd/\
  \ that owns display and routing only, a single config.go holding domain (Config) \u2192 DAO (ConfigDAO)\
  \ \u2192 service (ConfigSvc) in that order, one pflag flag registry, viper-sanctioned layered resolution\
  \ (flags > env > file > defaults), and no parsing or meta-flag pre-scans in main. Non-negotiable."
when_to_use: Use whenever writing, reviewing, or refactoring flag parsing, environment-variable handling,
  config-file loading, or CLI argument routing in any Go binary. A violation (parsing in main, double
  parsing, raw staging fields on the domain, hand-rolled merge plumbing) is a blocker, not a suggestion.
  Supersedes the configuration sections of build-go-cli-apps, go-application-structure, and go-switch-environments-and-run-tests.
group: languages
kind: skill
---

# Go CLI Configuration — Domain, DAO, Service in One File

## Skill summary

- **Name:** `go-recipe-cli-configuration`
- **Description:** Configuration is a first-class domain. It follows the
  domain/DAO/service split like everything else, with one deliberate deviation:
  all three sections live in a single `config.go` per binary, ordered domain →
  DAO → service, so the file reads as the pipeline itself.
- **When to use:** writing, reviewing, or refactoring any flag/env/config-file
  handling in a Go binary. A violation is a blocker.
- **Supersedes:** the configuration sections of `build-go-cli-apps` (§4 root
  command + viper wiring), `go-application-structure` (config package layout),
  and `go-switch-environments-and-run-tests` (APP_ENV + viper env files). Those
  skills remain authoritative for their other concerns (command trees for
  multi-subcommand tools, package layout, build tags).
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Refactor our main.go flag parsing into the configuration domain structure."
- "Review this config loader against conventions."
- "Add a new flag to atlasd — where does it go?"
- "Why is this binary parsing -config in main before calling LoadConfig?"

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

These rules extend `go-conventions` (the root authority) and are
pinned in the repo-level `CONVENTIONS.md` §1.4 where present. Project contracts specialize these rules through explicit approved decisions;
locality alone does not waive a shared obligation.

The convention exists to kill one specific failure mode: **configuration logic
duplicated across `main.go` and the config package.** The canonical symptom is a
`parseArgs`-style function in `cmd/` that pre-extracts a "meta-flag" (like
`-config`) and forwards the remaining args to a second parser inside the config
package. Every argument is then parsed twice, validation is split across two
layers, and neither layer can see the whole picture.

---

## Section 1 — The three layers of configuration

### 1.1 Domain — the persisted noun

The resolved, validated configuration is a **persisted noun**: `Config`,
`RelayConfig`. It is what the daemon/server is constructed from.

- Holds **only resolved values**: parsed `time.Duration`s, native `[]string`
  slices, final booleans.
- **No raw staging fields.** `syncIntervalRaw string` on the domain is a
  violation — raw strings belong to the DAO; by the time a domain object
  exists, every value is parsed.
- Validation lives on the domain (`Validate()`), hand-rolled, returning package
  sentinels (`go-conventions`).

```go
// Config is the resolved, validated runtime configuration. The Daemon is
// constructed from this. No raw or unresolved fields live here.
type Config struct {
	ListenAddr        string
	DataDir           string
	LogLevel          string
	SyncInterval      time.Duration // parsed, never a raw string
	MaintainerAddrs   []string      // native slice, never a CSV string
	AdvertiseViaRelay bool          // final value, never a *bool
	// ...
}
```

### 1.2 DAO — the transient input shape

`ConfigDAO` is the **transient object**: the unresolved input that every source
(flags, env, config file) decodes into before merging. It is never persisted
and never handed to the daemon.

- Durations are **raw strings** here (`"10s"`); resolution happens in the
  service.
- Booleans are **tri-state `*bool`** so "absent from this source" is
  distinguishable from "explicitly false". This is what replaces `fs.Visit`-
  based set-detection and `overrideBoolWhenSet` helpers: set-ness travels in
  the data, not in a side-channel map. A TOML `false` must never clobber a flag
  `true` and vice versa.
- `ConfigDAO` doubles as the **config-file schema** (one serialization
  contract: `toml:"..."` tags). If a second file format ever appears, split the
  schema out — do not stack tag families on the DAO.
- Strict unknown-key rejection in the file decode path is preserved (misspelled
  keys are an error, not silently ignored).

```go
// ConfigDAO is the transient, unresolved configuration input. Every source
// (flags, env, TOML) decodes into this shape; ConfigSvc merges and resolves it
// into a Config. Never persisted, never handed to the Daemon.
type ConfigDAO struct {
	ConfigPath        string   // consumed by the svc to locate the file
	SyncInterval      string   // raw "10s" — resolved by the svc
	MaintainerAddrs   []string
	AdvertiseViaRelay *bool    // nil = not set by this source
	// ...
}
```

### 1.3 Service — one registry, one parse, one pipeline

`ConfigSvc` operates on the domain and the DAO. It owns:

- **The single pflag flag registry for the binary** — the only place flag
  names, defaults, and help text are declared. (`pflag` is the GNU-style
  drop-in for stdlib `flag`: `--flag`, shorthand, interspersed positionals, and
  a `Changed` field per flag that carries explicit-set detection.)
- **The whole load pipeline**: parse args → DAO, decode file → DAO, read env →
  DAO, merge DAOs lowest→highest precedence, resolve DAO → domain, validate.
- **Package-level convenience entry**: `LoadConfig(args []string)` delegating
  to `GetConfigSvc().Load(args)`. This is the **only** config function `cmd/`
  may call.

```go
// LoadConfig is the package-level convenience entry point and the only
// configuration function cmd/ may call.
func LoadConfig(args []string) (Config, error) {
	return GetConfigSvc().Load(args)
}

// Load runs the full pipeline: parse → overlay sources → resolve → validate.
func (svc *ConfigSvc) Load(args []string) (Config, error) {
	fs := svc.newFlagSet()
	if err := fs.Parse(args); err != nil {
		return Config{}, svc.translateParseError(err)
	}
	flagDAO := svc.daoFromFlags(fs)
	fileDAO, err := svc.daoFromTOML(flagDAO.ConfigPath)
	if err != nil {
		return Config{}, err
	}
	envDAO := svc.daoFromEnv()
	merged := svc.merge(svc.daoFromDefaults(), fileDAO, flagDAO, envDAO)
	//                  lowest precedence ----------------> highest
	return svc.resolve(merged)
}
```

The pipeline is a **table of contents** (`go-conventions`):
each step is a named private method, the only `if` is an `err != nil` guard.

### 1.4 Precedence is fixed

**explicit flags > environment > config file > defaults.** The merge order in
`Load` encodes it; no source may jump the queue. Explicit-set detection (flag
`Changed`, tri-state DAO pointers) is what lets an unset flag fall through to
env, an unset env var fall through to the file, and an absent file key fall
through to the default.

---

## Section 2 — The `Cli` struct in `cmd/`

`cmd/<bin>/main.go` owns **display and routing only** — the concrete form of
the "wiring only" rule.

```go
// Cli owns everything user-facing: display output and routing to domain
// services. It holds no configuration state and no parsing logic.
type Cli struct {
	Out io.Writer
	Err io.Writer
}

// Construction is local, never a package-global mutable dependency graph.
// Config resolution returns a typed result including help/version intent;
// the Cli routes display without scanning args a second time.
// The composition root injects a configResolver and lifecycle consumer into Cli.
// Run calls resolver.Resolve(args), then named display or lifecycle steps.
// Keep the exact interfaces/DAO names consistent with the project's config owner.

```

Rules:

- **No flag parsing in `cmd/`.** `main.go` never imports `flag`/`pflag` for its
  own parsing, never pre-extracts a meta-flag, passes the original argument slice once to ConfigSvc; it never forwards a pre-parsed remainder.
- **Help routing may stay in `Cli`** (it is display routing), but the usage
  text should be sourced from the service's flag registry
  (`fs.FlagUsages()`) from the injected ConfigSvc result so
  the help screen cannot drift from the real defaults.
- **One place owns exit policy**: `Cli` maps sentinel errors to exit codes;
  `os.Exit` appears only in `main`.
- Tests construct `&Cli{Out: &buf, Err: &buf}` — no writer threading through
  free functions.

---

## Section 3 — Library sanction: pflag and viper

- `github.com/spf13/pflag` — sanctioned for the flag registry. Preferred over
  stdlib `flag` because of GNU syntax (`--flag`), shorthand support,
  interspersed positionals, native `StringSlice`/`Duration` types, and the
  `Changed` field.
- `github.com/spf13/viper` — sanctioned **exclusively for configuration
  resolution** (`BindPFlags`, `SetEnvPrefix` + `AutomaticEnv` +
  `EnvKeyReplacer`, `ReadInConfig`, `SetDefault`, `Get*` accessors). Its
  native precedence chain (explicit flags > env > file > defaults) is exactly
  §1.4, so it replaces hand-rolled `applyEnvOverrides`/`overrideNonEmpty`
  plumbing.
- **Not sanctioned:** cobra (command trees), viper for anything other than
  config, any other spf13 ecosystem package. Multi-subcommand tools follow
  `build-go-cli-apps`; single-command daemons follow this skill.
- Two honest gotchas when viper is in play: `ReadInConfig` silently ignores
  unknown file keys (keep a strict decode pass if unknown-key rejection is a
  contract), and `GetBool` accepts `"1"`/`"yes"`/`"on"` in addition to
  `"true"` — decide deliberately whether the looser env parsing is acceptable.

---

## Section 4 — Violations (blockers)

1. **Flag parsing in `main.go` / `cmd/`** — including any `parseArgs`-style
   pre-extraction of a "meta-flag". → Delete it; the service's registry parses
   every argument exactly once.
2. **Double parsing** — args parsed in `cmd/` and re-parsed in the config
   package. → One registry, one `Parse` call, in the service.
3. **Raw staging fields on the domain** (`syncIntervalRaw string`). → Move to
   `ConfigDAO`; the domain holds resolved values only.
4. **Set-ness side-channels** — `fs.Visit` maps, `overrideBoolWhenSet`,
   `overrideNonEmpty` merge helpers. → Tri-state `*bool` on the DAO, or viper's
   `Changed`-aware precedence.
5. **CSV strings crossing the domain boundary** — `Bootstrap string` that
   callers must comma-split. → `[]string` on the domain; splitting happens once
   in the service (or natively via `pflag.StringSlice`).
6. **Usage text hand-maintained away from the registry** — a help heredoc that
   can drift from the real flags/defaults. → Source from the flag registry or
   from `GetDefaultConfig()`.
7. **`os.Exit` scattered outside `main`** — the `Cli` returns codes; `main`
   owns the exit.
8. **Stack leakage** — introducing cobra or non-config viper usage under the
   cover of this skill. → Blocker; see Section 3.

---

## Section 5 — Testing

- **Service tests** invoke `Load([]string{...})` with args written like real
  command lines (`"-config", path, "-role", "maintainer"`); precedence cases
  are table-driven (flag-beats-env-beats-file-beats-default), sentinels
  asserted with `require.ErrorIs`, env cases use `t.Setenv` (no `t.Parallel()`
  on those).
- **DAO merge tests** cover tri-state boolean behavior explicitly: file-false
  vs flag-true, file-true vs flag-absent, both-absent.
- **Cli tests** construct `&Cli{Out: &buf, Err: &buf}`, assert stdout/stderr
  separation, exit codes, and that `-h/-help/--help` never touches stderr.
- **File decode tests** cover: missing file → sentinel, malformed file →
  sentinel, unknown keys → sentinel.
- Follow `go-recipe-code-test-loop` cadence and `go-test-domain-services` discipline;
  configuration is pure in-memory, so no `context.Context` and no DB harness.

---

## Checklist — before merging configuration work

- [ ] `cmd/<bin>/main.go` contains a `Cli{Out, Err}` struct, routing, display,
      and exit-code mapping — and zero flag parsing.
- [ ] One `config.go` per binary reads domain → DAO → service, top to bottom.
- [ ] `Config` (domain) holds resolved values only; no raw staging fields.
- [ ] `ConfigDAO` uses raw strings for durations and tri-state `*bool` for
      booleans; it is the single file-schema contract.
- [ ] `ConfigSvc` owns the single pflag registry; `LoadConfig(args)` is the
      only entry `cmd/` calls.
- [ ] Precedence is flags > env > file > defaults, encoded in one merge.
- [ ] Unknown config-file keys are rejected with a sentinel, not ignored.
- [ ] Usage text is sourced from the registry or `GetDefaultConfig()`.
- [ ] Tests are table-driven, written like real command lines, and cover every
      decision point including tri-state boolean merges.
