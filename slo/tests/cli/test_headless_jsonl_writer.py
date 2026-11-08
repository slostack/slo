"""Borrowed JSONL stream mechanics, independent of runner credential policy."""

from io import StringIO

import pytest

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.cli import headless


class RecordingStream(StringIO):
    """Record stream effects and optionally fail one operation."""

    def __init__(self, *, failure: str = "") -> None:
        """Create a disposable stream; failure selects write or flush."""
        super().__init__()
        self.operations: list[str] = []
        self.failure: str = failure

    def write(self, text: str, /) -> int:
        """Record the attempted write before optionally rejecting it."""
        self.operations.append("write")
        if self.failure == "write":
            raise OSError("write failed")
        return super().write(text)

    def flush(self) -> None:
        """Record flush without closing the borrowed stream."""
        self.operations.append("flush")
        if self.failure == "flush":
            raise OSError("flush failed")
        super().flush()


def test_jsonl_writer_preserves_bytes_and_borrowed_stream() -> None:
    """An already-redacted event becomes exactly one line and one flush."""
    event: AgentStreamEventDAO = AgentStreamEventDAO(kind="text_delta", delta="[REDACTED]\nnext")
    stream: RecordingStream = RecordingStream()
    headless._HeadlessJSONLWriter.write(event=event, stream=stream)
    assert stream.getvalue() == event.model_dump_json() + "\n"
    assert stream.operations == ["write", "flush"]
    assert not stream.closed
    stream.write("still borrowed")


@pytest.mark.parametrize("failure", ["write", "flush"])
def test_jsonl_failure_propagates_without_retry_or_close(failure: str) -> None:
    """Failed output cannot be retried or silently treated as delivered."""
    stream: RecordingStream = RecordingStream(failure=failure)
    with pytest.raises(OSError, match=f"{failure} failed"):
        headless._HeadlessJSONLWriter.write(event=AgentStreamEventDAO(kind="run_completed"), stream=stream)
    assert stream.operations == (["write"] if failure == "write" else ["write", "flush"])
    assert not stream.closed
