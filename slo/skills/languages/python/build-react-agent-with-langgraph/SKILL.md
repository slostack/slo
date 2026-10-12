---
name: build-react-agent-with-langgraph
description: 'Python: Building ReAct (reason + act) loops with LangGraph.'
when_to_use: 'For Python projects only. Use when assembling a new agent graph: state, agent node, tool
  node, routing, build_*_agent factory.'
group: languages
kind: skill
source_prompt: build-react-agent-with-langgraph.md
---

# Build ReAct Agents with LangGraph

## Skill summary

- **Name:** `build-react-agent-with-langgraph`
- **Description:** Building ReAct (reason + act) loops with LangGraph.
- **When to use:** Use when assembling a new agent graph: state, agent node, tool node, routing, build_*_agent factory.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `build-react-agent-with-langgraph.md`

## Examples

- The user asks: "Add or revise the react agent with langgraph for this feature."
- You want the canonical build pattern before touching react agent with langgraph.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

This document defines the conventions for building ReAct (Reason + Act) agent loops using LangGraph. The canonical reference implementation is [`src/agents/pubmed_search_agent/graph.py`](../../../../orders_service/src/agents/pubmed_search_agent/graph.py).

---

## 1. Mental Model — Agents as State Machines

LangGraph models an agent as a **directed graph** (state machine) with three concepts:

| Concept | What it is | Python type |
|---|---|---|
| **State** | A typed dict that flows through every node. Holds the message history and any custom fields (iteration counters, flags). | A class extending `MessagesState` |
| **Node** | An async function that receives state, does one thing, and returns a partial state update. | `async def node(state: AgentState) -> dict` |
| **Edge** | A connection between nodes. Static edges always fire; conditional edges choose the next node based on state. | `graph.add_edge()` or `graph.add_conditional_edges()` |

The ReAct loop is implicit in the graph structure — there is no `while` loop. The cycle `agent → tools → assess → agent → ...` continues until a conditional edge routes to `synthesize → END`.

```
              ┌──────────────────────────────────┐
              │                                  │
              ▼                                  │
START ──► agent ──► [should_continue?]            │
                          │     │                │
                      "tools"   "synthesize"     │
                          │         │            │
                          ▼         ▼            │
                       tools    synthesize ──► END
                          │                      │
                          ▼                      │
                       assess ───────────────────┘
```

---

## 2. File Organisation

Each agent that uses a ReAct loop gets its own directory under `src/agents/<agent_name>/` with this structure:

```
src/agents/<agent_name>/
├── graph.py          # LangGraph state, nodes, routing, graph builder
├── agent.py          # Thin wrapper class + __main__ entry point
├── prompts.py        # System prompt and iteration prompts
```

### Separation of concerns

| File | Responsibility |
|---|---|
| `graph.py` | All LangGraph machinery — state definition, node functions, routing logic, graph construction. This is the core of the agent. |
| `agent.py` | A wrapper class that builds the graph and exposes a simple async interface (e.g., `.react(human_message=...)`) for callers like A2A executors. Also contains the `__main__` block for testing. |
| `prompts.py` | All prompt text as module-level string constants. Never inline prompts in graph.py or agent.py. |

---

## 3. State Definition

Extend `MessagesState` with any fields the agent needs to track across iterations:

```python
from langgraph.graph import MessagesState

class PubmedAgentState(MessagesState):
    """Extends the built-in MessagesState with iteration, search budget,
    and phase-aware research tracking."""
    iteration: int
    max_iterations: int
    web_search_count: int
    max_web_searches: int
    search_phase: str
    local_search_count: int
    pubmed_search_count: int
    max_pubmed_searches: int
```

### Rules

| Rule | Detail |
|---|---|
| **Always extend `MessagesState`** | It provides the `messages` field with built-in append semantics — returning `{"messages": [new_msg]}` appends rather than replaces |
| **Type-hint every field** | `iteration: int`, not `iteration` |
| **Keep state minimal** | Only add fields that nodes actually read or write. Don't store derived data. |
| **Initialise at invocation** | Set default values when calling `graph.ainvoke(initial_state)`, not in the class definition |

---

## 4. Nodes

Each node is a pure-ish async function: it reads from state, does one thing, and returns a partial state update.

### 4.1 Agent node — calls the LLM

```python
def _make_agent_node(llm: LLM) -> NodeFn:
    """Return the agent node function, closed over the configured LLM."""

    async def agent_node(state: PubmedAgentState) -> dict:
        response: AIMessage = await llm.ainvoke(state["messages"])
        return {"messages": [response]}

    return agent_node
```

**Why a factory?** The LLM is configured at graph-build time and closed over. The node function itself only receives state — it has no other dependencies.

### 4.2 Tool node — executes tool calls

Use LangGraph's built-in `ToolNode`. It handles:
- Dispatching each tool call to the correct tool function
- Catching exceptions and converting them to `ToolMessage(content="Error: ...")`
- Returning all `ToolMessage` results appended to the message list

```python
from langgraph.prebuilt import ToolNode

tool_node: ToolNode = ToolNode(tools=tools, handle_tool_errors=True)
```

**Always set `handle_tool_errors=True`** — this converts tool exceptions into error messages the LLM can reason about, instead of crashing the graph.

### 4.3 Assessment node — injects iteration prompts (optional)

If your agent benefits from structured reasoning between tool calls, add an `assess` node that:
1. Increments the iteration counter
2. Counts tool calls from the most recent AIMessage (tracks each tool type separately)
3. Determines the current research phase
4. Builds a phase-aware assessment prompt with resource budgets
5. Appends it as a `HumanMessage`

```python
def _make_assess_node() -> NodeFn:
    async def assess_node(state: PubmedAgentState) -> dict:
        iteration: int = state["iteration"] + 1
        max_iterations: int = state["max_iterations"]
        web_search_count: int = state.get("web_search_count", 0)
        local_search_count: int = state.get("local_search_count", 0)
        pubmed_search_count: int = state.get("pubmed_search_count", 0)

        # Count tool calls from the most recent AIMessage
        for msg in reversed(state["messages"]):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc["name"] == "text_search":
                        web_search_count += 1
                    elif tc["name"] == "local_search":
                        local_search_count += 1
                    elif tc["name"] == "pubmed_search":
                        pubmed_search_count += 1
                break

        phase: str = _determine_phase(iteration=iteration)
        assessment: str = _build_assessment_prompt(
            iteration=iteration,
            max_iterations=max_iterations,
            web_searches_remaining=max(0, state["max_web_searches"] - web_search_count),
            pubmed_searches_remaining=max(0, state["max_pubmed_searches"] - pubmed_search_count),
            local_searches_used=local_search_count,
        )
        return {
            "messages": [HumanMessage(content=assessment)],
            "iteration": iteration,
            "web_search_count": web_search_count,
            "local_search_count": local_search_count,
            "pubmed_search_count": pubmed_search_count,
            "search_phase": phase,
        }
    return assess_node
```

This is the place to inject domain-specific reasoning (evidence quality assessment, coverage analysis, phase-based guidance) without cluttering the agent node.

### 4.4 Synthesize node — produces the final user-facing response

The synthesize node replaces the agent system prompt with a user-facing synthesis prompt, filters internal messages, and calls the LLM without tools bound:

```python
def _make_synthesize_node(llm: LLM) -> NodeFn:
    async def synthesize_node(state: PubmedAgentState) -> dict:
        synthesis_messages: list[BaseMessage] = [
            SystemMessage(content=SYNTHESIS_PROMPT),
        ]
        for msg in state["messages"]:
            if isinstance(msg, SystemMessage):
                continue
            if isinstance(msg, HumanMessage) and "## Iteration" in msg.content:
                continue
            synthesis_messages.append(msg)

        response: AIMessage = await llm.ainvoke(synthesis_messages)
        return {"messages": [response]}
    return synthesize_node
```

**Key**: The `llm` passed here is the **base LLM without tools bound** — the synthesis node must not make tool calls.

### Node rules

| Rule | Detail |
|---|---|
| **One responsibility per node** | Agent node calls the LLM. Tool node executes tools. Assess node injects prompts. Don't combine. |
| **Return partial state** | Only include the keys you're updating. `MessagesState` has append semantics for `messages`. |
| **Type-hint the return** | `-> dict` (the partial state update) |
| **Use factory functions** | Nodes that need configuration (LLM, tools) use a factory that returns the node function via closure |
| **Log at debug level** | Use `log_debug` inside nodes for observability without noise |

---

## 5. Routing — Conditional Edges

The routing function decides what happens after the agent node. It routes to `"synthesize"` (not `END`) so the dedicated synthesize node produces the final answer:

```python
def _should_continue(state: PubmedAgentState) -> Literal["tools", "synthesize"]:
    last_message: BaseMessage = state["messages"][-1]

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        if state["iteration"] >= state["max_iterations"]:
            return "synthesize"  # iteration limit — force synthesis
        return "tools"

    return "synthesize"  # no tool calls — ready to synthesize
```

### Rules

| Rule | Detail |
|---|---|
| **Return type** | `Literal` union of node names — use `"synthesize"` instead of `END` so the synthesize node runs |
| **Check tool calls** | `AIMessage.tool_calls` is the canonical way to detect if the LLM wants to call tools |
| **Enforce iteration limits** | Always check the iteration counter to prevent infinite loops |
| **No side effects** | Routing functions only inspect state — they never modify it |

---

## 6. Graph Assembly

The `build_*_agent()` function wires everything together:

```python
def build_pubmed_agent(
    model_name: str = "gpt-4.1-nano",
    temperature: float = 0.1,
    tools: Sequence[BaseTool] | None = None,
    ...
) -> CompiledStateGraph:
    # 1. Configure tools
    if tools is None:
        tools = [local_search, pubmed_search, text_search]

    # 2. Create LLM and bind tools
    llm: LLM = create_llm(model_name=model_name, ...)
    llm_with_tools: LLM = llm.bind_tools(tools=tools)

    # 3. Create nodes (note: synthesize uses base llm WITHOUT tools)
    agent_node: NodeFn = _make_agent_node(llm=llm_with_tools)
    tool_node: ToolNode = ToolNode(tools=tools, handle_tool_errors=True)
    assess_node: NodeFn = _make_assess_node()
    synthesize_node: NodeFn = _make_synthesize_node(llm=llm)

    # 4. Build graph
    graph: StateGraph = StateGraph(PubmedAgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("assess", assess_node)
    graph.add_node("synthesize", synthesize_node)

    # 5. Wire edges
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _should_continue)
    graph.add_edge("tools", "assess")
    graph.add_edge("assess", "agent")
    graph.add_edge("synthesize", END)

    return graph.compile()
```

### Builder rules

| Rule | Detail |
|---|---|
| **Return `CompiledStateGraph`** | Always compile before returning |
| **Accept tools as a parameter** | Enables testing with mock tools |
| **Two LLM references** | `llm_with_tools` for the agent node, bare `llm` for the synthesize node (must not make tool calls) |
| **Bind tools to the LLM** | Call `llm.bind_tools(tools=tools)` — this tells the LLM provider about available tools |
| **Type-hint every variable** | `graph: StateGraph = StateGraph(...)`, not `graph = StateGraph(...)` |
| **Use named arguments** | `create_llm(model_name=model_name, temperature=temperature)` |

---

## 7. Entry Points

### 7.1 High-level async function

```python
async def run_pubmed_agent(
    query: str,
    graph: CompiledStateGraph | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_web_searches: int = DEFAULT_MAX_WEB_SEARCHES,
    max_pubmed_searches: int = DEFAULT_MAX_PUBMED_SEARCHES,
    **build_kwargs,
) -> str:
    if graph is None:
        graph = build_pubmed_agent(**build_kwargs)

    initial_state: PubmedAgentState = {
        "messages": [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(content=f"Research query: {query}"),
        ],
        "iteration": 0,
        "max_iterations": max_iterations,
        "web_search_count": 0,
        "max_web_searches": max_web_searches,
        "local_search_count": 0,
        "pubmed_search_count": 0,
        "max_pubmed_searches": max_pubmed_searches,
        "search_phase": "discovery",
    }

    result: dict = await graph.ainvoke(initial_state)
    final_message: BaseMessage = result["messages"][-1]
    return final_message.content
```

### 7.2 Streaming entry point

For real-time progress feedback, use `stream_pubmed_agent()` which yields `ProgressEvent` dicts after each graph node completes:

```python
async def stream_pubmed_agent(
    query: str,
    graph: CompiledStateGraph | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_web_searches: int = DEFAULT_MAX_WEB_SEARCHES,
    max_pubmed_searches: int = DEFAULT_MAX_PUBMED_SEARCHES,
    **build_kwargs,
) -> AsyncGenerator[ProgressEvent, None]:
    # ... builds initial_state same as run_pubmed_agent ...

    async for chunk in graph.astream(initial_state, stream_mode="updates"):
        for node_name, node_output in chunk.items():
            # Track iteration and phase from assess node output
            # Build status message and detail string
            # Yield ProgressEvent with node, iteration, phase, message, detail, is_final, response
            yield event
```

The `ProgressEvent` TypedDict contains:
- `node`, `iteration`, `max_iterations`, `phase` — graph position
- `message` — user-facing status (e.g., "Searching for evidence (iteration 3/10, Gap-Filling phase)...")
- `detail` — contextual info extracted from node output (e.g., "Searching PubMed for 'metformin RCT'")
- `is_final` — `True` only for the synthesize node
- `response` — the synthesized answer (only on final event)

### 7.3 Wrapper class (for backward compatibility)

When an existing caller expects a class interface (e.g., A2A executors), create a thin wrapper in `agent.py`:

```python
class PubmedSearchAgent:
    def __init__(self, model_name: str = "gpt-4.1-nano", ...):
        self.max_iterations: int = max_iterations
        self.max_web_searches: int = max_web_searches
        self.max_pubmed_searches: int = max_pubmed_searches
        self._graph: CompiledStateGraph = build_pubmed_agent(model_name=model_name, ...)

    async def react(self, human_message: str) -> Dict:
        response: str = await run_pubmed_agent(
            query=human_message,
            graph=self._graph,
            max_iterations=self.max_iterations,
            max_web_searches=self.max_web_searches,
            max_pubmed_searches=self.max_pubmed_searches,
        )
        return {"response": response}

    async def react_streaming(self, human_message: str) -> AsyncGenerator[ProgressEvent, None]:
        async for event in stream_pubmed_agent(
            query=human_message,
            graph=self._graph,
            max_iterations=self.max_iterations,
            max_web_searches=self.max_web_searches,
            max_pubmed_searches=self.max_pubmed_searches,
        ):
            yield event
```

---

## 8. How the LLM Factory Fits In

The LLM factory `create_llm()` lives in `src/agents/base.py` and supports OpenAI, Azure OpenAI, and Google Gemini. It is a standalone function — not tied to any base class.

```python
from src.agents.base import LLM, create_llm

llm: LLM = create_llm(
    model_name="gpt-4.1-nano",
    temperature=0.1,
    streaming=True,
    max_retries=3,
    max_tokens=1500,
)
```

Graph agents import and use this directly. They do **not** extend `BaseChatAgent`.

---

## 9. Common Graph Patterns

### 9.1 Simple ReAct (no assessment)

For agents that don't need iteration prompts:

```
START → agent → [tools or END]
                  tools → agent
```

```python
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", should_continue)
graph.add_edge("tools", "agent")  # loop directly back
```

### 9.2 ReAct with assessment and synthesize (current pattern)

```
START → agent → [tools or synthesize]
                  tools → assess → agent
                  synthesize → END
```

The `assess` node sits between `tools` and `agent`, injecting phase-aware evaluation prompts. The `synthesize` node produces the final user-facing response with a separate prompt.

### 9.3 Concurrent tool execution

LangGraph's `ToolNode` automatically executes multiple tool calls from a single AIMessage concurrently. If the LLM returns:

```python
AIMessage(tool_calls=[
    {"name": "local_search", "args": {"query": "psoriasis hormones"}},
    {"name": "pubmed_search", "args": {"query": "psoriasis testosterone"}},
])
```

Both tools run concurrently within the single `tools` node. No extra graph wiring needed.

### 9.4 Conditional branching (e.g., human-in-the-loop)

```python
def route_after_tools(state) -> Literal["agent", "human_review", "__end__"]:
    if state["requires_review"]:
        return "human_review"
    return "agent"

graph.add_conditional_edges("tools", route_after_tools)
```

---

## 10. Prompts

All prompts live in `prompts.py` as module-level string constants. Each prompt has a single responsibility — no prompt mixes tool-routing and output-format instructions.

| Prompt | Used By | Responsibility |
|---|---|---|
| `AGENT_SYSTEM_PROMPT` | Agent node | Tool selection, research methodology (PICO decomposition, evidence hierarchy, 3-phase search strategy), relevance anchoring, decision rules |
| `REACT_ITERATION_PROMPT` | Assess node | Chain-of-thought evidence assessment (relevance anchor, PICO coverage audit, evidence quality inventory, contradiction check, recency assessment, metacognitive check), resource budgets, phase guidance |
| `SYNTHESIS_PROMPT` | Synthesize node | User-facing output — doctor tone, evidence weighting, confidence calibration, citation format, output structure |
| `PHASE_DISCOVERY_GUIDANCE` | Assess node (via `_build_assessment_prompt`) | Phase 1 strategy — broad queries, leverage local_search, map coverage |
| `PHASE_GAP_FILLING_GUIDANCE` | Assess node (via `_build_assessment_prompt`) | Phase 2 strategy — narrow targeted queries, synonyms, text_search for recency |
| `PHASE_VERIFICATION_GUIDANCE` | Assess node (via `_build_assessment_prompt`) | Phase 3 strategy — consistency checks, guideline searches, aggressive stopping |

### Iteration / assessment prompt

Uses `str.format()` placeholders filled at runtime:

```python
REACT_ITERATION_PROMPT: str = """\
## Iteration {iteration} of {max_iterations} | Phase: {phase_name}
...
### Resource Budget
- Web searches remaining: **{web_searches_remaining}**
- PubMed searches remaining: **{pubmed_searches_remaining}**
- Local searches used: **{local_searches_used}**

{phase_guidance}

### Decision
{remaining_guidance}
"""
```

The `_build_assessment_prompt()` function determines the phase, selects the appropriate guidance, and formats the template.

---

## 11. Checklist — Before Submitting a New Agent

- [ ] `graph.py` has state class, nodes, routing, builder function, `run_*` entry point, and `stream_*` entry point
- [ ] `agent.py` has wrapper class with `react()` and `react_streaming()`, plus `__main__` block
- [ ] `prompts.py` has all prompt text as constants — no inline strings in graph.py
- [ ] Every variable has a type hint on first assignment
- [ ] Every function call uses named arguments
- [ ] `ToolNode` uses `handle_tool_errors=True`
- [ ] Iteration limit is enforced in the routing function
- [ ] Routing returns `"synthesize"` (not `END`) so the synthesize node runs
- [ ] Synthesize node uses base LLM without tools bound
- [ ] Tools are accepted as a parameter in the builder (for testability)
- [ ] `create_llm()` is imported from `src/agents/base.py` (not duplicated)
- [ ] `ProgressEvent` TypedDict defined for streaming events
- [ ] Status message and detail extraction helpers implemented
- [ ] Updated `RESEARCH.md` agents section
- [ ] Updated `AGENTS.md` code prompts table
