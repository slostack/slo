"""Recovery classification and observation building (Feature 50)."""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

from langchain_core.messages import BaseMessage, HumanMessage

from src.agents.providers.stream_recovery.dao import ProviderStreamFailure
from src.agents.providers.credit_exhaustion_policy import (
    AllModelsExhaustedError,
    ProviderErrorClassifier,
    ProviderErrorKind,
    should_switch,
)
from src.agents.slo_agent.recovery.dao import RecoveryClass, RecoveryDecisionDAO
from src.auth.credential_dao import ProviderName

__all__ = [
    "IterationRecoveryPolicy",
    "RecoveryObservationBuilder",
    "RecoveryPolicy",
]

IterationRecoveryPolicy = Callable[[BaseException, int], RecoveryDecisionDAO]
"""Callable injected into ``SloAgent`` to decide recovery on an escaped exception.

Args at call time: ``(exc, recoveries_used)`` — the escaped exception and how many
recoveries this submission has already spent. Parallel to ``IterationRetryPolicy``
in ``rate_limit/service.py`` but decoupled from it.
"""


class RecoveryPolicy:
    """Classify an escaped ReAct-iteration exception into a RecoveryClass.

    Composes ``ProviderErrorClassifier`` for provider-error semantics rather than
    duplicating HTTP-status logic, then folds the result into the three-way
    recovery taxonomy the loop acts on.
    """

    @classmethod
    def classify(
        cls,
        *,
        exc: BaseException,
        provider: Optional[ProviderName] = None,
    ) -> RecoveryDecisionDAO:
        """Return the recovery decision for one escaped iteration exception.

        Provider context overflow and HTTP 413 request-body rejections are
        classified FATAL here. The loop must neither append a recovery observation
        nor replay either rejection; only the session may compact and retry an
        uncommitted, confirmed context overflow.

        Args:
            exc (BaseException): The exception that ended the iteration.
            provider (Optional[ProviderName]): Active provider, when known.

        Returns:
            RecoveryDecisionDAO: The classified recovery decision.
        """
        if isinstance(exc, ProviderStreamFailure):
            return RecoveryDecisionDAO(
                recovery_class=RecoveryClass.MECHANICAL,
                reason="Owned by the provider stream recovery layer.",
            )
        if cls._is_fatal(exc=exc):
            return RecoveryDecisionDAO(
                recovery_class=RecoveryClass.FATAL,
                reason=f"{type(exc).__name__} is never recoverable.",
            )
        terminal_rejection: ProviderErrorKind | None = cls._terminal_provider_rejection_kind(
            exc=exc,
            provider=provider,
        )
        if terminal_rejection is ProviderErrorKind.CONTEXT_OVERFLOW:
            return RecoveryDecisionDAO(
                recovery_class=RecoveryClass.FATAL,
                reason=(
                    "Context window overflow cannot be fixed by LLM recovery; "
                    "the session layer may perform one compaction retry before it becomes terminal."
                ),
            )
        if terminal_rejection is ProviderErrorKind.REQUEST_BODY_TOO_LARGE:
            return RecoveryDecisionDAO(
                recovery_class=RecoveryClass.FATAL,
                reason=(
                    "HTTP 413 request body too large is terminal and cannot be fixed "
                    "by LLM recovery or session-layer compaction."
                ),
            )
        if terminal_rejection in {
            ProviderErrorKind.AUTHENTICATION_FAILED,
            ProviderErrorKind.POLICY_REJECTED,
            ProviderErrorKind.MODEL_UNAVAILABLE,
            ProviderErrorKind.INVALID_PROVIDER_REQUEST,
        }:
            return RecoveryDecisionDAO(
                recovery_class=RecoveryClass.FATAL,
                reason="Provider rejected this request; correct the configuration or request before retrying.",
            )
        if provider is not None and should_switch(
            kind=ProviderErrorClassifier.classify(error=exc, provider=provider)
        ):
            return RecoveryDecisionDAO(
                recovery_class=RecoveryClass.MECHANICAL,
                reason="Owned by the rate-limit / route-switch layers.",
            )
        return RecoveryDecisionDAO(
            recovery_class=RecoveryClass.LLM_RECOVERABLE,
            reason=f"{type(exc).__name__} may be recoverable by the model.",
            observation_hint=cls._observation_hint(exc=exc),
        )

    @classmethod
    def _is_fatal(cls, *, exc: BaseException) -> bool:
        """Return whether ``exc`` must never be demoted into a recovery observation.

        Args:
            exc (BaseException): The escaped exception.

        Returns:
            bool: True when the exception is terminal regardless of budget.
        """
        return isinstance(exc, (asyncio.CancelledError, AllModelsExhaustedError)) or (
            isinstance(exc, ValueError) and "credential" in str(exc).lower()
        )

    @classmethod
    def _terminal_provider_rejection_kind(
        cls,
        *,
        exc: BaseException,
        provider: Optional[ProviderName],
    ) -> ProviderErrorKind | None:
        """Return the terminal provider-rejection kind when the inspector confirms one.

        Args:
            exc (BaseException): Escaped provider exception.
            provider (Optional[ProviderName]): Active provider when known.

        Returns:
            ProviderErrorKind | None: A terminal provider rejection; otherwise
                ``None``.
        """
        inspected_provider: ProviderName = provider or ProviderName.OPENAI
        kind: ProviderErrorKind = ProviderErrorClassifier.inspect(
            error=exc,
            provider=inspected_provider,
        ).kind
        if kind in {
            ProviderErrorKind.CONTEXT_OVERFLOW,
            ProviderErrorKind.REQUEST_BODY_TOO_LARGE,
            ProviderErrorKind.AUTHENTICATION_FAILED,
            ProviderErrorKind.POLICY_REJECTED,
            ProviderErrorKind.MODEL_UNAVAILABLE,
            ProviderErrorKind.INVALID_PROVIDER_REQUEST,
        }:
            return kind
        return None

    @classmethod
    def _observation_hint(cls, *, exc: BaseException) -> Optional[str]:
        """Return an optional extra sentence for the recovery observation.

        Args:
            exc (BaseException): The recoverable exception.

        Returns:
            Optional[str]: A hint sentence, or None.
        """
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return "The previous attempt timed out; a smaller or decomposed step may complete."
        return None


class RecoveryObservationBuilder:
    """Build the synthetic recovery observation appended to model context."""

    @classmethod
    def build(
        cls,
        *,
        exc: BaseException,
        decision: RecoveryDecisionDAO,
        accumulated_messages: list[BaseMessage],
    ) -> BaseMessage:
        """Return the observation message describing ``exc`` to the model.

        Args:
            exc (BaseException): The recoverable exception being demoted.
            decision (RecoveryDecisionDAO): The classification, for its hint text.
            accumulated_messages (list[BaseMessage]): Current run context.

        Returns:
            BaseMessage: A ``HumanMessage`` recovery observation.
        """
        hint: str = f"\n{decision.observation_hint}" if decision.observation_hint else ""
        body: str = (
            "The previous step failed before completing:\n\n"
            f"    {type(exc).__name__}: {exc}\n\n"
            "Analyze whether you can recover from this. If a different approach is "
            "likely to work, take it. If you cannot recover, explain why and stop."
            f"{hint}"
        )
        if accumulated_messages and isinstance(accumulated_messages[-1], HumanMessage):
            prior: str = cls._message_text(message=accumulated_messages[-1])
            return HumanMessage(content=f"{prior}\n\n{body}")
        return HumanMessage(content=body)

    @classmethod
    def _message_text(cls, *, message: BaseMessage) -> str:
        """Return the textual content of one message as a string.

        Args:
            message (BaseMessage): The message to extract text from.

        Returns:
            str: The message content as a plain string.
        """
        content = message.content
        if isinstance(content, str):
            return content
        return str(content)
