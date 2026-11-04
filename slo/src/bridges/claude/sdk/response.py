"""Per-response native stream validation, before executable publication."""

import json
from dataclasses import asdict

from claude_agent_sdk import AssistantMessage, TextBlock, ThinkingBlock, ToolUseBlock
# Native JSON payloads and SDK dataclass serialization are heterogeneous at this boundary.
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .dao import ClaudeToolCallDAO
from .exceptions import ClaudeBridgeError


class NativeBlock(BaseModel):
    """Validated native block with bounded incremental input and completion state."""

    model_config = ConfigDict(extra="ignore")
    type: str
    id: str = ""
    name: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    text: str = ""
    thinking: str = ""
    signature: str = ""
    partial_json: str = ""
    stopped: bool = False

    def append(self, *, delta: dict[str, Any]) -> str:
        """Accept only deltas belonging to this still-open block."""
        if self.stopped or not isinstance(delta, dict):
            raise protocol_error()
        kind = delta.get("type")
        if self.type == "tool_use" and kind == "input_json_delta":
            fragment = delta.get("partial_json")
            if not isinstance(fragment, str):
                raise protocol_error()
            if len(self.partial_json.encode()) + len(fragment.encode()) > 1024 * 1024:
                raise ClaudeBridgeError(
                    code="buffer_limit_exceeded", safe_message="Claude tool input exceeded its limit."
                )
            self.partial_json += fragment
            return ""
        if self.type == "text" and kind == "text_delta":
            fragment = delta.get("text")
            if not isinstance(fragment, str):
                raise protocol_error()
            self.text += fragment
            return fragment
        if self.type == "thinking" and kind in {"thinking_delta", "signature_delta"}:
            field = "thinking" if kind == "thinking_delta" else "signature"
            fragment = delta.get(field)
            if not isinstance(fragment, str):
                raise protocol_error()
            setattr(self, field, getattr(self, field) + fragment)
            return ""
        raise protocol_error()

    def complete_call(self) -> ClaudeToolCallDAO:
        """Parse a complete object without repairing incomplete native JSON."""
        if not self.name.startswith("mcp__slo__"):
            raise protocol_error()
        try:
            arguments = json.loads(self.partial_json) if self.partial_json else self.input
            # Delta strings bypass admission's JSON check; validate decoded values,
            # including exponent overflow, independently of optional assistant echoes.
            json_identity(value=arguments)
            return ClaudeToolCallDAO(
                tool_call_id=self.id, name=self.name.removeprefix("mcp__slo__"), arguments=arguments
            )
        except (ValueError, ValidationError):
            raise protocol_error() from None


class NativeResponseAssembly:
    """Own native ordering and bounded response-scoped corroboration snapshots."""

    def __init__(self, *, max_retained_bytes: int = 32 * 1024 * 1024) -> None:
        """Create an empty assembly, not an implicit response boundary."""
        self._max_retained_bytes = max_retained_bytes
        self._admitted_bytes = 0
        self._native_session_id: str | None = None
        self.response_id = "response"
        self.text = ""
        self.calls: tuple[ClaudeToolCallDAO, ...] = ()
        self._blocks: dict[int, NativeBlock] = {}
        self._open = False
        self._stop_reason: str | None = None
        self._response_ids: set[str] = set()
        self._snapshots: dict[str, tuple[NativeBlock, ...]] = {}
        self._echoes: list[tuple[NativeBlock, ...]] = []
        self._fragment_ids: dict[str, tuple[str, str]] = {}

    def _admit(self, *, value: Any) -> None:
        """Bound invocation retention without evicting evidence needed for late echoes.

        Charge all input, including repeats, before retaining it. A conservative
        factor of four covers normalized snapshots, UUID keys, pending echoes
        and duplicated streamed text; fixed per-envelope charge bounds counts.
        This is a serialized-data budget, not an exact Python heap measurement.
        """
        cost = 256 + 4 * len(json_identity(value=value).encode())
        if self._admitted_bytes + cost > self._max_retained_bytes:
            raise ClaudeBridgeError(
                code="buffer_limit_exceeded",
                safe_message="Claude reconciliation limit exceeded.",
            )
        self._admitted_bytes += cost

    def validate_scope(self, *, session_id: str | None, parent_tool_use_id: str | None) -> None:
        """Bind the first supplied native session and require root messages.

        Missing session metadata remains compatible with older SDK messages; it
        neither establishes nor clears the binding. Host session IDs are unrelated.
        Any supplied parent (including empty string) is not the native root.
        """
        if parent_tool_use_id is not None:
            raise protocol_error()
        if session_id is None:
            return
        if not isinstance(session_id, str) or not 1 <= len(session_id) <= 256:
            raise protocol_error()
        if self._native_session_id is not None and session_id != self._native_session_id:
            raise protocol_error()
        self._native_session_id = session_id

    def consume(self, *, event: dict[str, Any]) -> tuple[str, bool]:
        """Return new text and a validated boundary; never return partial calls."""
        self._admit(value=event)
        kind = event.get("type")
        if kind == "message_start":
            self._start(event=event)
            return "", False
        if not self._open:
            raise protocol_error()
        if kind == "message_delta":
            if self._stop_reason is not None:
                raise protocol_error()
            delta = event.get("delta")
            if not isinstance(delta, dict) or not isinstance(delta.get("stop_reason"), str):
                raise protocol_error()
            self._stop_reason = delta["stop_reason"]
            return "", False
        if kind == "message_stop":
            self._complete()
            return "", True
        index = event.get("index")
        if not isinstance(index, int) or index < 0:
            raise protocol_error()
        if kind == "content_block_start":
            self._start_block(index=index, event=event)
            fragment = self._blocks[index].text if self._blocks[index].type == "text" else ""
            self.text += fragment
            return fragment, False
        block = self._blocks.get(index)
        if block is None or block.stopped:
            raise protocol_error()
        if kind == "content_block_stop":
            block.stopped = True
            return "", False
        if kind == "content_block_delta":
            fragment = block.append(delta=event.get("delta", {}))
            self.text += fragment
            if len(self.text.encode()) > 8 * 1024 * 1024:
                raise ClaudeBridgeError(
                    code="buffer_limit_exceeded", safe_message="Claude response exceeded its limit."
                )
            return fragment, False
        raise protocol_error()

    def _start(self, *, event: dict[str, Any]) -> None:
        """Reject overlap and reused response identities instead of discarding state."""
        identity = event.get("message", {}).get("id")
        if (
            self._open
            or not isinstance(identity, str)
            or not 1 <= len(identity) <= 256
            or identity in self._response_ids
        ):
            raise protocol_error()
        if len(self._response_ids) >= 10000:
            raise ClaudeBridgeError(
                code="buffer_limit_exceeded", safe_message="Claude response identity limit exceeded."
            )
        self._response_ids.add(identity)
        self.response_id = identity
        self.text = ""
        self.calls = ()
        self._blocks = {}
        self._echoes = []
        self._stop_reason = None
        self._open = True

    def _start_block(self, *, index: int, event: dict[str, Any]) -> None:
        """Preserve source order and prevent duplicate or overlapping blocks."""
        if index != len(self._blocks) or any(not b.stopped for b in self._blocks.values()):
            raise protocol_error()
        raw = event.get("content_block")
        if not isinstance(raw, dict) or {"stopped", "partial_json"}.intersection(raw):
            raise protocol_error()
        try:
            block = NativeBlock.model_validate(raw)
        except ValidationError:
            raise protocol_error() from None
        if block.type not in {"text", "tool_use", "thinking"}:
            raise protocol_error()
        self._blocks[index] = block

    def _complete(self) -> None:
        """Commit calls only for a complete, nontruncated tool-use response."""
        if any(not b.stopped for b in self._blocks.values()):
            raise protocol_error()
        tools = [b for b in self._blocks.values() if b.type == "tool_use"]
        if tools and self._stop_reason != "tool_use":
            raise protocol_error()
        if not tools and self._stop_reason not in {None, "end_turn", "stop_sequence", "max_tokens"}:
            raise protocol_error()
        calls = tuple(b.complete_call() for b in tools)
        if len({call.tool_call_id for call in calls}) != len(calls):
            raise protocol_error()
        snapshot = tuple(self._blocks.values())
        for echo in self._echoes:
            self._validate_fragment(fragment=echo, snapshot=snapshot)
        self._snapshots[self.response_id] = snapshot
        self.calls = calls
        self._open = False

    def validate_terminal(self) -> None:
        """No successful terminal result may conceal an unfinished response."""
        if self._open:
            raise protocol_error()

    def reconcile_echo(self, *, message: AssistantMessage) -> None:
        """Validate a response-scoped fragment without publishing its content.

        The SDK preserves message_id (response identity) and uuid (delivery
        identity). Missing IDs in older SDK-shaped callers bind only to the
        current response. Open responses defer content comparison to message_stop.

        Args:
            message (AssistantMessage): Native fragment from the SDK parser.

        Raises:
            ClaudeBridgeError: Unknown identity, conflicting replay or content.
        """
        self._admit(value=asdict(message))
        self.validate_scope(
            session_id=message.session_id, parent_tool_use_id=message.parent_tool_use_id
        )
        identity = message.message_id
        if identity is not None and not isinstance(identity, str):
            raise protocol_error()
        if identity is None or identity == "":
            identity = self.response_id
        if identity not in self._response_ids or message.parent_tool_use_id or message.error:
            raise protocol_error()
        fragment = tuple(self._echo_block(block=block) for block in message.content)
        fragment_key = json_identity(value=[b.model_dump() for b in fragment])
        if message.uuid:
            previous = self._fragment_ids.get(message.uuid)
            if previous is not None and previous != (identity, fragment_key):
                raise protocol_error()
            self._fragment_ids[message.uuid] = (identity, fragment_key)
        if identity == self.response_id and self._open:
            if not any(
                json_identity(value=[b.model_dump() for b in echo]) == fragment_key
                for echo in self._echoes
            ):
                self._echoes.append(fragment)
            return
        self._validate_fragment(fragment=fragment, snapshot=self._snapshots[identity])

    @staticmethod
    def _echo_block(*, block: object) -> NativeBlock:
        """Normalize supported SDK blocks while preserving kind and tool identity."""
        kinds = {TextBlock: "text", ThinkingBlock: "thinking", ToolUseBlock: "tool_use"}
        kind = kinds.get(type(block))
        if kind is None:
            raise protocol_error()
        try:
            return NativeBlock.model_validate({"type": kind, **asdict(block)})
        except (ValidationError, TypeError):
            raise protocol_error() from None

    @staticmethod
    def _validate_fragment(
        *, fragment: tuple[NativeBlock, ...], snapshot: tuple[NativeBlock, ...]
    ) -> None:
        """Require an ordered subset of complete blocks, not flattened response text.

        Echoes are corroboration only: repeated identical blocks never append
        output. Tool IDs and exact payloads distinguish otherwise identical calls.
        """
        remaining = iter(snapshot)
        for echoed in fragment:
            if not any(
                NativeResponseAssembly._same_block(echoed=echoed, streamed=block)
                for block in remaining
            ):
                raise protocol_error()

    @staticmethod
    def _same_block(*, echoed: NativeBlock, streamed: NativeBlock) -> bool:
        """Compare semantic payloads independently of stream completion bookkeeping."""
        if echoed.type != streamed.type:
            return False
        if echoed.type == "tool_use":
            return json_identity(value=echoed.complete_call().model_dump()) == json_identity(
                value=streamed.complete_call().model_dump()
            )
        if echoed.type == "text":
            return echoed.text == streamed.text
        return echoed.thinking == streamed.thinking and echoed.signature == streamed.signature


def protocol_error() -> ClaudeBridgeError:
    """Return a bounded, payload-free protocol failure."""
    return ClaudeBridgeError(
        code="stream_protocol_failed", safe_message="Malformed or unfinished Claude response."
    )


def json_identity(*, value: Any) -> str:
    """Encode JSON types unambiguously for payload and replay comparison.

    Object key order is irrelevant; arrays remain ordered. Booleans never
    compare equal to numbers. Numeric representation is deliberately exact.
    """
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise protocol_error() from None
