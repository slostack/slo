"""Exercise real history writers with synthetic credentials and private anchors."""

from pathlib import Path

import pytest

from src.agents.providers.message_extension import ProviderMessageExtensionDAO
from src.agents.slo_agent.compaction.compacter import CompactionResult
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.auth.credential_store import CredentialStore


@pytest.mark.parametrize("source", ["environment", "store"])
@pytest.mark.parametrize("writer", ["compaction", "transcript", "metadata"])
async def test_history_writers_redact_credentials_without_losing_private_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer: str, source: str
) -> None:
    """Newly written artifacts omit keys; private continuation remains exact."""
    root = (tmp_path / "history").resolve()
    assert root.is_relative_to(tmp_path.resolve())
    key = "synthetic-writer-secret"
    opaque = "opaque-continuation-not-a-credential"
    auth_path = (tmp_path / "auth.json").resolve()
    assert auth_path.is_relative_to(tmp_path.resolve())
    monkeypatch.setenv("SLO_AUTH_FILE", str(auth_path))
    if source == "environment":
        monkeypatch.setenv("SLO_OPENROUTER_API_KEY", key)
    else:
        monkeypatch.delenv("SLO_OPENROUTER_API_KEY", raising=False)
        CredentialStore(path=auth_path).persist(
            cred=CredentialDAO(provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token=key)
        )
    store = FilesystemSessionHistoryStore(root=root)
    await store.ensure_session(session_id="safe", workdir=tmp_path, model_name="unknown")
    event = await store.append_event(
        event=SessionHistoryEventDAO(
            session_id="safe",
            turn_id="turn",
            kind="assistant_message",
            payload=SessionHistoryEventPayloadDAO(
                content="safe answer",
                provider_message_extension=ProviderMessageExtensionDAO(
                    provider=ProviderName.OPENROUTER,
                    source_model_name="openrouter:test/model",
                    reasoning_details=[{"type": "reasoning.encrypted", "data": opaque}],
                ),
            ),
        )
    )
    if writer == "compaction":
        await store.compact_to_boundary(
            session_id="safe",
            events=[event],
            turn_id="compact",
            result=CompactionResult(
                summary_text=key,
                first_kept_entry_id=event.event_id,
                cut_point_entry_id=event.event_id,
                tokens_before=10,
                tokens_after=1,
            ),
        )
    elif writer == "transcript":
        await store.rebuild_transcript(session_id="safe", markdown=key)
    else:
        metadata = await store.read_metadata(session_id="safe")
        await store.write_metadata(metadata=metadata.model_copy(update={"session_name": key}))
    for path in root.rglob("*"):
        assert path.resolve().is_relative_to(tmp_path.resolve())
        if path.is_file():
            assert key.encode() not in path.read_bytes(), path.name
    loaded = await store.load_events(session_id="safe")
    assert loaded[0].payload.provider_message_extension == event.payload.provider_message_extension
    assert opaque in (root / "safe/events.jsonl").read_text()


async def test_history_writers_redact_admitted_key_after_effective_key_rotates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An admitted key remains protected after the resolver changes effective credentials."""
    root = (tmp_path / "history").resolve()
    assert root.is_relative_to(tmp_path.resolve())
    admitted_key = "synthetic-admitted-key-a"
    rotated_key = "synthetic-effective-key-b"
    opaque = "opaque-continuation-not-a-credential"
    credential_a = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token=admitted_key,
    )
    credential_b = credential_a.model_copy(update={"access_token": rotated_key})
    store = FilesystemSessionHistoryStore(root=root)
    await store.ensure_session(session_id="rotation", workdir=tmp_path, model_name="unknown")

    with CredentialResolver.bind_build_credential(credential=credential_a):
        monkeypatch.setattr(CredentialResolver, "resolve", lambda *, provider: credential_b)
        event = await store.append_event(
            event=SessionHistoryEventDAO(
                session_id="rotation",
                turn_id="turn",
                kind="assistant_message",
                payload=SessionHistoryEventPayloadDAO(
                    content=f"safe answer {admitted_key}",
                    provider_message_extension=ProviderMessageExtensionDAO(
                        provider=ProviderName.OPENROUTER,
                        source_model_name="openrouter:test/model",
                        reasoning_details=[{"type": "reasoning.encrypted", "data": opaque}],
                    ),
                ),
            )
        )
        await store.rebuild_transcript(session_id="rotation", markdown=admitted_key)
        metadata = await store.read_metadata(session_id="rotation")
        await store.write_metadata(metadata=metadata.model_copy(update={"session_name": admitted_key}))

    artifact_text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*") if path.is_file())
    assert admitted_key not in artifact_text
    assert rotated_key not in artifact_text
    loaded = await store.load_events(session_id="rotation")
    assert len(loaded) == 1
    assert admitted_key not in (loaded[0].payload.content or "")
    assert loaded[0].payload.provider_message_extension == event.payload.provider_message_extension
    assert opaque in (root / "rotation/events.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("capture", ["none", "other_provider", "empty"])
@pytest.mark.parametrize("writer", ["event", "transcript", "metadata"])
async def test_unbound_history_writer_refuses_unresolved_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer: str, capture: str
) -> None:
    """Resolver failure must reject serialization, not publish unchecked raw text."""
    root = (tmp_path / "history").resolve()
    assert root.is_relative_to(tmp_path.resolve())
    secret = "F86_UNBOUND_RAW_SECRET"
    monkeypatch.setattr(CredentialResolver, "resolve", lambda *, provider: None)
    assert CredentialResolver._build_credential.get() is None
    store = FilesystemSessionHistoryStore(root=root)
    await store.ensure_session(session_id="unbound", workdir=tmp_path, model_name="unknown")
    metadata = await store.read_metadata(session_id="unbound")
    assert metadata.session_id == "unbound"
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def fail_resolution(*, provider: ProviderName) -> CredentialDAO:
        """Fail without reading environment, credential files or network."""
        raise OSError(secret)

    monkeypatch.setattr(CredentialResolver, "resolve", fail_resolution)
    # Invalid captures are negative controls, never admitted-operation evidence.
    if capture != "none":
        from contextvars import ContextVar

        invalid = CredentialDAO(
            provider=ProviderName.OPENAI if capture == "other_provider" else ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=secret if capture == "other_provider" else "",
        )
        monkeypatch.setattr(CredentialResolver, "_build_credential", ContextVar("invalid", default=invalid))
    failure: ValueError | None = None
    try:
        if writer == "event":
            await store.append_event(
                event=SessionHistoryEventDAO(
                    session_id="unbound",
                    kind="assistant_message",
                    payload=SessionHistoryEventPayloadDAO(content=secret),
                )
            )
        elif writer == "transcript":
            await store.rebuild_transcript(session_id="unbound", markdown=secret)
        else:
            await store.write_metadata(metadata=metadata.model_copy(update={"session_name": secret}))
    except ValueError as error:
        failure = error
    after = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert all(secret.encode() not in content for content in after.values())
    assert failure is not None
    assert str(failure) == "OpenRouter credential resolution unavailable; serialization refused."
    assert failure.__suppress_context__
    assert after == before


async def test_history_writer_fails_closed_when_credential_resolution_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolver fault must not persist a raw OpenRouter key."""
    root = (tmp_path / "history").resolve()
    assert root.is_relative_to(tmp_path.resolve())
    admitted_key = "synthetic-resolver-failure-key"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token=admitted_key,
    )
    store = FilesystemSessionHistoryStore(root=root)
    await store.ensure_session(session_id="failure", workdir=tmp_path, model_name="unknown")

    def fail_resolution(*, provider: ProviderName) -> CredentialDAO:
        """Raise the controlled resolver failure during serialization."""
        del provider
        raise OSError("controlled resolver failure")

    with CredentialResolver.bind_build_credential(credential=credential):
        monkeypatch.setattr(CredentialResolver, "resolve", fail_resolution)
        event = await store.append_event(
            event=SessionHistoryEventDAO(
                session_id="failure",
                turn_id="turn",
                kind="assistant_message",
                payload=SessionHistoryEventPayloadDAO(content=admitted_key),
            )
        )

    events_path = root / "failure/events.jsonl"
    assert events_path.exists()
    assert admitted_key not in events_path.read_text(encoding="utf-8")
    loaded = await store.load_events(session_id="failure")
    assert loaded[0].payload.content == "[REDACTED]"
    assert event.payload.content == admitted_key
