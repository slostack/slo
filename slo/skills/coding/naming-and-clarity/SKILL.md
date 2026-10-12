---
name: naming-and-clarity
description: Explicit self-describing names and a Build/Create/BuildAndCreate + publish/consume lifecycle verb vocabulary. Clarity over cleverness.
when_to_use: Apply whenever naming a function, method, or identifier — especially constructors, lifecycle helpers, and paired producer/consumer readers across a boundary.
group: coding
kind: skill
source_prompt: naming-and-clarity.md
---

# Naming & Clarity

## Skill summary

- **Name:** `naming-and-clarity`
- **Description:** Explicit self-describing names and a Build/Create/BuildAndCreate + publish/consume lifecycle verb vocabulary. Clarity over cleverness.
- **When to use:** Apply whenever naming a function, method, or identifier — especially constructors, lifecycle helpers, and paired producer/consumer readers across a boundary.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `naming-and-clarity.md`

## Examples

The snippets in this skill are illustrative examples, not copied production code; they demonstrate naming distinctions without imposing a language or framework.

- The user asks you to name a new constructor, worker loop, or producer/consumer pair.
- You are reviewing a diff and a function name reads clever rather than descriptive.
- You need to decide between `build`, `create`, `start`, or `new` for a new helper.

## Guidance

**Clarity over cleverness is the overriding tie-breaker.** Whenever two names are in tension, pick the one a new reader understands without context. A clever name that saves a few characters costs every future reader a lookup.

---

## 1. Explicit, self-describing names

Name a function or identifier for **exactly what it does**. The name is the first and most-read piece of documentation. Ban opaque, cutesy, or "clever" verbs — they force the reader to open the body to learn what the name should have told them.

Real examples that were rejected and fixed:

| Rejected (too clever) | Fixed (self-describing) | Why |
|---|---|---|
| `pumpRelayDataFrames` | `readSessionRelayData` | "pump" hides that it reads one session's inbound relay-data frames and delivers them to that session |
| `runRelayDemux` | `routeRelayFrames` | "demux"/"run" hide that it reads every inbound frame and routes each to the right session |
| `wireOverlay` | `buildOverlay` | "wire" as a verb is jargon; the function builds the overlay |

Banned as verbs: **`demux`, `pump`, `wire`** (and anything in the same clever-jargon family). If you catch yourself reaching for a metaphor, use the plain verb for the actual operation instead.

Rule of thumb: if a colleague cannot predict what the function does from its name alone, rename it.

---

## 2. Constructor / lifecycle verb vocabulary

Use one verb per lifecycle stage, consistently. The verb should reveal whether the call assembles an in-memory value, persists an existing value, or begins background execution/concurrency. The exact spelling is language-specific; the ownership distinction is shared.

| Verb family | Meaning | Persistence | Background execution |
|---|---|---|---|
| `build…` / language-equivalent | Assemble an **in-memory** object or composite wiring | No | No |
| `create…` / `save…` | Persist an already-instantiated object | Yes | No |
| `buildAndCreate…`-equivalent | Assemble then persist in one operation | Yes | No |
| `start…` / `launch…` | Begin a long-running task, worker, watcher, or other background activity | — | Yes |

`build` is for assembling or wiring a **composite**, not for every small constructor. `start` and `launch` describe execution, not construction. A language owner may define idiomatic spellings and concurrency primitives; this generic rule does not prescribe a runtime or a keyword.

### `Build…` / `build…`

The shared lifecycle distinction is expressed with language-appropriate spellings; this heading preserves the established vocabulary without making Go syntax universal. The same ownership distinction can be expressed in each supported language:

```python
# Python: assembly and persistence are separate operations.
overlay = build_overlay(config)                 # in memory; no I/O or task
session = build_and_create_session(config)      # assembly plus persistence
start_watcher(session)                          # begins background execution
```

```go
// Go: the concrete constructor spelling belongs to Go guidance.
overlay := buildOverlay(config)                 // in memory; no persistence
session := createSession(ctx, overlay)          // persists an existing value
startWatcher(ctx, session)                       // begins supervised concurrency
```

```typescript
// TypeScript: the names communicate the boundary even when the calls are async.
const overlay = buildOverlay(config)             // in memory; no I/O or task
const session = await createSession(overlay)     // persists an existing value
launchWatcher(session, abortSignal)              // begins background execution
```

A small-language-specific constructor convention belongs in that language's owner. For example, Go's package-private constructor spelling and Go lifecycle illustrations are documented in `skills/languages/go/go-conventions/SKILL.md`; they are not universal naming rules.

### `Create…` / `Save…`

Use `create` or `save` when an already-assembled value crosses a persistence boundary. The exact verb and casing belong to the language and project owner; the generic distinction is that persistence is the observable effect.

```python
save_session(session)  # persists an existing value; it does not assemble one
```

### `BuildAndCreate…`

Use a language-equivalent combined name only when callers routinely need assembly and persistence as one operation. Keep the two effects visible in the contract and do not hide background execution in the combined operation.

```typescript
const session = await buildAndCreateSession(config) // illustrative combined operation
```

### `start…` / `launch…`

Use `start` or `launch` for beginning long-running or concurrent work after construction or persistence. The lifecycle owner must document cancellation, cleanup, and waiting; construction names must not imply that work has started.

```go
startWatcher(ctx, session) // starts supervised background work
```

---

## 3. Producer/consumer pairs vs. same-direction readers

Use the **`publish…` / `consume…`** pair **only** for a genuine producer↔consumer relationship: one side *writes/produces* items onto a boundary (a channel, queue, or socket), the other side *reads/consumes* them. The matched vocabulary then makes the opposite roles obvious.

```go
// producer — writes jobs onto the queue
func (p *Dispatcher) publishJob(ctx context.Context, j Job) { ... }

// consumer — reads jobs off the queue
func (w *Worker) consumeJob(ctx context.Context) (Job, error) { ... }
```

**Do not force `publish`/`consume` onto two functions that do the same thing in the same direction.** Two concurrent readers that both *read* inbound frames are not a producer/consumer pair — name each for what it actually reads and at what scope:

```go
// caller: reads ONE session's inbound relay-data frames, delivers to that session's read channel
func readSessionRelayData(ctx context.Context, conn *Conn, sessionID uint64, readCh chan<- []byte) { ... }

// callee: reads ALL inbound frames on a registration, routes each to the right session (+ control frames)
func (d *Daemon) routeRelayFrames(ctx context.Context, regConn *Conn, relayAddr string) error { ... }
```

Naming these `publishRelayDataFrames` / `consumeRelayDataFrames` was a real mistake: both are inbound readers, so the publish/consume labels implied a producer/consumer split that does not exist and hid the true difference — one session vs. all sessions, data-only vs. all frame types. Name for the operation and its scope, not for a symmetry that isn't there.

---

## 4. Rich documentation comments

Clarity does not stop at the name. Every non-trivial function carries a documentation comment explaining:

- **WHAT** it does,
- **WHO** calls it,
- **WHEN** in the flow it runs.

This pairs with the applicable language documentation owner: Python uses `skills/languages/python/method-docstrings/SKILL.md`, Go uses the selected Go Godoc conventions, and TypeScript uses the selected TypeScript JSDoc conventions. This generic skill owns the WHAT/WHO/WHEN intent; language roots own concrete comment syntax and format. A good name plus a rich doc comment means the reader never has to reverse-engineer the body.

---

## 5. Clarity over cleverness (the tie-breaker)

When any naming or documentation decision is genuinely a toss-up, choose the option that is clearest to a reader who has never seen the code. This principle overrides brevity, symmetry, and idiom. If a convention here ever conflicts with clarity in a specific case, clarity wins — and note the exception in a comment.

---

## Quick checklist

- [ ] Can a reader predict what the function does from its name alone?
- [ ] No clever/jargon verbs (`demux`, `pump`, `wire`) — plain verb for the real operation?
- [ ] `build…` = in-memory assembly, no persistence, no background execution?
- [ ] `Create…` / `Save…` = persistence of an already-built object?
- [ ] `BuildAndCreate…` = build then persist?
- [ ] `start…` / `launch…` left as-is for background-task/loop spawning (not folded into `build`)?
- [ ] Does any language-specific constructor spelling follow the applicable language owner rather than this generic skill?
- [ ] Producer/consumer pair across a boundary named `publish…` / `consume…` with a shared noun?
- [ ] Rich doc comment states WHAT, WHO, and WHEN?
- [ ] When in doubt, did clarity win over cleverness?
