"""Offline child credential secrecy at the real capture and relay boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import IO
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.dao import SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.launch_tool import LaunchWorkflowTool
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.spawn_env import redact_openrouter_credential
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.agents.providers.openrouter import OpenRouterErrorNormalizer
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver


@pytest.fixture(autouse=True)
def owned_capture_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard filesystem boundaries for these and surrounding process tests."""
    root = tmp_path.resolve()
    original_open = Path.open
    original_mkdir = Path.mkdir

    def check(path: Path) -> None:
        """Reject writes outside the owned root, including symlink escapes."""
        assert path.resolve(strict=False).is_relative_to(root)

    def guarded_open(
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO[bytes] | IO[str]:
        """Guard every capture open before real writes occur."""
        check(path)
        return original_open(
            path, mode=mode, buffering=buffering, encoding=encoding, errors=errors, newline=newline
        )

    def guarded_mkdir(path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        """Guard capture and atomic-writer ancestry before directory creation."""
        check(path)
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "mkdir", guarded_mkdir)
    # Atomic writers create exclusive regular temporary siblings within the checked parent.


def test_redact_openrouter_credential_when_no_credential_returns_original_bytes() -> None:
    """Detached captures preserve ordinary bytes when no credential crossed the boundary."""
    raw = b'{"message":"ordinary diagnostic"}\n'

    assert redact_openrouter_credential(raw=raw, credential=b"") == raw


def test_redact_openrouter_credential_when_credential_is_present_replaces_only_literal() -> None:
    """Detached capture redaction removes the forwarded credential without parsing private payloads."""
    secret = b"detached-fd-secret"
    raw = b'{"message":"detached-fd-secret","reasoning":"opaque"}\n'

    assert (
        redact_openrouter_credential(raw=raw, credential=secret)
        == b'{"message":"[REDACTED]","reasoning":"opaque"}\n'
    )


async def test_detached_launch_passes_openrouter_key_only_in_child_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the detached-launch FD boundary without creating an actual child process."""
    secret = "detached-launch-secret"
    root = tmp_path.resolve()
    monkeypatch.setenv("SLO_OPENROUTER_API_KEY", secret)
    handle = WorkflowHandleDAO(
        workflow_id="wf-detached",
        owner_session_id="owner",
        orchestrator_session_id="orchestrator",
        pid=0,
        brief="Use only local fixtures.",
        cwd=str(root),
        state="launching",
    )
    spawned = MagicMock(pid=4321)
    spawn = AsyncMock(return_value=spawned)
    store = MagicMock()
    store.write = AsyncMock()

    result = await LaunchWorkflowTool._spawn_and_patch(
        store=store,
        spawn=spawn,
        history_root=root / "history",
        handle=handle,
        model="openrouter:vendor/detached",
        history_warning=None,
    )

    assert json.loads(result)["pid"] == 4321
    assert spawn.await_args is not None
    argv = spawn.await_args.args
    env = spawn.await_args.kwargs["env"]
    assert env["SLO_OPENROUTER_API_KEY"] == secret
    assert all(secret not in argument for argument in argv)
    for name in ("stdout.jsonl", "stderr.log"):
        text = (root / "history" / "orchestrator" / name).read_text(encoding="utf-8")
        assert secret not in text


async def test_headless_preparation_failure_writes_terminal_status_and_notifies_with_safe_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Drive the pre-session failure path through its real stdout, status, and notifier owners."""
    from src.agents.slo_agent.history.inbox.store import SessionInboxStore
    from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier
    from src.cli.headless import HeadlessRunner
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO

    root = tmp_path.resolve()
    secret = "preparation-secret"
    credential_path = root / "authentication.json"
    assert credential_path.resolve(strict=False).is_relative_to(root)
    monkeypatch.setenv("SLO_WORKFLOW_ID", "wf-preparation")
    monkeypatch.setattr("src.auth.credential_store.cfg", lambda **kwargs: str(credential_path))
    monkeypatch.setattr("src.cli.headless.default_history_root", lambda: root / "history")
    inbox = SessionInboxStore(history_root=root / "history")
    notifier = WorkflowNotifier(
        target_session_id="owner",
        orchestrator_session_id="preparation-session",
        workflow_id="wf-preparation",
        inbox_store=inbox,
    )
    runner = HeadlessRunner(
        config=SessionConfigDAO(
            workdir=root,
            model_name="openrouter:vendor/missing",
            session_id="preparation-session",
            history_root=root / "history",
            enable_history=True,
        ),
        notify_session_id="owner",
        notifier=notifier,
    )

    async def fail_preparation(*, config: SessionConfigDAO):
        """Raise an intentionally secret-bearing error that must not cross public artifacts."""
        del config
        raise RuntimeError(secret)

    monkeypatch.setattr("src.cli.headless.SloAgentSession.prepare", fail_preparation)
    exit_code = await runner.invoke(prompt="prepare locally")

    stdout = capsys.readouterr().out
    status_path = root / "history" / "preparation-session" / "orchestrator.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    pending = await inbox.list_pending(session_id="owner")
    public = (
        stdout
        + status_path.read_text(encoding="utf-8")
        + "".join(message.model_dump_json() for message in pending)
    )
    assert exit_code == 1
    assert status["state"] == "failed"
    assert [message.kind for message in pending] == ["workflow_failed"]
    assert secret not in public
    assert "Model preparation failed" in public


@pytest.mark.parametrize("terminal", [True, False])
async def test_child_capture_secret_stays_in_spawn_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: bool
) -> None:
    """Exercise captures, fallback, relay, lifecycle and durable fleet with no child."""
    secret = "synthetic-openrouter-capture-sentinel"
    monkeypatch.setenv("SLO_OPENROUTER_API_KEY", secret)
    monkeypatch.setenv("SLO_OTHER_SECRET", "not-forwarded")
    monkeypatch.setenv("SLO_PLUGINS_DISABLED", "1")
    root = tmp_path.resolve()
    store = FleetStore(history_root=root / "sessions/history", orchestrator_session_id="parent")
    registry = ProcessRegistry(fleet_store=store)
    task = SubAgentTaskDAO(task_id="task", prompt="Harmless task")
    execution_id = registry.register(task_id="task", session_id="child", task=task)
    relay = AsyncMock()
    lifecycle = MagicMock()
    logs = MagicMock()
    monkeypatch.setattr("src.agents.slo_agent.orchestrator.process.emit_lifecycle_event", lifecycle)
    monkeypatch.setattr("src.agents.slo_agent.orchestrator.process.log_info", logs)
    events = [AgentStreamEventDAO(kind="text_delta", delta=f"diagnostic {secret}")]
    if terminal:
        events.append(AgentStreamEventDAO(kind="run_failed", content=f"failure {secret}"))
    child = MagicMock(pid=12345, returncode=1)
    child.stdout.readline = AsyncMock(
        side_effect=[e.model_dump_json().encode() + b"\n" for e in events] + [b""]
    )
    child.stderr.readline = AsyncMock(
        side_effect=[json.dumps({"message": f"warning {secret}"}).encode() + b"\n", b""]
    )
    child.wait = AsyncMock(return_value=1)
    spawn = AsyncMock(return_value=child)
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    process = SubAgentProcess(
        task=task,
        session_id="child",
        model=None,
        relay=relay,
        registry=registry,
        execution_id=execution_id,
        parent_session_id="parent",
        slo_home=root,
    )
    result = await process.run()
    assert spawn.call_args.kwargs["env"]["SLO_OPENROUTER_API_KEY"] == secret
    assert spawn.call_args.kwargs["env"]["SLO_PLUGINS_DISABLED"] == "1"
    assert "SLO_OTHER_SECRET" not in spawn.call_args.kwargs["env"]
    assert all(secret not in arg for arg in spawn.call_args.args)
    capture = root / "sessions/history/parent/children/child"
    context = json.loads((capture / "spawn_context.json").read_text())
    assert context["prompt"] == "Harmless task"
    for name in ("spawn_context.json", "status.json", "stdout.jsonl", "stderr.jsonl"):
        text = (capture / name).read_text()
        assert secret not in text, name
        for line in text.splitlines() if name.endswith("jsonl") else [text]:
            json.loads(line)
    assert "[REDACTED]" in result.answer
    assert "failure" in result.answer if terminal else "warning" in result.answer
    assert relay.await_args_list[0].args[0].delta == "diagnostic [REDACTED]"
    assert all(secret not in call.args[0].model_dump_json() for call in relay.await_args_list)
    assert all(secret not in call.kwargs["message"] for call in lifecycle.call_args_list)
    assert all(secret not in call.kwargs.get("line", "") for call in logs.call_args_list)
    snapshot = store.load()
    assert snapshot is not None
    assert snapshot.entries[0].last_text == result.answer
    assert secret not in snapshot.model_dump_json()


@pytest.mark.parametrize("resolver_state", ["rotated", "failed"])
async def test_child_artifacts_preserve_admitted_redaction_after_rotation_or_resolver_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resolver_state: str,
) -> None:
    """Keep an admitted child credential redacted across every populated child artifact.

    The child captures credential A exactly once at operation admission. Its later public
    failure text is derived from the actual OpenRouter error normalizer, whose synthetic
    raw provider body carries both credentials and a non-credential marker. This verifies
    that the raw body reaches no child artifact while normal child output, terminal status,
    result, and fleet projection remain populated.
    """
    root = tmp_path.resolve()
    admitted_key = "F86_CHILD_ADMITTED_KEY_A"
    rotated_key = "F86_CHILD_EFFECTIVE_KEY_B"
    raw_body_marker = "F86_CHILD_RAW_PROVIDER_BODY"
    credential_a = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token=admitted_key,
    )
    credential_b = credential_a.model_copy(update={"access_token": rotated_key})
    store = FleetStore(history_root=root / "sessions/history", orchestrator_session_id="parent")
    registry = ProcessRegistry(fleet_store=store)
    task = SubAgentTaskDAO(task_id="task", prompt="Harmless task")
    execution_id = registry.register(task_id="task", session_id="child", task=task)
    relay = AsyncMock()
    logs = MagicMock()
    lifecycle = MagicMock()
    monkeypatch.setattr("src.agents.slo_agent.orchestrator.process.log_info", logs)
    monkeypatch.setattr("src.agents.slo_agent.orchestrator.process.emit_lifecycle_event", lifecycle)

    class ProviderBodyError(RuntimeError):
        """Carry a synthetic body solely through the production normalizer boundary."""

        def __init__(self) -> None:
            """Build the synthetic provider failure without placing it on a child stream."""
            super().__init__("synthetic provider failure")
            self.status_code = 400
            self.body = {
                "error": {
                    "type": "invalid_request",
                    "message": f"{admitted_key} {rotated_key} {raw_body_marker}",
                }
            }

    normalized_error = OpenRouterErrorNormalizer.normalize(error=ProviderBodyError())
    safe_failure = str(normalized_error)
    assert admitted_key not in safe_failure
    assert rotated_key not in safe_failure
    assert raw_body_marker not in safe_failure

    def resolve_after_admission(*, provider: ProviderName) -> CredentialDAO:
        """Simulate rotation or failure only after the child has captured A."""
        assert provider is ProviderName.OPENROUTER
        if resolver_state == "rotated":
            return credential_b
        raise OSError("resolver unavailable after admission")

    child = MagicMock(pid=12345, returncode=1)
    child.stdout.readline = AsyncMock(
        side_effect=[
            AgentStreamEventDAO(kind="text_delta", delta=f"ordinary output {admitted_key}")
            .model_dump_json()
            .encode("utf-8")
            + b"\n",
            AgentStreamEventDAO(kind="run_failed", content=f"failure {admitted_key}: {safe_failure}")
            .model_dump_json()
            .encode("utf-8")
            + b"\n",
            b"",
        ]
    )
    child.stderr.readline = AsyncMock(
        side_effect=[json.dumps({"message": safe_failure}).encode("utf-8") + b"\n", b""]
    )
    child.wait = AsyncMock(return_value=1)
    spawn = AsyncMock(return_value=child)
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    process = SubAgentProcess(
        task=task,
        session_id="child",
        model=None,
        relay=relay,
        registry=registry,
        execution_id=execution_id,
        parent_session_id="parent",
        slo_home=root,
    )

    with monkeypatch.context() as after_admission:
        after_admission.setattr(CredentialResolver, "resolve", lambda *, provider: credential_a)
        run_task = __import__("asyncio").create_task(process.run())
        await __import__("asyncio").sleep(0)
        after_admission.setattr(CredentialResolver, "resolve", resolve_after_admission)
        result = await run_task

    capture_dir = root / "sessions/history/parent/children/child"
    artifact_paths = [
        capture_dir / "stdout.jsonl",
        capture_dir / "stderr.jsonl",
        capture_dir / "status.json",
        root / "sessions/history/parent/fleet.json",
    ]
    artifact_text = "\n".join(path.read_text(encoding="utf-8") for path in artifact_paths)
    public_text = "\n".join(
        [
            result.model_dump_json(),
            "".join(event.model_dump_json() for event in [call.args[0] for call in relay.await_args_list]),
            "\n".join(call.kwargs.get("line", "") for call in logs.call_args_list),
            "\n".join(call.kwargs.get("message", "") for call in lifecycle.call_args_list),
        ]
    )
    assert "ordinary output" in artifact_text
    assert "OpenRouter request failed" in artifact_text
    assert "failure [REDACTED]" in result.answer
    assert store.load() is not None
    for forbidden in (admitted_key, rotated_key, raw_body_marker):
        assert forbidden not in artifact_text
        assert forbidden not in public_text
