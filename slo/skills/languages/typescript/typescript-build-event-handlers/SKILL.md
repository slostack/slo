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

**Testing policy:** `skills/coding/test-verification-policy/SKILL.md` owns how to test. Event handlers are journey entry points (level 1).

TypeScript domain events follow a discriminated union pattern: every event is a typed interface with a `type` literal string discriminant and a `payload` object. Handlers receive the full typed event — no `any` payloads, no untyped `data` arguments. Errors always propagate; handlers never swallow them silently.

### Core rules

1. **Every domain event is a typed interface** with a `type` literal and a typed `payload`. No generic `{ type: string; data: unknown }`.
2. **Events form a discriminated union** — `type DomainEvent = UserCreatedEvent | OrderPlacedEvent | ...`. TypeScript narrows automatically.
3. **One handler per event type** — single responsibility. A handler for `user.created` must not also handle `order.placed`.
4. **Handlers are async and throw on error** — they never catch-and-log silently. The bus or queue infrastructure handles retry/dead-letter.
5. **No `any` payloads** — handler signatures are `(event: UserCreatedEvent) => Promise<void>`, not `(event: any) => void`.
6. **Use a typed EventEmitter subclass or a typed bus class** — never call `emitter.emit('user.created', { ...untypedData })` directly.
7. **Test handlers directly as journey entry points** — pass a constructed event object to a handler built with real services on the test database; fake only the third-party provider client; assert persisted outcomes or thrown errors.
8. **Handlers receive dependencies through a factory options object** — this is the injection seam for third-party fakes in tests.

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

Each handler is an async function built by a factory that receives its dependencies — one file per handler (or one file per domain event, grouping closely related handlers).

- `EmailService` is internal: it records an `email_deliveries` row and sends through `EmailProviderClient`, the wrapper around the third-party provider.

```typescript
// src/services/email.service.ts
export interface EmailServiceOptions {
  deliveries: EmailDeliveryRepository;
  provider: EmailProviderClient; // third-party boundary (SES, SendGrid, ...)
}

export class EmailService {
  constructor(private readonly options: EmailServiceOptions) {}

  /** Send the welcome email and record the delivery. Throws if the provider fails. */
  async sendWelcome({ to, name, userId }: SendWelcomeInput): Promise<EmailDeliveryDAO> {
    const sent: ProviderSendResult = await this.options.provider.send({ to, template: 'welcome', variables: { name } });
    return this.options.deliveries.create({
      input: { userId, template: 'welcome', providerMessageId: sent.messageId },
    });
  }
}
```

```typescript
// src/events/handlers/send-welcome-email.handler.ts
import type { UserCreatedEvent } from '../domain-events.js';
import type { EmailService } from '../../services/email.service.js';

/**
 * Build the handler that sends a welcome email when a new user is created.
 * The returned handler throws on failure — the bus will re-emit the error.
 */
export function buildSendWelcomeEmailHandler(
  { emailService }: { emailService: EmailService },
): (event: UserCreatedEvent) => Promise<void> {
  return async (event: UserCreatedEvent): Promise<void> => {
    await emailService.sendWelcome({
      to: event.payload.email,
      name: event.payload.name,
      userId: event.payload.userId,
    });
  };
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
import { buildSendWelcomeEmailHandler } from './handlers/send-welcome-email.handler.js';
import type { EmailService } from '../services/email.service.js';
import { provisionDefaultWorkspaceHandler } from './handlers/provision-default-workspace.handler.js';
import { cancelPendingOrdersHandler } from './handlers/cancel-pending-orders.handler.js';
import { notifyFulfillmentTeamHandler } from './handlers/notify-fulfillment-team.handler.js';

export function registerDomainEventHandlers({ emailService }: { emailService: EmailService }): void {
  eventBus.on('user.created', buildSendWelcomeEmailHandler({ emailService }));
  eventBus.on('user.created', provisionDefaultWorkspaceHandler);
  eventBus.on('user.deactivated', cancelPendingOrdersHandler);
  eventBus.on('order.placed', notifyFulfillmentTeamHandler);
}
```

```typescript
// src/app.ts — call at startup
import { cfg } from './config/cfg.js';
import { db } from './connectors/db.js';
import { SesEmailProviderClient } from './clients/ses-email-provider.client.js';
import { EmailDeliveryRepository } from './domains/email/email-delivery.repository.js';
import { registerDomainEventHandlers } from './events/register-handlers.js';
import { EmailService } from './services/email.service.js';

const emailService: EmailService = new EmailService({
  deliveries: new EmailDeliveryRepository({ db }),
  provider: new SesEmailProviderClient({ region: cfg.awsRegion }),
});
registerDomainEventHandlers({ emailService });
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

- Call the handler directly with a typed event — no bus needed.
- `EmailService` and `EmailDeliveryRepository` are real and use the test database; `resetTestDatabase()` runs in `beforeEach`.
- Only `EmailProviderClient` (third-party) is faked, through an injected class implementing its interface. `msw` against the real provider client is equally valid.
- Assert the persisted delivery row and the recorded provider call; on failure, assert the error and that no row was written.

```typescript
// tests/events/handlers/send-welcome-email.handler.test.ts
import { beforeEach, describe, expect, it } from 'vitest';
import { db } from '@/connectors/db';
import type { EmailProviderClient, ProviderSendInput, ProviderSendResult } from '@/clients/email-provider.client';
import { EmailDeliveryRepository } from '@/domains/email/email-delivery.repository';
import type { UserCreatedEvent } from '@/events/domain-events';
import { buildSendWelcomeEmailHandler } from '@/events/handlers/send-welcome-email.handler';
import { EmailService } from '@/services/email.service';
import { resetTestDatabase } from '../../helpers/db';

/** Third-party fake: records sends and returns a fixed provider message id. */
class RecordingEmailProviderClient implements EmailProviderClient {
  readonly sent: ProviderSendInput[] = [];

  async send(input: ProviderSendInput): Promise<ProviderSendResult> {
    this.sent.push(input);
    return { messageId: 'msg-1' };
  }
}

/** Third-party fake: the provider is unavailable. */
class UnavailableEmailProviderClient implements EmailProviderClient {
  async send(_input: ProviderSendInput): Promise<ProviderSendResult> {
    throw new Error('SMTP unavailable');
  }
}

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

describe('sendWelcomeEmailHandler', (): void => {
  let deliveries: EmailDeliveryRepository;

  const buildHandler = (
    { provider }: { provider: EmailProviderClient },
  ): ((event: UserCreatedEvent) => Promise<void>) =>
    buildSendWelcomeEmailHandler({ emailService: new EmailService({ deliveries, provider }) });

  beforeEach(async (): Promise<void> => {
    await resetTestDatabase();
    deliveries = new EmailDeliveryRepository({ db });
  });

  it('records the delivery and sends the welcome template when a user is created', async (): Promise<void> => {
    const provider: RecordingEmailProviderClient = new RecordingEmailProviderClient();

    await buildHandler({ provider })(buildUserCreatedEvent());

    expect(provider.sent).toEqual([{ to: 'alice@example.com', template: 'welcome', variables: { name: 'Alice' } }]);
    expect(await deliveries.listByUser({ userId: 'user-123' })).toMatchObject([
      { template: 'welcome', providerMessageId: 'msg-1' },
    ]);
  });

  it('propagates the error and records no delivery when the provider is unavailable', async (): Promise<void> => {
    await expect(
      buildHandler({ provider: new UnavailableEmailProviderClient() })(buildUserCreatedEvent()),
    ).rejects.toThrow('SMTP unavailable');

    expect(await deliveries.listByUser({ userId: 'user-123' })).toEqual([]);
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
- [ ] Handlers are built by a factory that receives dependencies through an options object
- [ ] Tests for each handler pass a constructed typed event object and assert the persisted outcome or error
- [ ] Handler tests use real internal services on the test database; only the third-party provider client is faked (injected fake or `msw`)
