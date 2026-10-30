"""Pure slash-command suggestion logic for the Slo TUI."""

from __future__ import annotations

from typing import Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from src.auth.credential_dao import ProviderName
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

    kind: Literal["slash", "path"] = Field(
        default="slash", description="Completion source and acceptance policy."
    )
    visible: bool = False
    replacement_start: int = 0
    replacement_end: int = 0
    ghost_suffix: str = ""
    rows: list[SlashSuggestionRowDAO] = Field(default_factory=list)
    highlighted_index: int = 0
    total_matches: int = Field(default=0, ge=0)

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
        self._recent_models: list[str] = []

    def owns_arguments(self, *, buffer_text: str) -> bool:
        """Reserve enumerated command arguments before filesystem detection.

        Args:
            buffer_text: Full prompt, including any leading whitespace.

        Returns:
            Whether a registered command owns argument completion, even with no matches.
        """
        token, separator, _ = buffer_text.lstrip().partition(" ")
        command = self._registry.resolve(token=token.removeprefix("/"))
        return bool(token.startswith("/") and separator and command and command.argument_mode == "enumerated")

    def record_selection(self, *, model_name: str) -> None:
        """Remember at most five successful session-local selections without persistence."""
        self._recent_models = [model_name] + [name for name in self._recent_models if name != model_name][:4]

    def evaluate(
        self,
        *,
        buffer_text: str,
        active_model_name: str,
    ) -> SlashSuggestionStateDAO:
        """Return command-token or model-argument suggestions for the current buffer.

        Once arguments begin, command rows must not intercept Tab: arguments
        without enumerated rows leave discovery to the path-completion owner.

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
            state = self._model_argument_state(
                query=remainder,
                active_model_name=active_model_name,
            )
            offset = len(buffer_text) - len(stripped)
            return state.model_copy(
                update={
                    "replacement_start": state.replacement_start + offset,
                    "replacement_end": state.replacement_end + offset,
                }
            )
        if has_space:
            return SlashSuggestionStateDAO(visible=False)
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
        entries: list[ModelSuggestionEntryDAO] = model_suggestion_entries(active_model_name=active_model_name)
        ordered_entries: Sequence[ModelSuggestionEntryDAO] = self._ordered_model_entries(
            query=query,
            entries=entries,
        )
        rows, total_matches = self._bounded_model_rows(query=query, entries=ordered_entries)
        return self._bounded_model_state(query=query, rows=rows, total_matches=total_matches)

    def _ordered_model_entries(
        self,
        *,
        query: str,
        entries: Sequence[ModelSuggestionEntryDAO],
    ) -> Sequence[ModelSuggestionEntryDAO]:
        """Choose query or empty-query ordering for cached picker rows.

        WHAT: Delegates the mutually exclusive ordering policy without reading
            credentials, stores, or network state.
        WHO: ``_model_argument_state`` calls this after obtaining the cached projection.
        WHEN: Runs on every ``/model`` argument edit before candidate capping.

        Args:
            query (str): Operator-entered model query.
            entries (Sequence[ModelSuggestionEntryDAO]): Cached presentation rows.

        Returns:
            Sequence[ModelSuggestionEntryDAO]: Rows in the applicable local order.
        """
        if query.strip():
            return entries
        return self._empty_query_entries(entries=entries)

    def _empty_query_entries(
        self, *, entries: Sequence[ModelSuggestionEntryDAO]
    ) -> list[ModelSuggestionEntryDAO]:
        """Order empty-query rows by active, recent, first-class, then canonical identity.

        WHAT: Produces a deterministic local empty-query ordering with deduplicated
            session-local recent selections.
        WHO: ``_ordered_model_entries`` delegates here only for blank model queries.
        WHEN: Runs before matching/capping and never persists recency or performs I/O.

        Args:
            entries (Sequence[ModelSuggestionEntryDAO]): Cached presentation rows.

        Returns:
            list[ModelSuggestionEntryDAO]: Locally sorted empty-query rows.
        """
        recent_positions: dict[str, int] = self._recent_model_positions()
        return sorted(
            entries,
            key=lambda entry: self._empty_query_rank(entry=entry, recent_positions=recent_positions),
        )

    def _recent_model_positions(self) -> dict[str, int]:
        """Map each retained recent model to its first session-local selection position.

        WHAT: Converts the bounded recency list into stable lookup positions.
        WHO: ``_empty_query_entries`` uses it for deterministic empty-query ranking.
        WHEN: Runs only for blank ``/model`` queries; the list is in-memory only.

        Returns:
            dict[str, int]: First selection position for each recent canonical model.
        """
        return {model_name: index for index, model_name in enumerate(self._recent_models)}

    @staticmethod
    def _empty_query_rank(
        *, entry: ModelSuggestionEntryDAO, recent_positions: dict[str, int]
    ) -> tuple[int, int, str]:
        """Rank one blank-query row without nesting picker policy in the orchestrator.

        WHAT: Applies active-route, recent-selection, first-class, and lexical order.
        WHO: ``_empty_query_entries`` supplies this as its local sort key.
        WHEN: Runs only for cached blank-query rows before the 25-row cap.

        Args:
            entry (ModelSuggestionEntryDAO): Cached canonical presentation row.
            recent_positions (dict[str, int]): Stable positions for recent selections.

        Returns:
            tuple[int, int, str]: Deterministic empty-query priority and tie-breakers.
        """
        if entry.is_active:
            return (0, 0, entry.model_name)
        recent_position: Optional[int] = recent_positions.get(entry.model_name)
        if recent_position is not None:
            return (1, recent_position, entry.model_name)
        if not entry.support_tier_label:
            return (2, 0, entry.model_name)
        return (3, 0, entry.model_name)

    @staticmethod
    def _bounded_model_state(
        *, query: str, rows: list[SlashSuggestionRowDAO], total_matches: int
    ) -> SlashSuggestionStateDAO:
        """Build bounded state for one model argument replacement span.

        WHAT: Encodes the capped rows, total match count, replacement offsets, and
            literal ghost suffix into the state consumed by the menu.
        WHO: ``_model_argument_state`` calls it after local matching and capping.
        WHEN: Runs once per ``/model`` argument evaluation with no catalog I/O.

        Args:
            query (str): Original model argument text.
            rows (list[SlashSuggestionRowDAO]): Bounded render candidates.
            total_matches (int): Unbounded matching row count.

        Returns:
            SlashSuggestionStateDAO: Complete local menu state for the argument.
        """
        return SlashSuggestionStateDAO(
            visible=True,
            replacement_start=len("/model "),
            replacement_end=len("/model ") + len(query),
            ghost_suffix=SlashSuggestionEngine._model_ghost_suffix(query=query, rows=rows),
            rows=rows,
            highlighted_index=0,
            total_matches=total_matches,
        )

    @classmethod
    def _bounded_model_rows(
        cls,
        *,
        query: str,
        entries: Sequence[ModelSuggestionEntryDAO],
    ) -> tuple[list[SlashSuggestionRowDAO], int]:
        """Match cached picker rows locally and cap candidates before painting.

        WHAT: Case-folds canonical IDs and display labels, ranks every match
            deterministically, and materializes only the first 25 rows.
        WHO: ``_model_argument_state`` calls this from the TUI keystroke path.
        WHEN: On every ``/model`` argument edit after the catalog projection is
            already captured; it performs no credential, store, or network I/O.

        Args:
            query (str): Operator-entered model query.
            entries (Sequence[ModelSuggestionEntryDAO]): Cached presentation rows.

        Returns:
            tuple[list[SlashSuggestionRowDAO], int]: Render candidates and the
            unbounded number of matching catalog rows.
        """
        matches = cls._matching_model_entries(query=query, entries=entries)
        rows = [cls._model_row(entry=entry) for entry in matches[:25]]
        return rows, len(matches)

    @classmethod
    def _matching_model_entries(
        cls, *, query: str, entries: Sequence[ModelSuggestionEntryDAO]
    ) -> list[ModelSuggestionEntryDAO]:
        """Match and order cached entries before the bounded-row builder caps them.

        Called by ``_bounded_model_rows`` on each edit; performs no I/O.

        Args:
            query: Original operator search text.
            entries: Already ordered cached presentation rows.

        Returns:
            Matching rows, preserving empty-query priority.
        """
        normalized_query: str = query.strip().casefold()
        matches: list[ModelSuggestionEntryDAO] = [
            entry
            for entry in entries
            if normalized_query in entry.model_name.casefold()
            or normalized_query in entry.display_name.casefold()
        ]
        if normalized_query:
            matches.sort(key=lambda entry: cls._model_rank(entry=entry, query=normalized_query))
        return matches

    @classmethod
    def _model_row(cls, *, entry: ModelSuggestionEntryDAO) -> SlashSuggestionRowDAO:
        """Project one capped match for the menu during bounded-row construction.

        Args:
            entry: Cached presentation row with exact canonical identity.

        Returns:
            Literal menu row retaining the canonical insertion identity.
        """
        return SlashSuggestionRowDAO(
            insert_text=entry.model_name,
            label=entry.model_name,
            detail=cls._model_detail(entry=entry),
        )

    @staticmethod
    def _model_rank(*, entry: ModelSuggestionEntryDAO, query: str) -> tuple[int, str]:
        """Rank one picker row by exactness before canonical lexical order.

        Args:
            entry (ModelSuggestionEntryDAO): Cached canonical presentation row.
            query (str): Case-folded search text.

        Returns:
            tuple[int, str]: Deterministic rank and canonical tie-breaker.
        """
        model_name: str = entry.model_name.casefold()
        display_name: str = entry.display_name.casefold()
        if model_name == query:
            return (0, entry.model_name)
        if model_name.startswith(query):
            return (1, entry.model_name)
        if display_name.startswith(query):
            return (2, entry.model_name)
        return (3, entry.model_name)

    @staticmethod
    def _model_detail(*, entry: ModelSuggestionEntryDAO) -> str:
        """Render one compact, truthful model suggestion detail string.

        Args:
            entry (ModelSuggestionEntryDAO): Model suggestion entry from the
                generation-backed catalog read view.

        Returns:
            str: Human-readable detail string.
        """
        availability: str = entry.status_summary or (
            "requires /auth" if entry.requires_auth else "key configured; not checked"
        )
        context: str = f"context {entry.context_window}" if entry.context_window else "context unavailable"
        reasoning: str = SlashSuggestionEngine._reasoning_detail(entry=entry)
        return f"{availability} · {context} · {entry.provider.value} · reasoning {reasoning}"

    @staticmethod
    def _reasoning_detail(*, entry: ModelSuggestionEntryDAO) -> str:
        """Render only reasoning controls established by canonical capability evidence.

        Args:
            entry (ModelSuggestionEntryDAO): Catalog-backed picker presentation row.

        Returns:
            str: A compact statement distinguishing disable control from provider default.
        """
        # Gateway disable evidence is not part of direct-provider profiles.
        # Preserve their established compact summaries and two-line menu rows.
        if entry.provider is not ProviderName.OPENROUTER:
            return entry.reasoning_summary
        if entry.reasoning_disable_available and entry.reasoning_summary == "off":
            return "disable supported"
        if entry.reasoning_controls_available:
            if entry.reasoning_disable_available:
                return entry.reasoning_summary
            return f"{entry.reasoning_summary}; provider default"
        return "provider default; controls unavailable"

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
