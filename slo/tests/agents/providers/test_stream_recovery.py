"""Tests for provider stream recovery classification and safe configuration."""

from __future__ import annotations

import asyncio

import httpcore
import httpx
import pytest
from pydantic import ValidationError

from src.agents.providers.stream_recovery.dao import StreamRecoveryAction, StreamRecoveryDecisionDAO
from src.agents.providers.stream_recovery.service import (
    StreamRecoveryService,
    provider_stream_continuation_max_attempts,
    provider_stream_first_progress_timeout_seconds,
    provider_stream_idle_timeout_seconds,
    provider_stream_reconnect_delay_seconds,
)

_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    httpx.RemoteProtocolError,
    httpcore.RemoteProtocolError,
    httpx.ReadError,
    httpcore.ReadError,
    httpx.ReadTimeout,
    httpcore.ReadTimeout,
    httpx.WriteError,
    httpcore.WriteError,
    httpx.ConnectError,
    httpcore.ConnectError,
    httpx.ConnectTimeout,
    httpcore.ConnectTimeout,
)


def _transport_error(*, error_type: type[BaseException]) -> BaseException:
    """Build one concrete transport exception without network activity."""
    return error_type("token=secret prompt=private https://example.invalid/request-id")


class TestStreamRecoveryDecisionDAO:
    def test_is_frozen_when_field_assignment_is_attempted(self) -> None:
        """The recovery decision is immutable after classification."""
        decision: StreamRecoveryDecisionDAO = StreamRecoveryDecisionDAO(
            action=StreamRecoveryAction.PROPAGATE,
            reason_code="not_a_stream_disconnection",
        )

        with pytest.raises(ValidationError):
            decision.reason_code = "changed"  # type: ignore[misc]


class TestStreamRecoveryService:
    @pytest.mark.parametrize("error_type", _TRANSPORT_ERRORS)
    def test_classify_returns_retry_fresh_connection_when_transport_error_pre_commit(
        self, error_type: type[BaseException], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every controlled transport family retries before the commit boundary."""
        monkeypatch.setattr("random.uniform", lambda _low, _high: 1.0)

        decision: StreamRecoveryDecisionDAO = StreamRecoveryService.classify(
            exc=_transport_error(error_type=error_type),
            partial_output_committed=False,
        )

        assert decision.action is StreamRecoveryAction.RETRY_FRESH_CONNECTION
        assert decision.reason_code == "provider_stream_disconnected"
        assert decision.retry_delay_seconds == 1.0
        assert "secret" not in decision.exception_family

    @pytest.mark.parametrize("error_type", (httpx.RemoteProtocolError, httpcore.ReadError))
    def test_classify_returns_do_not_replay_when_transport_error_post_commit(
        self, error_type: type[BaseException]
    ) -> None:
        """A committed iteration never receives an automatic replay."""
        decision: StreamRecoveryDecisionDAO = StreamRecoveryService.classify(
            exc=_transport_error(error_type=error_type),
            partial_output_committed=True,
        )

        assert decision.action is StreamRecoveryAction.DO_NOT_REPLAY
        assert decision.reason_code == "provider_stream_interrupted"
        assert decision.retry_delay_seconds == 0.0

    @pytest.mark.parametrize("error", (RuntimeError("unknown"), asyncio.TimeoutError()))
    def test_classify_returns_propagate_when_error_is_not_controlled(self, error: BaseException) -> None:
        """Unknown and generic timeout errors retain existing ownership."""
        decision: StreamRecoveryDecisionDAO = StreamRecoveryService.classify(
            exc=error,
            partial_output_committed=False,
        )

        assert decision.action is StreamRecoveryAction.PROPAGATE
        assert StreamRecoveryService.safe_message(decision=decision) == "Provider request failed."

    def test_classify_returns_propagate_when_http_status_error(self) -> None:
        """HTTP status failures remain owned by the existing status taxonomy."""
        request: httpx.Request = httpx.Request(method="GET", url="https://example.invalid")
        response: httpx.Response = httpx.Response(status_code=503, request=request)
        error: httpx.HTTPStatusError = httpx.HTTPStatusError("status", request=request, response=response)

        decision: StreamRecoveryDecisionDAO = StreamRecoveryService.classify(
            exc=error,
            partial_output_committed=False,
        )

        assert decision.action is StreamRecoveryAction.PROPAGATE

    @pytest.mark.parametrize(
        ("sample", "expected"),
        ((0.5, 0.5), (1.5, 1.5)),
    )
    def test_classify_uses_bounded_reconnect_jitter(
        self, sample: float, expected: float, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reconnect delay remains within the locked half-to-one-and-a-half range."""
        monkeypatch.setattr("random.uniform", lambda _low, _high: sample)

        decision: StreamRecoveryDecisionDAO = StreamRecoveryService.classify(
            exc=httpx.RemoteProtocolError("closed"),
            partial_output_committed=False,
        )

        assert decision.retry_delay_seconds == expected

    def test_timeout_resolvers_fall_back_for_invalid_or_non_positive_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Malformed transport-progress configuration never prevents startup."""
        monkeypatch.setenv("SLO_PROVIDER_STREAM_FIRST_PROGRESS_TIMEOUT_SECONDS", "0")
        monkeypatch.setenv("SLO_PROVIDER_STREAM_IDLE_TIMEOUT_SECONDS", "invalid")
        monkeypatch.setenv("SLO_PROVIDER_STREAM_RECONNECT_DELAY_SECONDS", "-1")

        assert provider_stream_first_progress_timeout_seconds() == 90.0
        assert provider_stream_idle_timeout_seconds() == 120.0
        assert provider_stream_reconnect_delay_seconds() == 1.0

    def test_continuation_attempt_limit_uses_valid_environment_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A positive configured continuation limit overrides the default."""
        monkeypatch.setenv("SLO_PROVIDER_STREAM_CONTINUATION_MAX_ATTEMPTS", "3")

        assert provider_stream_continuation_max_attempts() == 3

    @pytest.mark.parametrize("value", ("0", "-1", "invalid"))
    def test_continuation_attempt_limit_falls_back_when_environment_is_invalid(
        self,
        value: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An invalid configured continuation limit retains the safe default."""
        monkeypatch.setenv("SLO_PROVIDER_STREAM_CONTINUATION_MAX_ATTEMPTS", value)

        assert provider_stream_continuation_max_attempts() == 5
