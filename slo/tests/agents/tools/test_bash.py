"""Tests for the ``bash`` tool (sub-spec 01.d §5.4)."""

import asyncio
import os
import shlex
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.agents.tools import bash as bash_module
from src.agents.tools._blocking import run_blocking_tool_call
from src.agents.tools._truncate import DEFAULT_MAX_LINES
from src.agents.tools.bash import (
    BashTool,
    bash_tool,
    _bash_teardown_grace_seconds,
    _default_bash_timeout_seconds,
)


def _assert_resolved_tmp_path_descendant(*, candidate: Path, tmp_path: Path) -> Path:
    """Return ``candidate`` only when resolving it cannot escape ``tmp_path``.

    Args:
        candidate (Path): Fixture path to validate before a test writes to it.
        tmp_path (Path): Pytest-owned root that contains every fixture write.

    Returns:
        Path: The resolved candidate when it is safely contained by ``tmp_path``.

    Raises:
        AssertionError: If resolving the candidate follows a symlink outside the
            pytest-owned root.
    """
    resolved_tmp_path: Path = tmp_path.resolve(strict=True)
    resolved_candidate: Path = candidate.resolve(strict=False)
    assert resolved_candidate.is_relative_to(
        resolved_tmp_path
    ), f"unsafe fixture path {resolved_candidate} escapes {resolved_tmp_path}"
    return resolved_candidate


def test_resolved_tmp_path_descendant_rejects_symlink_escape(tmp_path: Path) -> None:
    """Reject a fixture path whose symlink target escapes its pytest root."""
    escape_link: Path = tmp_path / "escape"
    _assert_resolved_tmp_path_descendant(candidate=escape_link, tmp_path=tmp_path)
    escape_link.symlink_to(tmp_path.parent, target_is_directory=True)

    with pytest.raises(AssertionError, match="escapes"):
        _assert_resolved_tmp_path_descendant(
            candidate=escape_link / "spill.txt",
            tmp_path=tmp_path,
        )


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
async def test_bash_truncates_and_spills(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Spill truncated Bash output into an ancestry-checked pytest-owned root.

    The test replaces only the tempfile allocator while retaining production
    formatting, truncation, and full-output writing through ``os.fdopen``.

    Args:
        monkeypatch (pytest.MonkeyPatch): Scopes the tempfile allocator seam to this test.
        tmp_path (Path): Pytest-owned root for the spill file.
    """
    spill_root: Path = _assert_resolved_tmp_path_descendant(
        candidate=tmp_path / "bash-spills",
        tmp_path=tmp_path,
    )
    spill_root.mkdir()

    def allocate_owned_spill(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
        text: bool = False,
    ) -> tuple[int, str]:
        """Allocate one real spill file after proving its resolved ancestry."""
        assert dir is None
        assert text is True
        target: Path = _assert_resolved_tmp_path_descendant(
            candidate=spill_root / f"{prefix}full-output{suffix}",
            tmp_path=tmp_path,
        )
        file_descriptor: int = os.open(
            target,
            os.O_CREAT | os.O_EXCL | os.O_RDWR,
            0o600,
        )
        return file_descriptor, str(target)

    monkeypatch.setattr(bash_module.tempfile, "mkstemp", allocate_owned_spill)
    command: str = (
        f"{shlex.quote(sys.executable)} -c "
        f"{shlex.quote(f'for i in range({DEFAULT_MAX_LINES + 100}): print(i)')}"
    )

    result: str = await bash_tool.ainvoke({"command": command})

    assert "[output truncated" in result
    assert "[full output spilled to:" in result
    spill_path: Path = Path(result.split("spilled to: ")[1].rstrip("]\n "))
    assert _assert_resolved_tmp_path_descendant(candidate=spill_path, tmp_path=tmp_path) == spill_path
    assert spill_path.exists()
    assert spill_path.read_text(encoding="utf-8").startswith("exit_code: 0\n0\n")


def test_bash_tool_metadata() -> None:
    assert bash_tool.name == "bash"
    assert "Execute a bash command" in bash_tool.description


@pytest.mark.asyncio
async def test_format_result_runs_through_blocking_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful invoke offloads ``_format_result`` through ``run_blocking_tool_call``.

    The mock delegates to the real gateway so result formatting still really
    runs; the assertion proves the offload seam rather than re-testing output.

    Args:
        monkeypatch (pytest.MonkeyPatch): Patches the bash module's gateway seam.
    """
    gateway_mock: AsyncMock = AsyncMock(side_effect=run_blocking_tool_call)
    monkeypatch.setattr(
        target=bash_module,
        name="run_blocking_tool_call",
        value=gateway_mock,
    )

    result: str = await BashTool.invoke(command="echo gateway-routed")

    gateway_mock.assert_awaited_once()
    call = gateway_mock.await_args
    assert call is not None
    assert call.kwargs["func"] == BashTool._format_result
    assert call.kwargs["process"].returncode == 0
    assert b"gateway-routed" in call.kwargs["stdout_bytes"]
    assert "exit_code: 0" in result
    assert "gateway-routed" in result


class TestDefaultBashTimeoutSeconds:
    """Branch coverage for the no-timeout default-ceiling resolver."""

    def test_unset_returns_1800(self, monkeypatch) -> None:
        monkeypatch.delenv("SLO_BASH_DEFAULT_TIMEOUT_SECONDS", raising=False)
        assert _default_bash_timeout_seconds() == 1800.0

    def test_disabled_with_zero_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv("SLO_BASH_DEFAULT_TIMEOUT_SECONDS", "0")
        assert _default_bash_timeout_seconds() is None

    def test_negative_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv("SLO_BASH_DEFAULT_TIMEOUT_SECONDS", "-5")
        assert _default_bash_timeout_seconds() is None

    def test_invalid_falls_back_to_1800(self, monkeypatch) -> None:
        monkeypatch.setenv("SLO_BASH_DEFAULT_TIMEOUT_SECONDS", "oops")
        assert _default_bash_timeout_seconds() == 1800.0

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
        assert BashTool._resolve_effective_timeout(timeout=None) == 1800.0

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
        result: str = await bash_tool.ainvoke({"command": "sleep 30 && echo done", "timeout": 1})
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
                os.killpg(pgid, 0)  # signal 0 == existence probe
            except ProcessLookupError:
                break  # whole group gone — success
            await asyncio.sleep(0.1)
        else:
            pytest.fail(f"process group {pgid} still had live members after teardown")
