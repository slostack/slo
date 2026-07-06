---
name: test-graphs-and-agents
description: Testing LangGraph agents with the FauxChatModel pattern.
when_to_use: Use when writing tests for an agent graph or tool-using ReAct loop.
group: coding
kind: skill
source_prompt: test-graphs-and-agents.md
---

# Testing LangGraph Agents

## Skill summary

- **Name:** `test-graphs-and-agents`
- **Description:** Testing LangGraph agents with the FauxChatModel pattern.
- **When to use:** Use when writing tests for an agent graph or tool-using ReAct loop.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `test-graphs-and-agents.md`

## Examples

- The user asks: "Write or revise the tests covered by test graphs and agents."
- You finished coding and need the matching test convention before calling the work done.

## Guidance

This document defines the conventions for testing LangGraph-based ReAct agents. The canonical reference implementation is [`tests/agents/pubmed_search_agent/test_graph.py`](../../../../orders_service/tests/agents/pubmed_search_agent/test_graph.py).

---

## 1. Scope — What to Test

Test the **application logic** that you write. Do not test LangGraph framework internals or LLM output quality.

| Test | Don't Test |
|---|---|
| State mutations (iteration counters, budget tracking) | Whether LangGraph correctly routes edges |
| Routing decisions (`_should_continue` logic) | LLM response quality or format adherence |
| Assessment/iteration prompt generation | `ToolNode` dispatch mechanics |
| Parameter pass-through (constructor → graph → state) | External API response formats |
| Graph construction (correct tools bound, correct type returned) | `MessagesState` append semantics |
| Initial state initialisation in `run_*` entry points | Framework compilation internals |

---

## 2. File Organisation

```
tests/agents/<agent_name>/
├── __init__.py
├── test_graph.py      # Tests for graph.py: state, nodes, routing, builder, entry point
└── test_agent.py      # Tests for agent.py: wrapper class parameter pass-through
```

Mirror the source structure:
- `src/agents/<agent_name>/graph.py` → `tests/agents/<agent_name>/test_graph.py`
- `src/agents/<agent_name>/agent.py` → `tests/agents/<agent_name>/test_agent.py`

---

## 3. Class Naming Convention

Group tests by the function or class under test. Prefix every test class with `Test`.

| Source Function / Class | Test Class Name |
|---|---|
| `_determine_phase()` | `TestDeterminePhase` |
| `_get_phase_display_name()` | `TestGetPhaseDisplayName` |
| `_get_phase_guidance()` | `TestGetPhaseGuidance` |
| `_build_assessment_prompt()` | `TestBuildAssessmentPrompt` |
| `_make_assess_node()` | `TestAssessNode` |
| `_should_continue()` | `TestShouldContinue` |
| `_make_synthesize_node()` | `TestSynthesizeNode` |
| `build_pubmed_agent()` | `TestBuildPubmedAgent` |
| `run_pubmed_agent()` | `TestRunPubmedAgent` |
| `_build_status_message()` | `TestBuildStatusMessage` |
| `_extract_node_detail()` | `TestExtractNodeDetail` |
| `stream_pubmed_agent()` | `TestStreamPubmedAgent` |
| `PubmedSearchAgent` | `TestPubmedSearchAgent` |

Test method naming follows the pattern: `test_<method>_when_<condition>`, matching the domain/app/controller test skills.

```python
class TestAssessNode:
    async def test_counts_call_when_single_text_search(self): ...
    async def test_accumulates_when_across_iterations(self): ...
    async def test_count_stays_zero_when_no_text_search_calls(self): ...
```

---

## 4. Testing Pure Functions

Functions like `_determine_phase`, `_build_assessment_prompt`, `_build_status_message`, and `_should_continue` are pure — they take inputs and return outputs with no side effects. Test them directly without mocks.

```python
class TestDeterminePhase:
    def test_iteration_1_is_discovery(self):
        assert _determine_phase(iteration=1) == "discovery"

    def test_iteration_4_is_gap_filling(self):
        assert _determine_phase(iteration=4) == "gap_filling"

    def test_iteration_8_is_verification(self):
        assert _determine_phase(iteration=8) == "verification"
```

```python
class TestBuildAssessmentPrompt:
    def test_final_iteration_includes_stop_instruction(self):
        result: str = _build_assessment_prompt(
            iteration=10,
            max_iterations=10,
            web_searches_remaining=2,
            pubmed_searches_remaining=1,
            local_searches_used=3,
        )
        assert "FINAL iteration" in result
        assert "stop calling tools" in result.lower()

    def test_phase_name_in_prompt(self):
        result: str = _build_assessment_prompt(
            iteration=5,
            max_iterations=10,
            web_searches_remaining=4,
            pubmed_searches_remaining=3,
            local_searches_used=2,
        )
        assert "Phase: Gap-Filling" in result
```

```python
class TestBuildStatusMessage:
    def test_first_agent_call_shows_analyzing(self):
        result: str = _build_status_message(
            node_name="agent", iteration=0, max_iterations=10, phase="discovery",
        )
        assert "Analyzing query" in result

    def test_tools_node_shows_searching(self):
        result: str = _build_status_message(
            node_name="tools", iteration=3, max_iterations=10, phase="gap_filling",
        )
        assert "Searching for evidence" in result
        assert "Gap-Filling" in result
```

```python
class TestShouldContinue:
    def test_returns_tools_when_tool_calls_and_under_limit(self):
        ai_msg: AIMessage = AIMessage(
            content="",
            tool_calls=[{"name": "pubmed_search", "args": {}, "id": "1"}],
        )
        state: dict = {"messages": [ai_msg], "iteration": 0, "max_iterations": 10}
        assert _should_continue(state) == "tools"

    def test_returns_synthesize_when_no_tool_calls(self):
        ai_msg: AIMessage = AIMessage(content="Ready to synthesize.")
        state: dict = {"messages": [ai_msg], "iteration": 1, "max_iterations": 10}
        assert _should_continue(state) == "synthesize"

    def test_returns_synthesize_when_iteration_limit_reached(self):
        ai_msg: AIMessage = AIMessage(
            content="",
            tool_calls=[{"name": "pubmed_search", "args": {}, "id": "1"}],
        )
        state: dict = {"messages": [ai_msg], "iteration": 10, "max_iterations": 10}
        assert _should_continue(state) == "synthesize"
```

Note: routing always returns `"synthesize"` instead of `END` — the synthesize node produces the final answer and routes to `END` itself.

---

## 5. Testing Node Functions

Node factories like `_make_assess_node()` return async functions. Get the node, then call it with a constructed state dict.

**Key**: The state is a plain `dict` matching the `TypedDict` schema — you do not need an actual `PubmedAgentState` instance.

```python
class TestAssessNode:
    @pytest.mark.asyncio
    async def test_increments_iteration(self):
        assess_node = _make_assess_node()
        state: dict = {
            "messages": [AIMessage(content="response")],
            "iteration": 0,
            "max_iterations": 10,
            "web_search_count": 0,
            "max_web_searches": 7,
            "local_search_count": 0,
            "pubmed_search_count": 0,
            "max_pubmed_searches": 5,
        }
        result: dict = await assess_node(state)
        assert result["iteration"] == 1
```

### Building AIMessages with tool_calls

Construct `AIMessage` objects directly — no real LLM needed:

```python
def _build_ai_message_with_tool_calls(tool_calls: list[dict], content: str = "") -> AIMessage:
    return AIMessage(content=content, tool_calls=tool_calls)

def _make_tool_call(name: str, args: dict | None = None, call_id: str = "1") -> dict:
    return {"name": name, "args": args or {}, "id": call_id}

# Usage:
ai_msg: AIMessage = _build_ai_message_with_tool_calls(
    tool_calls=[
        _make_tool_call(name="text_search", args={"query": "FDA update"}, call_id="1"),
        _make_tool_call(name="pubmed_search", args={"query": "testosterone"}, call_id="2"),
    ]
)
```

### Testing the Synthesize Node

The synthesize node has specific responsibilities: replace the system prompt, filter internal messages, and call the LLM without tools. Test each responsibility independently.

```python
class TestSynthesizeNode:
    @pytest.mark.asyncio
    async def test_replaces_system_message_with_synthesis_prompt(self):
        mock_llm: MagicMock = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Final answer"))

        synthesize_node = _make_synthesize_node(llm=mock_llm)
        state: dict = {
            "messages": [
                SystemMessage(content="Original agent prompt"),
                HumanMessage(content="Research query: test"),
            ],
        }
        await synthesize_node(state)

        # Capture the messages passed to ainvoke
        call_messages: list = mock_llm.ainvoke.call_args.args[0]
        assert isinstance(call_messages[0], SystemMessage)
        assert SYNTHESIS_PROMPT in call_messages[0].content

    @pytest.mark.asyncio
    async def test_filters_iteration_assessment_prompts(self):
        """Iteration assessment HumanMessages contain instructions like
        'do NOT write a response' that would confuse the synthesis LLM."""
        mock_llm: MagicMock = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Answer"))

        synthesize_node = _make_synthesize_node(llm=mock_llm)
        state: dict = {
            "messages": [
                SystemMessage(content="Agent prompt"),
                HumanMessage(content="Research query: test"),
                AIMessage(content="", tool_calls=[...]),
                ToolMessage(content="results", tool_call_id="1"),
                HumanMessage(content="## Iteration 1 of 3\n...do NOT write..."),
                AIMessage(content="Ready to synthesize."),
            ],
        }
        await synthesize_node(state)

        call_messages: list = mock_llm.ainvoke.call_args.args[0]
        iteration_msgs: list = [
            m for m in call_messages
            if isinstance(m, HumanMessage) and "## Iteration" in m.content
        ]
        assert len(iteration_msgs) == 0
```

Key things to test:
- System message is replaced with `SYNTHESIS_PROMPT`
- Original `SystemMessage` is stripped
- Non-system messages (user query, tool results) are preserved
- Iteration assessment `HumanMessage`s (containing "## Iteration") are filtered
- The returned dict contains an `AIMessage`

---

## 6. Testing Graph Construction

Mock `create_llm` to avoid real API initialisation. Verify the compiled graph has the expected tools bound and returns the correct type.

```python
class TestBuildPubmedAgent:
    @patch("src.agents.pubmed_search_agent.graph.create_llm")
    def test_default_tools_include_text_search(self, mock_create_llm: MagicMock):
        mock_llm: MagicMock = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_create_llm.return_value = mock_llm

        graph: CompiledStateGraph = build_pubmed_agent()

        # Inspect the tools passed to bind_tools
        bind_call_args = mock_llm.bind_tools.call_args
        tools_arg: list = bind_call_args.kwargs.get("tools", bind_call_args.args[0])
        tool_names: list[str] = [t.name for t in tools_arg]
        assert "local_search" in tool_names
        assert "pubmed_search" in tool_names
        assert "text_search" in tool_names

    @patch("src.agents.pubmed_search_agent.graph.create_llm")
    def test_graph_has_synthesize_node(self, mock_create_llm: MagicMock):
        mock_llm: MagicMock = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_create_llm.return_value = mock_llm

        graph: CompiledStateGraph = build_pubmed_agent()

        node_names: list[str] = list(graph.get_graph().nodes.keys())
        assert "synthesize" in node_names
```

When testing with custom tools, use a real `@tool`-decorated function — `ToolNode` validates tool types:

```python
    @patch("src.agents.pubmed_search_agent.graph.create_llm")
    def test_custom_tools_override(self, mock_create_llm: MagicMock):
        from langchain.tools import tool as tool_decorator

        @tool_decorator
        def custom_tool(query: str) -> str:
            """A custom test tool."""
            return "result"

        mock_llm: MagicMock = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_create_llm.return_value = mock_llm

        build_pubmed_agent(tools=[custom_tool])

        tools_arg = mock_llm.bind_tools.call_args.kwargs.get("tools")
        assert len(tools_arg) == 1
        assert tools_arg[0].name == "custom_tool"
```

---

## 7. Testing `run_*` Entry Points

Mock the compiled graph's `ainvoke` to capture the `initial_state` and verify it's initialised correctly.

```python
class TestRunPubmedAgent:
    @pytest.mark.asyncio
    async def test_initial_state_includes_all_fields(self):
        mock_graph: MagicMock = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={"messages": [AIMessage(content="Done.")], "iteration": 1}
        )

        await run_pubmed_agent(query="test", graph=mock_graph)

        initial_state: dict = mock_graph.ainvoke.call_args.args[0]
        assert initial_state["web_search_count"] == 0
        assert initial_state["max_web_searches"] == DEFAULT_MAX_WEB_SEARCHES
        assert initial_state["local_search_count"] == 0
        assert initial_state["pubmed_search_count"] == 0
        assert initial_state["max_pubmed_searches"] == DEFAULT_MAX_PUBMED_SEARCHES
        assert initial_state["search_phase"] == "discovery"
        assert initial_state["iteration"] == 0
```

To test that the graph is built when none is provided, patch the builder:

```python
    @pytest.mark.asyncio
    @patch("src.agents.pubmed_search_agent.graph.build_pubmed_agent")
    async def test_builds_graph_when_none_provided(self, mock_build: MagicMock):
        mock_graph: MagicMock = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={"messages": [AIMessage(content="Built.")], "iteration": 1}
        )
        mock_build.return_value = mock_graph

        result: str = await run_pubmed_agent(query="test")

        mock_build.assert_called_once()
        assert result == "Built."
```

---

## 8. Testing Wrapper Classes

Mock `build_pubmed_agent` and `run_pubmed_agent` to verify parameter pass-through without triggering real graph execution.

```python
class TestPubmedSearchAgent:
    @patch("src.agents.pubmed_search_agent.agent.build_pubmed_agent")
    def test_default_budgets(self, mock_build: MagicMock):
        mock_build.return_value = MagicMock()
        agent: PubmedSearchAgent = PubmedSearchAgent()
        assert agent.max_web_searches == DEFAULT_MAX_WEB_SEARCHES
        assert agent.max_pubmed_searches == DEFAULT_MAX_PUBMED_SEARCHES

    @patch("src.agents.pubmed_search_agent.agent.run_pubmed_agent", new_callable=AsyncMock)
    @patch("src.agents.pubmed_search_agent.agent.build_pubmed_agent")
    @pytest.mark.asyncio
    async def test_react_passes_all_budgets(self, mock_build, mock_run):
        mock_build.return_value = MagicMock()
        mock_run.return_value = "Mocked"

        agent: PubmedSearchAgent = PubmedSearchAgent(max_web_searches=2, max_pubmed_searches=3)
        await agent.react(human_message="question")

        mock_run.assert_called_once_with(
            query="question",
            graph=agent._graph,
            max_iterations=agent.max_iterations,
            max_web_searches=2,
            max_pubmed_searches=3,
        )
```

---

## 9. Testing Streaming (`stream_pubmed_agent`)

The streaming entry point uses `graph.astream()` and yields `ProgressEvent` dicts. Mock the graph's `astream` as an async generator:

```python
class TestStreamPubmedAgent:
    @pytest.mark.asyncio
    async def test_yields_events_for_each_node(self):
        mock_graph: MagicMock = MagicMock()

        async def fake_astream(initial_state, stream_mode=None):
            yield {"agent": {"messages": [AIMessage(content="planning")]}}
            yield {"tools": {"messages": [ToolMessage(content="results", tool_call_id="1")]}}
            yield {"assess": {"messages": [HumanMessage(content="## Iteration")], "iteration": 1, "search_phase": "discovery"}}
            yield {"agent": {"messages": [AIMessage(content="ready")]}}
            yield {"synthesize": {"messages": [AIMessage(content="Final answer.")]}}

        mock_graph.astream = fake_astream

        events: list[ProgressEvent] = []
        async for event in stream_pubmed_agent(query="test", graph=mock_graph):
            events.append(event)

        assert len(events) == 5
        assert events[0]["node"] == "agent"
        assert events[0]["is_final"] is False
        assert events[4]["node"] == "synthesize"
        assert events[4]["is_final"] is True
        assert events[4]["response"] == "Final answer."
```

Key things to test:
- Each node emits a `ProgressEvent`
- `is_final` is only `True` for the synthesize node
- `response` is populated only in the final event
- Iteration and phase are tracked across nodes (updated by assess node output)
- Status messages are populated with phase and iteration info
- Detail strings are extracted (tool call queries, result counts)

---

## 10. Mocking Patterns

| What to Mock | Where to Patch | Mock Type |
|---|---|---|
| LLM factory | `src.agents.<agent>.graph.create_llm` | `MagicMock` returning `MagicMock` with `.bind_tools()` |
| Graph invocation | `graph.ainvoke` | `AsyncMock` returning `{"messages": [...], "iteration": N}` |
| Graph streaming | `graph.astream` | Async generator function yielding `{node_name: {partial_state}}` |
| Graph builder | `src.agents.<agent>.agent.build_pubmed_agent` | `MagicMock` returning `MagicMock` |
| Entry point (batch) | `src.agents.<agent>.agent.run_pubmed_agent` | `AsyncMock` returning a string |
| Entry point (stream) | `src.agents.<agent>.agent.stream_pubmed_agent` | Async generator |
| AIMessage tool calls | Direct construction | `AIMessage(content="", tool_calls=[...])` |

**Always patch at the import site** (where the name is used), not at the definition site.

---

## 11. No Outbound Calls Rule

Every external dependency must be mocked. Tests must never:
- Call a real LLM API (OpenAI, Azure, Gemini)
- Execute real tool functions (PubMed, DuckDuckGo, local DB)
- Make HTTP requests
- Connect to databases

If a test makes any outbound call, it is broken — fix it by adding the appropriate mock.

---

## 12. Running Tests

```bash
# Run agent-specific tests
loadenv environments/test.env && PYTHONPATH=${PWD} poetry run pytest tests/agents/pubmed_search_agent/ -sv

# Run full suite for regression check
loadenv environments/test.env && PYTHONPATH=${PWD} poetry run pytest tests/ -sv
```

---

## 13. Routing Strategy — Clear Control Over Agent Flow

The agent's graph topology determines how internal reasoning is separated from user-facing output. The key principle: **route to a dedicated synthesize node instead of `END`**.

### Why Not Route Directly to END

When the agent node both decides what to search AND writes the final answer, internal reasoning leaks into the output. The LLM sees iteration assessment prompts ("do NOT write a response") alongside output format instructions and produces confused responses.

### The Synthesize Node Pattern

```
agent ──► _should_continue ──► "tools"       → tools → assess → agent (loop)
                             ──► "synthesize" → synthesize → END
```

1. **`_should_continue` returns node names, not `END`**: Both exit paths (`"tools"` and `"synthesize"`) point to real nodes.
2. **`add_conditional_edges` creates implicit edges**: When `_should_continue` returns `"synthesize"`, LangGraph automatically creates an edge from `agent` to `synthesize`. No explicit `add_edge("agent", "synthesize")` is needed.
3. **The synthesize node swaps prompts**: It replaces the agent system prompt with a user-facing synthesis prompt, filters internal messages, and calls the LLM without tools bound.
4. **Only synthesize routes to END**: `graph.add_edge("synthesize", END)`.

### Message Filtering in Synthesis

The synthesize node must filter messages that would confuse the synthesis LLM:

| Message Type | Action | Why |
|---|---|---|
| `SystemMessage` | Replace with `SYNTHESIS_PROMPT` | Agent prompt has tool-routing instructions, not output format |
| `HumanMessage` with "## Iteration" | Skip | Contains "do NOT write a response" that the synthesis LLM would obey |
| `HumanMessage` (user query) | Keep | The synthesis LLM needs the original question |
| `AIMessage` / `ToolMessage` | Keep | Evidence the synthesis LLM uses to write the answer |

### Prompt Separation

| Prompt | Used By | Responsibility |
|---|---|---|
| `AGENT_SYSTEM_PROMPT` | Agent node | Tool selection, PICO decomposition, evidence hierarchy, 3-phase search strategy |
| `REACT_ITERATION_PROMPT` | Assess node | Chain-of-thought evidence assessment, resource budgets, phase-specific guidance |
| `SYNTHESIS_PROMPT` | Synthesize node | User-facing output format, evidence weighting, confidence calibration, citation style |
| `PHASE_DISCOVERY_GUIDANCE` | Assess node | Phase 1 strategy — broad queries, leverage local_search |
| `PHASE_GAP_FILLING_GUIDANCE` | Assess node | Phase 2 strategy — narrow targeted queries, text_search for recency |
| `PHASE_VERIFICATION_GUIDANCE` | Assess node | Phase 3 strategy — consistency checks, aggressive stopping |

Each prompt has a single responsibility. No prompt contains both tool-routing and output-format instructions.

### Testing the Routing Strategy

Test both the routing function and the downstream behavior:

```python
# 1. Routing returns "synthesize" (not END) when done
def test_returns_synthesize_when_no_tool_calls(self):
    state = {"messages": [AIMessage(content="Done")], "iteration": 1, "max_iterations": 3}
    assert _should_continue(state) == "synthesize"

# 2. Synthesize node filters iteration messages
async def test_filters_iteration_assessment_prompts(self):
    # Verify HumanMessages with "## Iteration" are stripped

# 3. Synthesize node replaces system prompt
async def test_replaces_system_message_with_synthesis_prompt(self):
    # Verify SystemMessage is SYNTHESIS_PROMPT, not AGENT_SYSTEM_PROMPT

# 4. Graph has the synthesize node
def test_graph_has_synthesize_node(self):
    # Verify "synthesize" is in the compiled graph's node names
```

---

## 14. Checklist — Before Submitting Agent Tests

- [ ] Every decision point in nodes and routing has a test
- [ ] State mutation tests verify each field independently (including phase, all tool counts)
- [ ] Phase detection helpers tested (`_determine_phase`, `_get_phase_display_name`, `_get_phase_guidance`)
- [ ] Pure functions tested without mocks (`_build_assessment_prompt`, `_build_status_message`, `_extract_node_detail`)
- [ ] Node functions tested with constructed state dicts
- [ ] Synthesize node tests verify prompt replacement, message filtering, and output
- [ ] Graph construction tests mock `create_llm` and verify synthesize node exists
- [ ] Entry point tests capture and assert on `initial_state` (all budget fields, phase)
- [ ] Streaming tests verify event structure, iteration tracking, status messages, detail extraction
- [ ] Wrapper class tests verify parameter pass-through (including `max_pubmed_searches`)
- [ ] No outbound API calls in any test
- [ ] All tests pass (`pytest` exit code 0)
- [ ] Test classes follow `Test<FunctionOrClassName>` naming
- [ ] Test methods follow `test_<method>_when_<condition>` naming
