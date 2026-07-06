"""Per-model default options for the LLM factory.

Listing a model here is purely a defaults convenience — ``create_llm`` will
still construct a chat model for any name that matches the provider prefix
in ``src/agents/base.py``. Unlisted models fall back to
``temperature=0.1, streaming=True, max_tokens=4096`` (see the factory).

``max_tokens`` is the model's **total output ceiling** — the provider's hard
cap on tokens emitted in one response (e.g. 64000 for ``claude-sonnet-4-6``,
128000 for ``claude-opus-4-7``, mirroring pi). It is not a "visible output"
budget that thinking tokens are added on top of: for adaptive thinking the
thinking tokens count within it, so the factory sends this value as-is and
never exceeds it (see ``LLMFactory._anthropic_max_tokens``).

``context_window`` is the model's **total input context window** in tokens —
the provider's cap on how much history + prompt one request may carry. It is
the single source of truth consumed by ``CompactionChecker`` to decide when
auto-compaction must fire (``compaction/compaction_checker.py``). Models
absent from this table fall back to a conservative 200_000 there.

Convention: list current top-tier production models only. Small / mini /
preview variants still work via fallback defaults but are intentionally
absent from this table so they don't become the default recommendation.
"""

from typing import TypedDict

from src.auth.credential_dao import ProviderName


class ModelDefaults(TypedDict, total=False):
    temperature: float
    max_tokens: int
    context_window: int
    streaming: bool
    requests_per_minute: int
    tokens_per_minute: int
    automatic_retry_attempts: int
    local_retry_wait_cap_seconds: int


MODEL_DEFAULTS: dict[str, ModelDefaults] = {
    # Anthropic Claude — 4.x family. Opus is the flagship; Sonnet is the
    # standard production workhorse. Haiku is intentionally omitted.
    "claude-opus-4-7": {
        "temperature": 0.1,
        "max_tokens": 128_000,  # Total output ceiling (mirrors pi); was 8192.
        # 200k is the standard cap. A 1M window exists but requires the
        # `anthropic-beta: context-1m-2025-08-07` header, which slo does not
        # send — so 200k is the real effective limit. Bump to 1_000_000 only
        # in the same change that enables that beta in the LLM factory.
        "context_window": 200_000,
        "streaming": True,
        "requests_per_minute": 60,
        "tokens_per_minute": 200_000,
        "automatic_retry_attempts": 2,
        "local_retry_wait_cap_seconds": 30,
    },
    "claude-sonnet-4-6": {
        "temperature": 0.1,
        "max_tokens": 64_000,  # Total output ceiling (mirrors pi); was 8192.
        # 200k standard cap; 1M requires the `context-1m` beta header (not sent
        # by slo yet). Bump only when the factory enables that beta.
        "context_window": 200_000,
        "streaming": True,
        "requests_per_minute": 60,
        "tokens_per_minute": 200_000,
        "automatic_retry_attempts": 2,
        "local_retry_wait_cap_seconds": 30,
    },
    # OpenAI Codex — coding-optimized GPT-5.x variants. These route through the
    # same OpenAI lane as gpt-5.4; they differ in context-window sizing and
    # rate-limit expectations. Context-window values are conservative defaults
    # aligned with the gpt-5 / gpt-5.4 split until OpenAI publishes the exact
    # provider caps for this family.
    "gpt-5-codex": {
        "temperature": 0.1,
        "max_tokens": 8192,
        "context_window": 1_050_000,  # total input context window
        "streaming": True,
        "requests_per_minute": 30,
        "tokens_per_minute": 500_000,
        "automatic_retry_attempts": 2,
        "local_retry_wait_cap_seconds": 30,
    },
    "gpt-5.3-codex": {
        "temperature": 0.1,
        "max_tokens": 8192,
        "context_window": 1_050_000,  # total input context window
        "streaming": True,
        "requests_per_minute": 30,
        "tokens_per_minute": 500_000,
        "automatic_retry_attempts": 2,
        "local_retry_wait_cap_seconds": 30,
    },
    "gpt-5.3-codex-spark": {
        "temperature": 0.1,
        "max_tokens": 8192,
        "context_window": 1_050_000,  # total input context window
        "streaming": True,
        "requests_per_minute": 30,
        "tokens_per_minute": 500_000,
        "automatic_retry_attempts": 2,
        "local_retry_wait_cap_seconds": 30,
    },
    "gpt-5.2-codex": {
        "temperature": 0.1,
        "max_tokens": 8192,
        "context_window": 400_000,  # total input context window
        "streaming": True,
        "requests_per_minute": 30,
        "tokens_per_minute": 500_000,
        "automatic_retry_attempts": 2,
        "local_retry_wait_cap_seconds": 30,
    },
    # OpenAI — flagship GPT and reasoning models. Mini / nano variants are
    # intentionally omitted from this table.
    "gpt-5.4": {
        "temperature": 0.1,
        "max_tokens": 8192,
        "context_window": 1_050_000,  # total input context window
        "streaming": True,
        "requests_per_minute": 30,
        "tokens_per_minute": 500_000,
        "automatic_retry_attempts": 2,
        "local_retry_wait_cap_seconds": 30,
    },
    "gpt-5": {
        "temperature": 0.1,
        "max_tokens": 8192,
        "context_window": 400_000,  # total input context window
        "streaming": True,
        "requests_per_minute": 30,
        "tokens_per_minute": 500_000,
        "automatic_retry_attempts": 2,
        "local_retry_wait_cap_seconds": 30,
    },
    "gpt-4.1": {
        "temperature": 0.1,
        "max_tokens": 8192,
        "context_window": 1_000_000,  # total input context window
        "streaming": True,
        "requests_per_minute": 30,
        "tokens_per_minute": 500_000,
        "automatic_retry_attempts": 1,
        "local_retry_wait_cap_seconds": 30,
    },
    "gpt-4o": {
        "temperature": 0.1,
        "max_tokens": 8192,
        "context_window": 128_000,  # total input context window
        "streaming": True,
        "requests_per_minute": 30,
        "tokens_per_minute": 500_000,
        "automatic_retry_attempts": 1,
        "local_retry_wait_cap_seconds": 30,
    },
    "o3": {
        "temperature": 0.1,
        "max_tokens": 8192,
        "context_window": 200_000,  # total input context window
        "streaming": True,
        "requests_per_minute": 30,
        "tokens_per_minute": 500_000,
        "automatic_retry_attempts": 2,
        "local_retry_wait_cap_seconds": 30,
    },
    "o1": {
        "temperature": 0.1,
        "max_tokens": 8192,
        "context_window": 200_000,  # total input context window
        "streaming": True,
        "requests_per_minute": 30,
        "tokens_per_minute": 500_000,
        "automatic_retry_attempts": 2,
        "local_retry_wait_cap_seconds": 30,
    },
    # Kimi For Coding (KFC) — https://api.kimi.com/coding/v1 (OpenAI-compatible).
    # Keys issued from the Kimi Code Console (https://kimi.com/code).
    # max_retries=0 is enforced at the factory level so credit-exhaustion errors
    # surface immediately for ModelPool to handle.
    # 262k context; always-on reasoning (cannot be disabled via API).
    # Temperature MUST be exactly 1 — Kimi rejects any other value (400 error).
    "kimi-for-coding": {
        "temperature": 1,
        "max_tokens": 32768,
        "context_window": 262_144,  # total input context window
        "streaming": True,
        "requests_per_minute": 20,
        "tokens_per_minute": 200_000,
        "automatic_retry_attempts": 3,
        "local_retry_wait_cap_seconds": 30,
    },
}

_PROVIDER_DEFAULT_MODELS: dict[ProviderName, str] = {
    ProviderName.ANTHROPIC: "claude-sonnet-4-6",
    ProviderName.OPENAI: "gpt-5.4",
    ProviderName.KIMI_FOR_CODING: "kimi-for-coding",
}


def default_model_for_provider(*, provider: ProviderName) -> str:
    """Return the recommended landing model for one provider.

    Args:
        provider (ProviderName): Provider whose default model is needed.

    Returns:
        str: The recommended default model name.
    """
    return _PROVIDER_DEFAULT_MODELS[provider]
