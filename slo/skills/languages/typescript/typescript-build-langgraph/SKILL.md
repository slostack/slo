---
name: typescript-build-langgraph
description: Build typed LangGraph JavaScript/TypeScript state graphs with explicit state, nodes, routing,
  persistence, streaming, and Vitest verification boundaries.
when_to_use: Use when implementing or reviewing LangGraph graphs in JavaScript or TypeScript. Do not use this
  recipe for Python LangGraph code or for browser transport code.
group: languages
kind: skill
---

# Build LangGraph Graphs in TypeScript

## Scope and provenance

This is a **TypeScript-only** companion to the Python LangGraph recipe. It is not a mechanical translation:
use the current JavaScript/TypeScript API documented by LangChain, then verify the selected package versions in
the target project's lockfile.

**Official source consulted on 2026-10-10 (UTC):**

- [LangGraph overview](https://docs.langchain.com/oss/javascript/langgraph/overview)
- [Quickstart](https://docs.langchain.com/oss/javascript/langgraph/quickstart)
- [Use the graph API](https://docs.langchain.com/oss/javascript/langgraph/use-graph-api)
- [Memory](https://docs.langchain.com/oss/javascript/langgraph/add-memory)
- [Streaming](https://docs.langchain.com/oss/javascript/langgraph/streaming)
- [Event streaming](https://docs.langchain.com/oss/javascript/langgraph/event-streaming)
- [Persistence](https://docs.langchain.com/oss/javascript/langgraph/persistence)
- [Testing](https://docs.langchain.com/oss/javascript/langgraph/test)

The source snapshot was retrieved from the corresponding `.md` URLs. The complete SHA-256 values captured
for the retrieved pages were:

| Page | SHA-256 |
|---|---|
| `overview.md` | `45a693c9c60b553019037c57ea68e6144f5556a7ca12db5f1cb298e38182caf3` |
| `quickstart.md` | `aee6c1fb947bf3a507b3430a12c338d2749d3791a6d89029b578f24626640fca` |
| `use-graph-api.md` | `90e9d6780e3c3e6156451732bcdc0fa2b617a7e78e847aff5c1da331e5260965` |
| `add-memory.md` | `022f368580364dd32ae1a873487fa89d402edb56db004b7da7cc5dcfdd2e0659` |
| `streaming.md` | `92a9caf73dce3ed5b1a4145e35fb464163bc0ccbd214944a739f48e5c654a651` |
| `event-streaming.md` | `6b41cf8a26c984e4b9cc8b7a92dd94761d3ee99a04b9ae85d03b51cdd0e7354a` |
| `test.md` | `77b30d88554eddfb027114a35c00b1875b793d85ba979942bf5d8ef34d328cac` |
| `persistence.md` | `031dbe6e718d10ef18b48c27930b9a86d47da305c36239503185958517a874be` |

The local compile record below is verified for `@langchain/langgraph@1.4.21`,
`@langchain/core@1.2.17`, `zod@4.6.5`, TypeScript `5.7.3`, Node `v22.23.2`, and npm `10.9.8`.
Those versions are an implementation check, not a universal project dependency mandate.

## Graph construction boundary

Use `StateSchema` to define the state contract and `MessagesValue` when the graph owns an append/update-aware
message channel. Type node functions as `GraphNode<typeof State>`. Nodes return state updates; they do not
mutate the state object. Build the topology with `StateGraph`, `START`, `END`, and `compile()`.

```typescript
import {
  END,
  type GraphNode,
  MessagesValue,
  START,
  StateGraph,
  StateSchema,
} from "@langchain/langgraph";

const State = new StateSchema({
  messages: MessagesValue,
});

type GraphState = typeof State;

const greet: GraphNode<GraphState> = (): {
  messages: [{ role: "ai"; content: string }];
} => ({
  messages: [{ role: "ai", content: "hello world" }],
});

export const graph = new StateGraph(State)
  .addNode("greet", greet)
  .addEdge(START, "greet")
  .addEdge("greet", END)
  .compile();
```

**Verified implementation:** the exact graph shape above was placed in a temporary TypeScript project and
passed `npx tsc --noEmit --pretty false` with the versions recorded above. It was not added to a production
application and it does not make a provider request.

## Tools and conditional routing

For a tool-using graph, keep the tool node and the routing decision separate. The official quickstart uses
`tool` with a Zod input schema, `model.bindTools(tools)`, a typed `toolsByName` lookup, `ToolMessage` results,
and a conditional router that returns a node name or `END`. Adapt those shapes to the project's chosen model
integration; do not present a provider-specific example as a provider-independent contract.

A router is a graph decision, not a browser transport. Test the route for both the tool-call and terminal
paths, including malformed or unsupported tool calls at the boundary selected by the application.

## Persistence and runtime context

Choose persistence explicitly:

- A **checkpointer** stores thread-scoped graph state and requires a `configurable.thread_id` at invocation.
  `MemorySaver` is suitable for tests and ephemeral development only.
- A **store** holds application data across threads. Access it through the injected `Runtime` in nodes when
  the graph is compiled with a store.
- Production persistence requires a project-selected durable checkpointer/store and its setup/migration
  procedure. Do not infer Postgres, MongoDB, or another backend from the generic graph recipe.

The official pages use `MemorySaver`, `InMemoryStore`, `Runtime`, and durable saver/store integrations. Check
the selected package's current types before copying a persistence example: the docs have shown more than one
in-memory store spelling across pages and versions.

## Graph streaming is not browser SSE

LangGraph's `graph.stream()` and `graph.streamEvents(..., { version: "v3" })` are graph-runtime APIs. They
expose graph updates, values, message chunks, tool events, or typed event projections to server-side code.
They are **not** the browser's Server-Sent Events wire protocol.

If a server exposes graph progress to a browser, add an explicit adapter that:

1. consumes the graph stream on the server;
2. maps only approved events to the application's transport schema;
3. emits the application's SSE or WebSocket frames; and
4. is tested at both the graph projection and browser transport boundaries.

Do not call Sentinel's named SSE events a LangGraph stream, and do not replace an existing browser SSE or
WebSocket contract with `graph.stream()`.

The official streaming guide recommends event streaming for new applications and identifies the typed
projection API as introduced in LangGraph v1.2. Use the event-streaming page for new projection work, while
retaining lower-level stream modes where the application specifically needs them.

## Testing boundary

Follow the target TypeScript test stack. The official test page uses Vitest and demonstrates a factory that
builds an uncompiled `StateGraph`, compiles a fresh `MemorySaver` per test, invokes the compiled graph with a
thread ID, tests individual nodes through `graph.nodes[...].invoke(...)`, and exercises partial execution with
`updateState` and `interruptAfter`.

At minimum, test:

- the compiled graph's happy path and terminal state;
- every conditional route, including the no-tool/`END` route;
- tool success and tool failure/invalid-call behavior where tools are used;
- checkpoint thread separation when persistence is enabled; and
- the graph-to-transport adapter separately from browser SSE parsing.

A passing Vitest suite does not prove a Vue application's `vue-tsc -b` build. For Vue consumers, retain the
strict build gate and run it independently.

## Unverified examples and implementation limits

The code in the graph-construction section is the only example locally compile-checked for this companion.
Tool-provider integrations, durable persistence wiring, event-streaming transformers, Vue integration, and
browser transport adapters are **illustrative guidance, not locally verified implementations**. Pin versions in
the consuming project, compile its actual example, and record the result before treating any of those paths
as an implementation contract.

## Skill summary

Use this companion for typed LangGraph graphs in JavaScript or TypeScript. Keep graph state, node updates, routing, persistence, streaming, and tests explicit, and verify the selected package versions instead of treating the recorded example as a universal dependency contract.

## Examples

- Define state with the current LangGraph schema API, return immutable state updates from nodes, and connect `START` and `END` through an explicitly compiled `StateGraph`.
- Test a conditional tool route and the terminal route separately, then test any graph-to-browser transport adapter independently from browser SSE parsing.
- Use an ephemeral in-memory checkpointer only for tests or development; select and verify a durable persistence implementation for production.

## Guidance

Read this skill alongside the target project's TypeScript conventions and lockfile. Keep server-side graph streaming separate from browser transport, validate external data at the adapter boundary, and report compile, test, persistence, and transport evidence with their exact versions and limits.
