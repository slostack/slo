---
name: go-build-clients
description: "How to build an idiomatic Go client for a third-party or internal HTTP API (payments vendor,\
  \ telephony, microservice) \u2014 a client struct built with functional options, context-first typed\
  \ methods, JSON encode/decode helpers, typed errors with status-code mapping and retry/backoff, and\
  \ a consumer-side interface for mocking with httptest."
when_to_use: "Use when writing or reviewing any Go client that talks to an external HTTP API or internal\
  \ service \u2014 Twilio/Nuvei-style vendor clients, payment gateways, or service-to-service calls. Read\
  \ before adding a new integration package."
group: languages
kind: skill
---

# Build Go API Clients

## Skill summary

- **Name:** `go-build-clients`
- **Description:** Idiomatic Go translation of the external-API-client convention.
  A client struct built with functional options (base URL, `*http.Client` with
  timeouts, auth, retry policy), context-first methods with typed request/response
  structs, shared JSON encode/decode helpers, typed errors with status-code
  mapping and backoff, and a **consumer-side interface** so the client can be
  mocked in tests with `net/http/httptest`.
- **When to use:** Use when building or reviewing any Go client for a third-party
  or internal HTTP API.
- **Group:** `languages`
- **Kind:** `skill`

## Examples

- "Write a Go client for the Nuvei payments API."
- "Add a client for our internal ledger microservice."
- "How do I add retry/backoff to this vendor client?"
- "Mock this payment client in a test with httptest."
- "Review this Go integration package for convention violations."
- "What's the Go equivalent of our Python `make_request()` client base class?"
- "Set up the integrations/telephony package."

---

## Guidance

**Scope and authority:** Go; read `skills/languages/go/go-conventions/SKILL.md` first. This recipe is a reconciled snapshot of installed guidance, not permission to adopt a dependency. Framework-specific examples apply only to a project already using that stack. Select the test category with `skills/engineering/engineering-testing/SKILL.md`.

This is the Go translation of the stack-wide "Build External API Clients"
convention. The Python original centers on an async class with a `make_request()`
base method, Pydantic request/response DAOs, custom exception classes, and
`aiohttp`/`httpx` sessions. The Go idioms below preserve every underlying
principle — single request path, typed boundaries, rich typed errors, auth
masking, retry-on-transient, testability — but express them the Go way.

Defer to **`go-conventions`** for all naming, godoc, declarative
structure, functional-options, and error-wrapping rules — this skill only adds
the client-specific patterns on top. Domain methods that consume a client belong
in an application service; see **`go-build-application-services`** for the
`Execute()` orchestration boundary.

### Python → Go idiom map

| Python original | Go equivalent | Why |
|---|---|---|
| `class XAPIClient` + `__init__(cfg())` | `type Client struct` + `New(baseURL, opts...)` functional options | No hidden global config read; deps injected explicitly |
| async `make_request()` dispatch on method string | one private `do()` method taking a built `*http.Request` | Go's `http.Client.Do` already dispatches by verb |
| `aiohttp`/`httpx.AsyncClient` per call | one long-lived `*http.Client` on the struct | Connection pooling + configurable timeout |
| Pydantic request/response DAOs | typed structs with `json:"..."` tags + `validator` | Compile-time typed boundary |
| custom `XAPIError` exception classes | typed `*APIError` + sentinel `error` vars | `errors.Is`/`errors.As` at call sites |
| `asyncio.sleep` retry loop | retry loop keyed on `ctx` + backoff | Context cancellation, not a bare sleep |
| `unittest.mock.patch` on `make_request` | consumer-side interface + `httptest.Server` | Mock the boundary, exercise the real transport |

---

## Section 1 — Package Layout

Mirror the Python `src/integrations/<service>/` layout. One integration = one
package under `internal/integrations/`.

```
internal/integrations/nuvei/
├── client.go        # Client struct, New(), functional options, do() helper
├── options.go       # ClientOption functions (optional; may live in client.go)
├── errors.go        # APIError type + sentinel error vars
├── models.go        # typed request/response structs (the DAO analog)
├── payments.go      # domain methods: Authorize, Capture, Refund, ...
└── client_test.go   # table-driven tests against httptest.Server
```

Rules:
- Package name is the vendor/service, lowercase, no `client` suffix: `nuvei`, not
  `nuveiclient`. The type is `nuvei.Client`, read at the call site as
  `nuvei.New(...)`.
- No file reads config directly. Config is passed in by the caller (from the
  `config` package) as constructor arguments/options.

---

## Section 2 — The Client Struct and Functional Options

The Python `__init__` loaded `base_url`, `api_key`, `timeout`, retry counts from
`cfg()`. In Go, the required value (base URL) is a positional argument; everything
optional is a **functional option** (see `go-conventions`). This
keeps the call site self-documenting and makes the `*http.Client`, timeout, auth,
and retry policy injectable — which is what makes the client testable.

```go
// Package nuvei provides a client for the Nuvei payments API.
package nuvei

import (
	"log/slog"
	"net/http"
	"time"
)

// Client talks to the Nuvei payments API. It is safe for concurrent use;
// the underlying *http.Client pools connections across goroutines.
type Client struct {
	baseURL    string
	httpClient *http.Client
	apiKey     string
	maxRetries int
	backoff    time.Duration
	logger     *slog.Logger
}

// ClientOption configures a Client. Apply options with New.
type ClientOption func(*Client)

// WithHTTPClient overrides the default *http.Client (e.g. to inject a
// custom transport, proxy, or a test server's client).
func WithHTTPClient(hc *http.Client) ClientOption {
	return func(c *Client) { c.httpClient = hc }
}

// WithTimeout sets the per-request timeout on the default HTTP client.
// Ignored if WithHTTPClient supplies a client with its own Timeout.
func WithTimeout(d time.Duration) ClientOption {
	return func(c *Client) { c.httpClient.Timeout = d }
}

// WithRetries sets the maximum retry attempts for transient failures
// (5xx and 429). The default is 3.
func WithRetries(n int) ClientOption {
	return func(c *Client) { c.maxRetries = n }
}

// WithBackoff sets the base delay between retry attempts. The default is
// 200ms and grows linearly per attempt.
func WithBackoff(d time.Duration) ClientOption {
	return func(c *Client) { c.backoff = d }
}

// WithLogger sets the structured logger. The default discards output.
func WithLogger(l *slog.Logger) ClientOption {
	return func(c *Client) { c.logger = l }
}

// New creates a Nuvei client. baseURL and apiKey are required; all other
// behaviour is configured through options.
//
// Returns a ready-to-use client with sane defaults: a 30s HTTP timeout,
// 3 retries, and 200ms base backoff.
// ConfigDAO carries required client configuration.
type ConfigDAO struct {
    BaseURL string
    APIKey string
}

func New(in ConfigDAO, opts ...ClientOption) *Client {
    baseURL, apiKey := in.BaseURL, in.APIKey
	c := &Client{
		baseURL:    baseURL,
		apiKey:     apiKey,
		httpClient: &http.Client{Timeout: 30 * time.Second},
		maxRetries: 3,
		backoff:    200 * time.Millisecond,
		logger:     slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	for _, opt := range opts {
		opt(c)
	}
	return c
}
```

```go
// Bad — reads globals, no timeout, not injectable, not testable
func NewClient() *Client {
	return &Client{
		baseURL:    os.Getenv("NUVEI_BASE_URL"), // hidden dependency
		apiKey:     os.Getenv("NUVEI_API_KEY"),
		httpClient: http.DefaultClient,          // no timeout — will hang forever
	}
}

// Good — explicit args, defaults, injectable HTTP client
c := nuvei.New(nuvei.ConfigDAO{BaseURL: cfg.NuveiBaseURL, APIKey: cfg.NuveiAPIKey},
	nuvei.WithTimeout(15*time.Second),
	nuvei.WithRetries(5),
	nuvei.WithLogger(appLogger),
)
```

Never use `http.DefaultClient` or `http.Get`/`http.Post` in a client — they have
no timeout and cannot be configured. Always own a `*http.Client`.

---

## Section 3 — The Single Request Path (`do`)

The Python client routed everything through `make_request()`. The Go equivalent
is one unexported generic `doJSON` helper that: builds the request with context,
sets auth + content-type headers, retries transient failures, maps status codes
to typed errors, and decodes the JSON body into a caller-supplied target. Every
domain method calls this — one place for auth, retries, logging, and error
mapping.

```go
package nuvei

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"
)

// doJSON executes an HTTP request with retries and decodes the JSON response
// body into out (which may be nil for empty-body responses).
//
// body may be nil for GET/DELETE. Retries are attempted for 5xx and 429
// responses and for transport errors, up to the client's maxRetries. Returns
// an *APIError carrying the status code and response body on a non-2xx final
// response, or a wrapped transport error.
func doJSON[Req any, Resp any](
	ctx context.Context,
	c *Client,
	method, path string,
	body *Req,
	out *Resp,
) error {
	var lastErr error

	for attempt := 0; attempt <= c.maxRetries; attempt++ {
		if attempt > 0 {
			if err := sleepWithContext(ctx, c.backoff*time.Duration(attempt)); err != nil {
				return err // context cancelled/expired during backoff
			}
			c.logger.WarnContext(ctx, "retrying nuvei request",
				slog.String("method", method), slog.String("path", path),
				slog.Int("attempt", attempt))
		}

		resp, err := c.send(ctx, method, path, body)
		if err != nil {
			lastErr = err
			continue // transport error — retry
		}

		decoded, retry, err := handleResponse(resp, out)
		if retry {
			lastErr = err
			continue // retryable status — retry
		}
		if err != nil {
			return err // non-retryable API error or decode error
		}
		_ = decoded
		return nil
	}

	return fmt.Errorf("nuvei %s %s: exhausted %d retries: %w",
		method, path, c.maxRetries, lastErr)
}

// send builds and executes a single HTTP attempt. It sets authentication and
// content-type headers and masks the API key in logs.
func (c *Client) send(ctx context.Context, method, path string, body any) (*http.Response, error) {
	var reader io.Reader
	if body != nil {
		buf, err := json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("encoding request body: %w", err)
		}
		reader = bytes.NewReader(buf)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return nil, fmt.Errorf("building request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")

	// Auth header is never logged — mask it.
	c.logger.DebugContext(ctx, "nuvei request",
		slog.String("method", method), slog.String("path", path))

	return c.httpClient.Do(req)
}

// handleResponse maps an HTTP response to a typed outcome.
//
// It returns (true, retry=true, err) for retryable statuses (5xx, 429),
// (false, retry=false, *APIError) for non-retryable non-2xx statuses, and
// decodes the body into out for 2xx responses.
func handleResponse[Resp any](resp *http.Response, out *Resp) (decoded bool, retry bool, err error) {
	defer resp.Body.Close()

	raw, readErr := io.ReadAll(io.LimitReader(resp.Body, 1<<20)) // cap at 1MB
	if readErr != nil {
		return false, false, fmt.Errorf("reading response body: %w", readErr)
	}

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		if out == nil || len(raw) == 0 || resp.StatusCode == http.StatusNoContent {
			return true, false, nil
		}
		if err := json.Unmarshal(raw, out); err != nil {
			return false, false, fmt.Errorf("decoding response: %w (body: %s)", err, raw)
		}
		return true, false, nil
	}

	apiErr := newAPIError(resp.StatusCode, raw)
	if isRetryable(resp.StatusCode) {
		return false, true, apiErr
	}
	return false, false, apiErr
}

// isRetryable reports whether a status code warrants a retry.
func isRetryable(status int) bool {
	return status >= 500 || status == http.StatusTooManyRequests
}

// sleepWithContext sleeps for d unless ctx is cancelled first.
func sleepWithContext(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}
```

Key differences from the Python:
- **No method-string dispatch.** `http.Client.Do` already handles the verb; the
  Python `if method == METHOD_GET: ...` chain has no place in Go.
- **Retry loop is context-aware.** Backoff uses `sleepWithContext`, not a bare
  `time.Sleep` — a cancelled context stops retries immediately (§7 of
  `go-conventions`).
- **Body is read once, size-capped** with `io.LimitReader` to avoid unbounded
  memory from a hostile/broken upstream.

---

## Section 4 — Typed Errors (the Exception-Class Analog)

Python defined `XAPIError`, `XMissingAPIKeyError`, etc. Go uses one struct type
carrying rich context plus sentinel `var`s for known conditions, so callers use
`errors.As` / `errors.Is`.

```go
// Package-level sentinels for known failure conditions.
var (
	// ErrUnauthorized indicates the API rejected the credentials (401/403).
	ErrUnauthorized = errors.New("nuvei: unauthorized")
	// ErrNotFound indicates the requested resource does not exist (404).
	ErrNotFound = errors.New("nuvei: resource not found")
	// ErrRateLimited indicates the caller exceeded the rate limit (429).
	ErrRateLimited = errors.New("nuvei: rate limited")
)

// APIError carries the context of a failed Nuvei API call. It is returned for
// any non-2xx response and wraps a matching sentinel where one applies.
type APIError struct {
	StatusCode int
	Body       string // raw response body, for diagnostics
	sentinel   error  // one of the Err* sentinels, or nil
}

// Error implements the error interface.
func (e *APIError) Error() string {
	return fmt.Sprintf("nuvei: status %d: %s", e.StatusCode, e.Body)
}

// Unwrap enables errors.Is against the sentinel errors.
func (e *APIError) Unwrap() error { return e.sentinel }

// newAPIError builds an APIError and maps well-known status codes to sentinels.
func newAPIError(status int, body []byte) *APIError {
	e := &APIError{StatusCode: status, Body: string(body)}
	switch status {
	case http.StatusUnauthorized, http.StatusForbidden:
		e.sentinel = ErrUnauthorized
	case http.StatusNotFound:
		e.sentinel = ErrNotFound
	case http.StatusTooManyRequests:
		e.sentinel = ErrRateLimited
	}
	return e
}
```

Call sites get both the typed detail and the semantic category:

```go
// Good — semantic branch via sentinel, detail via typed error
resp, err := client.Authorize(ctx, req)
if errors.Is(err, nuvei.ErrRateLimited) {
	return scheduleRetryLater()
}
var apiErr *nuvei.APIError
if errors.As(err, &apiErr) {
	logger.Error("nuvei declined", slog.Int("status", apiErr.StatusCode))
}
```

```go
// Bad — string matching on the error message; brittle, unwrappable
if strings.Contains(err.Error(), "429") { ... }
```

---

## Section 5 — Typed Request/Response Structs (the DAO Analog)

The Pydantic DAOs become plain structs with `json` tags. Request DTOs carry
`validate` tags for `go-playground/validator` (the Pydantic-validation analog);
validate before sending. Follow ubiquitous language (§1.4 of
`go-conventions`): field names and JSON tags match the vendor's wire
names exactly — no synonyms.

```go
// AuthorizeRequest is the payload for a payment authorization.
type AuthorizeRequest struct {
	MerchantID  string `json:"merchant_id"   validate:"required"`
	AmountCents int64  `json:"amount_cents"  validate:"required,gt=0"`
	Currency    string `json:"currency"      validate:"required,iso4217"`
	CardToken   string `json:"card_token"    validate:"required"`
}

// AuthorizeResponse is the vendor's authorization result.
type AuthorizeResponse struct {
	TransactionID string `json:"transaction_id"`
	Status        string `json:"status"` // e.g. "APPROVED", "DECLINED"
	AuthCode      string `json:"auth_code"`
}
```

Use `int64` cents for money — never `float64` for currency amounts.

---

## Section 6 — Domain Methods

Each vendor operation is a thin, context-first method that builds the typed
request, validates it, and delegates to `doJSON`. This is the "domain-specific
methods" section of the Python original.

```go
import "github.com/go-playground/validator/v10"

var validate = validator.New()

// Authorize places a hold on the given card for the requested amount.
//
// Returns ErrUnauthorized if credentials are rejected, ErrRateLimited on a
// 429, or an *APIError carrying the status code for any other non-2xx response.
func (c *Client) Authorize(ctx context.Context, req AuthorizeRequest) (*AuthorizeResponse, error) {
	if err := validate.Struct(req); err != nil {
		return nil, fmt.Errorf("invalid authorize request: %w", err)
	}

	var out AuthorizeResponse
	if err := doJSON(ctx, c, http.MethodPost, "/v1/payments/authorize", &req, &out); err != nil {
		return nil, fmt.Errorf("nuvei authorize: %w", err)
	}
	return &out, nil
}

// Capture settles a previously authorized transaction.
//
// Returns ErrNotFound if the transaction ID is unknown.
func (c *Client) Capture(ctx context.Context, txID string) (*CaptureResponse, error) {
	if txID == "" {
		return nil, errors.New("nuvei capture: transaction ID is required")
	}
	var out CaptureResponse
	path := "/v1/payments/" + txID + "/capture"
	if err := doJSON[struct{}](ctx, c, http.MethodPost, path, nil, &out); err != nil {
		return nil, fmt.Errorf("nuvei capture %s: %w", txID, err)
	}
	return &out, nil
}
```

Every method takes `ctx context.Context` first (§7 of
`go-conventions`). No method touches `http` directly; all go through
`doJSON`.

---

## Section 7 — The Consumer-Side Interface (Testability)

The Python tests `patch`ed `make_request`. In Go, mock the **boundary the
consumer depends on**, not the client internals. The consuming package (an
application service — see `go-build-application-services`) defines a **minimal
local interface** listing only the methods it calls (§6 of
`go-conventions`: define interfaces at the consumer). The real
`*nuvei.Client` satisfies it; a hand-written fake satisfies it in tests.

```go
// internal/app/checkout/service.go
package checkout

// paymentClient is the subset of the payment vendor client this service needs.
// Defined here, at the consumer — not in the nuvei package.
type paymentClient interface {
	Authorize(ctx context.Context, req nuvei.AuthorizeRequest) (*nuvei.AuthorizeResponse, error)
	Capture(ctx context.Context, txID string) (*nuvei.CaptureResponse, error)
}

// Service orchestrates checkout against a payment client.
type Service struct {
	payments paymentClient
}

// NewService wires the checkout service to a payment client.
func NewService(payments paymentClient) *Service {
	return &Service{payments: payments}
}
```

Because the dependency is an interface, `checkout.Service` can be unit-tested with
a trivial fake, and the `nuvei.Client` itself is integration-tested against
`httptest` (§8).

---

## Section 8 — Testing with httptest

Test the client end-to-end against a real HTTP server (`httptest.Server`) instead
of mocking the transport. This exercises the actual request building, header
setting, retry loop, status mapping, and JSON decoding — the parts most likely to
break. Table-driven, one decision per case (§1.5 of `go-conventions`).

```go
package nuvei_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestClient_Authorize(t *testing.T) {
	tests := []struct {
		name       string
		handler    http.HandlerFunc
		wantStatus string
		wantErrIs  error
	}{
		{
			name: "approves on 200",
			handler: func(w http.ResponseWriter, r *http.Request) {
				assert.Equal(t, "Bearer test-key", r.Header.Get("Authorization"))
				assert.Equal(t, "/v1/payments/authorize", r.URL.Path)
				w.WriteHeader(http.StatusOK)
				_, _ = w.Write([]byte(`{"transaction_id":"tx_1","status":"APPROVED"}`))
			},
			wantStatus: "APPROVED",
		},
		{
			name: "maps 401 to ErrUnauthorized",
			handler: func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(http.StatusUnauthorized)
				_, _ = w.Write([]byte(`{"error":"bad key"}`))
			},
			wantErrIs: nuvei.ErrUnauthorized,
		},
		{
			name: "maps 429 to ErrRateLimited",
			handler: func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(http.StatusTooManyRequests)
			},
			wantErrIs: nuvei.ErrRateLimited,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(tc.handler)
			defer srv.Close()

			// No backoff and zero retries keep the failure cases fast.
			client := nuvei.New(nuvei.ConfigDAO{BaseURL: srv.URL, APIKey: "test-key"},
				nuvei.WithHTTPClient(srv.Client()),
				nuvei.WithRetries(0),
			)

			resp, err := client.Authorize(context.Background(), nuvei.AuthorizeRequest{
				MerchantID:  "m1",
				AmountCents: 1000,
				Currency:    "USD",
				CardToken:   "tok_1",
			})

			if tc.wantErrIs != nil {
				assert.ErrorIs(t, err, tc.wantErrIs)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tc.wantStatus, resp.Status)
		})
	}
}

// TestClient_Authorize_RetriesOn5xx asserts the retry loop recovers from a
// transient 500 followed by a 200.
func TestClient_Authorize_RetriesOn5xx(t *testing.T) {
	var calls int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if calls == 1 {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"transaction_id":"tx_2","status":"APPROVED"}`))
	}))
	defer srv.Close()

	client := nuvei.New(nuvei.ConfigDAO{BaseURL: srv.URL, APIKey: "test-key"},
		nuvei.WithHTTPClient(srv.Client()),
		nuvei.WithRetries(2),
		nuvei.WithBackoff(time.Millisecond),
	)

	resp, err := client.Authorize(context.Background(), nuvei.AuthorizeRequest{
		MerchantID: "m1", AmountCents: 1000, Currency: "USD", CardToken: "tok_1",
	})
	require.NoError(t, err)
	assert.Equal(t, "APPROVED", resp.Status)
	assert.Equal(t, 2, calls, "expected one retry after the transient 500")
}
```

To unit-test a **consumer** (e.g. `checkout.Service`) without any HTTP, write a
fake that satisfies the consumer-local interface from §7:

```go
type fakePaymentClient struct {
	authorizeFn func(ctx context.Context, req nuvei.AuthorizeRequest) (*nuvei.AuthorizeResponse, error)
}

func (f *fakePaymentClient) Authorize(ctx context.Context, req nuvei.AuthorizeRequest) (*nuvei.AuthorizeResponse, error) {
	return f.authorizeFn(ctx, req)
}
func (f *fakePaymentClient) Capture(ctx context.Context, txID string) (*nuvei.CaptureResponse, error) {
	return nil, errors.New("not implemented")
}

func TestCheckout_DeclinedPayment(t *testing.T) {
	fake := &fakePaymentClient{
		authorizeFn: func(ctx context.Context, req nuvei.AuthorizeRequest) (*nuvei.AuthorizeResponse, error) {
			return nil, nuvei.ErrRateLimited
		},
	}
	svc := checkout.NewService(fake)
	_, err := svc.PlaceOrder(context.Background(), someOrder)
	assert.ErrorIs(t, err, nuvei.ErrRateLimited)
}
```

Two levels, two tools: `httptest` for the client's transport, a plain fake for
its consumers. Neither reaches into client internals.

---

## Section 9 — Logging and Secret Masking

Same rules as the Python original, via `log/slog`:

- Log request start at `Debug` with method + path; never log the `Authorization`
  header, API key, card token, or PAN. In §3 the auth header is set on the
  request but never passed to the logger.
- Log retries at `Warn` with attempt number and status.
- Log final exhaustion at `Error`.
- Attach a request-scoped logger via `slog.With(...)` where a correlation ID is
  available.

```go
// Bad — leaks the API key into logs
c.logger.Debug("request", slog.String("auth", req.Header.Get("Authorization")))

// Good — no secrets, structured fields
c.logger.DebugContext(ctx, "nuvei request",
	slog.String("method", method), slog.String("path", path))
```

---

## Checklist

Run through before merging a Go client package. Each unchecked item is a blocker.

### Construction
- [ ] Client owns a configured `*http.Client` with a timeout — never
      `http.DefaultClient` or `http.Get`/`http.Post`.
- [ ] Required values are constructor args; optional config is **functional
      options** (`WithTimeout`, `WithRetries`, `WithHTTPClient`, ...).
- [ ] `WithHTTPClient` exists so tests can inject `httptest`'s client.
- [ ] No config is read from globals/env inside the package.

### Request path
- [ ] Exactly one shared request path (`doJSON`/`do`); domain methods delegate to
      it — no per-method `http` calls.
- [ ] Every method takes `ctx context.Context` first and builds requests with
      `http.NewRequestWithContext`.
- [ ] Retries cover only transient failures (5xx, 429); backoff uses the context,
      not a bare `time.Sleep`.
- [ ] Response body read once, size-capped with `io.LimitReader`, and closed.

### Types & errors
- [ ] Request/response structs are typed with `json` tags matching the wire names
      (ubiquitous language — no synonyms).
- [ ] Request DTOs validated (`go-playground/validator`) before sending.
- [ ] Non-2xx returns a typed `*APIError` with status + body; well-known statuses
      map to sentinel errors usable with `errors.Is`.
- [ ] Money uses integer cents, never `float64`.

### Testability
- [ ] Consumers depend on a **consumer-local interface**, not `*Client` directly.
- [ ] Client is tested against `httptest.Server` (success, status mapping, retry).
- [ ] Consumers are tested with a fake satisfying the local interface.
- [ ] Tests are table-driven; each case asserts one decision point.

### Logging
- [ ] Uses `log/slog`; never logs the auth header, API key, or card data.
- [ ] Retries logged at `Warn`, exhaustion at `Error`, request start at `Debug`.

---

See also: `go-conventions` (functional options, error wrapping,
consumer-side interfaces, table-driven tests) and `go-build-application-services`
(the `Execute()` orchestrator that consumes these clients).
