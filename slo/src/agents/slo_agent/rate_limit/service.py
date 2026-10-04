"""Rate-limit policy service functions."""

from __future__ import annotations

import json
import re
from typing import Callable, Optional, Sequence

from langchain_core.messages import BaseMessage

from config.ai_model_config import defaults_for_model
from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO
from src.agents.slo_agent.rate_limit.dao import ModelRateLimitPolicyDAO, RateLimitRetryPlanDAO

__all__ = [
    "IterationRetryPolicy",
    "estimate_request_tokens",
    "policy_for_model",
    "retry_plan_from_error",
]

IterationRetryPolicy = Callable[[BaseException, bool, int], RateLimitRetryPlanDAO]
"""Per-iteration retry decision injected into ``SloAgent.react_streaming``.

Args at call time: ``(exc, saw_visible_output_this_iteration, attempt_number)``.
Returns a ``RateLimitRetryPlanDAO`` (``retryable``, ``wait_seconds``, ``message``).
Defined here (next to ``RateLimitRetryPlanDAO``) so both ``agent.py`` and
``session.py`` import it from one place, avoiding a session<->agent import cycle.
"""


def policy_for_model(
    *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
) -> ModelRateLimitPolicyDAO:
    """Return the configured local rate policy for one model.

    Args:
        model_name (str): Supported model name.

    Returns:
        ModelRateLimitPolicyDAO: Local request-window and retry policy.
    """
    try:
        defaults: dict[str, object] = dict(defaults_for_model(model_name=model_name, snapshot=snapshot))
    except ValueError:
        defaults = {}
    return ModelRateLimitPolicyDAO(
        model_name=model_name,
        requests_per_minute=int_or_none(value=defaults.get("requests_per_minute")),
        tokens_per_minute=int_or_none(value=defaults.get("tokens_per_minute")),
        automatic_retry_attempts=int_or_none(value=defaults.get("automatic_retry_attempts")) or 0,
        local_retry_wait_cap_seconds=int_or_none(value=defaults.get("local_retry_wait_cap_seconds")) or 30,
    )


def estimate_request_tokens(
    *,
    prompt_text: str,
    message_history: Sequence[BaseMessage] = (),
    output_cap_tokens: int,
    reasoning_budget_tokens: Optional[int],
) -> int:
    """Estimate request-window token pressure including replayed history.

    Counts the new prompt text *and* every replayed message's textual content
    (assistant text, tool-call payloads, and tool outputs), because on a resumed
    session the replayed history — not the prompt — dominates the real request.
    A chars/4 heuristic is intentional and sufficient for a local pre-flight; it
    must walk all history content, not only the prompt (the pre-37 estimator's
    blind spot, see spec 36/37).

    Args:
        prompt_text (str): The new user prompt text.
        message_history (Sequence[BaseMessage]): Replayed prior messages for the
            next provider request. Defaults to empty (single-shot prompts).
        output_cap_tokens (int): Configured visible-output cap.
        reasoning_budget_tokens (Optional[int]): Provider-native thinking budget.

    Returns:
        int: Conservative request-window token estimate.
    """
    history_chars: int = sum(_message_char_length(message=m) for m in message_history)
    estimated_input_tokens: int = max(1, (len(prompt_text) + history_chars) // 4)
    return estimated_input_tokens + output_cap_tokens + (reasoning_budget_tokens or 0)


def _message_char_length(*, message: BaseMessage) -> int:
    """Return the approximate character length of one message's content.

    Handles string content, list (multimodal/blocks) content, and tool outputs,
    so tool-heavy replayed turns are not undercounted.

    Args:
        message (BaseMessage): One replayed message.

    Returns:
        int: Character count used by the chars/4 estimate.
    """
    content = getattr(message, "content", "")
    content_length: int = _content_char_length(content=content)
    extension_length: int = _provider_extension_char_length(message=message)
    return content_length + extension_length


def _content_char_length(*, content: object) -> int:
    """Count the visible content portion of one replayed LangChain message.

    Args:
        content (object): String, content blocks, or another LangChain-supported value.

    Returns:
        int: Visible content character count.
    """
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(part) if isinstance(part, str) else len(str(part)) for part in content)
    return len(str(content))


def _provider_extension_char_length(*, message: BaseMessage) -> int:
    """Count private replay metadata exactly once for the request estimate.

    Args:
        message (BaseMessage): One replayed message that may carry a typed provider extension.

    Returns:
        int: Serialized extension length, or zero when absent or malformed.
    """
    from src.agents.providers.message_extension import (
        PROVIDER_MESSAGE_EXTENSION_KEY,
        ProviderMessageExtensionDAO,
    )

    extension_data: object | None = message.additional_kwargs.get(PROVIDER_MESSAGE_EXTENSION_KEY)
    try:
        extension: ProviderMessageExtensionDAO = ProviderMessageExtensionDAO.model_validate(extension_data)
    except ValueError:
        return 0
    return len(json.dumps(extension.model_dump(mode="json"), ensure_ascii=False))


def retry_plan_from_error(
    *,
    model_name: str,
    exc: BaseException,
    attempt_number: int,
    max_attempts: int,
) -> RateLimitRetryPlanDAO:
    """Return a bounded retry plan for one caught provider error.

    Args:
        model_name (str): Active model name.
        exc (BaseException): Caught provider exception.
        attempt_number (int): One-indexed attempt number that just failed.
        max_attempts (int): Total attempt budget for the run.

    Returns:
        RateLimitRetryPlanDAO: Retryability, wait duration, and operator copy.
    """
    if attempt_number >= max_attempts:
        return RateLimitRetryPlanDAO(
            retryable=False,
            wait_seconds=0,
            message=f"{model_name} rate limit reached; retry budget exhausted.",
        )
    wait_seconds: int = _retry_after_seconds(message=str(exc)) or 15
    return RateLimitRetryPlanDAO(
        retryable=True,
        wait_seconds=wait_seconds,
        message=(
            f"Rate limited by {model_name}; retrying in {wait_seconds}s "
            f"(attempt {attempt_number + 1}/{max_attempts})."
        ),
    )


def _retry_after_seconds(*, message: str) -> Optional[int]:
    """Best-effort parse of provider retry-after guidance from exception text.

    Args:
        message (str): Stringified provider exception.

    Returns:
        Optional[int]: Parsed wait duration in seconds, or ``None``.
    """
    match = re.search(r"in\s+([0-9]+(?:\.[0-9]+)?)s", message)
    if match is None:
        return None
    return max(1, round(float(match.group(1))))


def int_or_none(*, value: object) -> Optional[int]:
    """Return ``value`` coerced to ``int`` when possible.

    Args:
        value (object): Candidate numeric value.

    Returns:
        Optional[int]: Parsed integer value, or ``None``.
    """
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[call-overload]  # intentional broad coercion
    except (TypeError, ValueError):
        return None
