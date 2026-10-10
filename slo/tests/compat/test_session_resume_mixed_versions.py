"""Actual released/new sessions continue each other's complete durable history."""

from pathlib import Path
from collections.abc import Callable

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.providers.message_extension import ProviderMessageExtensionDAO
from src.agents.slo_agent.history.dao import (
    HistoryEventKind,
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.history.transcript import ReplayEntryProjector
from src.auth.credential_dao import ProviderName
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.cli.typer_dispatch import TyperDispatch
from tests.compat.released_runner import run_released_slo
from tests.compat.released_scripts import RELEASED_RESUME_SESSION, RELEASED_WRITE_SESSION


@pytest.mark.parametrize(argnames="store_kind", argvalues=["tree", "flat"])
async def test_build_session_config_when_released_slo_wrote_session_new_slo_continues_it(
    released_slo_source: Path, isolated_slo_home: Path, store_kind: str
) -> None:
    """Old -> new continue/metadata rewrite -> old continue -> new retains exact text."""
    inputs = {"COMPAT_SESSION_ID": "released-session", "COMPAT_STORE": store_kind}
    written = run_released_slo(
        source=released_slo_source,
        slo_home=isolated_slo_home,
        script=RELEASED_WRITE_SESSION,
        extra_env=inputs,
    )
    assert written.returncode == 0, written.stderr
    workdir = isolated_slo_home / "new-workdir"
    assert workdir.resolve().is_relative_to(isolated_slo_home)
    workdir.mkdir()
    saved_metadata = await FilesystemSessionHistoryStore().read_metadata(session_id="released-session")
    config = TyperDispatch._build_session_config(
        workdir=workdir, resume_session_id="released-session", resumed_model_name=saved_metadata.model_name
    )
    assert config.model_name == "gpt-5.4"
    assert config.fallback_notice is not None and "retired-model-x" in config.fallback_notice
    session = SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="answer from new")]), cwd=str(workdir), tools=[]
        ),
        config=config,
        workdir=workdir,
        session_id="released-session",
        enable_history=True,
        history_store=FilesystemSessionHistoryStore() if store_kind == "flat" else None,
    )
    old = [["user", "question from released"], ["assistant", "answer from released"]]
    assert [
        [entry.kind, entry.content or entry.answer] for entry in await session.hydrate_transcript_entries()
    ] == old
    async for _event in session.invoke(text="question from new"):
        pass
    await session.mark_startup_notice_shown()
    metadata = await FilesystemSessionHistoryStore().read_metadata(session_id="released-session")
    assert metadata.model_name == "gpt-5.4" and metadata.startup_notice_shown_at is not None
    expected = old + [["user", "question from new"], ["assistant", "answer from new"]]
    reread = run_released_slo(
        source=released_slo_source,
        slo_home=isolated_slo_home,
        script=RELEASED_RESUME_SESSION,
        extra_env={**inputs, "COMPAT_CONTINUE": "1"},
    )
    assert reread.returncode == 0, reread.stderr
    assert reread.result == {
        "model_name": "gpt-5.4",
        "before": expected,
        "after": expected + [["user", "rollback question"], ["assistant", "rollback answer"]],
    }
    assert [
        [entry.kind, entry.content or entry.answer] for entry in await session.hydrate_transcript_entries()
    ] == reread.result["after"]


@pytest.mark.parametrize(argnames="store_kind", argvalues=["tree", "flat"])
@pytest.mark.parametrize(
    argnames="model_name",
    argvalues=[
        "openrouter:vendor/compat",
        "gpt-6-luna",
        "gpt-6.1-sol",
        "gpt-6-sol",
        "openrouter:typesafe/jev-router",
    ],
)
async def test_hydrate_transcript_entries_when_new_slo_wrote_session_released_slo_loads_all_turns(
    released_slo_source: Path, isolated_slo_home: Path, store_kind: str, model_name: str
) -> None:
    """New OpenRouter history with an extension is readable and writable on rollback."""
    store_type: dict[str, Callable[[], SessionHistoryStoreProtocol]] = {
        "tree": TreeBasedFilesystemSessionHistoryStore,
        "flat": FilesystemSessionHistoryStore,
    }
    store = store_type[store_kind]()
    assert store.root.resolve().is_relative_to(isolated_slo_home)
    await store.ensure_session(session_id="new-session", workdir=isolated_slo_home, model_name=model_name)
    extension = ProviderMessageExtensionDAO(
        provider=ProviderName.OPENROUTER, source_model_name="openrouter:vendor/compat"
    )
    expected: list[list[str]] = []
    for turn in (1, 2):
        question, answer = f"new question {turn}", f"new answer {turn}"
        expected.extend([["user", question], ["assistant", answer]])
        events: list[tuple[HistoryEventKind, SessionHistoryEventPayloadDAO]] = [
            ("run_started", SessionHistoryEventPayloadDAO()),
            ("user_message", SessionHistoryEventPayloadDAO(role="user", content=question)),
            (
                "assistant_message",
                SessionHistoryEventPayloadDAO(
                    role="assistant", content=answer, provider_message_extension=extension
                ),
            ),
            ("run_completed", SessionHistoryEventPayloadDAO()),
        ]
        for kind, payload in events:
            await store.append_event(
                event=SessionHistoryEventDAO(
                    session_id="new-session", turn_id=f"turn-{turn}", kind=kind, payload=payload
                )
            )
    before = await store.load_events(session_id="new-session")
    assert sum(event.payload.provider_message_extension is not None for event in before) == 2
    resumed = run_released_slo(
        source=released_slo_source,
        slo_home=isolated_slo_home,
        script=RELEASED_RESUME_SESSION,
        extra_env={"COMPAT_SESSION_ID": "new-session", "COMPAT_STORE": store_kind, "COMPAT_CONTINUE": "1"},
    )
    assert resumed.returncode == 0, resumed.stderr
    expected.extend([["user", "rollback question"], ["assistant", "rollback answer"]])
    assert resumed.result == {"model_name": "gpt-5.4", "before": expected[:4], "after": expected}
    after = await store.load_events(session_id="new-session")
    assert after[: len(before)] == before
    assert [
        [entry.kind, entry.content or entry.answer]
        for entry in ReplayEntryProjector.build_entries(events=after)
    ] == expected
