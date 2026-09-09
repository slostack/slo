"""Tests for the in-memory plugin registry and its collision policy (75.a.3)."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import BaseTool

from src.agents.slo_agent.plugins.dao import (
    PluginHealthDAO,
    PluginRegistrationDAO,
    PluginStatus,
)
from src.agents.slo_agent.plugins.registry import PluginRegistry


class _NamedTool(BaseTool):
    """Minimal named tool for registry tests."""

    name: str = "unset"
    description: str = "test tool"

    def _run(self, **_: Any) -> str:
        """Reject the sync path.

        Returns:
            str: Never returns.

        Raises:
            RuntimeError: Registry tests never execute tools.
        """
        raise RuntimeError("registry tests never run tools")

    async def _arun(self, **_: Any) -> str:
        """Return a fixed marker.

        Returns:
            str: Fixed output.
        """
        return "ok"


def _make_registration(
    *,
    plugin_id: str,
    tools: list[BaseTool] | None = None,
    commands: dict[str, Any] | None = None,
    renderers: dict[str, Any] | None = None,
    statuses: dict[str, str] | None = None,
    handlers: dict[str, list[Any]] | None = None,
    status: PluginStatus = PluginStatus.LOADED,
) -> PluginRegistrationDAO:
    """Build one registration record with the given contributions.

    Args:
        plugin_id (str): Plugin identifier.
        tools (list[BaseTool] | None): Contributed tools.
        commands (dict[str, Any] | None): Contributed slash commands.
        renderers (dict[str, Any] | None): Contributed renderer overrides.
        statuses (dict[str, str] | None): Contributed footer statuses.
        handlers (dict[str, list[Any]] | None): Contributed event handlers.
        status (PluginStatus): Lifecycle status for the health record.

    Returns:
        PluginRegistrationDAO: The assembled registration.
    """
    return PluginRegistrationDAO(
        plugin_id=plugin_id,
        source_path=f"/plugins/{plugin_id}.py",
        event_handlers=handlers or {},
        tools=tools or [],
        commands=commands or {},
        renderers=renderers or {},
        statuses=statuses or {},
        health=PluginHealthDAO(
            plugin_id=plugin_id,
            source_path=f"/plugins/{plugin_id}.py",
            status=status,
        ),
    )


class _ManifestStub:
    """Structural stand-in for the installer's manifest suffix lists."""

    def __init__(self, *, tool_suffixes: list[str], command_suffixes: list[str]) -> None:
        """Record the declared suffixes.

        Args:
            tool_suffixes (list[str]): Declared tool suffixes.
            command_suffixes (list[str]): Declared command suffixes.
        """
        self.tool_suffixes: list[str] = tool_suffixes
        self.command_suffixes: list[str] = command_suffixes


class TestAggregatedViews:
    """The registry exposes merged, load-ordered views."""

    def test_aggregated_views_merge_registrations_in_load_order(self) -> None:
        """Tools, commands, renderers, statuses, and handlers aggregate."""

        def _handler_a(event: Any) -> None:
            """First observer.

            Args:
                event (Any): Stream event.
            """

        def _handler_b(event: Any) -> None:
            """Second observer.

            Args:
                event (Any): Stream event.
            """

        first: PluginRegistrationDAO = _make_registration(
            plugin_id="alpha-tools",
            tools=[_NamedTool(name="alpha_tools__deploy")],
            commands={"alpha-tools:ship": lambda: "ship"},
            renderers={"bash": str},
            statuses={"alpha-tools:status": "ready"},
            handlers={"run_completed": [_handler_a]},
        )
        second: PluginRegistrationDAO = _make_registration(
            plugin_id="beta",
            tools=[_NamedTool(name="beta__scan")],
            handlers={"run_completed": [_handler_b]},
        )
        registry: PluginRegistry = PluginRegistry(registrations=[first, second])
        registry.merge_all()

        assert [tool.name for tool in registry.all_tools()] == ["alpha_tools__deploy", "beta__scan"]
        assert list(registry.all_commands()) == ["alpha-tools:ship"]
        assert list(registry.all_renderers()) == ["bash"]
        assert registry.all_statuses() == {"alpha-tools:status": "ready"}
        assert len(registry.handlers_for(event_kind="run_completed")) == 2
        assert registry.handlers_for(event_kind="tool_result") == []
        assert [health.plugin_id for health in registry.health_reports()] == ["alpha-tools", "beta"]

    def test_load_failed_registration_contributes_nothing_but_reports_health(self) -> None:
        """A LOAD_FAILED record is health-visible and contributes no capabilities."""
        failed: PluginRegistrationDAO = _make_registration(
            plugin_id="broken",
            status=PluginStatus.LOAD_FAILED,
        )
        registry: PluginRegistry = PluginRegistry(registrations=[failed])

        assert registry.all_tools() == []
        assert registry.health_reports()[0].status is PluginStatus.LOAD_FAILED


class TestCollisionPolicy:
    """Colliding registrations are refused and recorded in plugin health."""

    def test_builtin_tool_name_is_never_shadowed(self) -> None:
        """A plugin tool named like a built-in is refused and recorded."""
        registry: PluginRegistry = PluginRegistry(
            registrations=[_make_registration(plugin_id="evil")],
            builtin_tool_names=frozenset({"bash", "read"}),
        )

        accepted: bool = registry.register_tool(
            tool=_NamedTool(name="bash"),
            owner="evil",
        )

        assert accepted is False
        assert registry.all_tools() == []
        health: PluginHealthDAO = registry.health_reports()[0]
        assert health.load_error is not None
        assert "bash" in health.load_error

    def test_second_plugin_tool_with_same_name_is_refused(self) -> None:
        """The first registration wins; the duplicate is refused and recorded."""
        registry: PluginRegistry = PluginRegistry(
            registrations=[
                _make_registration(plugin_id="one-tools"),
                _make_registration(plugin_id="two-tools"),
            ]
        )

        first_ok: bool = registry.register_tool(tool=_NamedTool(name="one_tools__deploy"), owner="one-tools")
        second_ok: bool = registry.register_tool(tool=_NamedTool(name="one_tools__deploy"), owner="two-tools")

        assert first_ok is True
        assert second_ok is False
        assert [tool.name for tool in registry.all_tools()] == ["one_tools__deploy"]
        loser: PluginHealthDAO = registry.health_reports()[1]
        assert loser.load_error is not None
        assert "one_tools__deploy" in loser.load_error

    def test_duplicate_command_name_is_refused(self) -> None:
        """A second command under the same token is refused and recorded."""
        registry: PluginRegistry = PluginRegistry(
            registrations=[
                _make_registration(plugin_id="one-tools"),
                _make_registration(plugin_id="two-tools"),
            ]
        )

        assert registry.register_command(name="one-tools:ship", handler=lambda: 1, owner="one-tools") is True
        assert registry.register_command(name="one-tools:ship", handler=lambda: 2, owner="two-tools") is False
        assert len(registry.all_commands()) == 1
        assert registry.health_reports()[1].load_error is not None

    def test_duplicate_renderer_is_refused(self) -> None:
        """Only one renderer per tool name; the second is refused and recorded."""
        registry: PluginRegistry = PluginRegistry(
            registrations=[
                _make_registration(plugin_id="one"),
                _make_registration(plugin_id="two"),
            ]
        )

        assert registry.register_renderer(tool_name="bash", render=str, owner="one") is True
        assert registry.register_renderer(tool_name="bash", render=repr, owner="two") is False
        assert list(registry.all_renderers()) == ["bash"]
        assert registry.health_reports()[1].load_error is not None

    def test_event_handlers_never_collide(self) -> None:
        """Many plugins may observe the same event kind."""

        def _handler(event: Any) -> None:
            """Observer.

            Args:
                event (Any): Stream event.
            """

        registry: PluginRegistry = PluginRegistry(
            registrations=[
                _make_registration(plugin_id="one", handlers={"tool_result": [_handler]}),
                _make_registration(plugin_id="two", handlers={"tool_result": [_handler]}),
            ]
        )

        assert len(registry.handlers_for(event_kind="tool_result")) == 2


class TestManifestCrossValidation:
    """M6(c): declared manifest suffixes gate merge-time registrations."""

    def test_manifest_declared_tool_suffix_is_accepted(self) -> None:
        """A derived tool name whose suffix the manifest declares merges cleanly."""
        registry: PluginRegistry = PluginRegistry(
            registrations=[_make_registration(plugin_id="acme-deploy-tools")],
            manifests={
                "acme-deploy-tools": _ManifestStub(tool_suffixes=["deploy"], command_suffixes=["ship"])
            },
        )

        accepted: bool = registry.register_tool(
            tool=_NamedTool(name="acme_deploy_tools__deploy"),
            owner="acme-deploy-tools",
        )

        assert accepted is True
        assert registry.health_reports()[0].load_error is None

    def test_manifest_undeclared_tool_suffix_is_refused_and_recorded(self) -> None:
        """A derived tool name the manifest never declares is refused (M6(c))."""
        registry: PluginRegistry = PluginRegistry(
            registrations=[_make_registration(plugin_id="acme-deploy-tools")],
            manifests={
                "acme-deploy-tools": _ManifestStub(tool_suffixes=["deploy"], command_suffixes=["ship"])
            },
        )

        accepted: bool = registry.register_tool(
            tool=_NamedTool(name="acme_deploy_tools__surprise"),
            owner="acme-deploy-tools",
        )

        assert accepted is False
        assert registry.all_tools() == []
        health: PluginHealthDAO = registry.health_reports()[0]
        assert health.load_error is not None
        assert "surprise" in health.load_error

    def test_manifest_undeclared_command_suffix_is_refused_and_recorded(self) -> None:
        """A derived command token the manifest never declares is refused (M6(c))."""
        registry: PluginRegistry = PluginRegistry(
            registrations=[_make_registration(plugin_id="acme-deploy-tools")],
            manifests={"acme-deploy-tools": _ManifestStub(tool_suffixes=[], command_suffixes=["ship"])},
        )

        accepted: bool = registry.register_command(
            name="acme-deploy-tools:destroy",
            handler=lambda: None,
            owner="acme-deploy-tools",
        )

        assert accepted is False
        assert registry.all_commands() == {}
        assert registry.health_reports()[0].load_error is not None

    def test_plugin_without_manifest_registers_without_suffix_gate(self) -> None:
        """Project/CLI plugins (no manifest) skip suffix cross-validation."""
        registry: PluginRegistry = PluginRegistry(registrations=[_make_registration(plugin_id="loose")])

        assert registry.register_tool(tool=_NamedTool(name="anything_goes"), owner="loose") is True
        assert registry.register_command(name="loose:hi", handler=lambda: None, owner="loose") is True
