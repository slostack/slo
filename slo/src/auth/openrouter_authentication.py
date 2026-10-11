"""Verify one captured OpenRouter credential before allowing persistence."""

from __future__ import annotations

import asyncio
from typing import Optional, Protocol

from src.agents.model_catalog.dao import CatalogRefreshResultDAO
from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    CredentialSource,
    OpenRouterAuthenticationResultDAO,
    ProviderName,
    ResolvedCredentialDAO,
)
from src.auth.credential_resolver import CredentialResolver
from src.auth.credential_store import CredentialStore
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.integrations.openrouter.dao import OpenRouterKeyVerificationDAO
from src.integrations.openrouter.exceptions import (
    OpenRouterAuthenticationError,
    OpenRouterProtocolError,
    OpenRouterTimeoutError,
)


class CredentialSourceResolver(Protocol):
    """Existing resolver's source-bearing operation, injectable without secret I/O."""

    def resolve_with_source(self, *, provider: ProviderName) -> Optional[ResolvedCredentialDAO]:
        """Capture the effective credential for the requested provider."""


class OpenRouterClientFactory(Protocol):
    """Construct the existing client with one explicitly captured credential."""

    def __call__(self, *, credential: CredentialDAO) -> OpenRouterAPIClient:
        """Return a fresh client; its context manager owns transport cleanup."""


class AuthenticationCatalogService(Protocol):
    """The existing catalog refresh gateway consumed after verification."""

    async def refresh(
        self,
        *,
        provider: ProviderName,
        force: bool,
        resolved_credential: Optional[ResolvedCredentialDAO] = None,
        key_verification: Optional[OpenRouterKeyVerificationDAO] = None,
    ) -> CatalogRefreshResultDAO:
        """Refresh using the exact private capture and successful verification evidence."""


class OpenRouterAuthenticationService:
    """Own a single modal attempt, with private credential and safe outcome state."""

    def __init__(
        self,
        *,
        store: CredentialStore,
        resolver: CredentialSourceResolver = CredentialResolver(),
        client_factory: OpenRouterClientFactory = OpenRouterAPIClient,
        catalog_service: AuthenticationCatalogService = ModelCatalogService(),
    ) -> None:
        """Inject the established owners without performing I/O.

        Args:
            store: Existing credential persistence owner.
            resolver: Source-bearing resolver, never a second precedence reader.
            client_factory: Existing GET client constructor with optional local transport.
            catalog_service: Existing refresh owner accepting private evidence.
        """
        self._store = store
        self._resolver = resolver
        self._client_factory = client_factory
        self._catalog_service = catalog_service
        self._credential_changed = False
        self._verified_credential: Optional[CredentialDAO] = None
        self._result = OpenRouterAuthenticationResultDAO(safe_message="Authentication has not started.")

    @property
    def result(self) -> OpenRouterAuthenticationResultDAO:
        """Return safe current state, including saved state after cancellation."""
        return self._result

    def verified_credential(self) -> Optional[CredentialDAO]:
        """Return the private verified capture solely for modal dismissal compatibility."""
        return self._verified_credential

    async def invoke(self, *, submitted_key: Optional[str] = None) -> OpenRouterAuthenticationResultDAO:
        """Verify, conditionally persist, then refresh for one modal submission.

        Args:
            submitted_key: Private candidate; omitted means verify the effective stored key.

        Returns:
            OpenRouterAuthenticationResultDAO: Fixed safe outcome without secret-bearing objects.

        Raises:
            asyncio.CancelledError: Cancellation propagates; ``result`` records saved state.
        """
        try:
            async with asyncio.timeout(30):
                return await self._authenticate(submitted_key=submitted_key)
        except asyncio.CancelledError:
            self._result = self._result.model_copy(update={"safe_message": self._cancel_message()})
            raise
        except OpenRouterAuthenticationError:
            self._result = self._result.model_copy(update={"safe_message": self._rejection_message()})
            return self._result
        except (OpenRouterTimeoutError, asyncio.TimeoutError):
            self._result = self._result.model_copy(update={"safe_message": self._timeout_message()})
            return self._result
        except OpenRouterProtocolError:
            self._result = self._result.model_copy(update={"safe_message": self._protocol_message()})
            return self._result
        except Exception:
            self._result = self._result.model_copy(update={"safe_message": self._failure_message()})
            return self._result

    async def _authenticate(self, *, submitted_key: Optional[str]) -> OpenRouterAuthenticationResultDAO:
        """Sequence capture, verification, commit and refresh inside the attempt budget."""
        capture = self._capture(submitted_key=submitted_key)
        self._result = OpenRouterAuthenticationResultDAO(
            effective_source=capture.source, safe_message="Verifying OpenRouter key."
        )
        async with self._client_factory(credential=capture.credential) as client:
            evidence = await client.get_current_key()
        self._persist_verified_candidate(capture=capture, submitted_key=submitted_key)
        self._verified_credential = capture.credential
        self._result = self._result.model_copy(update={"key_verified": True})
        return await self._refresh(capture=capture, evidence=evidence)

    def _capture(self, *, submitted_key: Optional[str]) -> ResolvedCredentialDAO:
        """Choose the environment capture before considering a submitted candidate."""
        effective = self._resolver.resolve_with_source(provider=ProviderName.OPENROUTER)
        if effective is not None and effective.source is CredentialSource.ENVIRONMENT:
            return effective
        if submitted_key is None and effective is not None:
            return effective
        if submitted_key is None or not submitted_key.strip():
            raise ValueError("OpenRouter API key is required.")
        return ResolvedCredentialDAO(
            source=CredentialSource.STORE,
            credential=CredentialDAO(
                provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token=submitted_key
            ),
        )

    def _persist_verified_candidate(
        self, *, capture: ResolvedCredentialDAO, submitted_key: Optional[str]
    ) -> None:
        """Recheck source immediately before synchronous persistence; no await splits the commit."""
        if capture.source is CredentialSource.ENVIRONMENT:
            self._validate_environment_capture(capture=capture)
            return
        if submitted_key is None:
            return
        current = self._resolver.resolve_with_source(provider=ProviderName.OPENROUTER)
        if current is not None and current.source is CredentialSource.ENVIRONMENT:
            self._credential_changed = True
            raise ValueError("Credential changed; retry authentication.")
        self._store.persist(cred=capture.credential)
        self._result = self._result.model_copy(update={"replacement_saved": True})

    def _validate_environment_capture(self, *, capture: ResolvedCredentialDAO) -> None:
        """Reject obsolete environment evidence before auth success or catalog handoff.

        Args:
            capture: Private environment identity sent to the completed verifier.

        Raises:
            ValueError: The effective source or key changed during verification.
        """
        current = self._resolver.resolve_with_source(provider=ProviderName.OPENROUTER)
        if (
            current is not None
            and current.source is CredentialSource.ENVIRONMENT
            and current.credential.access_token == capture.credential.access_token
        ):
            return
        self._credential_changed = True
        raise ValueError("Credential changed; retry authentication.")

    async def _refresh(
        self, *, capture: ResolvedCredentialDAO, evidence: OpenRouterKeyVerificationDAO
    ) -> OpenRouterAuthenticationResultDAO:
        """Delegate publication once; translate status rather than forwarding arbitrary copy."""
        refreshed = await self._catalog_service.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=capture,
            key_verification=evidence,
        )
        if refreshed.status == "credential_changed":
            return self._discard_obsolete_verification_evidence()
        checked = refreshed.status in {"fresh", "refreshed"}
        message = "Key verified; catalog checked." if checked else "Key verified; catalog refresh failed."
        if capture.source is CredentialSource.ENVIRONMENT:
            message = (
                "Environment key is active; pasted key was not saved. "
                "Change SLO_OPENROUTER_API_KEY to replace it. " + message
            )
        self._result = self._result.model_copy(update={"catalog_checked": checked, "safe_message": message})
        return self._result

    def _discard_obsolete_verification_evidence(self) -> OpenRouterAuthenticationResultDAO:
        """Clear obsolete verification while retaining a factual completed store write.

        Returns:
            OpenRouterAuthenticationResultDAO: Safe retry outcome that cannot dismiss with stale evidence.
        """
        self._credential_changed = True
        self._verified_credential = None
        self._result = self._result.model_copy(
            update={
                "key_verified": False,
                "catalog_checked": False,
                "safe_message": "Credential changed; retry authentication.",
            }
        )
        return self._result

    def _rejection_message(self) -> str:
        """Return fixed copy for an explicitly rejected effective credential.

        Returns:
            str: Safe rejection notice without provider response text.
        """
        return "OpenRouter key was rejected. Check /auth or SLO_OPENROUTER_API_KEY."

    def _timeout_message(self) -> str:
        """Return fixed copy for an authentication operation deadline.

        Returns:
            str: Safe timeout notice without transport details.
        """
        return "OpenRouter request timed out. Retry authentication later."

    def _protocol_message(self) -> str:
        """Return fixed copy for an invalid verification response.

        Returns:
            str: Safe protocol notice without response details.
        """
        return "OpenRouter returned an invalid verification response. Retry authentication later."

    def _failure_message(self) -> str:
        """Distinguish verified/saved state without serializing dependency exceptions.

        Returns:
            str: Fixed safe failure copy for the current attempt state.
        """
        if self._credential_changed:
            return "Credential changed; retry authentication."
        if self._result.key_verified:
            return "Key verified; catalog refresh failed."
        return "OpenRouter authentication failed; retry authentication."

    def _cancel_message(self) -> str:
        """Report the persistence boundary truthfully to the cancelling modal."""
        if self._result.replacement_saved:
            return "Authentication cancelled; verified key was saved."
        return "Authentication cancelled; no key was saved."
