"""Editor pane boundary: captured owner, live admission and literal shell argv."""

import asyncio
import json
import shlex
from typing import Optional

import pytest

from src.agents.slo_agent.herdr.dao import (
    HerdrCliCommandDAO,
    HerdrCommandAdmission,
    HerdrCommandOutcomeDAO,
    HerdrCommandResultDAO,
)


class RecordingPaneTransport:
    """Model the shared transport's lock/admission without executing CLI commands."""

    def __init__(self, *, failure: str = "", hold: bool = False) -> None:
        """Retain a failure cutoff or a controllable shared-lock barrier."""
        self.closed = False
        self.failure = failure
        self.commands: list[HerdrCliCommandDAO] = []
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()
        if not hold:
            self.release.set()

    async def invoke(
        self, *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Recheck live permission only after waiting as the real lock does."""
        self.waiting.set()
        await self.release.wait()
        if not admission.try_admit():
            return HerdrCommandResultDAO(outcome=HerdrCommandOutcomeDAO(status="suppressed"))
        self.commands.append(command)
        if self.failure == "exception" or (self.failure == "run-exception" and command.argv[1] == "run"):
            raise RuntimeError("private transport secret")
        failed = self.failure == command.argv[1]
        payload: Optional[bytes] = None
        if command.capture_json:
            payload = (
                b"{}"
                if self.failure == "malformed"
                else json.dumps({"result": {"pane": {"pane_id": "editor-pane"}}}).encode()
            )
        result = HerdrCommandResultDAO(
            outcome=HerdrCommandOutcomeDAO(status="rejected" if failed else "ok"),
            json_bytes=payload,
            admitted=True,
        )
        admission.complete(result=result)
        return result


@pytest.mark.parametrize(
    argnames="filename",
    argvalues=["normal ü.py", "x'; touch sentinel; #", '$(touch sentinel)`touch sentinel`"\\.py'],
)
async def test_editor_submits_literal_shell_command_to_captured_owner(filename: str) -> None:
    """A hostile file stays one inert argv item through the actual command-string boundary."""
    from src.agents.slo_agent.herdr.editor import HerdrEditorLauncher

    transport = RecordingPaneTransport()
    launcher = HerdrEditorLauncher(
        transport=transport, owner_pane_id="captured-owner", authority=lambda: True
    )
    argv = ("/path with spaces/nvim", "--", "/files/" + filename)
    outcome = await launcher.invoke(argv=argv)
    assert outcome.status == "submitted"
    assert outcome.pane_id == "editor-pane"
    assert transport.commands[0].argv == (
        "pane",
        "split",
        "--pane",
        "captured-owner",
        "--direction",
        "right",
        "--no-focus",
    )
    run = transport.commands[1].argv
    assert run[:3] == ("pane", "run", "editor-pane")
    assert run[3] == shlex.join(argv)
    # Full shell lexical roundtrip, with punctuation recognized: no active operator or substitution.
    lexer = shlex.shlex(instream=run[3], posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    assert tuple(lexer) == argv
    await launcher.close()
    assert len(transport.commands) == 2  # no pane close, focus or fallback
    assert not transport.closed  # reporter owns shared transport


@pytest.mark.parametrize(
    argnames="failure", argvalues=["split", "malformed", "run", "exception", "run-exception"]
)
async def test_editor_failure_preserves_manual_recovery_without_retry(failure: str) -> None:
    """Failed/ambiguous operations return safe evidence, never retry or delete panes."""
    from src.agents.slo_agent.herdr.editor import HerdrEditorLauncher

    transport = RecordingPaneTransport(failure=failure)
    launcher = HerdrEditorLauncher(transport=transport, owner_pane_id="owner", authority=lambda: True)
    outcome = await launcher.invoke(argv=("/nvim", "--", "/file"))
    assert outcome.status == "failed"
    assert len(transport.commands) == (2 if failure in ("run", "run-exception") else 1)
    assert outcome.pane_id == ("editor-pane" if failure in ("run", "run-exception") else None)
    assert "private" not in outcome.model_dump_json()
    await launcher.close()


async def test_editor_revocation_under_lock_and_close_drain() -> None:
    """Queued commands lose authority before submission; closing drains owned waiters."""
    from src.agents.slo_agent.herdr.editor import HerdrEditorLauncher

    permitted = True
    transport = RecordingPaneTransport(hold=True)
    launcher = HerdrEditorLauncher(transport=transport, owner_pane_id="owner", authority=lambda: permitted)
    task = asyncio.create_task(coro=launcher.invoke(argv=("/nvim", "--", "/file")))
    await asyncio.wait_for(fut=transport.waiting.wait(), timeout=2)
    permitted = False
    transport.release.set()
    assert (await task).status == "failed"
    assert transport.commands == []
    assert (await launcher.invoke(argv=("/nvim", "--", "/file"))).status == "failed"
    await launcher.close()
    assert (await launcher.invoke(argv=("/nvim", "--", "/file"))).status == "failed"


@pytest.mark.parametrize(argnames="control", argvalues=["\n", "\r", "\x00", "\x1b", "\t"])
async def test_editor_line_input_rejects_controls_before_split(control: str) -> None:
    """Shell quoting cannot protect terminal line-editor controls; refuse without effects."""
    from src.agents.slo_agent.herdr.editor import HerdrEditorLauncher

    transport = RecordingPaneTransport()
    launcher = HerdrEditorLauncher(transport=transport, owner_pane_id="owner", authority=lambda: True)
    assert (await launcher.invoke(argv=("/nvim", "--", "/file" + control))).status == "failed"
    assert transport.commands == []
    await launcher.close()
