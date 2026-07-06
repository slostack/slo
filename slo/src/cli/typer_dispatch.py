"""Subcommand bodies for the Typer CLI (sub-spec 02.a.4).

Name mapping — CLI flag → Python attribute (headless run path):

  --resume <ref>                  → resume (str|None)        → resolved via history store
  --session-id <str>              → explicit_session_id      → SessionConfigDAO.session_id
  SLO_SESSION_ID env              → (resolve_session_id)     → SessionConfigDAO.session_id
  --workspace <path>              → workspace                → SessionConfigDAO.workspace_file
  --model <str>                   → model                    → SessionConfigDAO.model_name
  --reasoning <level>             → reasoning                → SessionConfigDAO.reasoning_level
  --cwd <path>                    → cwd                      → SessionConfigDAO.workdir
  --enable-history                → enable_history           → SessionConfigDAO.enable_history
  --system-prompt-file <path>     → system_prompt_file       → SessionConfigDAO.system_prompt
  --append-system-prompt-file <p> → append_system_prompt_file→ SessionConfigDAO.append_system_prompt
  --orchestrator                  → orchestrator_mode        → HeadlessRunner.orchestrator_mode
  --system-prompt-b64 <str>       → system_prompt_b64        → SessionConfigDAO.system_prompt

Resolution order for session id (first non-None wins):
  1. ``--resume`` reference resolved by the history store to a canonical UUID.
  2. ``--session-id`` explicit literal (validated as UUID4 or slug).
  3. ``SLO_SESSION_ID`` environment variable (validated on read).
  4. Fresh ``uuid4()`` generated inside ``SloAgentSession.build()``.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Optional

import typer

from config.cfg import SLO_HOME as _CFG_SLO_HOME, cfg
from config.logger import configure_app_file_logging, interactive_logging, log_info
from config.model_pool_config import parse_model_pool_config
from src.agents.reasoning_capabilities import ReasoningLevel
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.preferences.dao import UserPreferencesDAO, UserPreferencesStoreCorruptError
from src.agents.slo_agent.preferences.service import UserPreferencesStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.cli.headless import HeadlessRunner
from src.cli.headless_logging import headless_logging
from src.cli.headless_request import resolve_session_id, validate_session_id
from src.cli.update import Updater
from src.tui.app import SloTUI

__all__ = ["TyperDispatch"]


class TyperDispatch:
    """Namespace for Typer subcommand bodies.

    Each classmethod is the body of one subcommand. The Typer-decorated
    wrappers in ``app.py`` do nothing but parse args and delegate here.
    """

    @classmethod
    def tui(
        cls,
        *,
        workdir: Optional[Path],
        workspace_file: Optional[Path] = None,
        resume_session_reference: Optional[str] = None,
    ) -> None:
        """Open the Textual TUI scoped to ``workdir`` (or the cwd).

        Interactive runs temporarily swap the root logger away from
        terminal streams so Textual owns the screen without stdout/stderr
        log lines punching through the layout.

        Args:
            workdir (Optional[Path]): Directory to scope the TUI to.
                ``None`` means use ``Path.cwd()``.
            workspace_file (Optional[Path]): Optional VSCode workspace file
                whose declared folders contribute additive context.
            resume_session_reference (Optional[str]): Session reference to
                reopen (session id or unique session name). ``None`` allocates
                a new UUID4.
        """
        resolved_workdir: Path = (workdir or Path.cwd()).resolve()
        resolved_workspace_file: Optional[Path] = cls._resolve_workspace_file(
            workspace_file=workspace_file,
        )
        resolved_session_id: Optional[str] = cls._resolve_resume_reference(
            resume_session_reference=resume_session_reference,
        )
        slo_home: Path = _CFG_SLO_HOME
        with interactive_logging(slo_home=slo_home):
            config: SessionConfigDAO = cls._build_session_config(
                workdir=resolved_workdir,
                workspace_file=resolved_workspace_file,
                resume_session_id=resolved_session_id,
            )
            session: SloAgentSession = SloAgentSession.build(config=config)
            SloTUI(session=session).run(mouse=True)

    @classmethod
    def serve(cls, *, port: int) -> None:
        """Boot the ``/healthz``-only FastAPI app via uvicorn.

        Args:
            port (int): Port to bind the FastAPI app to.
        """
        import uvicorn
        from config.logger import LOGGING_CONFIG

        slo_home: Path = _CFG_SLO_HOME
        configure_app_file_logging(slo_home=slo_home)
        uvicorn.run(
            app="src.main:app",
            host="127.0.0.1",
            port=port,
            log_config=LOGGING_CONFIG,
        )

    @classmethod
    def run_headless(
        cls,
        *,
        prompt: str,
        as_json: bool = True,
        model: Optional[str] = None,
        reasoning: Optional[str] = None,
        cwd: Optional[str] = None,
        enable_history: bool = False,
        resume: Optional[str] = None,
        workspace: Optional[Path] = None,
        explicit_session_id: Optional[str] = None,
        system_prompt_file: Optional[Path] = None,
        append_system_prompt_file: Optional[Path] = None,
        orchestrator_mode: bool = False,
        system_prompt_b64: Optional[str] = None,
    ) -> int:
        """Run one agent loop headlessly, stream JSONL to stdout, return exit code.

        Builds a ``SessionConfigDAO`` through the same path as ``tui()`` so
        model resolution, preference loading, and credential lookup are
        identical. Wraps execution in ``headless_logging()`` to prevent log
        lines from contaminating the JSONL stdout channel.

        Session-id resolution order (first non-None wins):
          1. ``resume`` reference resolved by the history store to a UUID.
          2. ``explicit_session_id`` from ``--session-id``.
          3. ``SLO_SESSION_ID`` environment variable.
          4. Fresh UUID4 generated inside ``SloAgentSession.build()``.

        Args:
            prompt (str): The task prompt to execute headlessly.
            as_json (bool, optional): Emit JSONL when ``True``. Defaults to ``True``.
            model (Optional[str]): Model override; ``None`` falls back to
                preferences then ``cfg("DEFAULT_MODEL_NAME")``.
            reasoning (Optional[str]): Reasoning level override
                (``off``/``minimal``/``low``/``medium``/``high``/``xhigh``).
                ``None`` keeps the model's seeded default.
            cwd (Optional[str]): Working directory for the run; ``None``
                uses ``Path.cwd()``.
            enable_history (bool, optional): Persist history to disk.
                ``--resume`` always forces this to ``True``. Defaults to ``False``.
            resume (Optional[str]): Resume a known Slo session reference
                (session id or unique session name). ``None`` allocates a
                fresh session. Implies ``enable_history=True``.
            workspace (Optional[Path]): Optional VSCode workspace file.
            explicit_session_id (Optional[str]): Pre-validated explicit
                session id from ``--session-id``. ``None`` falls through to
                the env-var and fresh-UUID resolution chain.
            system_prompt_file (Optional[Path]): Path to a file whose
                content replaces the default system prompt.
            append_system_prompt_file (Optional[Path]): Path to a file
                whose content is appended to the base system prompt.
            orchestrator_mode (bool, optional): When ``True`` attach a
                ``SubAgentPool`` before running so the agent can spawn
                sub-agents. Defaults to ``False``.
            system_prompt_b64 (Optional[str]): Base64-encoded system prompt string.
                When non-None, decoded and applied as ``SessionConfigDAO.system_prompt``.
                Takes precedence over ``system_prompt_file``.

        Returns:
            int: POSIX exit code: ``0`` completed, ``2`` aborted, ``1`` failed.
        """
        slo_home: Path = _CFG_SLO_HOME
        resolved_workdir: Path = (Path(cwd) if cwd else Path.cwd()).resolve()
        resolved_workspace_file: Optional[Path] = cls._resolve_workspace_file(
            workspace_file=workspace,
        )
        resume_session_id: Optional[str] = cls._resolve_resume_reference(
            resume_session_reference=resume,
        )
        validated_explicit_id: Optional[str] = (
            validate_session_id(value=explicit_session_id) if explicit_session_id else None
        )
        canonical_session_id: Optional[str] = resolve_session_id(
            resume_session_id=resume_session_id,
            explicit_session_id=validated_explicit_id,
        )
        effective_enable_history: bool = enable_history or (resume is not None)
        config: SessionConfigDAO = cls._build_session_config(
            workdir=resolved_workdir,
            workspace_file=resolved_workspace_file,
            resume_session_id=canonical_session_id,
        )
        config = cls._apply_model_override(config=config, model=model)
        config = cls._apply_reasoning_override(config=config, reasoning=reasoning)
        config = cls._apply_history_override(
            config=config,
            enable_history=effective_enable_history,
        )
        config = cls._apply_system_prompt_overrides(
            config=config,
            system_prompt_file=system_prompt_file,
            append_system_prompt_file=append_system_prompt_file,
        )
        config = cls._apply_system_prompt_b64_override(
            config=config,
            system_prompt_b64=system_prompt_b64,
        )
        runner: HeadlessRunner = HeadlessRunner(
            config=config,
            orchestrator_mode=orchestrator_mode,
        )
        with headless_logging(slo_home=slo_home):
            return asyncio.run(runner.invoke(prompt=prompt))

    @classmethod
    def visualize(
        cls,
        *,
        session_reference: str,
        follow: bool = True,
        refresh_seconds: float = 1.0,
        detail_format: str = "textual",
    ) -> None:
        """Open the read-only workflow visualizer TUI for a completed or running session.

        Resolves the session reference, builds the visualizer config, and
        launches the Textual ``HeadlessWorkflowVisualizer`` app in the same
        process — no sub-process or network call required.

        Args:
            session_reference (str): Session id or unique session name to inspect.
            follow (bool, optional): Poll for live updates. Defaults to ``True``.
            refresh_seconds (float, optional): Polling cadence. Defaults to ``1.0``.
            detail_format (str, optional): Transcript rendering mode (``textual`` /
                ``markdown`` / ``html``). Defaults to ``"textual"``.
        """
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer  # noqa: PLC0415
        from src.tui.tree_export_format import TreeExportFormat  # noqa: PLC0415
        from src.tui.workflow_visualizer_loader import (  # noqa: PLC0415
            HeadlessWorkflowVisualizerConfigDAO,
        )

        try:
            resolved_format: TreeExportFormat = TreeExportFormat(detail_format.lower())
        except ValueError:
            typer.echo(
                message=f"Unknown --detail-format '{detail_format}'. "
                f"Valid values: textual, markdown, html.",
                err=True,
            )
            raise typer.Exit(code=1)

        slo_home: Path = _CFG_SLO_HOME
        config: HeadlessWorkflowVisualizerConfigDAO = HeadlessWorkflowVisualizerConfigDAO(
            session_reference=session_reference,
            follow=follow,
            refresh_seconds=refresh_seconds,
            detail_format=resolved_format,
        )
        with interactive_logging(slo_home=slo_home):
            HeadlessWorkflowVisualizer(config=config).run(mouse=True)

    @classmethod
    def update(cls, *, development: bool, ref: Optional[str] = None) -> None:
        """Reinstall slo via pipx from the repo (delegates to :class:`Updater`).

        Args:
            development (bool): When ``True``, track ``main``; otherwise pin to
                the latest release. Ignored when ``ref`` is given.
            ref (Optional[str]): Explicit branch / tag / commit to install.
        """
        Updater.invoke(development=development, ref=ref)

    @classmethod
    def _resolve_resume_reference(
        cls,
        *,
        resume_session_reference: Optional[str],
    ) -> Optional[str]:
        """Resolve the CLI resume reference to a canonical session id.

        Args:
            resume_session_reference (Optional[str]): Raw CLI resume input.

        Returns:
            Optional[str]: Canonical session id, or ``None`` for a fresh session.
        """
        if resume_session_reference is None:
            return None
        store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore()
        return asyncio.run(
            store.resolve_session_reference(reference=resume_session_reference),
        )

    @classmethod
    def _resolve_workspace_file(
        cls,
        *,
        workspace_file: Optional[Path],
    ) -> Optional[Path]:
        """Validate and resolve an optional workspace file path.

        Args:
            workspace_file (Optional[Path]): Raw CLI workspace path.

        Returns:
            Optional[Path]: Resolved workspace file path, or ``None``.

        Raises:
            typer.BadParameter: When the file does not exist.
        """
        if workspace_file is None:
            return None
        resolved_workspace_file: Path = workspace_file.expanduser().resolve()
        if not resolved_workspace_file.is_file():
            raise typer.BadParameter(
                message=f"Workspace file not found: {resolved_workspace_file}",
                param_hint="--workspace",
            )
        if resolved_workspace_file.suffix != ".code-workspace":
            log_info(
                msg="workspace_file_unexpected_suffix",
                workspace_file=str(resolved_workspace_file),
                suffix=resolved_workspace_file.suffix,
            )
        return resolved_workspace_file

    @classmethod
    def _build_session_config(
        cls,
        *,
        workdir: Path,
        workspace_file: Optional[Path] = None,
        resume_session_id: Optional[str] = None,
    ) -> SessionConfigDAO:
        """Assemble session config from preferences, then env, then cfg defaults.

        Resolution order for model name:
            1. ``UserPreferencesStore`` saved value.
            2. ``cfg("DEFAULT_MODEL_NAME")`` (env or cfg.py literal).

        Resolution order for reasoning level:
            1. ``UserPreferencesStore`` saved value.
            2. Model default (resolved later in ``SloAgentSession``).

        A corrupt preferences file is treated as absent so a stale or
        hand-edited file never prevents the TUI from booting.

        Args:
            workdir (Path): Resolved absolute workdir.
            workspace_file (Optional[Path]): Optional resolved workspace file.
            resume_session_id (Optional[str]): Optional explicit session
                id to reopen.

        Returns:
            SessionConfigDAO: A validated session-config DAO.
        """
        prefs: UserPreferencesDAO
        try:
            prefs = UserPreferencesStore.load()
        except UserPreferencesStoreCorruptError:
            log_info(msg="preferences_file_corrupt_falling_back_to_defaults")
            prefs = UserPreferencesDAO()

        model_name: str = (
            prefs.default_model_name
            or cfg("DEFAULT_MODEL_NAME")
            or "gpt-5.4"
        )
        model_pool_dao = parse_model_pool_config(preference_value=prefs.default_model_pool)

        return SessionConfigDAO(
            workdir=workdir,
            workspace_file=workspace_file,
            model_name=model_name,
            model_pool_dao=model_pool_dao,
            reasoning_level=prefs.default_reasoning_level,
            session_id=resume_session_id,
        )

    @classmethod
    def _apply_model_override(
        cls,
        *,
        config: SessionConfigDAO,
        model: Optional[str],
    ) -> SessionConfigDAO:
        """Return a copy of *config* with the model name overridden if supplied.

        Args:
            config (SessionConfigDAO): Existing config to copy.
            model (Optional[str]): Model name override; ``None`` returns *config*
                unchanged.

        Returns:
            SessionConfigDAO: Updated config, or the original when *model* is ``None``.
        """
        if model is None:
            return config
        return config.model_copy(update={"model_name": model})

    @classmethod
    def _apply_reasoning_override(
        cls,
        *,
        config: SessionConfigDAO,
        reasoning: Optional[str],
    ) -> SessionConfigDAO:
        """Return a copy of *config* with ``reasoning_level`` set if *reasoning* supplied.

        The value is passed as-is; ``SloAgentSession.build()`` validates it
        against the model's supported levels at run time.

        Args:
            config (SessionConfigDAO): Existing config to copy.
            reasoning (Optional[str]): Raw reasoning level string from the CLI
                (``off``/``minimal``/``low``/``medium``/``high``/``xhigh``).
                ``None`` returns *config* unchanged.

        Returns:
            SessionConfigDAO: Updated config, or the original when *reasoning* is ``None``.
        """
        if reasoning is None:
            return config
        return config.model_copy(update={"reasoning_level": reasoning})

    @classmethod
    def _apply_history_override(
        cls,
        *,
        config: SessionConfigDAO,
        enable_history: bool,
    ) -> SessionConfigDAO:
        """Return a copy of *config* with ``enable_history`` forced to *enable_history*.

        Args:
            config (SessionConfigDAO): Existing config to copy.
            enable_history (bool): Resolved history flag (already accounts for
                ``--resume`` implying ``True``).

        Returns:
            SessionConfigDAO: Updated config with the resolved history flag.
        """
        return config.model_copy(update={"enable_history": enable_history})

    @classmethod
    def _apply_system_prompt_overrides(
        cls,
        *,
        config: SessionConfigDAO,
        system_prompt_file: Optional[Path],
        append_system_prompt_file: Optional[Path],
    ) -> SessionConfigDAO:
        """Load optional prompt files and return a copy of *config* with them applied.

        Both files are read as UTF-8 text.  When neither file is supplied the
        original *config* is returned unchanged.

        Args:
            config (SessionConfigDAO): Existing config to copy.
            system_prompt_file (Optional[Path]): Path to a file that fully
                replaces the base system prompt.  ``None`` leaves the prompt
                as-is.
            append_system_prompt_file (Optional[Path]): Path to a file whose
                content is appended after the base system prompt.  ``None``
                leaves ``append_system_prompt`` unchanged.

        Returns:
            SessionConfigDAO: Updated config with any prompt overrides applied.
        """
        updates: dict = {}
        if system_prompt_file is not None:
            if not system_prompt_file.is_file():
                raise typer.BadParameter(
                    message=f"File not found: {system_prompt_file}",
                    param_hint="--system-prompt-file",
                )
            updates["system_prompt"] = system_prompt_file.read_text(encoding="utf-8")
        if append_system_prompt_file is not None:
            if not append_system_prompt_file.is_file():
                raise typer.BadParameter(
                    message=f"File not found: {append_system_prompt_file}",
                    param_hint="--append-system-prompt-file",
                )
            updates["append_system_prompt"] = append_system_prompt_file.read_text(
                encoding="utf-8"
            )
        if not updates:
            return config
        return config.model_copy(update=updates)

    @classmethod
    def _apply_system_prompt_b64_override(
        cls,
        *,
        config: SessionConfigDAO,
        system_prompt_b64: Optional[str],
    ) -> SessionConfigDAO:
        """Decode a base64 system prompt and apply it to *config*.

        Base64 is used instead of a raw string flag to avoid shell-quoting
        issues with multi-line prompt text.

        Args:
            config (SessionConfigDAO): Existing config to copy.
            system_prompt_b64 (Optional[str]): Base64-encoded prompt string.
                ``None`` returns *config* unchanged.

        Returns:
            SessionConfigDAO: Updated config with decoded system prompt, or the
                original when *system_prompt_b64* is ``None``.
        """
        if system_prompt_b64 is None:
            return config
        try:
            decoded: str = base64.b64decode(system_prompt_b64.encode()).decode("utf-8")
        except Exception as exc:
            raise typer.BadParameter(
                f"could not decode --system-prompt-b64: {exc}",
                param_hint="--system-prompt-b64",
            ) from exc
        return config.model_copy(update={"system_prompt": decoded})
