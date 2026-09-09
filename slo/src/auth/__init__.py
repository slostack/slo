"""src.auth — credential domain, on-disk store, resolver, OAuth flow.

This substep (02.b.1) ships only the domain and the store. The resolver
(02.b.2) is also wired in here so downstream code can import it from the
package root. The OAuth orchestrator and providers land in 02.b.3-4.
"""

from src.auth.credential_dao import (
    AuthType,
    AuthenticationFileDAO,
    CredentialDAO,
    ProviderName,
)
from src.auth.credential_resolver import CredentialResolver
from src.auth.credential_store import CredentialStore, CredentialStoreCorruptError
from src.auth.provider_factory import OAuthFlowFactory
from src.auth.providers import AnthropicOAuthProvider, OpenAICodexOAuthProvider

__all__ = [
    "AnthropicOAuthProvider",
    "AuthType",
    "AuthenticationFileDAO",
    "CredentialDAO",
    "CredentialResolver",
    "CredentialStore",
    "CredentialStoreCorruptError",
    "OAuthFlowFactory",
    "OpenAICodexOAuthProvider",
    "ProviderName",
]
