"""Real detached FD regression; only a bounded, test-owned child is executed."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import IO
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.slo_agent.orchestrator.launch_tool import LaunchWorkflowTool
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore


@pytest.mark.parametrize("sentinel", ["synthetic-call3-detached-fd-sentinel", 'synthetic-quote"/key'])
@pytest.mark.parametrize("stored_key", [False, True])
async def test_detached_capture_redacts_real_split_fd_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stored_key: bool, sentinel: str
) -> None:
    """Require redaction before persistence, preserving useful stdout/stderr.

    The injected spawn substitutes only the executable workload. Production
    capture handles, environment and session-detachment kwargs are preserved.
    The child writes only checked private history and inherited captures, exits
    itself, and is reaped by its owner; no process is signalled.
    """
    root = tmp_path.resolve()
    history_root = root / "history"
    assert history_root.resolve(strict=False).is_relative_to(root)
    auth_path = root / "auth" / "authentication.json"
    assert auth_path.resolve().is_relative_to(root)
    monkeypatch.setenv("SLO_AUTH_FILE", str(auth_path))
    if stored_key:
        monkeypatch.delenv("SLO_OPENROUTER_API_KEY", raising=False)
        CredentialStore(path=auth_path).persist(
            cred=CredentialDAO(
                provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token=sentinel
            )
        )
    else:
        monkeypatch.setenv("SLO_OPENROUTER_API_KEY", sentinel)
    monkeypatch.setenv("SLO_OTHER_SECRET", "must-not-forward")
    handle = WorkflowHandleDAO(
        workflow_id="wf-call3-fd",
        owner_session_id="owner",
        orchestrator_session_id="orchestrator",
        pid=0,
        brief="Local controlled capture regression",
        cwd=str(root),
        state="launching",
    )
    store = MagicMock()
    store.write = AsyncMock()

    async def spawn(
        *argv: str,
        start_new_session: bool,
        stdout: IO[bytes],
        stderr: IO[bytes],
        env: dict[str, str],
    ) -> asyncio.subprocess.Process:
        """Run a finite Python child against the real production capture FDs."""
        assert all(sentinel not in argument for argument in argv)
        assert env.get("SLO_OPENROUTER_API_KEY") == (None if stored_key else sentinel)
        assert "SLO_OTHER_SECRET" not in env
        for capture in (stdout, stderr):
            assert Path(capture.name).resolve().is_relative_to(root)
        script = (
            "import os, sys, asyncio\n"
            f"sys.path.insert(0, {str(Path.cwd())!r})\n"
            "from pathlib import Path\n"
            "from src.auth.credential_resolver import CredentialResolver\n"
            "from src.auth.credential_dao import ProviderName\n"
            "from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore\n"
            "from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO\n"
            "from src.agents.providers.message_extension import ProviderMessageExtensionDAO\n"
            "key = CredentialResolver.require(provider=ProviderName.OPENROUTER).access_token.encode()\n"
            "async def persist():\n"
            f" root = Path({str(root)!r}).resolve()\n"
            " history = root / 'private-history'\n"
            " assert history.resolve().is_relative_to(root)\n"
            " store = FilesystemSessionHistoryStore(root=history)\n"
            " await store.ensure_session(session_id='private', workdir=root, model_name='openrouter:vendor/local')\n"
            " extension = ProviderMessageExtensionDAO(provider=ProviderName.OPENROUTER, "
            "source_model_name='openrouter:vendor/local', reasoning_details=[{'data': 'OPAQUE_CHILD_ANCHOR'}])\n"
            " await store.append_event(event=SessionHistoryEventDAO(session_id='private', "
            "kind='assistant_message', payload=SessionHistoryEventPayloadDAO(content=key.decode(), "
            "provider_message_extension=extension)))\n"
            "asyncio.run(persist())\n"
            "for fd in (1, 2):\n"
            " os.write(fd, b'permitted diagnostic: ')\n"
            " for byte in key: os.write(fd, bytes([byte]))\n"
            " os.write(fd, b'\\n')\n"
        )
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-B",
            "-c",
            script,
            start_new_session=start_new_session,
            stdout=stdout,
            stderr=stderr,
            env=env,
            cwd=root,
        )
        assert await child.wait() == 0
        return child

    result = await LaunchWorkflowTool._spawn_and_patch(
        store=store,
        spawn=spawn,
        history_root=history_root,
        handle=handle,
        model="openrouter:vendor/local",
        history_warning=None,
    )
    assert sentinel not in result
    captures = [history_root / "orchestrator" / name for name in ("stdout.jsonl", "stderr.log")]
    contents = [capture.read_bytes() for capture in captures]
    assert all(b"permitted diagnostic:" in content for content in contents)
    assert all(
        sentinel.encode() not in content for content in contents
    ), "literal synthetic credential persisted through production detached FDs"
    assert all(b"[REDACTED]" in content for content in contents)
    private_path = root / "private-history" / "private" / "events.jsonl"
    assert private_path.resolve().is_relative_to(root)
    private_text = private_path.read_text()
    assert sentinel not in private_text
    private_event = json.loads(private_text)
    assert private_event["payload"]["content"] == "[REDACTED]"
    assert private_event["payload"]["provider_message_extension"]["reasoning_details"] == [
        {"data": "OPAQUE_CHILD_ANCHOR"}
    ]
    for artifact in (*captures, root / "private-history" / "private" / "session.json"):
        assert "OPAQUE_CHILD_ANCHOR" not in artifact.read_text()
    assert "OPAQUE_CHILD_ANCHOR" not in result
