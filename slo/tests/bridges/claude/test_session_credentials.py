"""B4: a native-login bridge session must not require a Slo Anthropic credential.

The bridge route authenticates through the operator's external Claude Code
login; the only bridge credential authority is the injected native status
boundary. These tests remove every Slo credential source (environment,
isolated store, isolated legacy path) and drive the real session entry
points. Ordinary-provider guards are asserted to remain unchanged.

Credential-side journeys (stale OAuth refresh for an ordinary route, and
auth becoming non-ready before a bridge send) live in
``tests/agents/slo_agent/test_session.py`` next to the existing lazy-build
refresh coverage, sharing the ``_remove_all_slo_credentials`` helper below.
"""

import importlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Self

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import ClaudeAuthenticationStatusDAO, ClaudeBridgeConfigurationDAO
from src.bridges.claude.sdk.exceptions import ClaudeBridgeError
from src.cli.headless import HeadlessRunner
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, scripted_adapter_class


def remove_all_slo_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Module-level alias for the credential-stripping helper below.

    Kept importable so sibling session tests share one isolation
    implementation instead of duplicating the ``__cfg__`` clearing
    knowledge. See :func:`_remove_all_slo_credentials`.
    """
    _remove_all_slo_credentials(monkeypatch=monkeypatch)


def scripted_adapter_class_with_auth(
    *,
    transport: ScriptedClaudeTransport,
    authentication_check: Callable[[], Awaitable[ClaudeAuthenticationStatusDAO]],
) -> type[SloClaudeBridgeAdapter]:
    """Build the scripted adapter with a caller-controlled native status boundary.

    Composes the existing ``scripted_adapter_class`` seam with the adapter's
    documented ``authentication_check`` injection point; no private SDK or
    session member is patched. The boundary supplies a synthetic status
    object only — it never inspects an account or reads a credential file.

    Args:
        transport (ScriptedClaudeTransport): Scripted native wire boundary.
        authentication_check: Awaitable returning the synthetic native status.

    Returns:
        type[SloClaudeBridgeAdapter]: Adapter class honoring both injections.
    """

    class AuthScriptedAdapter(SloClaudeBridgeAdapter):
        """Scripted adapter whose wire and native status come from the caller."""

        @classmethod
        def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
            """Register with the caller-supplied transport and status boundary."""
            return cls(
                configuration=configuration,
                transport=transport,
                authentication_check=authentication_check,
            )

    return AuthScriptedAdapter


def _remove_all_slo_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every Slo credential source for every provider.

    The per-test ``isolated_slo_home`` fixture already isolates the
    credential store and legacy Claude path to an empty temp root; this
    helper additionally strips the environment layer, including the
    suite's placeholder ``SLO_ANTHROPIC_API_KEY``, and clears the
    import-time ``config.cfg.__cfg__`` snapshot that ``CredentialResolver``
    actually consults. No credential file is read.
    """
    for name in (
        "SLO_ANTHROPIC_API_KEY",
        "SLO_OPENAI_API_KEY",
        "SLO_OPENROUTER_API_KEY",
        "SLO_KIMI_FOR_CODING_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    configuration = importlib.import_module("config.cfg")
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "KIMI_FOR_CODING_API_KEY",
    ):
        monkeypatch.setitem(dic=configuration.__cfg__, name=key, value=None)


async def test_bridge_startup_selection_and_lazy_invoke_without_slo_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Startup, model selection and lazy readiness need no Slo Anthropic key.

    Drives the real session: ``prepare_startup`` (startup gate),
    ``prepare_model_selection`` (selection gate) and ``invoke`` (lazy
    readiness refresh), then reads the run back from the real history
    store. Only the native wire/auth boundary is scripted.
    """
    _remove_all_slo_credentials(monkeypatch=monkeypatch)
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            session_id="bridge-no-slo-cred",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        await session.prepare_startup()
        assert session.preparation_status == "ready"

        selection: str = await session.prepare_model_selection(model_name="claude-bridge:claude-haiku-5-5")
        assert "Preference saved" in selection or "not saved" in selection
        assert "credentials" not in selection.lower()

        events = [event.kind async for event in session.invoke(text="hello")]
        assert events[-1] == "run_completed"
        assert transport.prompts == ["hello"]

        store = FilesystemSessionHistoryStore(root=tmp_path / "history")
        history = await store.load_events(session_id="bridge-no-slo-cred")
        assert sum(event.kind == "run_completed" for event in history) == 1
        assert [event.payload.content for event in history if event.kind == "user_message"] == ["hello"]
    finally:
        await session.close_agent_resources()


async def test_bridge_selection_back_to_bridge_without_slo_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second native selection exercises both pre- and in-lock selection gates."""
    _remove_all_slo_credentials(monkeypatch=monkeypatch)
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            session_id="bridge-reselect",
            enable_history=False,
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        first: str = await session.prepare_model_selection(model_name="claude-bridge:claude-haiku-5-5")
        assert "active model switched" in first
        second: str = await session.prepare_model_selection(model_name="claude-bridge:claude-sonnet-4-6")
        assert "active model switched to claude-bridge:claude-sonnet-4-6" in second
    finally:
        await session.close_agent_resources()


async def test_headless_bridge_journey_without_slo_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real headless entry completes one bridge run with no Slo Anthropic key."""
    _remove_all_slo_credentials(monkeypatch=monkeypatch)
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        session_id="bridge-headless-no-cred",
        enable_history=True,
        history_root=tmp_path / "history",
    )

    async def prepare_session(config: SessionConfigDAO) -> SloAgentSession:
        """Build the real lazy session with only the native boundary scripted."""
        return await SloAgentSession.prepare(
            config=config, bridge_adapter_class=scripted_adapter_class(transport=transport)
        )

    exit_code: int = await HeadlessRunner(config=config, session_preparer=prepare_session).invoke(
        prompt="hello"
    )
    output: list[dict[str, Any]] = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert exit_code == 0, output
    assert [event["content"] for event in output if event["kind"] == "run_completed"] == ["Hello bridge"]
    assert transport.prompts == ["hello"]
    assert transport.closed
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    history = await store.load_events(session_id="bridge-headless-no-cred")
    assert sum(event.kind == "run_completed" for event in history) == 1


async def test_direct_anthropic_route_still_requires_slo_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative guard: a direct (non-bridge) Anthropic route is unchanged."""
    _remove_all_slo_credentials(monkeypatch=monkeypatch)
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="claude-sonnet-4-6"),
    )
    outcome: str = await session.prepare_model_selection(model_name="claude-sonnet-4-6")
    assert "No Anthropic credentials found" in outcome


async def test_direct_openai_route_still_requires_slo_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative guard: a direct OpenAI route is unchanged."""
    _remove_all_slo_credentials(monkeypatch=monkeypatch)
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"),
    )
    outcome: str = await session.prepare_model_selection(model_name="gpt-5.4")
    assert "No OpenAI credentials found" in outcome


async def test_bridge_startup_denied_when_native_auth_not_ready_without_slo_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no Slo keys, a non-ready native login denies startup before any prompt.

    Asserts the denied outcome, not a fabricated completion or candidate
    adoption: preparation fails, no native prompt is submitted, and no
    adapter candidate survives on the session.
    """
    _remove_all_slo_credentials(monkeypatch=monkeypatch)
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()

    async def login_required() -> ClaudeAuthenticationStatusDAO:
        """Report a synthetic non-ready native login; never inspect an account."""
        return ClaudeAuthenticationStatusDAO(
            state="login_required", safe_message="Native login required; run claude auth login."
        )

    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            session_id="bridge-native-denied",
            enable_history=False,
        ),
        bridge_adapter_class=scripted_adapter_class_with_auth(
            transport=transport, authentication_check=login_required
        ),
    )
    with pytest.raises(ValueError, match="Native login required"):
        await session.prepare_startup()
    assert session.preparation_status == "failed"
    assert transport.prompts == []
    assert session._bridge_candidates == []
    assert session._prepared_bridge_adapter is None
    await session.close_agent_resources()


async def test_bridge_selection_denied_when_native_auth_not_ready_without_slo_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no Slo keys, a non-ready native login denies selection without mutation.

    The selection outcome surfaces the native denial; the active route is
    unchanged and no candidate is adopted.
    """
    _remove_all_slo_credentials(monkeypatch=monkeypatch)
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()

    async def login_required() -> ClaudeAuthenticationStatusDAO:
        """Report a synthetic non-ready native login; never inspect an account."""
        return ClaudeAuthenticationStatusDAO(
            state="login_required", safe_message="Native login required; run claude auth login."
        )

    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            session_id="bridge-selection-denied",
            enable_history=False,
        ),
        bridge_adapter_class=scripted_adapter_class_with_auth(
            transport=transport, authentication_check=login_required
        ),
    )
    outcome: str = await session.prepare_model_selection(model_name="claude-bridge:claude-sonnet-4-6")
    assert "Native login required" in outcome
    assert "switched" not in outcome
    assert session.active_model_name == "claude-bridge:claude-haiku-5-5"
    assert transport.prompts == []
    assert session._bridge_candidates == []
    await session.close_agent_resources()


async def test_bridge_startup_denied_when_explicitly_disabled_after_build_without_slo_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recognized route explicitly disabled before startup is denied by route validation.

    Recognition is not route validation: the credential seam must validate
    the recognized route before its early return, so an explicit opt-out is
    denied *before* the native status boundary is consulted. The injected
    recording boundary proves zero auth calls; no prompt is submitted and
    no candidate is adopted. No native process or query is involved.
    """
    _remove_all_slo_credentials(monkeypatch=monkeypatch)
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()
    auth_calls: list[str] = []

    async def recording_status() -> ClaudeAuthenticationStatusDAO:
        """Record every observation; never inspect an account or credential file."""
        auth_calls.append("authentication_check")
        return ClaudeAuthenticationStatusDAO(state="ready", safe_message="Native login ready.")

    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            session_id="bridge-optin-disabled",
            enable_history=False,
        ),
        bridge_adapter_class=scripted_adapter_class_with_auth(
            transport=transport, authentication_check=recording_status
        ),
    )
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="0")
    try:
        with pytest.raises(ValueError, match="Claude bridge is disabled"):
            await session.prepare_startup()
        assert session.preparation_status == "failed"
        assert auth_calls == []
        assert transport.prompts == []
        assert session._bridge_candidates == []
        assert session._prepared_bridge_adapter is None
    finally:
        await session.close_agent_resources()


async def test_bridge_invoke_denied_when_native_auth_becomes_non_ready_before_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auth that turns non-ready after startup denies the send with no query or completion.

    Startup succeeds against a ready boundary; the boundary then reports
    ``login_required`` when the lazy send re-checks native auth at
    ``start_session``. The typed authentication failure propagates, the
    streamed events never fabricate ``run_completed``, no native
    prompt/query is submitted, and real persisted history holds no
    successful terminal event for the denied send.
    """
    _remove_all_slo_credentials(monkeypatch=monkeypatch)
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()
    ready = True

    async def revocable_status() -> ClaudeAuthenticationStatusDAO:
        """Report ready, then login_required once the caller revokes it."""
        if ready:
            return ClaudeAuthenticationStatusDAO(state="ready", safe_message="Native login ready.")
        return ClaudeAuthenticationStatusDAO(
            state="login_required", safe_message="Native login required; run claude auth login."
        )

    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            session_id="bridge-auth-revoked",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class_with_auth(
            transport=transport, authentication_check=revocable_status
        ),
    )
    try:
        await session.prepare_startup()
        assert session.preparation_status == "ready"
        ready = False
        events: list[str] = []
        with pytest.raises(ClaudeBridgeError, match="Native login required") as captured:
            async for event in session.invoke(text="hello"):
                events.append(event.kind)
        assert captured.value.code == "authentication_required"
        assert "run_completed" not in events
        assert transport.prompts == []

        store = FilesystemSessionHistoryStore(root=tmp_path / "history")
        if await store.session_exists(session_id="bridge-auth-revoked"):
            history = await store.load_events(session_id="bridge-auth-revoked")
            assert not any(event.kind == "run_completed" for event in history)
    finally:
        await session.close_agent_resources()
