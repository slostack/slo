---
name: go-build-partitioned-events
description: "Scalable event distribution in Go via consistent hashing \u2014 partition events across\
  \ N consumer instances by a partition key with minimal reshuffling on scale in/out, map a key to its\
  \ owning worker, and wire the ring into NATS JetStream handlers. The Go analog of the Python uhashring\
  \ partition_config."
when_to_use: Use when a single event stream must be sharded across many worker instances so all events
  for the same entity land on the same worker (ordering, cache locality, lock-free processing), and you
  need stable ownership as workers join and leave. Pairs with build-go-event-handlers.
group: languages
kind: skill
---

# Build Go Partitioned Events

## Skill summary

- **Name:** `go-build-partitioned-events`
- **Description:** Scalable event distribution in Go via consistent hashing —
  partition events across N consumer instances by a partition key with minimal
  reshuffling on scale in/out, map a key to its owning worker, and compose the ring
  with NATS JetStream event handlers. The Go analog of the Python `uhashring`
  `partition_config.py`.
- **When to use:** Use when one event stream must be sharded across many worker
  instances so all events for the same entity land on the same worker (ordering,
  cache locality, lock-free processing), with stable ownership as workers join and
  leave.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Shard our system-events stream across 8 workers so events for the same account
  always hit the same worker."
- "Add a consistent-hash ring in Go so we can scale workers without reshuffling
  everything."
- "How do I map an event's partition key to the worker that owns it?"
- "A worker crashed — how do I make sure its keys move to other workers with minimal
  disruption?"
- "Wire consistent hashing into our NATS JetStream consumers."
- "Port our Python `partition_config.py` (uhashring) to Go."
- "Why is every worker processing every event, and how do I fix ownership?"

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

> **Read first:** this skill assumes the NATS JetStream handler conventions in
> `go-build-event-handlers`. Partitioning is a routing layer that sits *on top of*
> those handlers — it decides *which worker* runs a handler, not *what* the handler
> does. Defer to `go-conventions` for naming, godoc, declarative function
> structure, error wrapping, and testing rules; this skill does not restate them.

### 1 — What partitioning solves, and the Go idiom for it

The Python stack builds a `partition_config.py` that declares a fixed `continuum`
of worker nodes and wraps them in a `uhashring.HashRing` keyed with murmur3. Events
are routed to a node by hashing a partition key. The goal is **stable ownership**:
all events for a given entity (an account, a mapped system, a tenant) are handled by
one and only one worker, and the mapping barely changes when workers are added or
removed.

Go has no `uhashring`. The idiomatic equivalents, in order of preference:

1. **`github.com/buraksezer/consistent`** — a maintained consistent-hash library
   with bounded loads (Google's "consistent hashing with bounded loads"). Use this
   by default. It gives even distribution *and* a cap on how much any one member can
   own.
2. **A hand-rolled hash ring** — a sorted slice of virtual-node hashes over a
   `[]byte` hash (`xxhash`/`fnv`/`crc32`). Use only when you need behaviour the
   library doesn't offer, and document why.

Both are shown below. The principle that must survive the translation:

- **Consistent hashing, not modulo.** `hash(key) % N` reshuffles almost every key
  when `N` changes. A ring with virtual nodes moves only `~1/N` of keys when a node
  joins or leaves. This is the entire point — never regress to modulo.
- **Virtual nodes (replicas)** smooth out distribution. One physical worker maps to
  many points on the ring.
- **The ring is a typed dependency**, injected like any other — not a package-level
  global reached for from inside handlers (`go-conventions`).

---

### 2 — The `Ring` wrapper (library-backed, default)

Wrap `buraksezer/consistent` in a small domain type so the rest of the code depends
on *your* interface, not the library. This keeps the library swappable and gives
handlers a single, well-named method: "who owns this key?"

```go
// Package partition routes events to worker instances via consistent hashing.
//
// A Ring maps a partition key (e.g. an account ID) to the single worker that owns
// it. Ownership is stable: adding or removing a worker moves only ~1/N of keys,
// never the whole keyspace. This is the Go analog of the Python uhashring
// partition_config continuum.
package partition

import (
	"github.com/buraksezer/consistent"
	"github.com/cespare/xxhash/v2"
)

// Member is a single worker instance on the ring. The String value is the
// canonical, stable worker name — it MUST NOT change across restarts, or every
// key that worker owned will move.
type Member string

// String returns the worker name. Required by consistent.Member.
func (m Member) String() string { return string(m) }

// hasher adapts xxhash to the consistent.Hasher interface. xxhash is fast and
// well-distributed; the choice is fixed here so every process hashes identically.
type hasher struct{}

// Sum64 hashes data to a 64-bit value. All processes MUST use the same hasher,
// otherwise they disagree about ownership.
func (hasher) Sum64(data []byte) uint64 { return xxhash.Sum64(data) }

// Ring assigns partition keys to worker Members using consistent hashing with
// bounded loads. It is safe for concurrent reads after construction.
type Ring struct {
	self string
	ring *consistent.Consistent
}

// Config controls ring construction. See buraksezer/consistent for the semantics
// of PartitionCount, ReplicationFactor, and Load.
type Config struct {
	// Self is this process's own worker name. LocateSelf-style checks compare
	// ownership against it. Must match one of Workers.
	Self string
	// Workers is the full, ordered set of worker names — the continuum. Every
	// process MUST be started with the identical list, or they disagree.
	Workers []string
	// PartitionCount is the number of ring partitions. Higher = smoother
	// distribution, more memory. 271 is a sane default (prime, library default).
	PartitionCount int
	// ReplicationFactor is the number of virtual nodes per worker. 20+ keeps
	// distribution even. The uhashring "replicas" analog.
	ReplicationFactor int
	// Load is the bounded-load factor (>= 1). 1.25 caps any worker at 125% of
	// the average share, preventing hot workers.
	Load float64
}

// NewRing builds a Ring from Config.
//
// All worker processes must call NewRing with an identical Workers list and
// identical hashing parameters, or they will compute different owners for the
// same key. Returns an error if Self is not present in Workers.
func NewRing(cfg Config) (*Ring, error) {
	if !contains(cfg.Workers, cfg.Self) {
		return nil, fmt.Errorf("partition: self %q not in workers %v", cfg.Self, cfg.Workers)
	}

	members := make([]consistent.Member, len(cfg.Workers))
	for i, name := range cfg.Workers {
		members[i] = Member(name)
	}

	ring := consistent.New(members, consistent.Config{
		PartitionCount:    cfg.PartitionCount,
		ReplicationFactor: cfg.ReplicationFactor,
		Load:              cfg.Load,
		Hasher:            hasher{},
	})

	return &Ring{self: cfg.Self, ring: ring}, nil
}

// Owner returns the worker name that owns the given partition key.
//
// The same key always maps to the same worker for a given membership set. An
// empty key returns an error — an unpartitioned event is a routing bug, not a
// silently-accepted default.
func (r *Ring) Owner(key string) (string, error) {
	if key == "" {
		return "", errors.New("partition: empty partition key")
	}
	owner := r.ring.LocateKey([]byte(key))
	if owner == nil {
		return "", fmt.Errorf("partition: no owner for key %q (empty ring?)", key)
	}
	return owner.String(), nil
}

// OwnedBySelf reports whether this process owns the given partition key.
// Handlers use this to skip events that belong to another worker.
func (r *Ring) OwnedBySelf(key string) (bool, error) {
	owner, err := r.Owner(key)
	if err != nil {
		return false, err
	}
	return owner == r.self, nil
}

// Add registers a new worker on the ring. Only ~1/N of keys are reassigned.
// Call this on scale-out when a new worker is discovered.
func (r *Ring) Add(worker string) { r.ring.Add(Member(worker)) }

// Remove drops a worker from the ring, e.g. after a health check fails. Its keys
// are redistributed across the survivors; other keys are untouched.
func (r *Ring) Remove(worker string) { r.ring.Remove(Member(worker)) }
```

Notes:
- `Member` is a named type over `string`, not a bare string — it carries the
  `String()` method the library needs and documents intent (ubiquitous language:
  "worker name" is one concept, one type).
- The library is hidden behind `Ring`. Handlers never import `buraksezer/consistent`.
- Bounded load (`Load: 1.25`) is the feature `uhashring` lacks — it prevents a
  single worker from owning a disproportionate share when the key distribution is
  skewed.

---

### 3 — The static continuum (config), the Go way

The Python file hardcodes a `continuum` dict of `{uuid: {hostname, worker_name}}`.
The Go equivalent is **typed config loaded via viper**, not a literal map in source.
Worker identity and the roster belong in config so the same binary runs as any
worker.

```go
// WorkerConfig is one entry in the partition continuum.
type WorkerConfig struct {
	// Name is the stable worker identity used on the hash ring. Changing it
	// reshuffles every key that worker owned — treat as immutable.
	Name string `mapstructure:"name"`
	// Subject is the NATS subject / durable this worker consumes from.
	Subject string `mapstructure:"subject"`
}

// PartitionConfig is the full continuum plus this process's own identity.
type PartitionConfig struct {
	Self              string         `mapstructure:"self"`
	Workers           []WorkerConfig `mapstructure:"workers"`
	PartitionCount    int            `mapstructure:"partition_count"`
	ReplicationFactor int            `mapstructure:"replication_factor"`
	Load              float64        `mapstructure:"load"`
}

// ToRing constructs a Ring from the loaded config, applying safe defaults.
func (c PartitionConfig) ToRing() (*Ring, error) {
	names := make([]string, len(c.Workers))
	for i, w := range c.Workers {
		names[i] = w.Name
	}
	return NewRing(Config{
		Self:              c.Self,
		Workers:           names,
		PartitionCount:    orDefault(c.PartitionCount, 271),
		ReplicationFactor: orDefault(c.ReplicationFactor, 20),
		Load:              orDefaultFloat(c.Load, 1.25),
	})
}
```

```yaml
# config.yaml — the continuum. Every worker ships the SAME workers list;
# only `self` differs per process (set via env: PARTITION_SELF).
partition:
  self: system_events_worker_01
  partition_count: 271
  replication_factor: 20
  load: 1.25
  workers:
    - { name: system_events_worker_01, subject: "system.events.>" }
    - { name: system_events_worker_02, subject: "system.events.>" }
    - { name: system_events_worker_03, subject: "system.events.>" }
    - { name: system_events_worker_04, subject: "system.events.>" }
    - { name: system_events_worker_05, subject: "system.events.>" }
    - { name: system_events_worker_06, subject: "system.events.>" }
    - { name: system_events_worker_07, subject: "system.events.>" }
    - { name: system_events_worker_08, subject: "system.events.>" }
```

> **Ubiquitous language:** `worker_name` in Python becomes the `name` field, the
> `Member` type, and `PARTITION_SELF` — one concept, one canonical spelling across
> config, ring, and env (`go-conventions`). Do not introduce
> `nodeID`, `instance`, `shardName` synonyms.

---

### 4 — Choosing the partition key

The partition key is the load-bearing decision. It determines *co-location*: all
events sharing a key are processed by one worker, in order, without cross-worker
locks. Choose the **entity whose events must not be split**.

```go
// Good — key on the entity that needs ordered, co-located processing.
// All events for one account land on one worker → no distributed lock needed.
key := event.AccountID

// Bad — keying on the event ID scatters an entity's events across all workers,
// defeating ordering and cache locality. Every event is its own partition.
key := event.EventID // ← anti-pattern
```

Rules:
- The key must be **stable for the entity's lifetime** and present on **every**
  event for that entity.
- Prefer a **coarse** key (account, tenant) over a fine one (individual message) so
  related work co-locates.
- Never derive the key from mutable/derived fields — if the key can change, the
  owner changes mid-stream.

---

### 5 — Composing with NATS JetStream handlers

This is where the ring meets `go-build-event-handlers`. There are two deployment
shapes; pick per stream:

**Shape A — shared durable + in-handler ownership filter (simplest).**
Every worker subscribes to the same durable consumer and receives every message,
but only *acts* on messages it owns; others are `Ack`ed and dropped. Cheap to run,
works with a plain JetStream push/pull consumer, and the ring is the only
coordination.

```go
// SystemEventConsumer routes JetStream messages to the domain handler only when
// this worker owns the message's partition key.
type SystemEventConsumer struct {
	ring    *partition.Ring
	handler eventHandler // from go-build-event-handlers
	log     *slog.Logger
}

// eventHandler is the consumer-local interface (defined at the consumer, per
// go-conventions): the domain handler that does the real work.
type eventHandler interface {
	Handle(ctx context.Context, evt SystemEvent) error
}

// Consume is the JetStream message callback. It is a table of contents:
// decode → check ownership → delegate → ack. No business logic lives here.
func (c *SystemEventConsumer) Consume(ctx context.Context, msg jetstream.Msg) {
	evt, err := decodeSystemEvent(msg.Data())
	if err != nil {
		c.log.Error("decode system event", "err", err)
		_ = msg.Term() // poison message — do not redeliver
		return
	}

	if !c.owns(ctx, evt) {
		_ = msg.Ack() // owned by another worker; drop cleanly
		return
	}

	if err := c.handler.Handle(ctx, evt); err != nil {
		c.log.Error("handle system event", "key", evt.AccountID, "err", err)
		_ = msg.Nak() // let JetStream redeliver
		return
	}
	_ = msg.Ack()
}

// owns reports whether this worker owns the event's partition key, logging and
// treating a routing error as "not owned" so a bad key never blocks the stream.
func (c *SystemEventConsumer) owns(ctx context.Context, evt SystemEvent) bool {
	owned, err := c.ring.OwnedBySelf(evt.AccountID)
	if err != nil {
		c.log.Error("ownership check", "key", evt.AccountID, "err", err)
		return false
	}
	return owned
}
```

```go
// Bad — every worker processes every event. No ownership check means duplicate
// work, broken ordering, and racing writes to the same account.
func (c *SystemEventConsumer) Consume(ctx context.Context, msg jetstream.Msg) {
	evt, _ := decodeSystemEvent(msg.Data())
	_ = c.handler.Handle(ctx, evt) // ← no ring, no partitioning at all
	_ = msg.Ack()
}
```

**Shape B — per-partition subjects (native JetStream sharding).**
Publish with the partition baked into the subject and give each worker its own
durable filtered to the partitions it owns. JetStream then does the delivery
filtering; the ring decides *which subjects a worker subscribes to* at startup.
Use this when the "everyone receives everything" fan-out of Shape A is too costly.

```go
// PublishSubject derives the wire subject from the base subject and the ring
// partition, so JetStream can shard delivery by subject.
//
// e.g. base "system.events", key "acct-42" → "system.events.p.7"
func PublishSubject(base, key string, partitionCount int) string {
	p := int(xxhash.Sum64String(key) % uint64(partitionCount))
	return fmt.Sprintf("%s.p.%d", base, p)
}

// SelfFilterSubjects returns the subject filters this worker should bind its
// durable consumer to — one per partition the ring assigns to self.
func (r *Ring) SelfFilterSubjects(base string, partitionCount int) []string {
	var subjects []string
	for p := 0; p < partitionCount; p++ {
		owner, err := r.Owner(fmt.Sprintf("p.%d", p))
		if err != nil || owner != r.self {
			continue
		}
		subjects = append(subjects, fmt.Sprintf("%s.p.%d", base, p))
	}
	return subjects
}
```

> Trade-off: Shape A is operationally trivial but every worker pays to receive and
> decode every message. Shape B pushes filtering into JetStream (less wasted work)
> at the cost of consumer/subject management on membership changes. Default to
> Shape A; move to Shape B only when the fan-out cost is measured, not assumed.

---

### 6 — Adding and removing workers (minimal reshuffling)

The payoff of consistent hashing is realized only if membership changes are applied
to the ring *identically on every process*. Two disciplines:

- **Static roster (default):** the `workers` list is config; a scale change is a
  redeploy. All processes restart with the new list and recompute the same ring.
  Simple and correct. Reassigns only ~1/N of keys because the ring is consistent.
- **Dynamic membership:** discover live workers (NATS service discovery, a KV
  bucket, k8s endpoints) and call `ring.Add` / `ring.Remove` as they come and go.
  Every process must observe the same membership events, or they disagree about
  ownership during the window.

```go
// watchMembership applies worker join/leave events to the ring as they arrive.
// Each process subscribes to the same membership stream, so all rings converge.
func (c *SystemEventConsumer) watchMembership(ctx context.Context, events <-chan MembershipEvent) {
	for {
		select {
		case <-ctx.Done():
			return
		case e := <-events:
			switch e.Kind {
			case MemberJoined:
				c.ring.Add(e.Worker)
			case MemberLeft:
				c.ring.Remove(e.Worker)
			}
		}
	}
}
```

Gotchas that will bite you (capture these; they are not visible from the code):
- **During a membership change there is a brief window** where processes disagree
  about ownership → an event may be processed twice or missed. Design handlers to be
  **idempotent** (dedupe on event ID). Ordering guarantees are best-effort across
  rebalances.
- **A renamed worker moves all its keys.** `Name` is an identity, not a label.
- **Modulo publishing (Shape B) is NOT consistent hashing.** `hash(key) % N` in
  `PublishSubject` reshuffles subjects if `partitionCount` changes — keep
  `partitionCount` fixed and let the *ring* (not modulo) decide subject→worker
  ownership, which is why `SelfFilterSubjects` hashes `"p.%d"` labels through the
  ring rather than assigning partitions by index.
- **Different hashers = split brain.** If two processes hash differently (one on
  xxhash, one on fnv), they compute different owners. The hasher is fixed in code
  for exactly this reason.

---

### 7 — Wiring it up (`main.go`, no logic)

```go
func main() {
	cfg := config.MustLoad() // viper

	ring, err := cfg.Partition.ToRing()
	if err != nil {
		log.Fatalf("build partition ring: %v", err)
	}

	consumer := &SystemEventConsumer{
		ring:    ring,
		handler: systemevent.NewHandler(/* deps */),
		log:     slog.Default(),
	}

	if err := startJetStreamConsumer(context.Background(), cfg.NATS, consumer); err != nil {
		log.Fatalf("start consumer: %v", err)
	}
}
```

`main.go` wires dependencies and starts the consumer — no ownership logic, no
hashing (`go-conventions`).

---

### 8 — Testing the ring

Table-driven, one decision per case (`go-conventions`). Test the
two properties that actually matter: **stable ownership** and **minimal reshuffling**.

```go
func TestRing_Owner_IsDeterministic(t *testing.T) {
	ring := mustRing(t, "w1", []string{"w1", "w2", "w3"})

	first, err := ring.Owner("acct-42")
	require.NoError(t, err)

	// Same key + same membership → same owner, every time.
	for i := 0; i < 100; i++ {
		got, err := ring.Owner("acct-42")
		require.NoError(t, err)
		assert.Equal(t, first, got)
	}
}

func TestRing_Owner_EmptyKeyErrors(t *testing.T) {
	ring := mustRing(t, "w1", []string{"w1", "w2"})
	_, err := ring.Owner("")
	assert.ErrorContains(t, err, "empty partition key")
}

func TestRing_MinimalReshuffleOnRemove(t *testing.T) {
	workers := []string{"w1", "w2", "w3", "w4"}
	ring := mustRing(t, "w1", workers)

	keys := makeKeys(10_000)
	before := ownerMap(t, ring, keys)

	ring.Remove("w4") // simulate one worker leaving

	after := ownerMap(t, ring, keys)

	moved := 0
	for k, owner := range before {
		if after[k] != owner {
			moved++
		}
	}
	// Consistent hashing moves only ~1/N of keys, not the whole keyspace.
	// With 4 workers, expect well under 40% moved (generous upper bound).
	assert.Less(t, moved, len(keys)*40/100,
		"removing one of four workers reshuffled too many keys — not consistent hashing")
}
```

Test the consumer's ownership gate with a fake ring so no worker double-processes:

```go
func TestConsumer_SkipsUnownedEvents(t *testing.T) {
	tests := []struct {
		name       string
		owner      string
		self       string
		wantHandle bool
	}{
		{name: "handles event this worker owns", owner: "w1", self: "w1", wantHandle: true},
		{name: "skips event owned by another worker", owner: "w2", self: "w1", wantHandle: false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			handler := &spyHandler{}
			c := &SystemEventConsumer{
				ring:    fakeRing{self: tc.self, owner: tc.owner},
				handler: handler,
				log:     slog.Default(),
			}
			handled := c.owns(context.Background(), SystemEvent{AccountID: "acct-1"})
			assert.Equal(t, tc.wantHandle, handled)
		})
	}
}
```

---

## Checklist

Run through before merging a partitioned consumer. Each unchecked item is a blocker.

- [ ] Routing uses **consistent hashing**, not `hash(key) % N` — verified by a
      minimal-reshuffle test.
- [ ] The consistent-hash library (`buraksezer/consistent`) is wrapped behind a
      domain `Ring` type; handlers never import it directly.
- [ ] All worker processes are constructed with the **identical** worker roster and
      hashing parameters (same `PartitionCount`, `ReplicationFactor`, `Hasher`).
- [ ] The **hasher is fixed in code** — no per-process divergence possible.
- [ ] The partition key is the **entity that must co-locate** (account/tenant), is
      present on every event, and is stable for the entity's lifetime.
- [ ] `Owner`/`OwnedBySelf` reject an **empty key** with an error — no silent default.
- [ ] The JetStream consumer **checks ownership before delegating**; unowned
      messages are `Ack`ed and dropped (Shape A) or never delivered (Shape B).
- [ ] Handlers are **idempotent** (dedupe on event ID) to survive the double/miss
      window during a rebalance.
- [ ] Worker `Name` is treated as **immutable identity**; renaming is understood to
      reshuffle its keys.
- [ ] The ring is **injected**, not a package-level global.
- [ ] Ownership determinism, empty-key rejection, minimal-reshuffle, and the
      consumer skip-gate all have **table-driven tests**.
- [ ] Defers to `go-build-event-handlers` for handler internals and to
      `go-conventions` for naming, godoc, structure, and error handling.
