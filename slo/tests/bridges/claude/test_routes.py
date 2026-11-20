"""Qualified route admission and honest local catalog projections."""

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk._internal.transport import Transport
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from config.ai_model_config import resolve_model_name_with_fallback
from src.agents.base import LLMFactory
from src.agents.model_catalog.dao import ReasoningLevel
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
from src.auth.credential_dao import ProviderName
from src.auth.provider_for_model import provider_for_model
from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.claude.routes import ClaudeBridgeRoute
from src.tui.model_catalog import model_suggestion_entries
from src.bridges.claude.sdk.dao import ClaudeSessionOptionsDAO
from src.bridges.claude.sdk.native_transport import ClaudeNativeTransport
from src.bridges.claude.sdk.sdk_runtime import ClaudeSDKRuntime
from src.bridges.dao import SloBridgeSessionOptionsDAO
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
    assert entry.model_name == route
    assert entry.api_model_name == ClaudeBridgeRoute.native_model_id(model_name=route)
    options = ClaudeSDKRuntime._build_options(
        session_options=ClaudeSessionOptionsDAO(
            session_id="synthetic",
            model_id=route,
            native_model_id=ClaudeBridgeRoute.native_model_id(model_name=route),
            working_directory=Path("/tmp"),
            instructions="host",
        )
    )
    assert options.model == ClaudeBridgeRoute.native_model_id(model_name=route)
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
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="0")
    with pytest.raises(ValueError, match="disabled"):
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


@pytest.mark.parametrize("value", [None, "", "1", "true", "YES", "on", "  true  "])
def test_bridge_enabled_unless_explicitly_disabled(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    """Default configuration exposes qualified routes without native authentication."""
    from config.cfg import cfg

    monkeypatch.delenv(name="SLO_CLAUDE_BRIDGE_ENABLED", raising=False)
    monkeypatch.delenv(name="SLO_DEV_MODE", raising=False)
    if value is not None:
        monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value=value)
    assert cfg("SLO_CLAUDE_BRIDGE_ENABLED") == ("1" if value is None else value)
    assert ClaudeBridgeRoute.is_enabled()
    assert provider_for_model(model_name="claude-bridge:claude-sonnet-4-6") is ProviderName.ANTHROPIC
    assert any(
        row.model_name == "claude-bridge:claude-sonnet-4-6"
        for row in model_suggestion_entries(active_model_name="gpt-5.4")
    )


@pytest.mark.parametrize("value", ["0", "false", "NO", "off", "  False  "])
def test_explicit_disable_hides_and_rejects_bridge_routes(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Explicit opt-out removes discovery and rejects direct selection without fallback."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value=value)
    assert not ClaudeBridgeRoute.is_enabled()
    with pytest.raises(ValueError, match="disabled"):
        resolve_model_name_with_fallback(model_name="claude-bridge:claude-sonnet-4-6")
    assert not any(
        row.model_name.startswith(ClaudeBridgeRoute.PREFIX)
        for row in model_suggestion_entries(active_model_name="gpt-5.4")
    )


FABLE_NATIVE_IDS_BY_ROUTE: dict[str, str] = {
    "claude-bridge:claude-fable": "claude-fable-5-1",
    "claude-bridge:claude-fable-5-1": "claude-fable-5-1",
    "claude-bridge:claude-fable-5": "claude-fable-5",
}
"""Literal oracle for the explicit Fable routes: the family route targets Fable 5.1."""

INVENTED_FABLE_ROUTES: tuple[str, ...] = tuple(
    f"claude-bridge:claude-fable-{version}" for version in ("4-8", "4-9", "5-0", "5-2", "5-3", "5-4", "5-5")
)
"""Fable versions the former generated grid offered; the pinned CLI does not define them."""

PINNED_CLI_FABLE_NATIVE_IDS: frozenset[str] = frozenset({"claude-fable-5-1", "claude-fable-5"})
"""Fable ids in the bundled CLI registry (FABLE_ID, PREV_FABLE_ID) for claude-agent-sdk 0.2.176.

Revisit this set whenever the claude-agent-sdk pin in pyproject.toml moves: the bundled
CLI decides which Fable ids exist.
"""

REASONING_LEVELS: tuple[ReasoningLevel, ...] = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
NON_FABLE_ROUTES: tuple[str, ...] = tuple(
    route for route in ClaudeBridgeRoute.model_names() if "fable" not in route
)


async def stream_bridge_route_once(
    *, route: str, reasoning_level: ReasoningLevel, working_directory: Path
) -> tuple[ClaudeSessionOptionsDAO, ClaudeAgentOptions, str]:
    """Stream one prompt through the production factory, bridge, adapter and runtime.

    Only the native wire is scripted. The SDK options the runtime builds are captured
    at the SDK client boundary, so assertions read what production produced.

    Args:
        route (str): Qualified bridge route selected by the operator.
        reasoning_level (str): Canonical Slo reasoning level requested for the route.
        working_directory (Path): Disposable project directory for the host session.

    Returns:
        tuple[ClaudeSessionOptionsDAO, ClaudeAgentOptions, str]: Host session options,
        SDK options built by the runtime, and the streamed assistant text.
    """
    host_options: list[ClaudeSessionOptionsDAO] = []
    sdk_options: list[ClaudeAgentOptions] = []
    scripted_transport: ScriptedClaudeTransport = ScriptedClaudeTransport()

    def record_client(*, options: ClaudeAgentOptions, transport: Transport) -> ClaudeSDKClient:
        """Keep the production SDK client while recording the options it was built with."""
        sdk_options.append(options)
        return ClaudeSDKClient(options=options, transport=transport)

    product = LLMFactory.create(
        model_name=route,
        reasoning_level=reasoning_level,
        bridge_adapter_class=scripted_adapter_class(
            transport=scripted_transport, session_options=host_options, client_factory=record_client
        ),
    )
    bridge_owner = product.bridge_owner
    assert bridge_owner is not None
    bridge_owner.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="route-journey", working_directory=working_directory, instructions="host"
        )
    )
    try:
        chunks = [chunk async for chunk in product.llm.astream([HumanMessage(content="hello")])]
    finally:
        await bridge_owner.close()
    return host_options[0], sdk_options[0], "".join(str(chunk.content) for chunk in chunks)


async def native_cli_argv(*, session_options: ClaudeSessionOptionsDAO) -> list[str]:
    """Return the exact argv the production native transport would launch, without starting it.

    The process factory is the only seam. It records the command line at the executable
    boundary and refuses to start a process.

    Args:
        session_options (ClaudeSessionOptionsDAO): Host options the bridge produced.

    Returns:
        list[str]: Executable followed by the fixed native CLI arguments.
    """
    options: ClaudeAgentOptions = ClaudeSDKRuntime._build_options(session_options=session_options)
    options.cli_path = "/synthetic-not-executed"
    launched: list[tuple[str, ...]] = []

    async def record_launch(*args: str, **_kwargs: Any) -> asyncio.subprocess.Process:
        """Record the command line at the process boundary and refuse to spawn."""
        launched.append(args)
        raise OSError("synthetic launch boundary")

    transport = ClaudeNativeTransport(options=options, process_factory=record_launch)
    with contextlib.suppress(OSError):
        await transport.connect()
    assert len(launched) == 1
    return list(launched[0])


@pytest.mark.parametrize(("route", "native_model_id"), list(FABLE_NATIVE_IDS_BY_ROUTE.items()))
async def test_fable_route_sends_its_pinned_native_model_through_factory_bridge_and_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, route: str, native_model_id: str
) -> None:
    """Each explicit Fable route reaches its real Fable id on the Claude Code command line."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    host_options, sdk_options, streamed = await stream_bridge_route_once(
        route=route, reasoning_level="high", working_directory=tmp_path
    )
    assert host_options.model_id == route
    assert host_options.native_model_id == native_model_id
    assert sdk_options.model == native_model_id
    argv = await native_cli_argv(session_options=host_options)
    assert argv[argv.index("--model") + 1] == native_model_id
    assert "Hello bridge" in streamed


@pytest.mark.parametrize("route", list(FABLE_NATIVE_IDS_BY_ROUTE))
async def test_fable_reasoning_off_sends_low_effort_with_adaptive_thinking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, route: str
) -> None:
    """Fable rejects disabled thinking, so a selected off level becomes low effort with thinking on."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    host_options, sdk_options, _ = await stream_bridge_route_once(
        route=route, reasoning_level="off", working_directory=tmp_path
    )
    assert sdk_options.effort == "low"
    assert sdk_options.thinking == {"type": "adaptive"}
    argv = await native_cli_argv(session_options=host_options)
    effort_index: int = argv.index("--effort")
    assert argv[effort_index : effort_index + 4] == ["--effort", "low", "--thinking", "adaptive"]
    assert "disabled" not in argv


@pytest.mark.parametrize("reasoning_level", REASONING_LEVELS)
@pytest.mark.parametrize("route", list(FABLE_NATIVE_IDS_BY_ROUTE))
async def test_fable_route_never_sends_disabled_thinking_at_any_reasoning_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, route: str, reasoning_level: ReasoningLevel
) -> None:
    """No Fable route sends thinking disabled, whichever reasoning level the operator selects."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    host_options, sdk_options, _ = await stream_bridge_route_once(
        route=route, reasoning_level=reasoning_level, working_directory=tmp_path
    )
    argv = await native_cli_argv(session_options=host_options)
    assert sdk_options.thinking == {"type": "adaptive"}
    assert argv[argv.index("--thinking") + 1] == "adaptive"
    assert "disabled" not in argv


@pytest.mark.parametrize("route", INVENTED_FABLE_ROUTES)
def test_invented_fable_route_is_rejected_by_every_admission_point_before_native_work(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """Invented Fable versions fail at selection and never start the native transport."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    scripted_transport: ScriptedClaudeTransport = ScriptedClaudeTransport()
    with pytest.raises(ValueError, match="Unsupported Claude bridge model"):
        ClaudeBridgeRoute.validate(model_name=route)
    with pytest.raises(ValueError, match="Unsupported Claude bridge model"):
        ClaudeBridgeRoute.native_model_id(model_name=route)
    with pytest.raises(ValueError, match="Unsupported Claude bridge model"):
        provider_for_model(model_name=route)
    with pytest.raises(ValueError, match="Unsupported Claude bridge model"):
        resolve_model_name_with_fallback(model_name=route)
    with pytest.raises(ValueError, match="Unsupported Claude bridge model"):
        LLMFactory.create(
            model_name=route, bridge_adapter_class=scripted_adapter_class(transport=scripted_transport)
        )
    assert not scripted_transport.connected
    assert scripted_transport.prompts == []
    picker_names: set[str] = {row.model_name for row in model_suggestion_entries(active_model_name="gpt-5.4")}
    assert route not in picker_names


def test_fable_routes_offered_are_exactly_the_explicit_fable_routes() -> None:
    """The picker lists the three explicit Fable routes and no generated Fable version."""
    fable_routes: list[str] = [route for route in ClaudeBridgeRoute.model_names() if "claude-fable" in route]
    assert sorted(fable_routes) == sorted(FABLE_NATIVE_IDS_BY_ROUTE)


def test_every_fable_native_id_in_the_route_table_is_known_to_the_pinned_cli() -> None:
    """Drift guard: a Fable id the pinned CLI does not define fails here, not at the API."""
    fable_routes: list[str] = [route for route in ClaudeBridgeRoute.model_names() if "claude-fable" in route]
    assert fable_routes
    fable_native_ids: set[str] = {
        ClaudeBridgeRoute.native_model_id(model_name=route) for route in fable_routes
    }
    assert fable_native_ids <= PINNED_CLI_FABLE_NATIVE_IDS


@pytest.mark.parametrize("route", list(FABLE_NATIVE_IDS_BY_ROUTE))
def test_fable_route_entry_reports_native_identity_and_provider_required_reasoning(route: str) -> None:
    """Fable catalog projections show the real native id and keep thinking on."""
    entry = ClaudeBridgeRoute.entry(model_name=route)
    assert entry.api_model_name == FABLE_NATIVE_IDS_BY_ROUTE[route]
    assert entry.reasoning_profile.provider_reasoning_required is True
    assert entry.reasoning_profile.provider_effort_map["off"] == "low"


@pytest.mark.parametrize("route", NON_FABLE_ROUTES)
def test_non_fable_route_native_id_is_its_unprefixed_name_with_generic_reasoning(route: str) -> None:
    """Grid and retained routes send exactly the ids they send today, with the generic profile."""
    unprefixed: str = route.removeprefix(ClaudeBridgeRoute.PREFIX)
    entry = ClaudeBridgeRoute.entry(model_name=route)
    assert ClaudeBridgeRoute.native_model_id(model_name=route) == unprefixed
    assert entry.api_model_name == unprefixed
    assert entry.reasoning_profile.provider_reasoning_required is False
    assert dict(entry.reasoning_profile.provider_effort_map) == {
        "minimal": "low",
        "low": "low",
        "medium": "medium",
        "high": "high",
        "xhigh": "xhigh",
        "max": "max",
    }


def test_session_options_require_a_native_model_id_that_is_not_a_route(tmp_path: Path) -> None:
    """The SDK boundary receives a native id; a missing, empty or prefixed value is rejected."""
    route: str = "claude-bridge:claude-fable-5-1"
    with pytest.raises(ValidationError):
        ClaudeSessionOptionsDAO.model_validate(
            {"session_id": "s", "model_id": route, "working_directory": tmp_path, "instructions": "host"}
        )
    for native_model_id in ("", "claude-bridge:claude-fable-5-1", "claude-bridge:"):
        with pytest.raises(ValidationError):
            ClaudeSessionOptionsDAO(
                session_id="s",
                model_id=route,
                native_model_id=native_model_id,
                working_directory=tmp_path,
                instructions="host",
            )
    accepted: ClaudeSessionOptionsDAO = ClaudeSessionOptionsDAO(
        session_id="s",
        model_id=route,
        native_model_id="claude-fable-5-1",
        working_directory=tmp_path,
        instructions="host",
    )
    assert (accepted.model_id, accepted.native_model_id) == (route, "claude-fable-5-1")
