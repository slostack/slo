"""Tests for ``SubAgentFleetRowDAO``, ``SubAgentFleetRow``, and ``SubAgentFleetPanel``."""

from __future__ import annotations

import time
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from src.tui.widgets.sub_agent_fleet_panel import (
    _GLYPH,
    _LAST_TEXT_MAX_CHARS,
    SubAgentFleetPanel,
    SubAgentFleetRow,
    SubAgentFleetRowDAO,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dao(
    *,
    task_id: str = "task-A",
    session_id: str = "s1",
    status: str = "running",
    last_text: Optional[str] = None,
    prompt_preview: str = "",
) -> SubAgentFleetRowDAO:
    """Build a ``SubAgentFleetRowDAO`` with caller-supplied overrides.

    Args:
        task_id (str): Task label.
        session_id (str): Child session UUID.
        status (str): Lifecycle status literal.
        last_text (Optional[str]): Latest activity text.
        prompt_preview (str): Task prompt preview.

    Returns:
        SubAgentFleetRowDAO: Constructed DAO.
    """
    return SubAgentFleetRowDAO(
        task_id=task_id,
        session_id=session_id,
        status=status,  # type: ignore[arg-type]
        last_text=last_text,
        prompt_preview=prompt_preview,
    )


# ---------------------------------------------------------------------------
# TestSubAgentFleetRowDAO
# ---------------------------------------------------------------------------


class TestSubAgentFleetRowDAO:
    """``SubAgentFleetRowDAO`` construction and validation."""

    def test_default_status_is_running(self) -> None:
        """Newly constructed DAO has ``status == "running"``."""
        dao: SubAgentFleetRowDAO = _make_dao()

        assert dao.status == "running"

    def test_started_at_is_positive_float(self) -> None:
        """``started_at`` is a positive float close to ``time.monotonic()``."""
        before: float = time.monotonic()
        dao: SubAgentFleetRowDAO = _make_dao()
        after: float = time.monotonic()

        assert before <= dao.started_at <= after

    def test_extra_fields_forbidden(self) -> None:
        """Unknown fields raise ``ValidationError``."""
        with pytest.raises(ValidationError):
            SubAgentFleetRowDAO(  # type: ignore[call-arg]
                task_id="t",
                session_id="s",
                unexpected_field="boom",
            )

    def test_model_copy_update_preserves_started_at(self) -> None:
        """``model_copy(update=…)`` does not reset ``started_at``."""
        dao: SubAgentFleetRowDAO = _make_dao()
        original_started_at: float = dao.started_at

        updated: SubAgentFleetRowDAO = dao.model_copy(update={"last_text": "hello"})

        assert updated.started_at == original_started_at
        assert updated.last_text == "hello"

    def test_all_status_literals_accepted(self) -> None:
        """Every ``SubAgentStatus`` literal is a valid value."""
        for status in ("pending", "running", "completed", "failed", "aborted"):
            dao: SubAgentFleetRowDAO = _make_dao(status=status)
            assert dao.status == status

    def test_no_pane_index_field(self) -> None:
        """``SubAgentFleetRowDAO`` no longer has a ``pane_index`` field."""
        dao: SubAgentFleetRowDAO = _make_dao()
        assert not hasattr(dao, "pane_index")


# ---------------------------------------------------------------------------
# TestSubAgentFleetRowFormat
# ---------------------------------------------------------------------------


class TestSubAgentFleetRowFormat:
    """``SubAgentFleetRow._format`` static logic."""

    def test_glyph_always_present(self) -> None:
        """Every row contains ``⊇``."""
        dao: SubAgentFleetRowDAO = _make_dao()

        result: str = SubAgentFleetRow._format(dao=dao)

        assert _GLYPH in result

    def test_running_icon_present(self) -> None:
        """Running row contains ``⏳``."""
        dao: SubAgentFleetRowDAO = _make_dao(status="running")

        result: str = SubAgentFleetRow._format(dao=dao)

        assert "⏳" in result

    def test_completed_icon_present(self) -> None:
        """Completed row contains ``✓``."""
        dao: SubAgentFleetRowDAO = _make_dao(status="completed")

        result: str = SubAgentFleetRow._format(dao=dao)

        assert "✓" in result

    def test_failed_icon_present(self) -> None:
        """Failed row contains ``✗``."""
        dao: SubAgentFleetRowDAO = _make_dao(status="failed")

        result: str = SubAgentFleetRow._format(dao=dao)

        assert "✗" in result

    def test_aborted_icon_matches_failed(self) -> None:
        """Aborted row also renders ``✗``."""
        dao: SubAgentFleetRowDAO = _make_dao(status="aborted")

        result: str = SubAgentFleetRow._format(dao=dao)

        assert "✗" in result

    def test_truncates_long_last_text(self) -> None:
        """``last_text`` longer than ``_LAST_TEXT_MAX_CHARS`` is ellipsis-truncated."""
        long_text: str = "x" * (_LAST_TEXT_MAX_CHARS + 20)
        dao: SubAgentFleetRowDAO = _make_dao(last_text=long_text)

        result: str = SubAgentFleetRow._format(dao=dao)

        assert "…" in result
        assert long_text not in result

    def test_uses_prompt_preview_when_last_text_is_none(self) -> None:
        """When ``last_text`` is ``None``, ``prompt_preview`` is shown."""
        dao: SubAgentFleetRowDAO = _make_dao(
            last_text=None,
            prompt_preview="analyze the codebase",
        )

        result: str = SubAgentFleetRow._format(dao=dao)

        assert "analyze the codebase" in result

    def test_task_id_present_in_output(self) -> None:
        """The task label appears in the row output."""
        dao: SubAgentFleetRowDAO = _make_dao(task_id="my-task-label")

        result: str = SubAgentFleetRow._format(dao=dao)

        assert "my-task-label" in result

    def test_elapsed_seconds_present(self) -> None:
        """Elapsed seconds appear in the row output."""
        dao: SubAgentFleetRowDAO = SubAgentFleetRowDAO(
            task_id="t",
            session_id="s",
            started_at=time.monotonic() - 5.0,
        )

        result: str = SubAgentFleetRow._format(dao=dao)

        assert "s" in result
        assert any(f"{n}s" in result for n in range(4, 8))

    def test_running_row_uses_bold_label(self) -> None:
        """Running row wraps the label in ``[bold]`` markup."""
        dao: SubAgentFleetRowDAO = _make_dao(task_id="running-task", status="running")

        result: str = SubAgentFleetRow._format(dao=dao)

        assert "[bold]running-task[/bold]" in result

    def test_terminal_row_uses_dim_label(self) -> None:
        """Completed/failed row dims the label."""
        dao: SubAgentFleetRowDAO = _make_dao(task_id="done-task", status="completed")

        result: str = SubAgentFleetRow._format(dao=dao)

        assert "[dim]done-task[/dim]" in result

    def test_no_active_glyph_or_inactive_glyph_distinction(self) -> None:
        """There is only one glyph (⊇) — no active/inactive distinction."""
        dao: SubAgentFleetRowDAO = _make_dao()

        result: str = SubAgentFleetRow._format(dao=dao)

        assert result.startswith(_GLYPH) or _GLYPH in result
        assert "◉" not in result

    def test_fleet_row_with_bracketed_activity_does_not_raise(self) -> None:
        """A bracketed child activity is escaped so it never trips markup parsing.

        The row keeps intentional ``[bold]``/``[dim]`` markup, so the dynamic
        ``task_id`` and ``last_text`` segments must be escaped or a value like a
        regex ``[a-z]+`` would be swallowed or raise a ``MarkupError`` when Rich
        parses the row. Asserts the escaped form is present and that rendering the
        row string through a real Rich console does not raise.
        """
        from rich.console import Console
        from rich.markup import escape

        dao: SubAgentFleetRowDAO = _make_dao(
            task_id="task[x]",
            status="running",
            last_text="matched /[a-z]+/ 12 times",
        )

        result: str = SubAgentFleetRow._format(dao=dao)

        assert escape("matched /[a-z]+/ 12 times") in result
        assert escape("task[x]") in result
        Console().render_str(result)


# ---------------------------------------------------------------------------
# TestSubAgentFleetPanelState — pure state logic (no DOM)
# ---------------------------------------------------------------------------


class TestSubAgentFleetPanelState:
    """State-mutation tests that run without mounting the panel in a real DOM."""

    def _make_panel(self) -> SubAgentFleetPanel:
        """Return an un-mounted ``SubAgentFleetPanel`` for state testing."""
        return SubAgentFleetPanel()

    def test_initial_display_false(self) -> None:
        """Freshly constructed panel has ``display == False``."""
        panel: SubAgentFleetPanel = self._make_panel()

        assert panel.display is False

    def test_rows_empty_initially(self) -> None:
        """No rows on construction."""
        panel: SubAgentFleetPanel = self._make_panel()

        assert panel._rows == {}
        assert panel._row_widgets == {}

    def test_update_last_text_running_row(self) -> None:
        """``update_last_text`` updates ``last_text`` for a running row."""
        panel: SubAgentFleetPanel = self._make_panel()
        panel._rows["s1"] = _make_dao(session_id="s1", status="running")
        panel._row_widgets["s1"] = MagicMock()

        panel.update_last_text(session_id="s1", text="new activity")

        assert panel._rows["s1"].last_text == "new activity"

    def test_update_last_text_noop_on_terminal_row(self) -> None:
        """``update_last_text`` is a no-op when the row is ``completed``."""
        panel: SubAgentFleetPanel = self._make_panel()
        panel._rows["s1"] = _make_dao(session_id="s1", status="completed", last_text="old")
        panel._row_widgets["s1"] = MagicMock()

        panel.update_last_text(session_id="s1", text="should not change")

        assert panel._rows["s1"].last_text == "old"

    def test_update_last_text_noop_unknown_session(self) -> None:
        """``update_last_text`` is a no-op for an unregistered ``session_id``."""
        panel: SubAgentFleetPanel = self._make_panel()

        panel.update_last_text(session_id="unknown", text="x")

    def test_mark_terminal_completed(self) -> None:
        """``mark_terminal`` transitions a running row to ``completed``."""
        panel: SubAgentFleetPanel = self._make_panel()
        panel._rows["s1"] = _make_dao(session_id="s1", status="running")
        panel._row_widgets["s1"] = MagicMock()

        panel.mark_terminal(session_id="s1", status="completed")  # type: ignore[arg-type]

        assert panel._rows["s1"].status == "completed"

    def test_mark_terminal_failed(self) -> None:
        """``mark_terminal`` transitions a running row to ``failed``."""
        panel: SubAgentFleetPanel = self._make_panel()
        panel._rows["s1"] = _make_dao(session_id="s1", status="running")
        panel._row_widgets["s1"] = MagicMock()

        panel.mark_terminal(session_id="s1", status="failed")  # type: ignore[arg-type]

        assert panel._rows["s1"].status == "failed"

    def test_mark_terminal_noop_unknown_session(self) -> None:
        """``mark_terminal`` is a no-op for unregistered ``session_id``."""
        panel: SubAgentFleetPanel = self._make_panel()

        panel.mark_terminal(session_id="unknown", status="failed")  # type: ignore[arg-type]

    def test_on_mount_registers_interval(self) -> None:
        """``on_mount`` calls ``set_interval`` with a 1-second interval."""
        panel: SubAgentFleetPanel = self._make_panel()

        with patch.object(panel, "set_interval") as mock_set_interval:
            panel.on_mount()

            mock_set_interval.assert_called_once_with(
                interval=1.0,
                callback=panel._refresh_all_rows,
            )

    def test_refresh_all_rows_calls_widget_update(self) -> None:
        """``_refresh_all_rows`` calls ``update()`` on each row widget."""
        panel: SubAgentFleetPanel = self._make_panel()
        mock_widget: MagicMock = MagicMock()
        panel._rows["s1"] = _make_dao(session_id="s1")
        panel._row_widgets["s1"] = mock_widget

        panel._refresh_all_rows()

        mock_widget.update.assert_called_once()

    def test_no_pane_index_in_register_signature(self) -> None:
        """``register_row`` no longer accepts ``pane_index``."""
        import inspect

        sig = inspect.signature(SubAgentFleetPanel.register_row)
        assert "pane_index" not in sig.parameters
