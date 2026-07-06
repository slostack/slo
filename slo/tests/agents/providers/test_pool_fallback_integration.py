"""Integration tests for ModelPool fallback across FauxChatModel stubs (spec 28.a.6).

These tests assemble a real ModelPool from FauxChatModel instances and
exercise the full credit-exhaustion fallback path without touching any
provider API.
"""
from __future__ import annotations

import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from unittest.mock import patch

from src.agents.providers.credit_exhaustion_policy import (
    AllModelsExhaustedError,
    ProviderErrorKind,
)
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.agents.providers.faux import FauxChatModel
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
        "src.agents.providers.model_pool.CreditExhaustionPolicy.classify",
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


class TestPoolNonCreditError:
    def test_non_credit_error_propagates_immediately(self) -> None:
        """A 503 error does not trigger fallback — it re-raises."""
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
        with pytest.raises(_NetworkError):
            pool._generate(messages=_MESSAGES)
        assert "claude-primary" not in pool._cooldowns


class TestPoolBindToolsPreservesCooldowns:
    def test_bind_tools_copies_active_cooldowns(self) -> None:
        """bind_tools on a pool with a cooled entry preserves that cooldown."""
        pool: ModelPool = _pool(primary_responses=["ok"], secondary_responses=["ok2"])
        pool._cooldowns["claude-primary"] = time.monotonic() + 9999
        new_pool: ModelPool = pool.bind_tools(tools=[])
        assert "claude-primary" in new_pool._cooldowns
        assert new_pool._cooldowns["claude-primary"] == pool._cooldowns["claude-primary"]
