"""Synthetic F86-39/42 auth-to-selection-to-factory contract, not live evidence.

Real resolver/store/auth/client/catalog/search/session-selection/factory owners run
against MockTransport. Wire fixtures follow 86.a.1/86.a.6 documented shapes; they
are not observed provider responses. Modal paint, tools, and history resume remain
separate contracts, not claims made by this test.
"""

from __future__ import annotations

from src.tui.components.chat_transcript.component import ChatTranscript
from pathlib import Path
from collections.abc import Iterator
from unittest.mock import patch
import asyncio
import json

import httpx
import pytest

from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_store import CredentialStore
from src.auth.credential_resolver import CredentialResolver
from src.auth.openrouter_authentication import OpenRouterAuthenticationService

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.agents.base import LLMFactory
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.tui.app import SloTUI
from src.tui.authentication.auth_screen import AuthenticationScreen
from src.tui.authentication.widgets.api_key_input import ApiKeyInputWidget
from src.tui.authentication.widgets.provider_select import ProviderSelectWidget
from textual.widgets import Button, Input, Static
from langchain_core.tools import tool


@pytest.fixture
def isolated_catalog(tmp_path: Path) -> Iterator[CredentialStore]:
    """Redirect real persistence owners and reject any default HTTP transport.

    Args:
        tmp_path: Pytest-owned directory; all persistent targets stay beneath it.

    Yields:
        CredentialStore: Real private store used by both authentication and resolver.
    """
    private = (tmp_path / "private").resolve()
    assert private.is_relative_to(tmp_path.resolve())
    store = CredentialStore(path=private / "authentication.json")
    with (
        patch("src.auth.credential_resolver.CredentialStore", return_value=store),
        patch.object(CredentialResolver, "_env_var_for", return_value=None),
        patch("src.agents.model_catalog.store._CFG_SLO_HOME", private),
        patch("src.agents.model_catalog.store._cfg", return_value=None),
        patch("src.agents.slo_agent.preferences.service._CFG_SLO_HOME", private),
        patch("src.agents.slo_agent.preferences.service._cfg", return_value=None),
        patch.object(
            httpx.AsyncHTTPTransport, "handle_async_request", side_effect=AssertionError("Network forbidden")
        ),
        patch.object(httpx.HTTPTransport, "handle_request", side_effect=AssertionError("Network forbidden")),
    ):
        ModelCatalogService.reset()
        try:
            yield store
        finally:
            ModelCatalogService.reset()


async def test_default_transports_are_blocked(isolated_catalog: CredentialStore) -> None:
    """Prove accidental default sync/async transports fail before any network I/O."""
    async with httpx.AsyncClient() as client:
        with pytest.raises(AssertionError, match="Network forbidden"):
            await client.get("https://offline.invalid")
    with httpx.Client() as client:
        with pytest.raises(AssertionError, match="Network forbidden"):
            client.get("https://offline.invalid")


async def test_openrouter_offline_flow_verifies_discovers_and_projects_unseeded_route(
    isolated_catalog: CredentialStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify candidate evidence reaches publication, selection, local SSE and reload."""
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        """Serve fixed key and authenticated model fixtures without external I/O."""
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] == "Bearer integration-synthetic-key"
        requests.append(request)
        if request.url.path == "/api/v1/key":
            assert not isolated_catalog.additional_providers_path.exists()
            return httpx.Response(status_code=200, json={"data": {}})
        assert request.url.path == "/api/v1/models/user"
        assert isolated_catalog.additional_providers_path.exists()
        return httpx.Response(
            status_code=200,
            json={
                "data": [
                    {
                        "id": "vendor/unseeded-coder",
                        "name": "Unseeded Coder",
                        "context_length": 64000,
                        "supported_parameters": ["tools"],
                        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                    }
                ]
            },
        )

    from src.integrations.openrouter.client import OpenRouterAPIClient

    assert "openrouter:vendor/unseeded-coder" not in ModelCatalogService.load().entries
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:

        def client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Inject only HTTP transport; keep verification and discovery owners real."""
            return OpenRouterAPIClient(credential=credential, http_client=http_client)

        with patch("src.agents.model_catalog.service.OpenRouterAPIClient", side_effect=client_factory):
            result = await OpenRouterAuthenticationService(
                store=isolated_catalog,
                client_factory=client_factory,
            ).invoke(submitted_key="integration-synthetic-key")

    assert result.key_verified and result.replacement_saved and result.catalog_checked
    assert "integration-synthetic-key" not in result.model_dump_json() + repr(result) + caplog.text
    assert [request.url.path for request in requests] == ["/api/v1/key", "/api/v1/models/user"]
    assert (
        ModelCatalogService.load().entries["openrouter:vendor/unseeded-coder"].runtime_profile.context_window
        == 64000
    )
    assert "openrouter:vendor/unseeded-coder" in ModelCatalogService.load().entries

    from src.tui.slash_command_registry import SlashCommandRegistry
    from src.tui.slash_suggestion_engine import SlashSuggestionEngine
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import SloAgentSession

    engine = SlashSuggestionEngine(registry=SlashCommandRegistry(commands=[]))
    state = engine.evaluate(buffer_text="/model Unseeded Coder", active_model_name="gpt-5.4")
    assert state.total_matches == 1
    selected = state.rows[0].insert_text
    assert selected == "openrouter:vendor/unseeded-coder"
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_catalog.path.parent,
            model_name="gpt-5.4",
            enable_history=False,
        )
    )
    notice = await session.prepare_model_selection(model_name=selected)
    assert session.active_model_name == selected, notice

    from src.agents.base import LLMFactory
    from langchain_core.messages import HumanMessage

    inference_requests: list[str] = []

    def completion(request: httpx.Request) -> httpx.Response:
        """Capture an actual SDK request and return synthetic SSE, never live inference."""
        import json

        assert request.url == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer integration-synthetic-key"
        body = json.loads(request.content)
        assert body["model"] == "vendor/unseeded-coder"
        assert body["stream"] is True
        inference_requests.append(request.url.path)
        chunk = {
            "id": "local",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "vendor/unseeded-coder",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "local answer"},
                    "finish_reason": "stop",
                }
            ],
        }
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
        )

    snapshot = await ModelCatalogService.prepare_models(model_names=(selected,))
    async with httpx.AsyncClient(transport=httpx.MockTransport(completion)) as http_client:
        model = LLMFactory.create(
            model_name=session.active_model_name, snapshot=snapshot, http_async_client=http_client
        ).llm
        chunks = [chunk async for chunk in model.astream(input=[HumanMessage(content="Say hello")])]
    assert "".join(str(chunk.content) for chunk in chunks) == "local answer"
    assert inference_requests == ["/api/v1/chat/completions"]
    assert "integration-synthetic-key" not in caplog.text + repr(chunks) + notice
    cache = isolated_catalog.path.parent / "global" / "model_catalog_cache.v2.json"
    assert cache.resolve().is_relative_to(isolated_catalog.path.parent.resolve())
    assert "integration-synthetic-key" not in cache.read_text(encoding="utf-8")
    assert cache.stat().st_mode & 0o777 == 0o600
    assert isolated_catalog.additional_providers_path.stat().st_mode & 0o777 == 0o600
    ModelCatalogService.reset()
    assert selected in ModelCatalogService.load().entries


@pytest.mark.parametrize(
    ("failure", "expected_message"),
    [
        ("unauthorized", "OpenRouter key was rejected. Check /auth or SLO_OPENROUTER_API_KEY."),
        ("forbidden", "OpenRouter key was rejected. Check /auth or SLO_OPENROUTER_API_KEY."),
        ("protocol", "OpenRouter returned an invalid verification response. Retry authentication later."),
        ("timeout", "OpenRouter request timed out. Retry authentication later."),
    ],
)
@pytest.mark.parametrize("size", [(80, 24), (60, 15)])
async def test_mounted_rejected_replacement_preserves_store_and_session(
    isolated_catalog: CredentialStore,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    failure: str,
    expected_message: str,
    size: tuple[int, int],
) -> None:
    """Reject a candidate at the real GET boundary without mutating mounted state."""
    root = tmp_path.resolve()
    assert isolated_catalog.path.resolve().is_relative_to(root)
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token="previous-synthetic-key",
        )
    )
    original_bytes = isolated_catalog.additional_providers_path.read_bytes()
    original_snapshot = ModelCatalogService.load()
    requests: list[str] = []
    candidate = "rejected-candidate-secret"

    def reject_candidate(request: httpx.Request) -> httpx.Response:
        """Serve only candidate verification; discovery or inference is a failure."""
        assert request.method == "GET"
        assert request.url == "https://openrouter.ai/api/v1/key"
        assert request.headers["authorization"] == f"Bearer {candidate}"
        assert isolated_catalog.additional_providers_path.read_bytes() == original_bytes
        requests.append(request.url.path)
        if failure == "timeout":
            raise httpx.ReadTimeout(message=candidate, request=request)
        if failure == "protocol":
            return httpx.Response(status_code=200, content=candidate)
        status = 401 if failure == "unauthorized" else 403
        return httpx.Response(status_code=status, json={"error": {"message": candidate}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject_candidate)) as http_client:

        def client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Keep the real authentication and GET owners, replacing transport only."""
            return OpenRouterAPIClient(credential=credential, http_client=http_client)

        service = OpenRouterAuthenticationService(store=isolated_catalog, client_factory=client_factory)
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=root, model_name="gpt-5.4", enable_history=False)
        )
        app = SloTUI(session=session)
        screen = AuthenticationScreen(store=isolated_catalog, openrouter_factory=lambda: service)
        async with app.run_test(size=size) as pilot:
            await app.push_screen(screen)
            await screen.on_provider_select_widget_chosen(
                ProviderSelectWidget.Chosen(provider=ProviderName.OPENROUTER)
            )
            widget = screen.query_one(ApiKeyInputWidget)
            widget.query_one("#api-key-input", Input).value = candidate
            await widget._handle_save()
            from tests.tui.authentication._painted_output import wait_until_painted

            await wait_until_painted(pilot=pilot, text="Paste your openrouter API key")
            status_widget = widget.query_one("#api-key-error", Static)
            assert status_widget.render() == expected_message
            painted = await wait_until_painted(pilot=pilot, text=expected_message, widget=status_widget)
            assert "".join(expected_message.split()) in painted
            from tests.tui.authentication._painted_output import assert_widget_painted

            assert_widget_painted(app=app, widget=status_widget, text=expected_message)
            # Suppress only painting, preserving the real service result and widget text.
            original_visibility = status_widget.styles.visibility
            try:
                status_widget.styles.visibility = "hidden"
                await pilot.pause()
                assert status_widget.render() == expected_message
                with pytest.raises(AssertionError, match="Expected widget paint"):
                    assert_widget_painted(app=app, widget=status_widget, text=expected_message)
            finally:
                status_widget.styles.visibility = original_visibility
            await pilot.pause()
            assert_widget_painted(app=app, widget=status_widget, text=expected_message)
            viewport = "".join(strip.text for strip in screen._compositor.render_strips())
            assert candidate not in viewport
            assert candidate not in painted
            assert not widget.query_one("#api-key-save", Button).disabled
            assert widget.query_one("#api-key-input", Input).value == ""
            assert not service.result.key_verified
            assert not service.result.replacement_saved
            assert not service.result.catalog_checked
            assert service.verified_credential() is None
            assert isolated_catalog.additional_providers_path.read_bytes() == original_bytes
            assert ModelCatalogService.load() is original_snapshot
            assert session.active_model_name == "gpt-5.4"
            await screen.action_cancel()
            await pilot.pause()
            assert session.active_model_name == "gpt-5.4"
            assert candidate not in app.query_one(ChatTranscript).logical_copy_text()
    assert requests == ["/api/v1/key"]
    assert candidate not in caplog.text + service.result.model_dump_json()


@pytest.mark.parametrize("size", [(80, 24), (60, 15)])
async def test_mounted_refresh_paints_session_router_count_and_check_time(
    isolated_catalog: CredentialStore, tmp_path: Path, size: tuple[int, int]
) -> None:
    """Paint the real GET/catalog/session/router result after a deterministic listing barrier."""
    from tests.tui.authentication._painted_output import assert_widget_painted

    key = "refresh-paint-synthetic-secret"
    isolated_catalog.persist(
        cred=CredentialDAO(provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token=key)
    )
    entered, release = asyncio.Event(), asyncio.Event()
    requests: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        """Block the only listing until the mounted test releases its publication."""
        assert request.method == "GET"
        assert request.headers["authorization"] == f"Bearer {key}"
        requests.append(request.url.path)
        if request.url.path == "/api/v1/key":
            return httpx.Response(status_code=200, json={"data": {}})
        assert request.url.path == "/api/v1/models/user"
        entered.set()
        await release.wait()
        return httpx.Response(
            status_code=200,
            json={
                "data": [
                    {
                        "id": "vendor/refresh-paint",
                        "context_length": 64000,
                        "supported_parameters": ["tools"],
                        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                    }
                ]
            },
        )

    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=False)
    )
    app = SloTUI(session=session)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        if isinstance(app.screen, AuthenticationScreen):
            await app.screen.action_cancel()
            await pilot.pause()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:

            def client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
                """Replace transport only, keeping the entire refresh composition real."""
                return OpenRouterAPIClient(credential=credential, http_client=http)

            with patch("src.agents.model_catalog.service.OpenRouterAPIClient", side_effect=client_factory):
                task = asyncio.create_task(app._dispatch_slash_command(line="/model refresh"))
                try:
                    await asyncio.wait_for(entered.wait(), timeout=2)
                    assert not task.done()
                    release.set()
                    await asyncio.wait_for(task, timeout=5)
                    await pilot.pause()
                    checked = ModelCatalogService.lifecycle_status().catalog_checked_at
                    assert checked is not None
                    expected = f"OpenRouter catalog refreshed. 1 models; last complete check: {checked.isoformat(timespec='seconds')}."
                    notices = list(app.query(".tool-result"))
                    assert notices
                    notices[-1].scroll_visible(animate=False, force=True)
                    await pilot.pause()
                    if size == (60, 15):
                        assert_widget_painted(
                            app=app,
                            widget=notices[-1],
                            text="OpenRouter catalog refreshed. 1 models; last complete",
                        )
                        app.query_one("#transcript-scroll").scroll_end(animate=False, force=True)
                        await pilot.pause()
                        assert_widget_painted(
                            app=app,
                            widget=notices[-1],
                            text=f"check: {checked.isoformat(timespec='seconds')}.",
                        )
                    else:
                        assert_widget_painted(app=app, widget=notices[-1], text=expected)
                    viewport = "".join(strip.text for strip in app.screen._compositor.render_strips())
                    assert key not in viewport
                    assert session.active_model_name == "gpt-5.4"
                finally:
                    release.set()
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    assert requests == ["/api/v1/key", "/api/v1/models/user"]


@tool
def full_flow_echo() -> str:
    """Return the deterministic harmless result used by the mounted flow."""
    return "full-flow tool result"


async def test_mounted_openrouter_auth_picker_router_session_and_resume_flow(
    isolated_catalog: CredentialStore,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Drive the mounted auth, picker, router, tool, and fresh-session resume path."""
    root: Path = tmp_path.resolve()
    history_root: Path = root / "history"
    route: str = "openrouter:vendor/mounted-unseeded"
    candidate_key: str = "mounted-candidate-secret"
    reasoning_secret: str = "MOUNTED_PRIVATE_REASONING"
    request_bodies: list[dict[str, object]] = []
    candidate_verified = asyncio.Event()

    def responder(request: httpx.Request) -> httpx.Response:
        """Serve authentication, discovery, and local Chat Completions SSE responses."""
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] == f"Bearer {candidate_key}"
        if request.method == "GET" and request.url.path == "/api/v1/key":
            assert not isolated_catalog.additional_providers_path.exists()
            candidate_verified.set()
            return httpx.Response(status_code=200, json={"data": {}})
        if request.method == "GET" and request.url.path == "/api/v1/models/user":
            assert candidate_verified.is_set()
            assert isolated_catalog.additional_providers_path.exists()
            return httpx.Response(
                status_code=200,
                json={
                    "data": [
                        {
                            "id": "vendor/mounted-unseeded",
                            "name": "Mounted Unseeded Coder",
                            "context_length": 64000,
                            "supported_parameters": ["tools"],
                            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                        }
                    ]
                },
            )
        assert request.method == "POST"
        assert request.url.path == "/api/v1/chat/completions"
        body: dict[str, object] = json.loads(request.content)
        request_bodies.append(body)
        assert body["model"] == "vendor/mounted-unseeded"
        if len(request_bodies) == 1:
            chunk: dict[str, object] = {
                "id": "mounted-tool",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "vendor/mounted-unseeded",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "reasoning_details": [{"type": "encrypted", "data": reasoning_secret}],
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-mounted",
                                    "type": "function",
                                    "function": {"name": "full_flow_echo", "arguments": "{}"},
                                }
                            ],
                        },
                        "finish_reason": None,
                    }
                ],
            }
        elif len(request_bodies) == 2:
            chunk = {
                "id": "mounted-answer",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "vendor/mounted-unseeded",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "first mounted answer"},
                        "finish_reason": "stop",
                    }
                ],
            }
        else:
            chunk = {
                "id": "mounted-resume",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "vendor/mounted-unseeded",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "second mounted answer"},
                        "finish_reason": "stop",
                    }
                ],
            }
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http_client:

        def catalog_client(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Inject the local transport only at the real catalog HTTP boundary."""
            return OpenRouterAPIClient(credential=credential, http_client=http_client)

        original_builder = LLMFactory._build_openrouter

        def local_factory(
            *, model_name: str, resolved: dict[str, object], entry: object
        ) -> OpenRouterChatOpenAI:
            """Inject the local transport into the production OpenRouter factory builder."""
            resolved["http_async_client"] = http_client
            return original_builder(model_name=model_name, resolved=resolved, entry=entry)  # type: ignore[arg-type]

        with (
            patch("src.agents.model_catalog.service.OpenRouterAPIClient", side_effect=catalog_client),
            patch.object(LLMFactory, "_build_openrouter", side_effect=local_factory),
        ):
            ModelCatalogService.reset()
            first_session = SloAgentSession.build(
                config=SessionConfigDAO(
                    workdir=root,
                    model_name="gpt-5.4",
                    session_id="mounted-openrouter-flow",
                    history_root=history_root,
                    enable_history=True,
                    extra_tools=[full_flow_echo],
                    system_prompt="Use full_flow_echo before answering.",
                )
            )
            auth_screen = AuthenticationScreen(
                store=isolated_catalog,
                openrouter_factory=lambda: OpenRouterAuthenticationService(
                    store=isolated_catalog,
                    client_factory=catalog_client,
                ),
            )
            first_app = SloTUI(session=first_session)
            async with first_app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await first_app.push_screen(auth_screen)
                await auth_screen.on_provider_select_widget_chosen(
                    ProviderSelectWidget.Chosen(provider=ProviderName.OPENROUTER)
                )
                key_input = auth_screen.query_one(ApiKeyInputWidget)
                key_input.query_one("#api-key-input", Input).value = candidate_key
                await key_input._handle_save()
                for _ in range(20):
                    await pilot.pause()
                    if candidate_verified.is_set():
                        break
                assert candidate_verified.is_set()
                for _ in range(20):
                    await pilot.pause()
                    if "Key verified; catalog checked." in "".join(
                        strip.text for strip in auth_screen._compositor.render_strips()
                    ):
                        break
                painted_auth = "".join(strip.text for strip in auth_screen._compositor.render_strips())
                assert "Key verified; catalog checked." in painted_auth
                assert candidate_key not in painted_auth
                await auth_screen.on_success_widget_closed(type("Closed", (), {})())
                await pilot.pause()
                assert first_app._input is not None
                first_app._input.load_text("/model mounted unseeded")
                await pilot.pause()
                assert first_app._slash_suggestion_state.rows[0].insert_text == route
                first_app.on_prompt_input_suggestion_accepted(type("Accepted", (), {})())
                await pilot.pause()
                assert first_app._input.text == f"/model {route}"
                await first_app._dispatch_slash_command(line=f"/model {route}")
                assert first_session.active_model_name == route
                await first_app._submit_or_queue_prompt(text="run the tool")
                for _ in range(30):
                    await pilot.pause()
                    if not first_session.is_running:
                        break
                assert not first_session.is_running
                first_transcript = first_app.query_one(ChatTranscript).logical_copy_text()
                assert "first mounted answer" in first_transcript
                assert reasoning_secret not in first_transcript

            resumed_session = await SloAgentSession.prepare(
                config=SessionConfigDAO(
                    workdir=root,
                    model_name=route,
                    session_id="mounted-openrouter-flow",
                    history_root=history_root,
                    enable_history=True,
                    extra_tools=[full_flow_echo],
                    system_prompt="Use full_flow_echo before answering.",
                )
            )
            resumed_app = SloTUI(session=resumed_session)
            async with resumed_app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                assert resumed_app._input is not None
                await resumed_app._submit_or_queue_prompt(text="continue")
                for _ in range(30):
                    await pilot.pause()
                    if not resumed_session.is_running:
                        break
                assert not resumed_session.is_running
                resumed_transcript = resumed_app.query_one(ChatTranscript).logical_copy_text()
                assert "second mounted answer" in resumed_transcript
                assert reasoning_secret not in resumed_transcript
            ModelCatalogService.reset()

    assert len(request_bodies) == 3
    continuation_messages = request_bodies[2]["messages"]
    assert isinstance(continuation_messages, list)
    anchor = next(message for message in continuation_messages if message["role"] == "assistant")
    assert anchor["reasoning_details"] == [{"type": "encrypted", "data": reasoning_secret}]
    tool_result = next(message for message in continuation_messages if message["role"] == "tool")
    assert tool_result["tool_call_id"] == "call-mounted"
    assert tool_result["content"] == "full-flow tool result"
    for path in history_root.rglob("*"):
        assert path.resolve().is_relative_to(root)
        if path.is_file() and path.name != "events.jsonl":
            assert candidate_key not in path.read_text(encoding="utf-8")
            assert reasoning_secret not in path.read_text(encoding="utf-8")
    assert candidate_key not in caplog.text
    assert reasoning_secret not in caplog.text
