---
name: typescript-build-event-handlers
description: Build typed domain event buses, typed EventEmitter subclasses, and async event handler functions
  with discriminated union event types and correct error propagation.
when_to_use: Use when building domain event systems, typed EventEmitter subclasses, async event handlers,
  or in-process event buses in TypeScript.
group: languages
kind: skill
---

# TypeScript Build Event Handlers

## Skill summary

- **Name:** `typescript-build-event-handlers`
- **Description:** Build typed domain event buses, typed EventEmitter subclasses, and async event handler functions with discriminated union event types and correct error propagation.
- **When to use:** Use when building domain event systems, typed EventEmitter subclasses, async event handlers, or in-process event buses in TypeScript.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "add a UserCreatedEvent and register a handler that sends a welcome email"
- "build a typed in-process event bus with discriminated union event types"
- "create an async event handler for OrderPlacedEvent that never swallows errors"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

TypeScript domain events follow a discriminated union pattern: every event is a typed interface with a `type` literal string discriminant and a `payload` object. Handlers receive the full typed event — no `any` payloads, no untyped `data` arguments. Errors always propagate; handlers never swallow them silently.

### Core rules

1. **Every domain event is a typed interface** with a `type` literal and a typed `payload`. No generic `{ type: string; data: unknown }`.
2. **Events form a discriminated union** — `type DomainEvent = UserCreatedEvent | OrderPlacedEvent | ...`. TypeScript narrows automatically.
3. **One handler per event type** — single responsibility. A handler for `user.created` must not also handle `order.placed`.
4. **Handlers are async and throw on error** — they never catch-and-log silently. The bus or queue infrastructure handles retry/dead-letter.
5. **No `any` payloads** — handler signatures are `(event: UserCreatedEvent) => Promise<void>`, not `(event: any) => void`.
6. **Use a typed EventEmitter subclass or a typed bus class** — never call `emitter.emit('user.created', { ...untypedData })` directly.
7. **Test handlers in isolation** — pass a constructed event object and assert side effects or thrown errors.

---

### Typed event interfaces

```typescript
// src/events/domain-events.ts

export interface UserCreatedEvent {
  type: 'user.created';
  payload: {
    userId: string;
    email: string;
    name: string;
    createdAt: Date;
  };
}

export interface UserDeactivatedEvent {
  type: 'user.deactivated';
  payload: {
    userId: string;
    reason: string;
    deactivatedAt: Date;
  };
}

export interface OrderPlacedEvent {
  type: 'order.placed';
  payload: {
    orderId: string;
    customerId: string;
    lineItems: Array<{ sku: string; quantity: number; unitPriceCents: number }>;
    totalCents: number;
    placedAt: Date;
  };
}

export interface OrderFulfilledEvent {
  type: 'order.fulfilled';
  payload: {
    orderId: string;
    fulfilledAt: Date;
    trackingCode: string | null;
  };
}

// The discriminated union that the bus and all handlers use.
export type DomainEvent =
  | UserCreatedEvent
  | UserDeactivatedEvent
  | OrderPlacedEvent
  | OrderFulfilledEvent;

// Extract the payload type from any event.
export type EventPayload<T extends DomainEvent> = T['payload'];
```

---

### Typed event bus

A simple in-process bus backed by `EventEmitter`. The type system ensures you cannot register a handler for an event that does not exist, and cannot emit the wrong payload shape.

```typescript
// src/events/event-bus.ts
import { EventEmitter } from 'node:events';
import type { DomainEvent } from './domain-events.js';

type EventType = DomainEvent['type'];
type EventByType<T extends EventType> = Extract<DomainEvent, { type: T }>;
type AsyncHandler<T extends EventType> = (event: EventByType<T>) => Promise<void>;

export class DomainEventBus extends EventEmitter {
  /**
   * Register a typed async handler for a specific event type.
   * Errors thrown by the handler are re-emitted on the 'error' channel.
   */
  on<T extends EventType>(eventType: T, handler: AsyncHandler<T>): this {
    super.on(eventType, (event: EventByType<T>) => {
      handler(event).catch((err: unknown) => {
        this.emit('error', err, event);
      });
    });
    return this;
  }

  /**
   * Emit a strongly-typed domain event.
   * The payload shape is enforced at compile time.
   */
  emit<T extends EventType>(eventType: T, event: EventByType<T>): boolean;
  emit(eventType: string, ...args: unknown[]): boolean;
  emit(eventType: string, ...args: unknown[]): boolean {
    return super.emit(eventType, ...args);
  }

  /**
   * Register a one-time typed handler.
   */
  once<T extends EventType>(eventType: T, handler: AsyncHandler<T>): this {
    super.once(eventType, (event: EventByType<T>) => {
      handler(event).catch((err: unknown) => {
        this.emit('error', err, event);
      });
    });
    return this;
  }
}

// Singleton instance — import this wherever events are emitted or consumed.
export const eventBus = new DomainEventBus();

// Prevent silent crash from unhandled 'error' events.
eventBus.on('error', (err: unknown) => {
  console.error('[event-bus] unhandled handler error:', err);
});
```

---

### Individual handler functions

Each handler is a standalone async function — one file per handler (or one file per domain event, grouping closely related handlers):

```typescript
// src/events/handlers/send-welcome-email.handler.ts
import type { UserCreatedEvent } from '../domain-events.js';
import { EmailService } from '../../services/email.service.js';

/**
 * Send a welcome email when a new user is created.
 * Throws on failure — the bus will re-emit the error.
 */
export async function sendWelcomeEmailHandler(
  event: UserCreatedEvent,
): Promise<void> {
  await EmailService.sendWelcome({
    to: event.payload.email,
    name: event.payload.name,
    userId: event.payload.userId,
  });
}
```

```typescript
// src/events/handlers/provision-default-workspace.handler.ts
import type { UserCreatedEvent } from '../domain-events.js';
import { WorkspaceService } from '../../services/workspace.service.js';

/**
 * Create a default workspace for the user.
 * Throws on failure — the bus will re-emit the error.
 */
export async function provisionDefaultWorkspaceHandler(
  event: UserCreatedEvent,
): Promise<void> {
  await WorkspaceService.createDefault({
    ownerId: event.payload.userId,
    name: `${event.payload.name}'s Workspace`,
  });
}
```

---

### Handler registration

Registration happens in one place — a bootstrap function called at app startup:

```typescript
// src/events/register-handlers.ts
import { eventBus } from './event-bus.js';
import { sendWelcomeEmailHandler } from './handlers/send-welcome-email.handler.js';
import { provisionDefaultWorkspaceHandler } from './handlers/provision-default-workspace.handler.js';
import { cancelPendingOrdersHandler } from './handlers/cancel-pending-orders.handler.js';
import { notifyFulfillmentTeamHandler } from './handlers/notify-fulfillment-team.handler.js';

export function registerDomainEventHandlers(): void {
  eventBus.on('user.created', sendWelcomeEmailHandler);
  eventBus.on('user.created', provisionDefaultWorkspaceHandler);
  eventBus.on('user.deactivated', cancelPendingOrdersHandler);
  eventBus.on('order.placed', notifyFulfillmentTeamHandler);
}
```

```typescript
// src/app.ts — call at startup
import { registerDomainEventHandlers } from './events/register-handlers.js';

registerDomainEventHandlers();
```

---

### Emitting events (from a domain service)

```typescript
// src/domains/users/users.service.ts
import { eventBus } from '../../events/event-bus.js';
import type { UserDTO } from './users.dto.js';

export class UserService {
  static async create(input: CreateUserInput): Promise<UserDTO> {
    const user = await db.users.insert(input);

    // Emit after the database write succeeds.
    eventBus.emit('user.created', {
      type: 'user.created',
      payload: {
        userId: user.id,
        email: user.email,
        name: user.name,
        createdAt: user.createdAt,
      },
    });

    return user;
  }
}
```

---

### Testing handlers in isolation

Handlers are plain async functions — test them directly without involving the bus:

```typescript
// src/events/handlers/send-welcome-email.handler.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { sendWelcomeEmailHandler } from './send-welcome-email.handler.js';
import { EmailService } from '../../services/email.service.js';
import type { UserCreatedEvent } from '../domain-events.js';

vi.mock('../../services/email.service.js', () => ({
  EmailService: { sendWelcome: vi.fn() },
}));

const buildUserCreatedEvent = (overrides?: Partial<UserCreatedEvent['payload']>): UserCreatedEvent => ({
  type: 'user.created',
  payload: {
    userId: 'user-123',
    email: 'alice@example.com',
    name: 'Alice',
    createdAt: new Date('2024-01-01'),
    ...overrides,
  },
});

describe('sendWelcomeEmailHandler', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls EmailService.sendWelcome with the correct payload', async () => {
    const event = buildUserCreatedEvent();
    await sendWelcomeEmailHandler(event);

    expect(EmailService.sendWelcome).toHaveBeenCalledOnce();
    expect(EmailService.sendWelcome).toHaveBeenCalledWith({
      to: 'alice@example.com',
      name: 'Alice',
      userId: 'user-123',
    });
  });

  it('propagates errors thrown by EmailService', async () => {
    vi.mocked(EmailService.sendWelcome).mockRejectedValueOnce(
      new Error('SMTP unavailable'),
    );
    const event = buildUserCreatedEvent();

    await expect(sendWelcomeEmailHandler(event)).rejects.toThrow('SMTP unavailable');
  });
});
```

---

### Event handler checklist

Before finishing an event handler system, verify:

- [ ] Every event is a typed interface with a `type` literal discriminant and a typed `payload`
- [ ] All events form a discriminated union exported from `domain-events.ts`
- [ ] One handler function per behavior — no handler handles multiple event types
- [ ] All handlers are `async` and throw on error — no `try/catch` that swallows
- [ ] The bus re-emits errors to the `'error'` channel (or logs them) — not swallowed in the bus either
- [ ] Handler registration is centralized in `register-handlers.ts`, called once at startup
- [ ] Events are emitted only after the domain write succeeds — not before
- [ ] Tests for each handler pass a constructed typed event object and assert the expected side effect or error
