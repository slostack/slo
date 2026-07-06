"""Pure slash-command suggestion logic for the Slo TUI."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.tui.model_catalog import ModelSuggestionEntryDAO, model_suggestion_entries
from src.tui.slash_command_registry import SlashCommandRegistry, SlashCommandSpecDAO

__all__ = [
    "SlashSuggestionEngine",
    "SlashSuggestionRowDAO",
    "SlashSuggestionStateDAO",
]


class SlashSuggestionRowDAO(BaseModel):
    """One row in the live slash suggestion menu."""

    model_config = ConfigDict(extra="forbid")

    insert_text: str
    label: str
    detail: Optional[str] = None


class SlashSuggestionStateDAO(BaseModel):
    """Engine output for the current prompt buffer."""

    model_config = ConfigDict(extra="forbid")

    visible: bool = False
    replacement_start: int = 0
    replacement_end: int = 0
    ghost_suffix: str = ""
    rows: list[SlashSuggestionRowDAO] = Field(default_factory=list)
    highlighted_index: int = 0

    @property
    def highlighted_row(self) -> Optional[SlashSuggestionRowDAO]:
        """Return the highlighted suggestion row when present.

        Returns:
            Optional[SlashSuggestionRowDAO]: Highlighted row, or ``None``.
        """
        if not self.rows:
            return None
        return self.rows[self.highlighted_index]

    def with_highlight_delta(self, *, delta: int) -> "SlashSuggestionStateDAO":
        """Return a copy with the highlight moved by ``delta``.

        Args:
            delta (int): Positive or negative row movement.

        Returns:
            SlashSuggestionStateDAO: Copied state with updated highlight.
        """
        if not self.rows:
            return self
        next_index: int = (self.highlighted_index + delta) % len(self.rows)
        return self.model_copy(update={"highlighted_index": next_index})


class SlashSuggestionEngine:
    """Pure registry-backed slash suggestion engine."""

    def __init__(self, *, registry: SlashCommandRegistry) -> None:
        """Store the registry backing slash suggestions.

        Args:
            registry (SlashCommandRegistry): Canonical command registry.
        """
        self._registry: SlashCommandRegistry = registry

    def evaluate(
        self,
        *,
        buffer_text: str,
        active_model_name: str,
    ) -> SlashSuggestionStateDAO:
        """Return the suggestion state for the current buffer.

        Args:
            buffer_text (str): Current prompt buffer.
            active_model_name (str): Current session model.

        Returns:
            SlashSuggestionStateDAO: Suggestion state.
        """
        stripped: str = buffer_text.lstrip()
        if not stripped.startswith("/"):
            return SlashSuggestionStateDAO(visible=False)

        command_token, has_space, remainder = self._parse_command(buffer_text=stripped)
        command_query: str = command_token[1:]
        if self._is_model_argument_query(
            command_query=command_query,
            has_space=has_space,
        ):
            return self._model_argument_state(
                query=remainder,
                active_model_name=active_model_name,
            )
        return self._command_state(command_query=command_query)

    @staticmethod
    def _parse_command(*, buffer_text: str) -> tuple[str, bool, str]:
        """Split ``/cmd rest`` into token, separator flag, and remainder.

        Args:
            buffer_text (str): Left-stripped prompt buffer.

        Returns:
            tuple[str, bool, str]: Parsed token, spacing flag, and remainder.
        """
        command_token: str
        separator: str
        remainder: str
        command_token, separator, remainder = buffer_text.partition(" ")
        return command_token, bool(separator), remainder

    @staticmethod
    def _is_model_argument_query(*, command_query: str, has_space: bool) -> bool:
        """Return True when the prompt is in ``/model`` argument mode.

        Args:
            command_query (str): Slash command token without leading slash.
            has_space (bool): True when arguments have started.

        Returns:
            bool: True when the engine should show model suggestions.
        """
        return has_space and command_query == "model"

    def _command_state(self, *, command_query: str) -> SlashSuggestionStateDAO:
        """Return slash-command token suggestions.

        Args:
            command_query (str): Partial command token without leading slash.

        Returns:
            SlashSuggestionStateDAO: Command suggestion state.
        """
        matches: list[SlashCommandSpecDAO] = self._matching_commands(command_query=command_query)
        rows: list[SlashSuggestionRowDAO] = [self._command_row(command=command) for command in matches]
        return SlashSuggestionStateDAO(
            visible=bool(rows),
            replacement_start=0,
            replacement_end=len(command_query) + 1,
            ghost_suffix=self._command_ghost_suffix(
                command_query=command_query,
                rows=rows,
            ),
            rows=rows,
            highlighted_index=0,
        )

    def _matching_commands(self, *, command_query: str) -> list[SlashCommandSpecDAO]:
        """Return registry commands whose names start with the query.

        Args:
            command_query (str): Partial command token.

        Returns:
            list[SlashCommandSpecDAO]: Matching commands.
        """
        return [
            command for command in self._registry.ordered_commands() if command.name.startswith(command_query)
        ]

    @staticmethod
    def _command_row(*, command: SlashCommandSpecDAO) -> SlashSuggestionRowDAO:
        """Build one command suggestion row.

        Args:
            command (SlashCommandSpecDAO): Registry command metadata.

        Returns:
            SlashSuggestionRowDAO: Render-ready suggestion row.
        """
        return SlashSuggestionRowDAO(
            insert_text=SlashSuggestionEngine._command_insert_text(command=command),
            label=f"/{command.name}",
            detail=command.description,
        )

    @staticmethod
    def _command_insert_text(*, command: SlashCommandSpecDAO) -> str:
        """Return the inserted text for one command row.

        Args:
            command (SlashCommandSpecDAO): Registry command metadata.

        Returns:
            str: Text inserted into the prompt on acceptance.
        """
        if command.argument_mode == "none":
            return f"/{command.name}"
        return f"/{command.name} "

    @staticmethod
    def _command_ghost_suffix(
        *,
        command_query: str,
        rows: list[SlashSuggestionRowDAO],
    ) -> str:
        """Return the ghost-completion suffix for command suggestions.

        Args:
            command_query (str): Partial command token.
            rows (list[SlashSuggestionRowDAO]): Matching suggestion rows.

        Returns:
            str: Ghost suffix, or ``""`` when unavailable.
        """
        if not rows or not command_query:
            return ""
        best_label: str = rows[0].label
        prefix: str = f"/{command_query}"
        if not best_label.startswith(prefix):
            return ""
        return best_label[len(prefix) :]

    def _model_argument_state(
        self,
        *,
        query: str,
        active_model_name: str,
    ) -> SlashSuggestionStateDAO:
        """Return ``/model`` argument suggestions.

        Args:
            query (str): Partial model-name argument.
            active_model_name (str): Current session model.

        Returns:
            SlashSuggestionStateDAO: Model-argument suggestion state.
        """
        rows: list[SlashSuggestionRowDAO] = [
            SlashSuggestionRowDAO(
                insert_text=entry.model_name,
                label=entry.model_name,
                detail=self._model_detail(entry=entry),
            )
            for entry in model_suggestion_entries(active_model_name=active_model_name)
            if entry.model_name.startswith(query)
        ]
        return SlashSuggestionStateDAO(
            visible=bool(rows),
            replacement_start=len("/model "),
            replacement_end=len("/model ") + len(query),
            ghost_suffix=self._model_ghost_suffix(query=query, rows=rows),
            rows=rows,
            highlighted_index=0,
        )

    @staticmethod
    def _model_detail(*, entry: ModelSuggestionEntryDAO) -> str:
        """Render one model suggestion detail string.

        Args:
            entry: Model suggestion entry from ``model_catalog``.

        Returns:
            str: Human-readable detail string.
        """
        availability: str = "requires /auth" if entry.requires_auth else "ready"
        activity: str = "active" if entry.is_active else "available"
        return (
            f"{entry.provider.value} · {activity} · {availability} · " f"reasoning {entry.reasoning_summary}"
        )

    @staticmethod
    def _model_ghost_suffix(*, query: str, rows: list[SlashSuggestionRowDAO]) -> str:
        """Return the ghost-completion suffix for model suggestions.

        Args:
            query (str): Partial model-name query.
            rows (list[SlashSuggestionRowDAO]): Matching model rows.

        Returns:
            str: Ghost suffix, or ``""`` when unavailable.
        """
        if not rows or not query:
            return ""
        best_label: str = rows[0].label
        if not best_label.startswith(query):
            return ""
        return best_label[len(query) :]
