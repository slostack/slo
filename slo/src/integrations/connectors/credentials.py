"""Connector credential domain — DAOs, provider enum, and resolver (25.a.1, 26.a.4).

Resolution precedence per provider (default):
    1. On-disk store under ``~/.slo/connectors/<provider>/credentials.json``.
    2. Environment variables.
    3. ``require()`` raises ``ConnectorCredentialsRequiredError`` so the
       session can open an interactive capture screen.

The store-first order prevents placeholder env vars (e.g.
``SLO_ATLASSIAN_EMAIL=your-email@company.com``) from silently winning over
credentials the operator deliberately entered.  Set
``SLO_CONNECTOR_PREFER_ENV=1`` to restore env-first order for CI/CD pipelines
that set credentials explicitly.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict

from config.cfg import cfg as _cfg
from src.integrations.connectors.exceptions import ConnectorCredentialsRequiredError

__all__ = [
    "ConnectorCredentialDAO",
    "ConnectorCredentialResolver",
    "ConnectorProviderName",
]


class ConnectorProviderName(str, Enum):
    """Remote developer systems Slo can expose as connector tools.

    ``ATLASSIAN`` is shared by both Confluence and Jira so they draw from
    a single credential file.
    """

    ATLASSIAN = "atlassian"
    GITHUB = "github"
    GITLAB = "gitlab"


class ConnectorCredentialDAO(BaseModel):
    """Resolved runtime configuration for one connector provider.

    Attributes:
        provider (ConnectorProviderName): Which remote system this DAO targets.
        base_url (Optional[str]): REST API base URL or site root.
            Required for Atlassian; optional for GitHub/GitLab (defaults apply).
        token (str): API token or personal access token.
        username (Optional[str]): Username or email required by some providers
            (Atlassian basic-auth uses ``username:token``).
        timeout_seconds (float): Per-request HTTP timeout budget in seconds.
    """

    model_config = ConfigDict(frozen=True)

    provider: ConnectorProviderName
    base_url: Optional[str] = None
    token: str
    username: Optional[str] = None
    timeout_seconds: float = 30.0


class ConnectorCredentialResolver:
    """Stateless connector credential lookup across env, then the on-disk store.

    Every method is a classmethod so callers never need to instantiate this class.
    The class mirrors the shape of ``CredentialResolver`` in ``src.auth`` but stays
    entirely separate because these credentials authorize tools, not the LLM.
    """

    @classmethod
    def resolve(
        cls,
        *,
        provider: ConnectorProviderName,
    ) -> Optional[ConnectorCredentialDAO]:
        """Return credentials for one provider when available, else ``None``.

        Default resolution order (store-first):
            1. On-disk store — value the operator deliberately entered wins.
            2. Environment variables — still used as fallback.

        When ``SLO_CONNECTOR_PREFER_ENV=1`` is set, env is checked first.  This
        restores the original behavior for CI/CD pipelines that set credentials
        via environment variables explicitly.

        Args:
            provider (ConnectorProviderName): Provider whose credentials to look up.

        Returns:
            Optional[ConnectorCredentialDAO]: The resolved credentials, or ``None``
                when neither store nor env has a usable value.
        """
        from src.integrations.connectors.store import ConnectorCredentialStore  # noqa: PLC0415

        prefer_env: bool = (_cfg("SLO_CONNECTOR_PREFER_ENV") or "").strip() == "1"

        if prefer_env:
            env_cred: Optional[ConnectorCredentialDAO] = cls._from_env(provider=provider)
            if env_cred is not None:
                return env_cred
            return ConnectorCredentialStore.load(provider=provider)

        # Default: store first, then env
        stored_cred: Optional[ConnectorCredentialDAO] = ConnectorCredentialStore.load(
            provider=provider,
        )
        if stored_cred is not None:
            return stored_cred
        return cls._from_env(provider=provider)

    @classmethod
    def require(
        cls,
        *,
        provider: ConnectorProviderName,
    ) -> ConnectorCredentialDAO:
        """Return credentials or raise a typed missing-credential signal.

        Used by service clients that cannot proceed without credentials.
        The ``ConnectorCredentialsRequiredError`` that is raised carries
        enough context for a TUI session to open the interactive capture screen.

        Args:
            provider (ConnectorProviderName): Provider to resolve.

        Returns:
            ConnectorCredentialDAO: The resolved credentials.

        Raises:
            ConnectorCredentialsRequiredError: When no usable credentials exist
                from env or the on-disk store.
        """
        credential: Optional[ConnectorCredentialDAO] = cls.resolve(provider=provider)
        if credential is not None:
            return credential

        from src.integrations.connectors.store import ConnectorCredentialStore  # noqa: PLC0415

        raise ConnectorCredentialsRequiredError(
            provider=provider.value,
            required_fields=cls.required_fields(provider=provider),
            credentials_path=ConnectorCredentialStore.credentials_path(provider=provider),
        )

    @classmethod
    def is_configured(
        cls,
        *,
        provider: ConnectorProviderName,
    ) -> bool:
        """Return ``True`` when the provider has usable credentials.

        Used by the bundle factory to decide whether to include a provider's
        connector tools in the active tool list.

        Args:
            provider (ConnectorProviderName): Provider to check.

        Returns:
            bool: Whether env or store has a resolvable credential.
        """
        return cls.resolve(provider=provider) is not None

    @classmethod
    def required_fields(
        cls,
        *,
        provider: ConnectorProviderName,
    ) -> list[str]:
        """Return the field names the operator must supply for one provider.

        Used to pre-populate the interactive capture screen labels.

        Args:
            provider (ConnectorProviderName): Provider whose fields to list.

        Returns:
            list[str]: Ordered list of required field names.
        """
        if provider is ConnectorProviderName.ATLASSIAN:
            return ["base_url", "username", "token"]
        # GitHub and GitLab only need a token
        return ["token"]

    # ------------------------------------------------------------------
    # Private env-resolution helpers
    # ------------------------------------------------------------------

    @classmethod
    def _from_env(
        cls,
        *,
        provider: ConnectorProviderName,
    ) -> Optional[ConnectorCredentialDAO]:
        """Read credentials from environment variables for one provider.

        Args:
            provider (ConnectorProviderName): Provider to check in env.

        Returns:
            Optional[ConnectorCredentialDAO]: DAO built from env, or ``None``
                when the required env vars are absent or empty.
        """
        if provider is ConnectorProviderName.ATLASSIAN:
            return cls._atlassian_from_env()
        if provider is ConnectorProviderName.GITHUB:
            return cls._github_from_env()
        if provider is ConnectorProviderName.GITLAB:
            return cls._gitlab_from_env()
        return None

    @classmethod
    def _atlassian_from_env(cls) -> Optional[ConnectorCredentialDAO]:
        """Build Atlassian credentials from environment variables.

        Requires all three of ``SLO_ATLASSIAN_SITE_URL``,
        ``SLO_ATLASSIAN_EMAIL``, and ``SLO_ATLASSIAN_API_TOKEN``.

        Returns:
            Optional[ConnectorCredentialDAO]: Credentials when all required
                vars are present, otherwise ``None``.
        """
        site_url: Optional[str] = _cfg("SLO_ATLASSIAN_SITE_URL")
        email: Optional[str] = _cfg("SLO_ATLASSIAN_EMAIL")
        token: Optional[str] = _cfg("SLO_ATLASSIAN_API_TOKEN")
        if not site_url or not email or not token:
            return None
        timeout_raw: Optional[str] = _cfg("SLO_ATLASSIAN_TIMEOUT_SECONDS")
        timeout: float = float(timeout_raw) if timeout_raw else 30.0
        return ConnectorCredentialDAO(
            provider=ConnectorProviderName.ATLASSIAN,
            base_url=site_url.rstrip("/"),
            token=token,
            username=email,
            timeout_seconds=timeout,
        )

    @classmethod
    def _github_from_env(cls) -> Optional[ConnectorCredentialDAO]:
        """Build GitHub credentials from standard PAT environment variables.

        Checks ``GITHUB_TOKEN``, then ``GH_TOKEN``, then ``SLO_GITHUB_TOKEN``.

        Returns:
            Optional[ConnectorCredentialDAO]: Credentials when any PAT var is
                set, otherwise ``None``.
        """
        token: Optional[str] = _cfg("GITHUB_TOKEN") or _cfg("GH_TOKEN") or _cfg("SLO_GITHUB_TOKEN")
        if not token:
            return None
        base_url: str = (_cfg("SLO_GITHUB_API_BASE_URL") or "https://api.github.com").rstrip("/")
        timeout_raw: Optional[str] = _cfg("SLO_GITHUB_TIMEOUT_SECONDS")
        timeout: float = float(timeout_raw) if timeout_raw else 30.0
        return ConnectorCredentialDAO(
            provider=ConnectorProviderName.GITHUB,
            base_url=base_url,
            token=token,
            timeout_seconds=timeout,
        )

    @classmethod
    def _gitlab_from_env(cls) -> Optional[ConnectorCredentialDAO]:
        """Build GitLab credentials from standard PAT environment variables.

        Checks ``GITLAB_TOKEN``, then ``GLAB_TOKEN``, then ``SLO_GITLAB_TOKEN``.

        Returns:
            Optional[ConnectorCredentialDAO]: Credentials when any PAT var is
                set, otherwise ``None``.
        """
        token: Optional[str] = _cfg("GITLAB_TOKEN") or _cfg("GLAB_TOKEN") or _cfg("SLO_GITLAB_TOKEN")
        if not token:
            return None
        base_url: str = (_cfg("SLO_GITLAB_API_BASE_URL") or "https://gitlab.com/api/v4").rstrip("/")
        timeout_raw: Optional[str] = _cfg("SLO_GITLAB_TIMEOUT_SECONDS")
        timeout: float = float(timeout_raw) if timeout_raw else 30.0
        return ConnectorCredentialDAO(
            provider=ConnectorProviderName.GITLAB,
            base_url=base_url,
            token=token,
            timeout_seconds=timeout,
        )
