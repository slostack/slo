"""TaskPreview — the single formatter for compact child-task labels.

The registry (``prompt_preview``), the pool's spawned event, the visualizer
loader and the TUI session list all show the same label, so the normalization
and the 150-code-point cap live here, below the UI boundary; runtime code
never imports the TUI. This module formats only: it neither stores task text
nor owns status.

Feature 94, a.2 "Exact projection rules".
"""

from __future__ import annotations

__all__ = ["TaskPreview", "TASK_PREVIEW_MAX_CODE_POINTS"]

TASK_PREVIEW_MAX_CODE_POINTS: int = 150
"""Maximum preview length in Python Unicode code points, ellipsis included.

Measured after normalization; terminal cell clipping is a separate widget concern.
"""

_ELLIPSIS: str = "…"
"""Single code point appended when normalized text exceeds the cap."""

_C1_FIRST: int = 127
"""DEL; together with the C1 block up to ``_C1_LAST`` it is never displayable."""

_C1_LAST: int = 159
"""Last C1 control code point (inclusive)."""

_FIRST_PRINTABLE: int = 32
"""First code point after the C0 control block."""


class TaskPreview:
    """Build safe compact task labels for registry and TUI consumers."""

    @classmethod
    def build(cls, *, task_text: str) -> str:
        """Normalize and cap a label when a task is projected for display.

        WHAT: Strips C0/C1 controls, collapses whitespace runs to single spaces,
            then caps the normalized text at 150 code points; longer text keeps
            149 code points plus an ellipsis. Markup brackets stay literal.
        WHO: Called by ProcessRegistry.register, SubAgentPool's spawned event and
            (from T05/T07) the visualizer loader and session-list row.
        WHEN: Whenever task text becomes a display label; never for storage of
            the full task.

        Args:
            task_text (str): Full task or an explicitly identified legacy preview.

        Returns:
            str: At most 150 Unicode code points, including an ellipsis.
        """
        text: str = cls._normalize(task_text=task_text)
        if len(text) <= TASK_PREVIEW_MAX_CODE_POINTS:
            return text
        return text[: TASK_PREVIEW_MAX_CODE_POINTS - 1] + _ELLIPSIS

    @classmethod
    def _normalize(cls, *, task_text: str) -> str:
        """Remove controls before build collapses whitespace for literal rows.

        Whitespace controls (tab, newline, NEL and friends) survive the filter
        only to be collapsed by ``str.split``, so none reaches the result.

        Args:
            task_text (str): Untrusted display text.

        Returns:
            str: One-line text; no C0/C1 terminal controls remain.
        """
        safe: str = "".join(character for character in task_text if cls._is_kept(character=character))
        return " ".join(safe.split())

    @staticmethod
    def _is_kept(*, character: str) -> bool:
        """Return whether one code point may reach whitespace normalization.

        Args:
            character (str): One code point of untrusted text.

        Returns:
            bool: True for whitespace and printable code points; False for
                every other C0 control, DEL and C1 control.
        """
        code_point: int = ord(character)
        if character.isspace():
            return True
        return code_point >= _FIRST_PRINTABLE and not _C1_FIRST <= code_point <= _C1_LAST
