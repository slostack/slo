"""Tests for ``src.agents.providers.model_pool`` (spec 28.a.3 / 37.a.2)."""
from __future__ import annotations

import time
from typing import Any, AsyncIterator, Optional

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict
from unittest.mock import MagicMock, patch

from src.agents.providers.credit_exhaustion_policy import (
    AllModelsExhaustedError,
    ProviderErrorKind,
)
from src.agents.providers.faux import FauxChatModel
from src.agents.providers.model_pool import (
    ModelPool,
    ModelPoolDAO,
    ModelPoolEntryDAO,
    RouteSwitchRecordDAO,
)
from src.auth.credential_dao import ProviderName


class _FakeCreditError(Exception):
    """Minimal exception with status_code for mock credit-exhaustion scenarios."""

    status_code: int = 402


class _StatusError(Exception):
    """Exception carrying an HTTP ``status_code`` for real-classifier tests."""

    def __init__(self, *, status_code: int) -> None:
        """Initialise with a status code.

        Args:
            status_code (int): The HTTP status code the classifier inspects.
        """
        super().__init__(f"HTTP {status_code}")
        self.status_code: int = status_code
        self.code: Optional[str] = None


class _RaisingChatModel(BaseChatModel):
    """Member whose generate/stream paths raise a fixed error before any output."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, *, error: Exception, **data: Any) -> None:
        """Store the error to raise on every call.

        Args:
            error (Exception): The exception raised by every generate/stream path.
            **data (Any): BaseChatModel passthrough.
        """
        super().__init__(**data)
        self._error: Exception = error

    @property
    def _llm_type(self) -> str:
        return "raising"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise self._error

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise self._error

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        raise self._error
        yield  # pragma: no cover — marks this coroutine an async generator

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_RaisingChatModel":
        return self


class _StreamingChatModel(BaseChatModel):
    """Member that streams scripted chunks, optionally failing after the first."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        *,
        chunks: list[str],
        fail_after_first: Optional[Exception] = None,
        **data: Any,
    ) -> None:
        """Store the chunk script and optional mid-stream failure.

        Args:
            chunks (list[str]): Text content streamed one chunk at a time.
            fail_after_first (Optional[Exception]): When set, raised after the
                first chunk is yielded (to exercise the no-mid-stream-switch rule).
            **data (Any): BaseChatModel passthrough.
        """
        super().__init__(**data)
        self._chunks: list[str] = chunks
        self._fail_after_first: Optional[Exception] = fail_after_first

    @property
    def _llm_type(self) -> str:
        return "streaming"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="".join(self._chunks)))]
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="".join(self._chunks)))]
        )

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for index, text in enumerate(self._chunks):
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))
            if index == 0 and self._fail_after_first is not None:
                raise self._fail_after_first

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_StreamingChatModel":
        return self


def _switch_pool(
    *,
    primary: BaseChatModel,
    secondary: BaseChatModel,
    primary_provider: ProviderName = ProviderName.OPENAI,
    secondary_provider: ProviderName = ProviderName.ANTHROPIC,
) -> ModelPool:
    """Build a two-member pool (gpt-5.4 primary, claude-sonnet-4-6 secondary).

    Args:
        primary (BaseChatModel): Priority-0 member.
        secondary (BaseChatModel): Priority-1 member.
        primary_provider (ProviderName): Provider for the primary entry.
        secondary_provider (ProviderName): Provider for the secondary entry.

    Returns:
        ModelPool: Pool with real-classifier routing (no patched classify).
    """
    dao: ModelPoolDAO = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=primary_provider, priority=0),
            ModelPoolEntryDAO(
                model_name="claude-sonnet-4-6", provider=secondary_provider, priority=1
            ),
        ]
    )
    return ModelPool(
        pool_dao=dao,
        models={"gpt-5.4": primary, "claude-sonnet-4-6": secondary},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(*, content: str = "ok") -> ChatResult:
    """Build a minimal ChatResult for scripted responses.

    Args:
        content (str): Text content of the assistant response.

    Returns:
        ChatResult: Minimal result wrapping an AIMessage.
    """
    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


def _pool_with_two_entries(
    *,
    first_raises: Exception | None = None,
    second_content: str = "from-second",
) -> ModelPool:
    """Build a pool with two faux mock entries.

    Args:
        first_raises (Exception | None): If provided, the primary raises this exception.
        second_content (str): Content string returned by the secondary model.

    Returns:
        ModelPool: Configured two-entry pool.
    """
    primary: MagicMock = MagicMock()
    if first_raises:
        primary._generate.side_effect = first_raises
    else:
        primary._generate.return_value = _make_result(content="from-primary")

    secondary: MagicMock = MagicMock()
    secondary._generate.return_value = _make_result(content=second_content)

    dao: ModelPoolDAO = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(
                model_name="claude-primary",
                provider=ProviderName.ANTHROPIC,
                priority=0,
                cooldown_seconds=300,
            ),
            ModelPoolEntryDAO(
                model_name="gpt-fallback",
                provider=ProviderName.OPENAI,
                priority=1,
                cooldown_seconds=300,
            ),
        ]
    )
    return ModelPool(
        pool_dao=dao,
        models={"claude-primary": primary, "gpt-fallback": secondary},
    )


_MESSAGES: list[BaseMessage] = [HumanMessage(content="hello")]


# ---------------------------------------------------------------------------
# _select_model
# ---------------------------------------------------------------------------


class TestModelPoolSelectModel:
    def test_selects_highest_priority_entry(self) -> None:
        """The pool selects the entry with the lowest priority number first."""
        pool: ModelPool = _pool_with_two_entries()
        name, _, _ = pool._select_model()
        assert name == "claude-primary"

    def test_skips_cooled_entry(self) -> None:
        """A cooled primary is skipped; secondary is selected instead."""
        pool: ModelPool = _pool_with_two_entries()
        pool._cooldowns["claude-primary"] = time.monotonic() + 9999
        name, _, _ = pool._select_model()
        assert name == "gpt-fallback"

    def test_raises_when_all_cooled(self) -> None:
        """AllModelsExhaustedError when every entry is in cooldown."""
        pool: ModelPool = _pool_with_two_entries()
        pool._cooldowns["claude-primary"] = time.monotonic() + 9999
        pool._cooldowns["gpt-fallback"] = time.monotonic() + 9999
        with pytest.raises(AllModelsExhaustedError):
            pool._select_model()


# ---------------------------------------------------------------------------
# _generate
# ---------------------------------------------------------------------------


class TestModelPoolGenerate:
    def test_routes_to_primary_on_success(self) -> None:
        """Successful primary response is returned directly."""
        pool: ModelPool = _pool_with_two_entries()
        result: ChatResult = pool._generate(messages=_MESSAGES)
        assert result.generations[0].message.content == "from-primary"

    def test_falls_through_to_secondary_on_credit_exhaustion(self) -> None:
        """Credit exhaustion on primary routes the call to secondary."""
        with patch(
            "src.agents.providers.model_pool.CreditExhaustionPolicy.classify",
            return_value=ProviderErrorKind.CREDIT_EXHAUSTED,
        ):
            pool: ModelPool = _pool_with_two_entries(first_raises=_FakeCreditError("credit"))
            result: ChatResult = pool._generate(messages=_MESSAGES)

        assert result.generations[0].message.content == "from-second"

    def test_does_not_fall_through_on_non_credit_error(self) -> None:
        """A non-credit error propagates immediately; secondary never called."""
        with patch(
            "src.agents.providers.model_pool.CreditExhaustionPolicy.classify",
            return_value=ProviderErrorKind.OTHER,
        ):
            pool: ModelPool = _pool_with_two_entries(first_raises=RuntimeError("network timeout"))
            with pytest.raises(RuntimeError, match="network timeout"):
                pool._generate(messages=_MESSAGES)

    def test_raises_all_models_exhausted_when_both_cooled(self) -> None:
        """AllModelsExhaustedError when every entry is cooled before the call."""
        pool: ModelPool = _pool_with_two_entries()
        pool._cooldowns["claude-primary"] = time.monotonic() + 9999
        pool._cooldowns["gpt-fallback"] = time.monotonic() + 9999
        with pytest.raises(AllModelsExhaustedError):
            pool._generate(messages=_MESSAGES)


# ---------------------------------------------------------------------------
# bind_tools
# ---------------------------------------------------------------------------


class TestModelPoolBindTools:
    def test_bind_tools_returns_new_pool(self) -> None:
        """bind_tools returns a distinct ModelPool instance."""
        pool: ModelPool = _pool_with_two_entries()
        new_pool: ModelPool = pool.bind_tools(tools=[])
        assert new_pool is not pool

    def test_bind_tools_preserves_cooldowns(self) -> None:
        """Active cooldowns are copied into the new pool."""
        pool: ModelPool = _pool_with_two_entries()
        pool._cooldowns["claude-primary"] = time.monotonic() + 9999
        new_pool: ModelPool = pool.bind_tools(tools=[])
        assert "claude-primary" in new_pool._cooldowns

    def test_bind_tools_binds_each_inner_model(self) -> None:
        """bind_tools calls bind_tools on every inner model."""
        pool: ModelPool = _pool_with_two_entries()
        tools: list[MagicMock] = [MagicMock()]
        pool.bind_tools(tools=tools)
        pool._models["claude-primary"].bind_tools.assert_called_once()  # type: ignore[attr-defined]  # MagicMock
        pool._models["gpt-fallback"].bind_tools.assert_called_once()  # type: ignore[attr-defined]  # MagicMock


# ---------------------------------------------------------------------------
# active_model_name
# ---------------------------------------------------------------------------


class TestModelPoolActiveModelName:
    def test_active_model_name_returns_primary_when_no_cooldowns(self) -> None:
        """active_model_name is the primary entry when nothing is cooled."""
        pool: ModelPool = _pool_with_two_entries()
        assert pool.active_model_name == "claude-primary"

    def test_active_model_name_returns_secondary_when_primary_cooled(self) -> None:
        """active_model_name is the secondary when primary is in cooldown."""
        pool: ModelPool = _pool_with_two_entries()
        pool._cooldowns["claude-primary"] = time.monotonic() + 9999
        assert pool.active_model_name == "gpt-fallback"

    def test_active_model_name_returns_first_entry_when_all_cooled(self) -> None:
        """active_model_name falls back to first entry name when all are cooled."""
        pool: ModelPool = _pool_with_two_entries()
        pool._cooldowns["claude-primary"] = time.monotonic() + 9999
        pool._cooldowns["gpt-fallback"] = time.monotonic() + 9999
        assert pool.active_model_name == "claude-primary"


# ---------------------------------------------------------------------------
# ModelPoolDAO validation
# ---------------------------------------------------------------------------


class TestModelPoolDAOValidation:
    def test_requires_at_least_two_entries(self) -> None:
        """A single-entry config raises a validation error."""
        with pytest.raises(Exception):
            ModelPoolDAO(
                entries=[
                    ModelPoolEntryDAO(
                        model_name="claude-sonnet-4-6",
                        provider=ProviderName.ANTHROPIC,
                        priority=0,
                    )
                ]
            )

    def test_accepts_two_or_more_entries(self) -> None:
        """A two-entry config is valid."""
        dao: ModelPoolDAO = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(
                    model_name="claude-sonnet-4-6",
                    provider=ProviderName.ANTHROPIC,
                    priority=0,
                ),
                ModelPoolEntryDAO(
                    model_name="gpt-4o",
                    provider=ProviderName.OPENAI,
                    priority=1,
                ),
            ]
        )
        assert len(dao.entries) == 2


_HI_MSGS: list[BaseMessage] = [HumanMessage(content="hi")]


# ---------------------------------------------------------------------------
# _agenerate switching (37.a.2)
# ---------------------------------------------------------------------------


class TestModelPoolAgenerateSwitching:
    async def test_switches_to_next_member_on_rate_limit(self) -> None:
        """429 on primary → cooled → secondary answers."""
        pool: ModelPool = _switch_pool(
            primary=_RaisingChatModel(error=_StatusError(status_code=429)),
            secondary=FauxChatModel(responses=[AIMessage(content="from-secondary")]),
        )
        result: ChatResult = await pool._agenerate(messages=_HI_MSGS)
        assert result.generations[0].message.content == "from-secondary"
        assert "gpt-5.4" in pool._cooldowns

    async def test_switches_on_transient_provider_failure(self) -> None:
        """503 on primary → switch to secondary."""
        pool: ModelPool = _switch_pool(
            primary=_RaisingChatModel(error=_StatusError(status_code=503)),
            secondary=FauxChatModel(responses=[AIMessage(content="from-secondary")]),
        )
        result: ChatResult = await pool._agenerate(messages=_HI_MSGS)
        assert result.generations[0].message.content == "from-secondary"
        assert "gpt-5.4" in pool._cooldowns

    async def test_propagates_other_without_switching(self) -> None:
        """A 400 (OTHER) re-raises and does not cool the member."""
        pool: ModelPool = _switch_pool(
            primary=_RaisingChatModel(error=_StatusError(status_code=400)),
            secondary=FauxChatModel(responses=[AIMessage(content="never")]),
        )
        with pytest.raises(_StatusError):
            await pool._agenerate(messages=_HI_MSGS)
        assert "gpt-5.4" not in pool._cooldowns

    async def test_raises_all_models_exhausted_when_every_member_cooling(self) -> None:
        """Both members 429 → AllModelsExhaustedError surfaces."""
        pool: ModelPool = _switch_pool(
            primary=_RaisingChatModel(error=_StatusError(status_code=429)),
            secondary=_RaisingChatModel(error=_StatusError(status_code=429)),
            secondary_provider=ProviderName.OPENAI,
        )
        with pytest.raises(AllModelsExhaustedError):
            await pool._agenerate(messages=_HI_MSGS)


# ---------------------------------------------------------------------------
# _astream switching (37.a.2)
# ---------------------------------------------------------------------------


class TestModelPoolAstreamSwitching:
    async def test_streams_chunks_from_selected_member(self) -> None:
        """Token chunks reach the caller (no thread-wrapped downgrade)."""
        pool: ModelPool = _switch_pool(
            primary=_StreamingChatModel(chunks=["hello", " world"]),
            secondary=FauxChatModel(responses=[AIMessage(content="unused")]),
        )
        chunks = [c async for c in pool._astream(messages=_HI_MSGS)]
        assert "".join(str(c.message.content) for c in chunks) == "hello world"

    async def test_switches_before_first_chunk_on_rate_limit(self) -> None:
        """429 before any chunk on primary → secondary streams."""
        pool: ModelPool = _switch_pool(
            primary=_RaisingChatModel(error=_StatusError(status_code=429)),
            secondary=_StreamingChatModel(chunks=["from-secondary"]),
        )
        chunks = [c async for c in pool._astream(messages=_HI_MSGS)]
        assert "".join(str(c.message.content) for c in chunks) == "from-secondary"
        assert "gpt-5.4" in pool._cooldowns

    async def test_does_not_switch_after_first_chunk(self) -> None:
        """A failure after the first chunk re-raises (no mid-stream switch)."""
        pool: ModelPool = _switch_pool(
            primary=_StreamingChatModel(
                chunks=["partial"], fail_after_first=_StatusError(status_code=429)
            ),
            secondary=_StreamingChatModel(chunks=["never"]),
        )
        seen: list[str] = []
        with pytest.raises(_StatusError):
            async for chunk in pool._astream(messages=_HI_MSGS):
                seen.append(str(chunk.message.content))
        assert seen == ["partial"]
        assert "gpt-5.4" not in pool._cooldowns  # not switched


# ---------------------------------------------------------------------------
# Introspection surface (37.a.2)
# ---------------------------------------------------------------------------


class TestModelPoolIntrospection:
    def test_llm_returns_self(self) -> None:
        """The pool's .llm slot returns itself (drop-in build product)."""
        pool: ModelPool = _switch_pool(
            primary=FauxChatModel(responses=[]),
            secondary=FauxChatModel(responses=[]),
        )
        assert pool.llm is pool

    def test_active_llm_returns_selected_member(self) -> None:
        """active_llm resolves to the currently-selected member instance."""
        pool: ModelPool = _switch_pool(
            primary=FauxChatModel(responses=[]),
            secondary=FauxChatModel(responses=[]),
        )
        assert pool.active_llm is pool._models[pool.active_model_name]

    def test_active_provider_matches_selected_member(self) -> None:
        """active_provider is the primary's provider when nothing is cooled."""
        pool: ModelPool = _switch_pool(
            primary=FauxChatModel(responses=[]),
            secondary=FauxChatModel(responses=[]),
        )
        assert pool.active_provider is ProviderName.OPENAI

    def test_supports_explicit_caching_true_only_for_anthropic_active_route(self) -> None:
        """Caching flag follows the active route; True once the Anthropic member is active."""
        pool: ModelPool = _switch_pool(
            primary=FauxChatModel(responses=[]),
            secondary=FauxChatModel(responses=[]),
        )
        assert pool.supports_explicit_caching is False
        pool._cooldowns["gpt-5.4"] = time.monotonic() + 60
        assert pool.supports_explicit_caching is True


# ---------------------------------------------------------------------------
# Route-switch audit log (37.a.2)
# ---------------------------------------------------------------------------


class TestModelPoolRouteSwitchAudit:
    async def test_records_one_switch_per_cooled_member(self) -> None:
        """One audit record is appended per route switch, with from/kind set."""
        pool: ModelPool = _switch_pool(
            primary=_RaisingChatModel(error=_StatusError(status_code=429)),
            secondary=FauxChatModel(responses=[AIMessage(content="ok")]),
        )
        await pool._agenerate(messages=_HI_MSGS)
        records: list[RouteSwitchRecordDAO] = pool.drain_route_switch_log()
        assert len(records) == 1
        assert records[0].from_model_name == "gpt-5.4"
        assert records[0].to_model_name == "claude-sonnet-4-6"
        assert records[0].kind == "RATE_LIMITED"

    async def test_drain_clears_the_log(self) -> None:
        """Draining the audit log empties it for the next turn."""
        pool: ModelPool = _switch_pool(
            primary=_RaisingChatModel(error=_StatusError(status_code=429)),
            secondary=FauxChatModel(responses=[AIMessage(content="ok")]),
        )
        await pool._agenerate(messages=_HI_MSGS)
        pool.drain_route_switch_log()
        assert pool.drain_route_switch_log() == []


# ---------------------------------------------------------------------------
# bind_tools preserves the new surface (37.a.2)
# ---------------------------------------------------------------------------


class TestModelPoolBindToolsPreservesSurface:
    def test_bound_pool_keeps_cooldowns_and_adapter(self) -> None:
        """bind_tools copies cooldowns and forwards the request adapter."""
        pool: ModelPool = _switch_pool(
            primary=FauxChatModel(responses=[]),
            secondary=FauxChatModel(responses=[]),
        )
        pool._cooldowns["gpt-5.4"] = time.monotonic() + 60
        bound: ModelPool = pool.bind_tools(tools=[])
        assert "gpt-5.4" in bound._cooldowns
        assert bound._request_adapter is pool._request_adapter
