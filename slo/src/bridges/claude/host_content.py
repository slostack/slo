"""Translate host LangChain content blocks into portable Claude live content."""

from typing import Any

from .sdk.dao import ClaudeImageDAO, ClaudeTextDAO


class ClaudeHostContent:
    """Own the lossless text/base64-image block translation at the bridge entry."""

    @classmethod
    def translate(cls, *, block: str | dict[Any, Any]) -> ClaudeTextDAO | ClaudeImageDAO:
        """Translate one host block, including an empty string.

        Args:
            block: One LangChain content block.

        Returns:
            ClaudeTextDAO | ClaudeImageDAO: Validated portable live content.

        Raises:
            ValueError: Unknown fields, content kinds or malformed image sources occur.
        """
        if isinstance(block, str):
            return ClaudeTextDAO(text=block)
        if block.get("type") == "text" and set(block) == {"type", "text"}:
            return ClaudeTextDAO(text=block["text"])
        if block.get("type") != "image" or set(block) != {"type", "source"}:
            raise ValueError("Unsupported Claude content block.")
        source = block["source"]
        if (
            not isinstance(source, dict)
            or set(source) != {"type", "media_type", "data"}
            or source["type"] != "base64"
        ):
            raise ValueError("Unsupported Claude image source.")
        return ClaudeImageDAO(media_type=source["media_type"], data=source["data"])

    @staticmethod
    def model_context(*, content: str | list[str | dict[Any, Any]]) -> str | list[str | dict[Any, Any]]:
        """Reduce content to what a model is given: reasoning dropped, plain text joined.

        The same reduction applies to live and replayed messages, so thinking can
        never make an unchanged conversation look edited.
        """
        if isinstance(content, str):
            return content
        kept = [
            block
            for block in content
            if not (isinstance(block, dict) and block.get("type") in {"thinking", "reasoning"})
        ]
        texts = [
            block if isinstance(block, str) else block["text"]
            for block in kept
            if isinstance(block, str)
            or (block.get("type") == "text" and set(block) <= {"type", "text", "index"})
        ]
        return "".join(texts) if len(texts) == len(kept) else kept

    @classmethod
    def translate_all(
        cls, *, content: str | list[str | dict[Any, Any]]
    ) -> tuple[ClaudeTextDAO | ClaudeImageDAO, ...]:
        """Translate a whole message content in order.

        Args:
            content: A string or ordered LangChain block list.

        Returns:
            tuple[ClaudeTextDAO | ClaudeImageDAO, ...]: Ordered portable blocks.
        """
        blocks = [content] if isinstance(content, str) else content
        return tuple(cls.translate(block=block) for block in blocks)
