"""Tests for generic device authorization polling."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.device_authorization import DeviceAuthorizationFlow
from src.auth.oauth_errors import (
    OAuthDeviceAuthorizationExpiredError,
    OAuthDeviceAuthorizationProtocolError,
)
from src.auth.oauth_provider import (
    DeviceAuthorizationDAO,
    DeviceAuthorizationPollResultDAO,
    DeviceAuthorizationPollStatus,
    DeviceAuthorizationPresentationDAO,
    FauxOAuthProvider,
)

_DEVICE_CODE_SENTINEL: str = "device-code-must-not-leak"


def _credential() -> CredentialDAO:
    """Build the deterministic completed credential used by poll tests."""
    return CredentialDAO(
        provider=ProviderName.OPENAI,
        auth_type=AuthType.OAUTH,
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        expires_at=datetime.now(timezone.utc),
    )


class _FakeDeviceProvider(FauxOAuthProvider):
    """Test-only provider that returns scripted device sessions and poll results."""

    def __init__(
        self,
        *,
        results: list[DeviceAuthorizationPollResultDAO | BaseException],
        interval_seconds: int = 5,
        expires_in_seconds: int = 30,
    ) -> None:
        """Store scripted results for one in-memory device attempt."""
        super().__init__(provider=ProviderName.OPENAI)
        self._results: list[DeviceAuthorizationPollResultDAO | BaseException] = results
        self._device_authorization: DeviceAuthorizationDAO = DeviceAuthorizationDAO(
            device_code=_DEVICE_CODE_SENTINEL,
            user_code="ABCD-EFGH",
            verification_uri="https://example.test/device",
            expires_in_seconds=expires_in_seconds,
            interval_seconds=interval_seconds,
        )
        self.started: int = 0
        self.polls: int = 0

    async def start_device_authorization(self) -> DeviceAuthorizationDAO:
        """Return the one scripted in-memory session."""
        self.started += 1
        return self._device_authorization

    async def poll_device_authorization(
        self,
        *,
        device_authorization: DeviceAuthorizationDAO,
    ) -> DeviceAuthorizationPollResultDAO:
        """Record one poll and return its scripted outcome."""
        assert device_authorization.device_code == _DEVICE_CODE_SENTINEL
        self.polls += 1
        next_result: DeviceAuthorizationPollResultDAO | BaseException = self._results.pop(0)
        if isinstance(next_result, BaseException):
            raise next_result
        return next_result


class _Clock:
    """Injected monotonic clock whose sleeps advance time without waiting."""

    def __init__(self) -> None:
        """Initialize the fake clock at zero seconds."""
        self.now: float = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        """Return the current synthetic monotonic time."""
        return self.now

    async def sleep(self, seconds: float) -> None:
        """Record and advance by a synthetic sleep duration."""
        self.sleeps.append(seconds)
        self.now += seconds


async def _cancelled_sleep(seconds: float) -> None:
    """Cancel the current flow at its first scheduled wait."""
    raise asyncio.CancelledError()


class TestDeviceAuthorizationFlow:
    """The generic flow owns polling cadence, deadlines, and cancellation."""

    async def test_invoke_when_provider_returns_pending_then_complete(self) -> None:
        """The first poll is immediate, the second follows one pending wait, and presentation is safe."""
        credential: CredentialDAO = _credential()
        provider: _FakeDeviceProvider = _FakeDeviceProvider(
            results=[
                DeviceAuthorizationPollResultDAO(status=DeviceAuthorizationPollStatus.PENDING),
                DeviceAuthorizationPollResultDAO(
                    status=DeviceAuthorizationPollStatus.COMPLETE,
                    credential=credential,
                ),
            ]
        )
        clock: _Clock = _Clock()
        presentations: list[DeviceAuthorizationPresentationDAO] = []
        flow: DeviceAuthorizationFlow = DeviceAuthorizationFlow(
            provider=provider,
            present=presentations.append,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        result: CredentialDAO = await flow.invoke()

        assert result == credential
        assert provider.started == 1
        assert provider.polls == 2
        assert clock.sleeps == [5]
        assert presentations[0].model_dump() == {
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://example.test/device",
            "expires_in_seconds": 30,
        }
        assert _DEVICE_CODE_SENTINEL not in repr(presentations[0])

    async def test_invoke_when_provider_returns_zero_interval_uses_one_second_floor(self) -> None:
        """A provider-valid initial zero interval becomes one second only at sleep time."""
        provider: _FakeDeviceProvider = _FakeDeviceProvider(
            interval_seconds=0,
            results=[
                DeviceAuthorizationPollResultDAO(status=DeviceAuthorizationPollStatus.PENDING),
                DeviceAuthorizationPollResultDAO(
                    status=DeviceAuthorizationPollStatus.COMPLETE,
                    credential=_credential(),
                ),
            ],
        )
        clock: _Clock = _Clock()
        flow: DeviceAuthorizationFlow = DeviceAuthorizationFlow(
            provider=provider,
            present=lambda presentation: None,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        await flow.invoke()

        assert clock.sleeps == [1]

    async def test_invoke_when_provider_returns_slow_down_without_interval(self) -> None:
        """Slow-down without replacement waits the current interval plus five seconds."""
        provider: _FakeDeviceProvider = _FakeDeviceProvider(
            interval_seconds=2,
            results=[
                DeviceAuthorizationPollResultDAO(status=DeviceAuthorizationPollStatus.SLOW_DOWN),
                DeviceAuthorizationPollResultDAO(
                    status=DeviceAuthorizationPollStatus.COMPLETE,
                    credential=_credential(),
                ),
            ],
        )
        clock: _Clock = _Clock()
        flow: DeviceAuthorizationFlow = DeviceAuthorizationFlow(
            provider=provider,
            present=lambda presentation: None,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        await flow.invoke()

        assert clock.sleeps == [7]

    async def test_invoke_when_provider_returns_slow_down_with_zero_interval_uses_one_second_floor(
        self,
    ) -> None:
        """A zero replacement interval is accepted and floored when the next wait begins."""
        provider: _FakeDeviceProvider = _FakeDeviceProvider(
            results=[
                DeviceAuthorizationPollResultDAO(
                    status=DeviceAuthorizationPollStatus.SLOW_DOWN,
                    interval_seconds=0,
                ),
                DeviceAuthorizationPollResultDAO(
                    status=DeviceAuthorizationPollStatus.COMPLETE,
                    credential=_credential(),
                ),
            ],
        )
        clock: _Clock = _Clock()
        flow: DeviceAuthorizationFlow = DeviceAuthorizationFlow(
            provider=provider,
            present=lambda presentation: None,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        await flow.invoke()

        assert clock.sleeps == [1]

    async def test_invoke_when_deadline_expires_after_slow_down(self) -> None:
        """An expiry after slow-down pins the clock-drift recovery message."""
        provider: _FakeDeviceProvider = _FakeDeviceProvider(
            interval_seconds=1,
            expires_in_seconds=2,
            results=[DeviceAuthorizationPollResultDAO(status=DeviceAuthorizationPollStatus.SLOW_DOWN)],
        )
        clock: _Clock = _Clock()
        flow: DeviceAuthorizationFlow = DeviceAuthorizationFlow(
            provider=provider,
            present=lambda presentation: None,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        with pytest.raises(OAuthDeviceAuthorizationExpiredError) as caught:
            await flow.invoke()

        assert str(caught.value) == (
            "openai device sign-in expired after slow-down responses. This is often caused by clock drift "
            "in WSL or VM environments — sync or restart the VM clock, then start a new attempt."
        )

    async def test_invoke_does_not_poll_after_deadline(self) -> None:
        """A capped sleep that reaches expiry raises before another provider probe."""
        provider: _FakeDeviceProvider = _FakeDeviceProvider(
            interval_seconds=20,
            expires_in_seconds=3,
            results=[DeviceAuthorizationPollResultDAO(status=DeviceAuthorizationPollStatus.PENDING)],
        )
        clock: _Clock = _Clock()
        flow: DeviceAuthorizationFlow = DeviceAuthorizationFlow(
            provider=provider,
            present=lambda presentation: None,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        with pytest.raises(OAuthDeviceAuthorizationExpiredError):
            await flow.invoke()

        assert clock.sleeps == [3]
        assert provider.polls == 1

    async def test_invoke_when_poll_request_times_out_continues_polling(self) -> None:
        """A long-poll timeout is handled exactly like one pending poll result."""
        provider: _FakeDeviceProvider = _FakeDeviceProvider(
            results=[
                asyncio.TimeoutError(),
                DeviceAuthorizationPollResultDAO(
                    status=DeviceAuthorizationPollStatus.COMPLETE,
                    credential=_credential(),
                ),
            ]
        )
        clock: _Clock = _Clock()
        flow: DeviceAuthorizationFlow = DeviceAuthorizationFlow(
            provider=provider,
            present=lambda presentation: None,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        await flow.invoke()

        assert provider.polls == 2
        assert clock.sleeps == [5]

    def test_poll_result_rejects_invalid_status_payload_combinations(self) -> None:
        """The DAO rejects every status and payload combination the flow cannot interpret."""
        credential: CredentialDAO = _credential()

        with pytest.raises(ValidationError, match="COMPLETE requires credential"):
            DeviceAuthorizationPollResultDAO(status=DeviceAuthorizationPollStatus.COMPLETE)
        with pytest.raises(ValidationError, match="credential is only valid with COMPLETE"):
            DeviceAuthorizationPollResultDAO(
                status=DeviceAuthorizationPollStatus.PENDING,
                credential=credential,
            )
        with pytest.raises(ValidationError, match="interval_seconds is only valid with SLOW_DOWN"):
            DeviceAuthorizationPollResultDAO(
                status=DeviceAuthorizationPollStatus.PENDING,
                interval_seconds=1,
            )

    async def test_invoke_when_complete_has_no_credential(self) -> None:
        """A model-constructed invalid completion becomes the flow's safe protocol error."""
        malformed: DeviceAuthorizationPollResultDAO = DeviceAuthorizationPollResultDAO.model_construct(
            status=DeviceAuthorizationPollStatus.COMPLETE,
            credential=None,
            interval_seconds=None,
        )
        provider: _FakeDeviceProvider = _FakeDeviceProvider(results=[malformed])
        clock: _Clock = _Clock()
        flow: DeviceAuthorizationFlow = DeviceAuthorizationFlow(
            provider=provider,
            present=lambda presentation: None,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        with pytest.raises(OAuthDeviceAuthorizationProtocolError):
            await flow.invoke()

    async def test_invoke_when_task_is_cancelled(self) -> None:
        """Cancellation from the scheduled wait escapes and prevents another poll."""
        provider: _FakeDeviceProvider = _FakeDeviceProvider(
            results=[DeviceAuthorizationPollResultDAO(status=DeviceAuthorizationPollStatus.PENDING)]
        )
        flow: DeviceAuthorizationFlow = DeviceAuthorizationFlow(
            provider=provider,
            present=lambda presentation: None,
            sleep=_cancelled_sleep,
            monotonic=lambda: 0.0,
        )

        with pytest.raises(asyncio.CancelledError):
            await flow.invoke()

        assert provider.polls == 1
