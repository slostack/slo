"""The sole capture normalization contract for the Slo b.2 baseline fixtures."""

from __future__ import annotations

import re

__all__ = ["normalize_baseline_capture"]


_NORMALIZER_VERSION: str = "v1"
_UUID_PATTERN: re.Pattern[str] = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[1-5][0-9A-Fa-f]{3}-[89ABab][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
)
_TIMESTAMP_PATTERN: re.Pattern[str] = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-][0-2]\d:?[0-5]\d)?\b"
)
_TEMP_ROOT_PATTERN: re.Pattern[str] = re.compile(
    r"(?:/tmp/(?:pytest-of-[^/]+|tmp[^/]*)(?:/[^\s\"']*)?|"
    r"/var/folders/[^/]+/[^/]+/T(?:/[^\s\"']*)?|"
    r"[A-Za-z]:\\(?:Users\\[^\\]+\\AppData\\Local\\Temp|Temp)\\(?:tmp|pytest)[^\\\s\"']*(?:\\[^\s\"']*)?)"
)


def _normalize_timestamp(*, text: str) -> str:
    """Replace timestamps without changing surrounding capture content.

    Args:
        text (str): UTF-8 capture text before timestamp replacement.

    Returns:
        str: Capture text with timestamps represented by ``<TIMESTAMP>``.
    """
    return _TIMESTAMP_PATTERN.sub("<TIMESTAMP>", text)


def _normalize_uuid(*, text: str) -> str:
    """Replace UUID values without changing relationships among other identifiers.

    Args:
        text (str): UTF-8 capture text before UUID replacement.

    Returns:
        str: Capture text with UUID values represented by ``<UUID>``.
    """
    return _UUID_PATTERN.sub("<UUID>", text)


def _normalize_absolute_temp_root(*, text: str) -> str:
    """Replace only recognized absolute temporary roots.

    Args:
        text (str): UTF-8 capture text before temporary-root replacement.

    Returns:
        str: Capture text with recognized temporary roots represented by ``<TEMP_ROOT>``.
    """
    return _TEMP_ROOT_PATTERN.sub("<TEMP_ROOT>", text)


def normalize_baseline_capture(*, capture: bytes, case_id: str) -> bytes:
    """Normalize only volatile timestamps, UUIDs, and absolute temporary roots.

    WHAT: Replaces process-specific values while preserving all semantic text,
        ordering, identifiers' relationships, ANSI spans, exits, and errors.
    WHO: Every named b.2 characterization exercise calls this directly before
        ``BaselineComparator.compare``.
    WHEN: Immediately after each real/faux boundary capture is serialized.

    Args:
        capture (bytes): Raw sensitive-free UTF-8 capture bytes.
        case_id (str): Named baseline case; retained for diagnostics and to
            prevent a helper from silently normalizing an unnamed capture.

    Returns:
        bytes: UTF-8 capture with only allowed volatile substitutions.

    Raises:
        ValueError: If the caller omitted a baseline case identifier or the
            capture is not UTF-8 text.
    """
    if not case_id:
        raise ValueError("baseline capture requires a case_id")
    try:
        text: str = capture.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("baseline capture must be UTF-8") from error
    normalized_timestamp: str = _normalize_timestamp(text=text)
    normalized_uuid: str = _normalize_uuid(text=normalized_timestamp)
    normalized_temp_root: str = _normalize_absolute_temp_root(text=normalized_uuid)
    return normalized_temp_root.encode("utf-8")
