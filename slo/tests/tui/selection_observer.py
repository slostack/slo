"""TEMP MR116 observer: bounded geometry only; never reschedule Textual work.

Enabled only for the exact failing case by the test fixture. Profile callbacks
observe original calls/returns (including deferred closures), not replacement
messages or timers. Profiling has overhead, so a passing capture is not a fix.
The existing JUnit report carries the trace on success as well as failure.
"""

from __future__ import annotations

from src.tui.components.chat_transcript.component import ChatTranscript
import json
import platform
from time import monotonic_ns
from collections import deque
from types import FrameType
from typing import TYPE_CHECKING, Optional, cast

from textual.errors import NoWidget
from textual.widget import Widget

if TYPE_CHECKING:
    from src.tui.app import SloTUI


class SelectionObserver:
    """Keep a finite allowlisted call ledger for one natural Pilot execution."""

    LIMIT = 2048
    METHODS = frozenset(
        {
            "_flush_dirty_regions",
            "on_assistant_stream_block_rendered",
            "_scroll_transcript_to_end",
            "_pin_transcript_to_end_after_refresh",
            "_clear_force_following_after_scroll_end",
            "scroll_visible",
            "scroll_to_widget",
            "_lazily_scroll_end",
            "_scroll_to",
            "watch_scroll_y",
            "_location_for_offset",
        }
    )

    def __init__(self) -> None:
        """Allocate bounded memory before the target test; retain no text or credentials."""
        self.records: deque[dict[str, object]] = deque(maxlen=self.LIMIT)
        self.total = 0
        self.app: Optional[SloTUI] = None
        self.body: Optional[Widget] = None
        self.started = monotonic_ns()

    def profile(self, frame: FrameType, event: str, arg: object) -> None:
        """Observe allowlisted Python calls/returns without touching queues or callbacks.

        CPython calls this synchronously on the test thread; no locals are dumped.
        Original exceptions and return values remain untouched.
        """
        if event not in {"call", "return"}:
            return
        name = frame.f_code.co_name
        if not self._wanted(frame=frame, name=name):
            return
        self._capture_owners(frame=frame)
        fields = self._geometry()
        fields.update(self._message_fields(frame=frame))
        fields["owner"] = type(frame.f_locals.get("self")).__name__
        if name in {"post_message", "scroll_to_widget", "call_after_refresh"} and event == "return":
            fields["accepted"] = arg if isinstance(arg, bool) else None
        if name == "_location_for_offset":
            fields.update(self._hit_geometry(frame=frame, result=arg))
        self.append(event=f"{name}:{event}", fields=fields)

    @classmethod
    def _wanted(cls, *, frame: FrameType, name: str) -> bool:
        """Reject unrelated modules and message payloads before reading observer fields."""
        filename = frame.f_code.co_filename.replace("\\", "/")
        if not filename.endswith(
            (
                "/textual/widget.py",
                "/textual/message_pump.py",
                "/tui/app.py",
                "/widgets/assistant_stream_block.py",
                "/test_selection_scroll_highlight.py",
            )
        ):
            return False
        if name in {"post_message", "_dispatch_message"}:
            message = frame.f_locals.get("message")
            return type(message).__qualname__ == "AssistantStreamBlock.Rendered"
        if name == "call_after_refresh":
            callback = frame.f_locals.get("callback")
            return getattr(callback, "__name__", "") in cls.METHODS
        return name in cls.METHODS

    def _capture_owners(self, *, frame: FrameType) -> None:
        """Retain only app/body references during the bounded test, never session state."""
        owner = frame.f_locals.get("self")
        if type(owner).__name__ == "SloTUI":
            self.app = cast("SloTUI", owner)
        if type(owner).__name__ == "AssistantStreamBlock":
            self.body = cast(Widget, frame.f_locals["self"]._answer_body)
        if frame.f_code.co_name == "_location_for_offset":
            self.app = frame.f_locals["app"]
            self.body = frame.f_locals["body"]

    @staticmethod
    def _message_fields(*, frame: FrameType) -> dict[str, object]:
        """Correlate natural Rendered propagation using numeric identity and follow intent."""
        message = frame.f_locals.get("message", frame.f_locals.get("event"))
        if type(message).__qualname__ == "AssistantStreamBlock.Rendered":
            assert message is not None
            return {"message_id": id(message), "was_following": message.was_following}
        callback = frame.f_locals.get("callback")
        name = getattr(callback, "__name__", "")
        return {"callback": name} if name in SelectionObserver.METHODS else {}

    def _hit_geometry(self, *, frame: FrameType, result: object) -> dict[str, object]:
        """Sample the requested cell's native owner without storing rendered text."""
        body = frame.f_locals["body"]
        app = frame.f_locals["app"]
        target = frame.f_locals["target"]
        x, y = body.region.x + target.x, body.region.y + target.y
        try:
            widget, offset = app.screen.get_widget_and_offset_at(x=x, y=y)
        except NoWidget:
            return {"target": list(target), "cell": [x, y], "hit_owner": "NoWidget"}
        return {
            "target": list(target),
            "cell": [x, y],
            "hit_owner": type(widget).__name__,
            "hit_is_body": widget is body,
            "hit_offset": list(offset) if offset is not None else None,
            "found": list(result) if isinstance(result, tuple) else None,
        }

    def _geometry(self) -> dict[str, object]:
        """Read numeric viewport/latch/body state only; do not render or refresh."""
        if self.app is None:
            return {}
        scroll = self.app.query_one(ChatTranscript)._transcript_scroll
        fields: dict[str, object] = {
            "latch": self.app.query_one(ChatTranscript)._force_following_until_layout,
            "size": list(self.app.size),
        }
        if scroll is not None:
            fields.update(
                scroll_y=scroll.scroll_y,
                max_scroll_y=scroll.max_scroll_y,
                scroll_target_y=scroll.scroll_target_y,
                viewport=list(scroll.region),
            )
        if self.body is not None:
            fields["body_region"] = list(self.body.region)
        return fields

    def append(self, *, event: str, fields: dict[str, object]) -> None:
        """Append observer-owned numeric geometry; callers must not supply application text."""
        self.total += 1
        self.records.append(
            {"sequence": self.total, "elapsed_ns": monotonic_ns() - self.started, "event": event, **fields}
        )

    def serialize(self) -> str:
        """Build content-free JUnit evidence after profiling stops, on either outcome."""
        return json.dumps(
            {
                "schema": 1,
                "python": platform.python_version(),
                "system": platform.system(),
                "kernel": platform.release()[:128],
                "machine": platform.machine(),
                "total": self.total,
                "dropped": max(0, self.total - self.LIMIT),
                "records": list(self.records),
            },
            separators=(",", ":"),
        )
