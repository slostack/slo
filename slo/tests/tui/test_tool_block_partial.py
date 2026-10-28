"""Tests for the core ``tool_output_update`` TUI hop (75.a.5-CORE Hop 3).

The projector patches the already-mounted ``ToolExecutionBlock`` in place:
an update for a known id calls ``update_partial``; an update for an unknown id
mounts a block via ``_ensure_tool_block`` first; only the terminal
``tool_result`` pops the block from the mounted map.
"""

from __future__ import annotations

import pytest
from textual.content import Content

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.tools.tool_output import ToolOutputUpdateDAO
from src.tui.transcript_projector import TranscriptProjectionAdapter
from tests.tui.test_transcript_projector import FakeHost, FakeToolBlock


class _PartialRecordingToolBlock(FakeToolBlock):
    """Tool block fake that also records partial updates."""

    def __init__(self, *, tool_call_id: str, tool_name: str | None) -> None:
        """Initialize with empty partial history.

        Args:
            tool_call_id (str): Stable call id.
            tool_name (str | None): Tool name when known.
        """
        super().__init__(tool_call_id=tool_call_id, tool_name=tool_name)
        self.partials: list[ToolOutputUpdateDAO] = []

    def update_partial(self, *, snapshot: ToolOutputUpdateDAO) -> None:
        """Record one partial snapshot.

        Args:
            snapshot (ToolOutputUpdateDAO): Latest display snapshot.
        """
        super().update_partial(snapshot=snapshot)
        self.partials.append(snapshot)


class _PartialHost(FakeHost):
    """Host fake mounting partial-aware tool blocks."""

    async def mount_tool_execution_block(
        self,
        *,
        tool_call_id: str,
        tool_name: str | None,
        before: int | None = None,
    ) -> _PartialRecordingToolBlock:
        """Mount one partial-recording fake block.

        Args:
            tool_call_id (str): Stable call id.
            tool_name (str | None): Tool name when known.
            before (int | None): Unused insertion index.

        Returns:
            _PartialRecordingToolBlock: The mounted fake.
        """
        del before
        block = _PartialRecordingToolBlock(tool_call_id=tool_call_id, tool_name=tool_name)
        self.tool_blocks[tool_call_id] = block
        self.mount_order.append("tool")
        return block


@pytest.mark.asyncio
async def test_nameless_early_partial_retains_unknown_name_until_result() -> None:
    """An early unnamed snapshot remains display-only and accepts later identity."""
    host = _PartialHost()
    projector = TranscriptProjectionAdapter(host=host)
    await projector.project(
        event=AgentStreamEventDAO(kind="tool_output_update", tool_call_id="unnamed", content="early output")
    )
    block = host.tool_blocks["unnamed"]
    assert isinstance(block, _PartialRecordingToolBlock)
    assert block.tool_name is None
    assert block.partials[0].tool_name == ""
    assert block.partials[0].content_snapshot == "early output"
    assert block.result_output is None
    assert block._partial_output == "early output"
    headline = block._headline.render()
    assert isinstance(headline, Content)
    assert headline.plain == ""
    await projector.project(
        event=AgentStreamEventDAO(
            kind="tool_result", tool_call_id="unnamed", tool_name="bash", content="final output"
        )
    )
    assert block.tool_name == "bash"
    assert block.result_output == "final output"
    assert host.mount_order == ["tool"]
    assert "unnamed" not in projector._tool_blocks


@pytest.mark.asyncio
async def test_partial_update_patches_mounted_block_in_place() -> None:
    """A known block receives ``update_partial`` and stays mounted."""
    host = _PartialHost()
    projector = TranscriptProjectionAdapter(host=host)
    await projector.project(
        event=AgentStreamEventDAO(kind="tool_call_end", tool_call_id="call-1", tool_name="bash")
    )
    block = host.tool_blocks["call-1"]
    assert isinstance(block, _PartialRecordingToolBlock)

    await projector.project(
        event=AgentStreamEventDAO(
            kind="tool_output_update",
            tool_call_id="call-1",
            tool_name="bash",
            content="exit_code: 0\npartial",
            metadata={"truncated": False},
        )
    )

    assert len(block.partials) == 1
    assert block.partials[0].content_snapshot == "exit_code: 0\npartial"
    assert block.partials[0].tool_call_id == "call-1"
    assert block.result_output is None
    assert "call-1" in projector._tool_blocks


@pytest.mark.parametrize("event_name", [None, "read"])
async def test_partial_name_uses_event_then_existing_block(event_name: str | None) -> None:
    """Missing names retain known identity; explicit names update the same widget."""
    host = _PartialHost()
    projector = TranscriptProjectionAdapter(host=host)
    await projector.project(
        event=AgentStreamEventDAO(kind="tool_call_end", tool_call_id="known", tool_name="bash")
    )
    block = host.tool_blocks["known"]
    assert isinstance(block, _PartialRecordingToolBlock)
    await projector.project(
        event=AgentStreamEventDAO(
            kind="tool_output_update", tool_call_id="known", tool_name=event_name, content="partial"
        )
    )
    expected_name = event_name or "bash"
    assert block.partials[0].tool_name == expected_name
    assert block.tool_name == expected_name
    assert block._partial_output == "partial"
    assert block.result_output is None
    assert host.mount_order == ["tool"]


@pytest.mark.asyncio
async def test_early_partial_update_mounts_block_first() -> None:
    """An update arriving before normal mounting ensures the block exists."""
    host = _PartialHost()
    projector = TranscriptProjectionAdapter(host=host)

    await projector.project(
        event=AgentStreamEventDAO(
            kind="tool_output_update",
            tool_call_id="call-early",
            tool_name="bash",
            content="exit_code: 0\nearly",
        )
    )

    assert "call-early" in host.tool_blocks
    block = host.tool_blocks["call-early"]
    assert isinstance(block, _PartialRecordingToolBlock)
    assert block.partials[0].content_snapshot == "exit_code: 0\nearly"


@pytest.mark.asyncio
async def test_terminal_tool_result_supersedes_partial_and_pops_block() -> None:
    """Only the terminal branch pops; partial content never becomes the result."""
    host = _PartialHost()
    projector = TranscriptProjectionAdapter(host=host)
    await projector.project(
        event=AgentStreamEventDAO(kind="tool_call_end", tool_call_id="call-1", tool_name="bash")
    )
    await projector.project(
        event=AgentStreamEventDAO(
            kind="tool_output_update",
            tool_call_id="call-1",
            tool_name="bash",
            content="partial",
        )
    )
    block = host.tool_blocks["call-1"]

    await projector.project(
        event=AgentStreamEventDAO(
            kind="tool_result",
            tool_call_id="call-1",
            tool_name="bash",
            content="final output",
        )
    )

    assert block.result_output == "final output"
    assert "call-1" not in projector._tool_blocks


@pytest.mark.asyncio
async def test_partial_update_never_pops_block() -> None:
    """A stream of partials keeps the same single block mounted throughout."""
    host = _PartialHost()
    projector = TranscriptProjectionAdapter(host=host)

    for index in range(3):
        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_output_update",
                tool_call_id="call-1",
                tool_name="bash",
                content=f"snapshot {index}",
            )
        )

    assert len(projector._tool_blocks) == 1
    block = host.tool_blocks["call-1"]
    assert isinstance(block, _PartialRecordingToolBlock)
    assert len(block.partials) == 3
