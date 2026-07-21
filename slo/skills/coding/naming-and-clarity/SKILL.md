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

Use one verb per lifecycle stage, consistently. The verb tells the reader whether the call allocates memory, touches a database, or spawns a goroutine.

| Verb | Meaning | Persists? | Spawns goroutines? |
|---|---|---|---|
| `Build…` / `build…` | Instantiate and assemble an **in-memory** object or wiring | No | No |
| `Create…` / `Save…` | **Persist** an already-instantiated object | Yes | No |
| `BuildAndCreate…` | Build then persist in one call | Yes | No |
| `start…` / `launch…` | Spawn goroutines or long-running loops | — | Yes |

### `Build…` / `build…`

Assembles and wires an in-memory object or composite. **No persistence, no goroutines.** Domain-specific builds keep the noun so the name stays concrete:

```go
overlay := buildOverlay(cfg)          // assemble the overlay object graph
strategy := buildNATStrategy(peer)    // assemble the NAT-traversal strategy
```

`build` is for assembling or wiring a **composite** — not for every small constructor.

### `Create…` / `Save…`

Persist an object that already exists in memory. This is the verb that hits the store.

```go
CreateSession(ctx, session)   // write an in-memory session to the store
```

### `BuildAndCreate…`

Build then persist in a single call, when callers routinely need both.

```go
session := BuildAndCreateSession(ctx, cfg)
```

### `start…` / `launch…`

Spawn goroutines or long-running loops. This is **not** construction — do not fold a `start`/`launch` into a `build`. Leave existing `start…` / `launch…` names as they are.

```go
startRelay(ctx)     // spawns the relay loop; construction happened earlier
launchWatcher(ctx)  // spawns a background watcher
```

### Idiomatic Go `newX`

The package-private constructor form `newX` remains idiomatic Go for small constructors:

```go
func newConn(fd int) *Conn { ... }   // fine — small, single-object constructor
```

Use `newX` for small single-object constructors; use `build…` when you are assembling or wiring a composite object graph.

---

## 3. Producer/consumer pairs vs. same-direction readers

Use the **`publish…` / `consume…`** pair **only** for a genuine producer↔consumer relationship: one side *writes/produces* items onto a boundary (a channel, queue, or socket), the other side *reads/consumes* them. The matched vocabulary then makes the opposite roles obvious.

```go
// producer — writes jobs onto the queue
func (p *Dispatcher) publishJob(ctx context.Context, j Job) { ... }

// consumer — reads jobs off the queue
func (w *Worker) consumeJob(ctx context.Context) (Job, error) { ... }
```

**Do not force `publish`/`consume` onto two functions that do the same thing in the same direction.** Two goroutines that both *read* inbound frames are not a producer/consumer pair — name each for what it actually reads and at what scope:

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

This is the same standard captured in the `method-docstrings` skill — see `skills/coding/method-docstrings/SKILL.md` for the full format and language-specific examples. A good name plus a rich doc comment means the reader never has to reverse-engineer the body.

---

## 5. Clarity over cleverness (the tie-breaker)

When any naming or documentation decision is genuinely a toss-up, choose the option that is clearest to a reader who has never seen the code. This principle overrides brevity, symmetry, and idiom. If a convention here ever conflicts with clarity in a specific case, clarity wins — and note the exception in a comment.

---

## Quick checklist

- [ ] Can a reader predict what the function does from its name alone?
- [ ] No clever/jargon verbs (`demux`, `pump`, `wire`) — plain verb for the real operation?
- [ ] `build…` = in-memory assembly, no persistence, no goroutines?
- [ ] `Create…` / `Save…` = persistence of an already-built object?
- [ ] `BuildAndCreate…` = build then persist?
- [ ] `start…` / `launch…` left as-is for goroutine/loop spawning (not folded into `build`)?
- [ ] `newX` used only for small single-object constructors?
- [ ] Producer/consumer pair across a boundary named `publish…` / `consume…` with a shared noun?
- [ ] Rich doc comment states WHAT, WHO, and WHEN?
- [ ] When in doubt, did clarity win over cleverness?
