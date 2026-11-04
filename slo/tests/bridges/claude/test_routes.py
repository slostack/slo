"""Qualified route admission and honest local catalog projections."""

from pathlib import Path

import pytest

from config.ai_model_config import resolve_model_name_with_fallback
from src.agents.base import LLMFactory
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
from src.auth.credential_dao import ProviderName
from src.auth.provider_for_model import provider_for_model
from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.claude.routes import ClaudeBridgeRoute
from src.tui.model_catalog import model_suggestion_entries
from src.bridges.claude.sdk.dao import ClaudeSessionOptionsDAO
from src.bridges.claude.sdk.sdk_runtime import ClaudeSDKRuntime
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, scripted_adapter_class


@pytest.mark.parametrize("route", ClaudeBridgeRoute.model_names())
async def test_requested_route_stays_qualified_through_catalog_config_and_factory(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """Local selection does not claim provider availability or use direct Anthropic."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()
    assert provider_for_model(model_name=route) is ProviderName.ANTHROPIC
    assert resolve_model_name_with_fallback(model_name=route) == (route, None)
    snapshot = ModelCatalogService.load()
    entry = ModelCatalogService.entry_for_model(model_name=route, snapshot=snapshot)
    assert entry.model_name == entry.api_model_name == route
    options = ClaudeSDKRuntime._build_options(
        session_options=ClaudeSessionOptionsDAO(
            session_id="synthetic", model_id=route, working_directory=Path("/tmp"), instructions="host"
        )
    )
    assert options.model == route.removeprefix("claude-bridge:")
    assert options.tools == []
    assert options.mcp_servers == {}
    assert route not in snapshot.entries
    rows = model_suggestion_entries(active_model_name=route, snapshot=snapshot)
    row = next(row for row in rows if row.model_name == route)
    assert not row.requires_auth
    assert "unchecked" in row.status_summary
    assert "host planning" in row.status_summary
    assert row.reasoning_controls_available
    from src.tui.slash_suggestion_engine import SlashSuggestionEngine

    detail = SlashSuggestionEngine._model_detail(entry=row)
    assert "native capacity unverified" in detail
    assert "native effort" in detail
    product = LLMFactory.create(
        model_name=route, bridge_adapter_class=scripted_adapter_class(transport=transport)
    )
    assert isinstance(product.llm, SloClaudeBridge)
    assert product.llm.model_name == route
    assert product.bridge_owner is product.llm
    assert not transport.connected
    await product.bridge_owner.close()


@pytest.mark.parametrize("bridge_first", [False, True])
def test_pool_rejects_bridge_before_constructing_any_member(
    monkeypatch: pytest.MonkeyPatch, bridge_first: bool
) -> None:
    """No direct credential lookup or native registration may precede pool rejection."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    monkeypatch.delenv(name="SLO_ANTHROPIC_API_KEY", raising=False)
    names = ["claude-sonnet-4-6", "claude-bridge:claude-haiku-5-5"]
    if bridge_first:
        names.reverse()
    pool = ModelPoolDAO(
        entries=[ModelPoolEntryDAO(model_name=name, provider=ProviderName.ANTHROPIC) for name in names]
    )
    with pytest.raises(ValueError, match="bridge.*pool|pool.*bridge"):
        LLMFactory.create_pool(pool_dao=pool)


@pytest.mark.parametrize(
    "route",
    [
        "claude-bridge:",
        "claude-bridge:claude-opus-5-6",
        "claude-bridge:opus",
        "claude-bridge:claude-haiku-4-7",
    ],
)
def test_invalid_or_disabled_route_never_falls_back(monkeypatch: pytest.MonkeyPatch, route: str) -> None:
    """Explicit unsupported routes fail rather than becoming a direct default."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    with pytest.raises(ValueError):
        resolve_model_name_with_fallback(model_name=route)
    monkeypatch.delenv(name="SLO_CLAUDE_BRIDGE_ENABLED")
    with pytest.raises(ValueError, match="opt-in"):
        provider_for_model(model_name="claude-bridge:claude-sonnet-4-6")
    assert not any(
        row.model_name.startswith(ClaudeBridgeRoute.PREFIX)
        for row in model_suggestion_entries(active_model_name="gpt-5.4")
    )


def test_portable_sdk_public_imports_are_available() -> None:
    """The SDK package exposes its public boundary without importing host modules."""
    import src.bridges.claude.sdk as sdk
    from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
    from src.bridges.claude.sdk.protocol import SloBridgeAdapterProtocol

    assert sdk.SloClaudeBridgeAdapter is SloClaudeBridgeAdapter
    assert sdk.SloBridgeAdapterProtocol is SloBridgeAdapterProtocol
    assert sdk.ClaudeSessionOptionsDAO is not None
    assert sdk.ClaudeBridgeError is not None


def test_portable_sdk_package_has_no_host_imports() -> None:
    """Portable modules use relative internal imports and no Slo/LangChain/Textual."""
    package = Path(__file__).parents[3] / "src" / "bridges" / "claude" / "sdk"
    for path in package.glob("*.py"):
        content = path.read_text()
        assert "from src." not in content
        assert "import src." not in content
        assert "langchain" not in content
        assert "textual" not in content


@pytest.mark.parametrize(
    ("level", "effort"),
    [
        ("off", None),
        ("minimal", "low"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "xhigh"),
        ("max", "max"),
    ],
)
async def test_bridge_reasoning_reaches_native_effort(monkeypatch, tmp_path, level, effort):
    """The real factory and bridge carry Slo reasoning into SDK effort and thinking."""
    from langchain_core.messages import HumanMessage
    from src.bridges.dao import SloBridgeSessionOptionsDAO
    from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
    from src.bridges.claude.sdk.dao import ClaudeAuthenticationStatusDAO, ClaudeBridgeConfigurationDAO

    monkeypatch.setenv("SLO_CLAUDE_BRIDGE_ENABLED", "1")
    captured = []

    async def ready():
        return ClaudeAuthenticationStatusDAO(state="ready", safe_message="Ready")

    class Adapter(SloClaudeBridgeAdapter):
        async def start_session(self, *, session_options):
            captured.append(session_options)
            await super().start_session(session_options=session_options)

    transport = ScriptedClaudeTransport()
    prepared = Adapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready,
    )
    product = LLMFactory.create(
        model_name="claude-bridge:claude-opus-4-8",
        reasoning_level=level,
        bridge_adapter=prepared,
    )
    product.bridge_owner.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="effort-test",
            working_directory=tmp_path,
            instructions="host",
        )
    )
    try:
        _ = [chunk async for chunk in product.llm.astream([HumanMessage(content="hello")])]
    finally:
        await prepared.close()
    assert len(captured) == 1
    assert captured[0].effort == effort
    options = ClaudeSDKRuntime._build_options(session_options=captured[0])
    assert options.effort == effort
    assert options.thinking == {"type": "disabled" if effort is None else "adaptive"}
    assert "bare" not in options.extra_args
