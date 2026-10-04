"""Local SDK to session/history/headless security boundary evidence."""

from pathlib import Path
from typing import Any
from unittest.mock import patch
import json
import traceback

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from src.agents.base import LLMFactory
from src.agents.model_catalog.dao import ModelCatalogEntryDAO
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    CredentialSource,
    ProviderName,
    ResolvedCredentialDAO,
)
from src.auth.credential_resolver import CredentialResolver
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.cli.headless import HeadlessRunner
from src.tui.app import SloTUI
from src.integrations.openrouter.exceptions import OpenRouterAPIError
from tests.agents.providers.test_openrouter_fragments import _sse
from tests.agents.providers.test_openrouter_transport import _prepared_snapshot, _OPENROUTER_MODEL_NAME


@tool
def channel_echo() -> str:
    """Return an in-memory tool result without side effects."""
    return "local tool result"


async def test_sdk_session_private_history_and_public_headless_channels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """Execute a real bound tool turn; only private replay state retains opaque data."""
    sentinel = "OPAQUE_CHANNEL_86_9b27"
    requests: list[dict] = []
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve a private tool response followed by a visible final answer."""
        requests.append(json.loads(request.content))
        if len(requests) > 1:
            return _sse([{"content": "public final answer"}])
        return _sse(
            [
                {
                    "reasoning_details": [{"type": "encrypted", "data": sentinel}],
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-channel",
                            "type": "function",
                            "function": {"name": "channel_echo", "arguments": "{}"},
                        }
                    ],
                }
            ]
        )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME, snapshot=_prepared_snapshot(), http_async_client=client
            ).llm
        agent = SloAgent(
            llm=model, tools=[channel_echo], cwd=str(tmp_path), system_prompt="Use the local tool."
        )
        store = FilesystemSessionHistoryStore(root=root)
        session = SloAgentSession(
            agent=agent,
            workdir=tmp_path,
            session_id="channel-session",
            history_store=store,
            enable_history=True,
        )
        runner = HeadlessRunner(
            config=SessionConfigDAO(workdir=tmp_path, session_id=session.session_id, enable_history=False)
        )
        session.subscribe(handler=runner._emit)
        events = [event async for event in session.invoke(text="echo")]
    captured = capsys.readouterr()
    with patch("src.tui.app.CredentialResolver.resolve", return_value=credential):
        app = SloTUI(session=session)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            painted = "".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "public final answer" in painted
            assert sentinel not in painted
    assert len(requests) == 2
    assert requests[0]["tools"][0]["function"]["name"] == "channel_echo"
    assistant = next(message for message in requests[1]["messages"] if message["role"] == "assistant")
    assert assistant["reasoning_details"] == [{"type": "encrypted", "data": sentinel}]
    assert events[-1].kind == "run_completed"
    assert sentinel not in captured.out + captured.err + caplog.text
    assert sentinel not in "".join(event.model_dump_json() for event in events)
    files = list(root.rglob("*"))
    private_events: list[dict] = []
    for path in files:
        if not path.is_file():
            continue
        assert path.resolve().is_relative_to(tmp_path.resolve())
        text = path.read_text()
        if path.name == "events.jsonl":
            private_events.extend(json.loads(line) for line in text.splitlines())
        else:
            assert sentinel not in text
    anchors = [event for event in private_events if sentinel in json.dumps(event)]
    assert len(anchors) == 1
    assert anchors[0]["kind"] == "tool_call"
    assert anchors[0]["payload"]["provider_message_extension"]["reasoning_details"] == [
        {"type": "encrypted", "data": sentinel}
    ]


@pytest.mark.parametrize("compact", [False, True], ids=["resume", "compacted-tail"])
async def test_sdk_history_reset_replays_private_tool_anchor_to_same_route(
    tmp_path: Path,
    compact: bool,
) -> None:
    """Resume persisted local tool history and send its opaque anchor only to the same route."""
    sentinel = "OPAQUE_RESUME_86_1f39"
    requests: list[dict[str, object]] = []
    history_root = tmp_path / "history"
    assert history_root.resolve().is_relative_to(tmp_path.resolve())

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a tool call first, then record the resumed continuation request."""
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return _sse(
                [
                    {
                        "reasoning_details": [{"type": "encrypted", "data": sentinel}],
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-resume",
                                "type": "function",
                                "function": {"name": "channel_echo", "arguments": "{}"},
                            }
                        ],
                    }
                ]
            )
        return _sse([{"content": "resumed final"}])

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="fixture",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME,
                snapshot=_prepared_snapshot(),
                http_async_client=client,
            ).llm
        first_session = SloAgentSession(
            agent=SloAgent(
                llm=model, tools=[channel_echo], cwd=str(tmp_path), system_prompt="Use channel_echo."
            ),
            workdir=tmp_path,
            session_id="resume-session",
            history_store=FilesystemSessionHistoryStore(root=history_root),
            enable_history=True,
        )
        _ = [event async for event in first_session.invoke(text="echo")]
        assert len(requests) == 2
        first_continuation = requests[1]["messages"]
        assert isinstance(first_continuation, list)
        first_anchor = next(message for message in first_continuation if message["role"] == "assistant")
        assert first_anchor["reasoning_details"] == [{"type": "encrypted", "data": sentinel}]

        if compact:
            from src.agents.slo_agent.compaction.compacter import CompactionResult

            retained_store = FilesystemSessionHistoryStore(root=history_root)
            retained = await retained_store.load_events(session_id=first_session.session_id)
            boundary = next(event for event in retained if event.kind == "run_started")
            await retained_store.compact_to_boundary(
                session_id=first_session.session_id,
                events=retained,
                result=CompactionResult(
                    summary_text="Earlier context",
                    cut_point_entry_id=boundary.event_id,
                    first_kept_entry_id=boundary.event_id,
                    tokens_before=100,
                    tokens_after=50,
                ),
                turn_id="manual-compaction",
            )
        reset_store = FilesystemSessionHistoryStore(root=history_root)
        events = await reset_store.load_events(session_id=first_session.session_id)
        messages = await SessionHistoryProjector.build_message_history(events=events)
        replayed_anchor = next(message for message in messages if isinstance(message, AIMessage))
        assert any(isinstance(message, ToolMessage) for message in messages)
        assert (
            sentinel
            in replayed_anchor.additional_kwargs["slo_provider_extension"]["reasoning_details"][0]["data"]
        )

        resumed = [
            chunk
            async for chunk in model.astream(
                input=[*messages, HumanMessage(content="continue")],
            )
        ]

    assert "".join(str(chunk.content) for chunk in resumed) == "resumed final"
    assert len(requests) == 3
    continuation_messages = requests[2]["messages"]
    assert isinstance(continuation_messages, list)
    anchor = next(message for message in continuation_messages if message["role"] == "assistant")
    assert anchor["reasoning_details"] == [{"type": "encrypted", "data": sentinel}]
    for path in history_root.rglob("*"):
        assert path.resolve().is_relative_to(tmp_path.resolve())


async def test_new_session_prepare_resume_replays_private_tool_anchor_to_same_route(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Resume through two prepared session lifecycles and preserve same-route tool metadata.

    This exercises the production session gateway twice: the first session persists a
    real bound-tool turn, while a separately constructed session with the saved ID
    prepares and invokes the next prompt. The test does not construct a projector,
    SDK continuation, prebuilt agent, or session directly.
    """
    root: Path = tmp_path.resolve()
    history_root: Path = root / "history"
    route: str = "openrouter:vendor/session-resume"
    sentinel: str = "OPAQUE_NEW_SESSION_RESUME_86"
    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="local-session-resume-credential",
    )
    resolved_credential: ResolvedCredentialDAO = ResolvedCredentialDAO(
        credential=credential,
        source=CredentialSource.ENVIRONMENT,
    )
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve authenticated discovery and deterministic local Chat Completions SSE."""
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] == "Bearer " + credential.access_token
        if request.method == "GET":
            if request.url.path == "/api/v1/key":
                return httpx.Response(status_code=200, json={"data": {}})
            assert request.url.path == "/api/v1/models/user"
            return httpx.Response(
                status_code=200,
                json={
                    "data": [
                        {
                            "id": "vendor/session-resume",
                            "name": "Session Resume",
                            "context_length": 64000,
                            "supported_parameters": ["tools"],
                            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                        }
                    ]
                },
            )
        assert request.method == "POST"
        assert request.url.path == "/api/v1/chat/completions"
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return _sse(
                [
                    {
                        "reasoning_details": [{"type": "encrypted", "data": sentinel}],
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-new-session-resume",
                                "type": "function",
                                "function": {"name": "channel_echo", "arguments": "{}"},
                            }
                        ],
                    }
                ]
            )
        if len(requests) == 2:
            return _sse([{"content": "first session answer"}])
        return _sse([{"content": "resumed session answer"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        original_builder = LLMFactory._build_openrouter

        def build_with_local_transport(
            *,
            model_name: str,
            resolved: dict[str, Any],
            entry: ModelCatalogEntryDAO,
        ) -> OpenRouterChatOpenAI:
            """Inject only the local SDK transport into the normal factory builder."""
            resolved["http_async_client"] = client
            return original_builder(model_name=model_name, resolved=resolved, entry=entry)

        def build_catalog_client(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Inject only the catalog GET transport into its real client boundary."""
            return OpenRouterAPIClient(credential=credential, http_client=client)

        with (
            patch.object(CredentialResolver, "resolve_with_source", return_value=resolved_credential),
            patch.object(CredentialResolver, "require", return_value=credential),
            patch("src.agents.model_catalog.store._CFG_SLO_HOME", root),
            patch("src.agents.model_catalog.store._cfg", return_value=None),
            patch("src.agents.slo_agent.preferences.service._CFG_SLO_HOME", root),
            patch("src.agents.slo_agent.preferences.service._cfg", return_value=None),
            patch.object(SloAgentSession, "_load_plugins"),
            patch(
                "src.agents.model_catalog.service.OpenRouterAPIClient",
                side_effect=build_catalog_client,
            ),
            patch.object(LLMFactory, "_build_openrouter", side_effect=build_with_local_transport),
            patch.object(
                httpx.AsyncHTTPTransport,
                "handle_async_request",
                side_effect=AssertionError("Network forbidden"),
            ),
            patch.object(
                httpx.HTTPTransport, "handle_request", side_effect=AssertionError("Network forbidden")
            ),
        ):
            ModelCatalogService.reset()
            try:
                config: SessionConfigDAO = SessionConfigDAO(
                    workdir=root,
                    model_name=route,
                    session_id="new-session-resume",
                    history_root=history_root,
                    enable_history=True,
                    extra_tools=[channel_echo],
                    system_prompt="Use channel_echo before answering.",
                )
                first_session: SloAgentSession = await SloAgentSession.prepare(config=config)
                first_events: list[AgentStreamEventDAO] = [
                    event async for event in first_session.invoke(text="echo")
                ]
                assert first_events[-1].kind == "run_completed"
                assert len(requests) == 2

                resumed_session: SloAgentSession = await SloAgentSession.prepare(config=config)
                assert resumed_session is not first_session
                resumed_events: list[AgentStreamEventDAO] = [
                    event async for event in resumed_session.invoke(text="continue")
                ]
            finally:
                ModelCatalogService.reset()

    assert resumed_events[-1].kind == "run_completed"
    assert len(requests) == 3
    resumed_request: dict[str, object] = requests[2]
    assert resumed_request["model"] == "vendor/session-resume"
    resumed_messages = resumed_request["messages"]
    assert isinstance(resumed_messages, list)
    anchor = next(message for message in resumed_messages if message["role"] == "assistant")
    assert anchor["reasoning_details"] == [{"type": "encrypted", "data": sentinel}]
    assert anchor["tool_calls"][0]["id"] == "call-new-session-resume"
    tool_result = next(message for message in resumed_messages if message["role"] == "tool")
    assert tool_result == {
        "role": "tool",
        "content": "local tool result",
        "tool_call_id": "call-new-session-resume",
    }
    assert any(event.content == "resumed session answer" for event in resumed_events)
    history_files: list[Path] = list(history_root.rglob("*"))
    assert history_files
    for path in history_files:
        assert path.resolve().is_relative_to(root)
        if path.is_file() and path.name != "events.jsonl":
            assert sentinel not in path.read_text(encoding="utf-8")
    assert sentinel not in caplog.text
    assert credential.access_token not in caplog.text + "".join(
        event.model_dump_json() for event in resumed_events
    )


@pytest.mark.parametrize("failure", ["http", "transport"])
async def test_sdk_failure_logs_and_formatted_traceback_are_safe(
    failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Raw SDK error data cannot escape through logs, repr, or formatted traceback."""
    marker = "RAW_ERROR_CHANNEL_86_4c71"

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a raw body or a transport exception containing private data."""
        if failure == "transport":
            raise httpx.ReadError(marker, request=request)
        return httpx.Response(status_code=400, json={"error": {"type": "invalid_request", "message": marker}})

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME, snapshot=_prepared_snapshot(), http_async_client=client
            ).llm
        with pytest.raises(OpenRouterAPIError) as caught:
            _ = [chunk async for chunk in model.astream("hello")]
    assert marker not in str(caught.value) + repr(caught.value)
    assert marker not in "".join(traceback.format_exception(caught.value))
    assert marker not in caplog.text
    if failure == "http":
        assert caught.value.status_code == 400
        assert caught.value.error_type == "invalid_request"
