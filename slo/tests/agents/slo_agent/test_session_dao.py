"""Tests for ``SessionConfigDAO`` (sub-spec 02.a.1)."""

from __future__ import annotations

from pathlib import Path

from src.agents.hooks import Hook, ShouldStopAfterTurnHookContextDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO


class TestSessionConfigDAOResolvedStopHook:
    """``SessionConfigDAO.resolved_stop_hook`` decision branches."""

    def test_session_config_resolved_stop_hook_returns_supplied_hook(self, tmp_path: Path) -> None:
        """Custom hook supplied → ``resolved_stop_hook()`` returns it."""

        async def custom_hook(
            context: ShouldStopAfterTurnHookContextDAO,
        ) -> bool:
            return True

        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            should_stop_after_turn_hook=custom_hook,
        )

        assert config.resolved_stop_hook() is custom_hook

    def test_session_config_resolved_stop_hook_falls_back_to_default(self, tmp_path: Path) -> None:
        """No hook supplied → fallback is ``Hook.should_stop_after_turn_hook``."""
        config: SessionConfigDAO = SessionConfigDAO(workdir=tmp_path)

        # Bound classmethods are recreated on every attribute access, so
        # ``is`` fails even when both sides refer to the same underlying
        # function. Compare by equality, which uses ``__func__`` and
        # ``__self__`` under the hood.
        assert config.resolved_stop_hook() == Hook.should_stop_after_turn_hook


class TestSessionConfigDAOAppendSystemPrompt:
    """``append_system_prompt`` field (sub-spec 03.a)."""

    def test_append_system_prompt_defaults_to_none(self, tmp_path: Path) -> None:
        """``append_system_prompt`` is ``None`` when not supplied."""
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        config: SessionConfigDAO = SessionConfigDAO(workdir=tmp_path)

        assert config.append_system_prompt is None

    def test_append_system_prompt_accepted(self, tmp_path: Path) -> None:
        """An explicit ``append_system_prompt`` value is stored correctly."""
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            append_system_prompt="extra instructions",
        )

        assert config.append_system_prompt == "extra instructions"


# ---------------------------------------------------------------------------
# model_name aligned to pool primary (review fix #5)
# ---------------------------------------------------------------------------

from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO  # noqa: E402
from src.auth.credential_dao import ProviderName  # noqa: E402


class TestSessionConfigDAOPoolPrimaryAlignment:
    """When a pool is configured, ``model_name`` must equal the pool primary."""

    def test_model_name_aligned_to_pool_primary(self, tmp_path: Path) -> None:
        """A mismatched model_name is overridden to the first pool entry."""
        dao = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(
                    model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=0
                ),
                ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=1),
            ]
        )
        config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", model_pool_dao=dao)
        assert config.model_name == "claude-sonnet-4-6"

    def test_model_name_unchanged_without_pool(self, tmp_path: Path) -> None:
        """Without a pool, model_name is left as supplied."""
        config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4")
        assert config.model_name == "gpt-5.4"
