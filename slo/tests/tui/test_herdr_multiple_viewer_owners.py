"""Actual app workers share one admitted CLI and one queued viewer reservation."""

import asyncio
from pathlib import Path

import pytest

from src.tui.app import SloTUI
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_herdr_activation_composed import native_factory
from tests.tui.test_herdr_viewer_retention_composed import exercise_retained_viewer


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("cancel_replacement", [False, True])
@pytest.mark.parametrize("registry_fault", [False, True])
async def test_multiple_registered_viewers_survive_first_join_fault(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: object,
    monkeypatch: pytest.MonkeyPatch,
    persistent: bool,
    cancel_replacement: bool,
    registry_fault: bool,
) -> None:
    """First registry join failure cannot skip the real queued worker or retained drain."""
    notices: list[str] = []
    original_write = SloTUI._write_adapter_line

    def write(app: SloTUI, *, content: str, classes: str) -> None:
        """Fail the real diagnostic sink after the original registry join fault."""
        if registry_fault and content == "Viewer cleanup incomplete.":
            notices.append(content)
            raise RuntimeError("synthetic diagnostic sink fault")
        original_write(app, content=content, classes=classes)

    monkeypatch.setattr(target=SloTUI, name="_write_adapter_line", value=write)
    operation = exercise_retained_viewer(
        root=tmp_path,
        fake=fake_herdr,
        monkeypatch=monkeypatch,
        persistent=persistent,
        multiple_workers=True,
        cancel_replacement=cancel_replacement,
        registry_fault=registry_fault,
    )
    if persistent:
        with pytest.raises(asyncio.CancelledError):
            await operation
    else:
        await operation
    assert notices == (["Viewer cleanup incomplete."] if registry_fault else [])
