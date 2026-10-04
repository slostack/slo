"""Integration tests for ModelPool fallback across FauxChatModel stubs (spec 28.a.6).

These tests assemble a real ModelPool from FauxChatModel instances and
exercise the full credit-exhaustion fallback path without touching any
provider API.
"""

from __future__ import annotations

import time
from typing import Any, Optional, cast

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from unittest.mock import patch

from src.agents.providers.credit_exhaustion_policy import (
    AllModelsExhaustedError,
    ProviderErrorKind,
)
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.graph import adapt_chatgpt_backend_request
from src.auth.credential_dao import ProviderName

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _CreditError(Exception):
    """Fake 402 credit-exhaustion exception."""

    status_code: int = 402


class _NetworkError(Exception):
    """Fake non-credit error."""

    status_code: int = 503


def _faux(*, responses: list[str]) -> FauxChatModel:
    """Build a FauxChatModel scripted to return the given response strings.

    Args:
        responses (list[str]): Content strings for each response in order.

    Returns:
        FauxChatModel: Scripted deterministic chat model.
    """
    return FauxChatModel(responses=[AIMessage(content=r) for r in responses])


def _pool(
    *,
    primary_responses: list[str],
    secondary_responses: list[str],
) -> ModelPool:
    """Build a two-entry pool backed by FauxChatModel stubs.

    Args:
        primary_responses (list[str]): Content for primary responses.
        secondary_responses (list[str]): Content for secondary responses.

    Returns:
        ModelPool: Pool with claude-primary (priority 0) and gpt-secondary (priority 1).
    """
    dao: ModelPoolDAO = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(
                model_name="claude-primary",
                provider=ProviderName.ANTHROPIC,
                priority=0,
                cooldown_seconds=300,
            ),
            ModelPoolEntryDAO(
                model_name="gpt-secondary",
                provider=ProviderName.OPENAI,
                priority=1,
                cooldown_seconds=300,
            ),
        ]
    )
    return ModelPool(
        pool_dao=dao,
        models={
            "claude-primary": _faux(responses=primary_responses),
            "gpt-secondary": _faux(responses=secondary_responses),
        },
    )


_MESSAGES: list[HumanMessage] = [HumanMessage(content="hello")]


def _classify_side_effect(*, error: Exception, provider: ProviderName) -> ProviderErrorKind:
    """Test-local classifier: 402 → CREDIT_EXHAUSTED, anything else → OTHER.

    Args:
        error (Exception): The raised exception.
        provider (ProviderName): The provider that raised it.

    Returns:
        ProviderErrorKind: Classification result.
    """
    status: int | None = getattr(error, "status_code", None)
    if status == 402:
        return ProviderErrorKind.CREDIT_EXHAUSTED
    return ProviderErrorKind.OTHER


# ---------------------------------------------------------------------------
# Autouse fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_classify():
    """Replace the real classifier with a deterministic test version."""
    with patch(
        "src.agents.providers.model_pool.ProviderErrorClassifier.classify",
        side_effect=_classify_side_effect,
    ):
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPoolPrimarySucceeds:
    def test_primary_response_used_when_healthy(self) -> None:
        """When the primary model succeeds, the secondary is never called."""
        pool: ModelPool = _pool(
            primary_responses=["I am the primary"],
            secondary_responses=["I am the secondary"],
        )
        result = pool._generate(messages=_MESSAGES)
        assert result.generations[0].message.content == "I am the primary"
        assert pool._models["gpt-secondary"]._call_count == 0


class TestPoolFallback:
    def test_secondary_used_when_primary_exhausted(self) -> None:
        """Credit exhaustion on primary routes the call to secondary."""
        primary: FauxChatModel = FauxChatModel(responses=[])
        primary._generate = lambda *a, **kw: (_ for _ in ()).throw(_CreditError())

        secondary: FauxChatModel = _faux(responses=["from secondary"])
        dao: ModelPoolDAO = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(
                    model_name="claude-primary",
                    provider=ProviderName.ANTHROPIC,
                    priority=0,
                    cooldown_seconds=300,
                ),
                ModelPoolEntryDAO(
                    model_name="gpt-secondary",
                    provider=ProviderName.OPENAI,
                    priority=1,
                    cooldown_seconds=300,
                ),
            ]
        )
        pool: ModelPool = ModelPool(
            pool_dao=dao,
            models={"claude-primary": primary, "gpt-secondary": secondary},
        )

        result = pool._generate(messages=_MESSAGES)
        assert result.generations[0].message.content == "from secondary"
        assert "claude-primary" in pool._cooldowns

    def test_primary_is_cooled_after_exhaustion(self) -> None:
        """Primary cooldown timestamp is in the future after credit exhaustion."""
        primary: FauxChatModel = FauxChatModel(responses=[])
        primary._generate = lambda *a, **kw: (_ for _ in ()).throw(_CreditError())
        secondary: FauxChatModel = _faux(responses=["ok"])

        dao: ModelPoolDAO = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(
                    model_name="claude-primary",
                    provider=ProviderName.ANTHROPIC,
                    priority=0,
                    cooldown_seconds=300,
                ),
                ModelPoolEntryDAO(
                    model_name="gpt-secondary",
                    provider=ProviderName.OPENAI,
                    priority=1,
                    cooldown_seconds=300,
                ),
            ]
        )
        pool: ModelPool = ModelPool(
            pool_dao=dao,
            models={"claude-primary": primary, "gpt-secondary": secondary},
        )
        pool._generate(messages=_MESSAGES)
        assert pool._cooldowns.get("claude-primary", 0) > time.monotonic()


class TestPoolAllExhausted:
    def test_all_models_exhausted_raises(self) -> None:
        """When both entries are cooled, AllModelsExhaustedError is raised."""
        pool: ModelPool = _pool(primary_responses=[], secondary_responses=[])
        pool._cooldowns["claude-primary"] = time.monotonic() + 9999
        pool._cooldowns["gpt-secondary"] = time.monotonic() + 9999
        with pytest.raises(AllModelsExhaustedError):
            pool._generate(messages=_MESSAGES)


class TestPoolTransientProviderFailure:
    def test_switches_to_fallback_when_primary_returns_http_503(self) -> None:
        """A switchable transient 503 cools the primary model and uses the fallback."""
        primary: FauxChatModel = FauxChatModel(responses=[])
        primary._generate = lambda *a, **kw: (_ for _ in ()).throw(_NetworkError())
        secondary: FauxChatModel = _faux(responses=["never"])

        dao: ModelPoolDAO = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(
                    model_name="claude-primary",
                    provider=ProviderName.ANTHROPIC,
                    priority=0,
                ),
                ModelPoolEntryDAO(
                    model_name="gpt-secondary",
                    provider=ProviderName.OPENAI,
                    priority=1,
                ),
            ]
        )
        pool: ModelPool = ModelPool(
            pool_dao=dao,
            models={"claude-primary": primary, "gpt-secondary": secondary},
        )
        result = pool._generate(messages=_MESSAGES)

        assert result.generations[0].message.content == "never"
        assert pool._cooldowns.get("claude-primary", 0) > time.monotonic()


# ---------------------------------------------------------------------------
# Composed compaction fallback directions (85.a.4 §2 R2)
# ---------------------------------------------------------------------------


_SUMMARY_MESSAGES: list[BaseMessage] = [
    SystemMessage(content="You are a conversation compactor"),
    HumanMessage(content="compaction input"),
]


class _RateLimitError(Exception):
    """Fake 429 rate-limit exception — switchable for any provider lane."""

    status_code: int = 429


def _codex_openai() -> ChatOpenAI:
    """Build a ChatOpenAI rooted at the ChatGPT backend base URL.

    Called by ``_CapturingCodexMember`` so the real adapter recognizes the
    duck-typed member as a ChatGPT-backend Responses lane.

    Returns:
        ChatOpenAI: A model ``_uses_chatgpt_backend_responses`` classifies as Codex.
    """
    return ChatOpenAI(
        model="gpt-5.4",
        api_key="sk-test",  # type: ignore[arg-type]
        openai_api_base="https://chatgpt.com/backend-api/codex",  # type: ignore[call-arg]
        use_responses_api=True,
    )


class _CapturingMember:
    """Duck-typed pool member that records the request the adapter shaped for it.

    Used by the composed fallback-direction tests to observe exactly which
    messages and kwargs each selected lane received.
    """

    def __init__(self, *, error: Exception | None = None) -> None:
        """Store the optional pre-output failure.

        Args:
            error (Exception | None): Error raised before any output, or None
                for a healthy member.
        """
        self.error: Exception | None = error
        self.received_messages: list[BaseMessage] | None = None
        self.received_kwargs: dict[str, Any] | None = None

    async def _agenerate(
        self,
        *,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Record the shaped request, then fail or succeed as scripted.

        Args:
            messages (list[BaseMessage]): Adapter-shaped request messages.
            stop (Optional[list[str]]): Stop sequences forwarded by the pool.
            run_manager (Any): LangChain callback manager forwarded by the pool.
            **kwargs: Adapter-shaped invocation kwargs.

        Returns:
            ChatResult: A minimal successful result for a healthy member.
        """
        self.received_messages = list(messages)
        self.received_kwargs = dict(kwargs)
        if self.error is not None:
            raise self.error
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])


class _CapturingCodexMember(_CapturingMember):
    """Capturing member the adapter detects as ChatGPT-backend via ``.bound``."""

    def __init__(self, *, error: Exception | None = None) -> None:
        """Attach a ChatGPT-backend ``ChatOpenAI`` under ``.bound``.

        Args:
            error (Exception | None): Error raised before any output, or None
                for a healthy member.
        """
        super().__init__(error=error)
        self.bound: ChatOpenAI = _codex_openai()


def _compaction_direction_pool(*, primary: object, secondary: object) -> ModelPool:
    """Build a two-member pool wired with the real per-member request adapter.

    Called by the composed fallback-direction tests so the production
    ``adapt_chatgpt_backend_request`` shapes whichever lane the pool routes to.

    Args:
        primary (object): Priority-0 duck-typed capturing member.
        secondary (object): Priority-1 duck-typed capturing member.

    Returns:
        ModelPool: Pool routing primary then secondary.
    """
    dao: ModelPoolDAO = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
            ModelPoolEntryDAO(
                model_name="claude-sonnet-4-6",
                provider=ProviderName.ANTHROPIC,
                priority=1,
            ),
        ]
    )
    return ModelPool(
        pool_dao=dao,
        models={
            "gpt-5.4": cast(BaseChatModel, primary),
            "claude-sonnet-4-6": cast(BaseChatModel, secondary),
        },
        request_adapter=adapt_chatgpt_backend_request,
    )


class _OpenRouterSummaryMember(_CapturingMember):
    """Capturing member that owns a fixed prepared summary cap like the real adapter."""

    def __init__(self, *, ceiling: int, error: Exception | None = None) -> None:
        """Store the selected member's immutable cap and optional pre-output error."""
        super().__init__(error=error)
        self.ceiling = ceiling

    def cap_compaction_summary_kwargs(self, *, kwargs: dict[str, object]) -> dict[str, object]:
        """Return a detached request mapping bounded by this member's cap."""
        requested = kwargs.get("max_tokens")
        assert type(requested) is int
        return {**kwargs, "max_tokens": min(requested, self.ceiling)}


def _openrouter_summary_pool(*, primary: object, secondary: object) -> ModelPool:
    """Build a pool whose fallback's concrete member owns a smaller summary cap."""
    primary_name = "openrouter:vendor/primary"
    secondary_name = "openrouter:vendor/secondary"
    return ModelPool(
        pool_dao=ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name=primary_name, provider=ProviderName.OPENROUTER, priority=0),
                ModelPoolEntryDAO(model_name=secondary_name, provider=ProviderName.OPENROUTER, priority=1),
            ]
        ),
        models={primary_name: cast(BaseChatModel, primary), secondary_name: cast(BaseChatModel, secondary)},
        request_adapter=adapt_chatgpt_backend_request,
    )


class TestPoolCompactionFallbackDirections:
    """85.a.4 §2 R2 — a pre-output fallback re-derives the correct lane shape."""

    async def test_codex_primary_failure_restores_system_and_cap_for_non_codex_fallback(self) -> None:
        """Codex→non-Codex: the fallback keeps the SystemMessage and raw cap."""
        secondary = _CapturingMember()
        pool = _compaction_direction_pool(
            primary=_CapturingCodexMember(error=_RateLimitError()),
            secondary=secondary,
        )

        result = await pool._agenerate(messages=_SUMMARY_MESSAGES, max_tokens=1234)

        assert result.generations[0].message.content == "ok"
        assert secondary.received_kwargs == {"max_tokens": 1234}
        assert secondary.received_messages is not None
        assert any(isinstance(m, SystemMessage) for m in secondary.received_messages)

    async def test_non_codex_primary_failure_produces_instructions_for_codex_fallback(self) -> None:
        """non-Codex→Codex: the fallback carries instructions and no output cap."""
        secondary = _CapturingCodexMember()
        pool = _compaction_direction_pool(
            primary=_CapturingMember(error=_RateLimitError()),
            secondary=secondary,
        )

        result = await pool._agenerate(messages=_SUMMARY_MESSAGES, max_tokens=1234)

        assert result.generations[0].message.content == "ok"
        assert secondary.received_kwargs == {"instructions": "You are a conversation compactor"}
        assert secondary.received_messages is not None
        assert all(not isinstance(m, SystemMessage) for m in secondary.received_messages)

    async def test_openrouter_fallback_uses_smaller_selected_member_cap_for_summary(self) -> None:
        """A pre-output fallback recomputes the summary cap from its selected OpenRouter entry."""
        secondary = _OpenRouterSummaryMember(ceiling=500)
        pool = _openrouter_summary_pool(
            primary=_OpenRouterSummaryMember(ceiling=3000, error=_RateLimitError()),
            secondary=secondary,
        )

        result = await pool._agenerate(
            messages=_SUMMARY_MESSAGES,
            max_tokens=3000,
            _slo_compaction_summary=True,
        )

        assert result.generations[0].message.content == "ok"
        assert secondary.received_kwargs == {"max_tokens": 500}


class TestPoolBindToolsPreservesCooldowns:
    def test_bind_tools_copies_active_cooldowns(self) -> None:
        """bind_tools on a pool with a cooled entry preserves that cooldown."""
        pool: ModelPool = _pool(primary_responses=["ok"], secondary_responses=["ok2"])
        pool._cooldowns["claude-primary"] = time.monotonic() + 9999
        new_pool: ModelPool = pool.bind_tools(tools=[])
        assert "claude-primary" in new_pool._cooldowns
        assert new_pool._cooldowns["claude-primary"] == pool._cooldowns["claude-primary"]
