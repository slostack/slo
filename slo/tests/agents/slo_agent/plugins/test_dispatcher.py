"""Tests for exception-isolated, timeout-wrapped plugin dispatch (75.a.3)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.messages import BaseMessage, HumanMessage

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.plugins.dao import (
    AfterToolResultPatchDAO,
    BeforeAgentTurnDecisionDAO,
    BeforeToolCallDecisionDAO,
    PluginHealthDAO,
    PluginRegistrationDAO,
    PluginStatus,
)
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.plugins.dispatcher import PluginDispatcher
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.plugins.registry import PluginRegistry


def _make_registration(
    *, plugin_id: str, handlers: dict[str, list[Any]] | None = None
) -> PluginRegistrationDAO:
    """Build one loaded registration with the given event handlers.

    Args:
        plugin_id (str): Plugin identifier.
        handlers (dict[str, list[Any]] | None): Event-kind → handlers map.

    Returns:
        PluginRegistrationDAO: The assembled registration.
    """
    return PluginRegistrationDAO(
        plugin_id=plugin_id,
        source_path=f"/plugins/{plugin_id}.py",
        event_handlers=handlers or {},
        health=PluginHealthDAO(
            plugin_id=plugin_id,
            source_path=f"/plugins/{plugin_id}.py",
            status=PluginStatus.LOADED,
        ),
    )


def _build_dispatcher(
    *,
    registrations: list[PluginRegistrationDAO],
    before_tool_call: dict[str, list[Any]] | None = None,
    after_tool_result: dict[str, list[Any]] | None = None,
    before_agent_turn: list[Any] | None = None,
    timeout_seconds: float = 5.0,
) -> PluginDispatcher:
    """Build a dispatcher over the given registrations and interceptor chains.

    Args:
        registrations (list[PluginRegistrationDAO]): Observation registrations.
        before_tool_call (dict[str, list[Any]] | None): plugin_id → handlers.
        after_tool_result (dict[str, list[Any]] | None): plugin_id → handlers.
        before_agent_turn (list[Any] | None): Handlers for the agent-turn point.
        timeout_seconds (float): Per-handler interception timeout.

    Returns:
        PluginDispatcher: The wired dispatcher.
    """
    return PluginDispatcher(
        registry=PluginRegistry(registrations=registrations),
        before_tool_call_handlers=before_tool_call or {},
        after_tool_result_handlers=after_tool_result or {},
        before_agent_turn_handlers=before_agent_turn or [],
        interception_timeout_seconds=timeout_seconds,
    )


class TestObservationEmit:
    """``emit`` fans events to subscribed handlers with exception isolation."""

    @pytest.mark.asyncio
    async def test_emit_reaches_only_subscribed_handlers(self) -> None:
        """Handlers for the event's kind fire; others do not."""
        seen: list[str] = []

        def _on_completed(event: AgentStreamEventDAO) -> None:
            """Record one run_completed observation.

            Args:
                event (AgentStreamEventDAO): The stream event.
            """
            seen.append(f"completed:{event.kind}")

        def _on_other(event: AgentStreamEventDAO) -> None:
            """Record an unrelated observation.

            Args:
                event (AgentStreamEventDAO): The stream event.
            """
            seen.append("other")

        dispatcher: PluginDispatcher = _build_dispatcher(
            registrations=[
                _make_registration(plugin_id="one", handlers={"run_completed": [_on_completed]}),
                _make_registration(plugin_id="two", handlers={"tool_result": [_on_other]}),
            ]
        )

        await dispatcher.emit(event=AgentStreamEventDAO(kind="run_completed"))

        assert seen == ["completed:run_completed"]

    @pytest.mark.asyncio
    async def test_emit_dispatches_async_handlers(self) -> None:
        """An async handler is awaited through the isawaitable dispatch."""
        seen: list[str] = []

        async def _async_handler(event: AgentStreamEventDAO) -> None:
            """Record asynchronously.

            Args:
                event (AgentStreamEventDAO): The stream event.
            """
            await asyncio.sleep(0)
            seen.append("async")

        dispatcher: PluginDispatcher = _build_dispatcher(
            registrations=[_make_registration(plugin_id="one", handlers={"run_completed": [_async_handler]})]
        )

        await dispatcher.emit(event=AgentStreamEventDAO(kind="run_completed"))

        assert seen == ["async"]

    @pytest.mark.asyncio
    async def test_handler_exception_is_isolated_and_counted(self) -> None:
        """A raising handler never fails siblings or the run; health counts it."""
        seen: list[str] = []

        def _raising(event: AgentStreamEventDAO) -> None:
            """Raise unconditionally.

            Args:
                event (AgentStreamEventDAO): The stream event.
            """
            raise RuntimeError("handler boom")

        def _healthy(event: AgentStreamEventDAO) -> None:
            """Record a healthy observation.

            Args:
                event (AgentStreamEventDAO): The stream event.
            """
            seen.append("healthy")

        bad: PluginRegistrationDAO = _make_registration(
            plugin_id="bad", handlers={"run_completed": [_raising]}
        )
        good: PluginRegistrationDAO = _make_registration(
            plugin_id="good", handlers={"run_completed": [_healthy]}
        )
        dispatcher: PluginDispatcher = _build_dispatcher(registrations=[bad, good])

        await dispatcher.emit(event=AgentStreamEventDAO(kind="run_completed"))

        assert seen == ["healthy"]
        assert bad.health.handler_failures == 1
        assert good.health.handler_failures == 0


class TestBeforeToolCallChain:
    """``run_before_tool_call`` folds mutations and short-circuits on block."""

    @pytest.mark.asyncio
    async def test_mutated_input_flows_to_later_handler(self) -> None:
        """A handler's mutation is visible to the next handler in load order."""
        seen_inputs: list[dict[str, Any]] = []

        def _first(
            decision: BeforeToolCallDecisionDAO, tool_input: dict[str, Any]
        ) -> BeforeToolCallDecisionDAO:
            """Prefix the command argument.

            Args:
                decision (BeforeToolCallDecisionDAO): Current folded decision.
                tool_input (dict[str, Any]): Current args.

            Returns:
                BeforeToolCallDecisionDAO: Decision carrying the mutation.
            """
            mutated: dict[str, Any] = dict(tool_input)
            mutated["command"] = f"safe {tool_input['command']}"
            return BeforeToolCallDecisionDAO(mutated_input=mutated)

        def _second(
            decision: BeforeToolCallDecisionDAO, tool_input: dict[str, Any]
        ) -> BeforeToolCallDecisionDAO:
            """Record the args this handler sees.

            Args:
                decision (BeforeToolCallDecisionDAO): Current folded decision.
                tool_input (dict[str, Any]): Current args.

            Returns:
                BeforeToolCallDecisionDAO: Unchanged decision.
            """
            seen_inputs.append(dict(tool_input))
            return decision

        dispatcher: PluginDispatcher = _build_dispatcher(
            registrations=[],
            before_tool_call={"one": [_first], "two": [_second]},
        )

        folded: BeforeToolCallDecisionDAO = await dispatcher.run_before_tool_call(
            tool_name="bash",
            tool_call_id="call-1",
            tool_input={"command": "ls"},
        )

        assert seen_inputs == [{"command": "safe ls"}]
        assert folded.mutated_input == {"command": "safe ls"}
        assert folded.block is False

    @pytest.mark.asyncio
    async def test_block_short_circuits_chain(self) -> None:
        """The first block verdict stops the chain; later handlers never run."""
        ran: list[str] = []

        def _blocker(
            decision: BeforeToolCallDecisionDAO, tool_input: dict[str, Any]
        ) -> BeforeToolCallDecisionDAO:
            """Block the call.

            Args:
                decision (BeforeToolCallDecisionDAO): Current folded decision.
                tool_input (dict[str, Any]): Current args.

            Returns:
                BeforeToolCallDecisionDAO: Block verdict with reason.
            """
            return BeforeToolCallDecisionDAO(block=True, reason="nope")

        def _later(
            decision: BeforeToolCallDecisionDAO, tool_input: dict[str, Any]
        ) -> BeforeToolCallDecisionDAO:
            """Record that this handler ran.

            Args:
                decision (BeforeToolCallDecisionDAO): Current folded decision.
                tool_input (dict[str, Any]): Current args.

            Returns:
                BeforeToolCallDecisionDAO: Unchanged decision.
            """
            ran.append("later")
            return decision

        dispatcher: PluginDispatcher = _build_dispatcher(
            registrations=[],
            before_tool_call={"one": [_blocker], "two": [_later]},
        )

        folded: BeforeToolCallDecisionDAO = await dispatcher.run_before_tool_call(
            tool_name="bash",
            tool_call_id="call-1",
            tool_input={},
        )

        assert folded.block is True
        assert folded.reason == "nope"
        assert ran == []

    @pytest.mark.asyncio
    async def test_timeout_means_no_opinion_and_chain_continues(self) -> None:
        """A handler over the timeout is skipped; the failure is recorded."""

        async def _slow(
            decision: BeforeToolCallDecisionDAO, tool_input: dict[str, Any]
        ) -> BeforeToolCallDecisionDAO:
            """Sleep past the interception budget.

            Args:
                decision (BeforeToolCallDecisionDAO): Current folded decision.
                tool_input (dict[str, Any]): Current args.

            Returns:
                BeforeToolCallDecisionDAO: Never returns in time.
            """
            await asyncio.sleep(5)
            return decision

        def _fast(
            decision: BeforeToolCallDecisionDAO, tool_input: dict[str, Any]
        ) -> BeforeToolCallDecisionDAO:
            """Return a quick mutation.

            Args:
                decision (BeforeToolCallDecisionDAO): Current folded decision.
                tool_input (dict[str, Any]): Current args.

            Returns:
                BeforeToolCallDecisionDAO: Mutation verdict.
            """
            return BeforeToolCallDecisionDAO(mutated_input={"x": 1})

        slow_owner: PluginRegistrationDAO = _make_registration(plugin_id="slow")
        fast_owner: PluginRegistrationDAO = _make_registration(plugin_id="fast")
        dispatcher: PluginDispatcher = _build_dispatcher(
            registrations=[slow_owner, fast_owner],
            before_tool_call={"slow": [_slow], "fast": [_fast]},
            timeout_seconds=0.05,
        )

        folded: BeforeToolCallDecisionDAO = await dispatcher.run_before_tool_call(
            tool_name="bash",
            tool_call_id="call-1",
            tool_input={},
        )

        assert folded.mutated_input == {"x": 1}
        assert slow_owner.health.handler_failures == 1
        assert fast_owner.health.handler_failures == 0

    @pytest.mark.asyncio
    async def test_handler_exception_means_no_opinion(self) -> None:
        """A raising interceptor is skipped and counted, never propagated."""

        def _raising(
            decision: BeforeToolCallDecisionDAO, tool_input: dict[str, Any]
        ) -> BeforeToolCallDecisionDAO:
            """Raise unconditionally.

            Args:
                decision (BeforeToolCallDecisionDAO): Current folded decision.
                tool_input (dict[str, Any]): Current args.

            Returns:
                BeforeToolCallDecisionDAO: Never returns.
            """
            raise RuntimeError("interceptor boom")

        owner: PluginRegistrationDAO = _make_registration(plugin_id="bad")
        dispatcher: PluginDispatcher = _build_dispatcher(
            registrations=[owner],
            before_tool_call={"bad": [_raising]},
        )

        folded: BeforeToolCallDecisionDAO = await dispatcher.run_before_tool_call(
            tool_name="bash",
            tool_call_id="call-1",
            tool_input={},
        )

        assert folded.block is False
        assert folded.mutated_input is None
        assert owner.health.handler_failures == 1


class TestAfterToolResultChain:
    """``run_after_tool_result`` chains content patches middleware-style."""

    @pytest.mark.asyncio
    async def test_patches_fold_in_load_order(self) -> None:
        """Each handler sees the latest content; the final patch wins."""

        def _first(content: str, is_error: bool) -> AfterToolResultPatchDAO:
            """Append one marker.

            Args:
                content (str): Latest content.
                is_error (bool): Latest error flag.

            Returns:
                AfterToolResultPatchDAO: Patched content.
            """
            return AfterToolResultPatchDAO(content=f"{content}+one")

        def _second(content: str, is_error: bool) -> AfterToolResultPatchDAO:
            """Append a second marker.

            Args:
                content (str): Latest content.
                is_error (bool): Latest error flag.

            Returns:
                AfterToolResultPatchDAO: Patched content and error flag.
            """
            return AfterToolResultPatchDAO(content=f"{content}+two", is_error=True)

        dispatcher: PluginDispatcher = _build_dispatcher(
            registrations=[],
            after_tool_result={"one": [_first], "two": [_second]},
        )

        patch: AfterToolResultPatchDAO = await dispatcher.run_after_tool_result(
            tool_name="bash",
            tool_call_id="call-1",
            content="base",
            is_error=False,
        )

        assert patch.content == "base+one+two"
        assert patch.is_error is True

    @pytest.mark.asyncio
    async def test_omitted_fields_keep_current_values(self) -> None:
        """A handler returning an empty patch changes nothing."""

        def _noop(content: str, is_error: bool) -> AfterToolResultPatchDAO:
            """Offer no patch.

            Args:
                content (str): Latest content.
                is_error (bool): Latest error flag.

            Returns:
                AfterToolResultPatchDAO: Empty patch.
            """
            return AfterToolResultPatchDAO()

        dispatcher: PluginDispatcher = _build_dispatcher(
            registrations=[],
            after_tool_result={"one": [_noop]},
        )

        patch: AfterToolResultPatchDAO = await dispatcher.run_after_tool_result(
            tool_name="bash",
            tool_call_id="call-1",
            content="base",
            is_error=False,
        )

        assert patch.content is None
        assert patch.is_error is None


class TestBeforeAgentTurnInAgentLoop:
    """The agent, not the session, owns the per-outer-iteration hook timing."""

    @pytest.mark.asyncio
    async def test_before_agent_turn_runs_for_each_tool_iteration_with_actual_numbers(self) -> None:
        """A tool turn invokes handlers for iteration zero and its real follow-up."""
        observed_iterations: list[int] = []

        def _inject(iteration: int) -> BeforeAgentTurnDecisionDAO:
            """Record the actual outer loop number.

            Args:
                iteration (int): Upcoming outer ReAct iteration.

            Returns:
                BeforeAgentTurnDecisionDAO: No-op context contribution.
            """
            observed_iterations.append(iteration)
            return BeforeAgentTurnDecisionDAO()

        dispatcher: PluginDispatcher = _build_dispatcher(registrations=[])
        dispatcher.register_before_agent_turn_handler(owner="__unowned__", handler=_inject)
        faux: FauxChatModel = FauxChatModel(
            responses=[
                FauxChatModel.assistant_message(
                    tool_calls=[FauxChatModel.tool_call_dict(name="echo", args={})],
                ),
                FauxChatModel.assistant_message(content="done"),
            ]
        )
        from langchain_core.tools import tool

        @tool
        def echo() -> str:
            """Return terminal output for the agent loop test."""
            return "ok"

        agent: SloAgent = SloAgent(llm=faux, tools=[echo], plugin_dispatcher=dispatcher)

        async for _ in agent.invoke(query="run two turns"):
            pass

        assert observed_iterations == [0, 1]


class TestBeforeAgentTurnChain:
    """``run_before_agent_turn`` aggregates injected context messages."""

    @pytest.mark.asyncio
    async def test_injected_messages_aggregate_in_load_order(self) -> None:
        """Every handler's messages land in the aggregated decision."""

        def _first(iteration: int) -> BeforeAgentTurnDecisionDAO:
            """Inject one message.

            Args:
                iteration (int): Upcoming iteration number.

            Returns:
                BeforeAgentTurnDecisionDAO: One injected message.
            """
            return BeforeAgentTurnDecisionDAO(inject_messages=[HumanMessage(content="from-first")])

        async def _second(iteration: int) -> BeforeAgentTurnDecisionDAO:
            """Inject one message asynchronously.

            Args:
                iteration (int): Upcoming iteration number.

            Returns:
                BeforeAgentTurnDecisionDAO: One injected message.
            """
            return BeforeAgentTurnDecisionDAO(inject_messages=[HumanMessage(content="from-second")])

        dispatcher: PluginDispatcher = _build_dispatcher(
            registrations=[],
            before_agent_turn=[_first, _second],
        )

        decision: BeforeAgentTurnDecisionDAO = await dispatcher.run_before_agent_turn(iteration=2)

        contents: list[str] = [str(message.content) for message in decision.inject_messages]
        assert contents == ["from-first", "from-second"]

    @pytest.mark.asyncio
    async def test_raising_turn_handler_is_isolated(self) -> None:
        """A raising before_agent_turn handler contributes nothing and is counted."""

        def _raising(iteration: int) -> BeforeAgentTurnDecisionDAO:
            """Raise unconditionally.

            Args:
                iteration (int): Upcoming iteration number.

            Returns:
                BeforeAgentTurnDecisionDAO: Never returns.
            """
            raise RuntimeError("turn boom")

        owner: PluginRegistrationDAO = _make_registration(plugin_id="bad")
        dispatcher: PluginDispatcher = _build_dispatcher(
            registrations=[owner],
            before_agent_turn=[],
        )
        dispatcher.register_before_agent_turn_handler(owner="bad", handler=_raising)

        decision: BeforeAgentTurnDecisionDAO = await dispatcher.run_before_agent_turn(iteration=0)

        assert decision.inject_messages == []
        assert owner.health.handler_failures == 1


class TestLiveStatusMap:
    """A1: the dispatcher owns the live footer-status map."""

    def test_status_map_seeds_from_registry_and_updates_at_event_time(self) -> None:
        """Registered statuses seed the map; set_status mutates it live."""
        registration: PluginRegistrationDAO = _make_registration(plugin_id="ci-watch")
        registration.statuses["ci-watch:status"] = "seed"
        dispatcher: PluginDispatcher = _build_dispatcher(registrations=[registration])

        assert dispatcher.status_map() == {"ci-watch:status": "seed"}

        dispatcher.set_status(key="ci-watch:status", text="tests running")

        assert dispatcher.status_map() == {"ci-watch:status": "tests running"}

    def test_set_status_with_empty_text_clears_the_segment(self) -> None:
        """An empty status text removes the key from the live map."""
        registration: PluginRegistrationDAO = _make_registration(plugin_id="ci-watch")
        registration.statuses["ci-watch:status"] = "seed"
        dispatcher: PluginDispatcher = _build_dispatcher(registrations=[registration])

        dispatcher.set_status(key="ci-watch:status", text="")

        assert dispatcher.status_map() == {}
