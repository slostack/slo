"""Nonpipe failures must be safe before diagnostics and terminal persistence."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.slo_agent.orchestrator.dao import SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore


@pytest.mark.parametrize("source", ["environment", "store"])
@pytest.mark.parametrize("failure", ["spawn", "stdout", "stderr", "wait"])
async def test_nonpipe_failure_never_exports_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, failure: str
) -> None:
    """Inject faults at real process-owner seams and scan populated terminal output."""
    root = tmp_path.resolve(strict=False)
    history = (root / "sessions/history").resolve(strict=False)
    credential_path = (root / "authentication.json").resolve(strict=False)
    assert history.is_relative_to(root) and credential_path.is_relative_to(root)
    secret = "synthetic-nonpipe-secret"
    monkeypatch.setattr("src.auth.credential_store.cfg", lambda **kwargs: str(credential_path))
    monkeypatch.delenv("SLO_OPENROUTER_API_KEY", raising=False)
    if source == "environment":
        monkeypatch.setenv("SLO_OPENROUTER_API_KEY", secret)
    else:
        CredentialStore().persist(
            cred=CredentialDAO(
                provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token=secret
            )
        )
    child = MagicMock(pid=12345, returncode=1)
    child.stdout.readline = AsyncMock(return_value=b"")
    child.stderr.readline = AsyncMock(return_value=b"")
    child.wait = AsyncMock(return_value=1)
    spawn = AsyncMock(return_value=child)
    error = OSError(f"controlled {failure}: {secret}")
    if failure == "spawn":
        spawn.side_effect = error
    elif failure == "wait":
        child.wait.side_effect = error
    else:
        getattr(child, failure).readline.side_effect = error
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    logs = MagicMock()
    monkeypatch.setattr("src.agents.slo_agent.orchestrator.process.log_error", logs)
    registry = ProcessRegistry()
    task = SubAgentTaskDAO(task_id="task", prompt="safe")
    execution_id = registry.register(task_id="task", session_id="child", task=task)
    process = SubAgentProcess(
        task=task,
        session_id="child",
        model=None,
        relay=AsyncMock(),
        registry=registry,
        execution_id=execution_id,
        parent_session_id="parent",
        slo_home=root,
    )
    result = await process.run()
    assert result.status == "failed"
    assert secret not in result.model_dump_json()
    assert secret not in repr(logs.call_args_list)
    assert not logs.call_args.kwargs.get("stack_trace", False)
    files = list(history.rglob("*"))
    assert any(path.name == "status.json" for path in files)
    for path in files:
        assert path.resolve(strict=False).is_relative_to(root)
        if path.is_file():
            assert secret not in path.read_text()
