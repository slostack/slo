---
name: go-build-event-handlers
description: "Go scoped recipe (testcontainers, NATS): Build NATS JetStream event handlers in Go \u2014\
  \ stream/consumer setup, a typed dispatcher registry that routes an event by subject/type to the right\
  \ handler, ack/nack + redelivery semantics, idempotency, and delegation to application services. The\
  \ Go equivalent of the Python handler.py/base.py pattern."
when_to_use: "Only for the named project stack and component. Use when adding or reviewing code that consumes\
  \ events from NATS JetStream \u2014 subscribing to subjects, routing events to handlers, parsing typed\
  \ payloads, and handing work off to application services."
group: languages
kind: skill
---

# Build Go Event Handlers

## Skill summary

- **Name:** `go-build-event-handlers`
- **Description:** Build NATS JetStream event handlers in Go — stream/consumer
  setup, a typed dispatcher registry that routes an event by subject/type to the
  right handler, ack/nack + redelivery semantics, idempotency, and delegation to
  application services. The Go equivalent of the Python `handler.py` (routing) +
  `base.py` (handler registry) pattern.
- **When to use:** Use when adding or reviewing code that consumes events from
  NATS JetStream — subscribing to subjects, routing events, parsing typed
  payloads, and handing work off to application services.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Add a NATS JetStream consumer for the `WeightLoggedEvent`."
- "Wire up an event dispatcher that routes events by type to handlers."
- "How do I ack/nack a JetStream message with redelivery on failure?"
- "Make my event handler idempotent so redeliveries don't double-process."
- "Convert this Python `event_handlers/` folder to Go."
- "Register a new handler in the event router without touching existing code."
- "Review my JetStream handler for correct error/redelivery semantics."

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

This skill translates the Python event-handler pattern (`handler.py` routes an
incoming event through a list of registered handlers defined in `base.py`; each
handler self-selects by `event_name` and delegates real work to an application
service) into idiomatic Go on **NATS JetStream** (`github.com/nats-io/nats.go`).

Defer to `go-conventions` for all naming, structure, godoc, error
wrapping, and testing rules — this skill only adds the event-handling specifics.
Handlers do **routing and delegation only**; the actual business logic lives in
application services (see `go-build-application-services`). For scaling a single
subject across many workers with ordered per-key processing, see
`go-build-partitioned-events`.

### The four core principles (carried over from Python)

1. **Thin routing layer.** The dispatcher inspects the event and forwards it to
   the matching handler. It contains no business logic — the Go equivalent of
   `EventHandler.process` iterating `handlers`.
2. **Self-contained handlers that delegate.** Each handler parses its typed
   payload and calls an application service's `Execute()`. It never talks to the
   DB or external systems directly.
3. **The handler chain is never broken by one bad event.** In Python this meant
   "handlers never throw". In Go it means: a handler returns an `error`, and the
   dispatcher decides ack vs. nack — one handler's failure never panics the
   process or silently drops the message.
4. **Typed payloads at the boundary.** Python used Pydantic DAOs
   (`StepCountLoggedEventDAO`). Go uses JSON-tagged structs validated with
   `go-playground/validator`.

Where the Python idiom (decorators, a `handlers = [...]` list of classes with a
`process` classmethod) has no Go equivalent, we use an **interface + registry
map keyed by subject/type**. This is the idiomatic replacement for the "iterate
every handler and let each self-select" loop and it satisfies the
convention against long `switch` chains.

---

### Section 1 — The event envelope and typed payloads

Every message on the bus shares a common envelope so the dispatcher can route
without unmarshalling the full payload. The domain-specific data lives in
`Payload` (raw JSON), decoded by the concrete handler into its own typed struct.

```go
// Package events defines the event envelope, dispatcher, and handler contract
// for consuming NATS JetStream messages.
package events

import (
	"context"
	"encoding/json"
	"time"
)

// Envelope is the common wrapper for every event published to the bus.
//
// Type is the canonical event name (ubiquitous language — it matches the
// publisher and the domain constant). Payload is the event-specific body,
// decoded by the matching handler into its own typed struct. EventID is the
// idempotency key: a handler must not re-process an EventID it has already
// committed.
type Envelope struct {
	EventID   string          `json:"event_id"   validate:"required"`
	Type      string          `json:"type"       validate:"required"`
	OccurredAt time.Time      `json:"occurred_at"`
	Payload   json.RawMessage `json:"payload"`
}
```

Concrete payloads are ordinary JSON-tagged structs — the Pydantic-DAO analog.
Field names match the publisher and the DB columns mechanically (see the
ubiquitous-language rule in `go-conventions`).

```go
// WeightLoggedPayload is the typed body of a WeightLoggedEvent.
type WeightLoggedPayload struct {
	UserID    string    `json:"user_id"    validate:"required,uuid"`
	WeightKg  float64   `json:"weight_kg"  validate:"gt=0"`
	LoggedAt  time.Time `json:"logged_at"`
}

// StepCountLoggedPayload is the typed body of a StepCountLoggedEvent.
type StepCountLoggedPayload struct {
	UserID string `json:"user_id" validate:"required,uuid"`
	Steps  int    `json:"steps"   validate:"gte=0"`
	Date   string `json:"date"    validate:"required"`
}
```

Canonical event-type constants — never hardcode the string at a call site:

```go
// Event type names. These are the canonical identifiers shared with publishers.
const (
	TypeWeightLogged    = "WeightLoggedEvent"
	TypeStepCountLogged = "StepCountLoggedEvent"
	TypeScoreComputed   = "ScoreComputedEvent"
)
```

---

### Section 2 — The handler contract

A handler is an interface, not a bare function, so it can hold injected
dependencies (application services). This is the Go replacement for a Python
class with a `process` classmethod.

```go
// handler processes a single decoded event.
//
// Implementations must be idempotent: the same Envelope (identified by
// EventID) may be delivered more than once. A returned error signals the
// dispatcher to nack the message for redelivery; a nil error signals ack.
// Implementations must NOT call ack/nack themselves — that is the
// dispatcher's job.
type handler interface {
	// Handle performs routing-free work: decode payload, delegate to an
	// application service. It must not touch the DB or external systems
	// directly.
	Handle(ctx context.Context, env Envelope) error
}
```

A **transient vs. terminal** error distinction controls redelivery. A malformed
payload will never succeed on redelivery, so it must be terminal (ack + dead
letter), whereas a downstream timeout should be retried (nack).

```go
// TerminalError wraps an error that must not be retried. The dispatcher acks
// the message and routes it to the dead-letter path instead of redelivering.
type TerminalError struct{ Err error }

func (e *TerminalError) Error() string { return "terminal: " + e.Err.Error() }
func (e *TerminalError) Unwrap() error { return e.Err }

// Terminal marks err as non-retryable.
func Terminal(err error) error { return &TerminalError{Err: err} }
```

---

### Section 3 — Concrete handlers (delegate to application services)

Each handler holds the application service it delegates to, decodes its typed
payload, validates it, and calls `Execute()`. Guard clauses first; happy path
last. This mirrors the Python `EmailLiveSessionHostEventHandler` /
`LeaderboardEventHandler` shape.

```go
// weightLoggedHandler handles WeightLoggedEvent by delegating to the
// leaderboard-update application service.
type weightLoggedHandler struct {
	validate     *validator.Validate
	updateSvc    leaderboardUpdater // consumer-defined interface — see below
}

// leaderboardUpdater is the minimal contract this handler needs from the
// application-service layer (interface defined at the consumer, per
// go-conventions).
type leaderboardUpdater interface {
	Execute(ctx context.Context, params leaderboard.UpdateParams) error
}

// Handle decodes the weight payload and delegates the leaderboard update.
//
// Returns a TerminalError for an unparseable/invalid payload (no redelivery)
// and a plain error for a transient downstream failure (redelivery).
func (h *weightLoggedHandler) Handle(ctx context.Context, env Envelope) error {
	var payload WeightLoggedPayload
	if err := json.Unmarshal(env.Payload, &payload); err != nil {
		return Terminal(fmt.Errorf("decoding weight payload: %w", err))
	}
	if err := h.validate.Struct(payload); err != nil {
		return Terminal(fmt.Errorf("validating weight payload: %w", err))
	}

	return h.updateSvc.Execute(ctx, leaderboard.UpdateParams{
		UserID:   payload.UserID,
		WeightKg: payload.WeightKg,
	})
}
```

A handler that fans one subject to different services based on a sub-decision
still keeps `Handle` flat and delegates each branch:

```go
// scoreComputedHandler recomputes a leaderboard when a score is computed.
type scoreComputedHandler struct {
	validate  *validator.Validate
	scoreSvc  LeaderboardScoreUpdater
}

// Handle decodes the score payload and delegates to the score-update service.
func (h *scoreComputedHandler) Handle(ctx context.Context, env Envelope) error {
	var payload ScoreComputedPayload
	if err := json.Unmarshal(env.Payload, &payload); err != nil {
		return Terminal(fmt.Errorf("decoding score payload: %w", err))
	}
	if err := h.validate.Struct(payload); err != nil {
		return Terminal(fmt.Errorf("validating score payload: %w", err))
	}
	return h.scoreSvc.Execute(ctx, leaderboard.ScoreParams{
		UserID: payload.UserID,
		Score:  payload.Score,
	})
}
```

**Bad — business logic inside the handler (blocker):**

```go
// Bad — the handler queries the DB and computes the leaderboard itself.
func (h *weightLoggedHandler) Handle(ctx context.Context, env Envelope) error {
	var p WeightLoggedPayload
	json.Unmarshal(env.Payload, &p)                 // swallowed error
	rows, _ := h.db.Query(ctx, "SELECT ...")        // DB in a handler — no
	// ...100 lines of ranking math...               // business logic — no
	return nil
}
```

---

### Section 4 — The dispatcher (registry + routing)

The dispatcher is the Go equivalent of Python's `handler.py` + `base.py`
combined: a registry map (`base.py`'s `handlers` list) plus routing logic
(`EventHandler.process`). Registration is a single map entry, so adding an event
type never touches existing routing code — the map/registry rule from
`go-conventions`.

```go
// Dispatcher routes a decoded Envelope to the handler registered for its Type.
type Dispatcher struct {
	handlers map[string]handler
	log      *slog.Logger
}

// NewDispatcher creates an empty Dispatcher.
func NewDispatcher(log *slog.Logger) *Dispatcher {
	return &Dispatcher{handlers: make(map[string]handler), log: log}
}

// Register binds a handler to an event type. Registering a duplicate type
// panics at startup — a wiring bug should fail loudly, not silently overwrite.
func (d *Dispatcher) Register(eventType string, h handler) {
	if _, exists := d.handlers[eventType]; exists {
		panic(fmt.Sprintf("duplicate handler registration for %q", eventType))
	}
	d.handlers[eventType] = h
}

// Dispatch routes env to its registered handler and returns the handler's
// error. An unknown event type is not an error: it is acked and logged, so an
// unrelated event on a shared subject never blocks the stream.
func (d *Dispatcher) Dispatch(ctx context.Context, env Envelope) error {
	h, ok := d.handlers[env.Type]
	if !ok {
		d.log.Debug("no handler for event type; acking", "type", env.Type)
		return nil
	}
	return h.Handle(ctx, env)
}
```

Registration happens once at startup — the `base.py` analog, but explicit:

```go
// RegisterHandlers wires every event type to its handler. This is the single
// place to add a new handler — the Go equivalent of base.py's handlers list.
func RegisterHandlers(d *Dispatcher, deps Deps) {
	v := validator.New()
	d.Register(TypeWeightLogged, &weightLoggedHandler{validate: v, updateSvc: deps.Leaderboard})
	d.Register(TypeStepCountLogged, &stepCountLoggedHandler{validate: v, updateSvc: deps.Leaderboard})
	d.Register(TypeScoreComputed, &scoreComputedHandler{validate: v, scoreSvc: deps.Score})
}
```

---

### Section 5 — JetStream setup and the consume loop

This is the piece Python hid behind a framework. On JetStream you: connect,
ensure the stream exists, create a durable pull consumer, and consume messages —
translating each `jetstream.Msg` into an `Envelope`, dispatching, and then
ack/nacking based on the result.

```go
// StartConsumer connects to JetStream, ensures the stream + durable consumer
// exist, and blocks consuming messages until ctx is cancelled.
//
// Each message is decoded into an Envelope and routed through the dispatcher.
// Ack/Nak is decided from the dispatcher's error (see routeAck).
func StartConsumer(ctx context.Context, cfg ConsumerConfig, d *Dispatcher, log *slog.Logger) error {
	nc, err := nats.Connect(cfg.URL)
	if err != nil {
		return fmt.Errorf("connecting to nats: %w", err)
	}
	defer nc.Drain()

	js, err := jetstream.New(nc)
	if err != nil {
		return fmt.Errorf("creating jetstream context: %w", err)
	}

	// Idempotent: creates the stream if absent, else validates the config.
	stream, err := js.CreateOrUpdateStream(ctx, jetstream.StreamConfig{
		Name:     cfg.StreamName,
		Subjects: []string{cfg.SubjectFilter}, // e.g. "events.user.>"
	})
	if err != nil {
		return fmt.Errorf("ensuring stream %s: %w", cfg.StreamName, err)
	}

	// Durable consumer: survives restarts; MaxDeliver caps redeliveries;
	// AckWait bounds how long a message may be in-flight before redelivery.
	cons, err := stream.CreateOrUpdateConsumer(ctx, jetstream.ConsumerConfig{
		Durable:       cfg.DurableName,
		AckPolicy:     jetstream.AckExplicitPolicy,
		MaxDeliver:    cfg.MaxDeliver, // e.g. 5
		AckWait:       cfg.AckWait,    // e.g. 30 * time.Second
		FilterSubject: cfg.SubjectFilter,
	})
	if err != nil {
		return fmt.Errorf("ensuring consumer %s: %w", cfg.DurableName, err)
	}

	consumeCtx, err := cons.Consume(func(msg jetstream.Msg) {
		handleMsg(ctx, msg, d, log)
	})
	if err != nil {
		return fmt.Errorf("starting consume: %w", err)
	}
	defer consumeCtx.Stop()

	<-ctx.Done()
	return ctx.Err()
}
```

The per-message function is the bridge between the transport and the dispatcher.
It is the only place ack/nack lives — handlers never call ack/nack themselves.

```go
// handleMsg decodes one JetStream message, dispatches it, and applies the
// ack/nack decision. It never panics the consume loop: a bad message is acked
// as terminal, a transient failure is nacked for redelivery.
func handleMsg(ctx context.Context, msg jetstream.Msg, d *Dispatcher, log *slog.Logger) {
	var env Envelope
	if err := json.Unmarshal(msg.Data(), &env); err != nil {
		// Undecodable envelope will never succeed — ack and drop, don't loop.
		log.Error("undecodable envelope; acking to avoid poison loop", "err", err)
		_ = msg.Ack()
		return
	}

	err := d.Dispatch(ctx, env)
	routeAck(msg, env, err, log)
}

// routeAck applies the ack/nack decision for a dispatched message.
//
//   - nil error                → Ack (processed successfully)
//   - *TerminalError           → Ack (non-retryable; dead-letter via monitoring)
//   - any other error          → Nak with backoff (retry until MaxDeliver)
func routeAck(msg jetstream.Msg, env Envelope, err error, log *slog.Logger) {
	if err == nil {
		_ = msg.Ack()
		return
	}

	var terminal *TerminalError
	if errors.As(err, &terminal) {
		log.Error("terminal handler failure; acking (dead-letter)",
			"type", env.Type, "event_id", env.EventID, "err", err)
		_ = msg.Ack()
		return
	}

	log.Warn("transient handler failure; nacking for redelivery",
		"type", env.Type, "event_id", env.EventID, "err", err)
	_ = msg.NakWithDelay(backoffFor(msg))
}
```

**Redelivery / poison-message rule.** JetStream redelivers a nacked message up
to `MaxDeliver` times. Without a terminal-error path, a permanently-failing
message loops until it exhausts `MaxDeliver` and is silently dropped. Always:
ack undecodable/invalid payloads (`TerminalError`), and reserve nack for
genuinely transient failures.

---

### Section 6 — Idempotency

JetStream guarantees **at-least-once** delivery, so redelivery of an already
processed event is normal, not exceptional. A handler (or the service it calls)
must be idempotent on `EventID`. Two acceptable strategies:

```go
// Strategy A — processed-events table (dedupe at the boundary).
// The handler records EventID in a unique-constrained table inside the same
// transaction as the work; a duplicate insert means "already processed".
func (h *weightLoggedHandler) Handle(ctx context.Context, env Envelope) error {
	// ... decode + validate ...
	err := h.updateSvc.Execute(ctx, leaderboard.UpdateParams{
		EventID:  env.EventID, // service inserts into processed_events; ON CONFLICT DO NOTHING
		UserID:   payload.UserID,
		WeightKg: payload.WeightKg,
	})
	if errors.Is(err, leaderboard.ErrAlreadyProcessed) {
		return nil // already committed on a prior delivery — ack cleanly
	}
	return err
}
```

- **Strategy A (dedupe table):** persist `EventID` with a unique constraint in
  the same transaction as the effect. On conflict, treat as success and ack.
- **Strategy B (natural idempotency):** make the effect a set/upsert rather than
  an increment (`SET weight = $1` not `weight = weight + $1`), so reapplying the
  same event is a no-op. Prefer this when the domain allows it.

Never rely on "we probably won't get a redelivery." You will.

---

### Section 7 — Wiring it together (main)

`cmd/consumer/main.go` wires dependencies and starts the loop — no logic
(`go-conventions`).

```go
func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	cfg := config.Load() // viper-backed
	deps := buildDeps(cfg)

	dispatcher := events.NewDispatcher(log)
	events.RegisterHandlers(dispatcher, deps)

	if err := events.StartConsumer(ctx, cfg.Consumer, dispatcher, log); err != nil && !errors.Is(err, context.Canceled) {
		log.Error("consumer exited", "err", err)
		os.Exit(1)
	}
}
```

---

### Section 8 — Testing

Mirror the Python testing note: **test the dispatch decision, and test the
application service the handler invokes** — separately.

1. **Dispatcher routing** — a fake `handler` records the envelope it received;
   assert the right type is routed and unknown types ack without error.
2. **handler delegation** — a mock application service; assert `Execute` is
   called with the correctly mapped params, and that a bad payload yields a
   `TerminalError`.
3. **Ack decision** — table-driven test over `routeAck`: nil → ack,
   `TerminalError` → ack, other error → nak.

```go
// TestDispatch_RoutesByType asserts the dispatcher forwards to the handler
// registered for the envelope's Type and acks unknown types.
func TestDispatch_RoutesByType(t *testing.T) {
	tests := []struct {
		name       string
		eventType  string
		wantCalled bool
	}{
		{name: "routes known type to its handler", eventType: TypeWeightLogged, wantCalled: true},
		{name: "acks unknown type without calling any handler", eventType: "UnknownEvent", wantCalled: false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			spy := &spyHandler{}
			d := NewDispatcher(slog.Default())
			d.Register(TypeWeightLogged, spy)

			err := d.Dispatch(context.Background(), Envelope{Type: tc.eventType})

			assert.NoError(t, err)
			assert.Equal(t, tc.wantCalled, spy.called)
		})
	}
}
```

Use `testify` mocks for the application-service interface; reserve
`testcontainers-go` with a real NATS container for integration tests of the full
consume loop (subscribe → publish → assert side effect).

---

## Checklist

Apply before merging any event-handler code. Each unchecked item is a blocker.

### Routing & registration
- [ ] Dispatcher is a **registry map keyed by event type** — no long `switch`.
- [ ] Adding a new event type is a **single `Register` call**; no existing
      routing code is edited.
- [ ] Unknown event types are **acked and logged**, never nacked or errored.
- [ ] Duplicate registration **panics at startup**, not silently overwrites.

### Handlers
- [ ] Handlers contain **no business logic, no direct DB/external I/O** — they
      decode, validate, and delegate to an application service's `Execute()`.
- [ ] Consumer-local interfaces (the app-service contract) are defined at the
      **handler package**, not the provider (`go-conventions`).
- [ ] Handlers **never call ack/nack** — only the per-message bridge does.
- [ ] Payload structs are **JSON-tagged and validated** with `validator`; field
      names match the publisher and DB columns (ubiquitous language).

### Ack / redelivery
- [ ] Undecodable/invalid payloads return a **`TerminalError`** (ack + dead
      letter) — never nacked into a poison-message loop.
- [ ] Transient failures **nack for redelivery**; consumer sets a finite
      **`MaxDeliver`** and an appropriate **`AckWait`**.
- [ ] The consume loop **never panics** on one bad message.

### Idempotency
- [ ] The handler or its service is **idempotent on `EventID`** (dedupe table or
      natural upsert). At-least-once delivery is assumed.

### Context & concurrency
- [ ] `context.Context` is threaded from the consumer through dispatch to the
      service and honored on cancellation (`go-conventions`).

### Testing
- [ ] Dispatcher routing, handler delegation, and `routeAck` each have
      **table-driven tests**; the invoked application service is tested
      separately.

### Cross-references
- Business logic lives in application services → `go-build-application-services`.
- Scaling one subject across ordered per-key workers → `go-build-partitioned-events`.
- Naming, godoc, error wrapping, structure → `go-conventions`.
