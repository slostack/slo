"""Credential resolver — the single seam for credential lookups (02.b.2)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from config.cfg import cfg, openrouter_api_key
from config.logger import log_error
from src.auth.credential_dao import (
    AuthenticationFileDAO,
    AuthType,
    CredentialDAO,
    CredentialSource,
    ProviderName,
    ResolvedCredentialDAO,
)
from src.auth.credential_store import CredentialStore

__all__ = ["CredentialResolver"]


class CredentialResolver:
    """Stateless lookup across env, ``CredentialStore``, and the legacy Claude file.

    Order of precedence:
        1. Environment variable for the requested provider.
        2. ``CredentialStore``: ``~/.slo/global/authentication.json`` merged with
           ``authentication.additional-providers.json`` beside it.
        3. ``~/.claude/.credentials.json`` (Anthropic only).

    ``resolve`` returns ``Optional[CredentialDAO]`` and never raises.
    ``require`` raises ``ValueError`` with a provider-specific message
    when ``resolve`` returns ``None``.

    The resolver is stateless: every call queries each source fresh.
    Callers (``LLMFactory``, the TUI mount path, the auth modal) hold
    no reference to this class — they invoke it as a namespace.
    """

    _CLAUDE_CREDENTIALS_PATH: Path = Path.home() / ".claude" / ".credentials.json"
    _build_credential: ContextVar[Optional[CredentialDAO]] = ContextVar("build_credential", default=None)

    @classmethod
    @contextmanager
    def bind_build_credential(cls, *, credential: Optional[CredentialDAO]) -> Iterator[None]:
        """Bind a session's private capture during synchronous lazy factory construction.

        Catalog/source reads remain live for publication race checks. Only require()
        consumes this task-local binding; nested construction restores its predecessor.

        Args:
            credential: Admitted credential, or None for the ordinary factory path.

        Yields:
            None: Scope in which matching factory requests reuse the capture.
        """
        with cls.bind_operation_credential(credential=credential):
            yield

    @classmethod
    @contextmanager
    def bind_operation_credential(cls, *, credential: Optional[CredentialDAO]) -> Iterator[None]:
        """Bind one admitted credential for all protected writes in a session operation.

        WHAT: Makes an already admitted OpenRouter credential available to the
            task-local history redactor after lazy agent construction has returned.
        WHO: ``SloAgentSession`` owns this scope around one accepted prompt.
        WHEN: From admission through terminal persistence and cleanup; nested
            task scopes restore their predecessor on success, error, or cancellation.

        Args:
            credential: Admitted credential, or None for a non-OpenRouter operation.

        Yields:
            None: Scope in which protected serializers redact the operation capture.
        """
        token = cls._build_credential.set(credential)
        try:
            yield
        finally:
            cls._build_credential.reset(token)

    @classmethod
    def operation_credential(cls) -> Optional[CredentialDAO]:
        """Return the private admitted capture for a delayed operation owner.

        Headless event subscribers retain this capture only until terminal cleanup.
        This does not resolve a new credential or expose it in a public DTO.

        Returns:
            Optional[CredentialDAO]: Current task's admitted credential.
        """
        return cls._build_credential.get()

    @classmethod
    def redact_openrouter_text(cls, *, text: str) -> str:
        """Remove known credential representations from text before persistence.

        Args:
            text: Serialized history or diagnostic text, never a request body.

        Returns:
            str: Text with the effective and task-bound credentials replaced.
                Unrelated opaque continuation metadata remains unchanged.
        """
        captured = cls._build_credential.get()
        effective = cls._resolve_openrouter_credential_for_redaction()
        for credential in (effective, captured):
            if credential is None or credential.provider != ProviderName.OPENROUTER:
                continue
            token = credential.access_token
            if not token:
                continue
            variants = {token, json.dumps(token)[1:-1], quote(token, safe="")}
            for variant in sorted(variants, key=len, reverse=True):
                text = text.replace(variant, "[REDACTED]")
        return text

    @classmethod
    def _resolve_openrouter_credential_for_redaction(cls) -> Optional[CredentialDAO]:
        """Resolve an output-redaction credential without allowing resolver faults to expose text.

        WHAT: Refuses unchecked serialization on a resolution failure without
            an admitted capture; a captured operation retains its literal redaction.
        WHO: ``redact_openrouter_text`` calls this before history and diagnostic
            persistence.
        WHEN: Every protected serialization boundary; resolution failure never
            propagates raw serialized content to the filesystem.

        Returns:
            Optional[CredentialDAO]: The live OpenRouter credential, or ``None``
                when resolution is unavailable but an admitted capture exists.

        Raises:
            ValueError: Resolution failed without an admitted OpenRouter capture.
                The fixed message suppresses potentially secret-bearing context.
        """
        try:
            return cls.resolve(provider=ProviderName.OPENROUTER)
        except Exception:  # noqa: BLE001 -- persistence must fail closed on resolver faults.
            captured = cls._build_credential.get()
            if captured is None or captured.provider != ProviderName.OPENROUTER or not captured.access_token:
                raise ValueError(
                    "OpenRouter credential resolution unavailable; serialization refused."
                ) from None
            return None

    @classmethod
    def resolve(cls, *, provider: ProviderName) -> Optional[CredentialDAO]:
        """Return the best available credential for ``provider``, or None.

        Args:
            provider (ProviderName): Provider to look up.

        Returns:
            Optional[CredentialDAO]: The effective credential without its source.
        """
        resolved: Optional[ResolvedCredentialDAO] = cls.resolve_with_source(provider=provider)
        return resolved.credential if resolved is not None else None

    @classmethod
    def resolve_with_source(cls, *, provider: ProviderName) -> Optional[ResolvedCredentialDAO]:
        """Return one effective credential together with its precedence source.

        Args:
            provider (ProviderName): Provider whose credential should be resolved.

        Returns:
            Optional[ResolvedCredentialDAO]: The first usable credential and its
                source, or ``None`` when every source is unavailable.
        """
        env_cred: Optional[CredentialDAO] = cls._from_env(provider=provider)
        if env_cred is not None:
            return ResolvedCredentialDAO(credential=env_cred, source=CredentialSource.ENVIRONMENT)

        stored_cred: Optional[CredentialDAO] = cls._from_store(provider=provider)
        if stored_cred is not None:
            return ResolvedCredentialDAO(credential=stored_cred, source=CredentialSource.STORE)

        legacy_cred: Optional[CredentialDAO] = cls._from_legacy_claude(provider=provider)
        if legacy_cred is not None:
            return ResolvedCredentialDAO(credential=legacy_cred, source=CredentialSource.LEGACY)

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
        captured = cls._build_credential.get()
        if captured is not None and captured.provider == provider:
            return captured
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
        if provider is ProviderName.OPENROUTER and not env_value.strip():
            raise ValueError("SLO_OPENROUTER_API_KEY must not contain only whitespace.")
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
    def _from_legacy_claude(cls, *, provider: ProviderName) -> Optional[CredentialDAO]:
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
        if provider is ProviderName.OPENROUTER:
            return openrouter_api_key()
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
            return "No Anthropic credentials found. Run /auth in the TUI or " "set SLO_ANTHROPIC_API_KEY."
        if provider is ProviderName.OPENAI:
            return "No OpenAI credentials found. Run /auth in the TUI or " "set SLO_OPENAI_API_KEY."
        if provider is ProviderName.KIMI_FOR_CODING:
            return (
                "No Kimi For Coding credentials found. Set SLO_KIMI_FOR_CODING_API_KEY "
                "or store the API key via /auth in the TUI."
            )
        if provider is ProviderName.OPENROUTER:
            return "No OpenRouter credentials found. Run /auth in the TUI or set SLO_OPENROUTER_API_KEY."
        return f"No credentials found for provider '{provider.value}'."
