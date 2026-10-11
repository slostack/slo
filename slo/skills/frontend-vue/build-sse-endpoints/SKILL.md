---
name: build-sse-endpoints
description: Build Vue browser clients for application Server-Sent Events over fetch and ReadableStream,
  with typed named events, cancellation, and explicit rendering boundaries.
when_to_use: Use when a Vue frontend consumes an application SSE endpoint. Do not use this recipe for
  WebSocket connections or for LangGraph's server-side graph stream APIs.
group: frontend-vue
kind: skill
---

# Build Vue SSE Endpoints

## Scope and provenance

This is a focused companion for browser-facing application Server-Sent Events (SSE). It complements, and does
not replace, `skills/frontend-vue/build-websocket-endpoints/SKILL.md` or the WebSocket tutorial. Choose the
recipe from the actual transport contract: WebSocket is bidirectional; SSE is a server-to-browser stream.

The examples and constraints are provenance-labeled from the requested Sentinel applications, inspected
read-only at revision `f1c093f0ab5a5290daa27ae73371a3e9244b7ca8`:

- `/root/Code/PythonApps/sentinel/medask_admin_app` — admin Vue application, clean worktree.
- `/root/Code/PythonApps/sentinel/medask_doctors_app` — doctors Vue application, clean worktree.

The doctors application specifically uses `fetch` plus `ReadableStream` and named events (`status`, `delta`,
and `control`) in `useMedaskDoctorsChatStream.ts`. It is not evidence that every Vue application should use
SSE. The admin application provides corroborating Vue/TypeScript client and test conventions but does not
provide an SSE contract.

## Transport and event boundaries

Keep these layers distinct:

```text
LangGraph graph.stream / streamEvents (server runtime)
                 │ explicit server projection
                 ▼
application SSE endpoint (event: + data: frames)
                 │ fetch + ReadableStream
                 ▼
Vue composable → typed store actions → components
```

LangGraph graph streaming is not browser SSE. A server may adapt graph events into an application SSE schema,
but the adapter owns that mapping and must be tested separately. Do not pass graph chunks directly to Vue or
claim that Sentinel's `status`/`delta`/`control` events are LangGraph's stream modes.

## Vue client structure

Use the existing Vue family boundaries:

- A real API client owns URL construction, authentication, response/error handling, and request cancellation
  seams. Callers do not construct bearer headers or choose production/mock behavior ad hoc.
- A `use*` composable owns the stream lifecycle, frame parsing, abort cleanup, and mapping named events to
  typed store actions.
- Pinia setup stores own durable conversation/stream state. Components render state and emit user intent.
- Keep a separate mock client when the project has one. A localStorage-backed mock is not a substitute for the
  real HTTP client and must not be described as the runtime path without evidence.

These are observed Sentinel conventions, not universal requirements for unrelated Vue projects. The doctors
application's real `medaskDoctorsApiClient` is the runtime HTTP path; `medaskDoctorsClient` is retained for
mock/test setup. Preserve that distinction in examples and tests.

## Frame contract

Define a discriminated union from the actual backend contract. For the Sentinel doctors evidence, the
application emits named frames shaped like this:

```text
event: status
data: {"type":"status","message":"Searching..."}

event: delta
data: {"type":"delta","text":"Answer text"}

event: control
data: {"type":"completed", "data":{"response":"..."}}
event: control
data: {"type":"done", "request_id":"..."}
event: control
data: {"type":"error", "request_id":"...", "message":"..."}
```

**Sentinel evidence, not a universal wire contract:** dispatch first on the SSE `event:` name, then on the
`type` field for `control` payloads. Validate parsed `unknown` data before dispatching it. Do not silently
assume that an unnamed SSE event has the same shape as a named event or that another backend uses these names.

A minimal contract sketch is intentionally marked unverified here because the parser details (multiline data,
comments, reconnect IDs, retry directives, and cancellation policy) vary by application:

```typescript
interface NamedSseFrame {
  readonly eventName: string;
  readonly data: unknown;
}

interface SseStreamOptions {
  readonly signal?: AbortSignal;
}

async function consumeApplicationSse(
  options: SseStreamOptions,
): Promise<void> {
  // UNVERIFIED EXAMPLE: bind this to the project's real client, parser, and store.
  void options;
}
```

Do not copy this sketch into production without adding runtime validation, a complete SSE parser, and tests for
the chosen wire protocol.

## Cancellation and lifecycle

Every stream must have an explicit cancellation owner. Abort a prior stream before starting another one,
forward an `AbortSignal` to `fetch`, and clean up the active reader/controller when the composable is unmounted
or the conversation changes. Treat normal completion, a server `done`/`completed` control event, abort, malformed
frames, and transport failure as distinct state transitions where the application contract distinguishes them.

Keep one in-flight request per conversation unless the server contract explicitly supports concurrency. The
Sentinel doctors stream gates send actions while `isStreaming` is true and updates the store for both completion
and done control events; this is app evidence, not a universal requirement.

## Rendering and user-content safety

Preserve the application rendering boundary:

- User-entered content is rendered as escaped text, not through `v-html`.
- If assistant Markdown is rendered with `v-html`, configure and test the constrained Markdown renderer. The
  Sentinel doctors application uses `markdown-it` with `html: false`; raw HTML is escaped before the constrained
  assistant output reaches `v-html`.
- `html: false` is an evidence-backed Sentinel contract, not a license to use `v-html` for arbitrary content.
  A different renderer requires its own sanitizer and security review.

The WebSocket skill's message rendering and lifecycle examples remain valid for WebSocket consumers; do not
copy them into an SSE composable without adapting the transport and preserving this content boundary.

## Verification

For an SSE feature, run the target project's checks and distinguish them:

1. parser/composable tests using deterministic `ReadableStream<Uint8Array>` fixtures;
2. store/component tests for each named event and terminal/error path;
3. real-client boundary tests with `fetch` stubs or a test server;
4. mock-client tests, when the project intentionally retains a mock path; and
5. the strict TypeScript/Vue build gate (`vue-tsc -b` where configured), separately from Vitest.

The Sentinel doctors README states that its configured automated tests do not provide browser E2E coverage.
Do not report component/composable tests as browser-E2E verification. Nginx/proxy buffering and timeout
settings require deployment-specific verification and are not established by a green frontend suite.

## Checklist

- [ ] Transport selected from the actual contract: SSE, not WebSocket by assumption.
- [ ] LangGraph graph streaming, application projection, and browser SSE are documented as separate layers.
- [ ] `unknown` frame data is runtime-validated before use.
- [ ] Named events and terminal/error paths have focused tests.
- [ ] Abort and unmount cleanup are covered.
- [ ] Real API and mock client paths are explicitly distinguished.
- [ ] User content remains escaped.
- [ ] Assistant `v-html`, if used, is downstream of a constrained, tested renderer such as `html: false`.
- [ ] `vue-tsc -b` or the project's equivalent build gate passes independently of Vitest.
- [ ] Browser E2E and deployment/proxy claims are reported only when actually verified.

## Skill summary

Use this focused recipe for browser-facing application SSE consumed by Vue. Keep the server graph projection, SSE wire frames, composable lifecycle, store state, and component rendering as separate contracts, and do not substitute WebSocket or server-side LangGraph stream guidance.

## Examples

- Select SSE from the actual one-way server-to-browser contract, parse named events from a `ReadableStream`, validate `unknown` payloads, and dispatch typed store actions.
- Abort the prior request before starting another, pass the signal to `fetch`, and cover completion, done/control, malformed-frame, abort, unmount, and transport-failure paths.
- Test the graph-to-SSE projection separately from the browser parser and keep real-client, mock-client, and strict `vue-tsc -b` evidence distinct.

## Guidance

Start with the backend frame contract and the ownership of cancellation. Preserve escaped user content and a constrained assistant renderer, then verify each transport, lifecycle, event, and build boundary in the target project. Sentinel observations are evidence for their named applications, not universal wire or dependency choices.
