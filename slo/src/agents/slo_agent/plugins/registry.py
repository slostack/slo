"""In-memory plugin registry: validated registrations, collision policy, views (75.a.3).

``PluginRegistry`` is the single in-memory authority over loaded plugin
registrations and their health. It merges tools, commands, renderers, and
statuses through explicit ``register_*`` methods that enforce the locked
collision policy — built-ins are never shadowed and duplicate derived names are
refused and recorded in the owning plugin's health — and exposes the aggregated
views the session and dispatcher consume.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from langchain_core.tools import BaseTool

from src.agents.slo_agent.plugins.dao import (
    PluginEventHandler,
    PluginHealthDAO,
    PluginRegistrationDAO,
    PluginRendererFn,
    PluginStatus,
)

__all__ = ["PluginRegistry"]

_HandlerOwnerPair = tuple[PluginRegistrationDAO, PluginEventHandler]


class PluginRegistry:
    """Own every loaded plugin's registrations and health in memory.

    WHAT: The one authority the session merges from and the dispatcher reads
        from. Collision refusals are recorded on the owning plugin's health
        record, never raised into the session.
    WHO: Built by ``SloAgentSession`` from ``PluginLoader`` results; consumed
        by ``PluginDispatcher``, the tool-merge seam, the slash surface, and
        ``/plugins``.
    WHEN: Once per session load, and rebuilt on ``/plugins reload``.
    """

    def __init__(
        self,
        *,
        registrations: list[PluginRegistrationDAO],
        builtin_tool_names: frozenset[str] | None = None,
        manifests: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Index the loaded registrations and their optional manifests.

        Args:
            registrations (list[PluginRegistrationDAO]): Loader output in
                stable discovery order, including ``LOAD_FAILED`` records.
            builtin_tool_names (frozenset[str] | None): Names of the built-in
                bundle, which plugin tools may never shadow.
            manifests (Optional[Mapping[str, Any]]): Managed-plugin manifests
                keyed by plugin id; anything with ``tool_suffixes`` and
                ``command_suffixes`` list attributes satisfies the structural
                contract (``PluginManifestDAO`` at runtime).
        """
        self._registrations: list[PluginRegistrationDAO] = list(registrations)
        self._by_id: dict[str, PluginRegistrationDAO] = {
            registration.plugin_id: registration for registration in self._registrations
        }
        self._builtin_tool_names: frozenset[str] = builtin_tool_names or frozenset()
        self._manifests: Mapping[str, Any] = manifests or {}
        self._accepted_tools: list[BaseTool] = []
        self._accepted_tool_names: set[str] = set()
        self._accepted_commands: dict[str, Callable[..., Any]] = {}
        self._accepted_renderers: dict[str, PluginRendererFn] = {}

    def merge_all(self) -> None:
        """Fold every loaded registration's contributions through the policy.

        WHAT: Applies each plugin's declared tools, commands, and renderers
            through the collision-gated ``register_*`` methods in load order,
            so the first (or built-in) registration always wins and every
            refusal lands on the owning plugin's health record.
        WHO: Called by the session once after construction, before the merged
            views are consumed.
        WHEN: After the registry is built and before tools merge into the
            agent bundle.
        """
        for registration in self._loaded():
            for tool in registration.tools:
                self.register_tool(tool=tool, owner=registration.plugin_id)
            for name, handler in registration.commands.items():
                self.register_command(name=name, handler=handler, owner=registration.plugin_id)
            for tool_name, render in registration.renderers.items():
                self.register_renderer(tool_name=tool_name, render=render, owner=registration.plugin_id)

    # ---- Aggregated views --------------------------------------------------

    def all_tools(self) -> list[BaseTool]:
        """Return every accepted plugin tool in merge order.

        Returns:
            list[BaseTool]: Tools that survived the collision policy.
        """
        return list(self._accepted_tools)

    def all_commands(self) -> dict[str, Callable[..., Any]]:
        """Return every accepted plugin slash command.

        Returns:
            dict[str, Callable[..., Any]]: Command token → handler.
        """
        return dict(self._accepted_commands)

    def remove_command(self, *, name: str) -> None:
        """Remove one command rejected by the built-in slash registry.

        Args:
            name (str): Plugin command token that must no longer route at runtime.
        """
        self._accepted_commands.pop(name, None)

    def all_renderers(self) -> dict[str, PluginRendererFn]:
        """Return every accepted renderer override keyed by tool name.

        Returns:
            dict[str, PluginRendererFn]: Tool name → renderer.
        """
        return dict(self._accepted_renderers)

    def all_statuses(self) -> dict[str, str]:
        """Return the seed footer statuses from every loaded plugin.

        Returns:
            dict[str, str]: Status key → latest registered text.
        """
        statuses: dict[str, str] = {}
        for registration in self._loaded():
            statuses.update(registration.statuses)
        return statuses

    def handlers_for(self, *, event_kind: str) -> list[_HandlerOwnerPair]:
        """Return every ``(registration, handler)`` pair for one event kind.

        Args:
            event_kind (str): A ``StreamEventKind`` value.

        Returns:
            list[_HandlerOwnerPair]: Subscribed handlers in load order.
        """
        pairs: list[_HandlerOwnerPair] = []
        for registration in self._loaded():
            for handler in registration.event_handlers.get(event_kind, []):
                pairs.append((registration, handler))
        return pairs

    def registration_for(self, *, plugin_id: str) -> Optional[PluginRegistrationDAO]:
        """Return the registration owning one plugin id.

        Args:
            plugin_id (str): Canonical plugin identity.

        Returns:
            Optional[PluginRegistrationDAO]: Registration for the id, if present.
        """
        return self._by_id.get(plugin_id)

    def health_reports(self) -> list[PluginHealthDAO]:
        """Return every plugin's health record in load order.

        Returns:
            list[PluginHealthDAO]: Health for loaded and failed plugins alike.
        """
        return [registration.health for registration in self._registrations]

    def registrations(self) -> list[PluginRegistrationDAO]:
        """Return the live registration objects in load order.

        Returns:
            list[PluginRegistrationDAO]: The same mutable objects the loader
                produced, so health mutations stay visible through
                ``health_reports``.
        """
        return list(self._registrations)

    # ---- Merge-time registration with collision policy ---------------------

    def register_tool(self, *, tool: BaseTool, owner: str) -> bool:
        """Merge one plugin tool, refusing built-in and duplicate names.

        Args:
            tool (BaseTool): The tool a plugin contributed.
            owner (str): The contributing plugin's id.

        Returns:
            bool: True when the tool was accepted; False when refused (the
                refusal is recorded on the owner's health record).
        """
        name: str = tool.name or ""
        if name in self._builtin_tool_names or name in self._accepted_tool_names:
            return self._refuse(owner=owner, reason=f"tool name collision refused: {name}")
        if not self._suffix_allowed(owner=owner, kind="tool", derived_name=name, separator="__"):
            return False
        self._accepted_tools.append(tool)
        self._accepted_tool_names.add(name)
        return True

    def register_command(self, *, name: str, handler: Callable[..., Any], owner: str) -> bool:
        """Merge one plugin slash command, refusing duplicate tokens.

        Args:
            name (str): Canonical command token (without the leading slash).
            handler (Callable[..., Any]): The command handler.
            owner (str): The contributing plugin's id.

        Returns:
            bool: True when accepted; False when refused and recorded.
        """
        if name in self._accepted_commands:
            return self._refuse(owner=owner, reason=f"command name collision refused: {name}")
        if not self._suffix_allowed(owner=owner, kind="command", derived_name=name, separator=":"):
            return False
        self._accepted_commands[name] = handler
        return True

    def register_renderer(self, *, tool_name: str, render: PluginRendererFn, owner: str) -> bool:
        """Merge one renderer override, refusing duplicates per tool name.

        Args:
            tool_name (str): The tool whose output this renderer renders.
            render (PluginRendererFn): Output-string → summary renderer.
            owner (str): The contributing plugin's id.

        Returns:
            bool: True when accepted; False when refused and recorded.
        """
        if tool_name in self._accepted_renderers:
            return self._refuse(owner=owner, reason=f"renderer collision refused: {tool_name}")
        self._accepted_renderers[tool_name] = render
        return True

    # ---- Internals -----------------------------------------------------------

    def _loaded(self) -> list[PluginRegistrationDAO]:
        """Return registrations that loaded successfully.

        Returns:
            list[PluginRegistrationDAO]: ``LOADED`` registrations in order.
        """
        return [
            registration
            for registration in self._registrations
            if registration.health.status is PluginStatus.LOADED
        ]

    def _suffix_allowed(self, *, owner: str, kind: str, derived_name: str, separator: str) -> bool:
        """Cross-validate one derived name against the owner's manifest (M6(c)).

        A registration whose derived suffix is undeclared in the owning managed
        plugin's manifest is refused and recorded in plugin health. Plugins
        without a manifest (project/CLI tiers) skip the gate.

        Args:
            owner (str): The contributing plugin's id.
            kind (str): ``"tool"`` or ``"command"`` — selects the suffix list.
            derived_name (str): The full derived public name being registered.
            separator (str): Separator between namespace and suffix
                (``"__"`` for tools, ``":"`` for commands).

        Returns:
            bool: True when the registration may proceed.
        """
        manifest: Any = self._manifests.get(owner)
        if manifest is None:
            return True
        suffix: str = derived_name.rsplit(separator, maxsplit=1)[-1]
        declared: list[str] = (
            list(manifest.tool_suffixes) if kind == "tool" else list(manifest.command_suffixes)
        )
        if suffix in declared:
            return True
        return self._refuse(
            owner=owner,
            reason=f"{kind} suffix undeclared in manifest refused: {suffix}",
        )

    def _refuse(self, *, owner: str, reason: str) -> bool:
        """Record one refusal on the owning plugin's health record.

        Args:
            owner (str): The refused plugin's id.
            reason (str): Operator-visible refusal reason.

        Returns:
            bool: Always False — the refusal helper is the refusal return.
        """
        registration: Optional[PluginRegistrationDAO] = self._by_id.get(owner)
        if registration is not None:
            health: PluginHealthDAO = registration.health
            health.load_error = reason if health.load_error is None else f"{health.load_error}; {reason}"
        return False
