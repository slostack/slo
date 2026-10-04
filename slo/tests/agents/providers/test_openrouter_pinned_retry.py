"""Offline pinned-policy pool contracts with the real classifier."""

from unittest.mock import patch

from langchain_core.messages import AIMessage

from src.agents.base import LLMFactory
from src.agents.providers.faux import FauxChatModel
from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
from src.auth.credential_dao import ProviderName
from src.integrations.openrouter.exceptions import OpenRouterAPIError
from tests.agents.providers.test_model_pool import _RaisingChatModel
from tests.agents.providers.test_openrouter_capability_recovery import _MODEL, _snapshot


async def test_factory_pool_clone_caps_retry_after_with_pinned_profile() -> None:
    """A tool-bound pool keeps its build snapshot rather than reloading global limits."""
    snapshot = _snapshot()
    entry = snapshot.entries[_MODEL]
    entry = entry.model_copy(
        update={
            "runtime_profile": entry.runtime_profile.model_copy(update={"local_retry_wait_cap_seconds": 7})
        }
    )
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, _MODEL: entry}})
    pool_dao = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name=_MODEL, provider=ProviderName.OPENROUTER, priority=0),
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=1),
        ]
    )
    failing = _RaisingChatModel(error=OpenRouterAPIError(status_code=429, retry_after_seconds=999))
    fallback = FauxChatModel(responses=[AIMessage(content="ok")])
    from src.agents.base import LLMBuildResult

    with patch(
        "src.agents.base.LLMFactory.create",
        side_effect=[
            LLMBuildResult(llm=failing, supports_explicit_caching=False),
            LLMBuildResult(llm=fallback, supports_explicit_caching=False),
        ],
    ):
        pool = LLMFactory.create_pool(pool_dao=pool_dao, snapshot=snapshot).bind_tools(tools=[])
    with patch("src.agents.providers.model_pool.time.monotonic", return_value=100.0):
        result = await pool.ainvoke(input="hello")
    assert result.content == "ok"
    assert pool._cooldowns[_MODEL] == 107.0
