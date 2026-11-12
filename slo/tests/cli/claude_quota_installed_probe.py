"""Static-checked probe copied outside the checkout for isolated candidate acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import sys
from functools import partial
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from pydantic import BaseModel

import src.bridges.claude.bridge as bridge
import src.bridges.claude.sdk.sdk_runtime as runtime
import src.bridges.claude.sdk.transport as transport_module
from claude_agent_sdk._internal import message_parser

root, checkout = (Path(argument) for argument in sys.argv[1:3])


class InstalledProvenanceDAO(BaseModel):
    """Interpreter, distribution and module provenance for one isolated probe process."""

    executable: str
    isolated: int
    version: str
    modules: dict[str, str]
    hashes: dict[str, str]


def provenance() -> InstalledProvenanceDAO:
    """Reject checkout imports before loading fixtures and describe installed modules.

    Returns:
        InstalledProvenanceDAO: Interpreter and content identity for the receipt.

    Raises:
        AssertionError: A production module is outside the disposable candidate.
    """
    imported_modules: dict[str, ModuleType] = {
        "bridge": bridge,
        "runtime": runtime,
        "transport": transport_module,
        "parser": message_parser,
    }
    modules: dict[str, str] = {}
    for name, module in imported_modules.items():
        assert module.__file__ is not None
        modules[name] = str(Path(module.__file__).resolve())
    for name, path in modules.items():
        assert not Path(path).is_relative_to(checkout), ("checkout import rejected", name, path)
        if name != "parser":
            assert Path(path).is_relative_to(root / "venv"), ("not installed candidate", path)
    return InstalledProvenanceDAO(
        executable=sys.executable,
        isolated=sys.flags.isolated,
        version=importlib.metadata.version("slo"),
        modules=modules,
        hashes={name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in modules.items()},
    )


identity = provenance()
assert identity.isolated == 1
# Fixture imports must follow provenance rejection, including in the negative probe.
sys.path.insert(0, str(root / "support"))
from tests.bridges.claude.test_quota_recovery import QuotaThenSuccessTransport, quota_frame
from tests.cli.test_claude_bridge import scripted_adapter_class
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.dao import SubAgentTaskDAO
from src.bridges.claude.sdk.exceptions import ClaudeQuotaExceededError
from src.cli.headless import HeadlessRunner


async def prepare(config: SessionConfigDAO) -> SloAgentSession:
    """Prepare the real session with scripted native I/O for parent or headless child.

    Args:
        config (SessionConfigDAO): Disposable session/history configuration.

    Returns:
        SloAgentSession: Prepared session; its caller owns resource closure.
    """
    return await SloAgentSession.prepare(
        config=config,
        bridge_adapter_class=scripted_adapter_class(transport=QuotaThenSuccessTransport(frame=quota_frame())),
    )


async def main() -> None:
    """Exercise installed recovery or run the pool-owned failing headless child.

    The parent closes its session before dispatching the managed child. The real
    process owner drains and reaps that child; HeadlessRunner owns its session.

    Raises:
        SystemExit: Child exits with HeadlessRunner's asserted failure code, 1.
        AssertionError: Recovery, durable outcomes or managed launch differ.
    """
    if "--child" in sys.argv:
        (root / "child-identity.json").write_text(identity.model_dump_json(), encoding="utf-8")
        session_id = sys.argv[sys.argv.index("--session-id") + 1]
        code: int = await HeadlessRunner(
            config=SessionConfigDAO(
                workdir=root,
                model_name="claude-bridge:claude-haiku-5-5",
                reasoning_level="off",
                session_id=session_id,
                enable_history=True,
                history_root=root / "history",
            ),
            session_preparer=prepare,
        ).invoke(prompt="installed child")
        assert code == 1
        raise SystemExit(code)
    session: SloAgentSession = await prepare(
        config=SessionConfigDAO(
            workdir=root,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="installed-parent",
            enable_history=True,
            history_root=root / "history",
        )
    )
    try:
        try:
            async for event in session.invoke(text="installed inspect"):
                pass
        except ClaudeQuotaExceededError:
            pass
        else:
            raise AssertionError("missing installed quota")
        events: list[AgentStreamEventDAO] = [
            event async for event in session.invoke(text="installed explicit continuation")
        ]
        assert events[-1].kind == "run_completed"
    finally:
        await session.close_agent_resources()
    launches: list[tuple[str, ...]] = []

    async def spawn(
        *argv: str,
        stdout: int,
        stderr: int,
        limit: int,
        cwd: str | None,
        env: dict[str, str],
    ) -> asyncio.subprocess.Process:
        """Launch the scripted child at the existing ManagedAgentSpawn boundary.

        Args:
            argv (str): Production isolated CLI command; asserted before substitution.
            stdout (int): Pipe setting borrowed from the real process owner.
            stderr (int): Error pipe setting borrowed from the real process owner.
            limit (int): Stream reader buffer limit supplied by that owner.
            cwd (str | None): Child task working directory.
            env (dict[str, str]): Sanitized child environment supplied by the owner.

        Returns:
            asyncio.subprocess.Process: Real child; SubAgentProcess drains/reaps it.

        Raises:
            AssertionError: Production argv loses installed interpreter isolation.
        """
        assert argv[:4] == (sys.executable, "-I", "-m", "src.cli"), argv
        launches.append(argv)
        # Preserve interpreter/isolation while composing HeadlessRunner with native
        # fixtures at the supported process seam, never invoking live CLI auth.
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(root / "installed_probe.py"),
            str(root),
            str(checkout),
            "--child",
            *argv[4:],
            stdout=stdout,
            stderr=stderr,
            limit=limit,
            cwd=cwd,
            env=env,
        )

    async def relay(event: AgentStreamEventDAO) -> None:
        """Accept pool/child notices without another presentation sink.

        Args:
            event (AgentStreamEventDAO): Tagged notice from the real pool/process.
        """
        pass

    pool = SubAgentPool(
        orchestrator_session_id="installed-parent",
        owner_session_id="installed-parent",
        default_model="claude-bridge:claude-haiku-5-5",
        run_id=str(uuid4()),
        history_root=root / "history",
        relay=relay,
        process_factory=partial(SubAgentProcess, spawn=spawn),
    )
    result = await pool.dispatch(
        mode="single",
        tasks=[
            SubAgentTaskDAO(
                task_id="installed",
                task_summary="Verify installed child quota",
                prompt="installed child",
                cwd=str(root),
                session_id="installed-child",
                reasoning_level="off",
            )
        ],
    )
    assert len(launches) == 1 and not result.all_completed
    assert result.results[0].status == "failed" and "Claude usage limit reached" in result.results[0].answer
    store = FilesystemSessionHistoryStore(root=root / "history")
    for session_id, completed in [("installed-parent", 1), ("installed-child", 0)]:
        history_events = await store.load_events(session_id=session_id)
        assert sum(event.kind == "run_failed" for event in history_events) == 1
        assert sum(event.kind == "run_completed" for event in history_events) == completed
    receipt = {
        "parent": identity.model_dump(mode="json"),
        "child": json.loads((root / "child-identity.json").read_text(encoding="utf-8")),
        "managed_argv": launches[0],
    }
    (root / "installed-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    print("installed-quota-ok")


if __name__ == "__main__":
    asyncio.run(main())
