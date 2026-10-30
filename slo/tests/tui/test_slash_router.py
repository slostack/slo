"""Unit tests for ``SlashRouter`` (sub-spec 02.a.2 §8.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tui.slash_router import SlashCommandResultDAO, SlashRouter
from src.tui.workflows.dao import WorkflowListVisibilityRequestDAO


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
    session.catalog_snapshot = None
    session.workdir = workdir
    session.active_model_name = "claude-sonnet-4-6"
    session.active_reasoning_level = "high"
    session.is_running = False
    session.abort = MagicMock()
    session.steer = MagicMock()
    session.switch_model = MagicMock()
    session.prepare_model_selection = AsyncMock()
    session.refresh_model_catalog = AsyncMock()
    session.switch_reasoning_level = MagicMock(return_value="high")
    return session


@pytest.mark.parametrize("history", [False, True])
@pytest.mark.parametrize("busy", [False, True])
async def test_visibility_grammar_in_busy_and_history_states(
    tmp_path: Path, history: bool, busy: bool
) -> None:
    """Visibility grammar needs neither inference idleness nor a history root."""

    class VisibilitySession:
        """Expose only the state needed for local routing; all execution is absent."""

        is_running: bool = busy
        history_root: Optional[Path] = tmp_path / "history" if history else None

    session = VisibilitySession()
    for line, action, target in (
        ("/workflows tui dismiss", "dismiss", None),
        ("/wf\ttui\tdismiss\tparent", "dismiss", "parent"),
        ("/workflows  tui  show  ", "show", None),
        ("/wf\ttui\tshow", "show", None),
    ):
        result = await SlashRouter.dispatch(line=line, session=session)
        assert result.tui_visibility == WorkflowListVisibilityRequestDAO(action=action, target_id=target)
        assert result.rendered == ""
    for line in (
        "/workflows tui",
        "/workflows tui clear",
        "/wf tui show wf-a",
        "/wf tui dismiss a b",
        "/wf tui dismiss ../escape",
        "/wf tui dismiss [bold]",
    ):
        result = await SlashRouter.dispatch(line=line, session=session)
        assert result.tui_visibility is None
        assert result.rendered == _WORKFLOWS_USAGE
    assert not (tmp_path / "history").exists()


class TestSlashRouterModelPreparation:
    """Router delegation for session-owned catalog refresh and selection."""

    @pytest.mark.asyncio
    async def test_model_refresh_delegates_only_to_session_gateway(self) -> None:
        """``/model refresh`` invokes the one session-owned refresh owner once."""
        session: MagicMock = _build_session_stub()
        session.refresh_model_catalog = AsyncMock(return_value="OpenRouter catalog refreshed.")

        result: SlashCommandResultDAO = await SlashRouter.dispatch(line="/model refresh", session=session)

        session.refresh_model_catalog.assert_awaited_once_with()
        session.prepare_model_selection.assert_not_awaited()
        assert result.rendered == "OpenRouter catalog refreshed."

    @pytest.mark.asyncio
    async def test_model_selection_delegates_only_to_session_gateway(self) -> None:
        """``/model <id>`` leaves membership, credentials, and atomic commit to the session."""
        session: MagicMock = _build_session_stub()
        session.prepare_model_selection = AsyncMock(
            return_value="active model switched to openrouter:vendor/model. Preference saved."
        )

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/model openrouter:vendor/model",
            session=session,
        )

        session.prepare_model_selection.assert_awaited_once_with(model_name="openrouter:vendor/model")
        session.refresh_model_catalog.assert_not_awaited()
        session.switch_model.assert_not_called()
        assert result.refresh_title is True


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
    async def test_diff_with_path_returns_git_diff_intent(self) -> None:
        """A populated /diff command leaves path safety to the content service."""
        session: MagicMock = _build_session_stub()

        result = await SlashRouter.dispatch(line="/diff src/tui/app.py", session=session)

        assert result.git_diff_path == "src/tui/app.py"
        assert result.rendered is None

    @pytest.mark.asyncio
    async def test_diff_with_path_containing_spaces_preserves_argument_for_service_validation(self) -> None:
        """A free-text path remains intact so the content service owns validation and I/O."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/diff docs/file name.md",
            session=session,
        )

        assert result.git_diff_path == "docs/file name.md"
        assert result.rendered is None

    @pytest.mark.asyncio
    async def test_diff_without_path_returns_usage(self) -> None:
        """A blank /diff command opens no screen intent and explains its required argument."""
        session: MagicMock = _build_session_stub()

        result = await SlashRouter.dispatch(line="/diff   ", session=session)

        assert result.git_diff_path is None
        assert result.rendered == "/diff requires a file path. Usage: /diff <repository-relative-path>"

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

        assert "gpt-5.4" in (result.rendered or "")
        assert "type /model <search> to narrow" in (result.rendered or "")
        assert len((result.rendered or "").splitlines()) <= 7

    @pytest.mark.asyncio
    async def test_model_supported_name_switches_session_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`/model claude-sonnet-4-6` switches when credentials exist and saves preference."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.is_running = False
        session.prepare_model_selection = AsyncMock(
            return_value="active model switched to claude-sonnet-4-6. Preference saved."
        )

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/model claude-sonnet-4-6",
            session=session,
        )

        session.prepare_model_selection.assert_awaited_once_with(model_name="claude-sonnet-4-6")
        assert "claude-sonnet-4-6" in (result.rendered or "")
        assert "Preference saved" in (result.rendered or "")

    @pytest.mark.asyncio
    async def test_model_unknown_name_rejects(self) -> None:
        """Unknown model names render an actionable error."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-5.4"
        session.is_running = False

        session.prepare_model_selection = AsyncMock(return_value="unknown model: mistral-large")

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

        session.prepare_model_selection = AsyncMock(
            return_value="model 'claude-sonnet-4-6' requires /auth for anthropic"
        )

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

        session.prepare_model_selection = AsyncMock(
            return_value="cannot switch models while a prompt is in flight"
        )

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
    async def test_reasoning_without_args_lists_k3_supported_levels(self) -> None:
        """Bare K3 reasoning state lists its three canonical levels."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "kimi-k3"
        session.active_reasoning_level = "xhigh"

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning",
            session=session,
        )

        assert result.rendered == "model: kimi-k3\nreasoning: xhigh\nsupported: low, high, xhigh"

    @pytest.mark.asyncio
    async def test_reasoning_off_clamps_to_low_for_k3(self) -> None:
        """K3 reports the catalog-driven clamp from off to low."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "kimi-k3"
        session.active_reasoning_level = "xhigh"
        session.switch_reasoning_level = MagicMock(return_value="low")

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning off",
            session=session,
        )

        session.switch_reasoning_level.assert_called_once_with(reasoning_level="off")
        assert result.rendered == "reasoning changed xhigh -> low (requested off; clamped for kimi-k3)"

    @pytest.mark.asyncio
    async def test_reasoning_on_selects_k3_profile_default(self) -> None:
        """K3 on resolves to its catalog-defined xhigh default."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "kimi-k3"
        session.active_reasoning_level = "low"
        session.switch_reasoning_level = MagicMock(return_value="xhigh")

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning on",
            session=session,
        )

        session.switch_reasoning_level.assert_called_once_with(reasoning_level="xhigh")
        assert result.rendered == "reasoning changed low -> xhigh"

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

    @pytest.mark.parametrize(
        "reasoning,supported,off_result",
        [
            (
                {"supported_efforts": ["none"], "mandatory": False},
                "off (reasoning disable supported)",
                "reasoning changed low -> off",
            ),
            (
                {"supported_efforts": ["low", "high"]},
                "low, high (provider default; disable unavailable)",
                "reasoning disable unavailable for openrouter:vendor/model; provider default applies",
            ),
        ],
    )
    async def test_reasoning_state_and_off_follow_converted_controls(
        self,
        reasoning: dict[str, object],
        supported: str,
        off_result: str,
    ) -> None:
        """Expose only real controls through both public router commands."""
        from src.agents.model_catalog.seed import SeedModelCatalog
        from src.agents.model_catalog.service import ModelCatalogService
        from tests.agents.model_catalog.test_openrouter_converter_metadata import _entry

        entry = _entry(reasoning=reasoning)
        snapshot = SeedModelCatalog.load().model_copy(update={"entries": {entry.model_name: entry}})
        session = _build_session_stub()
        session.active_model_name = entry.model_name
        session.active_reasoning_level = "low"
        session.switch_reasoning_level = MagicMock(return_value="off")
        with patch.object(ModelCatalogService, "load", return_value=snapshot):
            state = await SlashRouter.dispatch(line="/reasoning", session=session)
            off = await SlashRouter.dispatch(line="/reasoning off", session=session)
        assert state.rendered == f"model: {entry.model_name}\nreasoning: low\nsupported: {supported}"
        assert off.rendered == off_result
        assert session.switch_reasoning_level.call_count == int("mandatory" in reasoning)

    @pytest.mark.asyncio
    async def test_reasoning_off_switches_disable_only_openrouter_route(self) -> None:
        """Accept explicit off when canonical metadata permits only gateway disable."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "openrouter:vendor/model"
        session.active_reasoning_level = "low"
        session.switch_reasoning_level = MagicMock(return_value="off")

        from src.agents.reasoning_capabilities import ResolvedReasoningConfigDAO

        with (
            patch.object(SlashRouter, "_provider_default_reasoning_note", return_value=""),
            patch(
                "src.tui.slash_router.resolve_reasoning_config",
                return_value=ResolvedReasoningConfigDAO(
                    enabled=False, requested_level="off", active_level="off"
                ),
            ),
            patch(
                "src.tui.slash_router.capability_for_model",
                return_value=MagicMock(
                    supported_levels=["off"],
                    reasoning_disable_available=True,
                ),
            ),
        ):
            result: SlashCommandResultDAO = await SlashRouter.dispatch(
                line="/reasoning off",
                session=session,
            )

        session.switch_reasoning_level.assert_called_once_with(reasoning_level="off")
        assert result.rendered == "reasoning changed low -> off"

    @pytest.mark.asyncio
    async def test_reasoning_off_rejects_unknown_openrouter_disable_permission(self) -> None:
        """Reject internal compatibility off when the provider did not permit disable."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "openrouter:vendor/model"
        session.active_reasoning_level = "low"

        with (
            patch.object(SlashRouter, "_provider_default_reasoning_note", return_value=""),
            patch(
                "src.tui.slash_router.capability_for_model",
                return_value=MagicMock(
                    supported_levels=["off", "low", "high"],
                    reasoning_disable_available=False,
                ),
            ),
        ):
            result: SlashCommandResultDAO = await SlashRouter.dispatch(
                line="/reasoning off",
                session=session,
            )

        assert (
            result.rendered
            == "reasoning disable unavailable for openrouter:vendor/model; provider default applies"
        )
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
        session.prepare_model_selection = AsyncMock(
            return_value="active model switched to claude-sonnet-4-6. Preference saved."
        )

        await SlashRouter.dispatch(line="/model claude-sonnet-4-6", session=session)

        session.prepare_model_selection.assert_awaited_once_with(model_name="claude-sonnet-4-6")

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


_WORKFLOWS_USAGE: str = (
    "usage: /workflows [abort <workflow-id> | dismiss <workflow-id> | resume <workflow-id>"
    " | tui dismiss [<workflow-id>] | tui show]"
)
"""Exact ``/workflows`` usage line, shared by the router, the registry and ``/help``."""


class TestSlashWorkflowsHandler:
    """``/workflows`` — list, abort, dismiss detached workflows (spec 57.a.6)."""

    @staticmethod
    def _build_workflow_session(*, tmp_path: Path) -> MagicMock:
        """Build a session stub with a history root for workflow dispatch.

        Args:
            tmp_path (Path): Test-scoped history root.

        Returns:
            MagicMock: Session stub exposing history_root and session_id.
        """
        session: MagicMock = _build_session_stub()
        session.session_id = "session-1234"
        session.history_root = tmp_path / "history"
        return session

    @staticmethod
    async def _write_handle(*, history_root: Path, state: str = "running") -> None:
        """Persist one ``wf-1`` handle owned by ``session-1234``.

        Uses this test process's own pid so the router's real liveness probe
        sees the workflow as alive.

        Args:
            history_root (Path): Handle store root.
            state (str): Initial handle state.
        """
        import os

        from src.agents.slo_agent.orchestrator.workflow_registry import (
            WorkflowHandleDAO,
            WorkflowHandleStore,
        )

        store: WorkflowHandleStore = WorkflowHandleStore(history_root=history_root)
        await store.write(
            handle=WorkflowHandleDAO(
                workflow_id="wf-1",
                owner_session_id="session-1234",
                orchestrator_session_id="orch-1",
                pid=os.getpid(),
                brief="run the workflow",
                cwd="/tmp",
                state=state,  # type: ignore[arg-type]
            )
        )

    @pytest.mark.asyncio
    async def test_workflows_lists_handles(self, tmp_path: Path) -> None:
        """``/workflows`` renders the reconciled listing."""
        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)
        await self._write_handle(history_root=session.history_root)

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/workflows",
            session=session,
        )

        assert result.rendered is not None
        assert result.rendered.startswith("wf-1  running  orch orch-1")

    @pytest.mark.asyncio
    async def test_workflows_abort_routes_to_service(self, tmp_path: Path) -> None:
        """``/workflows abort wf-1`` renders the service's abort text."""
        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)
        from unittest.mock import AsyncMock

        service: MagicMock = MagicMock()
        service.abort = AsyncMock(return_value="workflow wf-1 aborted")
        with patch(
            "src.tui.slash_router.WorkflowCommandService",
            return_value=service,
        ):
            result: SlashCommandResultDAO = await SlashRouter.dispatch(
                line="/workflows abort wf-1",
                session=session,
            )

        service.abort.assert_awaited_once_with(workflow_id="wf-1")
        assert result.rendered == "workflow wf-1 aborted"

    @pytest.mark.asyncio
    async def test_slash_router_dispatches_workflows_resume(self, tmp_path: Path) -> None:
        """``/workflows resume wf-1`` forwards the typed resume signal with its text."""
        from unittest.mock import AsyncMock

        from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowCommandResultDAO

        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)
        service: MagicMock = MagicMock()
        service.resume_result = AsyncMock(
            return_value=WorkflowCommandResultDAO(
                rendered="workflow wf-1 resumed (pid 5678)",
                resumed_workflow_id="wf-1",
            )
        )
        with patch(
            "src.tui.slash_router.WorkflowCommandService",
            return_value=service,
        ):
            result: SlashCommandResultDAO = await SlashRouter.dispatch(
                line="/workflows resume wf-1",
                session=session,
            )

        service.resume_result.assert_awaited_once_with(workflow_id="wf-1")
        assert result.rendered == "workflow wf-1 resumed (pid 5678)"
        assert result.resumed_workflow_id == "wf-1"
        assert result.dismissed_workflow_id is None

    @pytest.mark.asyncio
    async def test_workflows_failed_resume_carries_no_signal(self, tmp_path: Path) -> None:
        """A refused resume renders its text and never clears observation suppression."""
        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)
        await self._write_handle(history_root=session.history_root, state="running")

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/workflows resume wf-1",
            session=session,
        )

        assert result.rendered == "workflow wf-1 is running — only stalled or failed workflows can be resumed"
        assert result.resumed_workflow_id is None

    @pytest.mark.asyncio
    async def test_workflows_dismiss_forwards_typed_dismissal(self, tmp_path: Path) -> None:
        """A durable stalled→failed dismissal keeps the handle and signals its id."""
        from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore

        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)
        await self._write_handle(history_root=session.history_root, state="stalled")

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/workflows dismiss wf-1",
            session=session,
        )

        assert result.rendered == "workflow wf-1 dismissed (stalled → failed)"
        assert result.dismissed_workflow_id == "wf-1"
        assert result.resumed_workflow_id is None
        handle = await WorkflowHandleStore(history_root=session.history_root).read(
            owner_session_id="session-1234",
            workflow_id="wf-1",
        )
        assert handle is not None
        assert handle.state == "failed"

    @pytest.mark.asyncio
    async def test_workflows_refused_dismiss_carries_no_signal(self, tmp_path: Path) -> None:
        """A refused dismissal keeps its text; success text is never parsed."""
        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)
        await self._write_handle(history_root=session.history_root, state="running")

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/workflows dismiss wf-1",
            session=session,
        )

        assert result.rendered == "workflow wf-1 is running — only stalled workflows can be dismissed"
        assert result.dismissed_workflow_id is None

    @pytest.mark.asyncio
    async def test_workflows_list_and_abort_carry_no_signal(self, tmp_path: Path) -> None:
        """Only dismiss and resume can populate the typed observation signals."""
        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)

        listing: SlashCommandResultDAO = await SlashRouter.dispatch(line="/workflows", session=session)
        abort: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/workflows abort wf-1", session=session
        )

        assert (listing.dismissed_workflow_id, listing.resumed_workflow_id) == (None, None)
        assert (abort.rendered, abort.dismissed_workflow_id, abort.resumed_workflow_id) == (
            "no workflow wf-1",
            None,
            None,
        )

    @pytest.mark.asyncio
    async def test_workflows_bad_subcommand_renders_usage(self, tmp_path: Path) -> None:
        """An unknown subcommand (or a missing id) renders the usage line."""
        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/workflows pause wf-1",
            session=session,
        )
        result_missing_id: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/workflows abort",
            session=session,
        )

        usage: str = _WORKFLOWS_USAGE
        assert result.rendered == usage
        assert result_missing_id.rendered == usage

    @pytest.mark.asyncio
    async def test_workflows_without_history_renders_unavailable(self) -> None:
        """History-disabled sessions get the unavailable line."""
        session: MagicMock = _build_session_stub()
        session.history_root = None

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/workflows",
            session=session,
        )

        assert result.rendered == "workflows unavailable — history is disabled for this session"

    @pytest.mark.asyncio
    async def test_workflows_dispatches_while_prompt_in_flight(self, tmp_path: Path) -> None:
        """No self-guard on ``session.is_running`` — supervision mid-run is the point."""
        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)
        session.is_running = True

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/workflows",
            session=session,
        )

        assert result.rendered == "no detached workflows for this session"

    @pytest.mark.asyncio
    async def test_wf_alias_resolves_to_workflows(self, tmp_path: Path) -> None:
        """``/wf`` routes to the same handler."""
        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/wf",
            session=session,
        )

        assert result.rendered == "no detached workflows for this session"

    @pytest.mark.asyncio
    async def test_workflows_appears_in_help(self) -> None:
        """The registry entry shows up in ``/help`` output."""
        session: MagicMock = _build_session_stub()

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/help",
            session=session,
        )

        assert result.rendered is not None
        assert _WORKFLOWS_USAGE.removeprefix("usage: ") in result.rendered
        assert "list detached workflows" in result.rendered
        assert "tui dismiss [<id>]" in result.rendered

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("line", "target_id"),
        [
            ("/workflows tui dismiss", None),
            ("/workflows   tui   dismiss  ", None),
            ("/workflows tui dismiss wf-1", "wf-1"),
            ("/wf tui dismiss orch-1", "orch-1"),
            ("/wf tui\tdismiss\torch-1", "orch-1"),
        ],
        ids=["all", "extra-spaces", "workflow-id", "alias-session-id", "tabs"],
    )
    async def test_tui_dismiss_returns_typed_request(
        self, tmp_path: Path, line: str, target_id: Optional[str]
    ) -> None:
        """``tui dismiss [<id>]`` carries only a typed request; the app renders the outcome."""
        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)

        result: SlashCommandResultDAO = await SlashRouter.dispatch(line=line, session=session)

        assert result.tui_visibility == WorkflowListVisibilityRequestDAO(
            action="dismiss", target_id=target_id
        )
        assert (result.rendered, result.dismissed_workflow_id, result.resumed_workflow_id) == ("", None, None)
        assert not session.history_root.exists()

    @pytest.mark.asyncio
    async def test_tui_dismiss_works_without_history_root(self) -> None:
        """Attached groups exist without history, so ``tui`` routes before the history guard."""
        session: MagicMock = _build_session_stub()
        session.history_root = None

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/workflows tui dismiss", session=session
        )

        assert result.tui_visibility == WorkflowListVisibilityRequestDAO(action="dismiss")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("history", [True, False], ids=["history", "no-history"])
    @pytest.mark.parametrize(
        "line",
        [
            "/workflows tui",
            "/workflows tui clear",
            "/workflows tui dismiss wf-1 extra",
            "/workflows tui dismiss ../escape",
            "/workflows tui dismiss [bold]x",
        ],
        ids=["bare", "other", "two-ids", "unsafe", "markup"],
    )
    async def test_bad_tui_usage_renders_usage(self, tmp_path: Path, line: str, history: bool) -> None:
        """Any other ``tui`` form changes nothing and renders the usage line."""
        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)
        session.history_root = session.history_root if history else None

        result: SlashCommandResultDAO = await SlashRouter.dispatch(line=line, session=session)

        assert (result.rendered, result.tui_visibility) == (_WORKFLOWS_USAGE, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "line",
        ["/workflows", "/workflows abort wf-1", "/workflows dismiss wf-1", "/workflows resume wf-1"],
    )
    async def test_existing_subcommands_carry_no_tui_request(self, tmp_path: Path, line: str) -> None:
        """List, abort, dismiss and resume never produce a list-clearing request."""
        session: MagicMock = self._build_workflow_session(tmp_path=tmp_path)

        result: SlashCommandResultDAO = await SlashRouter.dispatch(line=line, session=session)

        assert result.tui_visibility is None

    @pytest.mark.asyncio
    async def test_non_tui_without_history_still_unavailable(self) -> None:
        """Only ``tui`` bypasses the history guard; other subcommands keep the unavailable line."""
        session: MagicMock = _build_session_stub()
        session.history_root = None

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/workflows dismiss wf-1", session=session
        )

        assert (result.rendered, result.tui_visibility) == (
            "workflows unavailable — history is disabled for this session",
            None,
        )


class TestSlashReasoningHandlerAstra:
    """Feature 83.a.1: `/reasoning` consumes the seeded seven-level Astra record."""

    @pytest.mark.asyncio
    async def test_reasoning_without_args_lists_all_seven_astra_levels(self) -> None:
        """Bare `/reasoning` on Astra lists the full canonical vocabulary."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-6-astra"
        session.active_reasoning_level = "high"

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning",
            session=session,
        )

        assert "model: gpt-6-astra" in (result.rendered or "")
        assert "reasoning: high" in (result.rendered or "")
        assert "supported: off, minimal, low, medium, high, xhigh, max" in (result.rendered or "")

    @pytest.mark.asyncio
    async def test_reasoning_max_selects_canonical_max_for_astra(self) -> None:
        """`/reasoning max` resolves to canonical ``max`` for Astra."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-6-astra"
        session.active_reasoning_level = "high"
        session.switch_reasoning_level = MagicMock(return_value="max")

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning max",
            session=session,
        )

        session.switch_reasoning_level.assert_called_once_with(reasoning_level="max")
        assert result.rendered == "reasoning changed high -> max"

    @pytest.mark.asyncio
    async def test_reasoning_max_still_maps_to_legacy_highest_for_gpt_5_4(self) -> None:
        """Legacy profiles without canonical ``max`` keep their existing highest."""
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
    async def test_reasoning_max_token_accepts_canonical_max_for_astra(self) -> None:
        """The literal token ``max`` parses to canonical max for Astra."""
        session: MagicMock = _build_session_stub()
        session.active_model_name = "gpt-6-astra"
        session.active_reasoning_level = "high"

        result: SlashCommandResultDAO = await SlashRouter.dispatch(
            line="/reasoning max",
            session=session,
        )

        session.switch_reasoning_level.assert_called_once_with(reasoning_level="max")
        assert "usage:" not in (result.rendered or "")


class TestSlashRouterActivity:
    """Registry-driven long-running detection for the TUI activity loader."""

    def test_compact_requires_activity(self) -> None:
        """``/compact`` is the long-running command that shows the loader."""
        assert SlashRouter.requires_activity(line="/compact") is True

    def test_quick_and_unknown_commands_do_not_require_activity(self) -> None:
        """Ordinary commands and unknown tokens never mount the loader."""
        assert SlashRouter.requires_activity(line="/model gpt-5.4") is False
        assert SlashRouter.requires_activity(line="/help") is False
        assert SlashRouter.requires_activity(line="/nope") is False
