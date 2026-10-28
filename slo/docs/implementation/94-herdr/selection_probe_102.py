"""Test-only observational scroll receipt plugin; no production mutation on disk."""

from __future__ import annotations

import functools
import traceback
from collections.abc import Callable

import pytest
from textual._callback import invoke
from textual.message_pump import MessagePump
from textual.widget import Widget

from src.tui.app import SloTUI


def pytest_addoption(parser: pytest.Parser) -> None:
    """Select observational or explicitly ordered experiment."""
    parser.addoption("--selection-order", default="observe", choices=("observe", "red"))


@pytest.fixture(autouse=True)
def selection_trace(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Record real scroll scheduling/execution without changing their ordering."""
    if "paint_and_scroll_remain_native" not in request.node.name:
        return
    records: list[str] = []
    sequence = 0
    held: list[tuple[MessagePump, Callable]] = []
    released = request.config.getoption("--selection-order") != "red"

    def state(owner: object) -> str:
        """Capture viewport and every mounted target's actual and virtual regions."""
        app = owner if isinstance(owner, SloTUI) else getattr(owner, "app", None)
        if not isinstance(app, SloTUI) or app._transcript_scroll is None:
            return ""
        scroll = app._transcript_scroll
        bodies = [
            w
            for w in app.screen.walk_children()
            if type(w).__name__ in {"AssistantAnswerBody", "AssistantThinkingBody", "UserMessageBody"}
        ]
        return str(
            (
                scroll.scroll_y,
                scroll.max_scroll_y,
                scroll.virtual_size,
                scroll.scrollable_content_region,
                app._force_following_until_layout,
                [(type(w).__name__, w.region, w.virtual_region, w.parent.virtual_region) for w in bodies],
            )
        )

    def record(label: str, owner: object) -> None:
        """Append an ordered in-memory snapshot, printed only at teardown."""
        records.append(f"{len(records):04d} {label} {state(owner)}")

    original_after = MessagePump.call_after_refresh

    def after(owner: MessagePump, callback: Callable, *args: object, **kwargs: object) -> bool:
        """Wrap original callbacks with their scheduling identity and causal source."""
        nonlocal sequence, released
        name = getattr(callback, "__qualname__", repr(callback))
        if not any(token in name for token in ("scroll", "following", "_pin_transcript")):
            return original_after(owner, callback, *args, **kwargs)
        sequence += 1
        identifier = sequence
        source = " > ".join(f"{f.name}:{f.lineno}" for f in traceback.extract_stack(limit=5)[:-1])
        record(f"QUEUE {identifier} {name} {args} {kwargs} FROM {source}", owner)

        async def execute() -> None:
            """Run exactly the queued callback with its original arguments."""
            nonlocal released
            record(f"BEGIN {identifier} {name}", owner)
            await invoke(functools.partial(callback, *args, **kwargs))
            record(f"END {identifier} {name}", owner)
            if name == "Widget._scroll_to" and not released:
                released = True
                assert held, "Controlled RED requires original pending follow callbacks"
                record(f"RELEASE {len(held)} original follow callbacks AFTER reveal", owner)
                for pump, pending in held:
                    original_after(pump, pending)
                held.clear()

        if "_pin_transcript_to_end_after_refresh" in name and not released:
            held.append((owner, execute))
            record(f"HOLD {identifier}", owner)
            return True
        return original_after(owner, execute)

    monkeypatch.setattr(MessagePump, "call_after_refresh", after)

    def observe(cls: type, name: str) -> None:
        """Record synchronous real methods before and after delegation."""
        original = getattr(cls, name)

        @functools.wraps(original)
        def wrapped(owner: object, *args: object, **kwargs: object) -> object:
            record(f"CALL {name} {args} {kwargs}", owner)
            result = original(owner, *args, **kwargs)
            record(f"RETURN {name} {result}", owner)
            return result

        monkeypatch.setattr(cls, name, wrapped)

    for name in ("scroll_visible", "scroll_to_widget", "scroll_to_region", "_scroll_to"):
        observe(Widget, name)
    observe(SloTUI, "on_assistant_stream_block_rendered")
    request.addfinalizer(lambda: print("\nTRACE " + request.node.name + "\n" + "\n".join(records)))
