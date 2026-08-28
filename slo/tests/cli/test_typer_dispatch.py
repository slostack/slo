"""Tests for ``TyperDispatch`` (sub-spec 02.a.4)."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import typer

from src.cli.typer_dispatch import TyperDispatch


class TestTyperDispatchTui:
    """Cover ``TyperDispatch.tui``."""

    def test_tui_builds_session_and_runs_slo_tui_with_mouse_enabled(self, tmp_path: Path) -> None:
        """``tui`` builds the session for the given workdir and runs ``SloTUI`` with mouse capture enabled."""
        fake_session: MagicMock = MagicMock(name="SloAgentSession")

        with (
            patch(
                "src.cli.typer_dispatch.interactive_logging",
                return_value=nullcontext(),
            ),
            patch(
                "src.cli.typer_dispatch.SloAgentSession.build",
                return_value=fake_session,
            ) as mock_build,
            patch(
                "src.cli.typer_dispatch.SloTUI",
            ) as MockSloTUI,
        ):
            TyperDispatch.tui(workdir=tmp_path)

        mock_build.assert_called_once()
        config = mock_build.call_args.kwargs["config"]
        assert config.workdir == tmp_path.resolve()

        MockSloTUI.assert_called_once_with(session=fake_session)
        MockSloTUI.return_value.run.assert_called_once_with(mouse=True)

    def test_tui_defaults_workdir_to_cwd(self) -> None:
        """``workdir=None`` resolves to ``Path.cwd().resolve()``."""
        fake_session: MagicMock = MagicMock(name="SloAgentSession")

        with (
            patch(
                "src.cli.typer_dispatch.interactive_logging",
                return_value=nullcontext(),
            ),
            patch(
                "src.cli.typer_dispatch.SloAgentSession.build",
                return_value=fake_session,
            ) as mock_build,
            patch("src.cli.typer_dispatch.SloTUI"),
        ):
            TyperDispatch.tui(workdir=None)

        config = mock_build.call_args.kwargs["config"]
        assert config.workdir == Path.cwd().resolve()

    def test_tui_enters_interactive_logging_before_building_session(
        self,
        tmp_path: Path,
    ) -> None:
        """The TUI path wraps session startup in ``interactive_logging``."""
        fake_session: MagicMock = MagicMock(name="SloAgentSession")
        fake_context: MagicMock = MagicMock(name="interactive_logging_context")
        enter_order: list[str] = []

        def _build(*args, **kwargs):
            enter_order.append("build")
            return fake_session

        fake_context.__enter__.side_effect = lambda: enter_order.append("enter")
        fake_context.__exit__.return_value = False

        with (
            patch(
                "src.cli.typer_dispatch.interactive_logging",
                return_value=fake_context,
            ) as mock_interactive_logging,
            patch(
                "src.cli.typer_dispatch.SloAgentSession.build",
                side_effect=_build,
            ),
            patch("src.cli.typer_dispatch.SloTUI"),
        ):
            TyperDispatch.tui(workdir=tmp_path)

        mock_interactive_logging.assert_called_once()
        assert enter_order == ["enter", "build"]

    def test_tui_resolves_named_session_reference_before_building_session(self, tmp_path: Path) -> None:
        """Named session references resolve to canonical ids before config assembly."""
        fake_session: MagicMock = MagicMock(name="SloAgentSession")

        with (
            patch(
                "src.cli.typer_dispatch.interactive_logging",
                return_value=nullcontext(),
            ),
            patch(
                "src.cli.typer_dispatch.TyperDispatch._resolve_resume_reference",
                return_value="resolved-session-id",
            ) as mock_resolve_resume_reference,
            patch(
                "src.cli.typer_dispatch.SloAgentSession.build",
                return_value=fake_session,
            ) as mock_build,
            patch("src.cli.typer_dispatch.SloTUI"),
        ):
            TyperDispatch.tui(
                workdir=tmp_path,
                resume_session_reference="release prep",
            )

        mock_resolve_resume_reference.assert_called_once_with(
            resume_session_reference="release prep",
        )
        config = mock_build.call_args.kwargs["config"]
        assert config.session_id == "resolved-session-id"

    def test_resolve_resume_reference_returns_none_when_missing(self) -> None:
        """No CLI resume reference means a fresh session."""
        assert TyperDispatch._resolve_resume_reference(resume_session_reference=None) is None

    def test_resolve_resume_reference_delegates_to_history_store(self) -> None:
        """Dispatch resolves names through the canonical history store."""
        fake_store: MagicMock = MagicMock()
        fake_store.resolve_session_reference = AsyncMock(return_value="resolved-session-id")

        with patch(
            "src.cli.typer_dispatch.FilesystemSessionHistoryStore",
            return_value=fake_store,
        ):
            resolved_session_id: str = TyperDispatch._resolve_resume_reference(
                resume_session_reference="release prep",
            )

        assert resolved_session_id == "resolved-session-id"

    def test_resolve_resume_reference_propagates_actionable_unknown_reference(self) -> None:
        """Unknown references fail fast with actionable copy."""
        fake_store: MagicMock = MagicMock()
        fake_store.resolve_session_reference = AsyncMock(
            side_effect=ValueError("unknown session reference: release prep"),
        )

        with patch(
            "src.cli.typer_dispatch.FilesystemSessionHistoryStore",
            return_value=fake_store,
        ):
            with pytest.raises(ValueError, match="unknown session reference: release prep"):
                TyperDispatch._resolve_resume_reference(
                    resume_session_reference="release prep",
                )


    def test_tui_threads_resolved_workspace_file_into_session_config(self, tmp_path: Path) -> None:
        """A valid workspace file is resolved and stored on SessionConfigDAO."""
        fake_session: MagicMock = MagicMock(name="SloAgentSession")
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text('{"folders": []}', encoding="utf-8")

        with (
            patch(
                "src.cli.typer_dispatch.interactive_logging",
                return_value=nullcontext(),
            ),
            patch(
                "src.cli.typer_dispatch.SloAgentSession.build",
                return_value=fake_session,
            ) as mock_build,
            patch("src.cli.typer_dispatch.SloTUI"),
        ):
            TyperDispatch.tui(workdir=tmp_path, workspace_file=workspace_file)

        config = mock_build.call_args.kwargs["config"]
        assert config.workspace_file == workspace_file.resolve()

    def test_tui_raises_bad_parameter_when_workspace_file_is_missing(self, tmp_path: Path) -> None:
        """A missing workspace file fails fast before any session is built."""
        with pytest.raises(typer.BadParameter, match="Workspace file not found"):
            TyperDispatch.tui(
                workdir=tmp_path,
                workspace_file=tmp_path / "missing.code-workspace",
            )

    def test_tui_threads_none_when_workspace_file_is_omitted(self, tmp_path: Path) -> None:
        """Omitting ``--workspace`` leaves SessionConfigDAO.workspace_file unset."""
        fake_session: MagicMock = MagicMock(name="SloAgentSession")

        with (
            patch(
                "src.cli.typer_dispatch.interactive_logging",
                return_value=nullcontext(),
            ),
            patch(
                "src.cli.typer_dispatch.SloAgentSession.build",
                return_value=fake_session,
            ) as mock_build,
            patch("src.cli.typer_dispatch.SloTUI"),
        ):
            TyperDispatch.tui(workdir=tmp_path)

        config = mock_build.call_args.kwargs["config"]
        assert config.workspace_file is None


class TestTyperDispatchUpdate:
    """Cover ``TyperDispatch.update``."""

    def test_update_delegates_to_updater_invoke(self) -> None:
        """``update`` forwards ``development`` / ``ref`` straight to ``Updater.invoke``."""
        with patch("src.cli.typer_dispatch.Updater.invoke") as mock_invoke:
            TyperDispatch.update(development=False)

        mock_invoke.assert_called_once_with(development=False, ref=None)

    def test_update_forwards_development_and_ref(self) -> None:
        """``--development`` / ``--ref`` are passed through unchanged."""
        with patch("src.cli.typer_dispatch.Updater.invoke") as mock_invoke:
            TyperDispatch.update(development=True, ref="v0.3.2")

        mock_invoke.assert_called_once_with(development=True, ref="v0.3.2")


class TestBuildSessionConfigPreferences:
    """``TyperDispatch._build_session_config`` loads preferences before cfg defaults."""

    def test_uses_model_from_preferences_when_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A saved model preference is used instead of cfg default."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
        from src.agents.slo_agent.preferences.service import UserPreferencesStore
        UserPreferencesStore.upsert(model_name="claude-sonnet-4-5")

        config = TyperDispatch._build_session_config(workdir=tmp_path)

        assert config.model_name == "claude-sonnet-4-5"

    def test_falls_back_to_cfg_when_no_preferences(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no preferences file exists, cfg default is used."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "absent.json"))
        # cfg.py snapshots env at import; patch the function directly.
        monkeypatch.setattr(
            "src.cli.typer_dispatch.cfg",
            lambda key: "gpt-fallback" if key == "DEFAULT_MODEL_NAME" else None,
        )

        config = TyperDispatch._build_session_config(workdir=tmp_path)

        assert config.model_name == "gpt-fallback"

    def test_uses_reasoning_level_from_preferences(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A saved reasoning level is passed into SessionConfigDAO."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
        from src.agents.slo_agent.preferences.service import UserPreferencesStore
        UserPreferencesStore.upsert(model_name="claude-sonnet-4-5", reasoning_level="high")

        config = TyperDispatch._build_session_config(workdir=tmp_path)

        assert config.reasoning_level == "high"

    def test_reasoning_level_is_none_when_no_preferences(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no preferences file exists, reasoning_level is None in config."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "absent.json"))

        config = TyperDispatch._build_session_config(workdir=tmp_path)

        assert config.reasoning_level is None

    def test_invalid_saved_model_preference_falls_back_with_notice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A saved preference pointing at an unknown model is safely replaced."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
        monkeypatch.setenv("SLO_DEFAULT_MODEL_NAME", "gpt-5.4")
        from src.agents.slo_agent.preferences.service import UserPreferencesStore
        UserPreferencesStore.upsert(model_name="mistral-large")

        config = TyperDispatch._build_session_config(workdir=tmp_path)

        assert config.model_name == "gpt-5.4"
        assert config.fallback_notice is not None
        assert "mistral-large" in config.fallback_notice
        assert "falling back" in config.fallback_notice

    def test_compatibility_prefix_preference_keeps_model_with_notice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A preference matching a provider prefix uses compatibility path."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
        from src.agents.slo_agent.preferences.service import UserPreferencesStore
        UserPreferencesStore.upsert(model_name="claude-legacy-model")

        config = TyperDispatch._build_session_config(workdir=tmp_path)

        assert config.model_name == "claude-legacy-model"
        assert config.fallback_notice is not None
        assert "compatibility-only" in config.fallback_notice

    def test_corrupt_preferences_file_falls_back_to_cfg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A corrupt preferences file logs a warning and uses cfg default."""
        path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))
        fake_cfg = lambda key: "fallback-model" if key == "DEFAULT_MODEL_NAME" else None
        monkeypatch.setattr("src.cli.typer_dispatch.cfg", fake_cfg)
        monkeypatch.setattr("config.ai_model_config.cfg", fake_cfg)
        path.write_text("{corrupt", encoding="utf-8")

        config = TyperDispatch._build_session_config(workdir=tmp_path)

        assert config.model_name == "fallback-model"


class TestRunHeadlessReasoningOverride:
    """``run_headless`` applies the ``--reasoning`` flag to ``SessionConfigDAO``."""

    def _run_headless_patched(
        self,
        tmp_path: Path,
        **kwargs,
    ) -> "SessionConfigDAO":
        """Run ``run_headless`` with all heavy dependencies patched out."""
        from contextlib import nullcontext
        captured_config: list = []

        async def _fake_invoke(*, prompt: str) -> int:
            return 0

        fake_runner = MagicMock()
        fake_runner.invoke = _fake_invoke

        def _capture_runner(*, config, orchestrator_mode=False, notify_session_id=None):
            captured_config.append(config)
            return fake_runner

        with (
            patch("src.cli.typer_dispatch.headless_logging", return_value=nullcontext()),
            patch("src.cli.typer_dispatch.HeadlessRunner", side_effect=_capture_runner),
            patch("src.cli.typer_dispatch.asyncio.run", return_value=0),
        ):
            TyperDispatch.run_headless(prompt="test prompt", **kwargs)

        return captured_config[0] if captured_config else None

    def test_reasoning_is_applied_to_config_when_provided(self, tmp_path: Path) -> None:
        """``--reasoning high`` sets ``SessionConfigDAO.reasoning_level`` to ``high``."""
        from contextlib import nullcontext

        captured_configs: list = []

        def _capture_runner(*, config, orchestrator_mode=False, notify_session_id=None):
            captured_configs.append(config)
            return MagicMock()

        with (
            patch("src.cli.typer_dispatch.headless_logging", return_value=nullcontext()),
            patch("src.cli.typer_dispatch.HeadlessRunner", side_effect=_capture_runner),
            patch("src.cli.typer_dispatch.asyncio.run", return_value=0),
        ):
            TyperDispatch.run_headless(prompt="do it", reasoning="high")

        assert len(captured_configs) == 1
        assert captured_configs[0].reasoning_level == "high"

    def test_reasoning_none_leaves_config_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ``reasoning`` is ``None`` the preferences value is kept unchanged."""
        from contextlib import nullcontext

        # Isolate from any saved preferences on the machine
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "absent.json"))
        captured_configs: list = []

        def _capture_runner(*, config, orchestrator_mode=False, notify_session_id=None):
            captured_configs.append(config)
            return MagicMock()

        with (
            patch("src.cli.typer_dispatch.headless_logging", return_value=nullcontext()),
            patch("src.cli.typer_dispatch.HeadlessRunner", side_effect=_capture_runner),
            patch("src.cli.typer_dispatch.asyncio.run", return_value=0),
        ):
            TyperDispatch.run_headless(prompt="do it", reasoning=None)

        assert len(captured_configs) == 1
        # reasoning_level is None when no preferences file exists
        assert captured_configs[0].reasoning_level is None


class TestRunHeadlessResumeImpliesHistory:
    """``--resume`` forces ``enable_history=True`` regardless of the flag value."""

    def test_resume_forces_enable_history_true(self) -> None:
        """Passing ``resume`` without ``--enable-history`` still enables history."""
        from contextlib import nullcontext
        from uuid import uuid4

        session_id: str = str(uuid4())
        captured_configs: list = []

        def _capture_runner(*, config, orchestrator_mode=False, notify_session_id=None):
            captured_configs.append(config)
            return MagicMock()

        with (
            patch("src.cli.typer_dispatch.headless_logging", return_value=nullcontext()),
            patch("src.cli.typer_dispatch.HeadlessRunner", side_effect=_capture_runner),
            patch("src.cli.typer_dispatch.asyncio.run", return_value=0),
            patch(
                "src.cli.typer_dispatch.TyperDispatch._resolve_resume_reference",
                return_value=session_id,
            ),
        ):
            TyperDispatch.run_headless(
                prompt="do it",
                resume="some-reference",
                enable_history=False,
            )

        assert len(captured_configs) == 1
        assert captured_configs[0].enable_history is True

    def test_no_resume_keeps_enable_history_false(self) -> None:
        """Without ``resume``, the flag value is respected."""
        from contextlib import nullcontext

        captured_configs: list = []

        def _capture_runner(*, config, orchestrator_mode=False, notify_session_id=None):
            captured_configs.append(config)
            return MagicMock()

        with (
            patch("src.cli.typer_dispatch.headless_logging", return_value=nullcontext()),
            patch("src.cli.typer_dispatch.HeadlessRunner", side_effect=_capture_runner),
            patch("src.cli.typer_dispatch.asyncio.run", return_value=0),
        ):
            TyperDispatch.run_headless(
                prompt="do it",
                resume=None,
                enable_history=False,
            )

        assert len(captured_configs) == 1
        assert captured_configs[0].enable_history is False


class TestRunHeadlessSessionIdResolution:
    """Session-id follows the resolution chain: resume > explicit > env > None."""

    def _run_headless_capture_config(self, **kwargs) -> "SessionConfigDAO":
        from contextlib import nullcontext

        captured: list = []

        def _capture_runner(*, config, orchestrator_mode=False, notify_session_id=None):
            captured.append(config)
            runner = MagicMock()
            runner.invoke = AsyncMock(return_value=0)
            return runner

        with (
            patch("src.cli.typer_dispatch.headless_logging", return_value=nullcontext()),
            patch("src.cli.typer_dispatch.HeadlessRunner", side_effect=_capture_runner),
            patch("src.cli.typer_dispatch.asyncio.run", return_value=0),
        ):
            TyperDispatch.run_headless(prompt="task", **kwargs)

        return captured[0]

    def test_explicit_session_id_is_applied_to_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SLO_SESSION_ID", raising=False)
        slug: str = "my-explicit-run"
        config = self._run_headless_capture_config(explicit_session_id=slug)
        assert config.session_id == slug

    def test_env_session_id_used_when_no_explicit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uuid import uuid4

        env_id: str = str(uuid4())
        monkeypatch.setenv("SLO_SESSION_ID", env_id)
        config = self._run_headless_capture_config()
        assert config.session_id == env_id.lower()

    def test_none_when_no_session_id_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SLO_SESSION_ID", raising=False)
        config = self._run_headless_capture_config()
        assert config.session_id is None


class TestRunHeadlessSystemPromptOverrides:
    """``--system-prompt-file`` and ``--append-system-prompt-file`` load file content."""

    def _capture_config(self, **kwargs) -> "SessionConfigDAO":
        from contextlib import nullcontext

        captured: list = []

        def _capture_runner(*, config, orchestrator_mode=False, notify_session_id=None):
            captured.append(config)
            runner = MagicMock()
            runner.invoke = AsyncMock(return_value=0)
            return runner

        with (
            patch("src.cli.typer_dispatch.headless_logging", return_value=nullcontext()),
            patch("src.cli.typer_dispatch.HeadlessRunner", side_effect=_capture_runner),
            patch("src.cli.typer_dispatch.asyncio.run", return_value=0),
        ):
            TyperDispatch.run_headless(prompt="task", **kwargs)

        return captured[0]

    def test_system_prompt_file_content_loaded_into_config(
        self, tmp_path: Path
    ) -> None:
        prompt_file: Path = tmp_path / "system.txt"
        prompt_file.write_text("You are a helpful agent.", encoding="utf-8")
        config = self._capture_config(system_prompt_file=prompt_file)
        assert config.system_prompt == "You are a helpful agent."

    def test_append_system_prompt_file_content_loaded_into_config(
        self, tmp_path: Path
    ) -> None:
        append_file: Path = tmp_path / "append.txt"
        append_file.write_text("Extra instructions.", encoding="utf-8")
        config = self._capture_config(append_system_prompt_file=append_file)
        assert config.append_system_prompt == "Extra instructions."

    def test_neither_file_leaves_config_prompts_none(self) -> None:
        config = self._capture_config()
        assert config.system_prompt is None
        assert config.append_system_prompt is None

    def test_missing_system_prompt_file_raises_bad_parameter(
        self, tmp_path: Path
    ) -> None:
        """A non-existent --system-prompt-file raises typer.BadParameter."""
        missing: Path = tmp_path / "does_not_exist.txt"
        with pytest.raises(typer.BadParameter) as exc_info:
            self._capture_config(system_prompt_file=missing)
        assert exc_info.value.param_hint == "--system-prompt-file"

    def test_missing_append_system_prompt_file_raises_bad_parameter(
        self, tmp_path: Path
    ) -> None:
        """A non-existent --append-system-prompt-file raises typer.BadParameter."""
        missing: Path = tmp_path / "also_missing.txt"
        with pytest.raises(typer.BadParameter) as exc_info:
            self._capture_config(append_system_prompt_file=missing)
        assert exc_info.value.param_hint == "--append-system-prompt-file"


class TestApplySystemPromptB64Override:
    """``TyperDispatch._apply_system_prompt_b64_override`` decodes and applies a b64 system prompt."""

    def _capture_config(self, **kwargs) -> "SessionConfigDAO":
        """Run ``run_headless`` and return the config that would be passed to HeadlessRunner."""
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO  # noqa: F401

        captured: list = []

        def _capture_runner(*, config, orchestrator_mode=False, notify_session_id=None):
            captured.append(config)
            runner = MagicMock()
            runner.invoke = AsyncMock(return_value=0)
            return runner

        with (
            patch("src.cli.typer_dispatch.headless_logging", return_value=nullcontext()),
            patch("src.cli.typer_dispatch.HeadlessRunner", side_effect=_capture_runner),
            patch("src.cli.typer_dispatch.asyncio.run", return_value=0),
        ):
            TyperDispatch.run_headless(prompt="task", **kwargs)

        return captured[0]

    def test_system_prompt_b64_decoded_and_applied_to_config(self) -> None:
        """A valid base64 value is decoded and stored as ``config.system_prompt``."""
        import base64

        prompt_text: str = "You are a focused orchestrator agent."
        encoded: str = base64.b64encode(prompt_text.encode()).decode()

        config = self._capture_config(system_prompt_b64=encoded)

        assert config.system_prompt == prompt_text

    def test_system_prompt_b64_none_leaves_config_unchanged(self) -> None:
        """``system_prompt_b64=None`` leaves ``config.system_prompt`` unset."""
        config = self._capture_config(system_prompt_b64=None)

        assert config.system_prompt is None

    def test_system_prompt_b64_wins_over_system_prompt_file(self, tmp_path: Path) -> None:
        """When both ``--system-prompt-file`` and ``--system-prompt-b64`` are given, b64 wins."""
        import base64

        file_body: str = "From file."
        b64_body: str = "From b64."
        prompt_file: Path = tmp_path / "system.txt"
        prompt_file.write_text(file_body, encoding="utf-8")
        encoded: str = base64.b64encode(b64_body.encode()).decode()

        config = self._capture_config(
            system_prompt_file=prompt_file,
            system_prompt_b64=encoded,
        )

        assert config.system_prompt == b64_body


class TestRunHeadlessNotifySession:
    """``run_headless`` threads ``--notify-session`` into ``HeadlessRunner`` (spec 57.a.3)."""

    def _captured_runner_kwargs(self, *, notify_session_id) -> dict:
        """Run ``run_headless`` with heavy deps patched and capture runner kwargs.

        Args:
            notify_session_id: Value passed through ``run_headless``.

        Returns:
            dict: The keyword arguments ``HeadlessRunner`` was constructed with.
        """
        from contextlib import nullcontext

        captured_kwargs: list[dict] = []

        def _capture_runner(**kwargs):
            captured_kwargs.append(kwargs)
            return MagicMock()

        with (
            patch("src.cli.typer_dispatch.headless_logging", return_value=nullcontext()),
            patch("src.cli.typer_dispatch.HeadlessRunner", side_effect=_capture_runner),
            patch("src.cli.typer_dispatch.asyncio.run", return_value=0),
        ):
            TyperDispatch.run_headless(
                prompt="do it",
                notify_session_id=notify_session_id,
            )

        assert len(captured_kwargs) == 1
        return captured_kwargs[0]

    def test_run_headless_threads_notify_session_id(self) -> None:
        """A supplied notify session id reaches the runner constructor."""
        kwargs: dict = self._captured_runner_kwargs(notify_session_id="tui-session-9")

        assert kwargs["notify_session_id"] == "tui-session-9"

    def test_run_headless_defaults_notify_session_id_to_none(self) -> None:
        """Without the flag the runner receives ``notify_session_id=None``."""
        kwargs: dict = self._captured_runner_kwargs(notify_session_id=None)

        assert kwargs["notify_session_id"] is None
