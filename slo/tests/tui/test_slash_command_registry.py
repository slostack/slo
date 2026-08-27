"""Tests for the slash-command registry."""

from __future__ import annotations

import pytest

from src.tui.slash_command_registry import (
    SlashCommandRegistry,
    SlashCommandSpecDAO,
    build_default_registry,
)


class TestSlashCommandRegistry:
    """Canonical-name, alias, and ordering guarantees."""

    def test_default_registry_resolves_help_aliases_to_help(self) -> None:
        """Alias tokens resolve to the canonical help command."""
        registry: SlashCommandRegistry = build_default_registry()

        help_command = registry.resolve(token="help")
        help_alias = registry.resolve(token="h")
        help_symbol = registry.resolve(token="?")

        assert help_command is not None
        assert help_alias is not None
        assert help_symbol is not None
        assert help_command.name == "help"
        assert help_alias.name == "help"
        assert help_symbol.name == "help"

    def test_default_registry_orders_commands_by_display_order(self) -> None:
        """Ordered iteration follows the configured display order."""
        registry: SlashCommandRegistry = build_default_registry()

        ordered_names: list[str] = [command.name for command in registry.ordered_commands()]

        assert ordered_names == [
            "help",
            "clear",
            "exit",
            "cwd",
            "abort",
            "steer",
            "auth",
            "workflows",
            "model",
            "reasoning",
            "theme",
            "tree",
            "context-window",
            "new",
            "compact",
            "diff",
            "rename",
            "preferences",
        ]

    def test_default_registry_registers_diff_at_97_without_shifting_neighbors(self) -> None:
        """The /diff command occupies the reserved order slot between compact and rename."""
        registry: SlashCommandRegistry = build_default_registry()

        diff_command = registry.resolve(token="diff")
        compact_command = registry.resolve(token="compact")
        rename_command = registry.resolve(token="rename")

        assert diff_command is not None
        assert diff_command.display_order == 97
        assert diff_command.argument_mode == "free_text"
        assert compact_command is not None and compact_command.display_order == 96
        assert rename_command is not None and rename_command.display_order == 100

    def test_duplicate_canonical_names_raise_value_error(self) -> None:
        """Two canonical command names may not collide."""
        with pytest.raises(ValueError, match="Duplicate slash command: help"):
            SlashCommandRegistry(
                commands=[
                    SlashCommandSpecDAO(name="help", description="one"),
                    SlashCommandSpecDAO(name="help", description="two"),
                ]
            )

    def test_duplicate_alias_tokens_raise_value_error(self) -> None:
        """Two commands may not bind the same alias token."""
        with pytest.raises(ValueError, match="Duplicate slash token: h"):
            SlashCommandRegistry(
                commands=[
                    SlashCommandSpecDAO(name="help", description="one", aliases=["h"]),
                    SlashCommandSpecDAO(name="history", description="two", aliases=["h"]),
                ]
            )
