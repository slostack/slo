"""Complete pagination must reject repetition before authoritative publication."""

import httpx
import pytest

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.integrations.openrouter.exceptions import OpenRouterDiscoveryIncompleteError


@pytest.mark.parametrize("repeated", [True, False])
async def test_full_pages_require_progress(repeated: bool) -> None:
    """Identical 0/500 pages cannot become a complete 500-row response."""
    offsets: list[str | None] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Supply a pagination hint, two full pages, then an empty terminal page."""
        offset = request.url.params.get("offset")
        offsets.append(offset)
        if offset is None:
            return httpx.Response(status_code=200, json={"data": [], "next": "ignored"})
        start = 0 if repeated else int(offset)
        rows = [{"id": f"vendor/model-{index}"} for index in range(start, start + 500)]
        return httpx.Response(status_code=200, json={"data": [] if offset == "1000" else rows})

    credential = CredentialDAO(provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY,
                               access_token="synthetic-pagination-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = OpenRouterAPIClient(credential=credential, http_client=http)
        if repeated:
            with pytest.raises(OpenRouterDiscoveryIncompleteError):
                await client.list_user_models()
            assert offsets == [None, "0", "500"]
        else:
            result = await client.list_user_models()
            assert len(result.data) == 1000
            assert offsets == [None, "0", "500", "1000"]
