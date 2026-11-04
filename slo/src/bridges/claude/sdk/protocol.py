"""Public SDK boundary for serial turns in one live native conversation."""

from collections.abc import AsyncIterator
from typing import Protocol, Self, runtime_checkable

from .dao import (
    ClaudeAuthenticationStatusDAO,
    ClaudeBridgeConfigurationDAO,
    ClaudeInvocationOptionsDAO,
    ClaudeSessionOptionsDAO,
    ClaudeToolResultBatchDAO,
    ClaudeToolResultSubmissionDAO,
)
from .events import ClaudeBridgeEvent


@runtime_checkable
class SloBridgeAdapterProtocol(Protocol):
    """Own one SDK conversation without exposing SDK objects to host callers."""

    @classmethod
    def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
        """Construct inertly without native I/O or event-loop capture."""
        ...

    async def check_authentication(self) -> ClaudeAuthenticationStatusDAO:
        """Observe existing native login without inference or credential extraction."""
        ...

    async def start_session(self, *, session_options: ClaudeSessionOptionsDAO) -> None:
        """Store validated fixed options before submission."""
        ...

    async def invoke_agent(self, *, invocation_options: ClaudeInvocationOptionsDAO) -> None:
        """Reserve one submission and start its SDK owner."""
        ...

    async def close_session(self) -> None:
        """Seal session admission before invocation; close() joins admitted resources."""
        ...

    def read_response(self, *, invocation_id: str) -> AsyncIterator[ClaudeBridgeEvent]:
        """Read to a parked tool boundary or terminal completion after SDK cleanup."""
        ...

    async def cancel_invocation(self, *, invocation_id: str) -> None:
        """Request supported interruption and join SDK closure."""
        ...

    async def submit_tool_results(
        self, *, invocation_id: str, tool_result_batch: ClaudeToolResultBatchDAO
    ) -> None:
        """Accept the complete outstanding result set without another query."""
        ...

    async def handle(self, *, event: ClaudeInvocationOptionsDAO | ClaudeToolResultSubmissionDAO) -> None:
        """Submit the declared command through the same admission owner."""
        ...

    async def reset(self) -> None:
        """Refuse transcript reset after admission; serial turns use invoke_agent."""
        ...

    async def close(self) -> None:
        """Seal admission and await all SDK-owned work."""
        ...
