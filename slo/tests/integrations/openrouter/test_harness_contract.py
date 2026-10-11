"""Default-gate production-boundary checks for the fixture-only opt-in harness."""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from tests.integrations.openrouter.test_live_openrouter import OpenRouterLiveHarness
from tests.integrations.openrouter import test_live_openrouter as harness_module
from src.integrations.openrouter.exceptions import OpenRouterAPIError
from tests.integration.test_openrouter_full_flow import isolated_catalog
from src.auth.credential_store import CredentialStore
from src.auth.openrouter_authentication import OpenRouterAuthenticationService
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.agents.model_catalog.service import ModelCatalogService

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "openrouter"
ROUTE = "openrouter:vendor/fixture-coder"


def credential() -> CredentialDAO:
    """Supply an authored sentinel, never a host credential."""
    return CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture-harness-only"
    )


@pytest.mark.parametrize("mode", [None, "", "live", "paid-smoke"])
async def test_disabled_entry_precedes_all_construction(mode: str | None) -> None:
    """Deny missing/invalid consent before resolver, HTTP or production client construction."""
    environment = {} if mode is None else {"SLO_OPENROUTER_LIVE_HARNESS": mode}
    with (
        patch("httpx.AsyncClient", side_effect=AssertionError("constructed")),
        patch(
            "tests.integrations.openrouter.test_live_openrouter.OpenRouterAPIClient",
            side_effect=AssertionError("constructed"),
        ),
    ):
        with pytest.raises(PermissionError, match="disabled"):
            await OpenRouterLiveHarness.invoke_fixture(
                environment=environment,
                credential_resolver=lambda: pytest.fail("resolved"),
                handler=lambda request: pytest.fail("network"),
                model_name=ROUTE,
            )


async def test_discovery_consumes_key_then_models_through_real_client_and_converter() -> None:
    """Use the checked-in bundle as wire data, not as a shape-only assertion."""
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        """Serve only authenticated metadata at the real fixed origin."""
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] == "Bearer fixture-harness-only"
        paths.append(request.url.path)
        filename = {"/api/v1/key": "key-valid.json", "/api/v1/models/user": "models-user-page.json"}[
            request.url.path
        ]
        return httpx.Response(status_code=200, content=(FIXTURES / filename).read_bytes())

    result = await OpenRouterLiveHarness.invoke_fixture(
        environment={"SLO_OPENROUTER_LIVE_HARNESS": "fixture-discovery"},
        credential_resolver=credential,
        handler=handler,
        model_name=None,
    )
    assert paths == ["/api/v1/key", "/api/v1/models/user"]
    assert result.model_names == (ROUTE,)
    assert result.inference_requests == 0
    assert "fixture-harness-only" not in repr(result)


@pytest.mark.parametrize(
    "outcome", ["answer", "extra_tool", "rate_limit", "wrong_tool", "tool_args", "multiple_tools"]
)
async def test_paid_fixture_enforces_two_requests_tool_continuation_and_no_retry(outcome: str) -> None:
    """Cross actual SDK/adapter with bundle SSE and private anchor, not fake model output."""
    posts: list[dict[str, object]] = []
    anchor = json.loads((FIXTURES / "private-anchor.json").read_text())

    async def handler(request: httpx.Request) -> httpx.Response:
        """Serve metadata then at most two real SDK requests using synthetic bytes."""
        if request.method == "GET":
            filename = {"/api/v1/key": "key-valid.json", "/api/v1/models/user": "models-user-page.json"}[
                request.url.path
            ]
            return httpx.Response(status_code=200, content=(FIXTURES / filename).read_bytes())
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        body = json.loads(request.content)
        posts.append(body)
        assert body["model"] == "vendor/fixture-coder"
        assert body.get("max_tokens", body.get("max_completion_tokens")) == 256
        assert body["stream"] is True
        if outcome == "rate_limit":
            error = json.loads((FIXTURES / "errors.json").read_text())["rate_limit"]
            return httpx.Response(status_code=error["status"], json={"error": error["error"]})
        if len(posts) == 1 or outcome == "extra_tool":
            frame = json.loads((FIXTURES / "chat-completions-tool.sse").read_text().split("data: ")[1])
            frame["choices"][0]["delta"]["reasoning_details"] = anchor["reasoning_details"]
            calls = frame["choices"][0]["delta"]["tool_calls"]
            if outcome == "wrong_tool":
                calls[0]["function"]["name"] = "bash"
            if outcome == "tool_args":
                calls[0]["function"]["arguments"] = '{"unsafe":true}'
            if outcome == "multiple_tools":
                calls.append({**calls[0], "index": 1, "id": "second"})
        else:
            assert body["messages"][1]["reasoning_details"] == anchor["reasoning_details"]
            assert body["messages"][2] == {
                "role": "tool",
                "content": "fixture-ok",
                "tool_call_id": "call_fixture",
            }
            frame = {
                "id": "done",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "vendor/fixture-coder",
                "choices": [{"index": 0, "delta": {"content": "done"}, "finish_reason": "stop"}],
            }
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=f"data: {json.dumps(frame)}\n\ndata: [DONE]\n\n",
        )

    arguments = dict(
        environment={"SLO_OPENROUTER_LIVE_HARNESS": "fixture-paid-smoke"},
        credential_resolver=credential,
        handler=handler,
        model_name=ROUTE,
    )
    if outcome == "answer":
        result = await OpenRouterLiveHarness.invoke_fixture(**arguments)
        assert result.inference_requests == 2 and result.tool_round_trips == 1
        assert "fixture-private-anchor" not in repr(result)
    else:
        expected = OpenRouterAPIError if outcome == "rate_limit" else ValueError
        with pytest.raises(expected):
            await OpenRouterLiveHarness.invoke_fixture(**arguments)
    assert len(posts) == (2 if outcome in {"answer", "extra_tool"} else 1)


@pytest.mark.parametrize("route", [None, "gpt-5.4", "openrouter:vendor/absent"])
async def test_paid_mode_requires_explicit_discovered_route(route: str | None) -> None:
    """Never select a default route or perform a model sweep."""

    async def handler(request: httpx.Request) -> httpx.Response:
        """Only metadata GETs may precede route admission."""
        assert request.method == "GET"
        filename = {"/api/v1/key": "key-valid.json", "/api/v1/models/user": "models-user-page.json"}[
            request.url.path
        ]
        return httpx.Response(status_code=200, content=(FIXTURES / filename).read_bytes())

    with pytest.raises(ValueError, match="exact discovered route"):
        await OpenRouterLiveHarness.invoke_fixture(
            environment={"SLO_OPENROUTER_LIVE_HARNESS": "fixture-paid-smoke"},
            credential_resolver=credential,
            handler=handler,
            model_name=route,
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://openrouter.ai/api/v1/key",
        "https://other.invalid/api/v1/key",
        "https://openrouter.ai/api/v1/models",
    ],
)
async def test_transport_refuses_other_origins_and_endpoints(url: str) -> None:
    """Public catalog and alternate origins are outside this harness authority."""

    async def handler(request: httpx.Request) -> httpx.Response:
        """Reject any unexpected dispatch locally."""
        pytest.fail("forbidden request dispatched")

    transport = harness_module.BoundedFixtureTransport(handler=handler, model_name=ROUTE, paid=True)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match="bound"):
            await client.get(url)


@pytest.mark.parametrize(
    "body",
    [
        {"model": "vendor/other", "max_tokens": 256},
        {"model": "vendor/fixture-coder", "max_tokens": 257},
        {"model": "vendor/fixture-coder"},
    ],
)
async def test_transport_rejects_route_or_output_budget_violation(body: dict[str, object]) -> None:
    """Reject oversized/missing caps and route changes before the mock responder runs."""

    async def handler(request: httpx.Request) -> httpx.Response:
        """Never receive a request that violates the selected smoke contract."""
        pytest.fail("out-of-budget request reached transport responder")

    transport = harness_module.BoundedFixtureTransport(handler=handler, model_name=ROUTE, paid=True)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match="bound"):
            await client.post("https://openrouter.ai/api/v1/chat/completions", json=body)


async def test_transport_refuses_third_request_and_discovery_inference() -> None:
    """Count attempts before responses; reject a third request and any GET-only-mode POST."""
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        """Count actual accepted requests without sockets."""
        seen.append(request.url.path)
        return httpx.Response(status_code=200, json={})

    for paid in (True, False):
        transport = harness_module.BoundedFixtureTransport(handler=handler, model_name=ROUTE, paid=paid)
        async with httpx.AsyncClient(transport=transport) as client:
            for _ in range(2 if paid else 0):
                await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json={"model": "vendor/fixture-coder", "max_tokens": 256},
                )
            with pytest.raises(ValueError, match="bound"):
                await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json={"model": "vendor/fixture-coder", "max_tokens": 256},
                )
    assert len(seen) == 2


@pytest.mark.parametrize("failure", [None, "authentication", "protocol"])
async def test_bundle_authentication_publication_and_rejection(
    isolated_catalog: CredentialStore,
    failure: str | None,
) -> None:
    """Consume bundle via real candidate auth, persistence, catalog publication and reload."""
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        """Serve synthetic bundle at production endpoints with candidate-before-store proof."""
        seen.append(request.url.path)
        if request.url.path == "/api/v1/key":
            assert not isolated_catalog.additional_providers_path.exists()
            if failure:
                error = json.loads((FIXTURES / "errors.json").read_text())[failure]
                return httpx.Response(status_code=error["status"], json={"error": error["error"]})
            return httpx.Response(status_code=200, content=(FIXTURES / "key-valid.json").read_bytes())
        assert request.url.path == "/api/v1/models/user"
        assert isolated_catalog.additional_providers_path.exists()
        return httpx.Response(status_code=200, content=(FIXTURES / "models-user-page.json").read_bytes())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:

        def factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Inject transport only, retaining all production auth and catalog owners."""
            return OpenRouterAPIClient(credential=credential, http_client=http_client)

        with patch("src.agents.model_catalog.service.OpenRouterAPIClient", side_effect=factory):
            result = await OpenRouterAuthenticationService(
                store=isolated_catalog, client_factory=factory
            ).invoke(
                submitted_key="fixture-harness-only",
            )
    assert result.key_verified is (failure is None)
    assert "fixture-harness-only" not in repr(result)
    if failure:
        assert seen == ["/api/v1/key"]
        assert not isolated_catalog.additional_providers_path.exists()
        return
    assert result.catalog_checked and result.replacement_saved
    assert seen == ["/api/v1/key", "/api/v1/models/user"]
    assert ModelCatalogService.load().entries[ROUTE].runtime_profile.context_window == 64000
    ModelCatalogService.reset()
    assert ModelCatalogService.load().entries[ROUTE].api_model_name == "vendor/fixture-coder"
