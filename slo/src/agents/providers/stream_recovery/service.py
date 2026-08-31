"""Classify provider stream failures and resolve safe reconnect configuration."""

from __future__ import annotations

import random

import httpcore
import httpx

from config.timeout_resolver import positive_float_env, positive_int_env
from src.agents.providers.stream_recovery.dao import StreamRecoveryAction, StreamRecoveryDecisionDAO

__all__ = [
    "StreamRecoveryService",
    "provider_stream_first_progress_timeout_seconds",
    "provider_stream_idle_timeout_seconds",
    "provider_stream_reconnect_delay_seconds",
    "provider_stream_continuation_max_attempts",
]

_FIRST_PROGRESS_TIMEOUT_SECONDS: float = 90.0
_IDLE_TIMEOUT_SECONDS: float = 120.0
_RECONNECT_DELAY_SECONDS: float = 1.0
_CONTINUATION_MAX_ATTEMPTS: int = 5
_STREAM_DISCONNECTION_TYPES: tuple[type[BaseException], ...] = (
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


def provider_stream_first_progress_timeout_seconds() -> float:
    """Resolve the first provider-progress deadline for an attempt."""
    return positive_float_env(
        primary_name="SLO_PROVIDER_STREAM_FIRST_PROGRESS_TIMEOUT_SECONDS",
        default=_FIRST_PROGRESS_TIMEOUT_SECONDS,
    )


def provider_stream_idle_timeout_seconds() -> float:
    """Resolve the maximum gap between provider progress events."""
    return positive_float_env(
        primary_name="SLO_PROVIDER_STREAM_IDLE_TIMEOUT_SECONDS",
        default=_IDLE_TIMEOUT_SECONDS,
    )


def provider_stream_reconnect_delay_seconds() -> float:
    """Resolve the base delay used for the one fresh-connection reconnect."""
    return positive_float_env(
        primary_name="SLO_PROVIDER_STREAM_RECONNECT_DELAY_SECONDS",
        default=_RECONNECT_DELAY_SECONDS,
    )


def provider_stream_continuation_max_attempts() -> int:
    """Resolve the total submission-attempt limit for stream continuations."""
    return positive_int_env(
        primary_name="SLO_PROVIDER_STREAM_CONTINUATION_MAX_ATTEMPTS",
        default=_CONTINUATION_MAX_ATTEMPTS,
    )


class StreamRecoveryService:
    """Classify provider-stream failures without inspecting provider or model identity."""

    @classmethod
    def classify(
        cls,
        *,
        exc: BaseException,
        partial_output_committed: bool,
    ) -> StreamRecoveryDecisionDAO:
        """Return the replay-safe decision for one escaped provider stream error.

        WHAT: Maps a controlled transport exception and commit state to a bounded action.
        WHO: Used by provider classification and the agent/session attempt boundary.
        WHEN: Runs before a retry, route switch, or recovery-observation decision.
        """
        if not cls.is_stream_disconnection(exc=exc):
            return cls._propagate_decision()
        if partial_output_committed:
            return cls._interrupted_decision(exc=exc)
        return cls._reconnect_decision(exc=exc)

    @classmethod
    def is_stream_disconnection(cls, *, exc: BaseException) -> bool:
        """Return whether an exception belongs to the controlled transport failure family.

        WHAT: Recognizes concrete HTTP transport failures and the typed progress
            deadlines produced at the graph stream read boundary.
        WHO: Called by provider classification and the agent's typed failure bridge.
        WHEN: Runs before any pool switch, session reconnect, or recovery decision.
        """
        from src.agents.providers.stream_recovery.dao import (  # noqa: PLC0415
            ProviderStreamProgressTimeout,
        )

        return isinstance(exc, _STREAM_DISCONNECTION_TYPES + (ProviderStreamProgressTimeout,))

    @classmethod
    def safe_message(cls, *, decision: StreamRecoveryDecisionDAO) -> str:
        """Return the approved content-free sentence for a recovery decision."""
        if decision.action is StreamRecoveryAction.RETRY_FRESH_CONNECTION:
            return "Provider stream disconnected before output; fresh-connection retry available."
        if decision.action is StreamRecoveryAction.DO_NOT_REPLAY:
            return "Provider stream ended after partial output; automatic replay is disabled."
        return "Provider request failed."

    @classmethod
    def _propagate_decision(cls) -> StreamRecoveryDecisionDAO:
        """Build the conservative decision for a non-transport exception."""
        return StreamRecoveryDecisionDAO(
            action=StreamRecoveryAction.PROPAGATE,
            reason_code="not_a_stream_disconnection",
        )

    @classmethod
    def _interrupted_decision(cls, *, exc: BaseException) -> StreamRecoveryDecisionDAO:
        """Build the terminal decision for a committed stream interruption."""
        return StreamRecoveryDecisionDAO(
            action=StreamRecoveryAction.DO_NOT_REPLAY,
            reason_code="provider_stream_interrupted",
            exception_family=cls._exception_family(exc=exc),
        )

    @classmethod
    def _reconnect_decision(cls, *, exc: BaseException) -> StreamRecoveryDecisionDAO:
        """Build the one-shot fresh-connection decision before committed output."""
        return StreamRecoveryDecisionDAO(
            action=StreamRecoveryAction.RETRY_FRESH_CONNECTION,
            reason_code="provider_stream_disconnected",
            retry_delay_seconds=cls._retry_delay_seconds(),
            exception_family=cls._exception_family(exc=exc),
        )

    @classmethod
    def _exception_family(cls, *, exc: BaseException) -> str:
        """Return only the exception type name, never untrusted exception text."""
        return f"{type(exc).__module__}.{type(exc).__name__}"

    @classmethod
    def _retry_delay_seconds(cls) -> float:
        """Return jittered bounded reconnect backoff from call-time configuration."""
        return provider_stream_reconnect_delay_seconds() * random.uniform(0.5, 1.5)
