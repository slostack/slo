"""Credential resolver — the single seam for credential lookups (02.b.2)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from config.cfg import cfg
from config.logger import log_error
from src.auth.credential_dao import (
    AuthenticationFileDAO,
    AuthType,
    CredentialDAO,
    ProviderName,
)
from src.auth.credential_store import CredentialStore


__all__ = ["CredentialResolver"]


class CredentialResolver:
    """Stateless lookup across env, ``CredentialStore``, and the legacy Claude file.

    Order of precedence:
        1. Environment variable for the requested provider.
        2. ``~/.slo/global/authentication.json`` via ``CredentialStore``.
        3. ``~/.claude/.credentials.json`` (Anthropic only).

    ``resolve`` returns ``Optional[CredentialDAO]`` and never raises.
    ``require`` raises ``ValueError`` with a provider-specific message
    when ``resolve`` returns ``None``.

    The resolver is stateless: every call queries each source fresh.
    Callers (``LLMFactory``, the TUI mount path, the auth modal) hold
    no reference to this class — they invoke it as a namespace.
    """

    _CLAUDE_CREDENTIALS_PATH: Path = Path.home() / ".claude" / ".credentials.json"

    @classmethod
    def resolve(cls, *, provider: ProviderName) -> Optional[CredentialDAO]:
        """Return the best available credential for ``provider``, or None.

        Args:
            provider (ProviderName): Provider to look up.

        Returns:
            Optional[CredentialDAO]: ``None`` when no source has a usable
                non-expired token. Otherwise the first source that
                resolves wins.
        """
        env_cred: Optional[CredentialDAO] = cls._from_env(provider=provider)
        if env_cred is not None:
            return env_cred

        stored_cred: Optional[CredentialDAO] = cls._from_store(provider=provider)
        if stored_cred is not None:
            return stored_cred

        legacy_cred: Optional[CredentialDAO] = cls._from_legacy_claude(provider=provider)
        if legacy_cred is not None:
            return legacy_cred

        return None

    @classmethod
    def require(cls, *, provider: ProviderName) -> CredentialDAO:
        """Like ``resolve`` but raises when nothing resolves.

        Used by ``LLMFactory.create`` where a missing credential is a
        runtime error, not a signal.

        Args:
            provider (ProviderName): Provider to look up.

        Returns:
            CredentialDAO: A usable credential.

        Raises:
            ValueError: Provider-specific, user-facing message naming the
                ``/auth`` slash command and the env-var fallback.
        """
        cred: Optional[CredentialDAO] = cls.resolve(provider=provider)
        if cred is None:
            raise ValueError(cls._missing_message(provider=provider))
        return cred

    @classmethod
    def _from_env(cls, *, provider: ProviderName) -> Optional[CredentialDAO]:
        """Return a synthetic DAO from the env var for ``provider``, or None.

        Args:
            provider (ProviderName): Which env var to read.

        Returns:
            Optional[CredentialDAO]: ``None`` when the env var is unset
                or empty.
        """
        env_value: Optional[str] = cls._env_var_for(provider=provider)
        if not env_value:
            return None
        return CredentialDAO(
            provider=provider,
            auth_type=AuthType.API_KEY,
            access_token=env_value,
        )

    @classmethod
    def _from_store(cls, *, provider: ProviderName) -> Optional[CredentialDAO]:
        """Return the stored row for ``provider``, skipping expired ones.

        Args:
            provider (ProviderName): Which row to look up.

        Returns:
            Optional[CredentialDAO]: ``None`` when no row exists or when
                the row is expired.
        """
        store: CredentialStore = CredentialStore()
        envelope: AuthenticationFileDAO = store.load()
        cred: Optional[CredentialDAO] = envelope.providers.get(provider)
        if cred is None:
            return None
        if cred.is_expired:
            return None
        return cred

    @classmethod
    def _from_legacy_claude(
        cls, *, provider: ProviderName
    ) -> Optional[CredentialDAO]:
        """Return an Anthropic credential from ``~/.claude/.credentials.json``.

        Args:
            provider (ProviderName): Only ``ANTHROPIC`` is honoured.

        Returns:
            Optional[CredentialDAO]: ``None`` for non-Anthropic providers
                or when the legacy file is missing / malformed.
        """
        if provider is not ProviderName.ANTHROPIC:
            return None
        token: Optional[str] = cls._read_legacy_claude_oauth(
            path=cls._CLAUDE_CREDENTIALS_PATH,
        )
        if token is None:
            return None
        return CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.OAUTH,
            access_token=token,
        )

    @classmethod
    def _read_legacy_claude_oauth(cls, *, path: Path) -> Optional[str]:
        """Pull ``claudeAiOauth.accessToken`` out of the Claude CLI file.

        Mirrors the body that lived at ``src/agents/base.py:170-205`` before
        this substep. Logs and swallows parse errors so a corrupt legacy
        file never crashes the resolver.

        Args:
            path (Path): Where the legacy file is expected to live.

        Returns:
            Optional[str]: The OAuth access token, or ``None`` when the
                file is missing or malformed.
        """
        if not path.exists():
            return None
        try:
            # Any: JSON parse output is structurally untyped.
            payload: dict[str, Any] = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            log_error(msg=f"CredentialResolver: legacy claude file at {path} is not JSON", e=exc)
            return None
        oauth: dict[str, Any] = payload.get("claudeAiOauth", {})
        token: Optional[str] = oauth.get("accessToken")
        if not token:
            return None
        return token

    @staticmethod
    def _env_var_for(*, provider: ProviderName) -> Optional[str]:
        """Map a provider to its env-var-shaped value via ``cfg``.

        Args:
            provider (ProviderName): Provider to map.

        Returns:
            Optional[str]: The env-var value or ``None`` when unset.
        """
        if provider is ProviderName.ANTHROPIC:
            return cfg(key="ANTHROPIC_API_KEY")
        if provider is ProviderName.OPENAI:
            return cfg(key="OPENAI_API_KEY")
        if provider is ProviderName.KIMI_FOR_CODING:
            return cfg(key="KIMI_FOR_CODING_API_KEY")
        return None

    @staticmethod
    def _missing_message(*, provider: ProviderName) -> str:
        """Return the user-facing message for ``require``'s ValueError.

        Args:
            provider (ProviderName): Provider that resolved to ``None``.

        Returns:
            str: A one-liner that names ``/auth`` and the env-var fallback.
        """
        if provider is ProviderName.ANTHROPIC:
            return (
                "No Anthropic credentials found. Run /auth in the TUI or "
                "set SLO_ANTHROPIC_API_KEY."
            )
        if provider is ProviderName.OPENAI:
            return (
                "No OpenAI credentials found. Run /auth in the TUI or "
                "set SLO_OPENAI_API_KEY."
            )
        if provider is ProviderName.KIMI_FOR_CODING:
            return (
                "No Kimi For Coding credentials found. Set SLO_KIMI_FOR_CODING_API_KEY "
                "or store the API key via /auth in the TUI."
            )
        return f"No credentials found for provider '{provider.value}'."
