"""Supported native status observation; Claude Code retains its existing login."""

import asyncio
import json
import os
from importlib.resources import files
from pathlib import Path

from .dao import ClaudeAuthenticationStatusDAO, ClaudeBridgeConfigurationDAO
from .exceptions import ClaudeBridgeError


class ClaudeNativeAuthentication:
    """Inspect native status with the same no-settings/no-override policy as inference."""

    _CONFLICT_NAMES: tuple[str, ...] = (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "ANTHROPIC_CUSTOM_HEADERS",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
    )

    def __init__(self, *, configuration: ClaudeBridgeConfigurationDAO) -> None:
        """Retain trusted configuration without probing credentials or executables."""
        self._configuration = configuration

    def get_executable(self) -> Path:
        """Select an absolute override or package-owned bundled path, never PATH lookup."""
        executable = self._configuration.executable
        if executable is None:
            executable = Path(str(files("claude_agent_sdk").joinpath("_bundled", "claude")))
        if not executable.is_absolute():
            raise ClaudeBridgeError(
                code="invalid_options", safe_message="Claude executable must be absolute."
            )
        return executable

    @classmethod
    def ensure_subscription_environment(cls) -> None:
        """Reject credential/gateway/cloud overrides without exposing their values."""
        if any(os.environ.get(name) for name in cls._CONFLICT_NAMES):
            raise ClaudeBridgeError(
                code="authentication_conflict",
                safe_message="Remove native API-key, token, gateway or cloud overrides before using Claude bridge.",
            )

    async def check_authentication(self) -> ClaudeAuthenticationStatusDAO:
        """Run documented auth status, not a model query; discard all raw diagnostics.

        Returns:
            ClaudeAuthenticationStatusDAO: Positive claude.ai observation or native-login guidance.
        """
        self.ensure_subscription_environment()
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.get_executable()),
                "--setting-sources",
                "",
                "auth",
                "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            async with asyncio.timeout(10):
                stdout, _ = await process.communicate()
            status = json.loads(stdout) if len(stdout) <= 64 * 1024 else {}
            if (
                process.returncode == 0
                and isinstance(status, dict)
                and status.get("authMethod") == "claude.ai"
            ):
                return ClaudeAuthenticationStatusDAO(state="ready", safe_message="Native Claude login ready.")
            return ClaudeAuthenticationStatusDAO(state="login_required", safe_message=self.login_guidance())
        except (OSError, ValueError, asyncio.TimeoutError):
            return ClaudeAuthenticationStatusDAO(state="unavailable", safe_message=self.login_guidance())
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()

    @staticmethod
    def login_guidance() -> str:
        """Explain external login and the native transcript privacy boundary."""
        return (
            "Sign in outside Slo using Claude Code /login, then select the bridge again. "
            "Login affects shared native account state; native transcripts may persist even with Slo history off."
        )
