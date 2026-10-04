"""Offline contract tests for the fixed OpenRouter GET boundary."""

from __future__ import annotations

import httpx
import pytest

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName


async def test_get_current_key_when_valid_shape_returns_safe_verification() -> None:
    """Verify the injected transport receives the captured key without leaking it."""
    secret: str = "test-openrouter-secret"
    seen_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        """Return a documented key envelope from the local transport."""
        seen_requests.append(request)
        return httpx.Response(status_code=200, json={"data": {"label": "private-account-label"}})

    from src.integrations.openrouter.client import OpenRouterAPIClient

    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token=secret,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client: OpenRouterAPIClient = OpenRouterAPIClient(credential=credential, http_client=http_client)
        verification = await client.get_current_key()

    assert verification.credential_fingerprint
    assert seen_requests[0].url == httpx.URL("https://openrouter.ai/api/v1/key")
    assert seen_requests[0].headers["authorization"] == f"Bearer {secret}"
    assert secret not in repr(verification)


async def test_list_user_models_when_total_requires_offset_pagination() -> None:
    """Restart listing at offset zero when the unpaged envelope is incomplete."""
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        """Return an unpaged hint then deterministic 500-row page envelopes."""
        requests.append(request)
        offset: str | None = request.url.params.get("offset")
        if offset is None:
            return httpx.Response(status_code=200, json={"data": [{"id": "first"}], "total_count": 501})
        if offset == "0":
            return httpx.Response(
                status_code=200,
                json={"data": [{"id": f"model-{index}"} for index in range(500)], "total_count": 501},
            )
        if offset == "500":
            return httpx.Response(status_code=200, json={"data": [{"id": "model-500"}], "total_count": 501})
        raise AssertionError(f"Unexpected offset {offset}")

    from src.integrations.openrouter.client import OpenRouterAPIClient

    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-openrouter-secret",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client: OpenRouterAPIClient = OpenRouterAPIClient(credential=credential, http_client=http_client)
        response = await client.list_user_models()

    assert len(response.data) == 501
    assert [(request.url.params.get("offset"), request.url.params.get("limit")) for request in requests] == [
        (None, None),
        ("0", "500"),
        ("500", "500"),
    ]


async def test_list_user_models_when_page_count_is_exact_multiple_fetches_empty_terminal_page() -> None:
    """Fetch the required empty terminal page when a page exactly fills the limit."""
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        """Return an incomplete unpaged list followed by a full and empty page."""
        requests.append(request)
        offset: str | None = request.url.params.get("offset")
        if offset is None:
            return httpx.Response(status_code=200, json={"data": [{"id": "first"}], "total_count": 500})
        if offset == "0":
            return httpx.Response(
                status_code=200,
                json={"data": [{"id": f"model-{index}"} for index in range(500)], "total_count": 500},
            )
        if offset == "500":
            return httpx.Response(status_code=200, json={"data": [], "total_count": 500})
        raise AssertionError(f"Unexpected offset {offset}")

    from src.integrations.openrouter.client import OpenRouterAPIClient

    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-openrouter-secret",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client: OpenRouterAPIClient = OpenRouterAPIClient(credential=credential, http_client=http_client)
        response = await client.list_user_models()

    assert len(response.data) == 500
    assert [request.url.params.get("offset") for request in requests] == [None, "0", "500"]


async def test_list_user_models_when_response_has_missing_data_rejects_incomplete_envelope() -> None:
    """Reject a successful envelope that cannot prove an authenticated list exists."""
    from src.integrations.openrouter.client import OpenRouterAPIClient
    from src.integrations.openrouter.exceptions import OpenRouterDiscoveryIncompleteError

    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-openrouter-secret",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        """Return an invalid success envelope from the local transport."""
        return httpx.Response(status_code=200, json={"total_count": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client: OpenRouterAPIClient = OpenRouterAPIClient(credential=credential, http_client=http_client)
        with pytest.raises(OpenRouterDiscoveryIncompleteError):
            await client.list_user_models()


async def test_get_current_key_when_redirected_rejects_response() -> None:
    """Treat every redirect as an invalid fixed-origin verification response."""
    from src.integrations.openrouter.client import OpenRouterAPIClient
    from src.integrations.openrouter.exceptions import OpenRouterProtocolError

    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-openrouter-secret",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        """Return a local redirect without allowing an external follow-up request."""
        return httpx.Response(status_code=302, headers={"location": "https://example.invalid"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client: OpenRouterAPIClient = OpenRouterAPIClient(credential=credential, http_client=http_client)
        with pytest.raises(OpenRouterProtocolError):
            await client.get_current_key()


async def test_get_current_key_when_transport_raises_normalizes_without_exception_chain() -> None:
    """Hide transport text and traceback context at the boundary's public exception seam."""
    from src.integrations.openrouter.client import OpenRouterAPIClient
    from src.integrations.openrouter.exceptions import OpenRouterAPIError

    secret: str = "test-openrouter-secret"
    marker: str = "raw-transport-marker"
    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token=secret,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        """Raise a synthetic transport failure containing an upstream marker."""
        raise httpx.ReadTimeout(marker, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client: OpenRouterAPIClient = OpenRouterAPIClient(credential=credential, http_client=http_client)
        with pytest.raises(OpenRouterAPIError) as raised:
            await client.get_current_key()

    assert raised.value.__cause__ is None
    assert marker not in str(raised.value)
    assert secret not in repr(raised.value)


async def test_list_user_models_when_pagination_total_changes_from_initial_response_rejects() -> None:
    """Keep the unpaged total as the pagination operation's immutable contract."""
    from src.integrations.openrouter.client import OpenRouterAPIClient
    from src.integrations.openrouter.exceptions import OpenRouterDiscoveryIncompleteError

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-openrouter-secret",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        """Return a contradictory total only after pagination restarts."""
        offset = request.url.params.get("offset")
        if offset is None:
            return httpx.Response(status_code=200, json={"data": [{"id": "first"}], "total_count": 501})
        if offset == "0":
            return httpx.Response(
                status_code=200,
                json={"data": [{"id": f"model-{index}"} for index in range(500)], "total_count": 502},
            )
        return httpx.Response(status_code=200, json={"data": [], "total_count": 502})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenRouterAPIClient(credential=credential, http_client=http_client)
        with pytest.raises(OpenRouterDiscoveryIncompleteError):
            await client.list_user_models()


async def test_list_user_models_when_duplicate_records_are_equal_deduplicates_them() -> None:
    """Accept repeated page records only when their complete mapping is identical."""
    from src.integrations.openrouter.client import OpenRouterAPIClient

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-openrouter-secret",
    )
    repeated: dict[str, object] = {"id": "model-499", "context_length": 1000}

    async def handler(request: httpx.Request) -> httpx.Response:
        """Return a boundary duplicate followed by one unique record."""
        offset = request.url.params.get("offset")
        if offset is None:
            return httpx.Response(status_code=200, json={"data": [{"id": "first"}], "total_count": 501})
        if offset == "0":
            records: list[dict[str, object]] = [{"id": f"model-{index}"} for index in range(500)]
            records[-1] = repeated
            return httpx.Response(status_code=200, json={"data": records, "total_count": 501})
        return httpx.Response(
            status_code=200,
            json={"data": [repeated, {"id": "model-500"}], "total_count": 501},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenRouterAPIClient(credential=credential, http_client=http_client)
        response = await client.list_user_models()

    assert len(response.data) == 501
    assert response.data[-1] == {"id": "model-500"}


async def test_list_user_models_when_aggregate_response_bytes_exceed_limit_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enforce the byte cap across the complete paginated operation, not per page."""
    import src.integrations.openrouter.client as client_module
    from src.integrations.openrouter.client import OpenRouterAPIClient
    from src.integrations.openrouter.exceptions import OpenRouterProtocolError

    monkeypatch.setattr(client_module, "_MAX_RESPONSE_BYTES", 200)
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-openrouter-secret",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        """Produce individually small pages whose aggregate crosses the bound."""
        offset = request.url.params.get("offset")
        if offset is None:
            return httpx.Response(status_code=200, json={"data": [{"id": "first"}], "total_count": 501})
        if offset == "0":
            return httpx.Response(
                status_code=200,
                json={"data": [{"id": f"model-{index:03d}"} for index in range(500)], "total_count": 501},
            )
        return httpx.Response(status_code=200, json={"data": [{"id": "model-500"}], "total_count": 501})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenRouterAPIClient(credential=credential, http_client=http_client)
        with pytest.raises(OpenRouterProtocolError):
            await client.list_user_models()


async def test_list_user_models_when_stream_exceeds_cap_stops_before_full_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an oversized streamed body without eagerly materializing response content."""
    import src.integrations.openrouter.client as client_module
    from src.integrations.openrouter.client import OpenRouterAPIClient
    from src.integrations.openrouter.exceptions import OpenRouterProtocolError

    monkeypatch.setattr(client_module, "_MAX_RESPONSE_BYTES", 8)
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-openrouter-secret",
    )

    class ChunkedStream(httpx.AsyncByteStream):
        """Provide a deterministic two-chunk response body."""

        async def __aiter__(self):
            """Yield a valid prefix followed by an over-limit suffix."""
            yield b'{"data":'
            yield b"[]}"

        async def aclose(self) -> None:
            """Implement the transport stream close protocol."""
            return None

    async def handler(request: httpx.Request) -> httpx.Response:
        """Return an explicitly streamed local response."""
        return httpx.Response(status_code=200, stream=ChunkedStream())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenRouterAPIClient(credential=credential, http_client=http_client)
        with pytest.raises(OpenRouterProtocolError):
            await client.list_user_models()


async def test_openrouter_client_context_closes_owned_client_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close only a client created by the boundary even when its request fails."""
    from src.integrations.openrouter.client import OpenRouterAPIClient
    from src.integrations.openrouter.exceptions import OpenRouterAPIError

    closed: list[bool] = []

    class OwnedClient:
        """Provide a closing stream client without network authority."""

        async def aclose(self) -> None:
            """Record owned-client teardown."""
            closed.append(True)

        def stream(self, **kwargs: object) -> object:
            """Raise an HTTP error before a response context is entered."""
            raise httpx.ReadTimeout(
                "local", request=httpx.Request(method="GET", url="https://example.invalid")
            )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-openrouter-secret",
    )
    owned_client = OwnedClient()
    client = OpenRouterAPIClient(credential=credential)
    client._http_client = owned_client  # type: ignore[assignment]
    with pytest.raises(OpenRouterAPIError):
        async with client:
            await client.get_current_key()

    assert closed == [True]


async def test_get_current_key_when_unauthorized_raises_safe_error() -> None:
    """Reject unauthorised replies without retaining an upstream body marker."""
    secret: str = "test-openrouter-secret"
    marker: str = "raw-upstream-body-marker"

    async def handler(request: httpx.Request) -> httpx.Response:
        """Return an unauthorised local response."""
        return httpx.Response(status_code=401, json={"error": {"message": marker}})

    from src.integrations.openrouter.client import OpenRouterAPIClient
    from src.integrations.openrouter.exceptions import OpenRouterAuthenticationError

    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token=secret,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client: OpenRouterAPIClient = OpenRouterAPIClient(credential=credential, http_client=http_client)
        with pytest.raises(OpenRouterAuthenticationError) as raised:
            await client.get_current_key()

    assert secret not in str(raised.value)
    assert marker not in str(raised.value)
