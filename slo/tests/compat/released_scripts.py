"""Programs importing only frozen released modules; every step ends with one JSON object."""

RELEASED_WRITE_SCHEMA_ONE_CACHE: str = """
import json
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.model_catalog.store import ModelCatalogStore
snapshot = ModelCatalogService.load()
ModelCatalogStore.write_cache(snapshot=snapshot)
print(json.dumps({"entries": len(snapshot.entries)}))
"""

RELEASED_PERSIST_CREDENTIAL: str = """
import json
import os
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
provider = ProviderName(os.environ["COMPAT_PROVIDER"])
CredentialStore().persist(
    cred=CredentialDAO(provider=provider, auth_type=AuthType.API_KEY, access_token=f"{provider.value}-released")
)
print(json.dumps({"persisted": provider.value}))
"""

RELEASED_LOAD_CREDENTIALS: str = """
import json
from src.auth.credential_store import CredentialStore
print(json.dumps({"providers": sorted(provider.value for provider in CredentialStore().load().providers)}))
"""

RELEASED_WRITE_SESSION: str = '''
import asyncio
import json
import os
from pathlib import Path
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

async def write() -> None:
    """Seed one complete released turn for the next version to continue."""
    store_type = {"tree": TreeBasedFilesystemSessionHistoryStore, "flat": FilesystemSessionHistoryStore}
    store = store_type[os.environ["COMPAT_STORE"]]()
    session_id = os.environ["COMPAT_SESSION_ID"]
    await store.ensure_session(session_id=session_id, workdir=Path.cwd(), model_name="retired-model-x")
    for kind, payload in (
        ("run_started", SessionHistoryEventPayloadDAO()),
        ("user_message", SessionHistoryEventPayloadDAO(role="user", content="question from released")),
        ("assistant_message", SessionHistoryEventPayloadDAO(role="assistant", content="answer from released")),
        ("run_completed", SessionHistoryEventPayloadDAO()),
    ):
        await store.append_event(event=SessionHistoryEventDAO(
            session_id=session_id, turn_id="turn-1", kind=kind, payload=payload
        ))

asyncio.run(write())
print(json.dumps({"written": os.environ["COMPAT_SESSION_ID"]}))
'''

RELEASED_RESUME_SESSION: str = '''
import asyncio
import json
import os
from pathlib import Path
from langchain_core.messages import AIMessage
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.cli.typer_dispatch import TyperDispatch

async def resume() -> dict[str, object]:
    """Resume, optionally continue, and reread real history on rollback."""
    config = TyperDispatch._build_session_config(
        workdir=Path.cwd(), resume_session_id=os.environ["COMPAT_SESSION_ID"]
    )
    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="rollback answer")]),
                       cwd=str(Path.cwd()), tools=[]),
        config=config, workdir=Path.cwd(), session_id=config.session_id, enable_history=True,
        history_store=FilesystemSessionHistoryStore() if os.environ["COMPAT_STORE"] == "flat" else None,
    )
    before = await session.hydrate_transcript_entries()
    if os.environ.get("COMPAT_CONTINUE") == "1":
        async for event in session.invoke(text="rollback question"):
            pass
        await session.mark_startup_notice_shown()
    after = await session.hydrate_transcript_entries()
    return {"model_name": session.active_model_name,
            "before": [[entry.kind, entry.content or entry.answer] for entry in before],
            "after": [[entry.kind, entry.content or entry.answer] for entry in after]}

print(json.dumps(asyncio.run(resume())))
'''

RELEASED_LOAD_CATALOG: str = """
import json
import src.cli.app
from src.agents.model_catalog.service import ModelCatalogService
print(json.dumps({"entries": len(ModelCatalogService.load().entries)}))
"""
