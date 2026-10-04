"""Pydantic shapes for persisted Slo credentials (02.b.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AuthType",
    "AuthenticationFileDAO",
    "CredentialDAO",
    "CredentialSource",
    "ProviderName",
    "RELEASED_CREDENTIAL_PROVIDERS",
    "ResolvedCredentialDAO",
]


class ProviderName(str, Enum):
    """Model provider Slo knows how to authenticate against.

    ``ANTHROPIC`` matches any model whose name starts with ``claude-``.
    ``OPENAI`` matches ``gpt-*``, ``o1-*``, ``o3-*``.
    ``KIMI_FOR_CODING`` matches ``kimi-*`` and ``moonshot-*`` models via
    the Kimi For Coding API (https://api.kimi.com/coding/v1).
    """

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    KIMI_FOR_CODING = "kimi_for_coding"
    OPENROUTER = "openrouter"


RELEASED_CREDENTIAL_PROVIDERS: frozenset[ProviderName] = frozenset(
    {ProviderName.ANTHROPIC, ProviderName.OPENAI, ProviderName.KIMI_FOR_CODING}
)
"""Providers released Slo v0.20.1 accepts in authentication.json. Never extend this set.

CredentialStore keeps other providers in the additional-provider file so released Slo
can still validate its closed provider enum.
"""


class CredentialSource(str, Enum):
    """Origin from which ``CredentialResolver`` resolved one credential."""

    ENVIRONMENT = "environment"
    STORE = "store"
    LEGACY = "legacy"


class AuthType(str, Enum):
    """How a credential was obtained.

    ``OAUTH`` was minted by a PKCE browser flow and may carry a
    ``refresh_token`` and ``expires_at``. ``API_KEY`` was pasted by the
    user directly and does not refresh.
    """

    OAUTH = "oauth"
    API_KEY = "api_key"


class CredentialDAO(BaseModel):
    """One persisted credential for one provider.

    Fields:
        provider (ProviderName): Provider this credential authorises.
        auth_type (AuthType): How the credential was obtained.
        access_token (str): Bearer secret passed to the provider SDK.
        refresh_token (Optional[str]): OAuth refresh token; ``None`` for
            ``api_key`` rows.
        expires_at (Optional[datetime]): UTC expiry of ``access_token``;
            ``None`` when the provider does not return one or for
            ``api_key`` rows.
        subject (Optional[str]): Best-effort principal identifier (email
            or user id) used for the success screen banner. ``None`` when
            the provider does not return one.
        scope (Optional[str]): Space-separated OAuth scopes, when present.
        created_at (datetime): When this row was first written. Used for
            debugging and never for auth decisions.
    """

    model_config = ConfigDict(use_enum_values=False)

    provider: ProviderName
    auth_type: AuthType
    access_token: str = Field(repr=False)
    refresh_token: Optional[str] = Field(default=None, repr=False)
    expires_at: Optional[datetime] = None
    subject: Optional[str] = None
    scope: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_expired(self) -> bool:
        """Return True when ``expires_at`` is set and in the past.

        Rows without ``expires_at`` (API keys, OAuth responses without
        TTL) are treated as never-expiring.

        Returns:
            bool: ``True`` if the credential is past its declared expiry.
        """
        if self.expires_at is None:
            return False
        return self.expires_at <= datetime.now(timezone.utc)


class ResolvedCredentialDAO(BaseModel):
    """Private effective credential and the precedence source that supplied it."""

    model_config = ConfigDict(frozen=True)

    credential: CredentialDAO = Field(repr=False)
    source: CredentialSource


class OpenRouterAuthenticationResultDAO(BaseModel):
    """Public authentication outcome containing no credential or wire payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    effective_source: Optional[CredentialSource] = Field(default=None, description="Captured source.")
    key_verified: bool = Field(default=False, description="Whether verification succeeded.")
    replacement_saved: bool = Field(default=False, description="Whether the candidate was persisted.")
    catalog_checked: bool = Field(default=False, description="Whether refresh reported success.")
    safe_message: str = Field(description="Fixed operator notice, never upstream text.")


class AuthenticationFileDAO(BaseModel):
    """On-disk envelope shared by both credential files owned by CredentialStore.

    ``authentication.json`` holds only RELEASED_CREDENTIAL_PROVIDERS for released Slo.
    ``authentication.additional-providers.json`` holds other providers this version knows.
    Both use the same shape and schema_version; unknown future providers need another file.

    Fields:
        schema_version (int): Bumped on incompatible changes.
        providers (dict[ProviderName, CredentialDAO]): Per-provider rows.
            Empty when no credentials are configured.
    """

    schema_version: int = 1
    providers: dict[ProviderName, CredentialDAO] = Field(default_factory=dict)
