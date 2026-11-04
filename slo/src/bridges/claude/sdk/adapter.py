"""One concrete portable adapter over the official Claude Agent SDK."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Optional, Self

from claude_agent_sdk._internal.transport import Transport

from .authentication import ClaudeNativeAuthentication
from .dao import (
    ClaudeAuthenticationStatusDAO,
    ClaudeBridgeConfigurationDAO,
    ClaudeInvocationOptionsDAO,
    ClaudeSessionOptionsDAO,
    ClaudeToolResultBatchDAO,
    ClaudeToolResultSubmissionDAO,
)
from .events import ClaudeBridgeEvent, ClaudeResponseCompletedDAO
from .exceptions import ClaudeBridgeError, ClaudeSubmissionNotStartedError
from .sdk_runtime import ClaudeSDKRuntime
from .inventory import ClaudeToolInventory


class SloClaudeBridgeAdapter:
    """Admit serial native turns and retain their SDK cleanup ownership."""

    def __init__(
        self,
        *,
        configuration: ClaudeBridgeConfigurationDAO,
        transport: Optional[Transport] = None,
        authentication_check: Optional[Callable[[], Awaitable[ClaudeAuthenticationStatusDAO]]] = None,
    ) -> None:
        """Store the supported external I/O seams without native activity.

        Args:
            configuration: Trusted native runtime configuration.
            transport: SDK-supported transport injection; None uses the native SDK default.
            authentication_check: Native status boundary substitute; None uses documented CLI status.
        """
        self._authentication = ClaudeNativeAuthentication(configuration=configuration)
        self._authentication_check = authentication_check or self._authentication.check_authentication
        self._transport = transport
        self._configuration = configuration
        self._runtime = ClaudeSDKRuntime(transport=transport, configuration=configuration)
        self._session_options: Optional[ClaudeSessionOptionsDAO] = None
        self._session_closed = False
        self._invocation_options: Optional[ClaudeInvocationOptionsDAO] = None
        self._closed = False
        self._reader_active = False
        self._admission_active = False
        self._resume_session_id: Optional[str] = None
        self._authentication_task: Optional[asyncio.Task[ClaudeAuthenticationStatusDAO]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
        """Return an inert adapter with one native owner and no running tasks."""
        return cls(configuration=configuration)

    async def check_authentication(self) -> ClaudeAuthenticationStatusDAO:
        """Observe supported native login; this never invokes the model or launches login."""
        self._ensure_adapter_open()
        self._ensure_owner_loop()
        if self._authentication_task is None or self._authentication_task.done():
            self._authentication_task = asyncio.create_task(coro=self._observe_authentication())
        try:
            status = await asyncio.shield(self._authentication_task)
        except asyncio.CancelledError:
            if self._closed:
                raise RuntimeError("Claude authentication cancelled by adapter closure.") from None
            raise
        self._ensure_adapter_open()
        return status

    async def _observe_authentication(self) -> ClaudeAuthenticationStatusDAO:
        """Adapt the injected awaitable status boundary to one owned asyncio task."""
        return await self._authentication_check()

    async def start_session(self, *, session_options: ClaudeSessionOptionsDAO) -> None:
        """Validate fixed options before any native submission; no prompt is sent."""
        self._ensure_adapter_open()
        session_options = session_options.model_copy(
            update={
                "tools": ClaudeToolInventory.freeze(tools=session_options.tools),
            },
            deep=True,
        )
        if self._session_closed:
            raise RuntimeError("Claude session is closed.")
        if self._session_options is not None and self._session_options != session_options:
            raise RuntimeError("Claude session configuration cannot change.")
        if (
            not session_options.working_directory.is_absolute()
            or not session_options.working_directory.is_dir()
        ):
            raise ValueError("Claude working directory must exist and be absolute.")
        status = await self.check_authentication()
        if status.state != "ready":
            raise ClaudeSubmissionNotStartedError(
                code="authentication_required", safe_message=status.safe_message
            )
        self._ensure_adapter_open()
        if self._session_closed:
            raise RuntimeError("Claude session is closed.")
        if self._session_options is not None and self._session_options != session_options:
            raise RuntimeError("Claude session configuration cannot change.")
        self._session_options = session_options

    async def invoke_agent(self, *, invocation_options: ClaudeInvocationOptionsDAO) -> None:
        """Reserve admission across authentication so competing callers cannot start work."""
        self._ensure_adapter_open()
        if self._admission_active:
            raise RuntimeError("Claude invocation admission is already in progress.")
        self._admission_active = True
        try:
            await self._admit_invocation(invocation_options=invocation_options)
        finally:
            self._admission_active = False

    async def _admit_invocation(self, *, invocation_options: ClaudeInvocationOptionsDAO) -> None:
        """Authenticate the reserved turn, then revalidate closure before native start.

        Args:
            invocation_options: The single new prompt owned by this reservation.

        Raises:
            RuntimeError: Session closure, missing configuration or an unsettled turn.
            ClaudeBridgeError: Native authentication is unavailable.
        """
        self._ensure_adapter_open()
        if self._session_closed:
            raise RuntimeError("Claude session is closed.")
        if self._reader_active:
            raise RuntimeError("Claude response already has a reader.")
        if self._session_options is None:
            raise RuntimeError("Claude session is not configured.")
        if not invocation_options.text.strip():
            raise ValueError("Claude bridge requires nonempty text.")
        status = await self.check_authentication()
        self._ensure_adapter_open()
        if self._session_closed or self._session_options is None:
            raise RuntimeError("Claude session is closed.")
        if self._reader_active:
            raise RuntimeError("Claude response already has a reader.")
        if status.state != "ready":
            raise ClaudeSubmissionNotStartedError(
                code="authentication_required", safe_message=status.safe_message
            )
        if self._invocation_options is not None:
            resume_session_id = self._runtime.completed_session_id()
            self._resume_session_id = resume_session_id
            self._runtime = ClaudeSDKRuntime(
                transport=self._transport,
                configuration=self._configuration,
                resume_session_id=resume_session_id,
            )
        self._invocation_options = invocation_options
        self._runtime.start(session_options=self._session_options, invocation_options=invocation_options)

    async def read_response(self, *, invocation_id: str) -> AsyncIterator[ClaudeBridgeEvent]:
        """Stream one admitted invocation; an invocation never has competing readers."""
        self._ensure_invocation(invocation_id=invocation_id)
        if self._reader_active:
            raise ClaudeBridgeError(
                code="invocation_conflict", safe_message="Claude response already has a reader."
            )
        self._reader_active = True
        boundary = False
        try:
            async for event in self._runtime.read_response():
                boundary = isinstance(event, ClaudeResponseCompletedDAO)
                yield event
        except ClaudeSubmissionNotStartedError:
            await self._runtime.close()
            self._runtime = ClaudeSDKRuntime(
                transport=self._transport,
                configuration=self._configuration,
                resume_session_id=self._resume_session_id,
            )
            self._invocation_options = None
            raise
        finally:
            self._reader_active = False
            if not boundary and self._invocation_options is not None:
                await self._runtime.cancel()

    async def close_session(self) -> None:
        """Seal session admission before an invocation has been admitted.

        This does not reset the adapter or authorize a replacement session.
        Use close() to join resources after invocation admission.

        Raises:
            RuntimeError: An invocation has already been admitted.
        """
        if self._invocation_options is not None:
            raise RuntimeError("Cannot retire an admitted native invocation with close_session.")
        self._session_options = None
        self._session_closed = True

    async def cancel_invocation(self, *, invocation_id: str) -> None:
        """Interrupt through the SDK owner and await supported closure."""
        self._ensure_invocation(invocation_id=invocation_id)
        await self._runtime.cancel()

    async def submit_tool_results(
        self, *, invocation_id: str, tool_result_batch: ClaudeToolResultBatchDAO
    ) -> None:
        """Admit one complete continuation to the retained invocation owner."""
        self._ensure_adapter_open()
        self._ensure_invocation(invocation_id=invocation_id)
        await self._runtime.submit_tool_results(
            invocation_id=invocation_id, tool_result_batch=tool_result_batch
        )

    async def handle(self, *, event: ClaudeInvocationOptionsDAO | ClaudeToolResultSubmissionDAO) -> None:
        """Use the same invocation admission, not an independent command queue."""
        self._ensure_adapter_open()
        if isinstance(event, ClaudeToolResultSubmissionDAO):
            await self.submit_tool_results(
                invocation_id=event.invocation_id, tool_result_batch=event.tool_result_batch
            )
            return
        if not isinstance(event, ClaudeInvocationOptionsDAO):
            raise TypeError("Unsupported Claude bridge command.")
        await self.invoke_agent(invocation_options=event)

    async def reset(self) -> None:
        """Refuse transcript reset after admission; serial turns use invoke_agent instead.

        Raises:
            RuntimeError: The adapter is closed or a native turn was admitted.
        """
        self._ensure_adapter_open()
        if self._invocation_options is not None:
            raise RuntimeError("Cannot reset native conversation context; start a new adapter to reset.")

    async def close(self) -> None:
        """Seal admission and retain the runtime while joining supported SDK closure."""
        self._ensure_owner_loop()
        self._closed = True
        if self._authentication_task is not None and not self._authentication_task.done():
            self._authentication_task.cancel()
            await asyncio.gather(self._authentication_task, return_exceptions=True)
        await self._runtime.cancel()

    def _ensure_owner_loop(self) -> None:
        """Bind first asynchronous use and reject cross-loop native control."""
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("Claude adapter used from another event loop.")
        self._loop = loop

    def _ensure_adapter_open(self) -> None:
        """Raise when terminal closure has sealed this adapter."""
        if self._closed:
            raise RuntimeError("Claude bridge adapter is closed.")

    def _ensure_invocation(self, *, invocation_id: str) -> None:
        """Require the exact locally admitted invocation without guessing native IDs."""
        if self._invocation_options is None or self._invocation_options.invocation_id != invocation_id:
            raise RuntimeError("Unknown Claude bridge invocation.")
