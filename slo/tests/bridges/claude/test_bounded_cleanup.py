"""Bounded cleanup at the supported transport owner, without native accounts."""

import asyncio
from pathlib import Path

import pytest

from src.bridges.claude.sdk.native_transport import ClaudeNativeTransport
from src.bridges.claude.sdk.sdk_runtime import ClaudeSDKRuntime
from src.bridges.claude.sdk.dao import ClaudeInvocationOptionsDAO, ClaudeSessionOptionsDAO
from tests.cli.test_claude_bridge import ScriptedClaudeTransport


async def test_disconnect_deadline_retains_failed_owner_for_explicit_retry(tmp_path: Path) -> None:
    """A wedged custom close cannot hang forever or authorize a successor."""

    class WedgedTransport(ScriptedClaudeTransport):
        """Expose a cleanup gate that is released only for explicit retry."""

        released = False

        async def close(self) -> None:
            """Remain cancellable but never acknowledge closure before release."""
            if not self.released:
                await asyncio.Event().wait()
            await super().close()

    transport = WedgedTransport(block_response=True)
    runtime = ClaudeSDKRuntime(transport=transport, cleanup_grace_seconds=0.02, cleanup_force_seconds=0.02)
    runtime.start(
        session_options=ClaudeSessionOptionsDAO(
            session_id="s", model_id="claude-bridge:model", working_directory=tmp_path, instructions=""
        ),
        invocation_options=ClaudeInvocationOptionsDAO(invocation_id="i", text="hi"),
    )
    try:
        async with asyncio.timeout(2):
            await transport.submitted.wait()
            with pytest.raises(RuntimeError, match="closure is unconfirmed"):
                await runtime.cancel()
            assert runtime._owner is not None
            assert not runtime._owner.done()
            with pytest.raises(RuntimeError):
                runtime.completed_session_id()
            transport.released = True
            await runtime.close()
            assert runtime._owner is not None
            assert runtime._owner.done()
            assert transport.closed
            assert transport.prompts == ["hi"]
    finally:
        transport.released = True
        await runtime.close()


@pytest.mark.parametrize("startup", [False, True])
async def test_missing_control_ack_is_bounded_before_disconnect(tmp_path: Path, startup: bool) -> None:
    """Cancellation does not wait for an initialize/interrupt acknowledgement."""
    import json

    class MissingAckTransport(ScriptedClaudeTransport):
        """Drop only the selected official SDK control acknowledgement."""

        control_entered: asyncio.Event

        def __init__(self) -> None:
            """Expose a public wire barrier."""
            super().__init__(block_response=True)
            self.control_entered = asyncio.Event()

        async def write(self, data: str) -> None:
            """Record selected control and deliberately never acknowledge it."""
            message = json.loads(data)
            subtype = message.get("request", {}).get("subtype")
            if subtype == ("initialize" if startup else "interrupt"):
                self.dropped_request = message["request_id"]
                self.control_entered.set()
                return
            await super().write(data=data)

    transport = MissingAckTransport()
    runtime = ClaudeSDKRuntime(transport=transport, cleanup_grace_seconds=0.02, cleanup_force_seconds=0.02)
    runtime.start(
        session_options=ClaudeSessionOptionsDAO(
            session_id="s", model_id="claude-bridge:model", working_directory=tmp_path, instructions=""
        ),
        invocation_options=ClaudeInvocationOptionsDAO(invocation_id="i", text="hi"),
    )
    try:
        async with asyncio.timeout(1):
            await (transport.control_entered.wait() if startup else transport.submitted.wait())
        cancelling = asyncio.create_task(coro=runtime.cancel())
        done, _ = await asyncio.wait({cancelling}, timeout=0.3)
        assert cancelling in done, "control acknowledgement exceeded cleanup budget"
        if startup:
            await cancelling
        else:
            with pytest.raises(RuntimeError, match="unconfirmed"):
                await cancelling
            # The missing ack consumed the grace budget. Only explicit close
            # may retry the unforced injected transport's remaining cleanup.
            await runtime.close()
        assert runtime._owner is not None
        assert runtime._owner.done() and transport.closed
        assert transport.prompts == ([] if startup else ["hi"])
    finally:
        # Test failure must not leave an owner waiting on a 60-second SDK control timer.
        if hasattr(transport, "dropped_request"):
            transport.messages.put_nowait(
                {
                    "type": "control_response",
                    "response": {
                        "subtype": "success",
                        "request_id": transport.dropped_request,
                        "response": {},
                    },
                }
            )
        if "cancelling" in locals():
            await asyncio.gather(cancelling, return_exceptions=True)
        await runtime.close()


async def test_interrupt_and_disconnect_share_one_grace_budget(tmp_path: Path) -> None:
    """Missing ack must not buy a second grace interval before retained failure."""
    import json

    class NoAckOrClose(ScriptedClaudeTransport):
        """Consume acknowledgement and cleanup deadlines independently."""

        released = False

        async def write(self, data: str) -> None:
            """Drop interrupt only."""
            if json.loads(data).get("request", {}).get("subtype") == "interrupt":
                return
            await super().write(data=data)

        async def close(self) -> None:
            """Refuse closure before explicit retry."""
            if not self.released:
                await asyncio.Event().wait()
            await super().close()

    transport = NoAckOrClose(block_response=True)
    runtime = ClaudeSDKRuntime(transport=transport, cleanup_grace_seconds=0.2, cleanup_force_seconds=0.02)
    runtime.start(
        session_options=ClaudeSessionOptionsDAO(
            session_id="s", model_id="claude-bridge:model", working_directory=tmp_path, instructions=""
        ),
        invocation_options=ClaudeInvocationOptionsDAO(invocation_id="i", text="hi"),
    )
    try:
        await transport.submitted.wait()
        start = asyncio.get_running_loop().time()
        with pytest.raises(RuntimeError, match="unconfirmed"):
            await runtime.cancel()
        elapsed = asyncio.get_running_loop().time() - start
        assert elapsed < 0.32, f"separate ack+disconnect grace budgets: {elapsed}"
    finally:
        transport.released = True
        await runtime.close()


async def test_startup_cancel_with_missing_ack_and_wedged_close_retains_retry_owner(tmp_path: Path) -> None:
    """SDK connect's shielded rollback must not block cancellation acknowledgement forever."""
    import json

    class StartupWedged(ScriptedClaudeTransport):
        """Refuse initialization and cleanup independently."""

        refuse = True

        async def write(self, data: str) -> None:
            """Do not acknowledge initialization."""
            message = json.loads(data)
            if message.get("request", {}).get("subtype") == "initialize":
                self.submitted.set()
                return
            await super().write(data=data)

        async def close(self) -> None:
            """Expose the SDK's shielded connect rollback."""
            if self.refuse:
                await asyncio.Event().wait()
            await super().close()

    transport = StartupWedged()
    runtime = ClaudeSDKRuntime(transport=transport, cleanup_grace_seconds=0.02, cleanup_force_seconds=0.02)
    runtime.start(
        session_options=ClaudeSessionOptionsDAO(
            session_id="s", model_id="claude-bridge:model", working_directory=tmp_path, instructions=""
        ),
        invocation_options=ClaudeInvocationOptionsDAO(invocation_id="i", text="hi"),
    )
    task = None
    try:
        await transport.submitted.wait()
        task = asyncio.create_task(coro=runtime.cancel())
        done, _ = await asyncio.wait({task}, timeout=0.3)
        assert task in done, "shielded connect rollback exceeded cleanup budget"
        with pytest.raises(RuntimeError, match="unconfirmed"):
            await task
        assert runtime._owner is not None
        assert not runtime._owner.done() and not transport.prompts
    finally:
        transport.refuse = False
        # Wake the existing shielded close for pre-fix evidence; no second native send.
        if task is not None and not task.done():
            assert runtime._owner is not None
            runtime._owner.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await runtime.close()


async def test_native_transport_forces_and_reaps_only_its_owned_child(tmp_path: Path) -> None:
    """A synthetic child ignoring EOF is killed/reaped within the transport deadline."""
    import sys
    from claude_agent_sdk import ClaudeAgentOptions

    script = tmp_path / "child.py"
    assert script.resolve().is_relative_to(tmp_path.resolve())
    script.write_text("import time\nprint('ready', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
    spawned: list[asyncio.subprocess.Process] = []

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        """Create only a test-owned interpreter, never the native executable."""
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        spawned.append(child)
        return child

    transport = ClaudeNativeTransport(
        options=ClaudeAgentOptions(cli_path="/not-executed", cwd=tmp_path),
        process_factory=spawn,
        grace_seconds=0.02,
        force_seconds=1,
    )
    try:
        await transport.connect()
        assert spawned[0].stdout is not None
        assert await spawned[0].stdout.readline() == b"ready\n"
        async with asyncio.timeout(2):
            await transport.close()
        assert spawned[0].returncode is not None
        assert not transport.is_ready()
        await transport.close()
    finally:
        await transport.force_close()
