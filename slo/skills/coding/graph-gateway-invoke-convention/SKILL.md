---
name: graph-gateway-invoke-convention
description: Gateway invoke convention for graph entry points and orchestration seams.
when_to_use: Use when building or reviewing graph-adjacent gateway methods so their
  invoke contract stays consistent.
group: coding
kind: skill
source_prompt: graph-gateway-invoke-convention.md
---

# Graph Gateway Invoke Convention

## Skill summary

- **Name:** `graph-gateway-invoke-convention`
- **Description:** Gateway invoke convention for graph entry points and orchestration seams.
- **When to use:** Use when building or reviewing graph-adjacent gateway methods so their invoke contract stays consistent.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `graph-gateway-invoke-convention.md`

## Examples

- The user asks: "Add a new graph gateway entry point."
- You are reviewing a graph orchestration wrapper and need the invoke-contract rules.

## Guidance

All LangGraph agent classes must expose `invoke()` as the **canonical gateway method** — the single entry point that starts the graph's functionality. This convention ensures every graph class has a predictable, discoverable API regardless of the domain.

---

## 1. Rules

| Rule | Detail |
|---|---|
| **Gateway method is always `invoke`** | The primary method that callers use to run the graph end-to-end must be named `invoke`. No exceptions. |
| **Streaming variant is `invoke_streaming`** | If the graph supports streaming progress events, expose `invoke_streaming` as an async generator alongside `invoke`. |
| **Domain aliases are allowed** | You may create aliases like `run_pubmed_agent = invoke` for backward compatibility or domain clarity, but `invoke` must always exist. The alias must delegate to `invoke`, never the other way around. |
| **`@staticmethod` for pure functions** | Routing functions, phase helpers, parsers, and detail extractors that take no instance state must be `@staticmethod`. This is required when passing them as Callables to `graph.add_conditional_edges()` or lookup tables. |
| **Instance methods for config-dependent logic** | Node factories (`_make_*_node`) and the `build()` method use instance configuration (model params, token budgets) and should be instance methods. |

---

## 2. Class Structure Template

```python
class <AgentName>Graph:
    """Encapsulates the LangGraph-based <domain> agent."""

    def __init__(
        self,
        model_name: str = "gpt-4.1-nano",
        temperature: float = 0.1,
        # ... domain-specific config
    ) -> None:
        self.model_name: str = model_name
        self.temperature: float = temperature
        # Store config — do NOT build the graph in __init__

    # ------------------------------------------------------------------
    # Public gateway
    # ------------------------------------------------------------------

    async def invoke(
        self,
        query: str,
        graph: Optional[CompiledStateGraph] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        **build_kwargs,
    ) -> str:
        """Run a query through the agent graph end-to-end.

        This is the canonical entry point. All callers should use this
        method (or its alias) to execute the graph.

        Args:
            query (str): The user's question.
            graph (Optional[CompiledStateGraph]): Pre-compiled graph.
                If None, one is built from instance config.
            history (Optional[List[Dict[str, Any]]]): Prior conversation
                turns for multi-turn context.
            max_iterations (int): Maximum tool-call rounds.
            **build_kwargs: Forwarded to ``build()`` when graph is None.

        Returns:
            str: The agent's final text response.
        """
        ...

    async def invoke_streaming(
        self,
        query: str,
        graph: Optional[CompiledStateGraph] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        **build_kwargs,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Stream progress events as the agent graph executes.

        Args:
            query (str): The user's question.
            graph (Optional[CompiledStateGraph]): Pre-compiled graph.
            history (Optional[List[Dict[str, Any]]]): Prior conversation turns.
            max_iterations (int): Maximum tool-call rounds.
            **build_kwargs: Forwarded to ``build()`` when graph is None.

        Yields:
            ProgressEvent: Dicts with node name, iteration info, status
                message, and (for the final event) the full response text.
        """
        ...

    # Domain alias (backward compatibility)
    run_pubmed_agent = invoke

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build(self, **overrides) -> CompiledStateGraph:
        """Construct and compile the agent graph.

        Uses instance config merged with any overrides.

        Returns:
            CompiledStateGraph: A compiled LangGraph ready for
                ``await graph.ainvoke(...)``.
        """
        ...

    # ------------------------------------------------------------------
    # State helpers (private)
    # ------------------------------------------------------------------

    def _build_initial_state(
        self,
        query: str,
        history: Optional[List[Dict[str, Any]]] = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_web_searches: int = DEFAULT_MAX_WEB_SEARCHES,
        max_pubmed_searches: int = DEFAULT_MAX_PUBMED_SEARCHES,
        max_compliance_iterations: int = DEFAULT_MAX_COMPLIANCE_ITERATIONS,
    ) -> dict:
        """Build the initial state dict for graph invocation.

        Shared by ``invoke`` and ``invoke_streaming`` to avoid
        duplication.
        """
        ...

    # ------------------------------------------------------------------
    # Node factories (private, instance methods)
    # ------------------------------------------------------------------

    def _make_agent_node(self, llm: LLM) -> NodeFn:
        ...

    def _make_synthesize_node(self, llm: LLM) -> NodeFn:
        ...

    # ------------------------------------------------------------------
    # Routing & pure helpers (static methods)
    # ------------------------------------------------------------------

    @staticmethod
    def _should_continue(state: AgentState) -> str:
        """Route after the agent node. No side effects."""
        ...

    @staticmethod
    def _determine_phase(iteration: int) -> str:
        ...

    @staticmethod
    def _build_assessment_prompt(...) -> str:
        ...
```

---

## 3. Backward-Compatible Module-Level Aliases

When refactoring an existing module of free functions into a class, preserve backward compatibility with module-level wrappers that delegate to the class:

```python
# --- Backward-compatible module-level API ---
# Existing callers continue to work without import changes.

async def run_pubmed_agent(
    query: str,
    graph: Optional[CompiledStateGraph] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    **build_kwargs,
) -> str:
    """Module-level alias — delegates to PubmedSearchGraph.invoke."""
    agent: PubmedSearchGraph = PubmedSearchGraph()
    return await agent.invoke(
        query=query,
        graph=graph,
        history=history,
        max_iterations=max_iterations,
        **build_kwargs,
    )


def build_pubmed_agent(**kwargs) -> CompiledStateGraph:
    """Module-level alias — delegates to PubmedSearchGraph.build."""
    agent: PubmedSearchGraph = PubmedSearchGraph()
    return agent.build(**kwargs)
```

---

## 4. Addendum: Execution Flow Diagram in Graph Classes

In addition to the standard class docstring (see `skills/coding/method-docstrings/SKILL.md`), graph classes must include an **execution flow diagram** as a module-level comment block **immediately above the class definition**. This gives the developer a declarative visualization of the node sequence without reading method bodies.

Do **not** embed the diagram inside the class docstring — the docstring follows the standard Google-style format described in `skills/coding/method-docstrings/SKILL.md`.

### Placement

```python
# ---------------------------------------------------------------------------
# PubmedSearchGraph — Execution Flow
# ---------------------------------------------------------------------------
#
# invoke() / invoke_streaming()
#   → _build_initial_state()
#     → graph.ainvoke() / graph.astream()
#
# Graph Node Sequence:
#
#               ┌──────────────────────────────────┐
#               │                                  │
#               ▼                                  │
# START ──► agent ──► [_should_continue?]           │
#                           │     │                │
#                       "tools"   "synthesize"     │
#                           │         │            │
#                           ▼         ▼            │
#                        tools    synthesize       │
#                           │         │            │
#                           ▼         ▼            │
#                        assess   compliance ──► [_should_amend?]
#                           │         ▲               │       │
#                           └─────────┘           "amend"    END
#                                                    │
#                                                    ▼
#                                                  amend ─────┘
# ---------------------------------------------------------------------------

class PubmedSearchGraph:
    """Encapsulates the LangGraph-based PubMed research agent."""
    ...
```

### Rules for the diagram

| Rule | Detail |
|---|---|
| **Module-level comment, not docstring** | Use `#` comment block above the class, not inside the docstring |
| **Show all nodes** | Every node registered with `graph.add_node()` must appear |
| **Show conditional edges** | Use `[function_name?]` notation for routing decision points |
| **Show loops** | Indicate cycles with arrows back to earlier nodes |
| **Label branches** | Use quoted strings matching the routing function's return values |
| **Mark terminal** | `END` marks where the graph terminates |
| **Show entry point** | First line shows which public methods enter the flow |

---

## 5. When to Apply

- **New graph agents**: Always use this pattern from the start.
- **Existing free-function graphs**: Refactor into a class when modifying the file for other reasons. Provide module-level aliases for backward compatibility.
- **Simple single-node graphs**: Even trivial graphs should follow this pattern for consistency — the class may be small, but the `invoke` entry point must exist.

---

## 6. Checklist

Before submitting a graph module, verify:

- [ ] Class exists with `invoke()` as the gateway method
- [ ] `invoke_streaming()` exists if the graph supports streaming
- [ ] Module-level comment block contains ASCII execution flow diagram showing all nodes (above the class definition)
- [ ] Class docstring follows standard Google-style format from `skills/coding/method-docstrings/SKILL.md`
- [ ] Routing functions and pure helpers are `@staticmethod`
- [ ] Node factories and `build()` are instance methods
- [ ] `_build_initial_state()` is extracted and shared between `invoke` and `invoke_streaming`
- [ ] Module-level backward-compatible aliases exist if refactoring from free functions
- [ ] All method signatures use named arguments and type hints
