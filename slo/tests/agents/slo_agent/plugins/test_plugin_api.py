"""Tests for the recording-only plugin contract."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from src.agents.slo_agent.plugins import (
    AfterToolResultPatchDAO,
    BeforeAgentTurnDecisionDAO,
    BeforeToolCallDecisionDAO,
    PluginAPI,
    PluginHealthDAO,
    PluginRegistrationDAO,
)


def _build_registration() -> PluginRegistrationDAO:
    """Build an empty registration owned by one example plugin.

    Returns:
        PluginRegistrationDAO: Recorder target with a loaded health record.
    """
    return PluginRegistrationDAO(
        plugin_id="example-plugin",
        source_path="/plugins/example.py",
        health=PluginHealthDAO(
            plugin_id="example-plugin",
            source_path="/plugins/example.py",
        ),
    )


def _build_tool() -> StructuredTool:
    """Build a LangChain-shaped tool for registration tests.

    Returns:
        StructuredTool: Named tool with no external side effects.
    """

    def echo(*, text: str) -> str:
        """Echo text for the test-only tool shape.

        Args:
            text (str): Input text.

        Returns:
            str: The supplied text.
        """
        return text

    return StructuredTool.from_function(func=echo, name="echo")


class TestPluginAPI:
    """PluginAPI records declared contributions without runtime effects."""

    def test_on_appends_handlers_and_records_event_once(self) -> None:
        """Repeated subscriptions retain handlers but keep health metadata idempotent."""
        registration: PluginRegistrationDAO = _build_registration()
        api: PluginAPI = PluginAPI(registration=registration)

        def handler(_: Any) -> None:
            """Accept an event in the test subscription."""

        api.on(event_kind="run_completed", handler=handler)
        api.on(event_kind="run_completed", handler=handler)

        assert registration.event_handlers["run_completed"] == [handler, handler]
        assert registration.health.subscribed_events == ["run_completed"]

    def test_register_tool_records_named_tool(self) -> None:
        """A named LangChain tool is preserved and visible in plugin health."""
        registration: PluginRegistrationDAO = _build_registration()
        api: PluginAPI = PluginAPI(registration=registration)
        tool: StructuredTool = _build_tool()

        api.register_tool(tool=tool)

        assert registration.tools == [tool]
        assert registration.health.registered_tools == ["echo"]

    def test_register_tool_without_name_does_not_crash(self) -> None:
        """A malformed tool is retained for later merge validation without health noise."""
        registration: PluginRegistrationDAO = _build_registration()
        api: PluginAPI = PluginAPI(registration=registration)

        api.register_tool(tool=object())  # type: ignore[arg-type]

        assert registration.tools == [object()] or len(registration.tools) == 1
        assert registration.health.registered_tools == []

    def test_register_command_and_renderer_record_names(self) -> None:
        """Command and renderer contributions are retained and listed in health."""
        registration: PluginRegistrationDAO = _build_registration()
        api: PluginAPI = PluginAPI(registration=registration)

        def command() -> None:
            """Serve as a command registration placeholder."""

        def render(output: str) -> str:
            """Serve as a renderer registration placeholder.

            Args:
                output (str): Raw output.

            Returns:
                str: Unmodified output.
            """
            return output

        api.register_command(name="release", handler=command)
        api.register_tool_renderer(tool_name="echo", render=render)

        assert registration.commands == {"release": command}
        assert registration.renderers == {"echo": render}
        assert registration.health.registered_commands == ["release"]
        assert registration.health.registered_renderers == ["echo"]

    def test_set_status_sets_and_clears_segment(self) -> None:
        """Non-empty status text sets a segment and empty text removes it."""
        registration: PluginRegistrationDAO = _build_registration()
        api: PluginAPI = PluginAPI(registration=registration)

        api.set_status(key="example:state", text="running")
        api.set_status(key="example:state", text="")

        assert registration.statuses == {}


@pytest.mark.parametrize(
    "dao_type, payload",
    [
        (PluginHealthDAO, {"plugin_id": "p", "source_path": "/p", "unexpected": True}),
        (BeforeToolCallDecisionDAO, {"unexpected": True}),
        (AfterToolResultPatchDAO, {"unexpected": True}),
        (BeforeAgentTurnDecisionDAO, {"unexpected": True}),
    ],
)
def test_plugin_boundary_daos_reject_extra_fields(dao_type: type[Any], payload: dict[str, Any]) -> None:
    """Trusted-plugin boundary DAOs forbid unrecognized fields."""
    with pytest.raises(ValidationError):
        dao_type.model_validate(payload)
