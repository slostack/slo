"""Generic polling application service for OAuth device authorization."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import aiohttp

from src.auth.credential_dao import CredentialDAO
from src.auth.oauth_errors import (
    OAuthDeviceAuthorizationExpiredError,
    OAuthDeviceAuthorizationProtocolError,
)
from src.auth.oauth_provider import (
    DeviceAuthorizationDAO,
    DeviceAuthorizationPollResultDAO,
    DeviceAuthorizationPollStatus,
    DeviceAuthorizationPresentationDAO,
    OAuthProvider,
)

__all__ = ["DeviceAuthorizationFlow"]


class DeviceAuthorizationFlow:
    """Run one provider-neutral device authorization session in memory."""

    def __init__(
        self,
        *,
        provider: OAuthProvider,
        present: Callable[[DeviceAuthorizationPresentationDAO], None],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Store dependencies for one cancellable device sign-in attempt.

        WHO: OAuthFlowFactory creates this for device-capable providers.
        WHEN: Once per selected authentication attempt; it is discarded after completion or cancellation.

        Args:
            provider (OAuthProvider): Provider that owns device wire requests.
            present (Callable[[DeviceAuthorizationPresentationDAO], None]): UI-safe instruction sink.
            sleep (Callable[[float], Awaitable[None]], optional): Injectable wait seam. Defaults to asyncio.sleep.
            monotonic (Callable[[], float], optional): Injectable deadline clock. Defaults to time.monotonic.
        """
        self._provider: OAuthProvider = provider
        self._present: Callable[[DeviceAuthorizationPresentationDAO], None] = present
        self._sleep: Callable[[float], Awaitable[None]] = sleep
        self._monotonic: Callable[[], float] = monotonic

    async def invoke(self) -> CredentialDAO:
        """Start, safely present, and poll one device authorization session.

        WHO: Authentication callers invoke this single application gateway.
        WHEN: After the factory selects device authorization for a provider.

        Returns:
            CredentialDAO: The provider-completed OAuth credential, never persisted here.
        """
        device_authorization: DeviceAuthorizationDAO = await self._provider.start_device_authorization()
        self._present(device_authorization.presentation())
        return await self._poll_until_complete(device_authorization=device_authorization)

    async def _poll_until_complete(
        self,
        *,
        device_authorization: DeviceAuthorizationDAO,
    ) -> CredentialDAO:
        """Poll immediately, then wait only while time remains.

        WHO: ``invoke`` calls this after publishing safe device instructions.
        WHEN: For the one in-memory lifetime of a device authorization session.

        Args:
            device_authorization (DeviceAuthorizationDAO): Secret-bearing provider session used only for polls.

        Returns:
            CredentialDAO: The credential from a COMPLETE result.

        Raises:
            OAuthDeviceAuthorizationExpiredError: The device session reaches its deadline.
            OAuthDeviceAuthorizationProtocolError: A bypassed or unknown poll result is unusable.
        """
        deadline: float = self._monotonic() + device_authorization.expires_in_seconds
        interval_seconds: int = device_authorization.interval_seconds
        saw_slow_down: bool = False
        should_wait: bool = False
        while True:
            self._raise_if_expired(deadline=deadline, saw_slow_down=saw_slow_down)
            if should_wait:
                await self._sleep_until_next_poll(
                    deadline=deadline,
                    interval_seconds=interval_seconds,
                    saw_slow_down=saw_slow_down,
                )
            result: DeviceAuthorizationPollResultDAO = await self._poll_once_or_pending(
                device_authorization=device_authorization,
            )
            credential: CredentialDAO | None = self._credential_if_complete(result=result)
            if credential is not None:
                return credential
            saw_slow_down = self._saw_slow_down(result=result, saw_slow_down=saw_slow_down)
            interval_seconds = self._next_interval_seconds(
                current_interval_seconds=interval_seconds,
                result=result,
            )
            should_wait = True

    def _raise_if_expired(self, *, deadline: float, saw_slow_down: bool) -> None:
        """Raise the typed expiry error when no poll time remains.

        WHO: The polling loop calls this before each provider probe.
        WHEN: Before the first poll and after every scheduled wait.
        """
        if self._monotonic() < deadline:
            return
        raise OAuthDeviceAuthorizationExpiredError(
            provider=self._provider.provider_name,
            after_slow_down=saw_slow_down,
        )

    async def _sleep_until_next_poll(
        self,
        *,
        deadline: float,
        interval_seconds: int,
        saw_slow_down: bool,
    ) -> None:
        """Sleep no longer than the remaining authorization lifetime.

        WHO: The polling loop calls this after a non-complete result.
        WHEN: Never before the initial immediate poll.
        """
        remaining_seconds: float = deadline - self._monotonic()
        await self._sleep(min(max(1, interval_seconds), remaining_seconds))
        self._raise_if_expired(deadline=deadline, saw_slow_down=saw_slow_down)

    async def _poll_once_or_pending(
        self,
        *,
        device_authorization: DeviceAuthorizationDAO,
    ) -> DeviceAuthorizationPollResultDAO:
        """Turn a long-poll request timeout into one pending result.

        WHO: The polling loop calls this for every provider probe.
        WHEN: Once immediately and then after each flow-owned wait.
        """
        try:
            return await self._provider.poll_device_authorization(
                device_authorization=device_authorization,
            )
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
            return DeviceAuthorizationPollResultDAO(status=DeviceAuthorizationPollStatus.PENDING)

    def _credential_if_complete(self, *, result: DeviceAuthorizationPollResultDAO) -> CredentialDAO | None:
        """Return a complete credential or reject a bypassed complete payload.

        WHO: The polling loop is the only caller.
        WHEN: After every provider result and before cadence decisions.
        """
        if result.status is not DeviceAuthorizationPollStatus.COMPLETE:
            return None
        if result.credential is not None:
            return result.credential
        raise OAuthDeviceAuthorizationProtocolError(provider=self._provider.provider_name)

    def _next_interval_seconds(
        self,
        *,
        current_interval_seconds: int,
        result: DeviceAuthorizationPollResultDAO,
    ) -> int:
        """Choose the next raw cadence from a non-complete provider result.

        WHO: The polling loop calls this after every incomplete result.
        WHEN: Before the next wait; the one-second floor stays at the sleep boundary.
        """
        if result.status is DeviceAuthorizationPollStatus.PENDING:
            return current_interval_seconds
        if result.status is DeviceAuthorizationPollStatus.SLOW_DOWN:
            if result.interval_seconds is not None:
                return result.interval_seconds
            return current_interval_seconds + 5
        raise OAuthDeviceAuthorizationProtocolError(provider=self._provider.provider_name)

    def _saw_slow_down(
        self,
        *,
        result: DeviceAuthorizationPollResultDAO,
        saw_slow_down: bool,
    ) -> bool:
        """Record whether any prior provider result asked the flow to slow down.

        WHO: The polling loop calls this after an incomplete result.
        WHEN: Its value is attached to a later expiry error for user guidance.
        """
        return saw_slow_down or result.status is DeviceAuthorizationPollStatus.SLOW_DOWN
