"""The recording-only API passed to a trusted plugin's register factory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool

from src.agents.slo_agent.plugins.dao import (
    PluginEventHandler,
    PluginRegistrationDAO,
    PluginRendererFn,
    PluginStatusSetter,
)

__all__ = ["PluginAPI"]


class PluginAPI:
    """Record one plugin's declarations without mutating the active runtime.

    WHAT: Captures extension requests in its registration record only.
    WHO: Constructed by the loader and received by a plugin's ``register`` function.
    WHEN: During session startup before the registry validates and applies entries.
    """

    def __init__(
        self,
        *,
        registration: PluginRegistrationDAO,
        status_setter: PluginStatusSetter | None = None,
    ) -> None:
        """Bind the recorder to one plugin registration.

        Args:
            registration (PluginRegistrationDAO): Registration record to populate.
            status_setter (PluginStatusSetter | None): Live dispatcher-owned
                status-map writer, or ``None`` during load-time recording.
        """
        self._registration: PluginRegistrationDAO = registration
        self._status_setter: PluginStatusSetter | None = status_setter

    def on(self, *, event_kind: str, handler: PluginEventHandler) -> None:
        """Record one event subscription.

        Args:
            event_kind (str): Event kind the handler observes.
            handler (PluginEventHandler): Sync-or-async callback to record.
        """
        self._registration.event_handlers.setdefault(event_kind, []).append(handler)
        self._record_once(values=self._registration.health.subscribed_events, value=event_kind)

    def register_tool(self, *, tool: BaseTool) -> None:
        """Record one tool contribution for later registry validation.

        Args:
            tool (BaseTool): Tool to make available if it passes merge validation.
        """
        self._registration.tools.append(tool)
        tool_name: str = getattr(tool, "name", "") or ""
        if not tool_name:
            return
        self._record_once(values=self._registration.health.registered_tools, value=tool_name)

    def register_command(self, *, name: str, handler: Callable[..., Any]) -> None:
        """Record one slash-command contribution.

        Args:
            name (str): Plugin-local command token.
            handler (Callable[..., Any]): Handler applied by the slash-command owner.
        """
        self._registration.commands[name] = handler
        self._record_once(values=self._registration.health.registered_commands, value=name)

    def register_tool_renderer(self, *, tool_name: str, render: PluginRendererFn) -> None:
        """Record one tool-output renderer override.

        Args:
            tool_name (str): Plugin-local tool key the renderer targets.
            render (PluginRendererFn): Raw-output-to-display-summary callback.
        """
        self._registration.renderers[tool_name] = render
        self._record_once(values=self._registration.health.registered_renderers, value=tool_name)

    def set_status(self, *, key: str, text: str) -> None:
        """Set or clear one plugin-owned footer status segment.

        Args:
            key (str): Stable plugin-derived segment key.
            text (str): Non-empty text sets the segment; empty text clears it.
        """
        if not text:
            self._registration.statuses.pop(key, None)
            self._write_live_status(key=key, text=text)
            return
        self._registration.statuses[key] = text
        self._write_live_status(key=key, text=text)

    def _write_live_status(self, *, key: str, text: str) -> None:
        """Forward an event-time status update to the session-owned live map.

        Args:
            key (str): Derived plugin status key.
            text (str): Visible text or an empty clear marker.
        """
        if self._status_setter is None:
            return
        self._status_setter(key, text)

    def on_before_tool_call(self, *, handler: Callable[..., Any]) -> None:
        """Record one ``before_tool_call`` interception handler.

        Args:
            handler (Callable[..., Any]): ``(decision, tool_input)`` →
                ``BeforeToolCallDecisionDAO`` sync-or-async handler.
        """
        self._registration.before_tool_call_handlers.append(handler)

    def on_after_tool_result(self, *, handler: Callable[..., Any]) -> None:
        """Record one ``after_tool_result`` interception handler.

        Args:
            handler (Callable[..., Any]): ``(content, is_error)`` →
                ``AfterToolResultPatchDAO`` sync-or-async handler.
        """
        self._registration.after_tool_result_handlers.append(handler)

    def on_before_agent_turn(self, *, handler: Callable[..., Any]) -> None:
        """Record one ``before_agent_turn`` interception handler.

        Args:
            handler (Callable[..., Any]): ``(iteration)`` →
                ``BeforeAgentTurnDecisionDAO`` sync-or-async handler.
        """
        self._registration.before_agent_turn_handlers.append(handler)

    @staticmethod
    def _record_once(*, values: list[str], value: str) -> None:
        """Append a health contribution only when it has not been recorded.

        Args:
            values (list[str]): Health list to update.
            value (str): Contribution name to record.
        """
        if value in values:
            return
        values.append(value)
