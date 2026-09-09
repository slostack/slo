"""Canonical slash-command metadata for the Slo TUI."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "SlashArgumentMode",
    "SlashCommandRegistry",
    "SlashCommandSpecDAO",
    "build_default_registry",
]


SlashArgumentMode = Literal["none", "free_text", "enumerated"]
"""Argument-behavior vocabulary for one slash command."""


class SlashCommandSpecDAO(BaseModel):
    """Presentation metadata for one slash command.

    Attributes:
        name (str): Canonical slash token without the leading slash.
        description (str): Human-readable one-line description.
        aliases (list[str]): Alternate tokens routed to ``name``.
        argument_mode (SlashArgumentMode): Whether the command accepts
            no args, free text, or enumerated suggestions.
        usage (Optional[str]): Explicit usage string when the command
            accepts arguments.
        argument_hint (Optional[str]): Short hint shown by the future
            suggestion engine before arguments are chosen.
        display_order (int): Stable ordering for ``/help`` and menus.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    aliases: list[str] = Field(default_factory=list)
    argument_mode: SlashArgumentMode = "none"
    usage: Optional[str] = None
    argument_hint: Optional[str] = None
    display_order: int = 0


class SlashCommandRegistry:
    """Indexed registry of slash-command metadata.

    The registry owns canonical naming, alias resolution, and ordered
    iteration. It deliberately does not own side-effect handlers.
    """

    def __init__(self, *, commands: list[SlashCommandSpecDAO]) -> None:
        """Index the provided command specs.

        Args:
            commands (list[SlashCommandSpecDAO]): Canonical command specs.

        Raises:
            ValueError: When canonical names or aliases collide.
        """
        self._commands_by_name: dict[str, SlashCommandSpecDAO] = {}
        self._canonical_by_token: dict[str, str] = {}
        for command in commands:
            self._register(command=command)

    def register(self, *, command: SlashCommandSpecDAO) -> None:
        """Register one extension command through the canonical collision owner.

        Args:
            command (SlashCommandSpecDAO): Built-in or plugin command metadata.

        Raises:
            ValueError: When a built-in, plugin, or alias token is already bound.
        """
        self._register(command=command)

    def _register(self, *, command: SlashCommandSpecDAO) -> None:
        """Add one command and its aliases to the registry.

        Args:
            command (SlashCommandSpecDAO): Command to register.

        Raises:
            ValueError: When the command name or any alias is duplicated.
        """
        self._ensure_command_name_is_unique(command=command)
        self._commands_by_name[command.name] = command
        self._bind_command_tokens(command=command)

    def _ensure_command_name_is_unique(self, *, command: SlashCommandSpecDAO) -> None:
        """Reject duplicate canonical command names.

        Args:
            command (SlashCommandSpecDAO): Command being added.

        Raises:
            ValueError: When the canonical command name is already present.
        """
        if command.name in self._commands_by_name:
            raise ValueError(f"Duplicate slash command: {command.name}")

    def _bind_command_tokens(self, *, command: SlashCommandSpecDAO) -> None:
        """Bind the command name and aliases to the canonical name.

        Args:
            command (SlashCommandSpecDAO): Command whose tokens are bound.
        """
        self._bind_token(token=command.name, canonical_name=command.name)
        for alias in command.aliases:
            self._bind_token(token=alias, canonical_name=command.name)

    def _bind_token(self, *, token: str, canonical_name: str) -> None:
        """Bind one raw token to its canonical command name.

        Args:
            token (str): Raw token typed by the user.
            canonical_name (str): Canonical command name.

        Raises:
            ValueError: When the token is already bound.
        """
        if token in self._canonical_by_token:
            raise ValueError(f"Duplicate slash token: {token}")
        self._canonical_by_token[token] = canonical_name

    def resolve(self, *, token: str) -> Optional[SlashCommandSpecDAO]:
        """Resolve one raw token to a command spec.

        Args:
            token (str): Raw token without the leading slash.

        Returns:
            Optional[SlashCommandSpecDAO]: Matching command, or ``None``.
        """
        canonical_name: Optional[str] = self._canonical_by_token.get(token)
        if canonical_name is None:
            return None
        return self._commands_by_name[canonical_name]

    def ordered_commands(self) -> list[SlashCommandSpecDAO]:
        """Return commands in stable display order.

        Returns:
            list[SlashCommandSpecDAO]: Ordered canonical commands.
        """
        return sorted(
            self._commands_by_name.values(),
            key=lambda command: (command.display_order, command.name),
        )


_DEFAULT_COMMANDS: list[SlashCommandSpecDAO] = [
    SlashCommandSpecDAO(
        name="help",
        description="this message",
        aliases=["h", "?"],
        display_order=10,
    ),
    SlashCommandSpecDAO(
        name="clear",
        description="clear the transcript",
        display_order=20,
    ),
    SlashCommandSpecDAO(
        name="exit",
        description="quit the TUI",
        aliases=["quit", "q"],
        display_order=30,
    ),
    SlashCommandSpecDAO(
        name="cwd",
        description="show the workdir",
        display_order=40,
    ),
    SlashCommandSpecDAO(
        name="abort",
        description="abort the in-flight prompt",
        display_order=50,
    ),
    SlashCommandSpecDAO(
        name="steer",
        description="queue a steering message",
        argument_mode="free_text",
        usage="/steer <message>",
        argument_hint="message",
        display_order=60,
    ),
    SlashCommandSpecDAO(
        name="auth",
        description="sign in / change provider",
        display_order=70,
    ),
    SlashCommandSpecDAO(
        name="workflows",
        description="list detached workflows; abort <id>; dismiss <id>; resume <id>",
        aliases=["wf"],
        argument_mode="enumerated",
        usage="/workflows [abort <workflow-id> | dismiss <workflow-id> | resume <workflow-id>]",
        argument_hint="abort <id> | dismiss <id> | resume <id>",
        display_order=75,
    ),
    SlashCommandSpecDAO(
        name="model",
        description="list or switch supported models",
        argument_mode="enumerated",
        usage="/model [name]",
        argument_hint="model name",
        display_order=80,
    ),
    SlashCommandSpecDAO(
        name="reasoning",
        description="list or switch reasoning level",
        argument_mode="enumerated",
        usage="/reasoning [level]",
        argument_hint="off|minimal|low|medium|high|xhigh|max",
        display_order=90,
    ),
    SlashCommandSpecDAO(
        name="theme",
        description="toggle between slo-default and slo-dark themes",
        display_order=92,
    ),
    SlashCommandSpecDAO(
        name="tree",
        description="show session history as a tree",
        argument_mode="enumerated",
        usage="/tree [textual|markdown|html]",
        argument_hint="format",
        display_order=93,
    ),
    SlashCommandSpecDAO(
        name="context-window",
        description="show context-window capacity and usage",
        argument_mode="none",
        display_order=94,
    ),
    SlashCommandSpecDAO(
        name="new",
        description="start a brand-new session",
        argument_mode="free_text",
        usage="/new [session name]",
        argument_hint="optional session name",
        display_order=95,
    ),
    SlashCommandSpecDAO(
        name="compact",
        description="compact session history now",
        argument_mode="none",
        display_order=96,
    ),
    SlashCommandSpecDAO(
        name="diff",
        description="show git diff for a file",
        argument_mode="free_text",
        usage="/diff <repository-relative-path>",
        argument_hint="repository-relative path",
        display_order=97,
    ),
    SlashCommandSpecDAO(
        name="rename",
        description="rename the current session",
        argument_mode="free_text",
        usage="/rename <session name>",
        argument_hint="session name",
        display_order=100,
    ),
    SlashCommandSpecDAO(
        name="plugins",
        description="list plugins; trust or reload plugin registrations",
        argument_mode="enumerated",
        display_order=98,
    ),
    SlashCommandSpecDAO(
        name="preferences",
        description="show or clear saved model/reasoning preferences",
        argument_mode="enumerated",
        usage="/preferences  |  /preferences clear",
        argument_hint="clear",
        display_order=105,
    ),
]


def build_default_registry() -> SlashCommandRegistry:
    """Build Slo's default slash-command registry.

    Returns:
        SlashCommandRegistry: Canonical registry for the shipped command set.
    """
    return SlashCommandRegistry(commands=list(_DEFAULT_COMMANDS))
