"""Unit tests for ``SlashRouter`` (sub-spec 02.a.2 §8.1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tui.slash_router import SlashCommandResultDAO, SlashRouter


def _build_session_stub(*, workdir: Path = Path("/tmp/slo-fake")) -> MagicMock:
    """Build a ``SloAgentSession`` stub with the router-facing runtime surface.

    Args:
        workdir (Path, optional): The workdir the stub exposes. Defaults
            to ``Path("/tmp/slo-fake")``.

    Returns:
        MagicMock: A stub exposing the workdir plus the command methods
            and runtime-state properties the router reads.
    """
    session: MagicMock = MagicMock()
    session.workdir = workdir
    session.active_model_name = "claude-sonnet-4-6"
    session.active_reasoning_level = "high"
    session.is_running = False
    session.abort = MagicMock()
    session.steer = MagicMock()
    session.switch_model = MagicMock()
    session.switch_reasoning_level = MagicMock(return_value="high")
    return session


class TestSlashRouterDispatch:
    """One test per slash command, plus the unknown-command case."""

    @pytest.mark.asyncio
    async def test_help_renders_help_block(self) -> None:
        """``/help`` returns the help text; aliases ``/h`` and ``/?`` match."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/help",
            session=session,
        )
        result_h: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/h",
            session=session,
        )
        result_q: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/?",
            session=session,
        )

        assert result.rendered == SlashRouter._help_text()
        assert result_h.rendered == SlashRouter._help_text()
        assert result_q.rendered == SlashRouter._help_text()

    @pytest.mark.asyncio
    async def test_clear_returns_should_clear(self) -> None:
        """``/clear`` returns ``should_clear=True`` and no rendered line."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/clear",
            session=session,
        )

        assert result.should_clear is True
        assert result.rendered is None

    @pytest.mark.asyncio
    async def test_exit_returns_should_exit(self) -> None:
        """``/exit`` returns ``should_exit=True``; aliases ``/quit`` and ``/q`` match."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/exit",
            session=session,
        )
        result_quit: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/quit",
            session=session,
        )
        result_q: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/q",
            session=session,
        )

        assert result.should_exit is True
        assert result_quit.should_exit is True
        assert result_q.should_exit is True

    @pytest.mark.asyncio
    async def test_cwd_renders_workdir(self) -> None:
        """``/cwd`` returns ``f"cwd: {session.workdir}"``."""
        workdir: Path = Path("/tmp/slo-fake-cwd")
        session: MagicMock = _build_session_stub(workdir=workdir)

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/cwd",
            session=session,
        )

        assert result.rendered == f"cwd: {workdir}"

    @pytest.mark.asyncio
    async def test_abort_calls_session_abort(self) -> None:
        """``/abort`` calls ``session.abort()`` exactly once and renders the marker."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/abort",
            session=session,
        )

        session.abort.assert_called_once_with()
        assert result.rendered == "(aborting…)"
        assert result.abort_run is True

    @pytest.mark.asyncio
    async def test_steer_with_args_calls_session_steer(self) -> None:
        """``/steer foo bar`` calls ``session.steer(message="foo bar")``."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/steer foo bar",
            session=session,
        )

        session.steer.assert_called_once_with(message="foo bar")
        assert result.steer_pending_message == "foo bar"

    @pytest.mark.asyncio
    async def test_steer_without_args_rejects(self) -> None:
        """Bare ``/steer`` renders the usage line and does not call ``steer``."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/steer",
            session=session,
        )

        assert result.rendered == "usage: /steer <message>"
        session.steer.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_without_args_returns_replace_session_intent(self) -> None:
        """Bare `/new` requests session replacement without an initial name."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/new",
            session=session,
        )

        assert result.replace_session is True
        assert result.requested_session_name is None

    @pytest.mark.asyncio
    async def test_new_with_args_returns_replace_session_intent(self) -> None:
        """`/new some name` requests replacement with the requested name."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/new some name",
            session=session,
        )

        assert result.replace_session is True
        assert result.requested_session_name == "some name"

    @pytest.mark.asyncio
    async def test_new_while_running_returns_actionable_rejection(self) -> None:
        """`/new` while a prompt is running is rejected."""
        session: MagicMock = _build_session_stub()
        session.is_running = True

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/new",
            session=session,
        )

        assert result.rendered == "cannot start a new session while a prompt is in flight; run /abort first"

    @pytest.mark.asyncio
    async def test_rename_with_args_returns_rename_intent(self) -> None:
        """`/rename foo` returns declarative rename intent."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/rename foo",
            session=session,
        )

        assert result.rename_current_session_to == "foo"
        assert result.refresh_title is True

    @pytest.mark.asyncio
    async def test_rename_without_args_rejects(self) -> None:
        """Bare `/rename` renders the usage line."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/rename",
            session=session,
        )

        assert result.rendered == "usage: /rename <session name>"

    @pytest.mark.asyncio
    async def test_unknown_command_renders_unknown_message(self) -> None:
        """Unknown ``/wibble`` renders ``unknown command: /wibble``."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/wibble",
            session=session,
        )

        assert result.rendered == "unknown command: /wibble"


class TestSlashModelHandler:
    """`/model` lists and switches supported models."""

    @pytest.mark.asyncio
    async def test_model_without_args_lists_grouped_models(self) -> None:
        """Bare `/model` renders the grouped supported-model catalog."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.is_running = False

        with patch(
            "src.tui.slash_router.CredentialResolver.resolve",
            side_effect=lambda *, provider: object(),
        ):
            result: SlashCommandResultDAO = await SlashRouter.dispatch(
                line="/model",
                session=session,
            )

        assert "Anthropic" in (result.rendered or "")
        assert "Openai" in (result.rendered or "")
        assert "gpt-5.4" in (result.rendered or "")
        assert "gpt-5-codex" in (result.rendered or "")
        assert "gpt-5.3-codex" in (result.rendered or "")
        assert "gpt-5.2-codex" in (result.rendered or "")
        assert "gpt-5.3-codex-spark" in (result.rendered or "")

    @pytest.mark.asyncio
    async def test_model_supported_name_switches_session_model(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`/model claude-sonnet-4-6` switches when credentials exist and saves preference."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.is_running = False
        session.switch_model = MagicMock()

        with patch(
            "src.tui.slash_router.CredentialResolver.resolve",
            side_effect=lambda *, provider: object(),
        ):
            result: SlashCommandResultDAO = await SlashRouter.dispatch(
                line="/model claude-sonnet-4-6",
                session=session,
            )

        session.switch_model.assert_called_once_with(model_name="claude-sonnet-4-6")
        assert "claude-sonnet-4-6" in (result.rendered or "")
        assert "Preference saved" in (result.rendered or "")

    @pytest.mark.asyncio
    async def test_model_unknown_name_rejects(self) -> None:
        """Unknown model names render an actionable error."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.is_running = False

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/model mistral-large",
            session=session,
        )

        assert result.rendered == "unknown model: mistral-large"

    @pytest.mark.asyncio
    async def test_model_missing_credentials_rejects(self) -> None:
        """Supported model without provider creds tells the user to run `/auth`."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.is_running = False

        with patch(
            "src.tui.slash_router.CredentialResolver.resolve",
            return_value=None,
        ):
            result: SlashCommandResultDAO = await SlashRouter.dispatch(
                line="/model claude-sonnet-4-6",
                session=session,
            )

        assert result.rendered == "model 'claude-sonnet-4-6' requires /auth for anthropic"

    @pytest.mark.asyncio
    async def test_model_in_flight_rejects_switch(self) -> None:
        """Switching while a prompt is running is rejected."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.is_running = True

        with patch(
            "src.tui.slash_router.CredentialResolver.resolve",
            side_effect=lambda *, provider: object(),
        ):
            result: SlashCommandResultDAO = await SlashRouter.dispatch(
                line="/model claude-sonnet-4-6",
                session=session,
            )

        assert result.rendered == "cannot switch models while a prompt is in flight"

    @pytest.mark.asyncio
    async def test_help_text_mentions_model(self) -> None:
        """`/help` documents the new `/model` command."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/help",
            session=session,
        )

        assert "/model" in (result.rendered or "")
        assert "/new [session name]" in (result.rendered or "")
        assert "/rename <session name>" in (result.rendered or "")


class TestSlashReasoningHandler:
    """`/reasoning` lists and switches supported levels."""

    @pytest.mark.asyncio
    async def test_reasoning_without_args_lists_current_and_supported_levels(self) -> None:
        """Bare `/reasoning` renders the active level and supported levels."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.active_reasoning_level = "high"

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning",
            session=session,
        )

        assert "model: gpt-5.4" in (result.rendered or "")
        assert "reasoning: high" in (result.rendered or "")
        assert "supported: off, minimal, low, medium, high, xhigh" in (result.rendered or "")

    @pytest.mark.asyncio
    async def test_reasoning_off_switches_session_reasoning(self) -> None:
        """`/reasoning off` switches the session and requests a title refresh."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.active_reasoning_level = "high"

        def _switch_reasoning_level(*, reasoning_level: str) -> str:
            session.active_reasoning_level = reasoning_level
            return reasoning_level

        session.switch_reasoning_level = MagicMock(side_effect=_switch_reasoning_level)

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning off",
            session=session,
        )

        session.switch_reasoning_level.assert_called_once_with(reasoning_level="off")
        assert result.rendered == "reasoning changed high -> off"
        assert result.refresh_title is True

    @pytest.mark.asyncio
    async def test_reasoning_on_restores_default_level(self) -> None:
        """`/reasoning on` resolves to the model's default reasoning-on level."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "off"

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning on",
            session=session,
        )

        session.switch_reasoning_level.assert_called_once_with(reasoning_level="high")
        assert result.rendered == "reasoning changed off -> high"

    @pytest.mark.asyncio
    async def test_reasoning_max_maps_to_highest_supported_level(self) -> None:
        """`/reasoning max` resolves to the model's strongest supported tier."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.active_reasoning_level = "high"
        session.switch_reasoning_level = MagicMock(return_value="xhigh")

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning max",
            session=session,
        )

        session.switch_reasoning_level.assert_called_once_with(reasoning_level="xhigh")
        assert result.rendered == "reasoning changed high -> xhigh"

    @pytest.mark.asyncio
    async def test_reasoning_on_rejects_non_reasoning_models_with_clear_message(self) -> None:
        """`/reasoning on` explains unsupported models instead of echoing `off -> off`."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-4o"
        session.active_reasoning_level = "off"

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning on",
            session=session,
        )

        assert result.rendered == "reasoning unsupported for gpt-4o"
        session.switch_reasoning_level.assert_not_called()

    @pytest.mark.asyncio
    async def test_reasoning_same_level_reports_already_active(self) -> None:
        """Re-requesting the active level renders an `already` confirmation."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.active_reasoning_level = "high"

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning high",
            session=session,
        )

        assert result.rendered == "reasoning already high"
        session.switch_reasoning_level.assert_not_called()

    @pytest.mark.asyncio
    async def test_reasoning_invalid_token_returns_usage_error(self) -> None:
        """Unknown reasoning tokens render an actionable usage line."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning turbo",
            session=session,
        )

        assert "unknown reasoning level: turbo" in (result.rendered or "")
        assert "usage: /reasoning <on|off|minimal|low|medium|high|xhigh|max>" in (result.rendered or "")

    @pytest.mark.asyncio
    async def test_reasoning_in_flight_rejects_switch(self) -> None:
        """Switching reasoning while a prompt is running is rejected."""
        session: MagicMock = _build_session_stub()
        session.is_running = True

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning high",
            session=session,
        )

        assert result.rendered == "cannot switch reasoning while a prompt is in flight"

    @pytest.mark.asyncio
    async def test_reasoning_clamped_change_renders_explicit_feedback(self) -> None:
        """Clamped reasoning changes tell the user what actually happened."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "medium"
        session.switch_reasoning_level = MagicMock(return_value="high")

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning xhigh",
            session=session,
        )

        assert result.rendered == (
            "reasoning changed medium -> high (requested xhigh; clamped for claude-sonnet-4-6)"
        )

    @pytest.mark.asyncio
    async def test_help_text_mentions_reasoning(self) -> None:
        """`/help` documents the `/reasoning` command."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/help",
            session=session,
        )

        assert "/reasoning" in (result.rendered or "")


class TestSlashAuthHandler:
    """``/auth`` (02.b.6) sets ``open_auth_modal`` and renders nothing."""

    @pytest.mark.asyncio
    async def test_auth_returns_open_auth_modal_true(self) -> None:
        """The handler does not render text; it sets the flag."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/auth",
            session=session,
        )

        assert result.open_auth_modal is True
        assert result.rendered is None
        assert result.should_clear is False
        assert result.should_exit is False

    @pytest.mark.asyncio
    async def test_help_text_mentions_auth(self) -> None:
        """``/help`` documents the new command."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/help",
            session=session,
        )

        assert "/auth" in (result.rendered or "")


class TestSlashThemeHandler:
    """Tests for the ``/theme`` toggle command."""

    @pytest.mark.asyncio
    async def test_theme_returns_toggle_theme_true(self) -> None:
        """``/theme`` returns ``toggle_theme=True`` and nothing else."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/theme",
            session=session,
        )

        assert result.toggle_theme is True
        assert result.rendered is None
        assert result.should_exit is False
        assert result.should_clear is False

    @pytest.mark.asyncio
    async def test_help_text_mentions_theme(self) -> None:
        """``/help`` documents the ``/theme`` command."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/help",
            session=session,
        )

        assert "/theme" in (result.rendered or "")


class TestSlashPreferencesHandler:
    """``/preferences`` command — display and clear."""

    @pytest.mark.asyncio
    async def test_preferences_shows_none_when_no_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no preferences file, /preferences shows (none) for both fields."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "absent.json"))
        session: MagicMock = _build_session_stub()

        result = await SlashRouter.dispatch(line="/preferences", session=session)

        assert result.rendered is not None
        assert "(none" in result.rendered

    @pytest.mark.asyncio
    async def test_preferences_shows_saved_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With saved preferences, /preferences shows the saved model and reasoning."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
        from src.agents.slo_agent.preferences.service import UserPreferencesStore
        UserPreferencesStore.upsert(model_name="claude-sonnet-4-5", reasoning_level="high")
        session: MagicMock = _build_session_stub()

        result = await SlashRouter.dispatch(line="/preferences", session=session)

        assert result.rendered is not None
        assert "claude-sonnet-4-5" in result.rendered
        assert "high" in result.rendered

    @pytest.mark.asyncio
    async def test_preferences_clear_deletes_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``/preferences clear`` deletes the file and confirms."""
        path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))
        from src.agents.slo_agent.preferences.service import UserPreferencesStore
        UserPreferencesStore.upsert(model_name="x")
        session: MagicMock = _build_session_stub()

        result = await SlashRouter.dispatch(line="/preferences clear", session=session)

        assert not path.exists()
        assert "cleared" in (result.rendered or "").lower()

    @pytest.mark.asyncio
    async def test_preferences_clear_when_no_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``/preferences clear`` with no file reports no-op gracefully."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "absent.json"))
        session: MagicMock = _build_session_stub()

        result = await SlashRouter.dispatch(line="/preferences clear", session=session)

        assert result.rendered is not None
        assert "no saved" in (result.rendered or "").lower()


class TestSlashModelPreferencePersistence:
    """``/model`` and ``/reasoning`` write back to the preferences store."""

    @pytest.mark.asyncio
    async def test_switch_model_writes_preferences(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A successful /model switch persists to the preferences file."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.is_running = False
        session.switch_model = MagicMock()

        with patch(
            "src.tui.slash_router.CredentialResolver.resolve",
            side_effect=lambda *, provider: object(),
        ):
            await SlashRouter.dispatch(line="/model claude-sonnet-4-6", session=session)

        from src.agents.slo_agent.preferences.service import UserPreferencesStore
        prefs = UserPreferencesStore.load()
        assert prefs.default_model_name == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_switch_reasoning_writes_preferences(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A successful /reasoning switch persists to the preferences file."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
        session: MagicMock = _build_session_stub()
        session.active_model_name = "claude-sonnet-4-6"
        session.active_reasoning_level = "off"
        session.is_running = False
        session.switch_reasoning_level = MagicMock(return_value="high")

        await SlashRouter.dispatch(line="/reasoning high", session=session)

        from src.agents.slo_agent.preferences.service import UserPreferencesStore
        prefs = UserPreferencesStore.load()
        assert prefs.default_reasoning_level == "high"
