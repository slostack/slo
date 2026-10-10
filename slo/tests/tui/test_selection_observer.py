"""Finite tests for TEMP observer storage and pass/failure-neutral serialization."""

import json
from types import SimpleNamespace
from typing import cast
from types import FrameType

import pytest
from textual.errors import NoWidget
from textual.geometry import Offset, Region

from tests.tui.selection_observer import SelectionObserver


def test_observer_retains_bounded_tail_and_reports_drops() -> None:
    """Overflow cannot grow memory; the sequence identifies exactly the lost prefix."""
    observer = SelectionObserver()
    for index in range(observer.LIMIT + 3):
        observer.append(event="fixture", fields={"x": index})
    result = json.loads(observer.serialize())
    assert len(result["records"]) == observer.LIMIT
    assert result["dropped"] == 3
    assert result["records"][0]["sequence"] == 4
    assert result["records"][-1]["x"] == observer.LIMIT + 2


@pytest.mark.parametrize(
    "name,filename,wanted",
    [
        ("scroll_visible", "/textual/widget.py", True),
        ("scroll_visible", "/unrelated.py", False),
        ("unrelated", "/textual/widget.py", False),
        ("post_message", "/textual/message_pump.py", False),
        ("call_after_refresh", "/textual/message_pump.py", False),
    ],
)
def test_observer_filters_unrelated_frames(name: str, filename: str, wanted: bool) -> None:
    """Only audited framework seams may enter the diagnostic buffer."""
    frame = cast(
        FrameType, SimpleNamespace(f_code=SimpleNamespace(co_name=name, co_filename=filename), f_locals={})
    )
    assert SelectionObserver._wanted(frame=frame, name=name) is wanted
    observer = SelectionObserver()
    observer.profile(frame=frame, event="c_call", arg=None)
    assert observer.total == 0


def test_observer_failure_geometry_preserves_missing_widget() -> None:
    """An off-screen cell does not turn observation into a new test exception."""

    def missing(*, x: int, y: int) -> None:
        """Model Textual's missing-cell result without rendering content."""
        raise NoWidget()

    frame = cast(
        FrameType,
        SimpleNamespace(
            f_locals={
                "body": SimpleNamespace(region=Region(x=3, y=-8, width=72, height=1)),
                "app": SimpleNamespace(screen=SimpleNamespace(get_widget_and_offset_at=missing)),
                "target": Offset(x=6, y=0),
            }
        ),
    )
    assert SelectionObserver()._hit_geometry(frame=frame, result=None) == {
        "target": [6, 0],
        "cell": [9, -8],
        "hit_owner": "NoWidget",
    }


def test_empty_observer_has_no_drops_or_application_state() -> None:
    """Serialization exposes only the finite schema, not environment or instance state."""
    result = json.loads(SelectionObserver().serialize())
    assert result["records"] == []
    assert result["dropped"] == 0
    assert set(result) == {"schema", "python", "system", "kernel", "machine", "total", "dropped", "records"}
