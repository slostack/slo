"""Host lifetime contract; invocation remains the existing BaseChatModel API."""

from typing import Protocol

from langchain_core.messages import BaseMessage

from .dao import SloBridgeCancellationReason, SloBridgeSessionOptionsDAO


class SloBridgeProtocol(Protocol):
    """Configure, cancel and close the same model retained by the graph."""

    def configure_session(self, *, session_options: SloBridgeSessionOptionsDAO) -> None:
        """Store final host context inertly; reject changed or closed configuration."""
        ...

    def request_cancellation(self, *, reason: SloBridgeCancellationReason) -> None:
        """Record intent on the owning loop; returning does not establish closure."""
        ...

    def live_message_history(self) -> list[BaseMessage]:
        """Return detached completed context for this live host session only."""
        ...

    def is_retired(self) -> bool:
        """Report whether closure completed, so the session may build a replacement."""
        ...

    async def finish_host_turn(self) -> None:
        """Settle a host stop before terminal publication, cancelling unfinished native work."""
        ...

    async def close(self) -> None:
        """Seal admission and await SDK closure; raised failures retain the owner."""
        ...
