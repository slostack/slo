"""Exception-isolated, ordered plugin observation and interception dispatch."""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Awaitable, Callable
from typing import Any, Optional, Protocol

from config.logger import log_error
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.plugins.dao import (
    AfterToolResultPatchDAO,
    BeforeAgentTurnDecisionDAO,
    BeforeToolCallDecisionDAO,
    PluginRegistrationDAO,
)
from src.agents.slo_agent.plugins.registry import PluginRegistry

__all__ = ["PluginDispatcher", "PluginToolInterceptorProtocol"]

_DEFAULT_INTERCEPTION_TIMEOUT_SECONDS: float = 5.0


class PluginToolInterceptorProtocol(Protocol):
    """Typed executor-facing subset of plugin interception dispatch."""

    async def run_before_tool_call(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        tool_input: dict[str, Any],
    ) -> BeforeToolCallDecisionDAO:
        """Return the pre-tool decision for one invocation."""

    async def run_after_tool_result(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        content: str,
        is_error: bool,
    ) -> AfterToolResultPatchDAO:
        """Return the terminal-result patch for one invocation."""


class PluginDispatcher:
    """Call plugin handlers without allowing them to fail the Slo runtime.

    WHAT: Fans stream events and executes ordered interception chains with an
        independent timeout and health accounting for every handler.
    WHO: Session subscribers use ``emit``; future tool/agent seams invoke the
        interception methods.
    WHEN: After plugin registrations have been merged for a session.
    """

    def __init__(
        self,
        *,
        registry: PluginRegistry,
        before_tool_call_handlers: Optional[dict[str, list[Callable[..., Any]]]] = None,
        after_tool_result_handlers: Optional[dict[str, list[Callable[..., Any]]]] = None,
        before_agent_turn_handlers: Optional[list[Callable[..., Any]]] = None,
        interception_timeout_seconds: Optional[float] = None,
    ) -> None:
        """Bind ordered handlers and seed the runtime-status map.

        Args:
            registry (PluginRegistry): Authority over registrations and health.
            before_tool_call_handlers (Optional[dict[str, list[Callable[..., Any]]]]):
                Explicit ordered interceptors by plugin id.
            after_tool_result_handlers (Optional[dict[str, list[Callable[..., Any]]]]):
                Explicit ordered result interceptors by plugin id.
            before_agent_turn_handlers (Optional[list[Callable[..., Any]]]): Ordered
                context-injection handlers.
            interception_timeout_seconds (Optional[float]): Test/config override.
        """
        self._registry: PluginRegistry = registry
        self._before_tool_call_handlers: dict[str, list[Callable[..., Any]]] = before_tool_call_handlers or {}
        self._after_tool_result_handlers: dict[str, list[Callable[..., Any]]] = (
            after_tool_result_handlers or {}
        )
        self._before_agent_turn_handlers: list[Callable[..., Any] | tuple[str, Callable[..., Any]]] = list(
            before_agent_turn_handlers or []
        )
        self._interception_timeout_seconds: float = (
            interception_timeout_seconds or _interception_timeout_seconds()
        )
        self._status_map: dict[str, str] = registry.all_statuses()

    async def emit(self, event: AgentStreamEventDAO) -> None:
        """Fan one bus event only to registrations subscribed to its kind.

        Args:
            event (AgentStreamEventDAO): Session stream event to observe.
        """
        for registration, handler in self._registry.handlers_for(event_kind=event.kind):
            await self._invoke_observer(registration=registration, handler=handler, event=event)

    async def run_before_tool_call(
        self, *, tool_name: str, tool_call_id: str, tool_input: dict[str, Any]
    ) -> BeforeToolCallDecisionDAO:
        """Fold ordered pre-tool mutations and stop on the first block verdict.

        Args:
            tool_name (str): Tool about to execute.
            tool_call_id (str): Stable call identity.
            tool_input (dict[str, Any]): Original call input.

        Returns:
            BeforeToolCallDecisionDAO: Folded block reason and latest input mutation.
        """
        current_input: dict[str, Any] = dict(tool_input)
        for owner, handler in self._ordered_handlers(handlers=self._before_tool_call_handlers):
            outcome: object = await self._invoke_interceptor(
                owner=owner,
                handler=handler,
                arguments=(BeforeToolCallDecisionDAO(mutated_input=current_input), current_input),
            )
            if not isinstance(outcome, BeforeToolCallDecisionDAO):
                continue
            if outcome.mutated_input is not None:
                current_input = dict(outcome.mutated_input)
            if outcome.block:
                return BeforeToolCallDecisionDAO(
                    block=True,
                    reason=outcome.reason,
                    mutated_input=current_input,
                )
        mutation: Optional[dict[str, Any]] = current_input if current_input != tool_input else None
        return BeforeToolCallDecisionDAO(mutated_input=mutation)

    async def run_after_tool_result(
        self, *, tool_name: str, tool_call_id: str, content: str, is_error: bool
    ) -> AfterToolResultPatchDAO:
        """Fold result patches so each handler receives the prior handler's result.

        Args:
            tool_name (str): Tool that settled.
            tool_call_id (str): Stable call identity.
            content (str): Current terminal content.
            is_error (bool): Current terminal error state.

        Returns:
            AfterToolResultPatchDAO: Only fields changed by the ordered chain.
        """
        current_content: str = content
        current_error: bool = is_error
        changed_content: bool = False
        changed_error: bool = False
        for owner, handler in self._ordered_handlers(handlers=self._after_tool_result_handlers):
            outcome: object = await self._invoke_interceptor(
                owner=owner,
                handler=handler,
                arguments=(current_content, current_error),
            )
            if not isinstance(outcome, AfterToolResultPatchDAO):
                continue
            if outcome.content is not None:
                current_content = outcome.content
                changed_content = True
            if outcome.is_error is not None:
                current_error = outcome.is_error
                changed_error = True
        return AfterToolResultPatchDAO(
            content=current_content if changed_content else None,
            is_error=current_error if changed_error else None,
        )

    def has_before_agent_turn_handlers(self) -> bool:
        """Return whether this dispatcher has any pre-agent-turn interceptor.

        Returns:
            bool: True when invoking the chain can contribute context.
        """
        return bool(self._before_agent_turn_handlers)

    async def run_before_agent_turn(self, *, iteration: int) -> BeforeAgentTurnDecisionDAO:
        """Collect ordered, isolated context additions for an upcoming model call.

        Args:
            iteration (int): Upcoming outer ReAct iteration.

        Returns:
            BeforeAgentTurnDecisionDAO: Aggregated injected messages in handler order.
        """
        aggregated: BeforeAgentTurnDecisionDAO = BeforeAgentTurnDecisionDAO()
        for owner, handler in self._ordered_turn_handlers():
            outcome: object = await self._invoke_interceptor(
                owner=owner,
                handler=handler,
                arguments=(iteration,),
            )
            if isinstance(outcome, BeforeAgentTurnDecisionDAO):
                aggregated.inject_messages.extend(outcome.inject_messages)
        return aggregated

    def register_before_tool_call_handler(self, *, owner: str, handler: Callable[..., Any]) -> None:
        """Append one pre-tool interceptor for the named plugin.

        Args:
            owner (str): Plugin id for health accounting.
            handler (Callable[..., Any]): Typed pre-tool callback.
        """
        self._before_tool_call_handlers.setdefault(owner, []).append(handler)

    def register_after_tool_result_handler(self, *, owner: str, handler: Callable[..., Any]) -> None:
        """Append one post-result interceptor for the named plugin.

        Args:
            owner (str): Plugin id for health accounting.
            handler (Callable[..., Any]): Typed post-result callback.
        """
        self._after_tool_result_handlers.setdefault(owner, []).append(handler)

    def register_before_agent_turn_handler(self, *, owner: str, handler: Callable[..., Any]) -> None:
        """Append one explicit turn interceptor for the named registration.

        Args:
            owner (str): Owning plugin id for health accounting.
            handler (Callable[..., Any]): Typed interception callback.
        """
        self._before_agent_turn_handlers.append((owner, handler))

    def set_status(self, *, key: str, text: str) -> None:
        """Set or clear one live plugin footer segment.

        Args:
            key (str): Derived plugin footer key.
            text (str): Visible text, or empty text to remove it.
        """
        if text:
            self._status_map[key] = text
            return
        self._status_map.pop(key, None)

    def status_map(self) -> dict[str, str]:
        """Return a copy of all current plugin footer statuses.

        Returns:
            dict[str, str]: Derived status key to visible text.
        """
        return dict(self._status_map)

    async def _invoke_observer(
        self, *, registration: PluginRegistrationDAO, handler: Callable[..., Any], event: AgentStreamEventDAO
    ) -> None:
        """Invoke one observer with exception isolation.

        Args:
            registration (PluginRegistrationDAO): Health owner.
            handler (Callable[..., Any]): Sync or async event observer.
            event (AgentStreamEventDAO): Event passed to the observer.
        """
        try:
            outcome: object = handler(event)
            if inspect.isawaitable(outcome):
                await outcome
        except Exception as exc:  # noqa: BLE001 -- extensions cannot break runs
            self._record_failure(registration=registration, error=exc)

    async def _invoke_interceptor(
        self, *, owner: str, handler: Callable[..., Any], arguments: tuple[object, ...]
    ) -> object:
        """Call one interceptor under the per-handler timeout budget.

        Args:
            owner (str): Plugin id owning the handler.
            handler (Callable[..., Any]): Sync or async interceptor.
            arguments (tuple[object, ...]): Ordered interceptor arguments.

        Returns:
            object: Handler result, or ``None`` after failure/timeout.
        """
        registration: Optional[PluginRegistrationDAO] = self._registration_for(owner=owner)
        try:
            outcome: object = handler(*arguments)
            if inspect.isawaitable(outcome):
                return await asyncio.wait_for(outcome, timeout=self._interception_timeout_seconds)
            return outcome
        except Exception as exc:  # noqa: BLE001 -- timeout and plugin exceptions are no-op
            if registration is not None:
                self._record_failure(registration=registration, error=exc)
            return None

    def _ordered_handlers(
        self, *, handlers: dict[str, list[Callable[..., Any]]]
    ) -> list[tuple[str, Callable[..., Any]]]:
        """Flatten explicit handler maps in insertion order.

        Args:
            handlers (dict[str, list[Callable[..., Any]]]): Owner-keyed handler map.

        Returns:
            list[tuple[str, Callable[..., Any]]]: Ordered owner/handler pairs.
        """
        return [(owner, handler) for owner, entries in handlers.items() for handler in entries]

    def _ordered_turn_handlers(self) -> list[tuple[str, Callable[..., Any]]]:
        """Normalize legacy bare turn handlers and explicit owner tuples.

        Returns:
            list[tuple[str, Callable[..., Any]]]: Ordered owned handlers.
        """
        pairs: list[tuple[str, Callable[..., Any]]] = []
        for entry in self._before_agent_turn_handlers:
            if isinstance(entry, tuple):
                pairs.append(entry)
                continue
            health_reports = self._registry.health_reports()
            owner: str = health_reports[0].plugin_id if health_reports else "__unowned__"
            pairs.append((owner, entry))
        return pairs

    def _registration_for(self, *, owner: str) -> Optional[PluginRegistrationDAO]:
        """Resolve a registration by id for health updates.

        Args:
            owner (str): Plugin id.

        Returns:
            Optional[PluginRegistrationDAO]: Registration when loaded.
        """
        return self._registry.registration_for(plugin_id=owner)

    @staticmethod
    def _record_failure(*, registration: PluginRegistrationDAO, error: Exception) -> None:
        """Increment health and log an isolated plugin failure.

        Args:
            registration (PluginRegistrationDAO): Health record to update.
            error (Exception): Exception or timeout raised by plugin code.
        """
        registration.health.handler_failures += 1
        log_error(msg=f"Plugin {registration.plugin_id} handler raised", e=error, stack_trace=False)


def _interception_timeout_seconds() -> float:
    """Read the configured interception timeout with a safe five-second default.

    Returns:
        float: Positive per-handler timeout in seconds.
    """
    raw_value: str = os.environ.get("SLO_PLUGIN_INTERCEPTION_TIMEOUT_SECONDS", "")
    try:
        configured: float = float(raw_value)
    except ValueError:
        return _DEFAULT_INTERCEPTION_TIMEOUT_SECONDS
    return configured if configured > 0 else _DEFAULT_INTERCEPTION_TIMEOUT_SECONDS
