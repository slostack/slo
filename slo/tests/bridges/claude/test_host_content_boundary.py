"""Reject heterogeneous host input before portable content can escape."""

import pytest

from src.bridges.claude.host_content import ClaudeHostContent


@pytest.mark.parametrize("content", [None, 7, ["valid", None], ["valid", {1: "text"}]])
def test_malformed_later_content_rejects_whole_message(content: object) -> None:
    """Unsupported runtime values fail as boundary validation, not attribute errors."""
    with pytest.raises(ValueError):
        ClaudeHostContent.translate_all(content=content)


@pytest.mark.parametrize("content", [[None], [{"type": "text", "text": 7}], [{1: "text"}]])
def test_model_context_rejects_malformed_blocks(content: object) -> None:
    """Fingerprint reduction cannot admit invalid shapes or non-string text."""
    with pytest.raises(ValueError):
        ClaudeHostContent.model_context(content=content)
