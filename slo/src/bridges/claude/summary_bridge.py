"""One-shot, tool-free Claude bridge for a single summariser request."""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, Optional

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.outputs import ChatGenerationChunk

from src.bridges.dao import SloBridgeSessionOptionsDAO

from .bridge import SloClaudeBridge


class ClaudeSummaryBridge(SloClaudeBridge):
    """Answer one shared summariser request on its own native session.

    The request's system message becomes the native instructions, no tools are
    ever bound, and the conversation bridge's session, consumed history and tool
    inventory are never touched. Claude Code owns output limits, so the
    summariser's ``max_tokens`` is accepted and ignored here only.
    """

    session_id: str
    working_directory: Path

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[ChatGenerationChunk, None]:
        """Configure instructions from the leading system message, then stream the answer."""
        if (
            not messages
            or not isinstance(messages[0], SystemMessage)
            or not isinstance(messages[0].content, str)
        ):
            raise ValueError("Claude summary request must begin with a text system message.")
        self.configure_session(
            session_options=SloBridgeSessionOptionsDAO(
                session_id=self.session_id,
                working_directory=self.working_directory,
                instructions=messages[0].content,
            )
        )
        kwargs.pop("max_tokens", None)
        async for chunk in super()._astream(messages[1:], stop, run_manager, **kwargs):
            yield chunk
