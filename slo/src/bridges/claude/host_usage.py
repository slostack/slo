"""Translate portable Claude usage into LangChain usage metadata (direct-Anthropic shape)."""

from typing import Optional

from langchain_core.messages.ai import InputTokenDetails, UsageMetadata

from .sdk.dao import ClaudeUsageDAO


class ClaudeHostUsage:
    """Own the usage math at the bridge exit, so streaming code stays free of it."""

    @classmethod
    def translate(cls, *, usage: Optional[ClaudeUsageDAO]) -> Optional[UsageMetadata]:
        """Return LangChain usage in the direct-Anthropic shape, or None when input or output is unknown.

        ``input_tokens`` includes cache read and write (unknown parts count as 0), as
        ``langchain_anthropic`` reports it; the cache counts ride in ``input_token_details``.

        Args:
            usage: Counts for one Claude response, or None when none were reported.

        Returns:
            Optional[UsageMetadata]: Shared-path usage, or None for an honest "unavailable".
        """
        if usage is None or usage.input_tokens is None or usage.output_tokens is None:
            return None
        input_tokens = usage.input_tokens + (usage.cache_read_tokens or 0) + (usage.cache_write_tokens or 0)
        metadata = UsageMetadata(
            input_tokens=input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=input_tokens + usage.output_tokens,
        )
        details = InputTokenDetails()
        if usage.cache_read_tokens is not None:
            details["cache_read"] = usage.cache_read_tokens
        if usage.cache_write_tokens is not None:
            details["cache_creation"] = usage.cache_write_tokens
        if details:
            metadata["input_token_details"] = details
        return metadata
