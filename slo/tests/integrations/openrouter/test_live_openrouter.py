"""Opt-in OpenRouter live-harness contract tests.

These tests are e2e-marked and disabled unless an operator sets the explicit
fixture-only switch. They never resolve credentials or create an HTTP client
before that switch is accepted. The checked-in executions use synthetic
credentials plus ``httpx.MockTransport`` to prove the harness gate and safe
output boundary; they do not contact OpenRouter.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
import pytest

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.integrations.openrouter.client import OpenRouterAPIClient

pytestmark = pytest.mark.e2e

_LIVE_HARNESS_ENVIRONMENT_VARIABLE = "SLO_OPENROUTER_LIVE_HARNESS"


def _fixture_echo() -> str:
    """Return a fixed harmless in-memory result; no external or filesystem effects."""
    return "fixture-ok"


class FixtureRequestHandler(Protocol):
    """Callable accepted by ``httpx.MockTransport`` without default network authority."""

    def __call__(self, request: httpx.Request) -> Coroutine[None, None, httpx.Response]:
        """Return one local response for a captured request."""


class BoundedFixtureTransport(httpx.MockTransport):
    """Enforce smoke authority before handing a request to the in-memory responder."""

    def __init__(self, *, handler: FixtureRequestHandler, model_name: str | None, paid: bool) -> None:
        """Capture explicit authority and a fresh per-run attempt counter."""
        super().__init__(handler=handler)
        self.model_name = model_name
        self.paid = paid
        self.attempts = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Reject wrong origins, endpoints, routes, caps and excess attempts before dispatch."""
        if request.url.host != "openrouter.ai" or request.url.scheme != "https":
            raise ValueError("Fixture transport origin bound violated.")
        if request.method == "GET" and request.url.path in {"/api/v1/key", "/api/v1/models/user"}:
            return await super().handle_async_request(request)
        self._admit_inference(request=request)
        return await super().handle_async_request(request)

    def _admit_inference(self, *, request: httpx.Request) -> None:
        """Count every admitted attempt, including failures; never reset on failure."""
        if (
            not self.paid
            or self.attempts >= 2
            or request.method != "POST"
            or request.url.path != "/api/v1/chat/completions"
        ):
            raise ValueError("Fixture inference request bound violated.")
        body = json.loads(request.content)
        cap = body.get("max_tokens", body.get("max_completion_tokens"))
        if (
            body.get("model") != (self.model_name or "").removeprefix("openrouter:")
            or type(cap) is not int
            or not 0 < cap <= 256
        ):
            raise ValueError("Fixture route/output bound violated.")
        self.attempts += 1


@dataclass(frozen=True)
class OpenRouterLiveHarnessConfig:
    """Validated, explicitly enabled live-harness configuration.

    The configuration intentionally contains no credential, route, or endpoint.
    Credential resolution is a caller-supplied dependency after this opt-in gate.
    """

    mode: Literal["authenticated_discovery", "paid_smoke"]
    paid_request_cap: int
    output_token_cap: int


@dataclass(frozen=True)
class FixtureHarnessResult:
    """Safe counters; no credential, account response or private continuation."""

    model_names: tuple[str, ...]
    inference_requests: int = 0
    tool_round_trips: int = 0


class OpenRouterLiveHarness:
    """Build fixture-driven OpenRouter checks only after explicit opt-in."""

    @classmethod
    async def invoke_fixture(
        cls,
        *,
        environment: dict[str, str],
        credential_resolver: Callable[[], CredentialDAO],
        handler: FixtureRequestHandler,
        model_name: str | None,
    ) -> FixtureHarnessResult:
        """Run consented synthetic discovery through the production GET/converter boundary.

        Args:
            environment: Explicit consent mapping.
            credential_resolver: Synthetic credential supplier, called only after consent.
            handler: In-memory response supplier; never a socket transport.
            model_name: Exact selected route for separately consented tool smoke.

        Returns:
            FixtureHarnessResult: Safe counters and canonical identities.
        """
        config = cls.require_opt_in(environment=environment)
        if config.mode == "paid_smoke" and not model_name:
            raise ValueError("Select one exact discovered route for fixture smoke.")
        config, client = cls.open_fixture_client_when_enabled(
            environment=environment,
            credential_resolver=credential_resolver,
            handler=handler,
            model_name=model_name,
        )
        assert client._http_client is not None
        async with client._http_client:
            await client.get_current_key()
            response = await client.list_user_models()
            converted = OpenRouterCatalogConverter.invoke(response=response, now=datetime.now(timezone.utc))
            names = tuple(converted.available_model_names)
            if config.mode == "authenticated_discovery":
                return FixtureHarnessResult(model_names=names)
            entries = [
                entry
                for entry in converted.entries
                if entry.model_name == model_name and entry.visible_in_picker
            ]
            if len(entries) != 1:
                raise ValueError("Select one exact discovered route for fixture smoke.")
            entry = entries[0]
            model = OpenRouterChatOpenAI(
                slo_model_name=entry.model_name,
                model=entry.api_model_name,
                api_key=client._credential.access_token,
                base_url="https://openrouter.ai/api/v1",
                http_async_client=client._http_client,
                max_retries=0,
                max_tokens=config.output_token_cap,
                streaming=True,
                use_responses_api=False,
                slo_capabilities=entry.capabilities,
                slo_output_ceiling=config.output_token_cap,
            )
            return await cls._round_trip(model=model, names=names)

    @staticmethod
    async def _round_trip(*, model: OpenRouterChatOpenAI, names: tuple[str, ...]) -> FixtureHarnessResult:
        """Execute exactly one no-argument in-memory tool and refuse further tool work."""
        tool = StructuredTool.from_function(func=_fixture_echo, name="fixture_echo")
        bound = model.bind_tools([tool])
        prompt = HumanMessage(content="Call fixture_echo once, then report its result.")
        assistant = await bound.ainvoke([prompt])
        assert isinstance(assistant, AIMessage)
        calls = assistant.tool_calls
        if len(calls) != 1 or calls[0]["name"] != tool.name or calls[0]["args"] != {}:
            raise ValueError("Fixture smoke requires exactly one harmless tool call.")
        output = await tool.ainvoke(calls[0]["args"])
        answer = await bound.ainvoke(
            [
                prompt,
                assistant,
                ToolMessage(content=output, tool_call_id=calls[0]["id"]),
            ]
        )
        assert isinstance(answer, AIMessage)
        if answer.tool_calls:
            raise ValueError("Fixture smoke request bound reached; refusing another tool call.")
        return FixtureHarnessResult(model_names=names, inference_requests=2, tool_round_trips=1)

    @classmethod
    def require_opt_in(cls, *, environment: dict[str, str]) -> OpenRouterLiveHarnessConfig:
        """Validate the harness switch before credential resolution or network construction.

        WHAT: Reads only the supplied environment mapping and admits a bounded
            fixture mode when the exact opt-in value is present.
        WHO: The live test entry point calls this before it asks a resolver for a
            credential or constructs an HTTP client.
        WHEN: Runs at the first executable boundary of an explicitly requested e2e test.

        Args:
            environment (dict[str, str]): Explicit environment view supplied by the caller.

        Returns:
            OpenRouterLiveHarnessConfig: The bounded mode configuration.

        Raises:
            PermissionError: If the explicit live-harness switch is absent or invalid.
        """
        value: str | None = environment.get(_LIVE_HARNESS_ENVIRONMENT_VARIABLE)
        if value == "fixture-discovery":
            return OpenRouterLiveHarnessConfig(
                mode="authenticated_discovery",
                paid_request_cap=0,
                output_token_cap=0,
            )
        if value == "fixture-paid-smoke":
            return OpenRouterLiveHarnessConfig(
                mode="paid_smoke",
                paid_request_cap=2,
                output_token_cap=256,
            )
        raise PermissionError(
            "OpenRouter live harness is disabled; set "
            "SLO_OPENROUTER_LIVE_HARNESS=fixture-discovery or fixture-paid-smoke."
        )

    @classmethod
    def open_fixture_client_when_enabled(
        cls,
        *,
        environment: dict[str, str],
        credential_resolver: Callable[[], CredentialDAO],
        handler: FixtureRequestHandler,
        model_name: str | None = None,
    ) -> tuple[OpenRouterLiveHarnessConfig, OpenRouterAPIClient]:
        """Resolve a supplied synthetic credential and bind it to mock-only transport.

        WHAT: Gates the fixture transport before resolving an injected credential.
        WHO: Explicit-opt-in tests use this seam to exercise safe discovery output.
        WHEN: Runs at the live-harness entry point, before credential or network work.

        Args:
            environment (dict[str, str]): Explicit environment view containing the opt-in switch.
            credential_resolver (Callable[[], CredentialDAO]): Injected synthetic credential source.
            handler (FixtureRequestHandler): In-memory HTTP response handler.

        Returns:
            tuple[OpenRouterLiveHarnessConfig, OpenRouterAPIClient]: Bounds and an existing
                client with no default transport authority.
        """
        config: OpenRouterLiveHarnessConfig = cls.require_opt_in(environment=environment)
        credential: CredentialDAO = credential_resolver()
        if credential.provider is not ProviderName.OPENROUTER:
            raise ValueError("OpenRouter fixture harness requires an OpenRouter credential.")
        http_client: httpx.AsyncClient = httpx.AsyncClient(
            transport=BoundedFixtureTransport(
                handler=handler,
                model_name=model_name,
                paid=config.mode == "paid_smoke",
            )
        )
        return config, OpenRouterAPIClient(credential=credential, http_client=http_client)


async def test_live_harness_when_disabled_rejects_before_credential_resolution_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject default execution without calling an injected credential resolver."""
    monkeypatch.delenv(_LIVE_HARNESS_ENVIRONMENT_VARIABLE, raising=False)
    resolver_called: bool = False

    def resolver() -> CredentialDAO:
        """Fail if a disabled harness tries to resolve a credential."""
        nonlocal resolver_called
        resolver_called = True
        raise AssertionError("credential resolution must not occur while disabled")

    async def handler(request: httpx.Request) -> httpx.Response:
        """Fail if a disabled harness tries to create a request."""
        raise AssertionError(f"network must not occur while disabled: {request.url}")

    with pytest.raises(PermissionError, match="disabled"):
        OpenRouterLiveHarness.open_fixture_client_when_enabled(
            environment={},
            credential_resolver=resolver,
            handler=handler,
        )
    assert not resolver_called


async def test_live_harness_when_fixture_discovery_is_enabled_uses_synthetic_resolver_and_safe_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise enabled discovery through mock transport without exposing the synthetic key."""
    monkeypatch.setenv(_LIVE_HARNESS_ENVIRONMENT_VARIABLE, "fixture-discovery")
    synthetic_key: str = "fixture-live-harness-key"
    seen_authorization: list[str] = []

    def resolver() -> CredentialDAO:
        """Return the test-only credential after the opt-in gate passed."""
        return CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=synthetic_key,
        )

    async def handler(request: httpx.Request) -> httpx.Response:
        """Provide a synthetic authenticated-list response without socket I/O."""
        seen_authorization.append(request.headers["authorization"])
        assert request.url.path == "/api/v1/models/user"
        return httpx.Response(status_code=200, json={"data": [{"id": "fixture/model"}]})

    config: OpenRouterLiveHarnessConfig
    client: OpenRouterAPIClient
    config, client = OpenRouterLiveHarness.open_fixture_client_when_enabled(
        environment={"SLO_OPENROUTER_LIVE_HARNESS": "fixture-discovery"},
        credential_resolver=resolver,
        handler=handler,
    )
    try:
        response = await client.list_user_models()
    finally:
        http_client: httpx.AsyncClient | None = client._http_client
        assert http_client is not None
        await http_client.aclose()

    assert config.mode == "authenticated_discovery"
    assert config.paid_request_cap == 0
    assert [record["id"] for record in response.data] == ["fixture/model"]
    assert seen_authorization == [f"Bearer {synthetic_key}"]
    assert synthetic_key not in repr(response) + response.model_dump_json()


def test_live_harness_when_paid_fixture_mode_is_enabled_sets_documented_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Document the paid opt-in cap without making a paid inference request."""
    monkeypatch.setenv(_LIVE_HARNESS_ENVIRONMENT_VARIABLE, "fixture-paid-smoke")

    config: OpenRouterLiveHarnessConfig = OpenRouterLiveHarness.require_opt_in(
        environment={"SLO_OPENROUTER_LIVE_HARNESS": "fixture-paid-smoke"}
    )

    assert config.mode == "paid_smoke"
    assert config.paid_request_cap == 2
    assert config.output_token_cap == 256
