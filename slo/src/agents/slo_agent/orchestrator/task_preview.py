"""TaskPreview — the single formatter for compact child-task labels.

The registry (``prompt_preview``), the pool's spawned event, the visualizer
loader and the TUI session list all show the same label, so the normalization
and the 150-code-point cap live here, below the UI boundary; runtime code
never imports the TUI. This module formats only: it neither stores task text
nor owns status.

Feature 94, a.2 "Exact projection rules".
"""

from __future__ import annotations

import re
from typing import Optional

TASK_SUMMARY_MAX_CODE_POINTS: int = 96
TASK_SUMMARY_RAW_MAX_CODE_POINTS: int = 512
TASK_SUMMARY_SCAN_CODE_POINTS: int = 16384
TASK_SUMMARY_PREFIX: str = "Task summary v1: "
TASK_SUMMARY_FALLBACK: str = "Task summary unavailable — open details"
TASK_SUMMARY_ERROR: str = (
    "task_summary must describe the assigned work in 1–96 characters; "
    "include an operation and concrete subject."
)
_PROHIBITED_SUMMARIES: frozenset[str] = frozenset(
    {
        TASK_SUMMARY_FALLBACK.casefold(),
        "work on task",
        "complete task",
        "follow instructions",
        "return ready",
        "phase task",
        "do the work",
    }
)
_BIDI_CONTROLS: frozenset[int] = frozenset(
    {0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)}
)

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
    def validate_summary(cls, *, task_summary: str) -> str:
        """Return a complete normalized authored label, or raise a fixed safe ValueError.

        Args:
            task_summary: Authored work description, bounded before normalization.
        Returns:
            str: Complete literal label, never clipped.
        Raises:
            ValueError: The label violates the mechanical input contract.
        """
        if len(task_summary) > TASK_SUMMARY_RAW_MAX_CODE_POINTS:
            raise ValueError(TASK_SUMMARY_ERROR)
        text = cls._normalize(task_text="".join(c for c in task_summary if ord(c) not in _BIDI_CONTROLS))
        tokens = sum(any(c.isalnum() for c in token) for token in text.split())
        if not 1 <= len(text) <= TASK_SUMMARY_MAX_CODE_POINTS or tokens < 2:
            raise ValueError(TASK_SUMMARY_ERROR)
        if text.casefold() in _PROHIBITED_SUMMARIES or text.startswith(TASK_SUMMARY_PREFIX):
            raise ValueError(TASK_SUMMARY_ERROR)
        return text

    @classmethod
    def encode_summary(cls, *, task_summary: str) -> str:
        """Encode an authored label in the released preview string.

        Args:
            task_summary: Producer-authored description.
        Returns:
            str: Marker followed by the complete validated label.
        Raises:
            ValueError: Invalid authored description.
        """
        return TASK_SUMMARY_PREFIX + cls.validate_summary(task_summary=task_summary)

    @classmethod
    def project_summary(cls, *, prompt_preview: str, task_text: Optional[str] = None) -> str:
        """Project admitted incarnation-local sources without inference or I/O.

        Args:
            prompt_preview: Matching saved carrier or legacy prefix.
            task_text: Matching complete original task, when available.
        Returns:
            str: Tagged label, explicit legacy label, or honest fallback.
        """
        authored = cls._project_carrier(prompt_preview=prompt_preview)
        if authored is not None:
            return authored
        if task_text is None and prompt_preview.rstrip().endswith(("…", "...")):
            return TASK_SUMMARY_FALLBACK
        return cls._scan_legacy_label(source=task_text if task_text is not None else prompt_preview)

    @classmethod
    def _project_carrier(cls, *, prompt_preview: str) -> Optional[str]:
        """Decode a valid carrier, letting invalid or untagged sources fall back.

        Args:
            prompt_preview: Already admitted incarnation-local preview.
        Returns:
            Optional[str]: Valid authored label, otherwise None.
        """
        if not prompt_preview.startswith(TASK_SUMMARY_PREFIX):
            return None
        try:
            return cls.validate_summary(task_summary=prompt_preview[len(TASK_SUMMARY_PREFIX) :])
        except ValueError:
            return None

    @classmethod
    def _scan_legacy_label(cls, *, source: str) -> str:
        """Find the first complete explicit label outside fenced legacy text.

        Args:
            source: Complete original text or a non-truncated legacy preview.
        Returns:
            str: Valid explicit label within the bounded window, or fixed fallback.
        """
        window = source[:TASK_SUMMARY_SCAN_CODE_POINTS]
        fence = ""
        consumed = 0
        for line in window.splitlines(keepends=True):
            consumed += len(line)
            # Match splitlines' complete boundary vocabulary, including Unicode separators.
            if not line.endswith(
                ("\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")
            ) and consumed < len(source):
                break
            text = line.strip()
            marker = re.match(r"(`{3,}|~{3,})", text)
            if fence:
                if (
                    marker
                    and marker[1][0] == fence[0]
                    and len(marker[1]) >= len(fence)
                    and not text[len(marker[1]) :].strip()
                ):
                    fence = ""
                continue
            if marker:
                fence = marker[1]
                continue
            label = re.match(r"(?:Task|Goal|Objective):(.+)$", text, flags=re.IGNORECASE)
            if label:
                try:
                    return cls.validate_summary(task_summary=label[1])
                except ValueError:
                    continue
        return TASK_SUMMARY_FALLBACK

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
