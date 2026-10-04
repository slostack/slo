"""In-memory construction bindings never change live credential source reads."""

import asyncio
from unittest.mock import patch

import pytest

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver


def test_nested_build_binding_restores_after_failure_and_leaves_other_providers_live() -> None:
    """Factory captures are provider-scoped and unwind without persisting any state."""
    first = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="local-a"
    )
    second = first.model_copy(update={"access_token": "local-b"})
    with patch.object(CredentialResolver, "resolve", return_value=second) as live:
        with CredentialResolver.bind_build_credential(credential=first):
            assert CredentialResolver.require(provider=ProviderName.OPENROUTER) is first
            live.assert_not_called()
            assert CredentialResolver.require(provider=ProviderName.OPENAI) is second
            assert CredentialResolver.resolve(provider=ProviderName.OPENROUTER) is second
            with pytest.raises(RuntimeError, match="local failure"):
                with CredentialResolver.bind_build_credential(credential=second):
                    assert CredentialResolver.require(provider=ProviderName.OPENROUTER) is second
                    raise RuntimeError("local failure")
            assert CredentialResolver.require(provider=ProviderName.OPENROUTER) is first
        assert CredentialResolver.require(provider=ProviderName.OPENROUTER) is second
        with CredentialResolver.bind_build_credential(credential=None):
            assert CredentialResolver.require(provider=ProviderName.OPENROUTER) is second


def test_operation_binding_resets_when_exception_escapes() -> None:
    """An operation-owned capture restores the previous task-local value on error."""
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-operation-reset",
    )

    with pytest.raises(RuntimeError, match="cancelled operation"):
        with CredentialResolver.bind_operation_credential(credential=credential):
            assert CredentialResolver._build_credential.get() is credential
            raise RuntimeError("cancelled operation")

    assert CredentialResolver._build_credential.get() is None


async def test_operation_binding_isolated_between_concurrent_tasks() -> None:
    """Concurrent sessions retain only their own task-local admitted credential."""
    first = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-concurrent-a",
    )
    second = first.model_copy(update={"access_token": "synthetic-concurrent-b"})
    entered = asyncio.Event()
    release = asyncio.Event()

    async def observe(credential: CredentialDAO, wait_for_peer: bool) -> CredentialDAO | None:
        """Observe the task-local credential while another scope is active.

        Args:
            credential (CredentialDAO): Capture for this asynchronous operation.
            wait_for_peer (bool): Whether to wait for the sibling scope.

        Returns:
            CredentialDAO | None: The operation-local capture.
        """
        with CredentialResolver.bind_operation_credential(credential=credential):
            entered.set()
            if wait_for_peer:
                await release.wait()
            else:
                await entered.wait()
                release.set()
            return CredentialResolver._build_credential.get()

    observed = await asyncio.gather(
        observe(credential=first, wait_for_peer=True),
        observe(credential=second, wait_for_peer=False),
    )

    assert observed == [first, second]
    assert CredentialResolver._build_credential.get() is None
