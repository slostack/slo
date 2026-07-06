"""Tests for the ``bash`` tool (sub-spec 01.d §5.4)."""
import asyncio
import os
import time

import pytest

from src.agents.tools._truncate import DEFAULT_MAX_LINES
from src.agents.tools.bash import (
    BashTool,
    bash_tool,
    _bash_teardown_grace_seconds,
    _default_bash_timeout_seconds,
)
from pathlib import Path


@pytest.mark.asyncio
async def test_bash_echo() -> None:
    result = await bash_tool.ainvoke({"command": "echo hello"})
    assert "exit_code: 0" in result
    assert "hello" in result


@pytest.mark.asyncio
async def test_bash_nonzero_exit_surfaces() -> None:
    result = await bash_tool.ainvoke({"command": "false"})
    assert "exit_code: 1" in result


@pytest.mark.asyncio
async def test_bash_stderr_interleaved() -> None:
    result = await bash_tool.ainvoke({"command": "echo out; echo err >&2"})
    assert "out" in result and "err" in result


@pytest.mark.asyncio
async def test_bash_timeout() -> None:
    result = await bash_tool.ainvoke({"command": "sleep 5", "timeout": 0.1})
    assert "exceeded" in result and "timeout" in result


@pytest.mark.asyncio
async def test_bash_truncates_and_spills() -> None:
    """Produce more than DEFAULT_MAX_LINES lines so truncation + spill kick in."""
    cmd = f"python -c 'import sys\nfor i in range({DEFAULT_MAX_LINES + 100}): print(i)'"
    result = await bash_tool.ainvoke({"command": cmd})
    assert "[output truncated" in result
    assert "[full output spilled to:" in result
    spill = result.split("spilled to: ")[1].rstrip("]\n ")
    assert os.path.exists(spill)


def test_bash_tool_metadata() -> None:
    assert bash_tool.name == "bash"
    assert "Execute a bash command" in bash_tool.description


class TestDefaultBashTimeoutSeconds:
    """Branch coverage for the no-timeout default-ceiling resolver."""

    def test_unset_returns_600(self, monkeypatch) -> None:
        monkeypatch.delenv("SLO_BASH_DEFAULT_TIMEOUT_SECONDS", raising=False)
        assert _default_bash_timeout_seconds() == 600.0

    def test_disabled_with_zero_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv("SLO_BASH_DEFAULT_TIMEOUT_SECONDS", "0")
        assert _default_bash_timeout_seconds() is None

    def test_negative_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv("SLO_BASH_DEFAULT_TIMEOUT_SECONDS", "-5")
        assert _default_bash_timeout_seconds() is None

    def test_invalid_falls_back_to_600(self, monkeypatch) -> None:
        monkeypatch.setenv("SLO_BASH_DEFAULT_TIMEOUT_SECONDS", "oops")
        assert _default_bash_timeout_seconds() == 600.0

    def test_valid_positive_is_used(self, monkeypatch) -> None:
        monkeypatch.setenv("SLO_BASH_DEFAULT_TIMEOUT_SECONDS", "120")
        assert _default_bash_timeout_seconds() == 120.0


class TestBashTeardownGraceSeconds:
    """Branch coverage for the bounded teardown-grace resolver."""

    def test_unset_returns_5(self, monkeypatch) -> None:
        monkeypatch.delenv("SLO_BASH_TEARDOWN_GRACE_SECONDS", raising=False)
        assert _bash_teardown_grace_seconds() == 5.0

    def test_invalid_falls_back_to_5(self, monkeypatch) -> None:
        monkeypatch.setenv("SLO_BASH_TEARDOWN_GRACE_SECONDS", "nope")
        assert _bash_teardown_grace_seconds() == 5.0

    def test_nonpositive_falls_back_to_5(self, monkeypatch) -> None:
        monkeypatch.setenv("SLO_BASH_TEARDOWN_GRACE_SECONDS", "0")
        assert _bash_teardown_grace_seconds() == 5.0

    def test_valid_positive_is_used(self, monkeypatch) -> None:
        monkeypatch.setenv("SLO_BASH_TEARDOWN_GRACE_SECONDS", "2.5")
        assert _bash_teardown_grace_seconds() == 2.5


class TestResolveEffectiveTimeout:
    """Branch coverage for the effective-timeout resolver."""

    def test_uses_caller_value(self) -> None:
        assert BashTool._resolve_effective_timeout(timeout=5.0) == 5.0

    def test_falls_back_to_default(self, monkeypatch) -> None:
        monkeypatch.delenv("SLO_BASH_DEFAULT_TIMEOUT_SECONDS", raising=False)
        assert BashTool._resolve_effective_timeout(timeout=None) == 600.0

    def test_caller_zero_is_not_none(self) -> None:
        # A caller passing 0 means "0s timeout", not "use the ceiling".
        assert BashTool._resolve_effective_timeout(timeout=0) == 0


class TestBashProcessGroupTermination:
    """The marquee regression: an orphaned child holding the stdout pipe must
    not block teardown past the timeout + grace window."""

    @pytest.mark.asyncio
    async def test_bash_timeout_returns_promptly_when_child_holds_pipe(self) -> None:
        """A forked child that survives the shell and holds the stdout pipe must
        not block teardown. Before the fix this returned in ~30s (when the orphan
        died); after the process-group kill it returns at the timeout boundary.
        """
        start: float = time.monotonic()
        result: str = await bash_tool.ainvoke(
            {"command": "sleep 30 && echo done", "timeout": 1}
        )
        elapsed: float = time.monotonic() - start

        assert "exceeded" in result and "timeout" in result
        assert elapsed < 10, f"teardown blocked for {elapsed:.1f}s — orphan held the pipe"

    @pytest.mark.asyncio
    async def test_bash_kills_whole_process_group(self, tmp_path) -> None:
        """After a timeout, no member of the spawned process group survives.

        ``$$`` is bash's pid, which equals the session-leader pgid (because the
        tool spawns with ``start_new_session=True``). A single-pid kill would
        leave the forked ``sleep`` alive; the group kill removes the whole tree.
        """
        marker = tmp_path / "pgid.txt"
        result: str = await bash_tool.ainvoke(
            {"command": f"echo $$ > {marker}; sleep 30 && echo done", "timeout": 1}
        )
        assert "exceeded" in result
        pgid: int = int(marker.read_text().strip())

        deadline: float = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)            # signal 0 == existence probe
            except ProcessLookupError:
                break                          # whole group gone — success
            await asyncio.sleep(0.1)
        else:
            pytest.fail(f"process group {pgid} still had live members after teardown")
