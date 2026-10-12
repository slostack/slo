---
name: typescript-build-clients
description: Build typed HTTP API client classes with a private makeRequest base, Zod response parsing,
  typed exceptions, and no caller-managed auth.
when_to_use: Use when writing a TypeScript client for an external or internal HTTP API, wrapping fetch/axios,
  or encapsulating vendor API calls.
group: languages
kind: skill
---

# TypeScript Build Clients

## Skill summary

- **Name:** `typescript-build-clients`
- **Description:** Build typed HTTP API client classes with a private makeRequest base, Zod response parsing, typed exceptions, and no caller-managed auth.
- **When to use:** Use when writing a TypeScript client for an external or internal HTTP API, wrapping fetch/axios, or encapsulating vendor API calls.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "create an HTTP client for the GitHub API with typed methods for listing repos and creating issues"
- "build a client class for the Stripe API that wraps makeRequest and parses responses with Zod"
- "write an API client for our internal notifications service"

## Guidance

**Scope:** TypeScript; load `skills/languages/typescript/typescript-conventions/SKILL.md`. Framework examples apply only to the declared stack. This is a vendored snapshot; installed same-name user skills still override it in the runtime manifest.

API clients in TypeScript mirror the Python convention: a class with one private `makeRequest` base method and typed public methods that each wrap a specific endpoint. Callers never manage auth headers, retry logic, or base URLs — the client owns all of that.

### Core rules

1. **One private `makeRequest` method** — all HTTP logic (headers, retries, error detection) lives there.
2. **Public methods are typed wrappers** — they call `makeRequest` with the correct path and parse the response through a Zod schema.
3. **The client manages auth** — `baseUrl` and `apiKey` (or token) are constructor arguments; callers never pass auth.
4. **Zod parses at the boundary** — response bodies are validated before being returned as typed DTOs.
5. **Typed exceptions only** — `makeRequest` throws `VendorApiError` (or a subclass); it never leaks raw `fetch` errors or plain `Error` objects.
6. **Retry logic lives in `makeRequest`** — individual methods never implement their own retry loops.
7. **No `any` in return types** — every public method declares a concrete return type.

---

### Typed exception

```typescript
// src/clients/stripe/stripe.errors.ts

export interface StripeApiErrorBody {
  error: {
    code: string;
    message: string;
    type: string;
  };
}

export class StripeApiError extends Error {
  constructor(
    public readonly statusCode: number,
    public readonly code: string,
    message: string,
    public readonly raw: unknown,
  ) {
    super(message);
    this.name = 'StripeApiError';
  }

  static fromResponse(statusCode: number, body: StripeApiErrorBody): StripeApiError {
    return new StripeApiError(
      statusCode,
      body.error.code,
      body.error.message,
      body,
    );
  }
}
```

---

### Request/response Zod schemas (DTOs)

```typescript
// src/clients/stripe/stripe.schemas.ts
import { z } from 'zod';

export const CustomerSchema = z.object({
  id: z.string(),
  email: z.string().email(),
  name: z.string().nullable(),
  created: z.number(),
  metadata: z.record(z.string()).default({}),
});

export type CustomerDTO = z.infer<typeof CustomerSchema>;

export const CreateCustomerRequestSchema = z.object({
  email: z.string().email(),
  name: z.string().optional(),
  metadata: z.record(z.string()).optional(),
});

export type CreateCustomerRequest = z.infer<typeof CreateCustomerRequestSchema>;

export const PaymentIntentSchema = z.object({
  id: z.string(),
  amount: z.number(),
  currency: z.string(),
  status: z.enum(['requires_payment_method', 'requires_confirmation', 'succeeded', 'canceled']),
  client_secret: z.string(),
});

export type PaymentIntentDTO = z.infer<typeof PaymentIntentSchema>;

export const CreatePaymentIntentRequestSchema = z.object({
  amount: z.number().int().positive(),
  currency: z.string().length(3),
  customer: z.string().optional(),
});

export type CreatePaymentIntentRequest = z.infer<typeof CreatePaymentIntentRequestSchema>;
```

---

### Base client class with `makeRequest`

```typescript
// src/clients/stripe/stripe.client.ts
import { z, ZodSchema } from 'zod';
import { StripeApiError, type StripeApiErrorBody } from './stripe.errors.js';
import {
  CustomerSchema,
  CreatePaymentIntentRequestSchema,
  PaymentIntentSchema,
  type CustomerDTO,
  type CreateCustomerRequest,
  type CreatePaymentIntentRequest,
  type PaymentIntentDTO,
} from './stripe.schemas.js';

const DEFAULT_BASE_URL = 'https://api.stripe.com/v1';
const DEFAULT_TIMEOUT_MS = 10_000;

interface MakeRequestOptions {
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  path: string;
  body?: Record<string, unknown>;
  params?: Record<string, string>;
}

export class StripeClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;

  constructor(options: {
    apiKey: string;
    baseUrl?: string;
    timeoutMs?: number;
  }) {
    this.apiKey = options.apiKey;
    this.baseUrl = options.baseUrl ?? DEFAULT_BASE_URL;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  // ------------------------------------------------------------------
  // Private base method — all HTTP logic is centralized here.
  // ------------------------------------------------------------------

  private async makeRequest<T>(
    options: MakeRequestOptions,
    responseSchema: ZodSchema<T>,
  ): Promise<T> {
    const url = new URL(`${this.baseUrl}${options.path}`);

    if (options.params) {
      for (const [key, value] of Object.entries(options.params)) {
        url.searchParams.set(key, value);
      }
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs);

    let response: Response;
    try {
      response = await fetch(url.toString(), {
        method: options.method,
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          'Content-Type': 'application/x-www-form-urlencoded',
          'Stripe-Version': '2024-04-10',
        },
        body:
          options.body != null
            ? new URLSearchParams(
                Object.entries(options.body).reduce<Record<string, string>>(
                  (acc, [k, v]) => ({ ...acc, [k]: String(v) }),
                  {},
                ),
              )
            : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      // Network / timeout errors — wrap before leaking to callers.
      throw new StripeApiError(
        0,
        'NETWORK_ERROR',
        err instanceof Error ? err.message : 'Network request failed',
        err,
      );
    } finally {
      clearTimeout(timeoutId);
    }

    const rawBody: unknown = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw StripeApiError.fromResponse(
        response.status,
        rawBody as StripeApiErrorBody,
      );
    }

    // Parse and validate at the boundary — never return unvalidated JSON.
    return responseSchema.parse(rawBody);
  }

  // ------------------------------------------------------------------
  // Public typed methods — thin wrappers over makeRequest.
  // ------------------------------------------------------------------

  async getCustomer(customerId: string): Promise<CustomerDTO> {
    return this.makeRequest(
      { method: 'GET', path: `/customers/${customerId}` },
      CustomerSchema,
    );
  }

  async createCustomer(request: CreateCustomerRequest): Promise<CustomerDTO> {
    return this.makeRequest(
      {
        method: 'POST',
        path: '/customers',
        body: request as Record<string, unknown>,
      },
      CustomerSchema,
    );
  }

  async createPaymentIntent(
    request: CreatePaymentIntentRequest,
  ): Promise<PaymentIntentDTO> {
    return this.makeRequest(
      {
        method: 'POST',
        path: '/payment_intents',
        body: request as Record<string, unknown>,
      },
      PaymentIntentSchema,
    );
  }

  async cancelPaymentIntent(paymentIntentId: string): Promise<PaymentIntentDTO> {
    return this.makeRequest(
      { method: 'POST', path: `/payment_intents/${paymentIntentId}/cancel` },
      PaymentIntentSchema,
    );
  }
}
```

---

### Instantiation pattern (dependency injection)

```typescript
// src/lib/clients.ts — singleton factory, injected into services
import { StripeClient } from '../clients/stripe/stripe.client.js';

let _stripeClient: StripeClient | null = null;

export function getStripeClient(): StripeClient {
  if (!_stripeClient) {
    const apiKey = process.env.STRIPE_API_KEY;
    if (!apiKey) throw new Error('STRIPE_API_KEY is not set');
    _stripeClient = new StripeClient({ apiKey });
  }
  return _stripeClient;
}
```

---

### Retry variant for `makeRequest`

When external APIs need retry, add it inside `makeRequest` using exponential backoff — never in individual methods:

```typescript
private async makeRequest<T>(
  options: MakeRequestOptions,
  responseSchema: ZodSchema<T>,
  retries = 3,
): Promise<T> {
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      return await this._doRequest(options, responseSchema);
    } catch (err) {
      if (err instanceof StripeApiError && err.statusCode >= 500 && attempt < retries) {
        await new Promise((r) => setTimeout(r, 2 ** attempt * 100));
        continue;
      }
      throw err;
    }
  }
  throw new Error('unreachable');
}
```

---

### Client file checklist

Before finishing a client, verify:

- [ ] Constructor accepts `baseUrl` and auth credentials — no env vars read inline in methods
- [ ] One `makeRequest` (or `_doRequest`) method holds all fetch logic
- [ ] Every public method has an explicit return type (`Promise<UserDTO>`, not `Promise<any>`)
- [ ] Responses are parsed through a Zod schema before being returned
- [ ] All thrown errors are wrapped in a typed exception class — no raw `Error` or raw fetch errors
- [ ] Retry logic (if any) lives in `makeRequest`, not in individual methods
- [ ] No `any` type assertions on response bodies
